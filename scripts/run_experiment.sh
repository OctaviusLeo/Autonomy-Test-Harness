#!/usr/bin/env bash
# Run (or resume) the Paired_Experiment in one ath-sim:<HEAD> container under the simulation lock, then copy
# experiment.json, the per-condition JUnit files, and summary.md into results/experiment/ and the summary to
# results/summary.md. Output: ~/ath-shared/runs/experiment-<commit>/ (re-running resumes there).
# Usage: bash scripts/run_experiment.sh   (commit and build ath-sim:<HEAD> first)
# ATH_RENDER_MODE=xvfb makes Xvfb every run's first render method (scripts/robust.sh's last method).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
if [ "${ATH_LOCK_HELD:-0}" != "1" ]; then exec bash scripts/sim_lock.sh bash scripts/run_experiment.sh "$@"; fi

commit="$(bash scripts/require_clean.sh)"
image="ath-sim:$commit"
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "run_experiment: image $image not found; build it with bash scripts/build_image.sh --tag $image" >&2
  exit 1
fi
shared="${ATH_SHARED:-$HOME/ath-shared}"
out="$shared/runs/experiment-$commit"
mkdir -p "$out"
echo "run_experiment: $image -> $out"

set +e
docker run --rm --name "ath-experiment-$$" ${ATH_WATCHDOG_TAG:+--label "ath.watchdog=$ATH_WATCHDOG_TAG"} --shm-size=1g \
  -e ATH_COMMIT="$commit" -e ATH_COMMAND="bash scripts/run_experiment.sh" -e ATH_HOST_RESULTS="$out" \
  ${ATH_RENDER_MODE:+-e "ATH_RENDER_MODE=$ATH_RENDER_MODE"} \
  -v "$out:/results" "$image" python -m harness.experiment.paired --out /results
rc=$?
set -e
docker run --rm --name "ath-chown-$$" -v "$out:/results" --entrypoint chown "$image" -R "$(id -u):$(id -g)" /results
if [ "$rc" -eq 0 ]; then
  rm -rf results/experiment
  mkdir -p results/experiment
  cp "$out/experiment.json" "$out/summary.md" results/experiment/
  cp -r "$out/junit" results/experiment/junit
  cp "$out/summary.md" results/summary.md
fi
echo "run_experiment: exit $rc; output $out"
exit "$rc"
