"""The Paired_Experiment (Requirements 10.1-10.5): the same 30 base Scenarios under seven conditions.

Conditions run in the order of ``config/experiment.yaml`` (``none`` first), and Scenarios in file order within
each. Every condition's Scenario files are the base Scenarios with that condition's one Fault added
(:func:`~harness.experiment.conditions.apply_condition`), so each Fault condition is paired with the no-Fault
baseline on identical Scenarios. Each run goes through the suite runner (child process, hard wall-clock limit,
teardown check). An errored run (no Verdict) is retried once and both attempts are kept. Restarted on the same
output directory, the experiment keeps completed runs and skips them, so an interrupted job resumes.

It writes ``<out>/experiment.json`` (stamped with the command, set seed, and commit): per condition n, passes,
pass rate, 95% Wilson interval, and runs still errored after the retry; the total run time (the sum of every
run's wall-clock duration plus report generation, so gaps between resumed segments are excluded) and the
number of segments. It also writes one JUnit file per condition and ``summary.md``.

Usage (inside the image): python -m harness.experiment.paired --out /results
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from harness import repro
from harness.experiment.conditions import Condition, apply_condition, load_conditions
from harness.experiment.stats import wilson_interval
from harness.reporting.junit import write_junit
from harness.reporting.records import outcome, write_atomic
from harness.reporting.summary import summary_markdown
from harness.runner import suite as suite_mod
from harness.runner.run_config import RunConfig, load_run_config
from harness.schema.validate import dump_scenario, load_scenario

REPO = Path(__file__).resolve().parents[2]
RUNS_PER_CONDITION_STRIDE = 1000  # run indices: condition k uses k * 1000 + scenario index (+ 500 for a retry)

Runner = Callable[[Path, Path, int, str], dict[str, Any]]


def suite_runner(cfg: RunConfig, run_config_path: Path, deps: suite_mod.SuiteDeps) -> Runner:
    def run(path: Path, out_dir: Path, run_index: int, condition: str) -> dict[str, Any]:
        return suite_mod.run_one(path, cfg, out_dir, run_index, condition, deps, run_config_path)
    return run


def write_condition_scenarios(base_paths: list[Path], condition: Condition, cond_dir: Path) -> list[Path]:
    """The condition's Scenario files (base Scenario plus the condition's Fault), same ids as the base."""
    paths = []
    for base in base_paths:
        scenario = apply_condition(load_scenario(base), condition)
        path = cond_dir / "scenarios" / f"{scenario.scenario_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = dump_scenario(scenario)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def move_aside(path: Path, label: str) -> Path | None:
    """Rename ``path`` (a bag or run directory from an earlier attempt) so a new run can use the name.

    ``ros2 bag record -o`` refuses an existing directory, so a retry or a resumed run needs the name free.
    """
    if not path.exists():
        return None
    k = 1
    while (target := path.with_name(f"{path.name}.{label}{k}")).exists():
        k += 1
    path.rename(target)
    return target


def completed(record_path: Path) -> dict[str, Any] | None:
    """A finished run's record (a Verdict, or an errored retry), or None if the run must (re)start."""
    if not record_path.exists():
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("status") != "errored" or record.get("attempt") == 2:
        return record
    return None


def run_with_retry(path: Path, cond_dir: Path, run_index: int, condition: str, runner: Runner,
                   clock: Callable[[], float]) -> dict[str, Any]:
    """Run once; if errored, keep that attempt under attempt_1/ and run again (both recorded)."""
    run_dir = cond_dir / "runs" / path.stem
    bag = cond_dir / "bags" / path.stem
    move_aside(bag, "interrupted")  # a partial bag from a run the job was stopped in
    started = clock()
    record = runner(path, cond_dir, run_index, condition)
    record["run_duration_s"] = round(clock() - started, 1)
    record["attempt"] = 1
    if record["status"] == "errored":
        first = dict(record)
        moved = move_aside(bag, "attempt")
        if moved is not None:
            first["bag_path"] = str(Path(str(first.get("bag_path", bag))).with_name(moved.name))
        attempt_dir = run_dir / "attempt_1"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        repro.write_text_atomic(attempt_dir / "run_record.json", json.dumps(first, indent=2) + "\n")
        started = clock()
        record = runner(path, cond_dir, run_index + RUNS_PER_CONDITION_STRIDE // 2, condition)
        record["run_duration_s"] = round(clock() - started, 1)
        record["attempt"] = 2
        record["first_attempt"] = {k: first.get(k) for k in ("status", "failing_step", "effect", "run_duration_s")}
    repro.write_text_atomic(run_dir / "run_record.json", json.dumps(record, indent=2) + "\n")
    return record


def condition_row(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    passes = sum(1 for r in records if outcome(r) == "pass")
    low, high = wilson_interval(passes, n)
    return {"condition": name, "n": n, "passes": passes, "pass_rate": round(passes / n, 4),
            "ci95": {"low": round(low, 4), "high": round(high, 4)},
            "errored_after_retry": sum(1 for r in records if r["status"] == "errored"),
            "scenario_ids": [r["scenario_id"] for r in records]}


def run_paired(base_paths: list[Path], conditions: dict[str, Condition], out_dir: Path, runner: Runner,
               clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """Run (or resume) every condition and return the per-condition records and rows."""
    clock = clock or time.monotonic
    out_dir = Path(out_dir)
    segments_path = out_dir / "segments.json"
    segments = json.loads(segments_path.read_text())["segments"] + 1 if segments_path.exists() else 1
    out_dir.mkdir(parents=True, exist_ok=True)
    repro.write_text_atomic(segments_path, json.dumps({"segments": segments}) + "\n")
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for k, (name, condition) in enumerate(conditions.items()):
        cond_dir = out_dir / name
        paths = write_condition_scenarios(base_paths, condition, cond_dir)
        records = []
        for i, path in enumerate(paths):
            record = completed(cond_dir / "runs" / path.stem / "run_record.json")
            if record is None:
                record = run_with_retry(path, cond_dir, k * RUNS_PER_CONDITION_STRIDE + i, name, runner, clock)
            records.append(record)
        by_condition[name] = records
    return {"segments": segments, "records": by_condition,
            "rows": [condition_row(name, records) for name, records in by_condition.items()]}


def total_run_time(records_by_condition: dict[str, list[dict[str, Any]]]) -> float:
    """Sum of every run's wall-clock duration, including first attempts of retried runs."""
    total = 0.0
    for records in records_by_condition.values():
        for r in records:
            total += float(r.get("run_duration_s") or 0.0)
            total += float((r.get("first_attempt") or {}).get("run_duration_s") or 0.0)
    return total


def experiment_markdown(report: dict[str, Any], records: list[dict[str, Any]], stamp: dict[str, Any]) -> str:
    lines = ["# Paired_Experiment summary", "",
             f"The {report['base_scenarios']} base Scenarios of `{report['base_set']}` (set seed {report['set_seed']}) "
             "under each condition; the same Scenarios in every condition. Pass rates with 95% Wilson score intervals.", "",
             "| Condition | Runs | Passed | Pass rate | 95% CI low | 95% CI high | Errored after retry |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["conditions"]:
        lines.append(f"| {row['condition']} | {row['n']} | {row['passes']} | {row['pass_rate']} | "
                     f"{row['ci95']['low']} | {row['ci95']['high']} | {row['errored_after_retry']} |")
    lines += ["", f"Total run time: {report['total_run_time_s']} s ({report['total_run_time_h']} h) "
                  f"over {report['segments']} segment(s).", ""]
    # The failed-runs table (reason, bag link, re-run command) and the stamp from the generic summary; its
    # per-type pass rates repeat the table above, so that section is left out.
    body = summary_markdown(records, "Runs", stamp)
    lines.append(body[body.index("## Failed runs"):])
    return "\n".join(lines)


def settings_used(conditions: dict[str, Condition], cfg: RunConfig | None) -> dict[str, Any]:
    """The Fault settings and Oracle thresholds the experiment ran with, kept beside its numbers."""
    faults = {name: None if c.fault is None else {"window_s": [c.fault.window.start_s, c.fault.window.end_s],
                                                   "params": c.fault.params.model_dump()}
              for name, c in conditions.items()}
    thresholds = None
    if cfg is not None:
        thresholds = {k: getattr(cfg, k) for k in ("footprint_radius_m", "collision_threshold_m", "goal_position_tol_m",
                                                   "goal_orientation_tol_rad", "startup_timeout_s", "settle_s")}
    return {"faults": faults, "thresholds": thresholds}


def write_reports(out_dir: Path, result: dict[str, Any], base_set: str, set_seed: int, stamp: repro.Stamp,
                  clock: Callable[[], float] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    clock = clock or time.monotonic
    started = clock()
    junit_dir = out_dir / "junit"
    for name, records in result["records"].items():
        write_junit(records, junit_dir / f"{name}.xml", f"experiment.{name}")
    all_records = [r for records in result["records"].values() for r in records]
    report = {"base_set": base_set, "set_seed": set_seed,
              "base_scenarios": result["rows"][0]["n"] if result["rows"] else 0,
              "conditions": result["rows"], "segments": result["segments"],
              "total_run_time_s": 0.0, "total_run_time_h": 0.0, "settings": settings}
    write_atomic(out_dir / "summary.md", experiment_markdown(report, all_records, stamp.to_dict()))
    report["total_run_time_s"] = round(total_run_time(result["records"]) + (clock() - started), 1)
    report["total_run_time_h"] = round(report["total_run_time_s"] / 3600, 2)
    write_atomic(out_dir / "summary.md", experiment_markdown(report, all_records, stamp.to_dict()))
    repro.write_stamped_json(out_dir / "experiment.json", report, stamp)
    return report


def regenerate_summary(run_dir: Path) -> str:
    """summary.md rebuilt from a finished run directory's experiment.json and RunRecords (for Gate A)."""
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "experiment.json").read_text(encoding="utf-8"))
    records = []
    for row in report["conditions"]:
        for scenario_id in row["scenario_ids"]:
            path = run_dir / row["condition"] / "runs" / scenario_id / "run_record.json"
            records.append(json.loads(path.read_text(encoding="utf-8")))
    return experiment_markdown(report, records, report["stamp"])


def main(argv: list[str] | None = None, runner: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run (or resume) the Paired_Experiment.")
    parser.add_argument("--out", type=Path, default=Path("/results"))
    parser.add_argument("--experiment", type=Path, default=REPO / "config" / "experiment.yaml")
    parser.add_argument("--run-config", type=Path, default=REPO / "config" / "run.yaml")
    args = parser.parse_args(argv)
    spec = yaml.safe_load(args.experiment.read_text(encoding="utf-8"))
    base_set = spec["base_set"]
    base_paths = sorted((REPO / base_set).glob("*.yaml"))
    conditions = load_conditions(args.experiment)
    cfg = load_run_config(args.run_config)
    runner = runner or suite_runner(cfg, args.run_config, suite_mod.SuiteDeps(write_reports=None))
    result = run_paired(base_paths, conditions, args.out, runner)
    report = write_reports(args.out, result, base_set, int(spec["set_seed"]), repro.make_stamp(seed=int(spec["set_seed"])),
                           settings=settings_used(conditions, cfg))
    for row in report["conditions"]:
        print(f"{row['condition']}: {row['passes']}/{row['n']} = {row['pass_rate']:.3f} "
              f"[{row['ci95']['low']:.3f}, {row['ci95']['high']:.3f}] errored {row['errored_after_retry']}", flush=True)
    print(f"total run time {report['total_run_time_s']:.1f} s over {report['segments']} segment(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
