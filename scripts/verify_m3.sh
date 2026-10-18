#!/usr/bin/env bash
# M3 gate: unit tests; results/m3_fault_check.json shows all six Fault types confined to their windows,
# each with a Verdict and a stamp; design.md records the odometry-drift decision and the schema rejects
# odom_drift; config/experiment.yaml holds the seven conditions inside the schema's bounds.
# Usage: bash scripts/verify_m3.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
bash scripts/in_image.sh python scripts/verify_gate.py m3
echo "verify_m3: PASS"
