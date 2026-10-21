# Third-party dependencies

Every third-party package, image, or asset this repository uses is listed here with
its version and license identifier (Requirement 0.7). Licenses were read from each
package's own metadata on this machine: Python package metadata, ROS `package.xml`
`<license>` tags, and Debian `copyright` files (`docs/evidence/licenses.json`, written by
`bash scripts/collect_evidence.sh`). Nothing here is vendored into the repository except
`docs/evidence/nav2_params_stock.yaml` (a copy of Nav2's stock parameter file, Apache-2.0,
kept as the evidence for the parameter diff) and `config/nav2_params_ath.yaml` (derived
from it by changing four topic names). Images and packages are fetched at build time.

This repository's own code is under the MIT License (`LICENSE`); the third-party components below keep their
own licenses and, apart from the two parameter files above, none of them is redistributed here. Those two
files come from `nav2_bringup` (Apache-2.0, <https://www.apache.org/licenses/LICENSE-2.0>) and keep that
license; the derived file states at its top how it was changed. There is no packaging or release.

## Docker images

| Name | Version | License |
| --- | --- | --- |
| `ros:jazzy-ros-base-noble` (Docker Official Image, Ubuntu 24.04 base) | `sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410` | Apache-2.0 (image definition and ROS 2 base); Ubuntu packages under their own licenses |
| `ghcr.io/astral-sh/uv:0.13.1` (build stage; only the `uv` binary is copied) | 0.13.1, `sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336` | Apache-2.0 OR MIT |

## ROS 2, Nav2, and Gazebo packages (in the `ath-sim` image)

| Name | Version | License |
| --- | --- | --- |
| ros-jazzy-ros-base | 0.11.0-1noble.20261006.035407 | Apache-2.0 |
| ros-jazzy-navigation2 | 1.3.13-1noble.20260921.033624 | Apache-2.0 |
| ros-jazzy-nav2-bringup | 1.3.13-1noble.20261006.042503 | Apache-2.0 |
| ros-jazzy-nav2-amcl | 1.3.13-1noble.20260921.024928 | LGPL-2.1-or-later |
| ros-jazzy-nav2-simple-commander | 1.3.13-1noble.20260921.030016 | Apache-2.0 |
| ros-jazzy-nav2-minimal-tb4-sim | 1.0.1-1noble.20261006.041301 | Apache-2.0 |
| ros-jazzy-nav2-minimal-tb4-description | 1.0.1-1noble.20260915.195305 | Apache-2.0 |
| ros-jazzy-nav2-minimal-tb3-sim | 1.0.1-1noble.20261006.041307 | Apache-2.0 |
| ros-jazzy-ros-gz-sim | 1.0.24-1noble.20261006.035056 | Apache-2.0 |
| ros-jazzy-ros-gz-bridge | 1.0.24-1noble.20260920.234644 | Apache-2.0 |
| ros-jazzy-ros-gz-image | 1.0.24-1noble.20260921.023911 | Apache-2.0 |
| ros-jazzy-gz-sim-vendor (Gazebo Harmonic gz-sim 8.15.0) | 0.0.13-1noble.20260905.073557 | Apache-2.0 |
| ros-jazzy-gz-rendering-vendor | 0.0.7-1noble.20260905.065113 | Apache-2.0 |
| ros-jazzy-gz-tools-vendor | 0.0.8-1noble.20260820.143431 | Apache-2.0 |
| ros-jazzy-rosbag2 | 0.26.11-1noble.20261006.034645 | Apache-2.0 |
| ros-jazzy-rosbag2-storage-mcap | 0.26.11-1noble.20260911.143733 | Apache-2.0 |

`nav2_amcl` is LGPL-2.1-or-later; the harness uses it unmodified as an installed package
and does not link against it.

## System packages (in the `ath-sim` image)

| Name | Version | License |
| --- | --- | --- |
| libgl1-mesa-dri (Mesa, llvmpipe) | 25.2.8-0ubuntu0.24.04.4 | MIT |
| libegl-mesa0 | 25.2.8-0ubuntu0.24.04.4 | MIT |
| libegl1 (glvnd) | 1.7.0-1build1 | MIT |
| mesa-utils | 9.0.0-2 | MIT (free-form `copyright` file; core Mesa license) |
| xvfb (X.Org server) | 2:21.1.12-1ubuntu1.8 | MIT (X.Org standard license; free-form `copyright` file) |
| git | 1:2.43.0-1ubuntu7.3 | GPL-2.0 |
| procps | 2:4.0.4-4ubuntu3.3 | LGPL-2.1-or-later |

## Python packages (from `uv.lock`)

| Name | Version | License |
| --- | --- | --- |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| numpy | 1.26.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| hypothesis | 6.170.1 | MPL-2.0 |
| pytest | 9.1.1 | MIT |
| pytest-cov | 7.1.0 | MIT |
| coverage | 7.16.2 | Apache-2.0 |
| annotated-types | 0.8.0 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| iniconfig | 2.3.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.7.0 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| sortedcontainers | 2.4.0 | Apache-2.0 |
| colorama (Windows-only dependency of pytest; not installed in the image) | 0.4.6 | BSD-3-Clause (PyPI metadata for 0.4.6: BSD License classifier) |
| setuptools (build backend for the editable install) | 84.0.0 | MIT (PyPI metadata for 84.0.0: License-Expression MIT) |

## Jenkins and plugins

The controller image `ath-jenkins:local` is built from these and is not distributed. Plugin licenses are
the ones each plugin's own `pom.xml` declares (`docs/evidence/jenkins/jenkins_plugins.tsv`, written by
`bash scripts/collect_jenkins_evidence.sh`), shown here as SPDX identifiers.

| Name | Version | License |
| --- | --- | --- |
| `jenkins/jenkins:2.580.1-lts-jdk21` (Jenkins LTS 2.580.1, OpenJDK 21.0.12.1, Debian 13) | `sha256:a660310e39ade10631f774bacd5219de767dfd08947ea5c32a739b5e5bb382c1` | MIT (Jenkins core POM); GPL-2.0-with-classpath-exception (OpenJDK `legal/java.base/LICENSE`) |
| `docker:29.9.1-cli` (only the `docker` binary and the Buildx plugin are copied) | `sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800` | Apache-2.0 |
| Docker CLI | 29.9.1 | Apache-2.0 (github.com/docker/cli LICENSE) |
| Docker Buildx | v0.38.0 | Apache-2.0 (github.com/docker/buildx LICENSE) |
| antisamy-markup-formatter | 173.v680e3a_b_69ff3 | MIT |
| apache-httpcomponents-client-4-api | 4.5.14-269.vfa_2321039a_83 | MIT |
| asm-api | 9.11-224.v369c884f7a_a_b_ | MIT |
| bootstrap5-api | 5.3.8-1048.va_c299057e35c | MIT |
| bouncycastle-api | 2.30.1.86.2-310.v4655f6742752 | MIT |
| branch-api | 2.1303.v9f3b_95dc329d | MIT |
| caffeine-api | 3.3.0-210.v71b_2985ce530 | Apache-2.0 |
| checks-api | 422.vc7e8b_51488c6 | MIT |
| cloudbees-folder | 6.1106.v3a_d9a_6d2465e | MIT |
| commons-lang3-api | 3.21.0-122.v6a_ea_4fd34049 | Apache-2.0 |
| commons-text-api | 1.15.0-218.va_61573470393 | Apache-2.0 |
| configuration-as-code | 2136.veb_3a_554550b_f | MIT |
| credentials-binding | 728.v902a_273b_8947 | MIT |
| credentials | 1514.vb_01eb_014e7d4 | MIT |
| display-url-api | 2.217.va_6b_de84cc74b_ | MIT |
| durable-task | 686.v80ff80875b_82 | MIT |
| echarts-api | 6.1.0-1321.v86c4c5114494 | MIT |
| font-awesome-api | 7.3.1-1013.v0835a_879ec6d | MIT |
| git-client | 6.6.1 | MIT |
| git | 5.11.0 | MIT |
| gson-api | 2.14.0-201.v8eefe5515533 | Apache-2.0 |
| instance-identity | 203.v15e81a_1b_7a_38 | MIT |
| ionicons-api | 94.vcc3065403257 | MIT |
| jackson-annotations2-api | 2.22-19.v10a_a_582ea_26e | Apache-2.0 |
| jackson2-api | 2.22.3-447.v6a_93ce7d2c82 | Apache-2.0 AND BSD-3-Clause |
| jackson3-api | 3.2.3-101.v69fc84453a_8e | Apache-2.0 |
| jakarta-activation-api | 2.1.4-1 | BSD-3-Clause |
| jakarta-mail-api | 2.1.5-1 | EPL-2.0 |
| jakarta-xml-bind-api | 4.0.9-19.v2b_a_5b_44d9a_1c | BSD-3-Clause |
| javax-activation-api | 1.2.0-8 | CDDL-1.1 |
| jaxb | 2.3.9-143.v5979df3304e6 | MIT |
| job-dsl | 3732.v9a_c49a_61a_313 | Apache-2.0 |
| joda-time-api | 2.15.0-208.v6b_084e7a_d9f0 | Apache-2.0 |
| jquery3-api | 3.7.1-687.v68d468e40b_30 | MIT |
| json-api | 20260814-226.v20f9685d642c | MIT-0 |
| junit | 1442.vb_b_a_467df2767 | MIT |
| mailer | 534.v1b_36f5864073 | MIT |
| mina-sshd-api-common | 2.19.0-192.v2b_a_7b_2c1dc71 | MIT |
| mina-sshd-api-core | 2.19.0-192.v2b_a_7b_2c1dc71 | MIT |
| pipeline-build-step | 601.v6d4c6d1a_9dc7 | MIT |
| pipeline-groovy-lib | 822.vc95f70dea_db_7 | MIT |
| pipeline-input-step | 560.v56198a_642157 | MIT |
| pipeline-milestone-step | 152.v6e22b_8cfc66c | MIT |
| pipeline-model-api | 2.2293.v6e7193cec599 | MIT |
| pipeline-model-definition | 2.2293.v6e7193cec599 | MIT |
| pipeline-model-extensions | 2.2293.v6e7193cec599 | MIT |
| pipeline-stage-step | 345.va_96187909426 | MIT |
| pipeline-stage-tags-metadata | 2.2293.v6e7193cec599 | MIT |
| plain-credentials | 199.v9f8e1f741799 | MIT |
| plugin-util-api | 7.1403.vd380b_c42e90c | MIT |
| prism-api | 1.30.0-741.v034eb_0b_0a_a_fa_ | MIT |
| scm-api | 728.vc30dcf7a_0df5 | MIT |
| script-security | 1436.v1082791135e4 | MIT |
| snakeyaml-api | 2.7-152.vc672728cf536 | MIT |
| snakeyaml-engine-api | 3.2-18.v885ed7ff698f | Apache-2.0 |
| ssh-credentials | 372.va_250881b_08cd | MIT |
| structs | 362.va_b_695ef4fdf9 | MIT |
| variant | 70.va_d9f17f859e0 | MIT |
| woodstox-core-api | 7.3.0-16.v017f30ed004c | Apache-2.0 |
| workflow-aggregator | 608.v67378e9d3db_1 | MIT |
| workflow-api | 1413.v2ff1a_5e720fa_ | MIT |
| workflow-basic-steps | 1098.v808b_fd7f8cf4 | MIT |
| workflow-cps | 4395.v738456a_5da_6b_ | MIT |
| workflow-durable-task-step | 1479.v56e587f413a_7 | MIT |
| workflow-job | 1609.v8926e7962024 | MIT |
| workflow-multibranch | 842.v3a_b_59b_57b_e6e | MIT |
| workflow-scm-step | 487.v41313a_96b_65d | MIT |
| workflow-step-api | 724.v538c2362b_dfb_ | MIT |
| workflow-support | 1015.v785e5a_b_b_8b_22 | MIT |
