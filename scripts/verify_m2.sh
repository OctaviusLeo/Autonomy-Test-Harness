#!/usr/bin/env bash
# M2 gate: unit tests; results/m2_fixed10 holds 30 stamped RunRecords with Verdicts, none errored, timed
# out, or with leftover processes, each with its bag under ~/ath-shared/runs/; the Smoke_Suite passed all
# three repeats; the wiring evidence shows Nav2 reading /scan_ath. Exit status decides the gate.
# Usage: bash scripts/verify_m2.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
bash scripts/in_image.sh --shared python scripts/verify_gate.py m2
echo "verify_m2: PASS"
