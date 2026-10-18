#!/usr/bin/env bash
# Run the M0 baseline (scripts/m0_baseline.py) in a container from ath-sim:<HEAD>, under the
# simulation lock, then copy its JSON into results/ and its evidence into docs/evidence/m0/.
# Usage: bash scripts/run_m0.sh   (commit and build ath-sim:<HEAD> with scripts/build_image.sh first)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/run_m0.sh "$@"; fi

commit="$(bash scripts/require_clean.sh)"
image="ath-sim:$commit"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "run_m0: image $image not found; run bash scripts/build_image.sh --tag $image first" >&2
  exit 1
fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
out="$shared/runs/m0-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"
echo "run_m0: image $image, output $out"

set +e
docker run --rm --name "ath-m0-$$" --shm-size=1g \
  -e ATH_COMMIT="$commit" -e ATH_COMMAND="bash scripts/run_m0.sh" \
  -v "$out:/results" "$image" python /opt/ath/scripts/m0_baseline.py --out /results
rc=$?
set -e
docker run --rm --name "ath-chown-$$" -v "$out:/results" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /results

mkdir -p results docs/evidence/m0
cp "$out/m0_baseline.json" results/m0_baseline.json
for f in dpkg_query.txt gz_sim_versions.txt; do cp "$out/$f" "docs/evidence/m0/$f"; done
for mode in egl xvfb; do
  if [ -d "$out/$mode" ]; then
    mkdir -p "docs/evidence/m0/$mode"
    cp "$out/$mode/logs/"*.log "docs/evidence/m0/$mode/" 2>/dev/null || true
    [ -f "$out/$mode/ogre2.log" ] && cp "$out/$mode/ogre2.log" "docs/evidence/m0/$mode/"
  fi
done
echo "run_m0: exit $rc; run directory $out"
exit "$rc"
