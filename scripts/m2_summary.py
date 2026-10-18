"""Summarize the M2 run of the 10 fixed Scenarios x 3 repeats into results/m2_fixed10/ (runs in the image).

Usage: python scripts/m2_summary.py --run /results --out results/m2_fixed10
Copies every repeat's RunRecords and Verdicts and writes a stamped summary.json: per repeat the passes,
failures with reasons, errored and timed-out runs; per Scenario whether the outcome changed between repeats.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from harness import repro


def outcome(record: dict) -> str:
    if record["status"] != "ok":
        return record["status"]
    verdict = record.get("verdict") or {}
    return "pass" if verdict.get("passed") else f"fail:{verdict.get('reason')}"


def summarize(run: Path) -> tuple[dict, list[tuple[Path, dict]]]:
    top = json.loads((run / "suite.json").read_text(encoding="utf-8"))
    entries = []
    for rel in top["records"]:
        path = run / rel
        entries.append((path, json.loads(path.read_text(encoding="utf-8"))))
    repeats: dict[int, list[dict]] = {}
    for path, record in entries:
        k = int(Path(rel_of(run, path)).parts[0].split("_")[1])
        repeats.setdefault(k, []).append(record)
    per_repeat = []
    for k in sorted(repeats):
        records = repeats[k]
        per_repeat.append({
            "repeat": k,
            "runs": len(records),
            "passes": sum(1 for r in records if outcome(r) == "pass"),
            "failures": [{"scenario_id": r["scenario_id"], "reason": (r.get("verdict") or {}).get("reason"),
                          "detail": (r.get("verdict") or {}).get("detail")}
                         for r in records if outcome(r).startswith("fail")],
            "errored": [{"scenario_id": r["scenario_id"], "failing_step": r.get("failing_step"), "effect": r.get("effect")}
                        for r in records if r["status"] == "errored"],
            "timed_out": [r["scenario_id"] for r in records if r["status"] == "timed_out"],
        })
    by_scenario: dict[str, list[str]] = {}
    for k in sorted(repeats):
        for r in repeats[k]:
            by_scenario.setdefault(r["scenario_id"], []).append(outcome(r))
    per_scenario = [{"scenario_id": sid, "outcomes": outs, "changed_between_repeats": len(set(outs)) > 1,
                     "passed_all_repeats": all(o == "pass" for o in outs)}
                    for sid, outs in sorted(by_scenario.items())]
    summary = {"suite": top["suite"], "repeats": len(per_repeat), "scenario_ids": top.get("scenario_ids"),
               "per_repeat": per_repeat, "per_scenario": per_scenario,
               "outcome_changed": [s["scenario_id"] for s in per_scenario if s["changed_between_repeats"]],
               "suite_wall_time_s": top.get("wall_time_s")}
    return summary, entries


def rel_of(run: Path, path: Path) -> str:
    return path.relative_to(run).as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the M2 fixed10 x3 run.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    summary, entries = summarize(args.run)
    if args.out.exists():
        shutil.rmtree(args.out)
    for path, record in entries:
        dest = args.out / Path(rel_of(args.run, path)).parent
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest / "run_record.json")
        if (path.parent / "verdict.json").exists():
            shutil.copy(path.parent / "verdict.json", dest / "verdict.json")
    stamp = repro.Stamp.from_dict(json.loads((args.run / "suite.json").read_text(encoding="utf-8"))["stamp"])
    repro.write_stamped_json(args.out / "summary.json", summary, stamp)
    for r in summary["per_repeat"]:
        print(f"repeat {r['repeat']}: {r['passes']}/{r['runs']} passed, {len(r['failures'])} failed, "
              f"{len(r['errored'])} errored, {len(r['timed_out'])} timed out")
    print(f"outcome changed between repeats: {summary['outcome_changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
