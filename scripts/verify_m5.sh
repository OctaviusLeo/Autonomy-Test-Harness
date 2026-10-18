#!/usr/bin/env bash
# Gate A (end to end): unit tests and the traceability check; ci/jenkins_run_log/ shows a green build (build,
# unit-test, and Smoke_Suite stages, Finished: SUCCESS), the red build and its green revert, and both timers;
# results/experiment/experiment.json has seven conditions on the same 30 Scenarios, every run with a Verdict,
# valid Wilson intervals, a total run time, and a stamp; results/summary.md and README.md regenerate identically;
# THIRD_PARTY.md lists every package and image docs/ENVIRONMENT.md names. Exit status decides the gate.
# Usage: bash scripts/verify_m5.sh   (start it with bg.sh while Jenkins may hold the simulation lock)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
bash scripts/in_image.sh python scripts/check_traceability.py
bash scripts/in_image.sh --shared python scripts/verify_gate.py m5
echo "verify_m5: PASS"
