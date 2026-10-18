#!/usr/bin/env bash
# Keep one detached job (scripts/bg.sh) going, and say where it stands. Run it again to poll: it never starts a
# second copy of a running job.
#   - never started: start it (STARTED)
#   - LOST (gone without an exit file), crashed (exit 124, or 128 and above), or stalled (its log and --progress
#     paths unchanged for --stall seconds while it is not waiting for the simulation lock): stop what is left of
#     it, keep its log as <name>.log.<k>, and start it again (RESTARTED <k>), at most --max-restarts times; then
#     record it in docs/BLOCKERS.md (ATH_BLOCKERS_FILE overrides) and give up (GAVE UP)
#   - finished: DONE <exit status>; a clean failure is a real result and is never restarted
# Only for jobs that are safe to start again: the experiment resumes, and suites, gates, and scripts/robust.sh
# steps start over. The job runs with ATH_WATCHDOG_TAG=bg-<name>, so its containers are stopped with it.
# Usage: bash scripts/bg_ensure.sh <name> [--stall S] [--max-restarts N] [--progress PATH]... [--task <id>]
#          -- <command> [args...]
# Exit status: 0 DONE 0; 75 running (also just started or restarted); the job's exit status for a real failure;
# 1 GAVE UP.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

name="${1:?usage: bg_ensure.sh <name> [options] -- <command> [args...]}"; shift
stall=1800; max_restarts=2; task=""; progress=()
while [ $# -gt 0 ]; do
  case "$1" in
    --stall) stall="$2"; shift 2 ;;
    --max-restarts) max_restarts="$2"; shift 2 ;;
    --progress) progress+=("$2"); shift 2 ;;
    --task) task="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "bg_ensure: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ $# -gt 0 ] || { echo "bg_ensure: no command after --" >&2; exit 2; }
d=runs/logs
log="$d/$name.log"; count_file="$d/$name.restarts"
blockers="${ATH_BLOCKERS_FILE:-docs/BLOCKERS.md}"
mkdir -p "$d"

newest() {  # newest modification time under the log and the --progress paths
  local p t newest=0
  for p in "$log" "${progress[@]}"; do
    [ -e "$p" ] || continue
    t="$(find "$p" -printf '%T@\n' 2>/dev/null | sort -n | tail -1)"; t="${t%.*}"
    [ -n "$t" ] && [ "$t" -gt "$newest" ] && newest="$t"
  done
  echo "$newest"
}

waiting_for_lock() {
  local waits acquires
  waits="$(grep -c 'waiting for .*sim.lock' "$log" 2>/dev/null)"
  acquires="$(grep -c 'acquired .*sim.lock' "$log" 2>/dev/null)"
  [ "${waits:-0}" -gt "${acquires:-0}" ]
}

group_alive() {  # true while process group $1 has a member that is not a zombie
  ps -eo pgid=,stat= 2>/dev/null | awk -v g="$1" '$1 == g && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}

stop_job() {  # SIGTERM the job's process group (bg.sh starts it with setsid), SIGKILL after 45 s, stop its containers
  local pid ids
  pid="$(cat "$d/$name.pid" 2>/dev/null)"
  if [ -n "$pid" ]; then
    kill -TERM -- "-$pid" 2>/dev/null
    for _ in $(seq 45); do group_alive "$pid" || break; sleep 1; done
    kill -KILL -- "-$pid" 2>/dev/null
  fi
  ids="$(docker ps -q --filter "label=ath.watchdog=bg-$name" 2>/dev/null)"
  [ -n "$ids" ] && docker stop -t 10 $ids > /dev/null 2>&1
  return 0
}

start_job() {
  bash scripts/bg.sh "$name" env "ATH_WATCHDOG_TAG=bg-$name" "$@" > /dev/null
}

restart() {  # $1 = why
  local k
  k="$(cat "$count_file" 2>/dev/null || echo 0)"
  if [ "$k" -ge "$max_restarts" ]; then
    {
      [ -s "$blockers" ] || printf '# Blockers\n\n'
      printf '## %s: %s (%s)\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${task:-$name}" "$1"
      printf -- '- Task: %s\n- Command: `%s`\n- Log: `%s` (earlier logs `%s.<k>`)\n' "${task:-$name}" "${cmd[*]}" "$log" "$log"
      printf -- '- Suspected cause: %s after %s restarts; last log lines:\n\n```\n' "$1" "$k"
      tail -n 15 "$log" 2>/dev/null
      printf '```\n\n'
    } >> "$blockers"
    echo "GAVE UP ($1 after $k restarts; recorded in $blockers)"
    return 1
  fi
  stop_job
  k=$(( k + 1 ))
  echo "$k" > "$count_file"
  [ -f "$log" ] && mv "$log" "$log.$k"
  start_job "${cmd[@]}"
  echo "RESTARTED $k ($1)"
  return 75
}

cmd=("$@")
if [ ! -f "$d/$name.pid" ] && [ ! -f "$d/$name.exit" ]; then
  rm -f "$count_file"
  start_job "${cmd[@]}"
  echo "STARTED"
  exit 75
fi

state="$(bash scripts/bg_status.sh "$name" 0 | head -1)"
rc=0
case "$state" in
  "DONE 0") echo "DONE 0" ;;
  DONE*)
    code="${state#DONE }"
    if [ "$code" -eq 124 ] || [ "$code" -ge 128 ]; then
      restart "crashed (exit $code)"; rc=$?
    else
      echo "DONE $code"; rc="$code"
    fi
    ;;
  LOST) restart "lost (gone without an exit status)"; rc=$? ;;
  RUNNING)
    age=$(( $(date +%s) - $(newest) ))
    if ! waiting_for_lock && [ "$age" -ge "$stall" ]; then
      restart "stalled (no progress for ${age} s)"; rc=$?
    else
      echo "RUNNING (last progress ${age} s ago$(waiting_for_lock && echo ', waiting for the simulation lock'))"
      rc=75
    fi
    ;;
  *) echo "bg_ensure: unexpected state '$state'" >&2; rc=1 ;;
esac
tail -n 5 "$log" 2>/dev/null
exit "$rc"
