"""Milestone gate checks. Each ``check_mN(repo)`` returns a list of problems; an empty list passes.

``scripts/verify_mN.sh`` runs the unit tests and then ``python scripts/verify_gate.py mN`` inside the
image, which prints every problem and exits non-zero if there is one. The checks read only
committed or generated files, so a gate is one repository command whose exit status decides it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

FULL_HASH = re.compile(r"^[0-9a-f]{40}$")

GITIGNORE_ENTRIES = (".env", "*.env", "*.pem", "*.key", "*.token", "secrets.*", "runs/", "__pycache__/",
                     ".pytest_cache/", ".hypothesis/", ".coverage", "htmlcov/", ".venv/", "*.mcap", "*.db3")
GITATTRIBUTES_ENTRIES = ("* text=auto eol=lf", "*.png binary", "*.pgm binary")
DOCKERIGNORE_ENTRIES = (".git", "runs/", ".kiro/", "results/", "__pycache__/", ".pytest_cache/", ".hypothesis/")
EVIDENCE_PATH = re.compile(r"`((?:docs|results|docker|config|ci)/[^`\s]+|uv\.lock)`")


def load_json(path: Path, problems: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{path}: cannot read JSON ({exc})")
        return None


def check_stamp(data: Any, where: str, problems: list[str]) -> None:
    stamp = data.get("stamp") if isinstance(data, dict) else None
    if not isinstance(stamp, dict) or not stamp.get("command") or "seed" not in stamp:
        problems.append(f"{where}: missing stamp with command and seed")
    elif not FULL_HASH.match(str(stamp.get("commit", ""))):
        problems.append(f"{where}: stamp commit is not a full 40-character hash")


def markdown_section(text: str, heading: str) -> str:
    """The body of the ``## heading`` section (up to the next ``## ``)."""
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return match.group(1) if match else ""


def quoted_block(text: str, title_fragment: str) -> str:
    """The ``>`` block whose first line contains ``title_fragment``."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(">") and title_fragment in line:
            block = [line]
            for follow in lines[i + 1:]:
                if not follow.startswith(">"):
                    break
                block.append(follow)
            return "\n".join(block)
    return ""


def check_entries(path: Path, required: tuple[str, ...], problems: list[str]) -> None:
    try:
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    except OSError:
        problems.append(f"{path.name}: missing")
        return
    missing = [entry for entry in required if entry not in lines]
    if missing:
        problems.append(f"{path.name}: missing entries {missing}")


def check_ignore_files(repo: Path, problems: list[str]) -> None:
    check_entries(repo / ".gitignore", GITIGNORE_ENTRIES, problems)
    check_entries(repo / ".gitattributes", GITATTRIBUTES_ENTRIES, problems)
    check_entries(repo / ".dockerignore", DOCKERIGNORE_ENTRIES, problems)


def check_cited_paths(repo: Path, text: str, where: str, problems: list[str]) -> None:
    for cited in sorted(set(EVIDENCE_PATH.findall(text))):
        if "<" in cited or "*" in cited:
            continue  # a pattern such as ath-sim:<commit>, not a file
        if not (repo / cited.rstrip("/")).exists():
            problems.append(f"{where}: cited path {cited} does not exist")


def same_bytes(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


def regenerate_m0_files(repo: Path, out: Path) -> None:
    """Write the world, map, and Nav2 parameter file into ``out`` with the repository's own scripts."""
    from harness import nav2_params
    from harness.world.arena import arena, write_map, write_world_sdf

    a = arena("empty_10x10")
    write_world_sdf(a, out / "worlds" / "empty_10x10.sdf")
    write_map(a, out / "maps" / "empty_10x10.pgm", out / "maps" / "empty_10x10.yaml")
    nav2_params.make(nav2_params.stock_share_dir(), out / "config" / "nav2_params_ath.yaml",
                     out / "docs" / "evidence" / "nav2_params_stock.yaml")


def check_m0(repo: Path, regenerate: Callable[[Path, Path], None] = regenerate_m0_files) -> list[str]:
    problems: list[str] = []
    m0 = load_json(repo / "results" / "m0_baseline.json", problems)
    if isinstance(m0, dict):
        if m0.get("nav2_result") != "SUCCEEDED":
            problems.append(f"m0_baseline.json: nav2_result is {m0.get('nav2_result')!r}, not SUCCEEDED")
        dist = m0.get("true_pose_to_goal_m")
        if not isinstance(dist, (int, float)) or dist > 0.30:
            problems.append(f"m0_baseline.json: true_pose_to_goal_m {dist!r} is not at most 0.30 m")
        if not (m0.get("render") or {}).get("method"):
            problems.append("m0_baseline.json: no render method")
        if m0.get("failed_step") is not None:
            problems.append(f"m0_baseline.json: failed_step {m0.get('failed_step')!r}")
        check_stamp(m0, "m0_baseline.json", problems)

    env_text = _read(repo / "docs" / "ENVIRONMENT.md", problems)
    for heading in ("Versions", "M0 outcome", "Headless rendering"):
        section = markdown_section(env_text, heading)
        if not section.strip():
            problems.append(f"ENVIRONMENT.md: section '{heading}' missing or empty")
        elif "TBD" in section:
            problems.append(f"ENVIRONMENT.md: section '{heading}' still has TBD")
    check_cited_paths(repo, env_text, "ENVIRONMENT.md", problems)

    design = _read(repo / ".kiro" / "specs" / "autonomy-test-harness" / "design.md", problems)
    block = quoted_block(design, "M0 outcome")
    if not block:
        problems.append("design.md: no 'M0 outcome' block")
    elif "TBD" in block:
        problems.append("design.md: 'M0 outcome' block still has TBD")

    out = repo / "runs" / "gate_m0"
    regenerate(repo, out)
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        if not same_bytes(repo / rel, out / rel):
            problems.append(f"regenerated {rel} differs from the committed file")

    check_ignore_files(repo, problems)
    return problems


def _read(path: Path, problems: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        problems.append(f"{path}: missing")
        return ""


CHECKS: dict[str, Callable[[Path], list[str]]] = {"m0": check_m0}
