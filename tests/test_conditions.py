"""Tests for the experiment conditions (Requirements 4.10, 10.1)."""

from __future__ import annotations

import json

import pytest
import yaml

from harness.experiment import conditions as c
from harness.schema.validate import ScenarioValidationError, load_scenario, parse_scenario


def test_seven_conditions_in_design_order_within_bounds():
    conds = c.load_conditions("config/experiment.yaml")
    assert list(conds) == ["none", "range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout"]
    assert conds["none"].fault is None
    assert conds["range_noise"].fault.params.sigma_m == 0.10
    assert conds["ray_dropout"].fault.params.prob == 0.5
    assert conds["latency"].fault.params.latency_ms == 300.0
    assert (conds["scan_dropout"].fault.window.start_s, conds["scan_dropout"].fault.window.end_s) == (5.0, 15.0)
    assert (conds["freeze"].fault.window.start_s, conds["freeze"].fault.window.end_s) == (5.0, 15.0)
    sector = conds["sector_blackout"].fault
    assert (sector.params.center_deg, sector.params.width_deg) == (270.0, 90.0)
    assert (sector.window.start_s, sector.window.end_s) == (5.0, 65.0)


def test_sector_center_matches_the_m0_lidar_yaw(repo_root):
    m0 = repo_root / "results" / "m0_baseline.json"
    if not m0.exists():
        pytest.skip("results/ is not in the image (.dockerignore); checked in the mounted run")
    yaw = json.loads(m0.read_text())["lidar_mount_yaw_deg"]
    data = yaml.safe_load(open("config/experiment.yaml"))
    assert data["lidar_mount_yaw_deg"] == yaw
    center = c.load_conditions("config/experiment.yaml")["sector_blackout"].fault.params.center_deg
    assert center == (360.0 - yaw) % 360.0


def test_apply_condition(repo_root):
    base = load_scenario(repo_root / "scenarios" / "experiment30" / "exp30-000.yaml")
    conds = c.load_conditions("config/experiment.yaml")
    assert c.apply_condition(base, conds["none"]) is base
    faulted = c.apply_condition(base, conds["latency"])
    assert [f.type for f in faulted.faults] == ["latency"] and faulted.scenario_id == base.scenario_id
    assert faulted.model_copy(update={"faults": []}) == base
    suffixed = c.apply_condition(base, conds["freeze"], suffix_id=True)
    assert suffixed.scenario_id == "exp30-000.freeze"


def test_cli_writes_variants(tmp_path, repo_root, capsys):
    base = repo_root / "scenarios" / "experiment30" / "exp30-000.yaml"
    assert c.main(["write", "--base", str(base), "--out", str(tmp_path / "a")]) == 0
    assert sorted(p.parent.name for p in (tmp_path / "a").rglob("*.yaml")) == sorted(c.load_conditions("config/experiment.yaml"))
    assert c.main(["write", "--base", str(base), "--out", str(tmp_path / "b"), "--suffix-ids", "--faults-only"]) == 0
    files = sorted(p.name for p in (tmp_path / "b").glob("*.yaml"))
    assert len(files) == 6 and "exp30-000.sector_blackout.yaml" in files
    assert load_scenario(tmp_path / "b" / "exp30-000.scan_dropout.yaml").faults[0].type == "scan_dropout"
    assert "exp30-000.latency.yaml" in capsys.readouterr().out


@pytest.mark.parametrize("text, fragment", [
    ("conditions:\n  - name: none\n  - name: none\n", "appears twice"),
    ("conditions:\n  - name: odom_drift\n    window: {start_s: 1.0, end_s: 2.0}\n", "not a Fault type"),
    ("conditions:\n  - name: latency\n    window: {start_s: 1.0, end_s: 2.0}\n    params: {latency_ms: 5000.0}\n", "latency_ms"),
    ("conditions:\n  - name: freeze\n    window: {start_s: 3.0, end_s: 2.0}\n", "window"),
])
def test_bad_conditions_are_rejected(tmp_path, text, fragment):
    (tmp_path / "faults.yaml").write_text((open("config/faults.yaml")).read())
    (tmp_path / "experiment.yaml").write_text(text)
    with pytest.raises(ValueError, match=fragment):
        c.load_conditions(tmp_path / "experiment.yaml")


def test_unknown_fault_type_in_defaults(tmp_path):
    (tmp_path / "faults.yaml").write_text("odom_drift:\n  params: {drift_m_per_s: 0.1}\n")
    with pytest.raises(ValueError, match="unknown Fault types"):
        c.load_fault_defaults(tmp_path / "faults.yaml")


def test_odom_drift_decision_is_recorded_and_enforced(repo_root):
    data = yaml.safe_load((repo_root / "scenarios" / "example_valid.yaml").read_text())
    data["faults"] = [{"type": "odom_drift", "window": {"start_s": 1.0, "end_s": 2.0}, "params": {}}]
    with pytest.raises(ScenarioValidationError, match="faults.0.type"):
        parse_scenario(data)
    design = repo_root / ".kiro" / "specs" / "autonomy-test-harness" / "design.md"
    if design.exists():
        assert "**Odometry drift (Requirement 4.10): not implemented.**" in design.read_text()
