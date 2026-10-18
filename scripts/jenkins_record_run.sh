#!/usr/bin/env bash
# Save the CI evidence under ci/jenkins_run_log/ (Requirement 9.5): the green builds' console logs, JSON
# summaries, and test reports (the revert build is the last green build), the red build's console log;
# verification.json (build numbers, commits, results, and the failing tests of the green, red, and revert builds);
# and the job's trigger configuration (config.xml, read as admin).
# Usage: bash scripts/jenkins_record_run.sh <green build> <red build> <revert build>
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
green="$1"; red="$2"; revert="$3"
job="http://127.0.0.1:8091/job/autonomy-test-harness"
out=ci/jenkins_run_log
mkdir -p "$out"

build_field() {  # build_field <build> <jq-less grep pattern> -> first match value
  curl -sf "$job/$1/api/json?tree=result,timestamp,duration,actions%5BlastBuiltRevision%5BSHA1%5D%5D" \
    | grep -o "$2" | head -1 | sed 's/.*:"\{0,1\}\([^",]*\)"\{0,1\}$/\1/'
}
failed_tests() {  # names of failed test cases in a build's report, comma-separated
  curl -sf "$job/$1/testReport/api/json?tree=suites%5Bcases%5BclassName,name,status%5D%5D" \
    | grep -o '"className":"[^"]*","name":"[^"]*","status":"\(FAILED\|REGRESSION\)"' \
    | sed 's/"className":"\([^"]*\)","name":"\([^"]*\)".*/\1::\2/' | paste -sd, - || true
}

# Both green builds (the first, and the revert, which is the last green build) with console, summary, tests.
for n in "$green" "$revert"; do
  curl -sf "$job/$n/consoleText" > "$out/build-$n-console.txt"
  curl -sf "$job/$n/api/json?tree=number,result,duration,timestamp,url,actions%5BlastBuiltRevision%5BSHA1%5D,totalCount,failCount,skipCount,causes%5BshortDescription%5D%5D,artifacts%5BrelativePath%5D" \
    > "$out/build-$n-summary.json"
  curl -sf "$job/$n/testReport/api/json?tree=passCount,failCount,skipCount,suites%5Bname,cases%5BclassName,name,status%5D%5D" \
    > "$out/build-$n-tests.json"
done
curl -sf "$job/$red/consoleText" > "$out/build-$red-console.txt"
bash scripts/jenkins_admin_get.sh /job/autonomy-test-harness/config.xml "$out/job-config.xml" > /dev/null

{
  printf '{\n  "job": "%s",\n' "$job"
  for role in green red revert; do
    n="${!role}"
    sha="$(build_field "$n" '"SHA1":"[0-9a-f]*"')"
    result="$(build_field "$n" '"result":"[A-Z_]*"')"
    printf '  "%s": {"build": %s, "commit": "%s", "result": "%s", "failed_tests": "%s"}' \
      "$role" "$n" "$sha" "$result" "$(failed_tests "$n")"
    [ "$role" = "revert" ] && printf '\n' || printf ',\n'
  done
  printf '}\n'
} > "$out/verification.json"
cat "$out/verification.json"
grep -E "<spec>" "$out/job-config.xml"
