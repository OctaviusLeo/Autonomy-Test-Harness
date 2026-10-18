#!/usr/bin/env bash
# Run a long command under a watchdog: a hard limit on active time, stall detection, and retries with the
# next method of a ladder when an attempt crashes, stalls, times out, or leaves incomplete outputs
# (design.md, "Stall and crash handling").
#
# Usage: bash scripts/watchdog.sh --name <job> [--timeout S] [--stall S] [--poll S] [--progress PATH]...
#          [--attempts N] [--complete 'shell check'] [--retry-on-failure] [--task <id>]
#          --method 'shell command' [--method 'next method']...
#
# Outcome of an attempt:
#   PASS        exit 0 and the --complete check passes
#   FAILED      a clean non-zero exit (below 128, not 124) with complete outputs: a real result such as a failing
#               test or a Scenario failing its Verdict. Reported as is and not retried, unless --retry-on-failure
#               (only for idempotent steps such as an image build or waiting for a Jenkins build).
#   INCOMPLETE  the --complete check fails (outputs missing, stale, or unparsable)        -> retry
#   CRASHED     killed by a signal (exit 128 or more)                                     -> retry
#   TIMEOUT     more than --timeout seconds of active time (or exit 124 from `timeout`)   -> retry
#   STALLED     no new output and no change under any --progress path for --stall seconds -> retry
# Time spent waiting for ~/ath-shared/sim.lock (a "waiting for" line from scripts/sim_lock.sh without its
# "acquired" line) is not active time and never counts as a stall: another job, such as a Jenkins build,
# holds the simulator.
#
# Attempt k runs method k (the last method repeats) in its own process group with ATH_WATCHDOG_TAG (the
# repository's docker run commands label their containers with it, so a killed attempt's containers are
# stopped too), ATH_ATTEMPT, and ATH_ATTEMPT_START (epoch seconds) in its environment. Logs go to
# runs/logs/<name>.attempt<k>.log (also streamed to the watchdog's own output), and one JSON line per attempt is appended to runs/logs/<name>.attempts.jsonl.
# When every attempt fails without a real result, an entry is appended to docs/BLOCKERS.md
# (ATH_BLOCKERS_FILE overrides the path) and the exit status is 1.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

name=""; timeout=3600; stall=900; poll=5; attempts=3; complete=""; retry_on_failure=0; task=""
methods=(); progress=()
while [ $# -gt 0 ]; do
  case "$1" in
    --name) name="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    --stall) stall="$2"; shift 2 ;;
    --poll) poll="$2"; shift 2 ;;
    --progress) progress+=("$2"); shift 2 ;;
    --attempts) attempts="$2"; shift 2 ;;
    --complete) complete="$2"; shift 2 ;;
    --retry-on-failure) retry_on_failure=1; shift ;;
    --task) task="$2"; shift 2 ;;
    --method) methods+=("$2"); shift 2 ;;
    *) echo "watchdog: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$name" ] && [ "${#methods[@]}" -gt 0 ] || { echo "usage: watchdog.sh --name <job> --method '<command>' [...]" >&2; exit 2; }

logs="${ATH_WATCHDOG_LOGS:-runs/logs}"
mkdir -p "$logs"
blockers="${ATH_BLOCKERS_FILE:-docs/BLOCKERS.md}"

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\t' '  '; }

newest_progress() {  # newest modification time (epoch seconds) under the --progress paths
  local p newest=0 t
  for p in "${progress[@]}"; do
    [ -e "$p" ] || continue
    t="$(find "$p" -printf '%T@\n' 2>/dev/null | sort -n | tail -1)"
    t="${t%.*}"
    [ -n "$t" ] && [ "$t" -gt "$newest" ] && newest="$t"
  done
  echo "$newest"
}

waiting_for_lock() {  # true while the attempt's last lock message is "waiting for"
  local waits acquires
  waits="$(grep -c 'waiting for .*sim.lock' "$1" 2>/dev/null)"
  acquires="$(grep -c 'acquired .*sim.lock' "$1" 2>/dev/null)"
  [ "${waits:-0}" -gt "${acquires:-0}" ]
}

group_alive() {  # true while process group $1 has a member that is not a zombie (an unreaped attempt is one)
  ps -eo pgid=,stat= 2>/dev/null | awk -v g="$1" '$1 == g && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}

stop_attempt() {  # $1 = process group leader, $2 = tag: SIGTERM the group, SIGKILL after 15 s, stop tagged containers
  local pid="$1" tag="$2" i
  kill -TERM -- "-$pid" 2>/dev/null
  for i in $(seq 15); do group_alive "$pid" || break; sleep 1; done
  kill -KILL -- "-$pid" 2>/dev/null
  stop_containers "$tag"
}

stop_containers() {
  local ids
  ids="$(docker ps -q --filter "label=ath.watchdog=$1" 2>/dev/null)"
  [ -n "$ids" ] && docker stop -t 10 $ids > /dev/null 2>&1
  return 0
}

# The attempt runs in its own process group, so a signal to the watchdog's group (bg_ensure.sh stopping a stalled
# job, Jenkins aborting a build) would not reach it: stop the attempt and its containers before exiting.
pid=""; tag=""; tail_pid=""
on_signal() {
  echo "watchdog[$name]: stopped by a signal; stopping the running attempt" >&2
  [ -n "$pid" ] && stop_attempt "$pid" "$tag"
  [ -n "$tail_pid" ] && kill "$tail_pid" 2>/dev/null
  exit 143
}
trap on_signal TERM INT HUP

record() {  # attempt method start end outcome rc log
  printf '{"name": "%s", "attempt": %s, "method": "%s", "start": %s, "end": %s, "active_s": %s, "outcome": "%s", "exit_code": %s, "log": "%s"}\n' \
    "$(json_escape "$name")" "$1" "$(json_escape "$2")" "$3" "$4" "$active" "$5" "$6" "$(json_escape "$7")" >> "$logs/$name.attempts.jsonl"
}

last_rc=1; last_outcome=""; last_log=""
for k in $(seq "$attempts"); do
  idx=$(( k <= ${#methods[@]} ? k - 1 : ${#methods[@]} - 1 ))
  method="${methods[$idx]}"
  log="$logs/$name.attempt$k.log"
  tag="$name-$$-$k"
  start="$(date +%s)"
  echo "watchdog[$name]: attempt $k of $attempts: $method"
  ATH_WATCHDOG_TAG="$tag" ATH_ATTEMPT="$k" ATH_ATTEMPT_START="$start" \
    setsid bash -c "$method" > "$log" 2>&1 < /dev/null &
  pid=$!
  # Stream the attempt's output here too (a Jenkins console shows it); tail exits once the attempt has.
  tail -n +1 -f --pid="$pid" "$log" 2>/dev/null &
  tail_pid=$!
  active=0; last_change="$start"; last_sig=""; outcome=""; last_beat="$start"
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$poll"
    now="$(date +%s)"
    if waiting_for_lock "$log"; then
      last_change="$now"  # queued behind another job: neither active nor stalled
    else
      active=$(( active + poll ))
    fi
    sig="$(stat -c %s "$log" 2>/dev/null):$(newest_progress)"
    if [ "$sig" != "$last_sig" ]; then last_sig="$sig"; last_change="$now"; fi
    if [ "$active" -ge "$timeout" ]; then outcome=TIMEOUT; break; fi
    if [ $(( now - last_change )) -ge "$stall" ]; then outcome=STALLED; break; fi
    if [ $(( now - last_beat )) -ge 300 ]; then  # heartbeat, so a supervisor sees the watchdog is alive
      echo "watchdog[$name]: attempt $k alive, ${active}s active, last change $(( now - last_change ))s ago"
      last_beat="$now"
    fi
  done
  if [ -n "$outcome" ]; then
    stop_attempt "$pid" "$tag"
    wait "$pid" 2>/dev/null
    rc=124
  else
    wait "$pid"; rc=$?
    stop_containers "$tag"  # an attempt that exited may still have left a labeled container behind
  fi
  wait "$tail_pid" 2>/dev/null
  complete_ok=1
  if [ -n "$complete" ]; then
    ATH_ATTEMPT="$k" ATH_ATTEMPT_START="$start" bash -c "$complete" >> "$log" 2>&1 || complete_ok=0
  fi
  if [ -z "$outcome" ]; then
    if [ "$rc" -eq 124 ]; then outcome=TIMEOUT
    elif [ "$rc" -ge 128 ]; then outcome=CRASHED
    elif [ "$complete_ok" -eq 0 ]; then outcome=INCOMPLETE
    elif [ "$rc" -eq 0 ]; then outcome=PASS
    else outcome=FAILED
    fi
  fi
  record "$k" "$method" "$start" "$(date +%s)" "$outcome" "$rc" "$log"
  echo "watchdog[$name]: attempt $k: $outcome (exit $rc, ${active}s active); log $log"
  last_rc="$rc"; last_outcome="$outcome"; last_log="$log"
  case "$outcome" in
    PASS) exit 0 ;;
    FAILED) [ "$retry_on_failure" -eq 1 ] || exit "$rc" ;;
  esac
done

{
  [ -s "$blockers" ] || printf '# Blockers\n\n'
  printf '## %s: %s (%s)\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${task:-$name}" "$last_outcome"
  printf -- '- Task: %s\n- Command: `%s`\n- Exit code: %s\n- Log: `%s` (attempt history `%s`)\n' \
    "${task:-$name}" "${methods[*]}" "$last_rc" "$last_log" "$logs/$name.attempts.jsonl"
  printf -- '- Suspected cause: every one of %s attempts ended %s; last log lines:\n\n```\n' "$attempts" "$last_outcome"
  tail -n 15 "$last_log" 2>/dev/null
  printf '```\n\n'
} >> "$blockers"
echo "watchdog[$name]: gave up after $attempts attempts ($last_outcome); recorded in $blockers" >&2
exit 1
