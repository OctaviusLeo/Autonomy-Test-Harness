"""Tests for the M3 fault-window check (harness/bag_checks.fault_report, scripts/m3_fault_check.py)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from harness.bag_checks import ScanMsg, fault_report
from harness.faults.injector_node import FaultPipeline

INC = 6.28 / 359
PARAMS = {
    "range_noise": {"sigma_m": 0.1}, "ray_dropout": {"prob": 0.5}, "scan_dropout": {}, "latency": {"latency_ms": 300.0},
    "freeze": {}, "sector_blackout": {"center_deg": 270.0, "width_deg": 90.0},
}
WINDOW = (1.0, 2.5)
DISPATCH = 10.0


def make_fault(kind, window=WINDOW):
    return SimpleNamespace(type=kind, window=SimpleNamespace(start_s=window[0], end_s=window[1]),
                           params=SimpleNamespace(**PARAMS[kind]))


def simulate(kind, n=50, window=WINDOW):
    """Run the real pipeline over a 10 Hz scan stream and record what a bag would hold."""
    p = FaultPipeline([make_fault(kind, window)], seed=3)
    p.set_dispatch(DISPATCH)
    raw, out = [], []
    for k in range(n):
        t = DISPATCH + k * 0.1 + 0.0123
        scan = SimpleNamespace(ranges=[1.0 + 0.001 * ((k * 7 + i) % 400) for i in range(360)], angle_min=0.0,
                               angle_increment=INC, range_min=0.164, range_max=20.0, stamp=100.0 + k * 0.1)
        raw.append(ScanMsg(scan.stamp, t, tuple(scan.ranges)))
        out.extend(ScanMsg(o.stamp, t + 0.001, tuple(o.ranges)) for o in p.on_scan(scan, t))
        for j in range(1, 20):  # the node's 200 Hz tick between scans
            now = t + j * 0.005
            out.extend(ScanMsg(o.stamp, now + 0.001, tuple(o.ranges)) for o in p.on_tick(now))
    return raw, out


@pytest.mark.parametrize("kind", sorted(PARAMS))
def test_each_fault_is_confined_to_its_window(kind):
    raw, out = simulate(kind)
    report = fault_report(raw, out, kind, WINDOW, DISPATCH, PARAMS[kind])
    assert report["confined_to_window"], report
    assert report["outside_changed"] == 0 and report["inside_scans"] > 10
    if kind == "latency":
        # The synthetic ticks fall 5 ms after each 0.3 s mark, plus 1 ms of recording delay.
        assert report["measured_delay_s"] == pytest.approx(0.306, abs=0.002) and report["min_delay_s"] >= 0.3
    if kind == "freeze":
        assert report["frozen_repeats"] == report["inside_scans"] and report["other_outputs_inside"] == 0
    if kind == "scan_dropout":
        assert report["outputs_published_inside"] == 0


def test_changes_outside_the_window_are_caught():
    raw, out = simulate("range_noise")
    changed = list(out)
    changed[3] = ScanMsg(changed[3].stamp, changed[3].received, (5.0,) * 360)
    report = fault_report(raw, changed, "range_noise", WINDOW, DISPATCH, PARAMS["range_noise"])
    assert not report["confined_to_window"] and report["outside_changed"] == 1
    missing = fault_report(raw, out[:5] + out[6:], "range_noise", WINDOW, DISPATCH, PARAMS["range_noise"])
    assert not missing["confined_to_window"] and missing["outside_missing"] == 1


def test_wrong_latency_and_leaking_dropout_fail():
    raw, out = simulate("latency")
    assert not fault_report(raw, out, "latency", WINDOW, DISPATCH, {"latency_ms": 100.0})["within_20_percent"]
    raw, out = simulate("scan_dropout")
    leak = out + [ScanMsg(raw[20].stamp, raw[20].received + 0.001, raw[20].ranges)]
    assert not fault_report(raw, leak, "scan_dropout", WINDOW, DISPATCH)["confined_to_window"]
    passthrough_raw, passthrough_out = simulate("freeze", n=5)  # the run ended before the window
    assert not fault_report(passthrough_raw, passthrough_out, "freeze", WINDOW, DISPATCH)["confined_to_window"]


@pytest.mark.ros
def test_m3_fault_check_script(tmp_path, repo_root, load_script, monkeypatch):
    import rosbag2_py
    from builtin_interfaces.msg import Time as TimeMsg
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import LaserScan

    from harness.experiment import conditions

    run = tmp_path / "run"
    written = conditions.write_variants(repo_root / "scenarios" / "experiment30" / "exp30-000.yaml", run / "scenarios",
                                        conditions.load_conditions("config/experiment.yaml"), suffix_ids=True,
                                        include_none=False)
    stamp = {"command": "bash scripts/run_suite.sh runs/m3_conditions", "seed": 0, "commit": "a" * 40}
    records = []
    from harness.schema.validate import load_scenario

    for path in written:
        scenario_id = path.stem
        kind = scenario_id.split(".", 1)[1]
        w = load_scenario(path).faults[0].window
        raw, out = simulate(kind, n=200, window=(w.start_s, w.end_s))  # 20 s of run, as when a goal ends early
        bag = run / "bags" / scenario_id
        bag.parent.mkdir(parents=True, exist_ok=True)
        writer = rosbag2_py.SequentialWriter()
        writer.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
                    rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
        for i, (name, typ) in enumerate([("/scan", "sensor_msgs/msg/LaserScan"), ("/scan_ath", "sensor_msgs/msg/LaserScan"),
                                         ("/ath/goal_dispatch", "builtin_interfaces/msg/Time")]):
            writer.create_topic(rosbag2_py.TopicMetadata(id=i, name=name, type=typ, serialization_format="cdr"))
        writer.write("/ath/goal_dispatch", serialize_message(TimeMsg(sec=int(DISPATCH))), int(DISPATCH * 1e9))
        events = [("/scan", m) for m in raw] + [("/scan_ath", m) for m in out]
        for topic, m in sorted(events, key=lambda e: e[1].received):
            msg = LaserScan()
            sec = int(m.stamp)
            msg.header.stamp.sec, msg.header.stamp.nanosec = sec, int(round((m.stamp - sec) * 1e9))
            msg.ranges = [float(r) for r in m.ranges]
            writer.write(topic, serialize_message(msg), int(round(m.received * 1e9)))
        del writer
        rdir = run / "runs" / scenario_id
        rdir.mkdir(parents=True)
        (rdir / "run_record.json").write_text(json.dumps({
            "scenario_id": scenario_id, "seed": 1, "status": "ok", "nav2_result": "SUCCEEDED",
            "verdict": {"passed": True, "reason": ""}, "stamp": stamp}))
        records.append(f"runs/{scenario_id}/run_record.json")
    (run / "suite.json").write_text(json.dumps({"suite": "m3_conditions", "records": records, "stamp": stamp}))
    script = load_script("m3_fault_check")
    assert script.main(["--run", str(run), "--out", str(tmp_path / "m3.json")]) == 0
    result = json.loads((tmp_path / "m3.json").read_text())
    assert result["all_confined"] and [f["fault"] for f in result["faults"]] == [
        "range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout"]
    assert result["stamp"]["commit"] == "a" * 40 and result["faults"][0]["verdict"]["passed"]
