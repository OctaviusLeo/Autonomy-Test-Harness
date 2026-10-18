"""Collect version and license evidence inside the ath-sim image (Requirements 0.5-0.7).

Versions come from the package managers themselves (``dpkg-query`` for apt packages,
``importlib.metadata`` for the Python packages installed from ``uv.lock``); licenses come from the
packages' own metadata (Python ``License-Expression``/``License`` fields and classifiers, ROS
``package.xml`` ``<license>`` tags, Debian ``copyright`` files). docs/ENVIRONMENT.md and
THIRD_PARTY.md cite the files this module writes under docs/evidence/.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Callable

ROS_PACKAGES = (
    "ros-jazzy-ros-base", "ros-jazzy-navigation2", "ros-jazzy-nav2-bringup", "ros-jazzy-nav2-amcl",
    "ros-jazzy-nav2-minimal-tb4-sim", "ros-jazzy-nav2-minimal-tb4-description", "ros-jazzy-nav2-simple-commander",
    "ros-jazzy-ros-gz-sim", "ros-jazzy-ros-gz-bridge", "ros-jazzy-ros-gz-image", "ros-jazzy-gz-sim-vendor",
    "ros-jazzy-gz-rendering-vendor", "ros-jazzy-gz-tools-vendor", "ros-jazzy-rosbag2", "ros-jazzy-rosbag2-storage-mcap",
)


def locked_packages(uv_lock_text: str) -> dict[str, str]:
    """Package name -> version for every registry package in uv.lock (the project itself excluded)."""
    data = tomllib.loads(uv_lock_text)
    return {p["name"]: p["version"] for p in data.get("package", [])
            if "registry" in (p.get("source") or {})}


def python_license(dist_metadata) -> str:
    """The best license statement in a distribution's metadata."""
    expression = dist_metadata.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [c.split("::")[-1].strip() for c in dist_metadata.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        return " / ".join(classifiers)
    text = (dist_metadata.get("License") or "").strip()
    return text.splitlines()[0][:80] if text else "UNKNOWN"


def ros_package_license(package_xml_text: str) -> str:
    licenses = re.findall(r"<license(?:\s[^>]*)?>([^<]+)</license>", package_xml_text)
    return " AND ".join(dict.fromkeys(lic.strip() for lic in licenses)) or "UNKNOWN"


def debian_copyright_license(copyright_text: str) -> str:
    for line in copyright_text.splitlines():
        if line.startswith("License:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def dpkg_versions(packages, run: Callable = subprocess.run) -> dict[str, str]:
    result = run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\n", *packages],
                 capture_output=True, text=True)
    versions = {}
    for line in result.stdout.splitlines():
        name, _, version = line.partition("\t")
        if version:
            versions[name] = version
    return versions


def ros_share_name(apt_name: str) -> str:
    """ros-jazzy-nav2-bringup -> nav2_bringup (the share directory of the ROS package)."""
    return apt_name.removeprefix("ros-jazzy-").replace("-", "_")


def collect(repo: Path, out: Path, apt_pins_text: str, run: Callable = subprocess.run,
            share: Path = Path("/opt/ros/jazzy/share"), doc: Path = Path("/usr/share/doc"),
            dist: Callable = metadata.distribution) -> dict:
    """Write image_dpkg.txt, image_python_packages.txt, and licenses.json under ``out``; return the data."""
    pins = [line.split("=", 1)[0] for line in apt_pins_text.splitlines() if "=" in line]
    apt_names = list(dict.fromkeys([*ROS_PACKAGES, *pins]))
    apt = dpkg_versions(apt_names, run)
    locked = locked_packages((repo / "uv.lock").read_text(encoding="utf-8"))
    python = {}
    for name, version in sorted(locked.items()):
        try:
            found = dist(name)
        except metadata.PackageNotFoundError:
            # uv.lock is cross-platform; e.g. colorama is only a Windows dependency of pytest.
            python[name] = {"locked": version, "installed": None, "license": None}
            continue
        python[name] = {"locked": version, "installed": found.version, "license": python_license(found.metadata)}
    licenses = {}
    for name in apt:
        package_xml = share / ros_share_name(name) / "package.xml"
        if name.startswith("ros-jazzy-") and package_xml.exists():
            licenses[name] = ros_package_license(package_xml.read_text(encoding="utf-8"))
        else:
            copyright_file = doc / name / "copyright"
            licenses[name] = (debian_copyright_license(copyright_file.read_text(errors="replace"))
                              if copyright_file.exists() else "UNKNOWN")
    out.mkdir(parents=True, exist_ok=True)
    (out / "image_dpkg.txt").write_text("".join(f"{n}\t{v}\n" for n, v in apt.items()), encoding="utf-8")
    (out / "image_python_packages.txt").write_text(
        "".join(f"{n}=={p['installed']}\n" for n, p in python.items() if p["installed"]), encoding="utf-8")
    data = {"apt": {n: {"version": v, "license": licenses[n]} for n, v in apt.items()}, "python": python}
    (out / "licenses.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
