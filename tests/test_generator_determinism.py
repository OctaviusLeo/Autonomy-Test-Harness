"""Feature: autonomy-test-harness, Property 1 (generator determinism under a fixed seed) and Property 19
(a Scenario re-run from its seed reproduces it). Validates: Requirements 3.2, 3.5, 5.6, 0.3.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from harness.generator import generate as gen
from harness.schema.validate import dump_scenario, load_scenario

CONFIGS = {name: gen.load_config(f"config/{name}.yaml") for name in ("generator", "generator_smoke")}


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.integers(0, 2**31 - 1), st.integers(1, 3), st.sampled_from(sorted(CONFIGS)))
def test_property_1_same_seed_same_bytes(seed, n, name):
    cfg = CONFIGS[name]
    first = gen.generate(seed, n, cfg, prefix="det")
    second = gen.generate(seed, n, cfg, prefix="det")
    assert [dump_scenario(s) for s in first.scenarios] == [dump_scenario(s) for s in second.scenarios]
    assert first.rejections == second.rejections


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.integers(0, 2**31 - 1), st.integers(1, 3), st.sampled_from(sorted(CONFIGS)))
def test_property_19_regenerating_from_the_stored_seed(seed, n, name):
    cfg = CONFIGS[name]
    for scenario in gen.generate(seed, n, cfg, prefix="re").scenarios:
        again, _ = gen.generate_one(scenario.seed, cfg, scenario.scenario_id)
        assert again == scenario
        assert dump_scenario(again) == dump_scenario(scenario)


def test_written_file_reloads_equal(tmp_path):
    cfg = CONFIGS["generator_smoke"]
    scenario = gen.generate(cfg.seed, 1, cfg, prefix="w").scenarios[0]
    path = tmp_path / "w.yaml"
    path.write_text(dump_scenario(scenario))
    assert load_scenario(path) == scenario


def test_scenario_seeds_follow_the_set_seed():
    assert gen.scenario_seeds(303, 5) == gen.scenario_seeds(303, 5)
    assert gen.scenario_seeds(303, 3) == gen.scenario_seeds(303, 5)[:3]
    assert gen.scenario_seeds(303, 3) != gen.scenario_seeds(304, 3)
