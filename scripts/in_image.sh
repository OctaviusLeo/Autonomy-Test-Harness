#!/usr/bin/env bash
# Run one short, light command in the ath-sim image with the working tree mounted at /opt/ath,
# as the calling user (so every file it writes is the caller's). Long or CPU-heavy jobs use
# test_unit.sh, run_suite.sh, or run_experiment.sh instead, which hold the simulation lock.
# Usage: bash scripts/in_image.sh [--image <tag>] [--results <dir>] <command> [args...]
#   --results <dir>  also mount a run's output directory (e.g. under ~/ath-shared/runs/) at /results
#   e.g. bash scripts/in_image.sh python scripts/build_world.py
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
image="${ATH_IMAGE:-ath-sim:dev}"
mounts=(-v "$PWD:/opt/ath")
while [ $# -gt 0 ]; do
  case "$1" in
    --image) image="$2"; shift 2 ;;
    --results) mounts+=(-v "$(readlink -f "$2"):/results"); shift 2 ;;
    *) break ;;
  esac
done
envs=(-e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
[ -n "${ATH_COMMIT:-}" ] && envs+=(-e "ATH_COMMIT=$ATH_COMMIT")
[ -n "${ATH_COMMAND:-}" ] && envs+=(-e "ATH_COMMAND=$ATH_COMMAND")
exec docker run --rm --name "ath-cmd-$$" --shm-size=1g -u "$(id -u):$(id -g)" "${envs[@]}" \
  "${mounts[@]}" -w /opt/ath "$image" "$@"
