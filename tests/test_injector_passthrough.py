"""Fault_Injector passthrough and schedule boundaries (Requirements 4.1, 4.2)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from harness.faults import schedule
from harness.faults.injector_node import FaultPipeline


def _fault(kind, start, end):
    return SimpleNamespace(type=kind, window=SimpleNamespace(start_s=start, end_s=end))


def test_window_boundaries():
    w = SimpleNamespace(start_s=5.0, end_s=15.0)
    assert not schedule.is_active(w, None)
    assert not schedule.is_active(w, 4.999)
    assert schedule.is_active(w, 5.0)
    assert schedule.is_active(w, 14.999)
    assert not schedule.is_active(w, 15.0)
    faults = [_fault("freeze", 5, 15), _fault("latency", 0, 6), _fault("ray_dropout", 20, 30)]
    assert schedule.active_indices(faults, 5.5) == [0, 1]
    assert schedule.active_indices(faults, 6.0) == [0]
    assert schedule.active_indices(faults, None) == []
    assert schedule.since_dispatch(12.5, None) is None
    assert schedule.since_dispatch(12.5, 2.5) == 10.0


def test_pipeline_without_faults_passes_every_scan_through():
    p = FaultPipeline()
    scans = [object() for _ in range(5)]
    p.set_dispatch(3.0)
    for i, scan in enumerate(scans):
        out = p.on_scan(scan, 3.0 + i)
        assert len(out) == 1 and out[0] is scan
    assert p.on_tick(10.0) == [] and p.active_types(10.0) == []


def test_pipeline_reports_active_types_only_after_dispatch():
    p = FaultPipeline([_fault("freeze", 0, 10)], seed=4)
    assert p.active_types(100.0) == []
    p.set_dispatch(100.0)
    p.set_dispatch(200.0)  # the first dispatch time wins
    assert p.dispatch == 100.0
    assert p.active_types(105.0) == ["freeze"] and p.active_types(110.0) == []


@pytest.mark.ros
def test_node_republishes_scans_unchanged():
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String

    from harness.faults.injector_node import ACTIVE_TOPIC, make_node

    rclpy.init()
    try:
        node = make_node(FaultPipeline(), now_fn=lambda: 1.0, node_name="injector_test", use_sim_time=False)
        peer = rclpy.create_node("injector_peer")
        qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        pub = peer.create_publisher(LaserScan, "/scan", qos)
        outputs, actives = [], []
        peer.create_subscription(LaserScan, "/scan_ath", outputs.append, qos)
        peer.create_subscription(String, ACTIVE_TOPIC, actives.append, qos)
        sent = []
        deadline = time.monotonic() + 15
        while len(outputs) < 10 and time.monotonic() < deadline:
            if len(sent) < 10 and pub.get_subscription_count() > 0:
                msg = LaserScan()
                msg.header.stamp.sec = len(sent)
                msg.angle_increment = 0.0175
                msg.ranges = [float(len(sent) + k) for k in range(360)]
                pub.publish(msg)
                sent.append(msg)
            rclpy.spin_once(node, timeout_sec=0.01)
            rclpy.spin_once(peer, timeout_sec=0.01)
        assert len(outputs) == 10
        for a, b in zip(sent, outputs):
            assert list(a.ranges) == list(b.ranges) and a.header.stamp.sec == b.header.stamp.sec
        assert json.loads(actives[0].data) == []
        assert node.received == node.published == 10
        assert node.now() == 1.0
        node.destroy_node()
        peer.destroy_node()
    finally:
        rclpy.shutdown()


@pytest.mark.ros
def test_main_loads_the_scenario_and_spins(monkeypatch, repo_root, capsys):
    import rclpy

    from harness.faults import injector_node

    seen = {}

    def fake_spin(node):
        seen["faults"] = [f.type for f in node.pipeline.faults]
        seen["clock"] = node.now()
        raise KeyboardInterrupt

    monkeypatch.setattr(rclpy, "spin", fake_spin)
    assert injector_node.main(["--scenario", str(repo_root / "scenarios" / "example_valid.yaml")]) == 0
    assert seen["faults"] == ["sector_blackout"] and seen["clock"] == 0.0
    assert "received=0 published=0" in capsys.readouterr().out
