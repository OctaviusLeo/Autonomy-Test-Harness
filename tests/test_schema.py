"""Unit tests for the Scenario schema and loader (Requirements 2.3, 2.4)."""

from __future__ import annotations

import pytest

from harness.schema.validate import ScenarioValidationError, load_scenario


def test_committed_example_loads(repo_root):
    scenario = load_scenario(repo_root / "scenarios" / "example_valid.yaml")
    assert scenario.schema_version == 1
    assert scenario.world == "empty_10x10"


def test_out_of_bound_field_is_named(repo_root):
    with pytest.raises(ScenarioValidationError, match="time_limit_s"):
        load_scenario(repo_root / "tests" / "fixtures" / "invalid_bad_field.yaml")


def test_unsupported_version_is_named(repo_root):
    with pytest.raises(ScenarioValidationError, match="999"):
        load_scenario(repo_root / "tests" / "fixtures" / "invalid_unsupported_version.yaml")


def test_unreadable_and_non_mapping_files(tmp_path):
    with pytest.raises(ScenarioValidationError, match="cannot read"):
        load_scenario(tmp_path / "missing.yaml")
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("a: [1, 2\n")
    with pytest.raises(ScenarioValidationError, match="cannot parse"):
        load_scenario(bad_yaml)
    listing = tmp_path / "list.yaml"
    listing.write_text("- 1\n- 2\n")
    with pytest.raises(ScenarioValidationError, match="mapping"):
        load_scenario(listing)
