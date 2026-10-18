# ath-jenkins:local: the project's Jenkins controller, configured entirely from files in this directory.
# Built and started by scripts/jenkins_up.sh (Compose project ath-jenkins).
FROM docker:29.9.1-cli@sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800 AS dockercli

FROM jenkins/jenkins:2.580.1-lts-jdk21@sha256:a660310e39ade10631f774bacd5219de767dfd08947ea5c32a739b5e5bb382c1

USER root
# The Docker CLI and its Buildx plugin, so pipeline steps drive the host's Docker Engine through its socket.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
# The repository is mounted read-only from the host and owned by another uid there.
RUN git config --system --add safe.directory '*'

USER jenkins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY casc.yaml /opt/ath-jenkins/casc.yaml
ENV CASC_JENKINS_CONFIG=/opt/ath-jenkins/casc.yaml
