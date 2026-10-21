"""Feature: autonomy-test-harness, Property 14 (one JUnit case per Scenario), Property 15 (the summary links a
bag and a re-run command for every failure), Property 16 (missing or unparsable report input is rejected).
Validates: Requirements 7.1, 7.2, 7.3, 7.5.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.reporting import junit, summary
from harness.reporting.records import ReportInputError, load_records, validate_record

HASH = "1" * 40
STAMP = {"command": "bash scripts/run_suite.sh smoke", "seed": 0, "commit": HASH}
CONDITIONS = ["none", "range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout"]


@st.composite
def record(draw, index: int):
    status = draw(st.sampled_from(["ok", "ok", "ok", "errored", "timed_out"]))
    passed = status == "ok" and draw(st.booleans())
    reason = "" if passed else draw(st.sampled_from(["collision", "timeout"]))
    if status == "timed_out":
        reason = "timeout"
    verdict = None if status == "errored" else {"passed": passed, "reason": reason,
                                                 "detail": draw(st.text(max_size=30)), "time_to_goal_s": None,
                                                 "min_clearance_m": 0.3}
    return {"scenario_id": f"s-{index:03d}", "seed": draw(st.integers(0, 2**31 - 1)),
            "fault_condition": draw(st.sampled_from(CONDITIONS)), "status": status,
            "failing_step": "spawn" if status == "errored" else None, "effect": "create exited 1",
            "generator_config": draw(st.sampled_from(["config/generator.yaml", "config/generator_smoke.yaml", None])),
            "bag_path": f"/home/u/ath-shared/runs/r/bags/s-{index:03d}", "wall_time_s": 30.0, "nav2_result": "SUCCEEDED",
            "verdict": verdict, "stamp": STAMP}


records_strategy = st.integers(1, 15).flatmap(lambda n: st.tuples(*[record(i) for i in range(n)]).map(list))


@settings(max_examples=100, derandomize=True)
@given(records_strategy)
def test_property_14_one_junit_case_per_scenario(records):
    root = ET.fromstring(junit.junit_xml(records, "smoke"))
    cases = root.findall("testcase")
    assert len(cases) == len(records) == int(root.get("tests"))
    failures = errors = 0
    for case, r in zip(cases, records):
        assert case.get("name").startswith(r["scenario_id"])
        if r["fault_condition"] != "none":
            assert case.get("name") == f"{r['scenario_id']}[{r['fault_condition']}]"
        if r["status"] == "errored":
            errors += 1
            assert case.find("error").get("message") == "errored: spawn" and case.find("failure") is None
        elif not r["verdict"]["passed"]:
            failures += 1
            assert case.find("failure").get("message") == r["verdict"]["reason"] and case.find("error") is None
        else:
            assert case.find("failure") is None and case.find("error") is None
    assert (int(root.get("failures")), int(root.get("errors"))) == (failures, errors)


@settings(max_examples=100, derandomize=True)
@given(records_strategy)
def test_property_15_summary_links_bag_and_rerun_for_every_failure(records):
    text = summary.summary_markdown(records, "smoke summary", STAMP)
    for r in records:
        failed = r["status"] != "ok" or not r["verdict"]["passed"]
        if not failed:
            continue
        row = next(line for line in text.splitlines() if line.startswith(f"| {r['scenario_id']} |"))
        reason = f"errored: {r['failing_step']}" if r["status"] == "errored" else r["verdict"]["reason"]
        assert f"| {reason} |" in row
        assert f"`{r['bag_path']}` (bags not committed)" in row
        assert f"--seed {r['seed']}" in row and "bash scripts/rerun_one.sh --config" in row
        if r["fault_condition"] != "none":
            assert f"--condition {r['fault_condition']}" in row
    assert f"Commit: `{HASH}`" in text


corruptions = st.sampled_from(["missing", "garbage", "not_object", "no_status", "bad_status", "no_verdict",
                               "bad_reason", "no_stamp", "bool_seed"])


@settings(max_examples=100, derandomize=True)
@given(records_strategy, st.data(), corruptions)
def test_property_16_bad_input_is_rejected_without_a_partial_report(tmp_path_factory, records, data, corruption):
    tmp = tmp_path_factory.mktemp("p16")
    paths = []
    for r in records:
        path = tmp / f"{r['scenario_id']}.json"
        path.write_text(json.dumps(r))
        paths.append(path)
    bad = data.draw(st.sampled_from(paths))
    r = json.loads(bad.read_text())
    if corruption == "missing":
        bad.unlink()
    elif corruption == "garbage":
        bad.write_text("{not json")
    elif corruption == "not_object":
        bad.write_text("[1, 2]")
    else:
        if corruption == "no_status":
            del r["status"]
        elif corruption == "bad_status":
            r["status"] = "crashed"
        elif corruption == "no_verdict":
            r["status"], r["verdict"] = "ok", None
        elif corruption == "bad_reason":
            r["status"], r["verdict"] = "ok", {"passed": False, "reason": "lost"}
        elif corruption == "no_stamp":
            del r["stamp"]
        else:
            r["seed"] = True
        bad.write_text(json.dumps(r))
    out = tmp / "report"
    out.mkdir()
    (out / "summary.md").write_text("previous report\n")
    with pytest.raises(ReportInputError) as info:
        junit.write_junit(load_records(paths), out / "junit.xml", "smoke")
    assert str(bad) in str(info.value)
    assert not (out / "junit.xml").exists()
    assert (out / "summary.md").read_text() == "previous report\n"  # untouched


def test_reports_written_atomically_and_bag_links(tmp_path):
    good = {"scenario_id": "a", "seed": 5, "fault_condition": "latency", "status": "ok", "generator_config": None,
            "bag_path": "/host/run/repeat_1/bags/a", "verdict": {"passed": False, "reason": "timeout", "detail": "x|y"},
            "stamp": STAMP}
    path = summary.write_summary([good], tmp_path / "s.md", "t", STAMP, bag_link_base="https://ci/job/1/artifact/bags/",
                                 run_root="/host/run")
    text = path.read_text()
    assert "[bag](https://ci/job/1/artifact/bags/repeat_1/bags/a)" in text and "x\\|y" in text
    assert "--config <generator config of the set> --seed 5 --condition latency" in text
    assert not list(tmp_path.glob(".*.tmp"))
    assert junit.write_junit([good], tmp_path / "j.xml", "t").read_text().startswith('<?xml version="1.0"')
    passing = dict(good, verdict={"passed": True, "reason": ""})
    assert "None." in summary.summary_markdown([passing], "t", STAMP)
    assert summary.pass_rates([good, passing]) == [("latency", 2, 1, 0.5)]
    with pytest.raises(ReportInputError, match="no RunRecords"):
        junit.junit_xml([], "t")
    with pytest.raises(ReportInputError, match="no RunRecords"):
        load_records([])
    with pytest.raises(ReportInputError, match="not a JSON object"):
        validate_record([], "x")


def test_text_sanitizers():
    from harness.reporting.records import one_line, xml_text

    assert xml_text("a\x1fb\x00c￾\td\n") == "a?b?c?\td\n"
    assert one_line("a\nb\x1ec d\te") == "a b c d e"
    row = summary.summary_markdown([{
        "scenario_id": "z", "seed": 1, "fault_condition": "none", "status": "ok", "bag_path": "/b",
        "verdict": {"passed": False, "reason": "timeout", "detail": "line1\x1eline2"}, "stamp": STAMP}], "t", STAMP)
    assert "| line1 line2 |" in row
