"""Unit tests for harness/repro.py and scripts/require_clean.sh (Requirement 0.1)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import repro

HASH = "0123456789abcdef0123456789abcdef01234567"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def throwaway_repo(tmp_path, repo_root) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "harness").mkdir()
    (repo / "results").mkdir()
    shutil.copy(repo_root / "scripts" / "require_clean.sh", repo / "scripts" / "require_clean.sh")
    (repo / "harness" / "mod.py").write_text("x = 1\n")
    (repo / "results" / "r.json").write_text("{}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_commit_hash_from_git_is_40_hex(throwaway_repo, monkeypatch):
    monkeypatch.delenv("ATH_COMMIT", raising=False)
    value = repro.commit_hash(cwd=throwaway_repo)
    assert len(value) == 40 and all(c in "0123456789abcdef" for c in value)
    assert value == _git(throwaway_repo, "rev-parse", "HEAD")


def test_ath_commit_takes_precedence(throwaway_repo, monkeypatch):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    assert repro.commit_hash(cwd=throwaway_repo) == HASH


@pytest.mark.parametrize("bad", ["abc123", HASH.upper(), HASH + "0", "", "g" * 40])
def test_malformed_ath_commit_is_rejected(monkeypatch, bad):
    monkeypatch.setenv("ATH_COMMIT", bad)
    with pytest.raises(repro.CommitError):
        repro.commit_hash()


def test_no_repository_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ATH_COMMIT", raising=False)
    with pytest.raises(repro.CommitError):
        repro.commit_hash(cwd=tmp_path)


def test_stamp_round_trips_through_json(monkeypatch, tmp_path):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    monkeypatch.setenv("ATH_COMMAND", "bash scripts/run_m0.sh")
    stamp = repro.make_stamp(seed=7)
    text = repro.stamp_json({"value": 1.5}, stamp)
    data = json.loads(text)
    assert data["value"] == 1.5
    assert repro.Stamp.from_dict(data["stamp"]) == stamp
    assert stamp.command == "bash scripts/run_m0.sh" and stamp.seed == 7
    path = repro.write_stamped_json(tmp_path / "out" / "x.json", {"value": 2}, stamp)
    assert json.loads(path.read_text())["stamp"]["commit"] == HASH
    assert not (tmp_path / "out" / "x.json.tmp").exists()


def test_stamp_rejects_short_commit_and_duplicate_key():
    with pytest.raises(repro.CommitError):
        repro.Stamp(command="c", seed=0, commit="abc")
    with pytest.raises(ValueError):
        repro.stamp_json({"stamp": 1}, repro.Stamp(command="c", seed=0, commit=HASH))


def test_command_line_defaults_to_argv(monkeypatch):
    monkeypatch.delenv("ATH_COMMAND", raising=False)
    assert repro.command_line(["python", "x.py", "--seed", "3"]) == "python x.py --seed 3"


def _require_clean(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "scripts/require_clean.sh"], cwd=repo, capture_output=True, text=True)


def test_require_clean_allows_results_and_prints_head(throwaway_repo):
    (throwaway_repo / "results" / "r.json").write_text('{"changed": true}\n')
    (throwaway_repo / "results" / "new.txt").write_text("new\n")
    result = _require_clean(throwaway_repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == _git(throwaway_repo, "rev-parse", "HEAD")


def test_require_clean_refuses_harness_change(throwaway_repo):
    (throwaway_repo / "harness" / "mod.py").write_text("x = 2\n")
    result = _require_clean(throwaway_repo)
    assert result.returncode != 0
    assert "harness/mod.py" in result.stderr
