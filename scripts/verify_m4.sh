#!/usr/bin/env bash
# M4 gate: unit tests and the Dockerfile pin check in the image; the headless-render check passed with
# its command recorded; design.md's headless-rendering outcome is filled; results/smoke/junit.xml has one
# passing test case per Smoke_Suite Scenario and results/smoke/summary.md carries a stamp.
# Usage: bash scripts/verify_m4.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
bash scripts/test_unit.sh
bash scripts/in_image.sh python scripts/check_dockerfile_pins.py
bash scripts/in_image.sh python scripts/verify_gate.py m4
echo "verify_m4: PASS"
