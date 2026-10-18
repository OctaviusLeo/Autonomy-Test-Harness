"""Feature: autonomy-test-harness, Property 4: Schema validation enforces bounds and version.

Validates: Requirements 2.3, 2.4. Plus unit tests for the design.md example, dump/load round trips,
and the rejected ``odom_drift`` type.
"""

from __future__ import annotations

import copy
import re

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.schema.scenario import FAULT_TYPES
from harness.schema.validate import ScenarioValidationError, dump_scenario, load_scenario, parse_scenario

coord = st.floats(-4.5, 4.5, allow_nan=False)
yaw = st.floats(-3.14, 3.14, allow_nan=False)
pose = st.fixed_dictionaries({"x": coord, "y": coord, "yaw": yaw})
size = st.floats(0.1, 1.0, allow_nan=False)
box = st.fixed_dictionaries({"shape": st.just("box"), "size": st.fixed_dictionaries({"x": size, "y": size, "z": size}),
                             "pose": pose})
cylinder = st.fixed_dictionaries({"shape": st.just("cylinder"),
                                  "size": st.fixed_dictionaries({"radius": size, "height": size}), "pose": pose})


@st.composite
def window(draw):
    start = draw(st.floats(0, 50, allow_nan=False))
    return {"start_s": start, "end_s": start + draw(st.floats(0.5, 50, allow_nan=False))}


PARAMS = {
    "range_noise": st.fixed_dictionaries({"sigma_m": st.floats(0, 1, allow_nan=False)}),
    "ray_dropout": st.fixed_dictionaries({"prob": st.floats(0, 1, allow_nan=False)}),
    "scan_dropout": st.just({}),
    "latency": st.fixed_dictionaries({"latency_ms": st.floats(0, 1000, allow_nan=False)}),
    "freeze": st.just({}),
    "sector_blackout": st.fixed_dictionaries({"center_deg": st.floats(0, 359.9, allow_nan=False),
                                              "width_deg": st.floats(1, 360, allow_nan=False)}),
}
fault = st.sampled_from(FAULT_TYPES).flatmap(
    lambda t: st.fixed_dictionaries({"type": st.just(t), "window": window(), "params": PARAMS[t]}))
scenario = st.fixed_dictionaries({
    "schema_version": st.just(1),
    "scenario_id": st.from_regex(r"[a-z0-9]{1,8}-[0-9]{3}", fullmatch=True),
    "seed": st.integers(0, 2**31 - 1),
    "world": st.just("empty_10x10"),
    "time_limit_s": st.floats(1, 300, allow_nan=False),
    "start": pose,
    "goal": pose,
    "obstacles": st.lists(st.one_of(box, cylinder), min_size=1, max_size=4),
    "faults": st.lists(fault, min_size=1, max_size=3),
})

negative = st.floats(-1e6, -1e-6, allow_nan=False)
not_positive = st.one_of(st.just(0.0), negative)
wrong_types = st.sampled_from(["abc", [1.0], {"v": 1}, True, None])

# Bounded leaf fields: (path suffix after the list element, strategy of out-of-bound values).
FAULT_BOUNDS = {
    "range_noise": [(("params", "sigma_m"), negative)],
    "ray_dropout": [(("params", "prob"), st.one_of(negative, st.floats(1.0001, 1e6, allow_nan=False)))],
    "latency": [(("params", "latency_ms"), st.one_of(negative, st.floats(1000.001, 1e6, allow_nan=False)))],
    "sector_blackout": [(("params", "width_deg"), st.one_of(not_positive, st.floats(360.001, 1e6, allow_nan=False))),
                        (("params", "center_deg"), st.one_of(negative, st.floats(360, 1e6, allow_nan=False)))],
}


def bound_targets(data: dict) -> list[tuple[tuple, st.SearchStrategy]]:
    targets: list[tuple[tuple, st.SearchStrategy]] = [
        (("seed",), st.integers(-(2**31), -1)),
        (("time_limit_s",), not_positive),
    ]
    for i, obstacle in enumerate(data["obstacles"]):
        for key in obstacle["size"]:
            targets.append((("obstacles", i, "size", key), not_positive))
    for i, f in enumerate(data["faults"]):
        targets.append((("faults", i, "window", "start_s"), negative))
        for suffix, values in FAULT_BOUNDS.get(f["type"], []):
            targets.append((("faults", i, *suffix), values))
    return targets


def leaf_paths(value, prefix=()) -> list[tuple]:
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in leaf_paths(v, prefix + (k,))]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in leaf_paths(v, prefix + (i,))]
    return [prefix]


def set_in(data, path, value):
    for part in path[:-1]:
        data = data[part]
    data[path[-1]] = value


def del_in(data, path):
    for part in path[:-1]:
        data = data[part]
    del data[path[-1]]


def names_path(message: str, path: tuple) -> bool:
    """True if the error names ``path`` (a union tag may sit after a list index, e.g. obstacles.0.box.size.x)."""
    parts = [re.escape(str(p)) for p in path]
    pattern = r"\.".join(parts)
    for i, p in enumerate(path):
        if isinstance(p, int):
            pattern = r"\.".join(parts[:i + 1]) + r"(\.\w+)?" + (r"\." + r"\.".join(parts[i + 1:]) if parts[i + 1:] else "")
            break
    return re.search(rf"field '{pattern}", message) is not None


def rejected(data) -> str:
    with pytest.raises(ScenarioValidationError) as info:
        parse_scenario(data)
    return str(info.value)


@settings(max_examples=100, derandomize=True)
@given(scenario)
def test_generated_valid_scenarios_load(data):
    assert parse_scenario(data).scenario_id == data["scenario_id"]


@settings(max_examples=100, derandomize=True)
@given(scenario, st.data())
def test_out_of_bound_value_is_rejected_naming_the_field(data, draw):
    path, values = draw.draw(st.sampled_from(bound_targets(data)))
    bad = copy.deepcopy(data)
    set_in(bad, path, draw.draw(values))
    assert names_path(rejected(bad), path)


@settings(max_examples=100, derandomize=True)
@given(scenario, st.data())
def test_wrong_type_is_rejected_naming_the_field(data, draw):
    path = draw.draw(st.sampled_from([p for p in leaf_paths(data) if p[-1] not in ("shape", "type")]))
    bad = copy.deepcopy(data)
    set_in(bad, path, draw.draw(wrong_types.filter(lambda v: not (isinstance(v, str) and path[-1] in ("scenario_id", "world")))))
    assert names_path(rejected(bad), path)


@settings(max_examples=100, derandomize=True)
@given(scenario, st.data())
def test_missing_field_is_rejected_naming_the_field(data, draw):
    path = draw.draw(st.sampled_from(leaf_paths(data)))
    bad = copy.deepcopy(data)
    del_in(bad, path)
    message = rejected(bad)
    if path[-1] in ("shape", "type"):
        assert f"field '{path[0]}.{path[1]}.{path[-1]}'" in message
    else:
        assert names_path(message, path)


@settings(max_examples=100, derandomize=True)
@given(scenario, st.integers(-1000, 1000).filter(lambda v: v != 1))
def test_unsupported_version_is_rejected_naming_the_version(data, version):
    bad = dict(data, schema_version=version)
    message = rejected(bad)
    assert f"unsupported schema_version {version}" in message


@settings(max_examples=100, derandomize=True)
@given(scenario, st.text(min_size=1, max_size=12).filter(lambda w: w != "empty_10x10"))
def test_unsupported_world_is_rejected_naming_the_field(data, world):
    assert "field 'world'" in rejected(dict(data, world=world))


@settings(max_examples=100, derandomize=True)
@given(scenario)
def test_window_order_and_unknown_fields(data):
    bad = copy.deepcopy(data)
    w = bad["faults"][0]["window"]
    w["end_s"] = w["start_s"]
    assert "end_s" in rejected(bad) and names_path(rejected(bad), ("faults", 0, "window"))
    extra = copy.deepcopy(data)
    extra["start"]["z"] = 1.0
    assert "field 'start.z'" in rejected(extra)


@settings(max_examples=100, derandomize=True)
@given(scenario)
def test_dump_then_load_round_trips(data):
    s = parse_scenario(data)
    text = dump_scenario(s)
    again = parse_scenario(yaml.safe_load(text))
    assert dump_scenario(again) == text


def design_example(repo_root) -> str:
    path = repo_root / ".kiro" / "specs" / "autonomy-test-harness" / "design.md"
    if not path.exists():
        pytest.skip("design.md is not in the image (.dockerignore excludes .kiro/); checked in the mounted run")
    section = path.read_text().split("## Scenario schema and example", 1)[1]
    return section.split("```yaml", 1)[1].split("```", 1)[0]


def test_design_example_loads(repo_root, tmp_path):
    path = tmp_path / "example.yaml"
    path.write_text(design_example(repo_root))
    s = load_scenario(path)
    assert (s.scenario_id, s.seed, s.faults[0].type) == ("exp30-007", 1733220917, "sector_blackout")
    assert load_scenario(repo_root / "scenarios" / "example_valid.yaml") == s


def test_dump_is_deterministic_and_rounds(repo_root):
    s = load_scenario(repo_root / "scenarios" / "example_valid.yaml")
    s2 = s.model_copy(update={"start": s.start.model_copy(update={"x": -3.123456789, "y": -0.00001})})
    text = dump_scenario(s2)
    assert "start: {x: -3.1235, y: 0.0, yaw: 0.4}" in text
    assert text.splitlines()[0] == "schema_version: 1"
    assert dump_scenario(s2) == text


def test_odom_drift_is_rejected_naming_type(repo_root):
    data = yaml.safe_load((repo_root / "scenarios" / "example_valid.yaml").read_text())
    data["faults"].append({"type": "odom_drift", "window": {"start_s": 1.0, "end_s": 2.0}, "params": {"drift_m_per_s": 0.1}})
    message = rejected(data)
    assert "field 'faults.1.type'" in message and "odom_drift" in message


def test_dump_refuses_a_value_that_rounds_out_of_bounds(repo_root):
    s = load_scenario(repo_root / "scenarios" / "example_valid.yaml")
    fault = s.faults[0].model_copy(update={"params": s.faults[0].params.model_copy(update={"center_deg": 359.99999})})
    with pytest.raises(ValueError, match="center_deg"):
        dump_scenario(s.model_copy(update={"faults": [fault]}))
