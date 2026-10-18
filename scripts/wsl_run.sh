#!/usr/bin/env bash
# Run one command in WSL from the repository root with the project's environment.
# From PowerShell: wsl -d Ubuntu-24.04 -- bash /mnt/c/dev/Autonomy-Test-Harness/scripts/wsl_run.sh <command> [args...]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
export ATH_SHARED="$HOME/ath-shared"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$ATH_SHARED/runs"
exec "$@"
