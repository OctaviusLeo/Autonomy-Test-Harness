"""Run a set of Scenarios, each in its own child process with a hard wall-clock limit (Requirements 5.3, 5.7).

For each Scenario (in file order) the suite starts ``python -m harness.runner.run_scenario`` in a new process
group and waits at most ``startup_timeout_s + 3 x time_limit_s + 60`` wall-clock seconds. A child still
running then is stopped (SIGINT, SIGKILL after 10 s) and its run is marked ``timed_out`` with a failing
Verdict (reason ``"timeout"``, detail "hard wall-clock limit"). A child that exits without writing its
RunRecord is ``errored`` at step ``harness``. After every Scenario the suite kills and records any leftover
process, waits until none remain, and removes Fast DDS shared-memory files before starting the next one
(Requirement 5.2). It writes a stamped ``suite.json`` and the reports (``junit.xml``, ``summary.md``).

Usage (inside the image):
  python -m harness.runner.suite --name smoke --scenarios /opt/ath/scenarios/fixed10 --out /results [--repeat 3]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from harness import repro
from harness.runner import processes
from harness.runner.processes import ProcessApi
from harness.runner.run_config import RunConfig, load_run_config
from harness.runner.run_scenario import bag_dir, host_path
from harness.schema.validate import load_scenario

REPO = Path(__file__).resolve().parents[2]
HARD_LIMIT_DETAIL = "hard wall-clock limit"


def write_reports(records: list[dict], out_dir: Path, name: str, seed: int = 0) -> None:
    """``junit.xml`` and ``summary.md`` in ``out_dir`` (bag links use ATH_BAG_LINK_BASE when Jenkins sets it)."""
    from harness.reporting.junit import write_junit
    from harness.reporting.summary import write_summary

    write_junit(records, Path(out_dir) / "junit.xml", name)
    write_summary(records, Path(out_dir) / "summary.md", f"Summary: {name}", repro.make_stamp(seed=seed).to_dict(),
                  bag_link_base=os.environ.get("ATH_BAG_LINK_BASE"), run_root=os.environ.get("ATH_HOST_RESULTS"))


@dataclasses.dataclass
class SuiteDeps:
    api: ProcessApi = dataclasses.field(default_factory=ProcessApi)
    python: str = sys.executable
    clean_shm: Callable[[], int] = processes.clean_shm
    write_reports: Callable[[list[dict], Path, str], None] | None = write_reports


def scenario_files(paths: Sequence[str | Path]) -> list[Path]:
    """Scenario YAML files from files and directories, in a stable order (directories sorted by name)."""
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.glob("*.yaml")) if p.is_dir() else [p])
    return files


def run_dir(out_dir: Path, scenario_id: str) -> Path:
    return Path(out_dir) / "runs" / scenario_id


def wait_with_limit(api: ProcessApi, proc: subprocess.Popen, limit_s: float) -> bool:
    """True if ``proc`` exited within ``limit_s`` wall-clock seconds."""
    deadline = api.monotonic() + limit_s
    while proc.poll() is None:
        if api.monotonic() >= deadline:
            return False
        api.sleep(1.0)
    return True


def synthetic_record(scenario, out_dir: Path, condition: str, run_index: int, status: str, step: str | None,
                     effect: str, wall_time_s: float, leftovers: list[str], stamp: repro.Stamp) -> dict[str, Any]:
    verdict = None
    if status == "timed_out":
        verdict = {"passed": False, "reason": "timeout", "detail": HARD_LIMIT_DETAIL, "time_to_goal_s": None,
                   "min_clearance_m": None}
    return {
        "scenario_id": scenario.scenario_id, "seed": scenario.seed, "fault_condition": condition,
        "run_index": run_index, "bag_path": host_path(bag_dir(out_dir, scenario.scenario_id)), "status": status,
        "failing_step": step, "effect": effect, "nav2_result": "UNKNOWN", "wall_time_s": round(wall_time_s, 1),
        "leftover_processes": leftovers, "verdict": verdict, "stamp": stamp.to_dict(),
    }


def run_one(path: Path, cfg: RunConfig, out_dir: Path, run_index: int, condition: str, deps: SuiteDeps,
            run_config_path: Path, extra_args: Sequence[str] = ()) -> dict[str, Any]:
    scenario = load_scenario(path)
    rdir = run_dir(out_dir, scenario.scenario_id)
    rdir.mkdir(parents=True, exist_ok=True)
    record_path = rdir / "run_record.json"
    record_path.unlink(missing_ok=True)
    cmd = [deps.python, "-m", "harness.runner.run_scenario", "--scenario", str(path), "--out", str(out_dir),
           "--run-index", str(run_index), "--condition", condition, "--run-config", str(run_config_path), *extra_args]
    started = deps.api.monotonic()
    proc = processes.start_group(deps.api, cmd, rdir / "child.log")
    finished = wait_with_limit(deps.api, proc, cfg.hard_limit_s(scenario.time_limit_s))
    if not finished:
        processes.stop_group(deps.api, proc)
    leftovers = [p.cmdline for p in processes.kill_leftovers(deps.api)]
    deps.clean_shm()
    stamp = repro.make_stamp(seed=scenario.seed)
    if not finished:
        record = synthetic_record(scenario, out_dir, condition, run_index, "timed_out", None,
                                  f"killed after {cfg.hard_limit_s(scenario.time_limit_s):.0f} s",
                                  deps.api.monotonic() - started, leftovers, stamp)
    elif record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["leftover_processes"] = [*record.get("leftover_processes", []), *leftovers]
    else:
        record = synthetic_record(scenario, out_dir, condition, run_index, "errored", "harness",
                                  f"run_scenario exited {proc.returncode} without a RunRecord",
                                  deps.api.monotonic() - started, leftovers, stamp)
    repro.write_text_atomic(record_path, json.dumps(record, indent=2) + "\n")
    return record


def run_suite(paths: Sequence[Path], cfg: RunConfig, out_dir: Path, condition: str = "none", first_index: int = 0,
              deps: SuiteDeps | None = None, run_config_path: Path = REPO / "config" / "run.yaml",
              extra_args: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Run every Scenario file in ``paths`` and return their RunRecords."""
    deps = deps or SuiteDeps()
    return [run_one(p, cfg, out_dir, first_index + k, condition, deps, run_config_path, extra_args)
            for k, p in enumerate(paths)]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [r.get("verdict") or {} for r in records]
    return {
        "runs": len(records),
        "passed": sum(1 for v in verdicts if v.get("passed")),
        "failed": sum(1 for r, v in zip(records, verdicts) if r["status"] != "errored" and not v.get("passed")),
        "errored": sum(1 for r in records if r["status"] == "errored"),
        "timed_out": sum(1 for r in records if r["status"] == "timed_out"),
        "failures": [{"scenario_id": r["scenario_id"], "status": r["status"], "reason": v.get("reason"),
                      "failing_step": r.get("failing_step")}
                     for r, v in zip(records, verdicts) if not v.get("passed")],
    }


def write_suite(name: str, out_dir: Path, entries: list[tuple[Path, dict[str, Any]]], seconds: float,
                stamp: repro.Stamp, deps: SuiteDeps, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write ``out_dir/suite.json`` for ``entries`` = (directory the run wrote into, RunRecord) pairs."""
    out_dir = Path(out_dir)
    records = [r for _, r in entries]
    data = {"suite": name, **(extra or {}), "wall_time_s": round(seconds, 1), **summarize(records),
            "records": [(run_dir(d, r["scenario_id"]) / "run_record.json").relative_to(out_dir).as_posix()
                        for d, r in entries]}
    repro.write_stamped_json(out_dir / "suite.json", data, stamp)
    if deps.write_reports is not None:
        deps.write_reports(records, out_dir, name)
    return data


def main(argv: list[str] | None = None, deps: SuiteDeps | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a set of Scenarios with hard limits.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--scenarios", nargs="+", required=True, help="Scenario files or directories")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--condition", default="none")
    parser.add_argument("--select", type=Path, help="YAML with 'ids': the Scenario ids to keep (or 'all')")
    parser.add_argument("--run-config", type=Path, default=REPO / "config" / "run.yaml")
    parser.add_argument("--wiring", action="store_true")
    args = parser.parse_args(argv)
    deps = deps or SuiteDeps()
    cfg = load_run_config(args.run_config)
    paths = select(scenario_files(args.scenarios), args.select)
    extra_args = ["--wiring"] if args.wiring else []
    started = time.monotonic()
    entries: list[tuple[Path, dict[str, Any]]] = []
    selection = [p.stem for p in paths]
    for k in range(args.repeat):
        out = args.out if args.repeat == 1 else args.out / f"repeat_{k + 1}"
        repeat_started = time.monotonic()
        records = run_suite(paths, cfg, out, args.condition, k * len(paths), deps, args.run_config, extra_args)
        write_suite(args.name, out, [(out, r) for r in records], time.monotonic() - repeat_started,
                    repro.make_stamp(seed=0), deps, {"repeat": k + 1, "condition": args.condition, "scenario_ids": selection})
        entries.extend((out, r) for r in records)
    if args.repeat > 1:
        write_suite(args.name, args.out, entries, time.monotonic() - started, repro.make_stamp(seed=0),
                    dataclasses.replace(deps, write_reports=None),
                    {"repeats": args.repeat, "condition": args.condition, "scenario_ids": selection})
    s = summarize([r for _, r in entries])
    print(f"suite {args.name}: {s['runs']} runs, {s['passed']} passed, {s['failed']} failed, "
          f"{s['errored']} errored, {s['timed_out']} timed out", flush=True)
    return 0


def select(paths: list[Path], selection: Path | None) -> list[Path]:
    """Keep only the Scenario ids listed in ``selection`` (``ids: all`` keeps every file)."""
    if selection is None:
        return paths
    import yaml

    ids = (yaml.safe_load(selection.read_text(encoding="utf-8")) or {}).get("ids", "all")
    if ids == "all":
        return paths
    return [p for p in paths if p.stem in set(ids)]


if __name__ == "__main__":
    raise SystemExit(main())
