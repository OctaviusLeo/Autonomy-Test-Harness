#!/usr/bin/env bash
# Copy a suite's reports and the bags of its failed runs into a directory Jenkins can publish and archive.
# Usage: bash scripts/ci_collect.sh <suite output dir> <destination dir>
set -euo pipefail
src="$1"; dest="$2"
mkdir -p "$dest"
for f in junit.xml summary.md suite.json; do
  if [ -f "$src/$f" ]; then cp "$src/$f" "$dest/"; else echo "ci_collect: $src/$f is missing" >&2; fi
done
# suite.json lists failed, errored, and timed-out runs under "failures", each with its scenario_id.
if [ -f "$src/suite.json" ]; then
  for id in $(grep -o '"scenario_id": "[^"]*"' "$src/suite.json" | sed 's/.*: "\(.*\)"/\1/' | sort -u); do
    if [ -d "$src/bags/$id" ]; then mkdir -p "$dest/bags"; cp -r "$src/bags/$id" "$dest/bags/"; fi
  done
fi
echo "ci_collect: $(ls "$dest" | tr '\n' ' ')"
