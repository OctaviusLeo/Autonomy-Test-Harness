"""Unit tests for scripts/check_dockerfile_pins.py (Requirements 8.1, 8.4)."""

from __future__ import annotations

import shutil

import pytest


@pytest.fixture
def root(tmp_path, repo_root):
    for rel in ("docker/Dockerfile", "docker/apt-pins.txt", "docker/base-image.txt", "docker/uv-image.txt", "uv.lock"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo_root / rel, tmp_path / rel)
    return tmp_path


def _edit(root, rel, old, new):
    path = root / rel
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_the_committed_image_is_pinned(root, load_script):
    script = load_script("check_dockerfile_pins")
    assert script.check(root) == []
    assert script.main(["--root", str(root)]) == 0


def test_unpinned_base_and_stray_packages_fail(root, load_script):
    script = load_script("check_dockerfile_pins")
    _edit(root, "docker/Dockerfile", "FROM ros:jazzy-ros-base-noble@sha256:", "FROM ros:jazzy-ros-base-noble-x@sha256:")
    _edit(root, "docker/Dockerfile", "RUN git config", "RUN apt-get update && apt-get install -y curl vim=2:9.1 && git config")
    _edit(root, "docker/Dockerfile", "uv sync --frozen --no-install-project", "uv sync --no-install-project")
    _edit(root, "docker/Dockerfile", "RUN uv sync --frozen", "RUN pip install requests")
    problems = "\n".join(script.check(root))
    for fragment in ("no FROM uses the pinned base", "apt-get install curl", "apt-get install vim=2:9.1",
                     "'pip install'", "uv sync --frozen"):
        assert fragment in problems
    assert script.main(["--root", str(root)]) == 1


def test_tag_only_from_and_bad_pin_lines_fail(root, load_script):
    script = load_script("check_dockerfile_pins")
    _edit(root, "docker/Dockerfile", "FROM ghcr.io/astral-sh/uv:0.13.1@sha256:", "FROM ghcr.io/astral-sh/uv:0.13.1 AS old\nFROM x@sha256:")
    (root / "docker/apt-pins.txt").write_text((root / "docker/apt-pins.txt").read_text() + "mesa-utils\nlibfoo=*\n")
    (root / "uv.lock").unlink()
    problems = "\n".join(script.check(root))
    for fragment in ("FROM ghcr.io/astral-sh/uv:0.13.1 is not pinned by digest", "no FROM uses the pinned uv image",
                     "'mesa-utils' is not an exact", "'libfoo=*' is not an exact", "uv.lock is missing"):
        assert fragment in problems
    (root / "docker/apt-pins.txt").write_text("")
    assert "apt-pins.txt is empty" in "\n".join(script.check(root))


def test_pins_file_must_be_copied(root, load_script):
    script = load_script("check_dockerfile_pins")
    _edit(root, "docker/Dockerfile", "COPY docker/apt-pins.txt /tmp/apt-pins.txt\n", "")
    assert any("never copies docker/apt-pins.txt" in p for p in script.check(root))


def test_parsing_helpers(load_script):
    script = load_script("check_dockerfile_pins")
    steps = script.instructions("# c\nFROM a@sha256:x\nRUN apt-get update \\\n && apt-get install -y b=1 c=2\n")
    assert steps == [("FROM", "a@sha256:x"), ("RUN", "apt-get update && apt-get install -y b=1 c=2")]
    assert script.apt_install_packages(steps[1][1]) == [["b=1", "c=2"]]
    assert script.apt_install_packages("xargs -a /tmp/apt-pins.txt apt-get install -y --no-install-recommends") == [["<pins-file>"]]
