#!/usr/bin/env bash
# M0 gate: unit tests, the M0 baseline result, environment and design records, regeneration of the
# world, map, and Nav2 parameter file, and the ignore files. Exit status decides the gate.
# Usage: bash scripts/verify_m0.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
bash scripts/in_image.sh python scripts/verify_gate.py m0
echo "verify_m0: PASS"
