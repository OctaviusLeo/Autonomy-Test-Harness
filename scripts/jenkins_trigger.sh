#!/usr/bin/env bash
# Start a build of the autonomy-test-harness job now (it builds the branch's newest commit), as the admin user.
# With --stop-running, first stop every build of the job that is still running (a stuck build holds the job,
# since builds never run concurrently). scripts/robust.sh's jenkins-build step uses this when a pushed commit's
# build never appears or never finishes; a finished build is never re-run.
# Usage: bash scripts/jenkins_trigger.sh [--stop-running]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
job_path="/job/autonomy-test-harness"
job="http://127.0.0.1:8091$job_path"
if [ "${1:-}" = "--stop-running" ]; then
  builds="$(curl -sf --max-time 30 "$job/api/json?tree=builds%5Bnumber%5D" || true)"
  for n in $(printf '%s' "$builds" | grep -o '"number":[0-9]*' | cut -d: -f2); do
    if curl -sf --max-time 30 "$job/$n/api/json?tree=building" | grep -q '"building":true'; then
      echo "jenkins_trigger: stopping running build $n"
      bash scripts/jenkins_admin_post.sh "$job_path/$n/stop"
      for _ in $(seq 60); do
        curl -sf --max-time 30 "$job/$n/api/json?tree=building" | grep -q '"building":false' && break
        sleep 5
      done
    fi
  done
elif [ $# -gt 0 ]; then
  echo "jenkins_trigger: unknown argument $1" >&2
  exit 2
fi
bash scripts/jenkins_admin_post.sh "$job_path/build?delay=0sec"
