"""Tests for the bag checks used by the M2 wiring evidence (Requirements 4.1, 5.1, 5.5)."""

from __future__ import annotations

import json
import math

import pytest

from harness import bag_checks as bc
from harness.bag_checks import ScanMsg

NAV2 = [{"node": n, "type": "sensor_msgs/msg/LaserScan", "reliability": "BEST_EFFORT"} for n in bc.NAV2_SCAN_READERS]


def scans(n, start=10.0, ranges=(1.0, math.inf, 2.0)):
    return [ScanMsg(start + 0.1 * i, start + 0.1 * i + 0.001, tuple(ranges)) for i in range(n)]


def test_same_ranges_treats_inf_and_nan_as_equal():
    assert bc.same_ranges([1.0, math.inf, math.nan], (1.0, math.inf, math.nan))
    assert not bc.same_ranges([1.0, 2.0], [1.0, 2.5])
    assert not bc.same_ranges([1.0], [1.0, 1.0])


def test_passthrough_ok_and_edges():
    raw = scans(20)
    assert bc.passthrough_report(raw, list(raw))["ok"]
    trimmed = bc.passthrough_report(raw, raw[1:-2])  # recorder edge effects only
    assert trimmed["ok"] and trimmed["unmatched_raw"] == 3


def test_passthrough_detects_changes_and_gaps():
    raw = scans(20)
    out = list(raw)
    out[5] = ScanMsg(out[5].stamp, out[5].received, (1.0, 5.0, 2.0))
    report = bc.passthrough_report(raw, out)
    assert not report["ok"] and report["differing"] == 1
    gap = bc.passthrough_report(raw, raw[:8] + raw[9:])
    assert not gap["ok"] and gap["unmatched_raw_inside"] == 1
    assert not bc.passthrough_report([], [])["ok"]


def test_wiring_report():
    subs = {"/scan_ath": [*NAV2, {"node": "/rosbag2_recorder"}], "/scan": [{"node": "/injector_node"}]}
    record = {"scenario_id": "fixed10-000", "status": "ok", "leftover_processes": []}
    good = bc.wiring_report(subs, (scans(5), scans(5)), 100, record)
    assert good["ok"] and good["missing_nav2_readers"] == []
    bad = bc.wiring_report({"/scan_ath": NAV2[:2], "/scan": [{"node": "/amcl"}]}, (scans(5), scans(5)), 0,
                           {**record, "leftover_processes": ["gz sim"]})
    assert not bad["ok"]
    assert bad["checks"] == {"nav2_reads_scan_ath": False, "nav2_does_not_read_scan": False,
                             "scan_ath_equals_scan": True, "ground_truth_recorded": False,
                             "no_leftover_processes": False}


@pytest.mark.ros
def test_read_scans_and_check_wiring_script(tmp_path, load_script, monkeypatch):
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import LaserScan

    from harness.runner.gt_bridge import GT_TOPIC, PoseSample, to_pose_stamped

    run = tmp_path / "run"
    bag = run / "bags" / "fixed10-000"
    bag.parent.mkdir(parents=True)
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
    for i, (name, kind) in enumerate([("/scan", "sensor_msgs/msg/LaserScan"), ("/scan_ath", "sensor_msgs/msg/LaserScan"),
                                      (GT_TOPIC, "geometry_msgs/msg/PoseStamped")]):
        writer.create_topic(rosbag2_py.TopicMetadata(id=i, name=name, type=kind, serialization_format="cdr"))
    for k in range(6):
        msg = LaserScan()
        msg.header.stamp.sec, msg.header.stamp.nanosec = 10 + k, 0
        msg.ranges = [1.0, float("inf"), 2.0 + k]
        writer.write("/scan", serialize_message(msg), (10 + k) * 10**9)
        writer.write("/scan_ath", serialize_message(msg), (10 + k) * 10**9 + 1000)
        writer.write(GT_TOPIC, serialize_message(to_pose_stamped(PoseSample(10 + k, 0, 0, 0, 0, 0, 0, 0, 1))),
                     (10 + k) * 10**9)
    del writer
    raw, out = bc.read_scans(bag)
    assert len(raw) == len(out) == 6 and raw[2].ranges[2] == 4.0 and out[0].received == pytest.approx(10.000001)
    assert bc.ground_truth_count(bag) == 6
    rdir = run / "runs" / "fixed10-000"
    (rdir / "wiring").mkdir(parents=True)
    (rdir / "wiring" / "subscriptions.json").write_text(json.dumps({"/scan_ath": NAV2, "/scan": []}))
    (rdir / "wiring" / "topic_info_scan_ath.txt").write_text("Subscription count: 4\n")
    stamp = {"command": "bash scripts/run_suite.sh runs/m2_one --wiring", "seed": 1, "commit": "e" * 40}
    (rdir / "run_record.json").write_text(json.dumps({"scenario_id": "fixed10-000", "status": "ok",
                                                     "leftover_processes": [], "stamp": stamp}))
    script = load_script("check_wiring")
    assert script.main(["--run", str(run), "--out", str(tmp_path / "evidence")]) == 0
    saved = json.loads((tmp_path / "evidence" / "wiring_check.json").read_text())
    assert saved["ok"] and saved["stamp"]["commit"] == "e" * 40
    assert (tmp_path / "evidence" / "topic_info_scan_ath.txt").exists()
