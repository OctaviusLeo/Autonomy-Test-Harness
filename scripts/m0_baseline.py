"""M0 baseline entry point (runs inside the ath-sim image; scripts/run_m0.sh starts it).

Usage: python scripts/m0_baseline.py --out /results [--repo /opt/ath]
Writes <out>/m0_baseline.json (stamped: command, seed 0, commit) and the evidence files it names.
Exits non-zero when a step fails; the JSON then names the failing step and its observed effect.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from harness import m0, repro
from harness.runner import session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 headless single-goal baseline.")
    parser.add_argument("--out", type=Path, default=Path("/results"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    os.environ.update(session.isolation_env(os.environ, 0))  # before rclpy reads ROS_DOMAIN_ID

    from harness.runner import nav_client

    nav_client.init_ros()
    deps = m0.M0Deps(make_client=lambda: nav_client.HarnessClient(scan_topic="/scan"))
    result = m0.M0Baseline(args.out, deps, args.repo, m0.stock_params_path()).run()
    nav_client.shutdown_ros()
    versions = result.get("versions", {})
    (args.out / "dpkg_query.txt").write_text(versions.get("dpkg_query", ""), encoding="utf-8")
    (args.out / "gz_sim_versions.txt").write_text(versions.get("gz_sim_versions", "") + "\n", encoding="utf-8")
    m0.write_result(result, args.out / "m0_baseline.json", repro.make_stamp(seed=0))
    print(f"m0_baseline: failed_step={result['failed_step']} nav2_result={result.get('nav2_result')} "
          f"true_pose_to_goal_m={result.get('true_pose_to_goal_m')}")
    return 0 if result["failed_step"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
