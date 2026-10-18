"""Run a set of Scenarios, each in its own child process with a hard wall-clock limit (Requirements 5.3, 5.7).

For each Scenario (in file order) the suite starts ``python -m harness.runner.run_scenario`` in a new process
group and waits at most ``startup_timeout_s + 3 x time_limit_s + 60`` wall-clock seconds. A child still
running then is stopped (SIGINT, SIGKILL after 10 s) and its run is marked ``timed_out`` with a failing
Verdict (reason ``"timeout"``, detail "hard wall-clock limit"). A child that exits without writing its
RunRecord is ``errored`` at step ``harness``. After every Scenario the suite kills and records any leftover
process, waits until none remain, and removes Fast DDS shared-memory files before starting the next one
(Requirement 5.2). It writes a stamped ``suite.json`` and the reports (``junit.xml``, ``summary.md``).

Stalls and crashes (design.md, "Stall and crash handling"): a child whose run directory and bag stop changing
for ``stall_timeout_s`` is stopped early as ``timed_out`` (detail "stalled: ..."). A run without a real result
(``errored``, or ``timed_out`` by the hard limit or a stall) is run once more with the other render method
(EGL or Xvfb); the first attempt's record stays in ``runs/<id>/attempt_1/`` and its bag is renamed
``bags/<id>.attempt1``. A run that failed its Verdict is a result about Nav2 and is never re-run.

Usage (inside the image):
  python -m harness.runner.suite --name smoke --scenarios /opt/ath/scenarios/fixed10 --out /results [--repeat 3]
         [--render-mode egl|xvfb] [--no-retry]
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
RETRY_INDEX_OFFSET = 500  # a retried run uses run index + 500 (its own Gazebo partition)


def write_reports(records: list[dict], out_dir: Path, name: str, seed: int = 0) -> None:
    """``junit.xml`` and ``summary.md`` in ``out_dir`` (bag links use ATH_BAG_LINK_BASE when Jenkins sets it)."""
    from harness.reporting.junit import write_junit
    from harness.reporting.summary import write_summary

    write_junit(records, Path(out_dir) / "junit.xml", name)
    write_summary(records, Path(out_dir) / "summary.md", f"Summary: {name}", repro.make_stamp(seed=seed).to_dict(),
                  bag_link_base=os.environ.get("ATH_BAG_LINK_BASE"), run_root=os.environ.get("ATH_HOST_RESULTS"))


def newest_mtime(paths: Sequence[Path]) -> float:
    """The newest modification time of anything under ``paths`` (0 when none exists)."""
    newest = 0.0
    for top in paths:
        if not Path(top).exists():
            continue
        newest = max(newest, Path(top).stat().st_mtime)
        for root, dirs, files in os.walk(top):
            for name in (*dirs, *files):
                try:
                    newest = max(newest, os.stat(os.path.join(root, name)).st_mtime)
                except OSError:
                    pass
    return newest


@dataclasses.dataclass
class SuiteDeps:
    api: ProcessApi = dataclasses.field(default_factory=ProcessApi)
    python: str = sys.executable
    clean_shm: Callable[[], int] = processes.clean_shm
    write_reports: Callable[[list[dict], Path, str], None] | None = write_reports
    newest_mtime: Callable[[Sequence[Path]], float] = newest_mtime


def scenario_files(paths: Sequence[str | Path]) -> list[Path]:
    """Scenario YAML files from files and directories, in a stable order (directories sorted by name)."""
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.glob("*.yaml")) if p.is_dir() else [p])
    return files


def run_dir(out_dir: Path, scenario_id: str) -> Path:
    return Path(out_dir) / "runs" / scenario_id


def wait_with_limit(api: ProcessApi, proc: subprocess.Popen, limit_s: float, stall_s: float | None = None,
                    progress: Callable[[], float] | None = None) -> str:
    """Wait for ``proc``: "exited", "timeout" after ``limit_s`` wall-clock seconds, or "stalled" when
    ``progress()`` (a newest-modification-time signature) has not changed for ``stall_s`` seconds."""
    start = api.monotonic()
    deadline = start + limit_s
    last_signature, last_change = None, start
    while proc.poll() is None:
        now = api.monotonic()
        if now >= deadline:
            return "timeout"
        if stall_s is not None and progress is not None:
            signature = progress()
            if signature != last_signature:
                last_signature, last_change = signature, now
            elif now - last_change >= stall_s:
                return "stalled"
        api.sleep(1.0)
    return "exited"


def other_render_mode(mode: str) -> str:
    return "xvfb" if mode == "egl" else "egl"


def move_aside(path: Path, label: str) -> Path | None:
    """Rename ``path`` (a bag or record from an earlier attempt) so a new attempt can use the name.

    ``ros2 bag record -o`` refuses an existing directory, so a retry or a resumed run needs the name free.
    """
    path = Path(path)
    if not path.exists():
        return None
    k = 1
    while (target := path.with_name(f"{path.name}.{label}{k}")).exists():
        k += 1
    path.rename(target)
    return target


def synthetic_record(scenario, out_dir: Path, condition: str, run_index: int, status: str, step: str | None,
                     effect: str, wall_time_s: float, leftovers: list[str], stamp: repro.Stamp,
                     detail: str = HARD_LIMIT_DETAIL) -> dict[str, Any]:
    verdict = None
    if status == "timed_out":
        verdict = {"passed": False, "reason": "timeout", "detail": detail, "time_to_goal_s": None,
                   "min_clearance_m": None}
    return {
        "scenario_id": scenario.scenario_id, "seed": scenario.seed, "fault_condition": condition,
        "run_index": run_index, "bag_path": host_path(bag_dir(out_dir, scenario.scenario_id)), "status": status,
        "failing_step": step, "effect": effect, "nav2_result": "UNKNOWN", "wall_time_s": round(wall_time_s, 1),
        "leftover_processes": leftovers, "verdict": verdict, "stamp": stamp.to_dict(),
    }


def run_attempt(path: Path, cfg: RunConfig, out_dir: Path, run_index: int, condition: str, deps: SuiteDeps,
                run_config_path: Path, extra_args: Sequence[str] = (), render_mode: str = "egl") -> dict[str, Any]:
    """One child process for one Scenario: its RunRecord, or a synthetic one if it hung, stalled, or crashed."""
    scenario = load_scenario(path)
    rdir = run_dir(out_dir, scenario.scenario_id)
    rdir.mkdir(parents=True, exist_ok=True)
    record_path = rdir / "run_record.json"
    record_path.unlink(missing_ok=True)
    move_aside(bag_dir(out_dir, scenario.scenario_id), "interrupted")  # a partial bag from a run that was stopped
    cmd = [deps.python, "-m", "harness.runner.run_scenario", "--scenario", str(path), "--out", str(out_dir),
           "--run-index", str(run_index), "--condition", condition, "--run-config", str(run_config_path),
           "--render-mode", render_mode, *extra_args]
    started = deps.api.monotonic()
    proc = processes.start_group(deps.api, cmd, rdir / "child.log")
    watched = (rdir, bag_dir(out_dir, scenario.scenario_id))
    ended = wait_with_limit(deps.api, proc, cfg.hard_limit_s(scenario.time_limit_s), cfg.stall_timeout_s,
                            lambda: deps.newest_mtime(watched))
    if ended != "exited":
        processes.stop_group(deps.api, proc)
    leftovers = [p.cmdline for p in processes.kill_leftovers(deps.api)]
    deps.clean_shm()
    stamp = repro.make_stamp(seed=scenario.seed)
    elapsed = deps.api.monotonic() - started
    if ended == "timeout":
        record = synthetic_record(scenario, out_dir, condition, run_index, "timed_out", None,
                                  f"killed after {cfg.hard_limit_s(scenario.time_limit_s):.0f} s", elapsed, leftovers,
                                  stamp)
    elif ended == "stalled":
        detail = f"stalled: no change in the run's logs or bag for {cfg.stall_timeout_s:.0f} s"
        record = synthetic_record(scenario, out_dir, condition, run_index, "timed_out", None,
                                  f"stopped after {elapsed:.0f} s ({detail})", elapsed, leftovers, stamp, detail)
    elif record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["leftover_processes"] = [*record.get("leftover_processes", []), *leftovers]
    else:
        record = synthetic_record(scenario, out_dir, condition, run_index, "errored", "harness",
                                  f"run_scenario exited {proc.returncode} without a RunRecord", elapsed, leftovers,
                                  stamp)
    record["render_mode"] = render_mode
    repro.write_text_atomic(record_path, json.dumps(record, indent=2) + "\n")
    return record


def needs_retry(record: dict[str, Any]) -> bool:
    """Only runs without a real result are retried: errored (no Verdict) or stopped by the hard limit or a stall.
    A run that failed its Verdict is a result about Nav2 and is never re-run to get a pass."""
    return record["status"] in ("errored", "timed_out")


def run_one(path: Path, cfg: RunConfig, out_dir: Path, run_index: int, condition: str, deps: SuiteDeps,
            run_config_path: Path, extra_args: Sequence[str] = (), retry: bool = True,
            render_mode: str = "egl") -> dict[str, Any]:
    """Run one Scenario; if it errored, hung, or stalled, keep that attempt and run it once more with the other
    render method (EGL or Xvfb), recording both attempts."""
    record = run_attempt(path, cfg, out_dir, run_index, condition, deps, run_config_path, extra_args, render_mode)
    record["attempt"] = 1
    if not (retry and needs_retry(record)):
        return record
    rdir = run_dir(out_dir, record["scenario_id"])
    first = dict(record)
    moved = move_aside(bag_dir(out_dir, record["scenario_id"]), "attempt")
    if moved is not None:
        first["bag_path"] = host_path(moved)
    (rdir / "attempt_1").mkdir(parents=True, exist_ok=True)
    repro.write_text_atomic(rdir / "attempt_1" / "run_record.json", json.dumps(first, indent=2) + "\n")
    record = run_attempt(path, cfg, out_dir, run_index + RETRY_INDEX_OFFSET, condition, deps, run_config_path,
                         extra_args, other_render_mode(render_mode))
    record["attempt"] = 2
    record["first_attempt"] = {k: first.get(k) for k in ("status", "failing_step", "effect", "render_mode",
                                                         "wall_time_s")}
    repro.write_text_atomic(rdir / "run_record.json", json.dumps(record, indent=2) + "\n")
    return record


def run_suite(paths: Sequence[Path], cfg: RunConfig, out_dir: Path, condition: str = "none", first_index: int = 0,
              deps: SuiteDeps | None = None, run_config_path: Path = REPO / "config" / "run.yaml",
              extra_args: Sequence[str] = (), retry: bool = True, render_mode: str = "egl") -> list[dict[str, Any]]:
    """Run every Scenario file in ``paths`` and return their RunRecords."""
    deps = deps or SuiteDeps()
    return [run_one(p, cfg, out_dir, first_index + k, condition, deps, run_config_path, extra_args, retry, render_mode)
            for k, p in enumerate(paths)]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [r.get("verdict") or {} for r in records]
    return {
        "runs": len(records),
        "passed": sum(1 for v in verdicts if v.get("passed")),
        "failed": sum(1 for r, v in zip(records, verdicts) if r["status"] != "errored" and not v.get("passed")),
        "errored": sum(1 for r in records if r["status"] == "errored"),
        "timed_out": sum(1 for r in records if r["status"] == "timed_out"),
        "retried": [{"scenario_id": r["scenario_id"], **r["first_attempt"]} for r in records if r.get("first_attempt")],
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
    parser.add_argument("--fail-on", choices=("nothing", "errors", "failures"), default="nothing",
                        help="exit 1 if any run errored or hit the hard limit (errors), or also failed its Verdict")
    parser.add_argument("--render-mode", choices=("egl", "xvfb"), default=os.environ.get("ATH_RENDER_MODE", "egl"),
                        help="the first render method of every run (the retry uses the other one)")
    parser.add_argument("--no-retry", action="store_true", help="do not re-run errored, hung, or stalled runs")
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
        records = run_suite(paths, cfg, out, args.condition, k * len(paths), deps, args.run_config, extra_args,
                            not args.no_retry, args.render_mode)
        write_suite(args.name, out, [(out, r) for r in records], time.monotonic() - repeat_started,
                    repro.make_stamp(seed=0), deps, {"repeat": k + 1, "condition": args.condition, "scenario_ids": selection})
        entries.extend((out, r) for r in records)
    if args.repeat > 1:
        write_suite(args.name, args.out, entries, time.monotonic() - started, repro.make_stamp(seed=0),
                    dataclasses.replace(deps, write_reports=None),
                    {"repeats": args.repeat, "condition": args.condition, "scenario_ids": selection})
    s = summarize([r for _, r in entries])
    print(f"suite {args.name}: {s['runs']} runs, {s['passed']} passed, {s['failed']} failed, "
          f"{s['errored']} errored, {s['timed_out']} timed out, {len(s['retried'])} retried", flush=True)
    return exit_status(s, args.fail_on)


def exit_status(summary: dict[str, Any], fail_on: str) -> int:
    """1 when the summary breaks the ``fail_on`` rule (errors: errored or timed out; failures: also failed)."""
    errors = summary["errored"] + summary["timed_out"]
    if fail_on == "errors" and errors:
        return 1
    if fail_on == "failures" and (errors or summary["failed"]):
        return 1
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
