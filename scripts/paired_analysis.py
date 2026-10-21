"""Write results/experiment/paired_analysis.json from the committed experiment results (harness/experiment/analysis.py).

Reads results/experiment/experiment.json (condition order, Fault windows, set seed), the per-condition JUnit
files beside it, and Nav2's goal tolerance from config/nav2_params_ath.yaml; runs nothing in the simulator.

Usage: python scripts/paired_analysis.py [--repo .]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from harness import repro
from harness.experiment import analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paired analysis of the committed experiment results.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    results = args.repo / "results" / "experiment"
    report = json.loads((results / "experiment.json").read_text(encoding="utf-8"))
    params = yaml.safe_load((args.repo / "config" / "nav2_params_ath.yaml").read_text(encoding="utf-8"))
    out = analysis.analyze(results / "junit", [row["condition"] for row in report["conditions"]],
                           (report.get("settings") or {}).get("faults") or {})
    out["oracle_goal_position_tol_m"] = report["settings"]["thresholds"]["goal_position_tol_m"]
    out["nav2_xy_goal_tolerance_m"] = analysis.nav2_xy_goal_tolerance(params)
    out["experiment_stamp"] = report["stamp"]
    path = repro.write_stamped_json(results / "paired_analysis.json", out,
                                    repro.make_stamp(seed=report["set_seed"], command="python scripts/paired_analysis.py",
                                                     cwd=args.repo))
    print(f"paired_analysis: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
