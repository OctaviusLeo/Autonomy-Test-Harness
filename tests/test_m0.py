"""Tests for the M0 baseline logic with fake processes, Gazebo, and Nav2 (Requirements 1.2-1.5)."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import pytest

from harness import m0
from harness.runner.gt_bridge import PoseSample

DPKG = ("ros-jazzy-nav2-bringup\t1.3.13-1noble\nros-jazzy-navigation2\t1.3.13-1noble\n"
        "ros-jazzy-nav2-minimal-tb4-sim\t1.0.1-1noble\nros-jazzy-nav2-minimal-tb3-sim\t\n")
OGRE_OK = "00:00:01: GL_RENDERER = llvmpipe (LLVM 20.1.2, 256 bits)\n"
LAUNCH_OK = "[INFO] up\n[WARNING] [launch]: user interrupted with ctrl-c (SIGINT)\n[ERROR] shutdown noise\n"


class FakeScan:
    def __init__(self, finite: int, total: int = 360):
        self.ranges = [1.0] * finite + [math.inf] * (total - finite)


class FakeSession:
    def __init__(self, world, out, env):
        self.world, self.out, self.env = world, out, env
        self.started: list[str] = []
        self.torn_down = False

    def start_launch(self, spec):
        self.started.append("launch")

    def start_xvfb(self):
        self.started.append("xvfb")

    def start_gt_bridge(self, world, model):
        self.started.append("gt_bridge")

    def models(self):
        return list(self.world.models)

    def alive(self, name):
        return self.world.launch_alive

    def teardown(self, order=(), clean_shm=False):
        self.torn_down = True
        return list(self.world.leftovers)


class FakeClient:
    def __init__(self, world):
        self.world = world
        self.sim_time = None
        self.last_scan = None
        self.gt_samples: list[PoseSample] = []
        self.closed = False

    def wait_for_scan(self, min_finite, timeout_s):
        self.last_scan = FakeScan(self.world.finite_by_mode[self.world.mode])
        return self.world.finite_by_mode[self.world.mode] >= min_finite

    def wait_for_clock(self, timeout_s):
        self.sim_time = 5.0
        return self.world.clock

    def wait_lifecycle_active(self, managers, timeout_s):
        return self.world.active

    def set_initial_pose(self, x, y, yaw, timeout_s):
        return self.world.amcl

    def spin_until(self, predicate, timeout_s):
        if self.world.gt_final is not None:
            self.gt_samples.append(PoseSample(4, 0, -3.0, -3.0, 0, 0, 0, 0, 1))
        return predicate()

    def send_goal(self, x, y, yaw, timeout_s):
        return "handle" if self.world.accept else None

    def publish_dispatch(self):
        return 5.0

    def wait_result(self, handle, dispatch_t, limit_s, wall_timeout_s):
        self.sim_time = 25.0
        if self.world.gt_final is not None:
            x, y, yaw = self.world.gt_final
            self.gt_samples.append(PoseSample(25, 0, x, y, 0, 0, 0, math.sin(yaw / 2), math.cos(yaw / 2)))
        return self.world.status

    def wait_sim_seconds(self, seconds, wall_timeout_s):
        return True

    def lookup_yaw(self, target, source, timeout_s):
        return math.pi / 2

    def close(self):
        self.closed = True


class FakeWorld:
    def __init__(self, **kw):
        self.models = ["ground_plane", "turtlebot4"]
        self.launch_alive = True
        self.leftovers: list[str] = []
        self.finite_by_mode = {"egl": 360, "xvfb": 360}
        self.ogre_by_mode = {"egl": OGRE_OK, "xvfb": OGRE_OK}
        self.clock = self.active = self.amcl = self.accept = True
        self.status = "SUCCEEDED"
        self.gt_final = (3.05, 3.03, 1.45)
        self.dpkg = DPKG
        self.launch_log = LAUNCH_OK
        self.mode = "egl"
        self.sessions: list[FakeSession] = []
        self.__dict__.update(kw)

    def deps(self, tmp_path: Path) -> m0.M0Deps:
        clock = iter(range(0, 100000, 5))

        def run(cmd, timeout, env=None):
            if cmd[0] == "dpkg-query":
                return subprocess.CompletedProcess(cmd, 0 if self.dpkg else 1, self.dpkg, "")
            return subprocess.CompletedProcess(cmd, 0, "8.15.0\n", "")

        def make_session(out, env):
            self.mode = "xvfb" if env.get("DISPLAY") == ":99" else "egl"
            self.sessions.append(FakeSession(self, out, env))
            return self.sessions[-1]

        def read_text(path):
            path = str(path)
            if path.endswith("ogre2.log"):
                return self.ogre_by_mode[self.mode]
            if path.endswith("os-release"):
                return 'PRETTY_NAME="Ubuntu 24.04.5 LTS"\nVERSION_ID="24.04"\n'
            if path.endswith("launch.log"):
                return self.launch_log
            return ""

        self.client = FakeClient(self)
        return m0.M0Deps(run=run, make_session=make_session, make_client=lambda: self.client, read_text=read_text,
                         remove=lambda p: None, copy=lambda a, b: None, env=lambda: {"ROS_DISTRO": "jazzy", "DISPLAY": ":0"},
                         sleep=lambda s: None, monotonic=lambda: next(clock))


def _run(tmp_path, **kw):
    world = FakeWorld(**kw)
    result = m0.M0Baseline(tmp_path, world.deps(tmp_path), Path("/opt/ath"), "/stock/nav2_params.yaml").run()
    return world, result


def test_happy_path_records_everything(tmp_path):
    world, r = _run(tmp_path)
    assert r["failed_step"] is None and r["nav2_result"] == "SUCCEEDED"
    assert r["render"]["method"] == "egl" and r["render"]["renderer"].startswith("llvmpipe")
    assert r["versions"]["packages"]["ros-jazzy-nav2-bringup"] == "1.3.13-1noble"
    assert "ros-jazzy-nav2-minimal-tb3-sim" not in r["versions"]["packages"]
    assert r["versions"]["os_release"]["VERSION_ID"] == "24.04" and r["versions"]["ros_distro"] == "jazzy"
    assert r["true_pose_to_goal_m"] == pytest.approx(math.hypot(0.05, 0.03), abs=1e-4)
    assert r["yaw_error_rad"] == pytest.approx(0.12, abs=1e-4) and r["within_tolerance"]
    assert r["lidar_mount_yaw_deg"] == 90.0
    assert r["launch"]["log"] == "egl/logs/launch.log"
    assert r["launch_log_check"]["error_lines_before_teardown"] == []
    assert r["launch_log_check"]["error_lines_during_teardown"] == 1
    assert world.sessions[0].started == ["launch", "gt_bridge"] and world.sessions[0].torn_down
    assert "DISPLAY" not in world.sessions[0].env and world.sessions[0].env["ROS_DOMAIN_ID"] == "1"
    assert world.client.closed


def test_egl_failure_falls_back_to_xvfb(tmp_path):
    world, r = _run(tmp_path, ogre_by_mode={"egl": "Couldn't open X display", "xvfb": OGRE_OK})
    assert r["failed_step"] is None and r["render"]["method"] == "xvfb"
    assert [a["mode"] for a in r["render"]["attempts"]] == ["egl", "xvfb"]
    assert r["render"]["attempts"][0]["step"] == "render"
    assert world.sessions[1].started[:2] == ["xvfb", "launch"]


def test_both_render_methods_fail(tmp_path):
    _, r = _run(tmp_path, finite_by_mode={"egl": 0, "xvfb": 12})
    assert r["failed_step"] == "render" and "finite ranges per scan=12" in r["effect"]


def test_server_never_lists_the_robot(tmp_path):
    world, r = _run(tmp_path, models=["ground_plane"], launch_alive=False)
    assert r["failed_step"] == "launch" and "turtlebot4" in r["effect"]
    assert len(world.sessions) == 1


def test_missing_packages_fail_the_image_step(tmp_path):
    _, r = _run(tmp_path, dpkg="ros-jazzy-nav2-bringup\t1.3.13\n")
    assert r["failed_step"] == "image" and "ros-jazzy-navigation2" in r["effect"]


@pytest.mark.parametrize("flag, text", [("clock", "/clock"), ("active", "lifecycle"), ("amcl", "AMCL")])
def test_activation_failures(tmp_path, flag, text):
    _, r = _run(tmp_path, **{flag: False})
    assert r["failed_step"] == "nav2_activate" and text in r["effect"]


def test_rejected_goal(tmp_path):
    _, r = _run(tmp_path, accept=False)
    assert r["failed_step"] == "goal" and "not accepted" in r["effect"]


def test_succeeded_but_far_from_goal_fails(tmp_path):
    _, r = _run(tmp_path, gt_final=(2.5, 3.0, 1.57))
    assert r["failed_step"] == "goal" and "SUCCEEDED but the true pose is 0.500 m" in r["effect"]
    assert r["within_tolerance"] is False


def test_aborted_goal(tmp_path):
    _, r = _run(tmp_path, status="ABORTED")
    assert r["failed_step"] == "goal" and "ABORTED" in r["effect"]


def test_no_ground_truth(tmp_path):
    _, r = _run(tmp_path, gt_final=None)
    assert r["failed_step"] == "ground_truth"


def test_process_death_before_teardown_fails_launch(tmp_path):
    log = "[ERROR] [amcl-1]: process has died [pid 5]\n[WARNING] [launch]: user interrupted with ctrl-c (SIGINT)\n"
    _, r = _run(tmp_path, launch_log=log)
    assert r["failed_step"] == "launch" and "process has died" in r["effect"]


def test_leftovers_are_recorded(tmp_path):
    _, r = _run(tmp_path, leftovers=["gz sim -r -s w.sdf"])
    assert r["leftover_processes"] == ["gz sim -r -s w.sdf"]


def test_helpers():
    assert m0.parse_dpkg("a\t1\nb\t\nbad line\n") == {"a": "1"}
    assert m0.parse_os_release('NAME="Ubuntu"\nnot a pair\n') == {"NAME": "Ubuntu"}
    assert m0.angle_diff(math.pi - 0.1, -math.pi + 0.1) == pytest.approx(0.2)


def test_write_result_is_stamped(tmp_path, monkeypatch):
    from harness import repro

    stamp = repro.Stamp("bash scripts/run_m0.sh", 0, "a" * 40)
    path = m0.write_result({"failed_step": None}, tmp_path / "m0.json", stamp)
    assert '"commit": "' + "a" * 40 in path.read_text()
