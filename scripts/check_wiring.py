"""M2 wiring evidence from one Scenario run made with `run_suite.sh <dir> --wiring` (runs in the image).

Usage: python scripts/check_wiring.py --run /results --out docs/evidence/m2_wiring
Copies the run's subscription evidence and RunRecord into --out and writes a stamped wiring_check.json.
Exits non-zero if a check fails.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from harness import bag_checks, repro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check and save the M2 wiring evidence.")
    parser.add_argument("--run", type=Path, required=True, help="suite output directory (one Scenario)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    run_dir = next((args.run / "runs").iterdir())
    record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    bag = args.run / "bags" / record["scenario_id"]
    subscriptions = json.loads((run_dir / "wiring" / "subscriptions.json").read_text(encoding="utf-8"))
    report = bag_checks.wiring_report(subscriptions, bag_checks.read_scans(bag), bag_checks.ground_truth_count(bag),
                                      record)
    args.out.mkdir(parents=True, exist_ok=True)
    for f in (run_dir / "wiring").iterdir():
        shutil.copy(f, args.out / f.name)
    shutil.copy(run_dir / "run_record.json", args.out / "run_record.json")
    repro.write_stamped_json(args.out / "wiring_check.json", report, repro.Stamp.from_dict(record["stamp"]))
    print(f"check_wiring: ok={report['ok']} checks={report['checks']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
