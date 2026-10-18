"""Unit tests for the scenario-set CLI (Requirements 3.2, 3.4, 3.5, 5.6)."""

from __future__ import annotations

import json

import pytest
import yaml

from harness.generator import cli
from harness.schema.validate import load_scenario

HASH = "c" * 40


@pytest.fixture
def small_config(tmp_path, repo_root):
    data = yaml.safe_load((repo_root / "config" / "generator_smoke.yaml").read_text())
    data["n"] = 3
    path = tmp_path / "gen.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_generate_writes_scenarios_and_stamped_record(small_config, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    assert cli.main(["generate", "--config", small_config, "--out", str(tmp_path / "set"), "--prefix", "t"]) == 0
    files = sorted(p.name for p in (tmp_path / "set").glob("*.yaml"))
    assert files == ["t-000.yaml", "t-001.yaml", "t-002.yaml"]
    record = json.loads((tmp_path / "set" / "generation.json").read_text())
    assert record["set_seed"] == 101 and record["n"] == 3 and record["prefix"] == "t"
    assert set(record["rejections"]) == {"start_inside_obstacle", "off_map", "unreachable"}
    assert record["stamp"]["commit"] == HASH and record["stamp"]["seed"] == 101
    assert record["scenarios"][1]["scenario_id"] == "t-001"
    assert load_scenario(tmp_path / "set" / "t-001.yaml").seed == record["scenarios"][1]["seed"]
    assert "3 Scenarios" in capsys.readouterr().out


def test_regenerate_and_locate(small_config, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    root = tmp_path / "scenarios"
    cli.write_set(small_config, root / "smoke", "t")
    record = json.loads((root / "smoke" / "generation.json").read_text())
    seed = record["scenarios"][2]["seed"]
    assert cli.main(["regenerate", "--config", small_config, "--seed", str(seed), "--id", "t-002"]) == 0
    assert capsys.readouterr().out == (root / "smoke" / "t-002.yaml").read_text()
    out = tmp_path / "one" / "x.yaml"
    assert cli.main(["regenerate", "--config", small_config, "--seed", str(seed), "--id", "t-002", "--out", str(out)]) == 0
    assert out.read_text() == (root / "smoke" / "t-002.yaml").read_text()
    assert cli.main(["locate", "--config", small_config, "--seed", str(seed), "--root", str(root)]) == 0
    assert capsys.readouterr().out.strip() == str(root / "smoke" / "t-002.yaml")
    assert cli.main(["locate", "--config", small_config, "--seed", "1", "--root", str(root)]) == 1
    assert cli.main(["locate", "--config", "config/other.yaml", "--seed", str(seed), "--root", str(root)]) == 1
