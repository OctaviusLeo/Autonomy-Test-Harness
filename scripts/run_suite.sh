#!/usr/bin/env bash
# Run a Scenario suite in one ath-sim container under the simulation lock.
# Usage: bash scripts/run_suite.sh <smoke|full|<scenario dir>> [--image <tag>] [--out <dir>] [--repeat <n>]
#                                  [--condition <name>] [--wiring]
#   smoke  scenarios/fixed10 (the Ids in config/smoke_suite.yaml)
#   full   scenarios/fixed10 and scenarios/experiment30, no Faults (the nightly Full_Suite)
#   <dir>  every *.yaml in a host directory (copied into the output directory for the container)
# Image: ath-sim:<commit>, where the commit is ATH_COMMIT (Jenkins sets it) or the clean HEAD.
# Output: --out, default ~/ath-shared/runs/<suite>-<UTC time>/ (bags, logs, RunRecords, junit.xml, summary.md).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/run_suite.sh "$@"; fi

[ $# -ge 1 ] || { echo "usage: bash scripts/run_suite.sh <smoke|full|<scenario dir>> [options]" >&2; exit 2; }
command="bash scripts/run_suite.sh $*"
suite="$1"; shift
image=""; out=""; repeat=1; condition="none"; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --image) image="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --repeat) repeat="$2"; shift 2 ;;
    --condition) condition="$2"; shift 2 ;;
    --wiring) extra+=(--wiring); shift ;;
    *) echo "run_suite: unknown argument $1" >&2; exit 2 ;;
  esac
done

commit="${ATH_COMMIT:-$(bash scripts/require_clean.sh)}"
image="${image:-ath-sim:$commit}"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "run_suite: image $image not found; build it with bash scripts/build_image.sh --tag $image" >&2
  exit 1
fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
case "$suite" in
  smoke) name=smoke; scenarios=(/opt/ath/scenarios/fixed10); extra+=(--select /opt/ath/config/smoke_suite.yaml) ;;
  full) name=full; scenarios=(/opt/ath/scenarios/fixed10 /opt/ath/scenarios/experiment30) ;;
  *)
    [ -d "$suite" ] || { echo "run_suite: $suite is not smoke, full, or a directory" >&2; exit 2; }
    name="$(basename "$suite")"; scenarios=(/results/scenarios) ;;
esac
out="${out:-$shared/runs/$name-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$out"
if [ "${scenarios[0]}" = "/results/scenarios" ]; then mkdir -p "$out/scenarios"; cp "$suite"/*.yaml "$out/scenarios/"; fi
echo "run_suite: $name with $image -> $out"

set +e
docker run --rm --name "ath-suite-$$" --shm-size=1g \
  -e ATH_COMMIT="$commit" -e ATH_COMMAND="$command" -e ATH_HOST_RESULTS="$out" \
  -v "$out:/results" "$image" \
  python -m harness.runner.suite --name "$name" --scenarios "${scenarios[@]}" --out /results \
    --repeat "$repeat" --condition "$condition" "${extra[@]}"
rc=$?
set -e
docker run --rm --name "ath-chown-$$" -v "$out:/results" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /results
echo "run_suite: exit $rc; output $out"
exit "$rc"
