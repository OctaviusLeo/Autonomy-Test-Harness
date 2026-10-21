"""Shared test helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_HASH = "a1b2c3d4" * 5


def _load_script(name: str):
    """Import scripts/<name>.py as a module (scripts/ is not a package)."""
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ath_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def load_script():
    return _load_script


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def write_file(repo: Path, rel: str, content) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


@pytest.fixture
def docs_repo(tmp_path) -> Path:
    """A synthetic repository with every results file the README generator reads."""
    r = tmp_path / "repo"
    write_file(r, "docs/README.template.md", (REPO_ROOT / "docs" / "README.template.md").read_text(encoding="utf-8"))
    write_file(r, "config/smoke_suite.yaml", "ids: all\n")
    rows = [{"condition": c, "n": 30, "passes": p, "pass_rate": round(p / 30, 4),
             "ci95": {"low": lo, "high": hi}, "errored_after_retry": 0, "scenario_ids": []}
            for c, p, lo, hi in (("none", 27, 0.7438, 0.9654), ("latency", 15, 0.3315, 0.6685))]
    write_file(r, "results/experiment/experiment.json", {
        "base_set": "scenarios/experiment30", "set_seed": 303, "base_scenarios": 30, "conditions": rows,
        "segments": 1, "total_run_time_s": 9876.5, "total_run_time_h": 2.74,
        "settings": {"faults": {"none": None, "latency": {"window_s": [5.0, 65.0], "params": {"latency_ms": 300.0}}},
                     "thresholds": {"footprint_radius_m": 0.18, "collision_threshold_m": 0.02,
                                    "goal_position_tol_m": 0.3, "goal_orientation_tol_rad": 0.3,
                                    "startup_timeout_s": 180.0, "settle_s": 2.0}},
        "stamp": {"command": "bash scripts/run_experiment.sh", "seed": 303, "commit": DOCS_HASH}})
    paired = [{"condition": "none", "n": 30, "passes": 27, "pass_pct": 90.0, "window_s": None, "window_length_s": None,
               "both_passed": 27, "both_failed": 3, "lost": 0, "gained": 0, "mcnemar_p": None},
              {"condition": "latency", "n": 30, "passes": 15, "pass_pct": 50.0, "window_s": [5.0, 65.0],
               "window_length_s": 60.0, "both_passed": 14, "both_failed": 2, "lost": 13, "gained": 1,
               "mcnemar_p": 0.00183}]
    write_file(r, "results/experiment/paired_analysis.json", {
        "baseline": "none", "conditions": paired,
        "false_successes": [{"scenario_id": "exp30-013", "condition": "latency", "reason": "timeout",
                             "final_distance_m": 0.331}],
        "collisions": [{"scenario_id": "exp30-008", "condition": "latency", "min_clearance_m": -0.005}],
        "oracle_goal_position_tol_m": 0.3, "nav2_xy_goal_tolerance_m": 0.25,
        "stamp": {"command": "python scripts/paired_analysis.py", "seed": 303, "commit": DOCS_HASH}})
    write_file(r, "results/summary.md", "# Paired_Experiment summary\n\n95% Wilson | none | 30 | 27 | 0.9 |\n"
                                        "Total run time: 9876.5 s (2.74 h)\n")
    write_file(r, "results/m2_fixed10/summary.json", {
        "repeats": 3, "per_repeat": [{"repeat": k, "runs": 10, "passes": 10} for k in (1, 2, 3)],
        "per_scenario": [{"scenario_id": f"fixed10-00{i}"} for i in range(10)], "outcome_changed": [],
        "stamp": {"command": "bash scripts/run_suite.sh smoke --repeat 3 --out /home/u/ath-shared/runs/m2", "seed": 0,
                  "commit": DOCS_HASH}})
    write_file(r, "results/m3_fault_check.json", {
        "faults": [{"fault": "latency", "confined_to_window": True, "verdict": {"passed": True}, "measured_delay_s": 0.302},
                   {"fault": "freeze", "confined_to_window": True, "verdict": {"passed": False}}],
        "stamp": {"command": "bash scripts/run_suite.sh runs/m3_conditions", "seed": 0, "commit": DOCS_HASH}})
    write_file(r, "results/m0_baseline.json", {
        "nav2_result": "SUCCEEDED", "true_pose_to_goal_m": 0.1358, "tolerance_m": 0.3,
        "render": {"method": "egl", "renderer": "llvmpipe (LLVM 20.1.2, 256 bits)"},
        "stamp": {"command": "bash scripts/run_m0.sh", "seed": 0, "commit": DOCS_HASH}})
    write_file(r, "results/headless_render_check.txt",
               f"Command: bash scripts/check_headless_render.sh\nSeed: 0\nCommit: {DOCS_HASH}\nResult: PASS\n"
               "Forward beam: index 269, bearing 269.613 deg, measured 2.0009 m, expected 2.0 +- 0.05 m\n"
               "Finite ranges: 360 of 360 (need at least 300)\n")
    return r
