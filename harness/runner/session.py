"""One simulation session inside the ath-sim container: launch, readiness, helpers, teardown.

The SUT starts through Nav2's stock ``tb4_simulation_launch.py`` with launch arguments only
(design.md, "Platform decision"). Each session gets its own ROS domain, localhost-only discovery,
and its own Gazebo partition, so a leftover process from an earlier run cannot talk to this one.
Every child process runs in its own process group with a log file, and teardown stops them all,
kills any leftover by name, and removes Fast DDS shared-memory files (Requirement 5.2).
OS calls go through :class:`~harness.runner.processes.ProcessApi` and a ``run`` callable, so
tests drive a session with fakes.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from harness.runner import processes
from harness.runner.processes import ProcessApi

RunFn = Callable[..., subprocess.CompletedProcess]
XVFB_DISPLAY = ":99"
XVFB_SOCKET = Path("/tmp/.X11-unix/X99")
RENDER_MODES = ("egl", "xvfb")


def run_command(cmd: Sequence[str], timeout: float, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a short command and capture its output; a timeout becomes return code 124."""
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(list(cmd), 124, out, "timeout")


@dataclasses.dataclass(frozen=True)
class LaunchSpec:
    world_path: str
    map_path: str
    params_path: str
    x: float
    y: float
    yaw: float

    def command(self) -> list[str]:
        return [
            "ros2", "launch", "nav2_bringup", "tb4_simulation_launch.py",
            "headless:=True", "use_rviz:=False",
            f"world:={self.world_path}", f"map:={self.map_path}", f"params_file:={self.params_path}",
            f"x_pose:={self.x:.4f}", f"y_pose:={self.y:.4f}", f"yaw:={self.yaw:.4f}",
        ]


def isolation_env(base: dict, run_index: int) -> dict:
    env = dict(base)
    env["ROS_DOMAIN_ID"] = str(1 + run_index % 100)
    env["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
    env["GZ_PARTITION"] = f"ath_{run_index}"
    return env


def render_env(base: dict, mode: str) -> dict:
    env = dict(base)
    if mode == "egl":
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
    elif mode == "xvfb":
        env["DISPLAY"] = XVFB_DISPLAY
    else:
        raise ValueError(f"unknown render mode {mode!r}")
    return env


def parse_model_list(output: str) -> list[str]:
    """Model names from ``gz model --list`` output (lines of the form ``    - name``)."""
    return [line.strip()[2:].strip() for line in output.splitlines() if line.strip().startswith("- ")]


def ogre_renderer(log_text: str) -> str | None:
    """The GL_RENDERER string from ogre2.log, or None if the renderer never started."""
    for line in log_text.splitlines():
        if "GL_RENDERER = " in line:
            return line.split("GL_RENDERER = ", 1)[1].strip()
    return None


INTERRUPT_MARKER = "user interrupted with ctrl-c"


def launch_log_findings(text: str) -> dict:
    """Split a ``ros2 launch`` log at the teardown SIGINT and report errors on each side.

    A process that died or a Python traceback before teardown is an unhandled error during the
    run; anything after the marker happened while the harness was shutting the SUT down.
    """
    marker_found = INTERRUPT_MARKER in text
    before, _, after = text.partition(INTERRUPT_MARKER)
    lines_before = before.splitlines()
    return {
        "teardown_marker_found": marker_found,
        "error_lines_before_teardown": [line for line in lines_before if "[ERROR]" in line],
        "unhandled_before_teardown": [line for line in lines_before
                                      if "process has died" in line or "Traceback" in line],
        "error_lines_during_teardown": sum(1 for line in after.splitlines() if "[ERROR]" in line),
    }


class Session:
    """The processes of one run. ``env`` must already carry the isolation and render settings."""

    def __init__(self, out_dir: Path, env: dict, api: ProcessApi | None = None, run: RunFn = run_command,
                 python: str = sys.executable, shm_dir: Path = Path("/dev/shm")) -> None:
        self.out_dir = Path(out_dir)
        self.env = env
        self.api = api or ProcessApi()
        self.run = run
        self.python = python
        self.shm_dir = Path(shm_dir)
        self.procs: dict[str, subprocess.Popen] = {}

    def start(self, name: str, cmd: Sequence[str]) -> subprocess.Popen:
        proc = processes.start_group(self.api, cmd, self.out_dir / "logs" / f"{name}.log", env=self.env)
        self.procs[name] = proc
        return proc

    def start_launch(self, spec: LaunchSpec) -> subprocess.Popen:
        return self.start("launch", spec.command())

    def start_gt_bridge(self, world: str, model: str) -> subprocess.Popen:
        return self.start("gt_bridge", [self.python, "-m", "harness.runner.gt_bridge", "--world", world, "--model", model])

    def start_xvfb(self) -> subprocess.Popen:
        return self.start("xvfb", ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"])

    def ensure_xvfb(self, socket: Path = XVFB_SOCKET, timeout_s: float = 10.0) -> bool:
        """Start Xvfb on :99 unless something already serves it (the entrypoint does when ATH_RENDER_MODE=xvfb);
        True once the display's socket exists."""
        if not Path(socket).exists():
            self.start_xvfb()
            end = self.api.monotonic() + timeout_s
            while not Path(socket).exists() and self.api.monotonic() < end:
                self.api.sleep(0.2)
        return Path(socket).exists()

    def models(self, timeout: float = 30.0) -> list[str]:
        result = self.run(["gz", "model", "--list"], timeout=timeout, env=self.env)
        return parse_model_list(result.stdout) if result.returncode == 0 else []

    def alive(self, name: str) -> bool:
        proc = self.procs.get(name)
        return proc is not None and proc.poll() is None

    def stop(self, name: str) -> str | None:
        proc = self.procs.pop(name, None)
        return None if proc is None else processes.stop_group(self.api, proc)

    def teardown(self, order: Sequence[str] = (), clean_shm: bool = False) -> list[str]:
        """Stop every process (``order`` first, the rest after), then kill and report leftovers.

        ``clean_shm`` also removes Fast DDS shared-memory files; only a process with no live ROS
        node of its own may do that (the suite does it after a Scenario's child process exits).
        """
        for name in [*order, *[n for n in list(self.procs) if n not in order]]:
            self.stop(name)
        leftovers = processes.kill_leftovers(self.api)
        if clean_shm:
            processes.clean_shm(self.shm_dir)
        return [p.cmdline for p in leftovers]


def base_env() -> dict:
    return dict(os.environ)
