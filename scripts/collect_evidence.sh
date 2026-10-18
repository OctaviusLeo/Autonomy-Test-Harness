#!/usr/bin/env bash
# Write the version evidence docs/ENVIRONMENT.md cites: host tools (Docker, uv) and, from inside
# the image, apt and Python package versions and licenses.
# Usage: bash scripts/collect_evidence.sh [--image <tag>]   (default ath-sim:dev)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
image="ath-sim:dev"
if [ "${1:-}" = "--image" ]; then image="$2"; fi
mkdir -p docs/evidence
docker version > docs/evidence/host_docker_version.txt
docker compose version > docs/evidence/host_docker_compose_version.txt
uv --version > docs/evidence/host_uv_version.txt
docker image inspect --format '{{.Id}} {{.Size}} {{index .Config.Labels "ath.commit"}}' "$image" > docs/evidence/image_id.txt
ATH_IMAGE="$image" bash scripts/in_image.sh python scripts/collect_image_evidence.py --out docs/evidence
