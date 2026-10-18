"""M0 baseline: prove the stock Nav2 TurtleBot 4 simulation runs headless in the ath-sim image and
reaches one goal sent from a script (Requirements 1.2-1.4), and record the evidence.

Steps, each a named failing step (Requirement 1.5): ``image`` (package and tool versions),
``launch`` (the stock launch with the arena, stock parameters, start pose (-3, -3, 0)), ``render``
(EGL first; Xvfb in the container if EGL fails), ``nav2_activate``, ``goal`` (one
``NavigateToPose`` goal to (3, 3, 1.57) within 120 s of simulation time), and ``ground_truth``
(the true final pose from Gazebo). It also records the lidar's mount yaw from TF. Everything the
script touches goes through injectable factories so the logic is tested with fakes.
"""

from __future__ import annotations

import dataclasses
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from harness import repro
from harness.runner import session as session_mod
from harness.runner.session import LaunchSpec, Session

PACKAGES = ("ros-jazzy-navigation2", "ros-jazzy-nav2-bringup")
MINIMAL_SIM_PATTERN = "ros-jazzy-nav2-minimal-tb*"
START = (-3.0, -3.0, 0.0)
GOAL = (3.0, 3.0, 1.57)
GOAL_LIMIT_S = 120.0
TOLERANCE_M = 0.30
MIN_FINITE_RANGES = 300
STARTUP_TIMEOUT_S = 180.0
WORLD = "empty_10x10"
ROBOT_MODEL = "turtlebot4"
OGRE_LOG = Path.home() / ".gz" / "rendering" / "ogre2.log"


class StepFailed(Exception):
    def __init__(self, step: str, effect: str) -> None:
        super().__init__(f"{step}: {effect}")
        self.step = step
        self.effect = effect


@dataclasses.dataclass
class M0Deps:
    """Everything M0 touches outside its own logic; tests replace these."""

    run: Callable = session_mod.run_command
    make_session: Callable[[Path, dict], Session] = lambda out, env: Session(out, env)
    make_client: Callable[[], Any] = None  # set in main(): nav_client.HarnessClient (needs rclpy)
    read_text: Callable[[Path], str] = lambda p: Path(p).read_text(errors="replace") if Path(p).exists() else ""
    remove: Callable[[Path], None] = lambda p: Path(p).unlink(missing_ok=True)
    copy: Callable[[Path, Path], None] = lambda src, dst: (Path(dst).parent.mkdir(parents=True, exist_ok=True),
                                                           shutil.copyfile(src, dst))
    env: Callable[[], dict] = lambda: dict(os.environ)
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


def parse_dpkg(output: str) -> dict[str, str]:
    """``dpkg-query -W`` output (``name<TAB>version`` per line) as a dict."""
    versions = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip():
            versions[parts[0].strip()] = parts[1].strip()
    return versions


def parse_os_release(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"')
    return result


def angle_diff(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def record_versions(deps: M0Deps) -> dict[str, Any]:
    dpkg = deps.run(["dpkg-query", "-W", *PACKAGES, MINIMAL_SIM_PATTERN], timeout=30)
    packages = parse_dpkg(dpkg.stdout)
    missing = [p for p in PACKAGES if p not in packages]
    minimal = sorted(p for p in packages if p.startswith("ros-jazzy-nav2-minimal-tb"))
    if dpkg.returncode != 0 or missing or not minimal:
        raise StepFailed("image", f"dpkg-query -W found {sorted(packages)}; missing {missing or 'minimal sim'}")
    gz = deps.run(["gz", "sim", "--versions"], timeout=30)
    if gz.returncode != 0 or not gz.stdout.strip():
        raise StepFailed("image", f"gz sim --versions failed: {gz.stderr.strip()}")
    return {
        "dpkg_query": dpkg.stdout,
        "packages": packages,
        "os_release": parse_os_release(deps.read_text(Path("/etc/os-release"))),
        "gz_sim_versions": gz.stdout.strip(),
        "ros_distro": deps.env().get("ROS_DISTRO", ""),
    }


def stock_params_path() -> str:
    from ament_index_python.packages import get_package_share_directory  # only in the image

    return str(Path(get_package_share_directory("nav2_bringup")) / "params" / "nav2_params.yaml")


class M0Baseline:
    def __init__(self, out_dir: Path, deps: M0Deps, repo: Path, params_path: str) -> None:
        self.out_dir = Path(out_dir)
        self.deps = deps
        self.repo = Path(repo)
        self.params_path = params_path
        self.result: dict[str, Any] = {
            "start": dict(zip(("x", "y", "yaw"), START)),
            "goal": dict(zip(("x", "y", "yaw"), GOAL)),
            "goal_limit_s": GOAL_LIMIT_S,
            "tolerance_m": TOLERANCE_M,
            "params_file": params_path,
            "robot_model": ROBOT_MODEL,
            "failed_step": None,
            "effect": None,
        }
        self.session: Session | None = None
        self.client = None

    def launch_spec(self) -> LaunchSpec:
        return LaunchSpec(str(self.repo / "worlds" / f"{WORLD}.sdf"), str(self.repo / "maps" / f"{WORLD}.yaml"),
                          self.params_path, *START)

    def try_render(self, mode: str) -> dict[str, Any]:
        """Launch in ``mode`` and decide whether rendering works; leaves the session up on success."""
        env = session_mod.render_env(session_mod.isolation_env(self.deps.env(), 0), mode)
        self.deps.remove(OGRE_LOG)
        self.session = self.deps.make_session(self.out_dir / mode, env)
        if mode == "xvfb":
            self.session.start_xvfb()
            self.deps.sleep(2.0)
        spec = self.launch_spec()
        self.session.start_launch(spec)
        attempt: dict[str, Any] = {"mode": mode, "command": spec.command(),
                                   "launch_log": f"{mode}/logs/launch.log"}
        end = self.deps.monotonic() + STARTUP_TIMEOUT_S
        models: list[str] = []
        while self.deps.monotonic() < end:
            models = self.session.models()
            if ROBOT_MODEL in models:
                break
            if not self.session.alive("launch"):
                break
            self.deps.sleep(2.0)
        attempt["models"] = models
        if ROBOT_MODEL not in models:
            attempt.update(ok=False, step="launch", effect=f"model {ROBOT_MODEL} not listed by gz model --list "
                                                            f"within {STARTUP_TIMEOUT_S:.0f} s (saw {models})")
            return attempt
        self.client = self.client or self.deps.make_client()
        got_scan = self.client.wait_for_scan(MIN_FINITE_RANGES, timeout_s=60.0)
        scan = self.client.last_scan
        finite = sum(1 for r in scan.ranges if math.isfinite(r)) if scan is not None else 0
        renderer = session_mod.ogre_renderer(self.deps.read_text(OGRE_LOG))
        attempt.update(finite_ranges=finite, ranges=len(scan.ranges) if scan is not None else 0, renderer=renderer)
        if got_scan and renderer:
            attempt.update(ok=True)
            self.deps.copy(OGRE_LOG, self.out_dir / mode / "ogre2.log")
        else:
            attempt.update(ok=False, step="render",
                           effect=f"renderer={renderer!r}, finite ranges per scan={finite} (need {MIN_FINITE_RANGES})")
        return attempt

    def render_and_launch(self) -> None:
        attempts = []
        for mode in ("egl", "xvfb"):
            attempt = self.try_render(mode)
            attempts.append(attempt)
            if attempt["ok"]:
                self.result["render"] = {"method": mode, "renderer": attempt["renderer"], "attempts": attempts}
                self.result["launch"] = {"command": attempt["command"], "log": attempt["launch_log"]}
                return
            self.teardown()
            if attempt["step"] == "launch" and mode == "egl":
                # The server never came up: not a rendering question, so do not try Xvfb.
                self.result["render"] = {"method": None, "attempts": attempts}
                raise StepFailed("launch", attempt["effect"])
        self.result["render"] = {"method": None, "attempts": attempts}
        raise StepFailed("render", "; ".join(f"{a['mode']}: {a['effect']}" for a in attempts))

    def activate(self) -> None:
        c = self.client
        if not c.wait_for_clock(30.0):
            raise StepFailed("nav2_activate", "no /clock message within 30 s")
        if not c.wait_lifecycle_active(("lifecycle_manager_localization",), timeout_s=120.0):
            raise StepFailed("nav2_activate", "localization lifecycle manager not active within 120 s")
        if not c.set_initial_pose(*START, timeout_s=60.0):
            raise StepFailed("nav2_activate", "AMCL did not report a pose near the initial pose within 60 s")
        if not c.wait_lifecycle_active(("lifecycle_manager_navigation",), timeout_s=120.0):
            raise StepFailed("nav2_activate", "navigation lifecycle manager not active within 120 s")

    def navigate(self) -> None:
        self.session.start_gt_bridge(WORLD, ROBOT_MODEL)
        c = self.client
        if not c.spin_until(lambda: len(c.gt_samples) > 0, 30.0):
            raise StepFailed("ground_truth", "no sample on /ath/ground_truth/robot_pose within 30 s")
        handle = c.send_goal(*GOAL, timeout_s=30.0)
        if handle is None:
            raise StepFailed("goal", "NavigateToPose goal was not accepted within 30 s")
        dispatch = c.publish_dispatch()
        status = c.wait_result(handle, dispatch, GOAL_LIMIT_S, wall_timeout_s=GOAL_LIMIT_S * 5)
        end_t = c.sim_time
        c.wait_sim_seconds(2.0, wall_timeout_s=30.0)
        self.result["nav2_result"] = status
        self.result["dispatch_sim_time_s"] = round(dispatch, 3)
        self.result["result_sim_time_s"] = round(end_t - dispatch, 3) if end_t is not None else None
        samples = [s for s in c.gt_samples if s.t >= dispatch]
        if not samples:
            raise StepFailed("ground_truth", "no Ground_Truth sample after goal dispatch")
        final = samples[-1]
        gx, gy, gyaw = GOAL
        dist = math.hypot(final.x - gx, final.y - gy)
        self.result["final_true_pose"] = {"x": round(final.x, 4), "y": round(final.y, 4),
                                          "yaw": round(final.yaw, 4), "t": round(final.t, 3)}
        self.result["true_pose_to_goal_m"] = round(dist, 4)
        self.result["yaw_error_rad"] = round(angle_diff(final.yaw, gyaw), 4)
        self.result["ground_truth_samples"] = len(c.gt_samples)
        self.result["within_tolerance"] = dist <= TOLERANCE_M
        if status != "SUCCEEDED":
            raise StepFailed("goal", f"NavigateToPose ended {status}; true pose {dist:.3f} m from the goal")
        if dist > TOLERANCE_M:
            raise StepFailed("goal", f"Nav2 reported SUCCEEDED but the true pose is {dist:.3f} m from the goal "
                                     f"(tolerance {TOLERANCE_M} m)")

    def lidar_yaw(self) -> None:
        yaw = self.client.lookup_yaw("base_link", "rplidar_link", timeout_s=10.0)
        self.result["lidar_mount_yaw_rad"] = None if yaw is None else round(yaw, 4)
        self.result["lidar_mount_yaw_deg"] = None if yaw is None else round(math.degrees(yaw), 2)

    def teardown(self) -> None:
        if self.session is not None:
            leftovers = self.session.teardown(order=("gt_bridge", "launch", "xvfb"))
            self.result.setdefault("leftover_processes", []).extend(leftovers)
            self.session = None

    def run(self) -> dict[str, Any]:
        started = self.deps.monotonic()
        try:
            self.result["versions"] = record_versions(self.deps)
            self.render_and_launch()
            self.activate()
            self.lidar_yaw()
            self.navigate()
        except StepFailed as exc:
            self.result["failed_step"] = exc.step
            self.result["effect"] = exc.effect
        finally:
            self.teardown()
            if self.client is not None:
                self.client.close()
            self.check_launch_log()
            self.result["wall_time_s"] = round(self.deps.monotonic() - started, 1)
        return self.result

    def check_launch_log(self) -> None:
        """Requirement 1.3: no process died and no traceback before teardown began."""
        launch = self.result.get("launch")
        if not launch:
            return
        findings = session_mod.launch_log_findings(self.deps.read_text(self.out_dir / launch["log"]))
        self.result["launch_log_check"] = findings
        if findings["unhandled_before_teardown"] and self.result["failed_step"] is None:
            self.result["failed_step"] = "launch"
            self.result["effect"] = "unhandled error before teardown: " + findings["unhandled_before_teardown"][0]


def write_result(result: dict[str, Any], out_path: Path, stamp: repro.Stamp) -> Path:
    return repro.write_stamped_json(out_path, result, stamp)
