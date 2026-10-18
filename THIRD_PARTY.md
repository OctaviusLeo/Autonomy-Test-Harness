# Third-party dependencies

Every third-party package, image, or asset this repository uses is listed here with
its version and license identifier (Requirement 0.7). Licenses were read from each
package's own metadata on this machine: Python package metadata, ROS `package.xml`
`<license>` tags, and Debian `copyright` files (`docs/evidence/licenses.json`, written by
`bash scripts/collect_evidence.sh`). Nothing here is vendored into the repository except
`docs/evidence/nav2_params_stock.yaml` (a copy of Nav2's stock parameter file, Apache-2.0,
kept as the evidence for the parameter diff) and `config/nav2_params_ath.yaml` (derived
from it by changing four topic names). Images and packages are fetched at build time.

This repository is private: no public license, no packaging, no public releases.

## Docker images

| Name | Version | License |
| --- | --- | --- |
| `ros:jazzy-ros-base-noble` (Docker Official Image, Ubuntu 24.04 base) | `sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410` | Apache-2.0 (image definition and ROS 2 base); Ubuntu packages under their own licenses |
| `ghcr.io/astral-sh/uv` (build stage; only the `uv` binary is copied) | 0.13.1, `sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336` | Apache-2.0 OR MIT |

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

Added in task 6.2.

| Name | Version | License |
| --- | --- | --- |
