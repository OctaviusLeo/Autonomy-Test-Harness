#!/usr/bin/env bash
# Run one long step under scripts/watchdog.sh with a ladder of methods: an attempt that crashes, stalls, runs past
# its time limit, or leaves incomplete outputs is retried with the next method, and a real result (a failing test,
# a Scenario failing its Verdict, a red Jenkins build) is reported as it is (design.md, "Stall and crash handling").
# When every attempt fails without a result, the step is recorded in docs/BLOCKERS.md and the exit status is 1.
#
# Usage: bash scripts/robust.sh <step> [args...]
#   build [--tag <tag>]       build_image.sh; then with --pull; then with --no-cache (also retried after a failure)
#   unit [test_unit.sh args]  test_unit.sh; then with the ROS 2 tests in a second pytest process
#   suite <smoke|full|dir> [run_suite.sh args]
#                             run_suite.sh; then with Xvfb as every run's first render method; then EGL again.
#                             The last attempt's output is always in --out (default as run_suite.sh's); earlier
#                             attempts are kept beside it as <out>.attempt<k>.
#   experiment                run_experiment.sh, which resumes; again; then resumed with Xvfb first
#   m0                        run_m0.sh (it tries EGL, then Xvfb, itself), repeated after a crash or stall
#   render-check              check_headless_render.sh (EGL with no display by design), repeated likewise
#   gate <m0|m1|...|m5>       verify_<m>.sh, repeated likewise
#   jenkins-build <commit>    wait for the commit's build; then (re)start the controller and start a build; then
#                             stop the stuck build and start another. Exit 0 only if the build is SUCCESS.
#                             The first wait lasts ATH_JENKINS_FIRST_WAIT_S seconds (default 3600).
# ATH_ROBUST_TIMEOUT and ATH_ROBUST_STALL override the step's limits (seconds of active time, seconds without
# progress); ATH_ROBUST_DRY_RUN=1 prints the watchdog command instead of running it.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

usage() { sed -n '7,22p' "$0" | sed 's/^# \{0,1\}//' >&2; }
[ $# -ge 1 ] || { usage; exit 2; }
step="$1"; shift
q() { if [ $# -gt 0 ]; then printf '%q ' "$@"; fi; }  # shell-quote words for a --method string
q1() { printf '%q' "$1"; }  # one word, no trailing space
shared="${ATH_SHARED:-$HOME/ath-shared}"
name="$step-$(date -u +%Y%m%dT%H%M%SZ)"
wd=(--name "$name" --task "$step")
fresh() { echo "[ \"\$(stat -c %Y $(q1 "$1") 2>/dev/null || echo 0)\" -ge \"\$ATH_ATTEMPT_START\" ]"; }

case "$step" in
  build)
    tag="ath-sim:dev"; args=("$@")
    while [ $# -gt 0 ]; do case "$1" in --tag) tag="$2"; shift 2 ;; *) shift ;; esac; done
    base="bash scripts/build_image.sh $(q "${args[@]}")"
    wd+=(--timeout 7200 --stall 1800 --retry-on-failure
         --complete "docker run --rm $(q1 "$tag") python -c 'import rclpy, rosbag2_py, harness'"
         --method "$base" --method "ATH_BUILD_PULL=1 $base" --method "ATH_BUILD_NO_CACHE=1 $base")
    ;;
  unit)
    base="bash scripts/test_unit.sh $(q "$@")"
    wd+=(--timeout 3600 --stall 1200 --attempts 3 --complete "$(fresh runs/coverage.json)"
         --method "$base" --method "ATH_TEST_SPLIT=1 $base")
    ;;
  suite)
    [ $# -ge 1 ] || { usage; exit 2; }
    suite="$1"; args=("$@"); out=""
    while [ $# -gt 0 ]; do case "$1" in --out) out="$2"; shift 2 ;; *) shift ;; esac; done
    if [ -z "$out" ]; then
      case "$suite" in smoke|full) label="$suite" ;; *) label="$(basename "$suite")" ;; esac
      out="$shared/runs/$label-$(date -u +%Y%m%dT%H%M%SZ)"
      args+=(--out "$out")
    fi
    # Before attempt k > 1, keep attempt k-1's output as <out>.attempt<k-1>, so --out holds the last attempt.
    keep="if [ \"\$ATH_ATTEMPT\" -gt 1 ] && [ -e $(q1 "$out") ]; then mv $(q1 "$out") $(q1 "$out").attempt\$((ATH_ATTEMPT - 1)); fi; "
    base="bash scripts/run_suite.sh $(q "${args[@]}")"
    limit=10800; [ "$suite" = "full" ] && limit=57600
    wd+=(--timeout "$limit" --stall 1200 --progress "$out"
         --complete "test -s $(q1 "$out")/suite.json && test -s $(q1 "$out")/junit.xml"
         --method "$keep$base" --method "${keep}ATH_RENDER_MODE=xvfb $base" --method "${keep}ATH_RENDER_MODE=egl $base")
    ;;
  experiment)
    commit="$(bash scripts/require_clean.sh 2>/dev/null || true)"
    [ -n "$commit" ] && wd+=(--progress "$shared/runs/experiment-$commit")
    wd+=(--timeout 21600 --stall 1800 --complete "$(fresh results/experiment/experiment.json)"
         --method "bash scripts/run_experiment.sh" --method "bash scripts/run_experiment.sh"
         --method "ATH_RENDER_MODE=xvfb bash scripts/run_experiment.sh")
    ;;
  m0)
    wd+=(--timeout 3600 --stall 900 --attempts 2 --complete "$(fresh results/m0_baseline.json)"
         --method "bash scripts/run_m0.sh")
    ;;
  render-check)
    wd+=(--timeout 2400 --stall 900 --attempts 2 --complete "$(fresh results/headless_render_check.txt)"
         --method "bash scripts/check_headless_render.sh")
    ;;
  gate)
    [ $# -eq 1 ] && [ -f "scripts/verify_$1.sh" ] || { echo "robust: gate needs one of m0..m5" >&2; exit 2; }
    wd=(--name "gate-$1-${name#gate-}" --task "gate $1" --timeout 14400 --stall 3600 --attempts 2
        --method "bash scripts/verify_$1.sh")
    ;;
  jenkins-build)
    [ $# -eq 1 ] && [ "${#1}" -eq 40 ] || { echo "robust: jenkins-build needs a 40-character commit" >&2; exit 2; }
    commit="$1"
    export ATH_JENKINS_RESULT_FILE="${ATH_WATCHDOG_LOGS:-runs/logs}/$name.result"
    rm -f "$ATH_JENKINS_RESULT_FILE"
    wait_cmd="bash scripts/jenkins_wait_build.sh $commit 5400"
    wd+=(--timeout 7200 --stall 900 --retry-on-failure
         --method "bash scripts/jenkins_wait_build.sh $commit ${ATH_JENKINS_FIRST_WAIT_S:-3600}"
         --method "bash scripts/jenkins_up.sh && bash scripts/jenkins_trigger.sh && $wait_cmd"
         --method "bash scripts/jenkins_trigger.sh --stop-running && $wait_cmd")
    ;;
  *) usage; exit 2 ;;
esac

[ -n "${ATH_ROBUST_TIMEOUT:-}" ] && wd+=(--timeout "$ATH_ROBUST_TIMEOUT")
[ -n "${ATH_ROBUST_STALL:-}" ] && wd+=(--stall "$ATH_ROBUST_STALL")
if [ "${ATH_ROBUST_DRY_RUN:-0}" = "1" ]; then
  q bash scripts/watchdog.sh "${wd[@]}"; echo
  exit 0
fi
if [ "$step" != "jenkins-build" ]; then
  exec bash scripts/watchdog.sh "${wd[@]}"
fi
bash scripts/watchdog.sh "${wd[@]}" || exit $?
result="$(cat "$ATH_JENKINS_RESULT_FILE" 2>/dev/null || true)"
echo "robust: Jenkins build of $commit finished ${result:-with no result}"
[ "$result" = "SUCCESS" ]
