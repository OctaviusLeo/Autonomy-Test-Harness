#!/usr/bin/env bash
# M1 gate: unit tests; both committed scenario sets regenerate byte for byte into runs/gate_m1,
# have the right counts, load, carry stamped generation records, and their first Scenario
# regenerates from its stored seed. Exit status decides the gate.
# Usage: bash scripts/verify_m1.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
# The regenerated copies are compared without their stamps, so any well-formed commit hash will do.
ATH_COMMIT=0000000000000000000000000000000000000000 bash scripts/generate_sets.sh --out-root runs/gate_m1
bash scripts/in_image.sh python scripts/verify_gate.py m1
echo "verify_m1: PASS"
