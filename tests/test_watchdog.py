"""Tests for scripts/watchdog.sh: stall, timeout, crash, and incomplete-output detection with method ladders."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

FAST = ["--poll", "1"]


def watchdog(repo_root: Path, tmp_path: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "ATH_WATCHDOG_LOGS": str(tmp_path / "logs"), "ATH_BLOCKERS_FILE": str(tmp_path / "BLOCKERS.md")}
    return subprocess.run(["bash", str(repo_root / "scripts" / "watchdog.sh"), "--name", "job", *FAST, *args],
                          capture_output=True, text=True, env=env, timeout=timeout)


def outcomes(tmp_path: Path) -> list[str]:
    path = tmp_path / "logs" / "job.attempts.jsonl"
    return [json.loads(line)["outcome"] for line in path.read_text().splitlines()]


def test_pass_first_time(repo_root, tmp_path):
    result = watchdog(repo_root, tmp_path, "--method", "echo hello; echo tag=$ATH_WATCHDOG_TAG attempt=$ATH_ATTEMPT")
    assert result.returncode == 0 and outcomes(tmp_path) == ["PASS"]
    log = (tmp_path / "logs" / "job.attempt1.log").read_text()
    assert "hello" in log and "attempt=1" in log and "tag=job-" in log


def test_stalled_attempt_is_killed_and_the_next_method_passes(repo_root, tmp_path):
    pid_file = tmp_path / "pid"
    result = watchdog(repo_root, tmp_path, "--stall", "3",
                      "--method", f"echo $$ > {pid_file}; sleep 300",
                      "--method", "echo second method")
    assert result.returncode == 0 and outcomes(tmp_path) == ["STALLED", "PASS"]
    pid = int(pid_file.read_text())
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the stalled attempt's process group is gone


def test_timeout_counts_active_time_even_with_output(repo_root, tmp_path):
    result = watchdog(repo_root, tmp_path, "--timeout", "4", "--stall", "60",
                      "--method", "while true; do echo tick; sleep 1; done",
                      "--method", "true")
    assert result.returncode == 0 and outcomes(tmp_path) == ["TIMEOUT", "PASS"]


def test_crash_and_exit_124_are_retried(repo_root, tmp_path):
    result = watchdog(repo_root, tmp_path, "--method", "kill -9 $$", "--method", "exit 124", "--method", "true")
    assert result.returncode == 0 and outcomes(tmp_path) == ["CRASHED", "TIMEOUT", "PASS"]


def test_incomplete_outputs_are_retried(repo_root, tmp_path):
    out = tmp_path / "out.json"
    check = f'test -s {out} && [ "$(stat -c %Y {out})" -ge "$ATH_ATTEMPT_START" ]'
    result = watchdog(repo_root, tmp_path, "--complete", check,
                      "--method", "true",
                      "--method", f"echo '{{}}' > {out}")
    assert result.returncode == 0 and outcomes(tmp_path) == ["INCOMPLETE", "PASS"]


def test_a_real_failure_is_reported_not_retried(repo_root, tmp_path):
    result = watchdog(repo_root, tmp_path, "--method", "echo 1 test failed; exit 3", "--method", "true")
    assert result.returncode == 3 and outcomes(tmp_path) == ["FAILED"]
    assert "1 test failed" in result.stdout
    assert not (tmp_path / "BLOCKERS.md").exists()


def test_retry_on_failure_for_idempotent_steps(repo_root, tmp_path):
    counter = tmp_path / "n"
    method = f"n=$(cat {counter} 2>/dev/null || echo 0); echo $((n+1)) > {counter}; [ $n -ge 1 ]"
    result = watchdog(repo_root, tmp_path, "--retry-on-failure", "--method", method)
    assert result.returncode == 0 and outcomes(tmp_path) == ["FAILED", "PASS"]


def test_exhaustion_records_a_blocker(repo_root, tmp_path):
    result = watchdog(repo_root, tmp_path, "--attempts", "2", "--task", "6.6", "--method", "kill -9 $$")
    assert result.returncode == 1 and outcomes(tmp_path) == ["CRASHED", "CRASHED"]
    blockers = (tmp_path / "BLOCKERS.md").read_text()
    assert blockers.startswith("# Blockers") and "6.6 (CRASHED)" in blockers and "Exit code: 137" in blockers
    assert "job.attempts.jsonl" in blockers


def test_waiting_for_the_lock_is_neither_stalled_nor_active(repo_root, tmp_path):
    method = "echo 'waiting for /x/sim.lock'; sleep 6; echo 'acquired /x/sim.lock'; echo done"
    result = watchdog(repo_root, tmp_path, "--stall", "3", "--timeout", "3", "--method", method)
    assert result.returncode == 0 and outcomes(tmp_path) == ["PASS"]


def test_progress_paths_keep_a_quiet_attempt_alive(repo_root, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    # 8 s with no output, longer than the 5 s stall limit; a new file every 0.5 s leaves room for a loaded machine.
    method = f"for i in $(seq 16); do touch {work}/f$i; sleep 0.5; done"
    result = watchdog(repo_root, tmp_path, "--stall", "5", "--progress", str(work), "--method", method)
    assert result.returncode == 0 and outcomes(tmp_path) == ["PASS"]


def test_usage_errors(repo_root, tmp_path):
    assert watchdog(repo_root, tmp_path).returncode == 2
    assert watchdog(repo_root, tmp_path, "--bogus", "1").returncode == 2
