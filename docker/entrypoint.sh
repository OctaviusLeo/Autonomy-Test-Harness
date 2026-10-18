#!/usr/bin/env bash
# ath-sim entrypoint: ROS environment, world resource path, render mode, then the command.
#   ATH_RENDER_MODE=egl   no display; gz-rendering falls back to headless EGL on Mesa (llvmpipe)
#   ATH_RENDER_MODE=xvfb  start Xvfb :99 inside this container and render through GLX on llvmpipe
set -eo pipefail
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
export GZ_SIM_RESOURCE_PATH="/opt/ath/worlds${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"
export LIBGL_ALWAYS_SOFTWARE=1

case "${ATH_RENDER_MODE:-egl}" in
  egl)
    unset DISPLAY WAYLAND_DISPLAY
    ;;
  xvfb)
    if [ ! -S /tmp/.X11-unix/X99 ]; then
      Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp > /tmp/xvfb.log 2>&1 &
      for _ in $(seq 100); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
    fi
    export DISPLAY=:99
    ;;
  *)
    echo "ath-entrypoint: unknown ATH_RENDER_MODE '${ATH_RENDER_MODE}' (expected egl or xvfb)" >&2
    exit 2
    ;;
esac

exec "$@"
