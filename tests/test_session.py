"""Tests for the simulation session helpers (Requirements 5.1, 5.2)."""

from __future__ import annotations

import subprocess

import pytest

from harness.runner import session as s
from harness.runner.processes import ProcessApi, ProcInfo


def test_launch_command_uses_only_launch_arguments():
    spec = s.LaunchSpec("/opt/ath/worlds/empty_10x10.sdf", "/opt/ath/maps/empty_10x10.yaml",
                        "/opt/ath/config/nav2_params_ath.yaml", -3.0, -2.5, 0.4)
    assert spec.command() == [
        "ros2", "launch", "nav2_bringup", "tb4_simulation_launch.py", "headless:=True", "use_rviz:=False",
        "world:=/opt/ath/worlds/empty_10x10.sdf", "map:=/opt/ath/maps/empty_10x10.yaml",
        "params_file:=/opt/ath/config/nav2_params_ath.yaml", "x_pose:=-3.0000", "y_pose:=-2.5000", "yaw:=0.4000",
    ]


def test_isolation_and_render_env():
    env = s.isolation_env({"DISPLAY": ":0", "PATH": "/bin"}, 205)
    assert env["ROS_DOMAIN_ID"] == "6" and env["GZ_PARTITION"] == "ath_205"
    assert env["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert "DISPLAY" not in s.render_env({**env, "WAYLAND_DISPLAY": "w"}, "egl")
    assert s.render_env(env, "xvfb")["DISPLAY"] == ":99"
    with pytest.raises(ValueError):
        s.render_env(env, "glx")


def test_parse_model_list_and_ogre_renderer():
    out = "\nRequesting state for world [empty_10x10]...\n\nWarning [Utils.cc:132] x\nAvailable models:\n    - ground_plane\n    - turtlebot4\n"
    assert s.parse_model_list(out) == ["ground_plane", "turtlebot4"]
    log = "00:51:41: GL_VENDOR = Mesa\n00:51:41: GL_RENDERER = llvmpipe (LLVM 20.1.2, 256 bits)\n"
    assert s.ogre_renderer(log) == "llvmpipe (LLVM 20.1.2, 256 bits)"
    assert s.ogre_renderer("Couldn't open X display") is None


def test_run_command_captures_output_and_timeouts():
    assert s.run_command(["bash", "-c", "echo hi"], timeout=10).stdout == "hi\n"
    timed_out = s.run_command(["bash", "-c", "echo start; sleep 5"], timeout=0.5)
    assert timed_out.returncode == 124


class FakeProc:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 1000 + len(cmd)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -9
        return self.returncode


def test_session_starts_named_groups_and_tears_down(tmp_path):
    started, signals, killed = [], [], []

    def popen(cmd, **kwargs):
        started.append(FakeProc(cmd, **kwargs))
        return started[-1]

    def killpg(pgid, sig):
        signals.append((pgid, sig))
        for p in started:
            if p.pid == pgid:
                p.returncode = -sig

    leftovers = [ProcInfo(77, "ros2 daemon")]
    api = ProcessApi(popen=popen, killpg=killpg, kill=lambda pid, sig: (killed.append(pid), leftovers.clear()),
                     list_processes=lambda: list(leftovers), protected_pids=set, sleep=lambda x: None)
    ran = []

    def run(cmd, timeout, env):
        ran.append((cmd, env["GZ_PARTITION"]))
        return subprocess.CompletedProcess(cmd, 0, "Available models:\n    - turtlebot4\n", "")

    (tmp_path / "shm").mkdir()
    (tmp_path / "shm" / "fastrtps_port1").write_text("x")
    sess = s.Session(tmp_path, {"GZ_PARTITION": "ath_3"}, api=api, run=run, python="python3", shm_dir=tmp_path / "shm")
    sess.start_launch(s.LaunchSpec("w", "m", "p", 0, 0, 0))
    sess.start_gt_bridge("empty_10x10", "turtlebot4")
    sess.start_xvfb()
    assert sess.alive("launch") and not sess.alive("missing")
    assert started[1].cmd[:3] == ["python3", "-m", "harness.runner.gt_bridge"]
    assert started[0].kwargs["start_new_session"] and started[0].kwargs["env"] == {"GZ_PARTITION": "ath_3"}
    assert sess.models() == ["turtlebot4"] and ran[0] == (["gz", "model", "--list"], "ath_3")
    assert (tmp_path / "logs" / "launch.log").exists()
    assert sess.teardown(order=("gt_bridge", "launch"), clean_shm=True) == ["ros2 daemon"]
    assert killed == [77] and sess.procs == {}
    assert list((tmp_path / "shm").iterdir()) == []
    assert sess.stop("launch") is None


def test_models_empty_when_gz_fails(tmp_path):
    sess = s.Session(tmp_path, {}, run=lambda cmd, timeout, env: subprocess.CompletedProcess(cmd, 1, "", "err"))
    assert sess.models() == []
    assert isinstance(s.base_env(), dict)
