#!/usr/bin/env bash
# Generate the committed scenario sets inside the image, stamped with the clean commit:
#   scenarios/fixed10/       from config/generator_smoke.yaml (prefix fixed10), the Smoke_Suite
#   scenarios/experiment30/  from config/generator.yaml       (prefix exp30), the experiment's base set
# Usage: bash scripts/generate_sets.sh [--out-root <dir>]   (default: scenarios; the M1 gate uses runs/)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
root="scenarios"
if [ "${1:-}" = "--out-root" ]; then root="$2"; fi
commit="${ATH_COMMIT:-$(bash scripts/require_clean.sh)}"
for spec in "config/generator_smoke.yaml fixed10 fixed10" "config/generator.yaml experiment30 exp30"; do
  read -r config dir prefix <<< "$spec"
  cmd=(python -m harness.generator.cli generate --config "$config" --out "$root/$dir" --prefix "$prefix")
  rm -rf "${root:?}/$dir"
  ATH_COMMIT="$commit" ATH_COMMAND="${cmd[*]}" bash scripts/in_image.sh "${cmd[@]}"
done
