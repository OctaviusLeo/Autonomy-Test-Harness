"""Headless-render check (Requirements 8.2, 8.3): does the lidar render a known scene in the container?

With no display attached, it starts the arena through the stock launch (robot at the origin, facing +x),
spawns one 1.0 m box whose near face is 2.0 m in front of the lidar, reads a fresh ``/scan``, and checks
that the forward beam (bearing 270 deg: the lidar is mounted at +90 deg) measures 2.0 m within 0.05 m and
that at least 300 ranges are finite. The lidar sits 0.04 m behind the robot's center (TF at M0).

Usage (inside the image): python -m harness.render_check --out /results
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from harness import repro
from harness.runner import session as session_mod
from harness.runner.run_scenario import obstacle_sdf, spawn_command
from harness.runner.session import LaunchSpec, Session

EXPECTED_RANGE_M = 2.0
TOLERANCE_M = 0.05
MIN_FINITE = 300
FORWARD_BEARING_DEG = 270.0
LIDAR_OFFSET_X_M = -0.04  # base_link -> rplidar_link translation along x (TF, M0)
BOX_SIZE_M = 1.0
WORLD = "empty_10x10"
ROBOT = "turtlebot4"
OGRE_LOG = Path.home() / ".gz" / "rendering" / "ogre2.log"


def box_obstacle():
    """The known scene: a 1.0 m cube centered so its near face is EXPECTED_RANGE_M ahead of the lidar."""
    from harness.schema.scenario import BoxObstacle

    x = LIDAR_OFFSET_X_M + EXPECTED_RANGE_M + BOX_SIZE_M / 2
    return BoxObstacle.model_validate({"shape": "box", "size": {"x": BOX_SIZE_M, "y": BOX_SIZE_M, "z": BOX_SIZE_M},
                                       "pose": {"x": x, "y": 0.0, "yaw": 0.0}})


def beam_index(n: int, angle_min: float, angle_increment: float, bearing_deg: float) -> int:
    """The ray whose bearing is closest to ``bearing_deg``."""
    best, best_gap = 0, math.inf
    for i in range(n):
        b = math.degrees(angle_min + i * angle_increment) % 360.0
        gap = abs((b - bearing_deg + 180.0) % 360.0 - 180.0)
        if gap < best_gap:
            best, best_gap = i, gap
    return best


def evaluate(ranges, angle_min: float, angle_increment: float) -> dict[str, Any]:
    i = beam_index(len(ranges), angle_min, angle_increment, FORWARD_BEARING_DEG)
    measured = float(ranges[i])
    finite = sum(1 for r in ranges if math.isfinite(r))
    ok_range = math.isfinite(measured) and abs(measured - EXPECTED_RANGE_M) <= TOLERANCE_M
    return {"beam_index": i, "beam_bearing_deg": round(math.degrees(angle_min + i * angle_increment) % 360.0, 3),
            "measured_range_m": round(measured, 4), "expected_range_m": EXPECTED_RANGE_M, "tolerance_m": TOLERANCE_M,
            "finite_ranges": finite, "total_ranges": len(ranges), "min_finite": MIN_FINITE,
            "passed": ok_range and finite >= MIN_FINITE}


@dataclasses.dataclass
class RenderDeps:
    make_session: Callable[[Path, dict], Session] = lambda out, env: Session(out, env)
    make_client: Callable[[], Any] = None  # set by main(): nav_client.HarnessClient
    read_text: Callable[[Path], str] = lambda p: Path(p).read_text(errors="replace") if Path(p).exists() else ""
    copy: Callable[[Path, Path], Any] = lambda a, b: shutil.copyfile(a, b) if Path(a).exists() else None
    env: Callable[[], dict] = lambda: dict(os.environ)
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def run_check(out: Path, deps: RenderDeps, repo: Path, params_path: str) -> dict[str, Any]:
    env = session_mod.isolation_env(deps.env(), 0)
    result: dict[str, Any] = {"display": env.get("DISPLAY"), "render_mode": env.get("ATH_RENDER_MODE", "egl"),
                              "passed": False}
    session = deps.make_session(out, env)
    client = None
    try:
        spec = LaunchSpec(str(repo / "worlds" / f"{WORLD}.sdf"), str(repo / "maps" / f"{WORLD}.yaml"), params_path,
                          0.0, 0.0, 0.0)
        session.start_launch(spec)
        result["launch_command"] = spec.command()
        end = deps.monotonic() + 180.0
        while deps.monotonic() < end and ROBOT not in session.models():
            deps.sleep(2.0)
        if ROBOT not in session.models():
            result["problem"] = "the robot never appeared in gz model --list"
            return result
        box = box_obstacle()
        sdf = out / "box.sdf"
        sdf.write_text(obstacle_sdf(box, "render_box"), encoding="utf-8")
        spawn = session.run(spawn_command(WORLD, sdf, "render_box", box), timeout=60.0, env=env)
        result["box"] = {"center_x": box.pose.x, "center_y": 0.0, "size_m": BOX_SIZE_M, "spawn_exit": spawn.returncode}
        if spawn.returncode != 0 or "render_box" not in session.models():
            result["problem"] = "the box was not spawned"
            return result
        client = deps.make_client()
        if not client.wait_for_scan(1, 60.0):
            result["problem"] = "no /scan message"
            return result
        seen = client.scan_count
        client.spin_until(lambda: client.scan_count >= seen + 10, 30.0)  # about 1 s of scans after the spawn
        scan = client.last_scan
        result.update(evaluate(list(scan.ranges), scan.angle_min, scan.angle_increment))
        result["scan_stamp_s"] = round(scan.header.stamp.sec + scan.header.stamp.nanosec * 1e-9, 3)
        result["renderer"] = session_mod.ogre_renderer(deps.read_text(OGRE_LOG))
        deps.copy(OGRE_LOG, out / "ogre2.log")
        return result
    finally:
        if client is not None:
            client.close()
        result["leftover_processes"] = session.teardown(order=("launch",))


def report_text(result: dict[str, Any], stamp: repro.Stamp) -> str:
    lines = [
        "Headless-render check (Requirement 8.3): generated by scripts/check_headless_render.sh; do not edit.",
        f"Command: {stamp.command}",
        f"Seed: {stamp.seed}",
        f"Commit: {stamp.commit}",
        f"Result: {'PASS' if result['passed'] else 'FAIL'}",
        "",
        "Scene: arena empty_10x10, robot at (0, 0, yaw 0), one 1.0 m box with its near face 2.0 m ahead of the lidar.",
        f"Display attached: {result.get('display') or 'none'}; render mode: {result.get('render_mode')}",
        f"Renderer (ogre2.log): {result.get('renderer')}",
    ]
    if "measured_range_m" in result:
        lines += [
            f"Forward beam: index {result['beam_index']}, bearing {result['beam_bearing_deg']} deg, "
            f"measured {result['measured_range_m']} m, expected {result['expected_range_m']} +- {result['tolerance_m']} m",
            f"Finite ranges: {result['finite_ranges']} of {result['total_ranges']} (need at least {result['min_finite']})",
            f"Scan stamp: {result['scan_stamp_s']} s of simulation time",
        ]
    if result.get("problem"):
        lines.append(f"Problem: {result['problem']}")
    lines.append(f"Leftover processes after teardown: {result.get('leftover_processes')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless-render check.")
    parser.add_argument("--out", type=Path, default=Path("/results"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    os.environ.update(session_mod.isolation_env(os.environ, 0))

    from harness.m0 import stock_params_path
    from harness.runner import nav_client

    nav_client.init_ros()
    deps = RenderDeps(make_client=lambda: nav_client.HarnessClient(scan_topic="/scan"))
    result = run_check(args.out, deps, args.repo, stock_params_path())
    nav_client.shutdown_ros()
    text = report_text(result, repro.make_stamp(seed=0))
    repro.write_text_atomic(args.out / "headless_render_check.txt", text)
    print(text, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
