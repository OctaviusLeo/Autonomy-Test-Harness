#!/usr/bin/env bash
# Wait until the autonomy-test-harness job has a finished build of <commit>, then print its number and result.
# Uses the anonymous read-only API at http://127.0.0.1:8091, with a 30 s limit on every request, and prints a
# heartbeat every 5 minutes. ATH_JENKINS_RESULT_FILE, when set, also receives the result (SUCCESS, FAILURE, ...).
# Usage: bash scripts/jenkins_wait_build.sh <40-character commit> [max seconds, default 21600]
# Exit status: 0 a build of <commit> finished (whatever its result), 2 no build of <commit> appeared within the
# limit (or the controller did not answer), 3 a build of <commit> was still running at the limit (stuck).
set -euo pipefail
commit="$1"; max="${2:-21600}"
job="http://127.0.0.1:8091/job/autonomy-test-harness"
start="$(date +%s)"; end=$(( start + max )); last_beat="$start"; running=""
while [ "$(date +%s)" -lt "$end" ]; do
  builds="$(curl -sf --max-time 30 "$job/api/json?tree=builds%5Bnumber%5D" || true)"
  for n in $(printf '%s' "$builds" | grep -o '"number":[0-9]*' | cut -d: -f2); do
    info="$(curl -sf --max-time 30 "$job/$n/api/json?tree=building,result,actions%5BlastBuiltRevision%5BSHA1%5D%5D" || true)"
    case "$info" in
      *"\"SHA1\":\"$commit\""*)
        if printf '%s' "$info" | grep -q '"building":false'; then
          result="$(printf '%s' "$info" | grep -o '"result":"[A-Z_]*"' | cut -d'"' -f4)"
          echo "build $n of $commit: $result"
          if [ -n "${ATH_JENKINS_RESULT_FILE:-}" ]; then echo "$result" > "$ATH_JENKINS_RESULT_FILE"; fi
          exit 0
        fi
        running="$n"
        ;;
    esac
  done
  now="$(date +%s)"
  if [ $(( now - last_beat )) -ge 300 ]; then
    echo "jenkins_wait_build: waiting for $commit, $(( now - start )) s${running:+, build $running running}"
    last_beat="$now"
  fi
  sleep 20
done
if [ -n "$running" ]; then
  echo "jenkins_wait_build: build $running of $commit still running after $max s" >&2
  exit 3
fi
echo "jenkins_wait_build: no build of $commit within $max s" >&2
exit 2
