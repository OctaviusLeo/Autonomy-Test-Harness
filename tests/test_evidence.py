"""Tests for version and license evidence collection (Requirements 0.5-0.7)."""

from __future__ import annotations

import json
import subprocess
from email.message import Message
from importlib import metadata

from harness import evidence

LOCK = """version = 1
[[package]]
name = "autonomy-test-harness"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "pyyaml"
version = "6.0.3"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "colorama"
version = "0.4.6"
source = { registry = "https://pypi.org/simple" }
"""


def _meta(**fields) -> Message:
    msg = Message()
    for key, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            msg[key.replace("_", "-")] = v
    return msg


def test_locked_packages_skip_the_project():
    assert evidence.locked_packages(LOCK) == {"pyyaml": "6.0.3", "colorama": "0.4.6"}


def test_python_license_preference_order():
    assert evidence.python_license(_meta(License_Expression="MIT")) == "MIT"
    assert evidence.python_license(_meta(Classifier=["License :: OSI Approved :: BSD License", "Topic :: X"])) == "BSD License"
    assert evidence.python_license(_meta(License="Apache 2.0\nlong text")) == "Apache 2.0"
    assert evidence.python_license(_meta()) == "UNKNOWN"


def test_ros_and_debian_licenses():
    xml = '<package><license>Apache-2.0</license><license file="x">BSD</license><license>Apache-2.0</license></package>'
    assert evidence.ros_package_license(xml) == "Apache-2.0 AND BSD"
    assert evidence.ros_package_license("<package/>") == "UNKNOWN"
    assert evidence.debian_copyright_license("Format: x\nFiles: *\nLicense: GPL-2\n") == "GPL-2"
    assert evidence.debian_copyright_license("free text") == "UNKNOWN"
    assert evidence.ros_share_name("ros-jazzy-nav2-bringup") == "nav2_bringup"


def test_collect_writes_the_evidence_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text(LOCK)
    share = tmp_path / "share"
    (share / "nav2_bringup").mkdir(parents=True)
    (share / "nav2_bringup" / "package.xml").write_text("<package><license>Apache-2.0</license></package>")
    doc = tmp_path / "doc"
    (doc / "git").mkdir(parents=True)
    (doc / "git" / "copyright").write_text("License: GPL-2\n")

    def run(cmd, capture_output, text):
        assert cmd[:4] == ["dpkg-query", "-W", "-f", "${Package}\t${Version}\n"]
        out = "ros-jazzy-nav2-bringup\t1.3.13\ngit\t1:2.43\nros-jazzy-ros-base\t\nmesa-utils\t9.0.0-2\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    class Dist:
        version = "6.0.3"
        metadata = _meta(License="MIT License")

    def dist(name):
        if name == "colorama":
            raise metadata.PackageNotFoundError(name)
        return Dist()

    data = evidence.collect(repo, tmp_path / "out", "git=1:2.43\nmesa-utils=9.0.0-2\n", run=run, share=share, doc=doc, dist=dist)
    assert data["apt"]["ros-jazzy-nav2-bringup"] == {"version": "1.3.13", "license": "Apache-2.0"}
    assert data["apt"]["git"]["license"] == "GPL-2"
    assert data["apt"]["mesa-utils"]["license"] == "UNKNOWN"
    assert "ros-jazzy-ros-base" not in data["apt"]
    assert data["python"]["colorama"]["installed"] is None
    assert (tmp_path / "out" / "image_python_packages.txt").read_text() == "pyyaml==6.0.3\n"
    assert "git\t1:2.43\n" in (tmp_path / "out" / "image_dpkg.txt").read_text()
    assert json.loads((tmp_path / "out" / "licenses.json").read_text())["python"]["pyyaml"]["license"] == "MIT License"
