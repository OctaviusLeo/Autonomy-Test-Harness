#!/usr/bin/env bash
# The container half of scripts/test_unit.sh: pytest -m "not sim" with statement coverage over harness/ and
# scripts/, then the coverage rule (scripts/check_coverage.py).
# Usage (inside the ath-sim image, from /opt/ath): bash scripts/unit_in_image.sh <out dir> [--junit]
#   writes <out dir>/coverage.json, and <out dir>/junit.xml with --junit
# ATH_TEST_SPLIT=1 runs the tests that use ROS 2 (marker ros) in a second pytest process that appends to the
# same coverage data (scripts/robust.sh's second method when a unit-test run crashes or stalls).
set -uo pipefail
out="$1"; junit=0
[ "${2:-}" = "--junit" ] && junit=1
common=(-p no:cacheprovider -q --cov=harness --cov=scripts)

junit_arg() { [ "$junit" = "1" ] && echo "--junitxml=$out/$1"; }

if [ "${ATH_TEST_SPLIT:-0}" = "1" ]; then
  echo "unit_in_image: split run (tests without ROS 2, then marker ros)"
  # shellcheck disable=SC2046
  pytest -m "not sim and not ros" "${common[@]}" --cov-report= $(junit_arg junit-1.xml)
  rc=$?
  # shellcheck disable=SC2046
  pytest -m "ros and not sim" "${common[@]}" --cov-append --cov-report=term \
    --cov-report="json:$out/coverage.json" $(junit_arg junit-2.xml)
  rc2=$?
  # Exit status 5 means no test was selected, which is not a failure for one half of a split run.
  [ "$rc" -eq 5 ] && rc=0
  [ "$rc2" -eq 5 ] && rc2=0
  [ "$rc" -eq 0 ] && rc="$rc2"
  if [ "$junit" = "1" ]; then
    python - "$out" <<'EOF'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path(sys.argv[1])
root = ET.Element("testsuites")
for part in ("junit-1.xml", "junit-2.xml"):
    if (out / part).exists():
        tree = ET.parse(out / part).getroot()
        root.extend(tree.findall("testsuite") if tree.tag == "testsuites" else [tree])
ET.ElementTree(root).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
EOF
  fi
else
  # shellcheck disable=SC2046
  pytest -m "not sim" "${common[@]}" --cov-report=term --cov-report="json:$out/coverage.json" $(junit_arg junit.xml)
  rc=$?
fi
if [ "$rc" -eq 0 ]; then
  python scripts/check_coverage.py "$out/coverage.json"
  rc=$?
fi
exit "$rc"
