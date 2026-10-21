"""Tests for the paired analysis of the experiment (harness/experiment/analysis.py, scripts/paired_analysis.py)
and the exact McNemar test (harness/experiment/stats.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.experiment import analysis
from harness.experiment.stats import mcnemar_exact

from conftest import write_file

HASH = "c" * 40
WINDOWS = {"none": None, "freeze": {"window_s": [5.0, 15.0], "params": {}}}


def junit(condition: str, cases: dict[str, str | None]) -> str:
    """A JUnit file in harness/reporting/junit.py's format; a case maps to None (passed) or a failure."""
    parts = [f'<testsuite name="experiment.{condition}" tests="{len(cases)}">']
    for scenario, failure in cases.items():
        name = scenario if condition == "none" else f"{scenario}[{condition}]"  # junit.case_name
        parts.append(f'<testcase classname="ath.experiment.{condition}" name="{name}">')
        nav2 = "SUCCEEDED"
        if failure == "error":
            parts.append('<error message="errored: launch">no clock</error>')
        elif failure is not None:
            reason, nav2, detail = failure.split("|")
            parts.append(f'<failure message="{reason}">{detail}</failure>')
        parts.append(f"<system-out>seed=1 bag=/b nav2_result={nav2}</system-out></testcase>")
    return "\n".join(parts + ["</testsuite>"])


@pytest.fixture
def junit_dir(tmp_path) -> Path:
    d = tmp_path / "junit"
    write_file(d, "none.xml", junit("none", {"s-0": None, "s-1": None, "s-2": None,
                                             "s-3": "timeout|TIME_LIMIT|goal not reached; 2.000 m from goal"}))
    write_file(d, "freeze.xml", junit("freeze", {
        "s-0": "timeout|SUCCEEDED|goal not reached within 90.0 s; nav2_result=SUCCEEDED; 0.331 m from goal",
        "s-1": "collision|TIME_LIMIT|min clearance -0.005 m &lt; 0.02 m; 3.287 m from goal",
        "s-2": None, "s-3": None}))
    return d


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0 and mcnemar_exact(1, 0) == 1.0
    assert mcnemar_exact(6, 0) == pytest.approx(2 / 64)
    assert mcnemar_exact(3, 1) == pytest.approx(2 * 5 / 16) and mcnemar_exact(1, 3) == mcnemar_exact(3, 1)
    assert mcnemar_exact(30, 0) == pytest.approx(2 / 2 ** 30)
    with pytest.raises(ValueError, match="non-negative"):
        mcnemar_exact(-1, 2)


def test_analyze_counts_pairs_false_successes_and_collisions(junit_dir):
    out = analysis.analyze(junit_dir, ["none", "freeze"], WINDOWS)
    none, freeze = out["conditions"]
    assert none == {"condition": "none", "n": 4, "passes": 3, "pass_pct": 75.0, "window_s": None,
                    "window_length_s": None, "both_passed": 3, "both_failed": 1, "lost": 0, "gained": 0,
                    "mcnemar_p": None}
    assert (freeze["passes"], freeze["pass_pct"], freeze["window_length_s"]) == (2, 50.0, 10.0)
    assert (freeze["both_passed"], freeze["both_failed"], freeze["lost"], freeze["gained"]) == (1, 0, 2, 1)
    assert freeze["mcnemar_p"] == 1.0
    assert out["false_successes"] == [{"scenario_id": "s-0", "condition": "freeze", "reason": "timeout",
                                       "final_distance_m": 0.331}]
    assert out["collisions"] == [{"scenario_id": "s-1", "condition": "freeze", "min_clearance_m": -0.005}]


def test_errored_runs_count_as_not_passed_and_scenarios_must_match(junit_dir):
    write_file(junit_dir, "freeze.xml", junit("freeze", {"s-0": "error", "s-1": None, "s-2": None, "s-3": None}))
    freeze = analysis.analyze(junit_dir, ["none", "freeze"], WINDOWS)["conditions"][1]
    assert (freeze["passes"], freeze["lost"], freeze["gained"]) == (3, 1, 1)
    write_file(junit_dir, "freeze.xml", junit("freeze", {"s-0": None}))
    with pytest.raises(ValueError, match="same Scenarios"):
        analysis.analyze(junit_dir, ["none", "freeze"], WINDOWS)
    write_file(junit_dir, "freeze.xml", '<testsuite><testcase name="s-0[latency]"/></testsuite>')
    with pytest.raises(ValueError, match="not a Scenario of condition freeze"):
        analysis.read_junit(junit_dir / "freeze.xml", "freeze")
    assert analysis.read_junit(junit_dir / "none.xml", "none")[0]["scenario_id"] == "s-0"


def test_script_writes_stamped_analysis(junit_dir, tmp_path, load_script, monkeypatch):
    repo = tmp_path / "repo"
    for path in junit_dir.iterdir():
        write_file(repo, f"results/experiment/junit/{path.name}", path.read_text())
    write_file(repo, "results/experiment/experiment.json", {
        "set_seed": 303, "conditions": [{"condition": "none"}, {"condition": "freeze"}],
        "settings": {"faults": WINDOWS, "thresholds": {"goal_position_tol_m": 0.3}},
        "stamp": {"command": "bash scripts/run_experiment.sh", "seed": 303, "commit": HASH}})
    write_file(repo, "config/nav2_params_ath.yaml",
               "controller_server:\n  ros__parameters:\n    general_goal_checker:\n      xy_goal_tolerance: 0.25\n")
    monkeypatch.setenv("ATH_COMMIT", "d" * 40)
    assert load_script("paired_analysis").main(["--repo", str(repo)]) == 0
    out = json.loads((repo / "results/experiment/paired_analysis.json").read_text())
    assert out["nav2_xy_goal_tolerance_m"] == 0.25 and out["oracle_goal_position_tol_m"] == 0.3
    assert out["experiment_stamp"]["commit"] == HASH
    assert out["stamp"] == {"command": "python scripts/paired_analysis.py", "seed": 303, "commit": "d" * 40}
    assert [row["condition"] for row in out["conditions"]] == ["none", "freeze"]
