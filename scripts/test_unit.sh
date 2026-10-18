#!/usr/bin/env bash
# Run the unit tests (pytest -m "not sim") inside the ath-sim image, with statement coverage over
# harness/ and scripts/, then enforce the coverage rule with scripts/check_coverage.py.
# Usage: bash scripts/test_unit.sh [--image <tag>] [--baked] [--junit <path>]
#   --image  image to run (default ath-sim:dev)
#   --baked  test the code built into the image instead of mounting the working tree
#            (what Jenkins runs, since its workspace is not a host path)
#   --junit  also write a JUnit XML file to <path>
# Writes runs/coverage.json. Holds ~/ath-shared/sim.lock while it runs.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/test_unit.sh "$@"; fi

image="ath-sim:dev"; baked=0; junit=""
while [ $# -gt 0 ]; do
  case "$1" in
    --image) image="$2"; shift 2 ;;
    --baked) baked=1; shift ;;
    --junit) junit="$2"; shift 2 ;;
    *) echo "test_unit: unknown argument $1" >&2; exit 2 ;;
  esac
done

shared="${ATH_SHARED:-$HOME/ath-shared}"
out="$shared/unit/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$out" runs
mount=()
if [ "$baked" = "0" ]; then mount=(-v "$PWD:/opt/ath"); fi

junit_arg=""
if [ -n "$junit" ]; then junit_arg="--junitxml=/out/junit.xml"; fi

set +e
docker run --rm --name "ath-unit-$$" --shm-size=1g \
  "${mount[@]}" -v "$out:/out" -w /opt/ath \
  -e PYTHONDONTWRITEBYTECODE=1 -e COVERAGE_FILE=/tmp/.coverage \
  -e HYPOTHESIS_STORAGE_DIRECTORY=/tmp/hypothesis \
  -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -e ROS_DOMAIN_ID=$(( ($$ % 100) + 101 )) \
  "$image" bash -c '
    pytest -m "not sim" -p no:cacheprovider -q \
      --cov=harness --cov=scripts --cov-report=term --cov-report=json:/out/coverage.json '"$junit_arg"'
    rc=$?
    if [ "$rc" -eq 0 ]; then python scripts/check_coverage.py /out/coverage.json; rc=$?; fi
    exit "$rc"'
rc=$?
set -e

# Containers run as root: hand the output back to the calling user before copying it.
docker run --rm --name "ath-chown-$$" -v "$out:/out" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /out
[ -f "$out/coverage.json" ] && cp "$out/coverage.json" runs/coverage.json
if [ -n "$junit" ] && [ -f "$out/junit.xml" ]; then mkdir -p "$(dirname "$junit")"; cp "$out/junit.xml" "$junit"; fi
rm -rf "$out"
echo "test_unit: exit $rc (image $image, baked=$baked)"
exit "$rc"
