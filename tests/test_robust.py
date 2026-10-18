"""Tests for the method ladders (scripts/robust.sh), the watchdog's signal handling, and the detached-job
supervisor (scripts/bg_ensure.sh)."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest


def dry_run(repo_root: Path, tmp_path: Path, *args: str) -> list[str]:
    env = {**os.environ, "ATH_ROBUST_DRY_RUN": "1", "ATH_SHARED": str(tmp_path / "shared")}
    result = subprocess.run(["bash", str(repo_root / "scripts" / "robust.sh"), *args], capture_output=True, text=True,
                            env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    words = shlex.split(result.stdout)
    assert words[:2] == ["bash", "scripts/watchdog.sh"]
    return words[2:]


def values(words: list[str], flag: str) -> list[str]:
    return [words[k + 1] for k, w in enumerate(words) if w == flag]


def test_build_ladder_pulls_then_drops_the_cache(repo_root, tmp_path):
    words = dry_run(repo_root, tmp_path, "build", "--tag", "ath-sim:" + "a" * 40)
    assert values(words, "--method") == [
        f"bash scripts/build_image.sh --tag ath-sim:{'a' * 40} ",
        f"ATH_BUILD_PULL=1 bash scripts/build_image.sh --tag ath-sim:{'a' * 40} ",
        f"ATH_BUILD_NO_CACHE=1 bash scripts/build_image.sh --tag ath-sim:{'a' * 40} "]
    assert "--retry-on-failure" in words and f"ath-sim:{'a' * 40}" in values(words, "--complete")[0]


def test_unit_ladder_splits_the_ros_tests_and_checks_fresh_coverage(repo_root, tmp_path):
    words = dry_run(repo_root, tmp_path, "unit")
    assert values(words, "--method") == ["bash scripts/test_unit.sh ", "ATH_TEST_SPLIT=1 bash scripts/test_unit.sh "]
    assert "--retry-on-failure" not in words and "runs/coverage.json" in values(words, "--complete")[0]


def test_suite_ladder_switches_render_method_and_keeps_earlier_attempts(repo_root, tmp_path):
    out = tmp_path / "out"
    words = dry_run(repo_root, tmp_path, "suite", "smoke", "--image", "ath-sim:x", "--out", str(out),
                    "--fail-on", "failures")
    methods = values(words, "--method")
    assert len(methods) == 3 and values(words, "--progress") == [str(out)]
    assert methods[0].endswith(f"bash scripts/run_suite.sh smoke --image ath-sim:x --out {out} --fail-on failures ")
    assert "ATH_RENDER_MODE=xvfb bash scripts/run_suite.sh" in methods[1]
    assert "ATH_RENDER_MODE=egl bash scripts/run_suite.sh" in methods[2]
    default = dry_run(repo_root, tmp_path, "suite", "full")
    progress = values(default, "--progress")[0]
    assert progress.startswith(str(tmp_path / "shared" / "runs" / "full-")) and "57600" in default
    assert f"--out {progress}" in values(default, "--method")[0]

    # Run the ladder with a stand-in for run_suite.sh: EGL crashes after writing part of its output, Xvfb works.
    fake = tmp_path / "fake_suite.sh"
    fake.write_text('out="${@: -3:1}"; mkdir -p "$out/runs"; echo "mode=${ATH_RENDER_MODE:-egl}" > "$out/mode"\n'
                    '[ "${ATH_RENDER_MODE:-egl}" = xvfb ] || kill -9 $$\n'
                    'echo "{}" > "$out/suite.json"; echo "<testsuites/>" > "$out/junit.xml"\n')
    ladder = [w.replace("bash scripts/run_suite.sh", f"bash {fake}") if w in methods else w for w in words]
    env = {**os.environ, "ATH_WATCHDOG_LOGS": str(tmp_path / "logs"), "ATH_BLOCKERS_FILE": str(tmp_path / "B.md")}
    result = subprocess.run(["bash", str(repo_root / "scripts" / "watchdog.sh"), *ladder, "--poll", "1"],
                            capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / "mode").read_text() == "mode=xvfb\n" and (out / "suite.json").exists()
    assert (Path(f"{out}.attempt1") / "mode").read_text() == "mode=egl\n"
    lines = (tmp_path / "logs").glob("*.attempts.jsonl")
    assert [json.loads(x)["outcome"] for x in next(lines).read_text().splitlines()] == ["CRASHED", "PASS"]


def test_experiment_gate_and_jenkins_ladders(repo_root, tmp_path):
    experiment = values(dry_run(repo_root, tmp_path, "experiment"), "--method")
    assert experiment == ["bash scripts/run_experiment.sh"] * 2 + ["ATH_RENDER_MODE=xvfb bash scripts/run_experiment.sh"]
    gate = dry_run(repo_root, tmp_path, "gate", "m2")
    assert values(gate, "--method") == ["bash scripts/verify_m2.sh"] and values(gate, "--attempts") == ["2"]
    commit = "c" * 40
    jenkins = dry_run(repo_root, tmp_path, "jenkins-build", commit)
    methods = values(jenkins, "--method")
    assert methods[0] == f"bash scripts/jenkins_wait_build.sh {commit} 3600"
    assert "jenkins_up.sh && bash scripts/jenkins_trigger.sh &&" in methods[1]
    assert "jenkins_trigger.sh --stop-running &&" in methods[2] and "--retry-on-failure" in jenkins
    for step in ("m0", "render-check"):
        assert values(dry_run(repo_root, tmp_path, step), "--attempts") == ["2"]


@pytest.mark.parametrize("args", [[], ["nope"], ["gate", "m9"], ["jenkins-build", "abc"], ["suite"]])
def test_robust_usage_errors(repo_root, args):
    result = subprocess.run(["bash", str(repo_root / "scripts" / "robust.sh"), *args], capture_output=True, text=True,
                            env={**os.environ, "ATH_ROBUST_DRY_RUN": "1"}, timeout=60)
    assert result.returncode == 2


def gone(pid: int) -> bool:
    """True once ``pid`` has exited (a zombie counts: in a container without an init, nobody may reap it)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return True
    return state in ("Z", "X")


def wait_for(predicate, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "condition not met in time"
        time.sleep(0.2)


def test_a_signal_to_the_watchdog_stops_the_running_attempt(repo_root, tmp_path):
    pid_file = tmp_path / "pid"
    env = {**os.environ, "ATH_WATCHDOG_LOGS": str(tmp_path / "logs")}
    proc = subprocess.Popen(["bash", str(repo_root / "scripts" / "watchdog.sh"), "--name", "sig", "--poll", "1",
                             "--method", f"echo $$ > {pid_file}; sleep 300"], env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: pid_file.exists() and pid_file.read_text().strip())
    attempt = int(pid_file.read_text())
    os.killpg(proc.pid, signal.SIGTERM)  # what bg_ensure.sh does to a stalled job's group
    assert proc.wait(timeout=60) == 143
    wait_for(lambda: gone(attempt), 20)


# --------------------------------------------------------------------------- bg_ensure.sh
@pytest.fixture
def job(repo_root, tmp_path):
    name = f"pytest-bg-{uuid.uuid4().hex[:8]}"
    logs = repo_root / "runs" / "logs"
    env = {**os.environ, "ATH_BLOCKERS_FILE": str(tmp_path / "BLOCKERS.md")}

    def ensure(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(repo_root / "scripts" / "bg_ensure.sh"), name, *args], capture_output=True,
                              text=True, env=env, timeout=120)

    ensure.name, ensure.logs = name, logs
    yield ensure
    pid = (logs / f"{name}.pid").read_text().strip() if (logs / f"{name}.pid").exists() else ""
    if pid:
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for path in logs.glob(f"{name}.*"):
        path.unlink()


def poll(ensure, *args: str, until: int, timeout: float = 30.0) -> subprocess.CompletedProcess:
    end = time.monotonic() + timeout
    while True:
        result = ensure(*args)
        if result.returncode == until or time.monotonic() > end:
            return result
        time.sleep(0.5)


def test_bg_ensure_starts_once_and_reports_done(job):
    first = job("--", "bash", "-c", "sleep 1; echo hi")
    assert first.returncode == 75 and first.stdout.startswith("STARTED")
    again = job("--", "bash", "-c", "sleep 1; echo hi")
    assert again.returncode in (0, 75) and "STARTED" not in again.stdout  # never a second copy
    done = poll(job, "--", "bash", "-c", "true", until=0)
    assert done.returncode == 0 and done.stdout.startswith("DONE 0") and "hi" in done.stdout


def test_bg_ensure_reports_a_real_failure_without_restarting(job):
    job("--", "bash", "-c", "exit 3")
    done = poll(job, "--", "bash", "-c", "exit 3", until=3)
    assert done.returncode == 3 and done.stdout.startswith("DONE 3")
    assert not (job.logs / f"{job.name}.restarts").exists()


def test_bg_ensure_restarts_a_crashed_job_then_gives_up(job, tmp_path):
    cmd = ("--max-restarts", "1", "--task", "6.6", "--", "bash", "-c", "echo crashing; kill -9 $$")
    assert job(*cmd).stdout.startswith("STARTED")
    seen: list[tuple[int, str]] = []

    def step() -> bool:
        result = job(*cmd)
        seen.append((result.returncode, result.stdout.splitlines()[0]))
        return result.returncode == 1

    wait_for(step, 60)
    assert any(line.startswith("RESTARTED 1 (crashed (exit 137))") for _, line in seen)
    assert seen[-1][1].startswith("GAVE UP")
    blockers = (tmp_path / "BLOCKERS.md").read_text()
    assert "6.6 (crashed (exit 137))" in blockers and "kill -9" in blockers
    assert (job.logs / f"{job.name}.log.1").exists()


def test_bg_ensure_restarts_a_stalled_or_lost_job(job):
    cmd = ("--stall", "2", "--max-restarts", "2", "--", "sleep", "60")
    assert job(*cmd).returncode == 75
    first_pid = int((job.logs / f"{job.name}.pid").read_text())
    time.sleep(3.5)
    stalled = job(*cmd)
    assert stalled.returncode == 75 and stalled.stdout.startswith("RESTARTED 1 (stalled")
    wait_for(lambda: gone(first_pid), 20)
    wait_for(lambda: (job.logs / f"{job.name}.pid").exists() and
             (job.logs / f"{job.name}.pid").read_text().strip() not in ("", str(first_pid)))
    second_pid = int((job.logs / f"{job.name}.pid").read_text())
    os.killpg(second_pid, signal.SIGKILL)  # gone without an exit file
    wait_for(lambda: gone(second_pid), 20)
    lost = job(*cmd)
    assert lost.returncode == 75 and lost.stdout.startswith("RESTARTED 2 (lost")


def test_bg_ensure_waiting_for_the_lock_is_not_a_stall(job):
    cmd = ("--stall", "1", "--", "bash", "-c", "echo 'waiting for /x/sim.lock'; sleep 60")
    job(*cmd)
    time.sleep(2.5)
    waiting = job(*cmd)
    assert waiting.returncode == 75 and "waiting for the simulation lock" in waiting.stdout


def test_bg_ensure_usage(job):
    assert job().returncode == 2
    assert job("--bogus").returncode == 2
