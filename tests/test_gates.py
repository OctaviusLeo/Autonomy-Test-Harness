"""Tests for the milestone gate checks (harness/gates.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness import gates

HASH = "b" * 40


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def m0_repo(tmp_path, repo_root) -> Path:
    repo = tmp_path / "repo"
    for rel in (".gitignore", ".gitattributes", ".dockerignore"):
        _write(repo, rel, (repo_root / rel).read_text())
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo_root / rel, repo / rel)
    _write(repo, "results/m0_baseline.json", json.dumps({
        "nav2_result": "SUCCEEDED", "true_pose_to_goal_m": 0.12, "render": {"method": "egl"}, "failed_step": None,
        "stamp": {"command": "bash scripts/run_m0.sh", "seed": 0, "commit": HASH}}))
    _write(repo, "docs/evidence/a.txt", "x")
    _write(repo, "docs/ENVIRONMENT.md",
           "# Env\n## Versions\n| a | 1 | `docs/evidence/a.txt` |\n## M0 outcome\nok `results/m0_baseline.json`, "
           "image `ath-sim:<commit>`\n## Headless rendering\nEGL\n## Jenkins\nTBD later\n")
    _write(repo, ".kiro/specs/autonomy-test-harness/design.md",
           "text\n> **M0 outcome (filled):**\n> - done\n\nafter TBD\n")
    return repo


def _copy_regen(repo: Path, out: Path) -> None:
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo / rel, out / rel)


def test_m0_gate_passes_on_a_complete_repo(m0_repo):
    assert gates.check_m0(m0_repo, regenerate=_copy_regen) == []


def test_m0_gate_reports_each_problem(m0_repo):
    _write(m0_repo, "results/m0_baseline.json", json.dumps({
        "nav2_result": "ABORTED", "true_pose_to_goal_m": 0.5, "render": {}, "failed_step": "goal",
        "stamp": {"command": "c", "seed": 0, "commit": "abc"}}))
    env = (m0_repo / "docs/ENVIRONMENT.md").read_text().replace("EGL", "TBD").replace("a.txt", "missing.txt")
    _write(m0_repo, "docs/ENVIRONMENT.md", env)
    _write(m0_repo, ".kiro/specs/autonomy-test-harness/design.md", "> **M0 outcome:**\n> - TBD\n")
    _write(m0_repo, ".gitattributes", "* text=auto eol=lf\n")

    def bad_regen(repo, out):
        _copy_regen(repo, out)
        (out / "maps/empty_10x10.yaml").write_text("changed")

    problems = "\n".join(gates.check_m0(m0_repo, regenerate=bad_regen))
    for fragment in ("not SUCCEEDED", "not at most 0.30", "no render method", "failed_step 'goal'",
                     "40-character", "'Headless rendering' still has TBD", "missing.txt does not exist",
                     "'M0 outcome' block still has TBD", "maps/empty_10x10.yaml differs", "*.png binary"):
        assert fragment in problems


def test_m0_gate_missing_files(tmp_path):
    problems = gates.check_m0(tmp_path, regenerate=lambda repo, out: None)
    text = "\n".join(problems)
    assert "cannot read JSON" in text and "ENVIRONMENT.md" in text and "no 'M0 outcome' block" in text
    assert ".gitignore: missing" in text


def test_stamp_check_and_helpers():
    problems: list[str] = []
    gates.check_stamp({"stamp": {"seed": 1}}, "x", problems)
    gates.check_stamp([], "y", problems)
    assert len(problems) == 2
    assert gates.markdown_section("## A\none\n## B\ntwo\n", "B").strip() == "two"
    assert gates.markdown_section("## A\n", "C") == ""
    assert gates.quoted_block("no block", "M0") == ""


def test_verify_gate_script(m0_repo, load_script, monkeypatch, capsys):
    script = load_script("verify_gate")
    monkeypatch.setitem(gates.CHECKS, "m0", lambda repo: gates.check_m0(repo, regenerate=_copy_regen))
    assert script.main(["m0", "--repo", str(m0_repo)]) == 0
    (m0_repo / "results/m0_baseline.json").unlink()
    assert script.main(["m0", "--repo", str(m0_repo)]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_real_regeneration_matches_committed_files(repo_root, tmp_path):
    gates.regenerate_m0_files(repo_root, tmp_path)
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "config/nav2_params_ath.yaml"):
        assert gates.same_bytes(repo_root / rel, tmp_path / rel)
