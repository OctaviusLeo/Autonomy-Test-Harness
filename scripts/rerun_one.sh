#!/usr/bin/env bash
# Re-run one committed Scenario alone from its seed, in an ath-sim container under the simulation lock.
# It regenerates the Scenario, checks it equals the committed file with that seed, applies --condition
# (an experiment condition from config/experiment.yaml) if given, and runs it with the suite runner.
# Usage: bash scripts/rerun_one.sh --config <generator yaml> --seed <scenario seed> [--condition <name>]
#                                  [--image <tag>] [--out <dir>]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/rerun_one.sh "$@"; fi

command="bash scripts/rerun_one.sh $*"
config=""; seed=""; condition="none"; image=""; out=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="$2"; shift 2 ;;
    --seed) seed="$2"; shift 2 ;;
    --condition) condition="$2"; shift 2 ;;
    --image) image="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    *) echo "rerun_one: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$config" ] && [ -n "$seed" ] || { echo "usage: bash scripts/rerun_one.sh --config <yaml> --seed <seed> [--condition <name>]" >&2; exit 2; }

commit="${ATH_COMMIT:-$(bash scripts/require_clean.sh)}"
image="${image:-ath-sim:$commit}"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "rerun_one: image $image not found; build it with bash scripts/build_image.sh --tag $image" >&2
  exit 1
fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
out="${out:-$shared/runs/rerun-$seed-$condition-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$out"

set +e
docker run --rm --name "ath-rerun-$$" --shm-size=1g \
  -e ATH_COMMIT="$commit" -e ATH_COMMAND="$command" -e ATH_HOST_RESULTS="$out" \
  -v "$out:/results" "$image" \
  python -m harness.runner.rerun --config "$config" --seed "$seed" --condition "$condition" --out /results
rc=$?
set -e
docker run --rm --name "ath-chown-$$" -v "$out:/results" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /results
echo "rerun_one: exit $rc; output $out"
exit "$rc"
