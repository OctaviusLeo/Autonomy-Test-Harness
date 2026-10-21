"""Paired analysis of the experiment, from its committed JUnit reports (``results/experiment/junit/``).

Every condition runs the same base Scenarios, so each Fault condition is compared with the no-Fault baseline
Scenario by Scenario: the pairs that passed in both, failed in both, passed only without the Fault (``lost``),
or passed only with it (``gained``), and the exact two-sided McNemar p-value on the discordant pairs. From each
failure's detail it also lists the runs Nav2 reported ``SUCCEEDED`` that the Oracle failed, with the true final
distance to the goal, and the collisions, with the minimum clearance.

Usage: python scripts/paired_analysis.py [--repo .]   (writes results/experiment/paired_analysis.json)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from harness.experiment.stats import mcnemar_exact

CASE = re.compile(r"^(?P<scenario>[^\[\]]+)(?:\[(?P<condition>\w+)\])?$")  # harness.reporting.junit.case_name
NAV2 = re.compile(r"nav2_result=(\w+)")
DISTANCE = re.compile(r"(\d+(?:\.\d+)?) m from goal")
CLEARANCE = re.compile(r"min clearance (-?\d+(?:\.\d+)?) m")


def read_junit(path: Path, condition: str) -> list[dict[str, Any]]:
    """One entry per test case of ``condition``: Scenario, passed, reason, detail, and Nav2's reported result."""
    runs = []
    for case in ET.parse(path).getroot().iter("testcase"):
        name = case.get("name", "")
        match = CASE.match(name)
        if not match or (match["condition"] or "none") != condition:
            raise ValueError(f"{path}: test case name {name!r} is not a Scenario of condition {condition}")
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        nav2 = NAV2.search(case.findtext("system-out") or "")
        runs.append({"scenario_id": match["scenario"], "passed": problem is None,
                     "reason": "" if problem is None else problem.get("message", ""),
                     "detail": "" if problem is None else problem.text or "",
                     "nav2_result": nav2.group(1) if nav2 else None})
    return runs


def _number(pattern: re.Pattern, text: str) -> float | None:
    match = pattern.search(text)
    return float(match.group(1)) if match else None


def analyze(junit_dir: Path, conditions: list[str], fault_windows: dict[str, Any],
            baseline: str = "none") -> dict[str, Any]:
    """Per-condition paired counts against ``baseline``, the false successes, and the collisions."""
    runs = {name: read_junit(Path(junit_dir) / f"{name}.xml", name) for name in conditions}
    base = {r["scenario_id"]: r["passed"] for r in runs[baseline]}
    rows, false_successes, collisions = [], [], []
    for name in conditions:
        passed = {r["scenario_id"]: r["passed"] for r in runs[name]}
        if set(passed) != set(base):
            raise ValueError(f"condition {name} does not have the same Scenarios as {baseline}")
        lost = sum(base[s] and not passed[s] for s in base)
        gained = sum(passed[s] and not base[s] for s in base)
        window = (fault_windows.get(name) or {}).get("window_s")
        rows.append({"condition": name, "n": len(passed), "passes": sum(passed.values()),
                     "pass_pct": round(100 * sum(passed.values()) / len(passed), 1),
                     "window_s": window, "window_length_s": None if window is None else round(window[1] - window[0], 3),
                     "both_passed": sum(base[s] and passed[s] for s in base),
                     "both_failed": sum(not base[s] and not passed[s] for s in base),
                     "lost": lost, "gained": gained,
                     "mcnemar_p": None if name == baseline else float(f"{mcnemar_exact(lost, gained):.3g}")})
        for r in runs[name]:
            if not r["passed"] and r["nav2_result"] == "SUCCEEDED":
                false_successes.append({"scenario_id": r["scenario_id"], "condition": name, "reason": r["reason"],
                                        "final_distance_m": _number(DISTANCE, r["detail"])})
            if r["reason"] == "collision":
                collisions.append({"scenario_id": r["scenario_id"], "condition": name,
                                   "min_clearance_m": _number(CLEARANCE, r["detail"])})
    return {"baseline": baseline, "conditions": rows, "false_successes": false_successes, "collisions": collisions}


def nav2_xy_goal_tolerance(params: dict[str, Any]) -> float:
    """The position tolerance Nav2's goal checker applies to its own pose estimate."""
    return float(params["controller_server"]["ros__parameters"]["general_goal_checker"]["xy_goal_tolerance"])
