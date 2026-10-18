# ath-sim: ROS 2 Jazzy + Gazebo Harmonic + Nav2 and its minimal TurtleBot 4 simulation,
# rendering on the CPU (Mesa llvmpipe), plus the harness's Python environment.
# Build: bash scripts/build_image.sh [--tag ath-sim:<commit>]
# Pins: docker/base-image.txt, docker/uv-image.txt and docker/apt-pins.txt
# (written by scripts/resolve_apt_pins.sh, checked by scripts/check_dockerfile_pins.py).

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM ros:jazzy-ros-base-noble@sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Exact apt versions only; every package and version comes from docker/apt-pins.txt.
COPY docker/apt-pins.txt /tmp/apt-pins.txt
RUN apt-get update \
 && xargs -a /tmp/apt-pins.txt apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

RUN git config --system --add safe.directory '*'

# Python: a venv that still sees ROS's system packages (rclpy, rosbag2_py), filled from uv.lock.
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /opt/ath
COPY pyproject.toml uv.lock ./
RUN uv venv --system-site-packages --python /usr/bin/python3 /opt/venv \
 && uv sync --frozen --no-install-project

# The harness, installed editable at /opt/ath (a bind mount of the working tree replaces it in dev runs).
COPY . /opt/ath
RUN uv sync --frozen \
 && mkdir -p /results

ENV ATH_RENDER_MODE=egl
COPY docker/entrypoint.sh /usr/local/bin/ath-entrypoint
RUN chmod 755 /usr/local/bin/ath-entrypoint
ENTRYPOINT ["/usr/local/bin/ath-entrypoint"]
CMD ["bash"]
