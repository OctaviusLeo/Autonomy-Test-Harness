"""Feature: autonomy-test-harness, Property 17 (identical Scenarios across conditions) and Property 18 (a valid
95% Wilson interval), plus unit tests for known intervals, resumption, and the errored-run retry.
Validates: Requirements 10.1, 10.2, 10.3.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.experiment import paired
from harness.experiment.conditions import load_conditions
from harness.experiment.stats import Z95, wilson_interval
from harness.schema.validate import load_scenario

HASH = "9" * 40
STAMP = {"command": "bash scripts/run_experiment.sh", "seed": 303, "commit": HASH}
CONDITIONS = load_conditions("config/experiment.yaml")
BASE = sorted(Path("scenarios/experiment30").glob("*.yaml"))


class FakeRunner:
    """Stands in for suite.run_one: writes and returns a RunRecord; outcomes and failures are scripted."""

    def __init__(self, errored=(), crash_after=None, fail=()):
        self.calls: list[tuple[str, str, int]] = []
        self.errored = dict.fromkeys(errored, 0)
        self.crash_after = crash_after
        self.fail = set(fail)

    def __call__(self, path, out_dir, run_index, condition):
        if self.crash_after is not None and len(self.calls) >= self.crash_after:
            raise KeyboardInterrupt("job stopped")
        scenario = load_scenario(path)
        self.calls.append((condition, scenario.scenario_id, run_index))
        key = (condition, scenario.scenario_id)
        status = "ok"
        if key in self.errored and self.errored[key] < (2 if key[1].endswith("9") else 1):
            self.errored[key] += 1
            status = "errored"
        passed = key not in self.fail
        record = {"scenario_id": scenario.scenario_id, "seed": scenario.seed, "fault_condition": condition,
                  "status": status, "failing_step": "spawn" if status == "errored" else None, "effect": "x",
                  "generator_config": "config/generator.yaml", "bag_path": f"/h/{condition}/bags/{scenario.scenario_id}",
                  "faults": [f.type for f in scenario.faults],
                  "verdict": None if status == "errored" else {"passed": passed, "reason": "" if passed else "timeout",
                                                               "detail": "d"},
                  "stamp": STAMP}
        run_dir = Path(out_dir) / "runs" / scenario.scenario_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "bags" / scenario.scenario_id).mkdir(parents=True, exist_ok=True)
        (run_dir / "run_record.json").write_text(json.dumps(record))
        return record


def ticking(step=10.0):
    t = [0.0]

    def clock():
        t[0] += step / 2
        return t[0]
    return clock


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.lists(st.sampled_from(sorted(c for c in CONDITIONS if c != "none")), unique=True, min_size=1, max_size=6),
       st.lists(st.integers(0, 29), unique=True, min_size=1, max_size=4))
def test_property_17_same_scenarios_in_every_condition(tmp_path_factory, faults, indices):
    out = tmp_path_factory.mktemp("p17")
    conditions = {"none": CONDITIONS["none"], **{name: CONDITIONS[name] for name in faults}}
    base = [BASE[i] for i in sorted(indices)]
    result = paired.run_paired(base, conditions, out, FakeRunner(), ticking())
    baseline = [r["scenario_id"] for r in result["records"]["none"]]
    for name in faults:
        assert [r["scenario_id"] for r in result["records"][name]] == baseline
        for r in result["records"][name]:
            assert r["faults"] == [name]
            faulted = load_scenario(out / name / "scenarios" / f"{r['scenario_id']}.yaml")
            plain = load_scenario(out / "none" / "scenarios" / f"{r['scenario_id']}.yaml")
            assert faulted.model_copy(update={"faults": []}) == plain
    assert [row["scenario_ids"] for row in result["rows"]] == [baseline] * (len(faults) + 1)


@settings(max_examples=100, derandomize=True)
@given(st.integers(1, 500).flatmap(lambda n: st.tuples(st.integers(0, n), st.just(n))))
def test_property_18_wilson_interval_is_valid(case):
    passes, n = case
    low, high = wilson_interval(passes, n)
    p = passes / n
    assert 0.0 <= low <= p <= high <= 1.0
    z2 = Z95 ** 2
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    assert low == pytest.approx(max(0.0, center - half), abs=1e-12)
    assert high == pytest.approx(min(1.0, center + half), abs=1e-12)


def test_wilson_known_values_and_errors():
    assert wilson_interval(27, 30) == pytest.approx((0.744, 0.965), abs=1e-3)
    assert wilson_interval(15, 30) == pytest.approx((0.332, 0.668), abs=1e-3)
    assert wilson_interval(0, 30)[0] == 0.0 and wilson_interval(30, 30)[1] == 1.0
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_interval(31, 30)


def test_resuming_skips_completed_runs_and_sums_run_durations(tmp_path):
    conditions = {"none": CONDITIONS["none"], "latency": CONDITIONS["latency"]}
    base = BASE[:3]
    first = FakeRunner(crash_after=4)
    with pytest.raises(KeyboardInterrupt):
        paired.run_paired(base, conditions, tmp_path, first, ticking())
    assert len(first.calls) == 4
    (tmp_path / "latency" / "bags" / "exp30-001").mkdir(parents=True)  # partial bag from the stopped run
    second = FakeRunner()
    result = paired.run_paired(base, conditions, tmp_path, second, ticking())
    assert [c[:2] for c in second.calls] == [("latency", "exp30-001"), ("latency", "exp30-002")]
    assert (tmp_path / "latency" / "bags" / "exp30-001.interrupted1").exists()
    assert result["segments"] == 2
    durations = [r["run_duration_s"] for rs in result["records"].values() for r in rs]
    assert len(durations) == 6 and paired.total_run_time(result["records"]) == pytest.approx(sum(durations))


def test_errored_runs_are_retried_once_and_both_attempts_kept(tmp_path):
    conditions = {"none": CONDITIONS["none"]}
    base = [BASE[0], BASE[9]]  # exp30-009 errors on both attempts
    runner = FakeRunner(errored=[("none", "exp30-000"), ("none", "exp30-009")])
    result = paired.run_paired(base, conditions, tmp_path, runner, ticking())
    ok, still = result["records"]["none"]
    assert ok["status"] == "ok" and ok["attempt"] == 2 and ok["first_attempt"]["status"] == "errored"
    assert still["status"] == "errored" and still["attempt"] == 2
    assert [c[2] for c in runner.calls] == [0, 500, 1, 501]
    first = json.loads((tmp_path / "none" / "runs" / "exp30-000" / "attempt_1" / "run_record.json").read_text())
    assert first["status"] == "errored" and first["bag_path"].endswith("exp30-000.attempt1")
    assert result["rows"][0]["errored_after_retry"] == 1 and result["rows"][0]["passes"] == 1
    total = paired.total_run_time(result["records"])
    assert total == pytest.approx(sum(r["run_duration_s"] + r["first_attempt"]["run_duration_s"] for r in (ok, still)))
    again = FakeRunner()
    paired.run_paired(base, conditions, tmp_path, again, ticking())
    assert again.calls == []  # an errored second attempt counts as done


def test_reports_and_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATH_COMMIT", HASH)
    monkeypatch.setenv("ATH_COMMAND", "bash scripts/run_experiment.sh")
    runner = FakeRunner(fail=[("ray_dropout", "exp30-004"), ("scan_dropout", "exp30-004")])
    assert paired.main(["--out", str(tmp_path)], runner=runner) == 0
    report = json.loads((tmp_path / "experiment.json").read_text())
    assert [row["condition"] for row in report["conditions"]] == list(CONDITIONS)
    assert all(row["n"] == 30 for row in report["conditions"]) and report["base_scenarios"] == 30
    dropout = next(row for row in report["conditions"] if row["condition"] == "ray_dropout")
    assert dropout["passes"] == 29 and dropout["ci95"]["low"] < 29 / 30 < dropout["ci95"]["high"]
    assert report["stamp"] == {"command": "bash scripts/run_experiment.sh", "seed": 303, "commit": HASH}
    assert report["settings"]["faults"]["latency"] == {"window_s": [5.0, 65.0], "params": {"latency_ms": 300.0}}
    assert report["settings"]["faults"]["none"] is None and report["settings"]["thresholds"]["footprint_radius_m"] == 0.18
    durations = [json.loads(p.read_text())["run_duration_s"] for p in tmp_path.glob("*/runs/*/run_record.json")]
    assert len(durations) == 210 and report["segments"] == 1
    assert sum(durations) <= report["total_run_time_s"] <= sum(durations) + 60  # plus report generation
    assert sorted(p.name for p in (tmp_path / "junit").iterdir()) == sorted(f"{c}.xml" for c in CONDITIONS)
    summary = (tmp_path / "summary.md").read_text()
    assert "| ray_dropout | 30 | 29 | 0.9667 |" in summary and "Total run time:" in summary
    assert "--seed" in summary and "--condition scan_dropout" in summary and f"`{HASH}`" in summary
    assert "none: 30/30" in capsys.readouterr().out
    assert paired.regenerate_summary(tmp_path) == summary
