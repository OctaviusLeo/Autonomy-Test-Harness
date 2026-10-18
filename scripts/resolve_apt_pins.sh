#!/usr/bin/env bash
# Resolve the exact versions the ath-sim image installs.
#  - docker/base-image.txt: ros:jazzy-ros-base-noble pinned by its current digest
#  - docker/uv-image.txt:   ghcr.io/astral-sh/uv:<host uv version> pinned by digest
#  - docker/apt-pins.txt:   one name=version per line, from apt-cache policy inside the pinned base
# and rewrites the two FROM lines in docker/Dockerfile to match.
# Usage: bash scripts/resolve_apt_pins.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

base_tag="ros:jazzy-ros-base-noble"
uv_version="$(uv --version | awk '{print $2}')"
uv_tag="ghcr.io/astral-sh/uv:${uv_version}"
packages=(
  ros-jazzy-navigation2
  ros-jazzy-nav2-bringup
  ros-jazzy-nav2-minimal-tb4-sim
  ros-jazzy-nav2-minimal-tb4-description
  ros-jazzy-nav2-simple-commander
  ros-jazzy-rosbag2-storage-mcap
  git
  procps
  xvfb
  libegl1
  libegl-mesa0
  libgl1-mesa-dri
  mesa-utils
)

digest_of() {
  docker pull -q "$1" > /dev/null
  docker image inspect --format '{{index .RepoDigests 0}}' "$1"
}

base_ref="$(digest_of "$base_tag")"          # e.g. ros@sha256:...
base_pinned="${base_tag}@${base_ref#*@}"
uv_ref="$(digest_of "$uv_tag")"
uv_pinned="${uv_tag}@${uv_ref#*@}"
echo "base: $base_pinned"
echo "uv:   $uv_pinned"

tmp="$(mktemp)"
docker run --rm --name "ath-resolve-pins-$$" "$base_pinned" bash -c '
  set -euo pipefail
  apt-get update -qq > /dev/null
  for p in "$@"; do
    v="$(apt-cache policy "$p" | awk "/Candidate:/{print \$2}")"
    if [ -z "$v" ] || [ "$v" = "(none)" ]; then echo "no candidate for $p" >&2; exit 1; fi
    echo "$p=$v"
  done' _ "${packages[@]}" > "$tmp"

mv "$tmp" docker/apt-pins.txt
echo "$base_pinned" > docker/base-image.txt
echo "$uv_pinned" > docker/uv-image.txt
if [ -f docker/Dockerfile ]; then
  sed -i -E "s#^FROM ros:jazzy-ros-base-noble@sha256:[0-9a-f]+#FROM ${base_pinned}#; s#^FROM ghcr.io/astral-sh/uv:[^ ]+ AS uv#FROM ${uv_pinned} AS uv#" docker/Dockerfile
fi
cat docker/apt-pins.txt
