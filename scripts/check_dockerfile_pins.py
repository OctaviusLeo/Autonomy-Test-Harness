"""Check that the ath-sim image is fully pinned (Requirements 8.1, 8.4).

Fails, listing every problem, if:
- a FROM line is not pinned by sha256 digest, or the base and uv stages differ from docker/base-image.txt
  and docker/uv-image.txt;
- an `apt-get install` installs a package without an exact version from docker/apt-pins.txt (installing
  the pins file itself with `xargs -a /tmp/apt-pins.txt` counts as pinned when every line is name=version);
- Python packages come from anywhere but uv.lock (`uv sync --frozen` required; pip, `uv pip`, `uv add` forbidden).

Usage: python scripts/check_dockerfile_pins.py [--root .]
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

DIGEST = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
PIN_LINE = re.compile(r"^[a-z0-9][a-z0-9+.-]*=[A-Za-z0-9.+:~_-]+$")
PINS_FILE_IN_IMAGE = "/tmp/apt-pins.txt"
FORBIDDEN_PYTHON = ("pip install", "pip3 install", "uv pip", "uv add", "easy_install", "pipx")


def instructions(dockerfile: str) -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) pairs with line continuations joined and comments dropped."""
    joined = re.sub(r"\\\s*\n", " ", dockerfile)
    result = []
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, rest = line.partition(" ")
        result.append((keyword.upper(), " ".join(rest.split())))
    return result


def check_pins_file(text: str) -> list[str]:
    problems = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        problems.append("docker/apt-pins.txt is empty")
    for line in lines:
        if not PIN_LINE.match(line) or "*" in line:
            problems.append(f"docker/apt-pins.txt: '{line}' is not an exact name=version pin")
    return problems


def apt_install_packages(command: str) -> list[list[str]]:
    """The package arguments of every `apt-get install` in a RUN command (each list is one install)."""
    installs = []
    for part in re.split(r"&&|;|\|\|", command):
        tokens = shlex.split(part)
        if "apt-get" in tokens and "install" in tokens[tokens.index("apt-get"):]:
            after = tokens[tokens.index("install", tokens.index("apt-get")) + 1:]
            installs.append(["<pins-file>"] if _uses_pins_file(tokens) else [t for t in after if not t.startswith("-")])
    return installs


def _uses_pins_file(tokens: list[str]) -> bool:
    return tokens[:1] == ["xargs"] and "-a" in tokens and tokens[tokens.index("-a") + 1] == PINS_FILE_IN_IMAGE


def check(root: Path) -> list[str]:
    problems: list[str] = []
    dockerfile = (root / "docker" / "Dockerfile").read_text(encoding="utf-8")
    pins_text = (root / "docker" / "apt-pins.txt").read_text(encoding="utf-8")
    pins = {line.strip() for line in pins_text.splitlines() if line.strip()}
    base = (root / "docker" / "base-image.txt").read_text(encoding="utf-8").strip()
    uv_image = (root / "docker" / "uv-image.txt").read_text(encoding="utf-8").strip()
    problems += check_pins_file(pins_text)
    steps = instructions(dockerfile)
    froms = [args.split()[0] for kind, args in steps if kind == "FROM"]
    for image in froms:
        if not DIGEST.match(image):
            problems.append(f"FROM {image} is not pinned by digest")
    if base not in froms:
        problems.append(f"no FROM uses the pinned base {base} (docker/base-image.txt)")
    if uv_image not in froms:
        problems.append(f"no FROM uses the pinned uv image {uv_image} (docker/uv-image.txt)")
    copies_pins = any(kind == "COPY" and args.split()[-1] == PINS_FILE_IN_IMAGE and "docker/apt-pins.txt" in args
                      for kind, args in steps)
    runs = [args for kind, args in steps if kind == "RUN"]
    for command in runs:
        for packages in apt_install_packages(command):
            if packages == ["<pins-file>"]:
                if not copies_pins:
                    problems.append(f"apt-get installs {PINS_FILE_IN_IMAGE} but the Dockerfile never copies docker/apt-pins.txt there")
                continue
            for package in packages:
                if package not in pins:
                    problems.append(f"apt-get install {package}: not an exact version from docker/apt-pins.txt")
        for forbidden in FORBIDDEN_PYTHON:
            if forbidden in command:
                problems.append(f"RUN uses '{forbidden}'; Python packages must come from uv.lock")
    if not any("uv sync --frozen" in command for command in runs):
        problems.append("no RUN installs the Python packages with `uv sync --frozen` from uv.lock")
    if not (root / "uv.lock").exists():
        problems.append("uv.lock is missing")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the ath-sim image's pins.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(f"check_dockerfile_pins: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("check_dockerfile_pins: base and uv images pinned by digest; every apt package pinned; Python from uv.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
