#!/usr/bin/env bash
# POST to one Jenkins URL path as the admin user, with a CSRF crumb, without ever printing the password.
# The password is read from ~/.config/ath/jenkins.env into a private, temporary netrc file for curl; the crumb's
# session cookie goes to a private, temporary cookie jar. Both are removed on exit.
# Usage: bash scripts/jenkins_admin_post.sh <path, e.g. /job/autonomy-test-harness/build>
set -euo pipefail
path="$1"
base="http://127.0.0.1:8091"
env_file="$HOME/.config/ath/jenkins.env"
[ -r "$env_file" ] || { echo "jenkins_admin_post: $env_file is missing; run bash scripts/jenkins_up.sh" >&2; exit 1; }
password="$(sed -n 's/^ATH_JENKINS_ADMIN_PASSWORD=//p' "$env_file")"
netrc="$(umask 077; mktemp)"
jar="$(umask 077; mktemp)"
trap 'rm -f "$netrc" "$jar"' EXIT
printf 'machine 127.0.0.1 login admin password %s\n' "$password" > "$netrc"
unset password
crumb_json="$(curl -sf --max-time 30 --netrc-file "$netrc" -c "$jar" "$base/crumbIssuer/api/json" || true)"
header=()
if [ -n "$crumb_json" ]; then
  field="$(printf '%s' "$crumb_json" | grep -o '"crumbRequestField":"[^"]*"' | cut -d'"' -f4)"
  crumb="$(printf '%s' "$crumb_json" | grep -o '"crumb":"[^"]*"' | cut -d'"' -f4)"
  header=(-H "$field: $crumb")
fi
code="$(curl -s --max-time 30 --netrc-file "$netrc" -b "$jar" "${header[@]}" -X POST -o /dev/null \
  -w '%{http_code}' "$base$path" || true)"
case "$code" in
  2*|3*) echo "jenkins_admin_post: POST $path answered $code" ;;
  *) echo "jenkins_admin_post: POST $path answered ${code:-nothing}" >&2; exit 1 ;;
esac
