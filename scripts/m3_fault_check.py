"""M3 check: one run per Fault type, each Fault's effect confined to its window (runs in the image).

Usage: python scripts/m3_fault_check.py --run /results --out results/m3_fault_check.json
--run is the output of `bash scripts/run_suite.sh runs/m3_conditions` (six Fault variants of one Scenario).
Writes a stamped JSON with one entry per Fault type (the bag comparison and the run's Verdict); exits
non-zero if a Fault type is missing or not confined to its window.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness import bag_checks, repro
from harness.oracle.bag_reader import read_trace
from harness.schema.scenario import FAULT_TYPES
from harness.schema.validate import load_scenario


def check_run(run: Path, record: dict) -> dict:
    scenario = load_scenario(run / "scenarios" / f"{record['scenario_id']}.yaml")
    fault = scenario.faults[0]
    bag = run / "bags" / record["scenario_id"]
    trace = read_trace(bag)
    entry = {"scenario_id": record["scenario_id"], "seed": record["seed"], "status": record["status"],
             "nav2_result": record.get("nav2_result"), "verdict": record.get("verdict")}
    if trace.dispatch_time is None:
        return {**entry, "fault": fault.type, "confined_to_window": False, "problem": "no dispatch time in the bag"}
    raw, out = bag_checks.read_scans(bag)
    report = bag_checks.fault_report(raw, out, fault.type, (fault.window.start_s, fault.window.end_s),
                                     trace.dispatch_time, fault.params.model_dump())
    return {**entry, **report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check each Fault type's run against its window.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    suite = json.loads((args.run / "suite.json").read_text(encoding="utf-8"))
    entries = []
    for rel in suite["records"]:
        record = json.loads((args.run / rel).read_text(encoding="utf-8"))
        entries.append(check_run(args.run, record))
    by_type = {e["fault"]: e for e in entries}
    missing = [t for t in FAULT_TYPES if t not in by_type]
    result = {"faults": [by_type[t] for t in FAULT_TYPES if t in by_type], "missing_fault_types": missing,
              "all_confined": not missing and all(e["confined_to_window"] for e in entries),
              "checked_with_commit": repro.commit_hash()}
    stamp = repro.Stamp.from_dict(suite["stamp"])
    repro.write_stamped_json(args.out, result, stamp)
    for e in result["faults"]:
        print(f"{e['fault']}: confined={e['confined_to_window']} verdict={(e.get('verdict') or {}).get('passed')}")
    return 0 if result["all_confined"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
