#!/usr/bin/env bash
# Fetch one Jenkins URL path as the admin user into a file, without ever printing the password.
# The password is read from ~/.config/ath/jenkins.env into a private, temporary netrc file for curl.
# Usage: bash scripts/jenkins_admin_get.sh <path, e.g. /job/autonomy-test-harness/config.xml> <output file>
set -euo pipefail
path="$1"; out="$2"
env_file="$HOME/.config/ath/jenkins.env"
[ -r "$env_file" ] || { echo "jenkins_admin_get: $env_file is missing; run bash scripts/jenkins_up.sh" >&2; exit 1; }
password="$(sed -n 's/^ATH_JENKINS_ADMIN_PASSWORD=//p' "$env_file")"
netrc="$(umask 077; mktemp)"
trap 'rm -f "$netrc"' EXIT
printf 'machine 127.0.0.1 login admin password %s\n' "$password" > "$netrc"
unset password
curl -sf --netrc-file "$netrc" -o "$out" "http://127.0.0.1:8091${path}"
echo "jenkins_admin_get: saved ${path} to ${out}"
