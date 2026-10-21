"""Generate README.md from docs/README.template.md and the files under results/ (Requirements 11.1-11.3, 0.1).

Every number the README states is read from a generated results file and printed next to the command, seed,
and commit that produced it. ``scripts/check_traceability.py`` then checks that every number in README.md and
results/summary.md appears in a generated file under results/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def load(repo: Path, rel: str) -> Any:
    path = repo / rel
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"build_docs: {rel} is missing; run the step that generates it") from exc
    return json.loads(text) if rel.endswith(".json") else text


SHARED_DIR = re.compile(r"/home/[^/\s`]+/ath-shared")


def stamp_line(stamp: dict[str, Any]) -> str:
    # A stamped command names the host's shared directory; the README shows it as $ATH_SHARED.
    command = SHARED_DIR.sub("$ATH_SHARED", stamp["command"])
    return f"Command `{command}`, seed {stamp['seed']}, commit `{stamp['commit']}`."


def experiment_table(report: dict[str, Any], analysis: dict[str, Any]) -> str:
    paired = {row["condition"]: row for row in analysis["conditions"]}
    lines = [f"| Condition | Fault window (s after dispatch) | Passed | 95% Wilson interval | "
             f"Lost / gained vs. {analysis['baseline']} | Exact McNemar p | Errored after retry |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["conditions"]:
        p = paired[row["condition"]]
        window = "-" if p["window_s"] is None else f"{p['window_s'][0]}-{p['window_s'][1]}"
        versus = "-" if p["mcnemar_p"] is None else f"{p['lost']} / {p['gained']}"
        mcnemar = "-" if p["mcnemar_p"] is None else p["mcnemar_p"]
        lines.append(f"| {row['condition']} | {window} | {row['passes']} of {row['n']} ({p['pass_pct']}%) | "
                     f"[{row['ci95']['low']}, {row['ci95']['high']}] | {versus} | {mcnemar} | "
                     f"{row['errored_after_retry']} |")
    return "\n".join(lines)


def fault_windows(analysis: dict[str, Any]) -> str:
    """E.g. "Each fault starts 5.0 s after the goal is sent and lasts 10.0 s (freeze) or 60.0 s (latency)."."""
    by_start: dict[float, dict[float, list[str]]] = {}
    for row in analysis["conditions"]:
        if row["window_s"] is not None:
            by_start.setdefault(row["window_s"][0], {}).setdefault(row["window_length_s"], []).append(row["condition"])
    clauses = [f"starts {start} s after the goal is sent and lasts "
               + " or ".join(f"{length} s ({', '.join(names)})" for length, names in sorted(lengths.items()))
               for start, lengths in sorted(by_start.items())]
    return "Each fault " + "; or ".join(clauses) + "."


def false_successes(analysis: dict[str, Any]) -> str:
    runs = analysis["false_successes"]
    listed = ", ".join(f"`{r['scenario_id']}` under {r['condition']} ({r['final_distance_m']} m)" for r in runs)
    runs_word = "run" if len(runs) == 1 else "runs"
    return (f"In {len(runs)} {runs_word} Nav2 reported `SUCCEEDED` but the robot's true final position was outside "
            f"the Oracle's {analysis['oracle_goal_position_tol_m']} m tolerance: {listed}. Nav2's goal checker "
            f"accepts {analysis['nav2_xy_goal_tolerance_m']} m, measured on its own (AMCL) pose estimate.")


def collisions(analysis: dict[str, Any]) -> str:
    runs = analysis["collisions"]
    listed = ", ".join(f"`{r['scenario_id']}` under {r['condition']} (minimum clearance {r['min_clearance_m']} m)"
                       for r in runs)
    subject = "collision is a small overlap" if len(runs) == 1 else "collisions are small overlaps"
    return f"The recorded {subject} of the disc footprint with an obstacle: {listed}."


def analysis_stamp(analysis: dict[str, Any]) -> str:
    return (f"Paired counts, McNemar p-values, false successes and collisions: "
            f"`results/experiment/paired_analysis.json`, generated from the committed JUnit files. "
            f"{stamp_line(analysis['stamp'])}")


def experiment_details(report: dict[str, Any]) -> str:
    lines = [f"Total run time: {report['total_run_time_s']} s ({report['total_run_time_h']} h) over {report['segments']} "
             f"segment(s), the sum of every run's wall-clock duration plus report generation. "
             f"Base set `{report['base_set']}`, set seed {report['set_seed']}."]
    settings = report.get("settings") or {}
    if settings.get("faults"):
        parts = []
        for name, fault in settings["faults"].items():
            if fault is None:
                continue
            params = ", ".join(f"{k} {v}" for k, v in fault["params"].items()) or "no parameters"
            parts.append(f"`{name}` ({params}; window {fault['window_s'][0]}-{fault['window_s'][1]} s after dispatch)")
        lines += ["", "Fault settings: " + "; ".join(parts) + "."]
    if settings.get("thresholds"):
        t = settings["thresholds"]
        lines += ["", f"Oracle: footprint radius {t['footprint_radius_m']} m, collision below "
                      f"{t['collision_threshold_m']} m clearance, goal within {t['goal_position_tol_m']} m and "
                      f"{t['goal_orientation_tol_rad']} rad of the goal, judged from ground truth only."]
    return "\n".join(lines)


def experiment_stamp(report: dict[str, Any]) -> str:
    return ("Generated by `bash scripts/run_experiment.sh` into `results/experiment/experiment.json` and "
            f"`results/summary.md`. {stamp_line(report['stamp'])}")


def m2_summary(summary: dict[str, Any], smoke_ids: Any) -> str:
    repeats = ", ".join(f"repeat {r['repeat']}: {r['passes']} of {r['runs']}" for r in summary["per_repeat"])
    changed = summary["outcome_changed"]
    selection = ("the smoke suite is every `fixed10` Scenario" if smoke_ids == "all"
                 else f"the smoke suite is {', '.join(smoke_ids)}")
    return (f"The {len(summary['per_scenario'])} fixed Scenarios, {summary['repeats']} times with no Fault: {repeats} "
            f"passed; outcome changed between repeats for {len(changed)} Scenario(s){': ' + ', '.join(changed) if changed else ''}. "
            f"So {selection} (`config/smoke_suite.yaml`). `results/m2_fixed10/summary.json`. {stamp_line(summary['stamp'])}")


def m3_summary(check: dict[str, Any]) -> str:
    parts = []
    for e in check["faults"]:
        verdict = (e.get("verdict") or {}).get("passed")
        extra = f", measured delay {e['measured_delay_s']} s" if e.get("measured_delay_s") is not None else ""
        parts.append(f"`{e['fault']}` confined {e['confined_to_window']} (Verdict passed {verdict}{extra})")
    return ("One run of `exp30-000` per Fault type, each bag checked scan by scan against the Fault's window: "
            + "; ".join(parts) + f". `results/m3_fault_check.json`. {stamp_line(check['stamp'])}")


def m0_summary(m0: dict[str, Any]) -> str:
    return (f"One `NavigateToPose` goal from a script in the headless stock simulation: Nav2 reported "
            f"{m0['nav2_result']} and the true final pose was {m0['true_pose_to_goal_m']} m from the goal "
            f"(tolerance {m0['tolerance_m']} m); rendering method {m0['render']['method']} "
            f"(`{m0['render']['renderer']}`). `results/m0_baseline.json`. {stamp_line(m0['stamp'])}")


def render_summary(text: str) -> str:
    result = re.search(r"^Result: (\w+)", text, re.M)
    beam = re.search(r"measured ([\d.]+) m, expected ([\d.]+) \+- ([\d.]+) m", text)
    finite = re.search(r"Finite ranges: (\d+) of (\d+)", text)
    commit = re.search(r"^Commit: ([0-9a-f]{40})", text, re.M)
    if not (result and beam and finite and commit):
        raise ValueError("results/headless_render_check.txt is not in the expected format")
    return (f"Headless-render check in the container with no display: {result.group(1)}; a box with its near face "
            f"{beam.group(2)} m ahead of the lidar measured {beam.group(1)} m (tolerance {beam.group(3)} m), "
            f"{finite.group(1)} of {finite.group(2)} ranges finite. `results/headless_render_check.txt` "
            f"(command `bash scripts/check_headless_render.sh`, seed 0, commit `{commit.group(1)}`).")


def values(repo: Path) -> dict[str, str]:
    report = load(repo, "results/experiment/experiment.json")
    analysis = load(repo, "results/experiment/paired_analysis.json")
    smoke = yaml.safe_load(load(repo, "config/smoke_suite.yaml")).get("ids", "all")
    return {
        "EXPERIMENT_TABLE": experiment_table(report, analysis),
        "FAULT_WINDOWS": fault_windows(analysis),
        "FALSE_SUCCESSES": false_successes(analysis),
        "COLLISIONS": collisions(analysis),
        "ANALYSIS_STAMP": analysis_stamp(analysis),
        "EXPERIMENT_DETAILS": experiment_details(report),
        "EXPERIMENT_STAMP": experiment_stamp(report),
        "M2_SUMMARY": m2_summary(load(repo, "results/m2_fixed10/summary.json"), smoke),
        "M3_SUMMARY": m3_summary(load(repo, "results/m3_fault_check.json")),
        "M0_SUMMARY": m0_summary(load(repo, "results/m0_baseline.json")),
        "RENDER_SUMMARY": render_summary(load(repo, "results/headless_render_check.txt")),
    }


def render(template: str, fills: dict[str, str]) -> str:
    missing = sorted(set(PLACEHOLDER.findall(template)) - set(fills))
    if missing:
        raise KeyError(f"no value for {missing}")
    return PLACEHOLDER.sub(lambda m: fills[m.group(1)], template)


def build(repo: Path) -> str:
    return render(load(repo, "docs/README.template.md"), values(repo))


# ----------------------------------------------------------------------------------------- traceability
URL = re.compile(r"https?://\S+")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.]*\d)(?![\w])")


def numbers_in(text: str) -> list[str]:
    """Numbers stated in prose and tables: URLs, version strings (``1.3.13``, ``v0.38.0``), and identifiers or
    hashes that mix digits with letters are not numbers here."""
    return NUMBER.findall(URL.sub(" ", text))


def as_float(token: str) -> float:
    return float(token)


def result_numbers(repo: Path) -> set[float]:
    found: set[float] = set()
    for path in (repo / "results").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".md", ".txt", ".xml"):
            found.update(as_float(t) for t in numbers_in(path.read_text(encoding="utf-8", errors="replace")))
    return found


def untraceable(repo: Path, files: tuple[str, ...] = ("README.md", "results/summary.md")) -> list[str]:
    known = result_numbers(repo)
    problems = []
    for rel in files:
        for token in numbers_in((repo / rel).read_text(encoding="utf-8")):
            if as_float(token) not in known:
                problems.append(f"{rel}: {token} does not appear in any generated file under results/")
    return problems
