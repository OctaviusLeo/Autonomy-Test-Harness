#!/usr/bin/env bash
# Wait until the autonomy-test-harness job has a finished build of <commit>, then print its number and result.
# Uses the anonymous read-only API at http://127.0.0.1:8090.
# Usage: bash scripts/jenkins_wait_build.sh <40-character commit> [max seconds, default 21600]
set -euo pipefail
commit="$1"; max="${2:-21600}"
job="http://127.0.0.1:8090/job/autonomy-test-harness"
end=$(( $(date +%s) + max ))
while [ "$(date +%s)" -lt "$end" ]; do
  builds="$(curl -sf "$job/api/json?tree=builds%5Bnumber%5D" || true)"
  for n in $(printf '%s' "$builds" | grep -o '"number":[0-9]*' | cut -d: -f2); do
    info="$(curl -sf "$job/$n/api/json?tree=building,result,actions%5BlastBuiltRevision%5BSHA1%5D%5D" || true)"
    case "$info" in
      *"\"SHA1\":\"$commit\""*)
        if printf '%s' "$info" | grep -q '"building":false'; then
          result="$(printf '%s' "$info" | grep -o '"result":"[A-Z_]*"' | cut -d'"' -f4)"
          echo "build $n of $commit: $result"
          exit 0
        fi
        ;;
    esac
  done
  sleep 20
done
echo "jenkins_wait_build: no finished build of $commit within $max s" >&2
exit 1
