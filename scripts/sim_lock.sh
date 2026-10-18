#!/usr/bin/env bash
# Run one command while holding the project-wide lock ~/ath-shared/sim.lock, so image builds,
# test runs in the image, suites, the experiment, and Jenkins stages never overlap.
# Usage: bash scripts/sim_lock.sh <command> [args...]   (inside a holder, ATH_LOCK_HELD=1 skips the wait)
set -euo pipefail
if [ "${ATH_LOCK_HELD:-0}" = "1" ]; then exec "$@"; fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
mkdir -p "$shared"
exec 9>>"$shared/sim.lock"
echo "waiting for $shared/sim.lock" >&2
flock 9
echo "acquired $shared/sim.lock" >&2
export ATH_LOCK_HELD=1
"$@"
