#!/usr/bin/env bash
# Headless-render check in an ath-sim:<HEAD> container with no display attached (no DISPLAY, no X socket),
# under the simulation lock. Writes results/headless_render_check.txt (command, output, PASS or FAIL).
# Usage: bash scripts/check_headless_render.sh   (commit and build ath-sim:<HEAD> first)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/check_headless_render.sh "$@"; fi

commit="${ATH_COMMIT:-$(bash scripts/require_clean.sh)}"
image="ath-sim:$commit"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "check_headless_render: image $image not found; build it with bash scripts/build_image.sh --tag $image" >&2
  exit 1
fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
out="$shared/runs/render-check-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"
set +e
docker run --rm --name "ath-render-$$" ${ATH_WATCHDOG_TAG:+--label "ath.watchdog=$ATH_WATCHDOG_TAG"} --shm-size=1g \
  -e ATH_COMMIT="$commit" -e ATH_COMMAND="bash scripts/check_headless_render.sh" \
  -v "$out:/results" "$image" python -m harness.render_check --out /results
rc=$?
set -e
docker run --rm --name "ath-chown-$$" -v "$out:/results" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /results
mkdir -p results
cp "$out/headless_render_check.txt" results/headless_render_check.txt
echo "check_headless_render: exit $rc; run directory $out"
exit "$rc"
