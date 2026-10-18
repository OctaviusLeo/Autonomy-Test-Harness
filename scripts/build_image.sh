#!/usr/bin/env bash
# Build the ath-sim image under the simulation lock.
# Usage: bash scripts/build_image.sh [--tag <tag>]
#   default tag ath-sim:dev (the working tree as it is)
#   --tag ath-sim:<40-character commit> builds a reported-run image; it refuses a dirty tree
#   (scripts/require_clean.sh) and a commit that is not HEAD.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

tag="ath-sim:dev"
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) tag="$2"; shift 2 ;;
    *) echo "build_image: unknown argument $1" >&2; exit 2 ;;
  esac
done
case "$tag" in
  ath-sim:*) ;;
  *) echo "build_image: tag must start with ath-sim: (got $tag)" >&2; exit 2 ;;
esac

label_commit="dev"
if [ "$tag" != "ath-sim:dev" ]; then
  head="$(bash scripts/require_clean.sh)"
  want="${tag#ath-sim:}"
  if [ "$want" != "$head" ]; then
    echo "build_image: tag commit $want is not HEAD $head" >&2
    exit 1
  fi
  label_commit="$head"
fi

echo "build_image: building $tag (commit label $label_commit)"
bash scripts/sim_lock.sh docker build \
  -f docker/Dockerfile \
  --label "ath.commit=$label_commit" \
  -t "$tag" .

echo "build_image: built $tag $(docker image inspect --format 'id={{.Id}} size_bytes={{.Size}}' "$tag")"
