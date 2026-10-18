#!/usr/bin/env bash
# Refuse a reported run from a dirty tree; print the commit hash it would be stamped with.
# Changes under results/, runs/, docs/, ci/jenkins_run_log/, README.md, and .kiro/ are allowed:
# they are generated outputs, documentation, and Kiro's task files, not harness code.
# Usage: bash scripts/require_clean.sh   (prints the full 40-character HEAD hash on success)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

allowed() {
  case "$1" in
    results/*|runs/*|docs/*|ci/jenkins_run_log/*|README.md|.kiro/*) return 0 ;;
    *) return 1 ;;
  esac
}

dirty=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  path="${line:3}"
  # A rename is "old -> new"; both sides must be allowed.
  if [[ "$path" == *" -> "* ]]; then
    old="${path%% -> *}"; new="${path##* -> }"
    old="${old#\"}"; old="${old%\"}"; new="${new#\"}"; new="${new%\"}"
    allowed "$old" || dirty+=("$old")
    allowed "$new" || dirty+=("$new")
  else
    path="${path#\"}"; path="${path%\"}"
    allowed "$path" || dirty+=("$path")
  fi
done < <(git --no-optional-locks status --porcelain)

if [ "${#dirty[@]}" -gt 0 ]; then
  echo "require_clean: refusing a reported run; commit or revert these paths first:" >&2
  printf '  %s\n' "${dirty[@]}" >&2
  exit 1
fi
git rev-parse HEAD
