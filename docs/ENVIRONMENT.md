# Environment

This file records the exact version of every tool, package, and dependency the
Autonomy Test Harness relies on (Requirement 0.5), each beside an artifact obtained
on this machine that proves it: a package-manager query, a documentation reference
for that exact version, or a passing test (Requirement 0.6). Evidence files live
under `docs/evidence/`; the image-side files are written by
`bash scripts/collect_evidence.sh --image ath-sim:<commit>`.

The "target machine" for every Simulation step is the owner's Windows 11 PC running
the project's `ath-sim` Docker image in Docker Engine inside WSL 2 (`Ubuntu-24.04`).
Package versions are read with `dpkg-query` inside that image. Evidence below was
collected from `ath-sim:814a2c39bed7ff27bb2f3c8a87d1d108db3c3047`
(`docs/evidence/image_id.txt`).

## Versions

| Component | Exact version | Evidence |
| --- | --- | --- |
| OS (image) | Ubuntu 24.04.5 LTS (noble) | `/etc/os-release` in `results/m0_baseline.json` (`versions.os_release`) |
| ROS 2 | Jazzy (`ros-jazzy-ros-base` 0.11.0-1noble.20261006.035407) | `docs/evidence/image_dpkg.txt`; `ROS_DISTRO=jazzy` in `results/m0_baseline.json` |
| Gazebo Harmonic (gz-sim) | 8.15.0 (`ros-jazzy-gz-sim-vendor` 0.0.13-1noble.20260905.073557) | `docs/evidence/m0/gz_sim_versions.txt` (`gz sim --versions`); `docs/evidence/image_dpkg.txt` |
| gz-rendering (vendor) | `ros-jazzy-gz-rendering-vendor` 0.0.7-1noble.20260905.065113 | `docs/evidence/image_dpkg.txt` |
| gz-tools (vendor) | `ros-jazzy-gz-tools-vendor` 0.0.8-1noble.20260820.143431 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-navigation2 | 1.3.13-1noble.20260921.033624 | `docs/evidence/m0/dpkg_query.txt` (`dpkg-query -W`, M0) |
| ros-jazzy-nav2-bringup | 1.3.13-1noble.20261006.042503 | `docs/evidence/m0/dpkg_query.txt` |
| ros-jazzy-nav2-amcl | 1.3.13-1noble.20260921.024928 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-nav2-simple-commander | 1.3.13-1noble.20260921.030016 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-nav2-minimal-tb4-sim | 1.0.1-1noble.20261006.041301 | `docs/evidence/m0/dpkg_query.txt` |
| ros-jazzy-nav2-minimal-tb4-description | 1.0.1-1noble.20260915.195305 | `docs/evidence/m0/dpkg_query.txt` |
| ros-jazzy-nav2-minimal-tb3-sim | 1.0.1-1noble.20261006.041307 (installed as a dependency of `nav2_bringup`; unused) | `docs/evidence/m0/dpkg_query.txt` |
| ros-jazzy-ros-gz-sim | 1.0.24-1noble.20261006.035056 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-ros-gz-bridge | 1.0.24-1noble.20260920.234644 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-ros-gz-image | 1.0.24-1noble.20260921.023911 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-rosbag2 | 0.26.11-1noble.20261006.034645 | `docs/evidence/image_dpkg.txt` |
| ros-jazzy-rosbag2-storage-mcap | 0.26.11-1noble.20260911.143733 | `docs/evidence/image_dpkg.txt` |
| Mesa (`libgl1-mesa-dri`, `libegl-mesa0`) | 25.2.8-0ubuntu0.24.04.4 | `docs/evidence/image_dpkg.txt` |
| libegl1 (glvnd) | 1.7.0-1build1 | `docs/evidence/image_dpkg.txt` |
| xvfb | 2:21.1.12-1ubuntu1.8 | `docs/evidence/image_dpkg.txt` |
| mesa-utils | 9.0.0-2 | `docs/evidence/image_dpkg.txt` |
| git (image) | 1:2.43.0-1ubuntu7.3 | `docs/evidence/image_dpkg.txt` |
| procps (image) | 2:4.0.4-4ubuntu3.3 | `docs/evidence/image_dpkg.txt` |
| Python (image) | 3.12.3 | `docs/evidence/image_python.txt` |
| Python packages | see "Python packages" | `docs/evidence/image_python_packages.txt`, `uv.lock` |
| Base image | `ros:jazzy-ros-base-noble@sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410` | `docker/base-image.txt` (resolved by `scripts/resolve_apt_pins.sh`) |
| uv image (build stage) | `ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336` | `docker/uv-image.txt` |
| uv (host, for `uv lock`) | 0.13.1 | `docs/evidence/host_uv_version.txt` |
| Docker Engine (host, WSL) | 29.9.1 (client and server) | `docs/evidence/host_docker_version.txt` (`docker version`) |
| Docker Compose plugin (host) | v5.6.0 | `docs/evidence/host_docker_compose_version.txt` |

## Host

Windows 11 Pro desktop; WSL 2 distribution `Ubuntu-24.04` with Docker Engine and the
Compose plugin installed by the owner (no Docker Desktop involvement). Host versions are
in the table above. The host has no Python environment; all Python runs in the image.

## Docker image

`docker/Dockerfile` builds `ath-sim` from the base image pinned by digest
(`docker/base-image.txt`), installs exactly the apt versions in `docker/apt-pins.txt`,
copies `uv` from its digest-pinned image, creates `/opt/venv` with system site packages
(so ROS's `rclpy` and `rosbag2_py` stay importable), and installs the Python packages
with `uv sync --frozen` from `uv.lock`. Reported runs use `ath-sim:<40-character commit>`
built by `bash scripts/build_image.sh --tag ath-sim:<commit>` from a clean tree.

Pins (resolved by `bash scripts/resolve_apt_pins.sh` on 2026-10-17; checked by
`python scripts/check_dockerfile_pins.py`, which fails if a base is not digest-pinned, if any
`apt-get install` lacks an exact version from `docker/apt-pins.txt`, or if Python packages come
from anywhere but `uv.lock`):

- Base image (`docker/base-image.txt`): `ros:jazzy-ros-base-noble@sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410`
- uv build stage (`docker/uv-image.txt`): `ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336`
- `docker/apt-pins.txt` (every top-level apt package and its exact version):
  - `ros-jazzy-navigation2=1.3.13-1noble.20260921.033624`
  - `ros-jazzy-nav2-bringup=1.3.13-1noble.20261006.042503`
  - `ros-jazzy-nav2-minimal-tb4-sim=1.0.1-1noble.20261006.041301`
  - `ros-jazzy-nav2-minimal-tb4-description=1.0.1-1noble.20260915.195305`
  - `ros-jazzy-nav2-simple-commander=1.3.13-1noble.20260921.030016`
  - `ros-jazzy-rosbag2-storage-mcap=0.26.11-1noble.20260911.143733`
  - `git=1:2.43.0-1ubuntu7.3`
  - `procps=2:4.0.4-4ubuntu3.3`
  - `xvfb=2:21.1.12-1ubuntu1.8`
  - `libegl1=1.7.0-1build1`
  - `libegl-mesa0=25.2.8-0ubuntu0.24.04.4`
  - `libgl1-mesa-dri=25.2.8-0ubuntu0.24.04.4`
  - `mesa-utils=9.0.0-2`

Dependencies of these packages are installed at the versions the ROS and Ubuntu repositories held
at build time; `docs/evidence/image_dpkg.txt` records the ones the harness relies on directly.

## Python packages

From `uv.lock`, installed in the image (`docs/evidence/image_python_packages.txt`;
licenses from each package's metadata in `docs/evidence/licenses.json`):

| Package | Version |
| --- | --- |
| pydantic | 2.14.1 |
| pydantic-core | 2.50.1 |
| numpy | 1.26.4 |
| PyYAML | 6.0.3 |
| hypothesis | 6.170.1 |
| pytest | 9.1.1 |
| pytest-cov | 7.1.0 |
| coverage | 7.16.2 |
| annotated-types | 0.8.0 |
| typing-extensions | 4.16.0 |
| typing-inspection | 0.4.4 |
| iniconfig | 2.3.1 |
| packaging | 26.3 |
| pluggy | 1.7.0 |
| pygments | 2.21.0 |
| sortedcontainers | 2.4.0 |

`colorama` 0.4.6 is in `uv.lock` only as a Windows-only dependency of pytest and is not
installed in the image.

## Headless rendering

Method: **EGL, headless, on Mesa's `llvmpipe` software rasterizer** (CPU rendering; no GPU
and no display). The stock launch does not pass `--headless-rendering`; with no `DISPLAY`,
OGRE 2 fails to open an X display and switches to EGL by itself. `ogre2.log` from the M0 run
shows `EGL_MESA_device_software` and `GL_RENDERER = llvmpipe (LLVM 20.1.2, 256 bits)`
(`docs/evidence/m0/egl/ogre2.log`), and the lidar produced 360 finite ranges per scan
(`render.attempts[0].finite_ranges` in `results/m0_baseline.json`). The Xvfb fallback was
not needed. The image's default `ATH_RENDER_MODE` is `egl`.

Check from a known scene (Requirement 8.3): `bash scripts/check_headless_render.sh` (seed 0, commit
`eab421795f3efad6cf9e0ef2269c98b714bc47ed`) starts the arena with no display attached, places a 1.0 m box with
its near face 2.0 m ahead of the lidar, and reads one `/scan`: the forward beam measured 2.0009 m (expected
2.0 m within 0.05 m) and 360 of 360 ranges were finite. Result: PASS (`results/headless_render_check.txt`).

## M0 outcome

From `results/m0_baseline.json`, written by `bash scripts/run_m0.sh` (seed 0, commit
`814a2c39bed7ff27bb2f3c8a87d1d108db3c3047`, image `ath-sim:814a2c39bed7ff27bb2f3c8a87d1d108db3c3047`):

- **Confirmed package versions (Requirement 1.2):** `ros-jazzy-navigation2` 1.3.13-1noble.20260921.033624,
  `ros-jazzy-nav2-bringup` 1.3.13-1noble.20261006.042503, `ros-jazzy-nav2-minimal-tb4-sim`
  1.0.1-1noble.20261006.041301, `ros-jazzy-nav2-minimal-tb4-description` 1.0.1-1noble.20260915.195305,
  `ros-jazzy-nav2-minimal-tb3-sim` 1.0.1-1noble.20261006.041307 (`docs/evidence/m0/dpkg_query.txt`).
- **Rendering method:** EGL (see "Headless rendering").
- **Headless launch (Requirement 1.3):** `tb4_simulation_launch.py headless:=True use_rviz:=False` with
  the arena world and map and the stock `nav2_params.yaml`, in a container with no display. The launch
  log (`docs/evidence/m0/egl/launch.log`) has no `[ERROR]` line, no dead process, and no traceback before
  the harness's teardown SIGINT (`launch_log_check`). After the SIGINT, Nav2's component container logs
  18 shutdown errors and crashes while shutting down; that happens only during teardown.
- **Single goal (Requirement 1.4):** start (-3.0, -3.0, 0.0), goal (3.0, 3.0, 1.57) through
  `NavigateToPose`. Nav2 reported `SUCCEEDED` 20.103 s of simulation time after dispatch; the true
  final pose from Gazebo was (2.9254, 3.1135, yaw 1.3805), **0.1358 m** from the goal (tolerance 0.30 m)
  with a yaw error of 0.1895 rad. 1228 Ground_Truth samples were recorded; no process was left over.
- **Lidar mount yaw from TF:** `base_link` to `rplidar_link` yaw = +90.0°, so the robot's forward
  direction is scan bearing 270°.
- **Robot model name:** Gazebo names the spawned model `turtlebot4` (the URDF's name; the stock
  spawn's `-entity nav2_turtlebot4` is not what `ros_gz_sim create` uses with `-topic robot_description`),
  so the Ground_Truth reader and the Runner use `turtlebot4` (`render.attempts[0].models`).
- **If M0 fails:** the failing step and its observed effect are recorded here; M0 passed, so there is none.

## Jenkins

Not set up yet; task 6.2 records Jenkins, its plugins, and the Docker CLI here.

## Reproducibility limit

The ROS apt repository keeps only each package's current version, so a pinned version
disappears after the next ROS sync; a rebuild then fails loudly at `apt-get` instead of
drifting. `bash scripts/resolve_apt_pins.sh` re-resolves the pins. Each reported run names
its image (`ath-sim:<commit>`), and the image ID used for this evidence is recorded in
`docs/evidence/image_id.txt`. ROS snapshot repositories exist for LTS distributions but were
reported months behind in 2026, so they are not relied on.
