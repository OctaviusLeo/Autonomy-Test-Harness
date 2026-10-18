#!/usr/bin/env bash
# Build and start the local Jenkins controller (Compose project ath-jenkins, http://127.0.0.1:8091).
# Creates ~/.config/ath/jenkins.env (mode 600) with a random 32-character admin password if it is missing;
# the password is never printed. Waits until /login answers 200.
# Usage: bash scripts/jenkins_up.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

config_dir="$HOME/.config/ath"
env_file="$config_dir/jenkins.env"
mkdir -p "$config_dir"
chmod 700 "$config_dir"
if [ ! -s "$env_file" ]; then
  (umask 077
   password=""
   # Every stage reads its whole input, so no SIGPIPE trips pipefail.
   while [ "${#password}" -lt 32 ]; do
     password="$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-32)"
   done
   printf 'ATH_JENKINS_ADMIN_PASSWORD=%s\n' "$password" > "$env_file")
  echo "jenkins_up: created $env_file (mode 600)"
fi
chmod 600 "$env_file"

export ATH_SHARED="${ATH_SHARED:-$HOME/ath-shared}"
export ATH_REPO="$PWD"
export ATH_JENKINS_ENV_FILE="$env_file"
DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
export DOCKER_GID
mkdir -p "$ATH_SHARED/jenkins"

docker compose -p ath-jenkins -f ci/jenkins/docker-compose.yml up -d --build

for _ in $(seq 120); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/login || true)"
  if [ "$code" = "200" ]; then
    echo "jenkins_up: http://127.0.0.1:8091/login answers 200"
    exit 0
  fi
  sleep 5
done
echo "jenkins_up: /login did not answer 200 within 10 minutes (last code $code)" >&2
docker logs --tail 50 ath-jenkins >&2 || true
exit 1
