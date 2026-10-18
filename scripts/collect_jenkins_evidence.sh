#!/usr/bin/env bash
# Write the Jenkins evidence docs/ENVIRONMENT.md and THIRD_PARTY.md cite: the controller's version, the
# Docker CLI and Buildx inside it, and every installed plugin with its version and the license its own
# pom.xml declares (plugins whose pom declares none inherit the Jenkins plugin parent POM's MIT license).
# Usage: bash scripts/collect_jenkins_evidence.sh   (the controller must be running)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
out=docs/evidence/jenkins
mkdir -p "$out"
curl -sI http://127.0.0.1:8091/login | grep -i '^x-jenkins:' | tr -d '\r' > "$out/jenkins_version.txt"
docker image inspect --format '{{.Id}}' ath-jenkins:local > "$out/ath_jenkins_image_id.txt"
docker exec ath-jenkins bash -c 'java -version 2>&1 | head -1; docker version --format "docker CLI {{.Client.Version}} (server {{.Server.Version}})"; docker buildx version' \
  > "$out/jenkins_tools.txt"
docker exec ath-jenkins bash -c '
  cd /var/jenkins_home/plugins
  for f in *.jpi; do
    name="${f%.jpi}"
    version="$(unzip -p "$f" META-INF/MANIFEST.MF | tr -d "\r" | sed -n "s/^Plugin-Version: //p")"
    licenses="$(unzip -p "$f" "META-INF/maven/*/pom.xml" 2>/dev/null | tr -d "\r\n" \
      | grep -o "<licenses>.*</licenses>" | grep -o "<name>[^<]*</name>" | sed "s/<[^>]*>//g" | paste -sd ";" - || true)"
    printf "%s\t%s\t%s\n" "$name" "$version" "${licenses:-MIT (inherited from the Jenkins plugin parent POM)}"
  done' > "$out/jenkins_plugins.tsv"
echo "collect_jenkins_evidence: $(wc -l < "$out/jenkins_plugins.tsv") plugins; $(cat "$out/jenkins_version.txt")"
