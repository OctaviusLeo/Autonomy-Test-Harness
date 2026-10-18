"""Runner unit tests with fake processes, Gazebo, Nav2, and clocks (Requirements 5.2, 5.3, 5.4, 5.7)."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import repro
from harness.oracle.judge import RunTrace
from harness.runner import rerun, run_scenario as rs, suite
from harness.runner.gt_bridge import PoseSample
from harness.runner.processes import ProcessApi, ProcInfo
from harness.runner.run_config import load_run_config
from harness.schema.validate import load_scenario

HASH = "d" * 40
CFG = load_run_config("config/run.yaml")
STAMP = repro.Stamp("bash scripts/run_suite.sh smoke", 0, HASH)


# --------------------------------------------------------------------------- run_scenario with fakes
class FakeSession:
    def __init__(self, world, out, env):
        self.world, self.out, self.env = world, out, env
        self.started: list[list[str]] = []
        self.python = "python3"
        self.ran: list[list[str]] = []

    def start_launch(self, spec):
        self.started.append(spec.command())

    def start_gt_bridge(self, world, model):
        self.started.append(["gt_bridge", world, model])

    def start(self, name, cmd):
        self.started.append([name, *cmd])

    def ensure_xvfb(self):
        self.started.append(["xvfb"])
        return self.world.xvfb_ok

    def models(self):
        return list(self.world.models) + [f"obs_{k}" for k in range(self.world.spawned)]

    def alive(self, name):
        return True

    def run(self, cmd, timeout, env):
        self.ran.append(cmd)
        if cmd[:4] == ["ros2", "run", "ros_gz_sim", "create"]:
            if self.world.spawn_rc != 0:
                return subprocess.CompletedProcess(cmd, self.world.spawn_rc, "", "service call failed")
            self.world.spawned += 0 if self.world.spawn_invisible else 1
        return subprocess.CompletedProcess(cmd, 0, "Subscription count: 5\n", "")

    def teardown(self, order=(), clean_shm=False):
        self.world.torn_down += 1
        return list(self.world.leftovers)


class FakeClient:
    def __init__(self, world):
        self.world = world
        self.sim_time = 4.0
        self.closed = False

    def wait_for_scan(self, n, timeout_s):
        return self.world.scan

    def wait_for_subscribers(self, topic, count, timeout_s):
        return self.world.recorder

    def wait_for_clock(self, timeout_s):
        return True

    def wait_lifecycle_active(self, managers, timeout_s):
        return self.world.active

    def set_initial_pose(self, x, y, yaw, timeout_s):
        if self.world.boom:
            raise RuntimeError("boom")
        return True

    def send_goal(self, x, y, yaw, timeout_s):
        return "handle" if self.world.accept else None

    def publish_dispatch(self):
        return 5.0

    def wait_result(self, handle, dispatch_t, limit_s, wall_timeout_s):
        self.sim_time = 30.0
        return self.world.status

    def wait_sim_seconds(self, s, wall_timeout_s):
        return True

    def subscriptions_info(self, topic):
        return [{"node": "/amcl", "type": "sensor_msgs/msg/LaserScan", "reliability": "BEST_EFFORT"}]

    def close(self):
        self.closed = True


class World:
    def __init__(self, **kw):
        self.models = ["ground_plane", "turtlebot4"]
        self.spawned = 0
        self.spawn_rc = 0
        self.spawn_invisible = False
        self.scan = self.recorder = self.active = self.accept = True
        self.boom = False
        self.xvfb_ok = True
        self.sessions: list[FakeSession] = []
        self.status = "SUCCEEDED"
        self.leftovers: list[str] = []
        self.torn_down = 0
        self.trace = None
        self.__dict__.update(kw)

    def deps(self):
        clock = iter(range(0, 10**6, 3))

        def read_trace(bag):
            if self.trace == "unreadable":
                raise OSError("no metadata.yaml")
            return self.trace

        def make_session(out, env):
            self.sessions.append(FakeSession(self, out, env))
            return self.sessions[-1]

        return rs.RunnerDeps(make_session=make_session,
                             make_client=lambda topic: FakeClient(self), read_trace=read_trace,
                             env=lambda: {"ATH_HOST_RESULTS": "/home/u/ath-shared/runs/x", "DISPLAY": ":0"},
                             monotonic=lambda: next(clock), sleep=lambda s: None)


def gt(x, y, t, yaw=0.0):
    return PoseSample(int(t), int((t % 1) * 1e9), x, y, 0.0, 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))


@pytest.fixture
def smoke_scenario(repo_root):
    path = repo_root / "scenarios" / "fixed10" / "fixed10-000.yaml"
    return path, load_scenario(path)


def run(world, scenario_pair, tmp_path, wiring=False, out=None, render_mode="egl"):
    path, scenario = scenario_pair
    return rs.run_scenario(scenario, path, CFG, out or tmp_path / "results", 3, "none", world.deps(), STAMP,
                           wiring=wiring, render_mode=render_mode)


def test_successful_run_writes_record_and_verdict(smoke_scenario, tmp_path):
    _, s = smoke_scenario
    world = World(trace=RunTrace([gt(s.start.x, s.start.y, 5.0), gt(s.goal.x, s.goal.y, 12.0, s.goal.yaw)], 5.0))
    rec = run(world, smoke_scenario, tmp_path, wiring=True)
    assert rec["status"] == "ok" and rec["verdict"]["passed"] and rec["nav2_result"] == "SUCCEEDED"
    assert rec["stamp"] == STAMP.to_dict() and rec["generator_config"] == "config/generator_smoke.yaml"
    assert rec["bag_path"] == str(tmp_path / "results" / "bags" / "fixed10-000")
    run_dir = tmp_path / "results" / "runs" / "fixed10-000"
    assert json.loads((run_dir / "run_record.json").read_text())["scenario_id"] == "fixed10-000"
    assert json.loads((run_dir / "verdict.json").read_text())["passed"]
    assert sorted(p.name for p in (run_dir / "obstacles").iterdir()) == ["obs_0.sdf", "obs_1.sdf"]
    assert json.loads((run_dir / "wiring" / "subscriptions.json").read_text())["/scan_ath"][0]["node"] == "/amcl"
    assert (run_dir / "wiring" / "topic_info_scan_ath.txt").exists()
    assert rec["dispatch_sim_time_s"] == 5.0 and rec["result_sim_time_s"] == 25.0
    assert world.torn_down == 1


@pytest.mark.parametrize("change, step, fragment", [
    ({"models": ["ground_plane"]}, "launch", "turtlebot4 not listed"),
    ({"scan": False}, "launch", "no message on /scan"),
    ({"spawn_rc": 1}, "spawn", "create obs_0 exited 1"),
    ({"spawn_invisible": True}, "spawn", "not listed after spawning"),
    ({"recorder": False}, "launch", "recorder"),
    ({"active": False}, "nav2_activate", "lifecycle manager"),
    ({"accept": False}, "goal", "not accepted"),
    ({"trace": "unreadable"}, "ground_truth", "cannot read bag"),
    ({"trace": RunTrace([], 5.0)}, "ground_truth", "no Ground_Truth sample"),
    ({"trace": RunTrace([PoseSample(1, 0, 0, 0, 0, 0, 0, 0, 1)], 5.0)}, "ground_truth", "no Ground_Truth sample at or after"),
    ({"boom": True}, "harness", "RuntimeError: boom"),
])
def test_failing_steps_are_errored_and_torn_down(smoke_scenario, tmp_path, change, step, fragment):
    world = World(**change)
    rec = run(world, smoke_scenario, tmp_path)
    assert rec["status"] == "errored" and rec["failing_step"] == step and fragment in rec["effect"]
    assert rec["verdict"] is None and world.torn_down == 1
    assert (tmp_path / "results" / "runs" / "fixed10-000" / "run_record.json").exists()


def test_render_modes(smoke_scenario, tmp_path):
    _, s = smoke_scenario
    trace = RunTrace([gt(s.start.x, s.start.y, 5.0), gt(s.goal.x, s.goal.y, 12.0, s.goal.yaw)], 5.0)
    egl = World(trace=trace)
    assert run(egl, smoke_scenario, tmp_path)["render_mode"] == "egl"
    assert "DISPLAY" not in egl.sessions[0].env and ["xvfb"] not in egl.sessions[0].started
    xvfb = World(trace=trace)
    rec = run(xvfb, smoke_scenario, tmp_path / "x", render_mode="xvfb")
    assert rec["status"] == "ok" and rec["render_mode"] == "xvfb"
    assert xvfb.sessions[0].env["DISPLAY"] == ":99" and xvfb.sessions[0].started[0] == ["xvfb"]
    broken = World(xvfb_ok=False)
    rec = run(broken, smoke_scenario, tmp_path / "b", render_mode="xvfb")
    assert rec["status"] == "errored" and rec["failing_step"] == "launch" and "Xvfb" in rec["effect"]
    with pytest.raises(ValueError):
        run(World(), smoke_scenario, tmp_path / "c", render_mode="glx")


def test_session_starts_xvfb_only_when_nothing_serves_the_display(tmp_path):
    from harness.runner.session import Session

    now = [0.0]
    api = ProcessApi(monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    started = []
    session = Session(tmp_path, {}, api=api)
    session.start_xvfb = lambda: started.append("xvfb")
    socket = tmp_path / "X99"
    socket.touch()
    assert session.ensure_xvfb(socket) and started == []
    socket.unlink()
    assert not session.ensure_xvfb(socket, timeout_s=2.0) and started == ["xvfb"] and now[0] >= 2.0


def test_leftovers_are_recorded(smoke_scenario, tmp_path):
    _, s = smoke_scenario
    world = World(leftovers=["gz sim -r -s /tmp/w.sdf"], trace=RunTrace([gt(s.goal.x, s.goal.y, 9.0)], 5.0))
    assert run(world, smoke_scenario, tmp_path)["leftover_processes"] == ["gz sim -r -s /tmp/w.sdf"]


def test_bag_path_and_commands_follow_the_scenario_id(smoke_scenario, tmp_path):
    _, s = smoke_scenario
    assert rs.bag_dir(Path("/results/repeat_2"), "fixed10-004") == Path("/results/repeat_2/bags/fixed10-004")
    cmd = rs.bag_command(Path("/results/bags/fixed10-004"), ["/scan", "/scan_ath"])
    assert cmd[:3] == ["ros2", "bag", "record"] and "--use-sim-time" in cmd and "zstd_fast" in cmd
    assert cmd[cmd.index("-o") + 1] == "/results/bags/fixed10-004" and cmd[-2:] == ["/scan", "/scan_ath"]
    box = s.obstacles[0]
    spawn = rs.spawn_command("empty_10x10", Path("/x/obs_0.sdf"), "obs_0", box)
    assert spawn[spawn.index("-z") + 1] == f"{rs.obstacle_height(box) / 2}"
    assert "<static>true</static>" in rs.obstacle_sdf(box, "obs_0")
    assert rs.host_path(Path("/results/bags/a"), {"ATH_HOST_RESULTS": "/h/run"}) == "/h/run/bags/a"
    assert rs.host_path(Path("/elsewhere/a"), {"ATH_HOST_RESULTS": "/h/run"}) == "/elsewhere/a"
    assert rs.generator_config_for("exp30-003") == "config/generator.yaml"
    assert rs.generator_config_for("exp30-003.latency") == "config/generator.yaml"
    assert rs.generator_config_for("nope-000") is None


# --------------------------------------------------------------------------- suite with fake children
class FakeChild:
    def __init__(self, behaviour, cmd, rdir: Path):
        self.behaviour = behaviour
        self.pid = 4242
        self.returncode = None
        scenario_id = cmd[cmd.index("--scenario") + 1].rsplit("/", 1)[-1].removesuffix(".yaml")
        if behaviour != "crash":
            (rdir.parents[1] / "bags" / scenario_id).mkdir(parents=True, exist_ok=True)  # the recorder started
        if behaviour in ("ok", "fail"):
            passed = behaviour == "ok"
            rdir.joinpath("run_record.json").write_text(json.dumps({
                "scenario_id": scenario_id, "seed": 1, "fault_condition": "none", "status": "ok",
                "failing_step": None, "nav2_result": "SUCCEEDED", "leftover_processes": [],
                "verdict": {"passed": passed, "reason": "" if passed else "timeout"}, "stamp": STAMP.to_dict()}))
            self.returncode = 0
        elif behaviour == "crash":
            self.returncode = 1

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -9
        return self.returncode


def suite_deps(behaviours: dict[str, str | list[str]], leftovers_after: dict[str, list[str]] | None = None,
               moving: bool = False):
    """Fake children per Scenario id: one behaviour, or a list (one per attempt). ``moving`` makes the run's files
    look busy (a hung child keeps logging), so only the hard limit stops it; otherwise nothing changes (a stall)."""
    now = [0.0]
    children = []
    table: list[ProcInfo] = []
    killed: list[int] = []

    def popen(cmd, **kwargs):
        scenario_id = cmd[cmd.index("--scenario") + 1].rsplit("/", 1)[-1].removesuffix(".yaml")
        rdir = Path(kwargs["stdout"].name).parent
        behaviour = behaviours[scenario_id]
        child = FakeChild(behaviour.pop(0) if isinstance(behaviour, list) else behaviour, cmd, rdir)
        children.append((scenario_id, child, cmd))
        for line in (leftovers_after or {}).get(scenario_id, []):
            table.append(ProcInfo(900 + len(table), line))
        return child

    def killpg(pgid, sig):
        for _, child, _ in children:
            if child.returncode is None:
                child.returncode = -sig

    def kill(pid, sig):
        killed.append(pid)
        table[:] = [p for p in table if p.pid != pid]

    def sleep(seconds):
        now[0] += seconds

    api = ProcessApi(popen=popen, killpg=killpg, kill=kill, list_processes=lambda: list(table),
                     protected_pids=set, monotonic=lambda: now[0], sleep=sleep)
    reports = []
    deps = suite.SuiteDeps(api=api, python="python3", clean_shm=lambda: 0,
                           write_reports=lambda records, out, name: reports.append((name, len(records))),
                           newest_mtime=lambda paths: now[0] if moving else 0.0)
    return deps, children, killed, now, reports


@pytest.fixture
def three_scenarios(tmp_path, repo_root):
    d = tmp_path / "scen"
    d.mkdir()
    for k in (0, 1, 2):
        shutil.copy(repo_root / "scenarios" / "fixed10" / f"fixed10-00{k}.yaml", d)
    return d


def test_hung_scenario_is_killed_at_the_hard_limit_and_the_suite_continues(three_scenarios, tmp_path, monkeypatch):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    deps, children, _, now, _ = suite_deps({"fixed10-000": "hang", "fixed10-001": "ok", "fixed10-002": "crash"},
                                           moving=True)
    records = suite.run_suite(suite.scenario_files([three_scenarios]), CFG, tmp_path / "out", deps=deps, retry=False)
    assert [c[0] for c in children] == ["fixed10-000", "fixed10-001", "fixed10-002"]
    hung = records[0]
    assert hung["status"] == "timed_out" and hung["verdict"]["reason"] == "timeout"
    assert hung["verdict"]["detail"] == "hard wall-clock limit" and not hung["verdict"]["passed"]
    assert now[0] >= CFG.hard_limit_s(90.0)
    assert children[0][1].returncode is not None  # stopped, not left running
    assert records[1]["status"] == "ok" and records[1]["verdict"]["passed"]
    assert records[2]["status"] == "errored" and records[2]["failing_step"] == "harness"
    assert "exited 1" in records[2]["effect"]
    assert records[0]["stamp"]["commit"] == HASH and records[2]["stamp"]["seed"] == records[2]["seed"]
    assert json.loads((tmp_path / "out" / "runs" / "fixed10-000" / "run_record.json").read_text())["status"] == "timed_out"
    assert children[1][2][children[1][2].index("--run-index") + 1] == "1"


def arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_runs_without_a_result_are_retried_once_with_the_other_render_method(three_scenarios, tmp_path, monkeypatch):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    deps, children, _, now, _ = suite_deps({"fixed10-000": ["hang", "ok"], "fixed10-001": ["fail", "ok"],
                                            "fixed10-002": ["crash", "crash"]})
    out = tmp_path / "out"
    (out / "bags" / "fixed10-000").mkdir(parents=True)  # a partial bag from an earlier, stopped suite
    records = suite.run_suite(suite.scenario_files([three_scenarios]), CFG, out, deps=deps)
    assert [c[0] for c in children] == ["fixed10-000", "fixed10-000", "fixed10-001", "fixed10-002", "fixed10-002"]
    assert [arg(c[2], "--render-mode") for c in children] == ["egl", "xvfb", "egl", "egl", "xvfb"]
    assert [arg(c[2], "--run-index") for c in children] == ["0", "500", "1", "2", "502"]
    stalled, failed, crashed = records
    assert stalled["status"] == "ok" and stalled["attempt"] == 2 and stalled["render_mode"] == "xvfb"
    assert stalled["first_attempt"]["status"] == "timed_out" and "stalled" in stalled["first_attempt"]["effect"]
    first = json.loads((out / "runs" / "fixed10-000" / "attempt_1" / "run_record.json").read_text())
    assert first["verdict"]["detail"].startswith("stalled: no change") and first["render_mode"] == "egl"
    assert first["bag_path"].endswith("fixed10-000.attempt1") and (out / "bags" / "fixed10-000.attempt1").is_dir()
    assert (out / "bags" / "fixed10-000.interrupted1").is_dir() and (out / "bags" / "fixed10-000").is_dir()
    assert now[0] < 2 * CFG.hard_limit_s(90.0)  # stopped after stall_timeout_s, not the hard limit
    assert failed["attempt"] == 1 and not failed["verdict"]["passed"]  # a real result is never re-run
    assert crashed["status"] == "errored" and crashed["attempt"] == 2
    assert crashed["first_attempt"]["status"] == "errored"
    s = suite.summarize(records)
    assert [r["scenario_id"] for r in s["retried"]] == ["fixed10-000", "fixed10-002"] and s["errored"] == 1


def test_suite_main_render_mode_and_no_retry(three_scenarios, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    monkeypatch.setenv("ATH_RENDER_MODE", "xvfb")
    deps, children, _, _, _ = suite_deps({"fixed10-000": "crash", "fixed10-001": "ok", "fixed10-002": "ok"})
    assert suite.main(["--name", "n", "--scenarios", str(three_scenarios), "--out", str(tmp_path / "o"),
                       "--no-retry", "--fail-on", "errors"], deps=deps) == 1
    assert len(children) == 3 and {arg(c[2], "--render-mode") for c in children} == {"xvfb"}
    assert "1 errored, 0 timed out, 0 retried" in capsys.readouterr().out


def test_newest_mtime_and_move_aside(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    for k, name in enumerate(("a/b/old", "a/new")):
        (tmp_path / name).touch()
        os.utime(tmp_path / name, (1000 + k, 1000 + k))
    os.utime(tmp_path / "a" / "b", (900, 900))
    os.utime(tmp_path / "a", (900, 900))
    assert suite.newest_mtime([tmp_path / "a", tmp_path / "missing"]) == 1001
    assert suite.newest_mtime([tmp_path / "missing"]) == 0.0
    assert suite.move_aside(tmp_path / "missing", "attempt") is None
    (tmp_path / "bag").mkdir()
    assert suite.move_aside(tmp_path / "bag", "attempt").name == "bag.attempt1"
    (tmp_path / "bag").mkdir()
    assert suite.move_aside(tmp_path / "bag", "attempt").name == "bag.attempt2"
    assert suite.other_render_mode("egl") == "xvfb" and suite.other_render_mode("xvfb") == "egl"


def test_leftovers_after_a_scenario_are_killed_and_recorded(three_scenarios, tmp_path, monkeypatch):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    deps, _, killed, _, _ = suite_deps({"fixed10-000": "ok", "fixed10-001": "ok", "fixed10-002": "ok"},
                                       {"fixed10-001": ["/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge"]})
    records = suite.run_suite(suite.scenario_files([three_scenarios]), CFG, tmp_path / "out", deps=deps)
    assert records[1]["leftover_processes"] == ["/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge"]
    assert killed == [900] and records[2]["leftover_processes"] == []


def test_suite_main_with_repeats_and_selection(three_scenarios, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    select = tmp_path / "select.yaml"
    select.write_text("ids: [fixed10-000, fixed10-002]\n")
    deps, children, _, _, reports = suite_deps({"fixed10-000": "ok", "fixed10-002": "fail"})
    assert suite.main(["--name", "smoke", "--scenarios", str(three_scenarios), "--out", str(tmp_path / "o"),
                       "--repeat", "2", "--select", str(select), "--wiring"], deps=deps) == 0
    assert len(children) == 4 and "--wiring" in children[0][2]
    top = json.loads((tmp_path / "o" / "suite.json").read_text())
    assert top["repeats"] == 2 and top["runs"] == 4 and top["passed"] == 2 and top["failed"] == 2
    assert top["records"][0] == "repeat_1/runs/fixed10-000/run_record.json"
    assert top["scenario_ids"] == ["fixed10-000", "fixed10-002"]
    rep2 = json.loads((tmp_path / "o" / "repeat_2" / "suite.json").read_text())
    assert rep2["repeat"] == 2 and rep2["stamp"]["commit"] == HASH
    assert reports == [("smoke", 2), ("smoke", 2)]
    assert "4 runs, 2 passed, 2 failed" in capsys.readouterr().out


def test_exit_status_rules():
    clean = {"errored": 0, "timed_out": 0, "failed": 0}
    failed = {**clean, "failed": 1}
    hung = {**clean, "timed_out": 1}
    assert suite.exit_status(failed, "nothing") == 0
    assert suite.exit_status(failed, "errors") == 0 and suite.exit_status(hung, "errors") == 1
    assert suite.exit_status(failed, "failures") == 1 and suite.exit_status(clean, "failures") == 0


def test_select_all_and_scenario_files(three_scenarios, tmp_path):
    files = suite.scenario_files([three_scenarios, three_scenarios / "fixed10-001.yaml"])
    assert [f.name for f in files] == ["fixed10-000.yaml", "fixed10-001.yaml", "fixed10-002.yaml", "fixed10-001.yaml"]
    all_ids = tmp_path / "all.yaml"
    all_ids.write_text("ids: all\n")
    assert suite.select(files[:3], all_ids) == files[:3]
    assert suite.select(files[:3], None) == files[:3]


# --------------------------------------------------------------------------- rerun
def test_rerun_prepares_the_committed_scenario(tmp_path, repo_root):
    record = json.loads((repo_root / "scenarios" / "fixed10" / "generation.json").read_text())
    seed = record["scenarios"][4]["seed"]
    dest = rerun.prepare("config/generator_smoke.yaml", seed, tmp_path)
    assert dest.read_text() == (repo_root / "scenarios" / "fixed10" / "fixed10-004.yaml").read_text()


def test_rerun_applies_a_condition(tmp_path, repo_root):
    record = json.loads((repo_root / "scenarios" / "experiment30" / "generation.json").read_text())
    seed = record["scenarios"][0]["seed"]
    dest = rerun.prepare("config/generator.yaml", seed, tmp_path, condition="sector_blackout")
    faulted = load_scenario(dest)
    assert faulted.scenario_id == "exp30-000" and [f.type for f in faulted.faults] == ["sector_blackout"]


def test_rerun_refuses_a_changed_committed_file(tmp_path, repo_root):
    root = tmp_path / "scenarios"
    shutil.copytree(repo_root / "scenarios" / "fixed10", root / "fixed10")
    path = root / "fixed10" / "fixed10-001.yaml"
    path.write_text(path.read_text().replace("time_limit_s: 90.0", "time_limit_s: 95.0"))
    seed = load_scenario(path).seed
    with pytest.raises(rerun.RerunError, match="differs"):
        rerun.prepare("config/generator_smoke.yaml", seed, tmp_path / "out", root=root)


def test_rerun_main(tmp_path, repo_root, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    record = json.loads((repo_root / "scenarios" / "fixed10" / "generation.json").read_text())
    seed = record["scenarios"][2]["seed"]
    deps, children, _, _, _ = suite_deps({"fixed10-002": "ok"})
    assert rerun.main(["--config", "config/generator_smoke.yaml", "--seed", str(seed), "--out", str(tmp_path)], deps) == 0
    assert "fixed10-002 status=ok verdict=True" in capsys.readouterr().out
    assert json.loads((tmp_path / "suite.json").read_text())["suite"] == "rerun"
    assert rerun.main(["--config", "config/generator_smoke.yaml", "--seed", "12", "--out", str(tmp_path)], deps) == 1
    assert math.isfinite(1.0)
