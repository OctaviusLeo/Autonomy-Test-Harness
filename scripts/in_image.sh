#!/usr/bin/env bash
# Run one short, light command in the ath-sim image with the working tree mounted at /opt/ath,
# as the calling user (so every file it writes is the caller's). Long or CPU-heavy jobs use
# test_unit.sh, run_suite.sh, or run_experiment.sh instead, which hold the simulation lock.
# Usage: bash scripts/in_image.sh [--image <tag>] <command> [args...]
#   e.g. bash scripts/in_image.sh python scripts/build_world.py
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
image="${ATH_IMAGE:-ath-sim:dev}"
if [ "${1:-}" = "--image" ]; then image="$2"; shift 2; fi
envs=(-e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
[ -n "${ATH_COMMIT:-}" ] && envs+=(-e "ATH_COMMIT=$ATH_COMMIT")
[ -n "${ATH_COMMAND:-}" ] && envs+=(-e "ATH_COMMAND=$ATH_COMMAND")
exec docker run --rm --name "ath-cmd-$$" --shm-size=1g -u "$(id -u):$(id -g)" "${envs[@]}" \
  -v "$PWD:/opt/ath" -w /opt/ath "$image" "$@"
