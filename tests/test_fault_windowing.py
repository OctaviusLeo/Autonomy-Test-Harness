"""Feature: autonomy-test-harness, Property 5: Faults apply only inside their window.
Validates: Requirements 4.2, 4.11 (plus a ROS node test per Fault type).
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.faults.injector_node import FaultPipeline

PARAMS = {
    "range_noise": SimpleNamespace(sigma_m=0.2),
    "ray_dropout": SimpleNamespace(prob=0.5),
    "scan_dropout": SimpleNamespace(),
    "latency": SimpleNamespace(latency_ms=300.0),
    "freeze": SimpleNamespace(),
    "sector_blackout": SimpleNamespace(center_deg=270.0, width_deg=90.0),
}
INC = 6.28 / 359


def fault(kind, start, end):
    return SimpleNamespace(type=kind, window=SimpleNamespace(start_s=start, end_s=end), params=PARAMS[kind])


def scan(k: int):
    return SimpleNamespace(ranges=[1.0 + 0.01 * ((k + i) % 300) for i in range(360)], angle_min=0.0,
                           angle_increment=INC, range_min=0.164, range_max=20.0, stamp=k)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.sampled_from(sorted(PARAMS)), st.floats(0.0, 5.0), st.floats(0.5, 5.0), st.integers(0, 2**31 - 1),
       st.floats(0.0, 3.0))
def test_property_5_faults_apply_only_inside_their_window(kind, start, length, seed, dispatch):
    end = start + length
    p = FaultPipeline([fault(kind, start, end)], seed)
    before = scan(-1)
    assert p.on_scan(before, 0.0) == [before]  # no dispatch yet: always passthrough
    p.set_dispatch(dispatch)
    last_outside = before
    released_by_tick = []
    for k in range(120):  # 10 Hz for 12 s of simulation time
        t = k * 0.1
        s = scan(k)
        out = p.on_scan(s, dispatch + t)
        released_by_tick.extend(p.on_tick(dispatch + t + 0.05))
        if not (start <= (dispatch + t) - dispatch < end):  # the elapsed time the pipeline computes
            if kind == "latency" and out == [] and t >= end:
                continue  # held, unmodified, behind scans still queued from the window (released below)
            assert len(out) == 1 and out[0] is s
            last_outside = s
            continue
        if kind == "scan_dropout":
            assert out == []
        elif kind == "latency":
            assert out == []
        elif kind == "freeze":
            assert out == [last_outside]
        elif kind == "sector_blackout":
            r = np.asarray(out[0].ranges)
            bearings = np.mod(np.degrees(np.arange(360) * INC), 360)
            assert np.all(np.isinf(r[np.abs(bearings - 270) < 44.9]))
            assert np.all(r[np.abs(bearings - 270) > 45.1] == np.asarray(s.ranges)[np.abs(bearings - 270) > 45.1])
        else:  # range_noise or ray_dropout changes the ranges
            assert not np.array_equal(np.asarray(out[0].ranges), np.asarray(s.ranges))
            assert out[0] is not s and out[0].stamp == s.stamp
    if kind == "latency":
        inside = [k for k in range(120) if start <= (dispatch + k * 0.1) - dispatch < end]
        assert [r.stamp for r in released_by_tick][:len(inside)] == inside[:len(released_by_tick)]
        assert len(released_by_tick) >= len(inside) - 3  # the last few may still be queued at the end
        stamps = [r.stamp for r in released_by_tick]
        assert stamps == sorted(stamps)
        assert all(r.ranges == scan(r.stamp).ranges for r in released_by_tick)  # delayed, never modified


def test_faults_apply_in_scenario_order_with_independent_rngs():
    faults = [fault("range_noise", 0, 10), fault("sector_blackout", 0, 10)]
    p = FaultPipeline(faults, seed=11)
    p.set_dispatch(0.0)
    out = np.asarray(p.on_scan(scan(1), 1.0)[0].ranges)
    bearings = np.mod(np.degrees(np.arange(360) * INC), 360)
    assert np.all(np.isinf(out[np.abs(bearings - 270) < 44.9]))
    alone = FaultPipeline([fault("range_noise", 0, 10)], seed=11)
    alone.set_dispatch(0.0)
    noisy = np.asarray(alone.on_scan(scan(1), 1.0)[0].ranges)
    keep = np.abs(bearings - 270) > 45.1
    assert np.array_equal(out[keep], noisy[keep])  # the second Fault's RNG does not perturb the first's draws
    assert p.active_types(1.0) == ["range_noise", "sector_blackout"] and p.active_types(11.0) == []


def test_latency_queue_drains_after_the_window():
    p = FaultPipeline([fault("latency", 0.0, 1.0)], seed=1)
    p.set_dispatch(0.0)
    assert p.on_scan(scan(0), 0.5) == []
    assert p.on_tick(0.79) == [] and [s.stamp for s in p.on_tick(0.8)] == [0]
    s = scan(1)
    assert p.on_scan(s, 1.5) == [s]


def test_latency_releases_in_order_when_the_window_closes():
    # Scans queued in the window's last 300 ms are still held when the window closes; a scan arriving then
    # waits behind them, unmodified, instead of overtaking them, and passthrough resumes once they are out.
    p = FaultPipeline([fault("latency", 0.0, 1.0)], seed=1)
    p.set_dispatch(0.0)
    published = []
    for k in range(16):  # 10 Hz from 0.0 s to 1.5 s, the 200 Hz timer approximated by a tick after each scan
        published += p.on_scan(scan(k), k * 0.1)
        published += p.on_tick(k * 0.1 + 0.05)
    assert [s.stamp for s in published] == sorted(s.stamp for s in published)
    after = scan(99)
    assert p.on_scan(after, 1.6) == [after]


@pytest.mark.ros
@pytest.mark.parametrize("kind", sorted(PARAMS))
def test_node_applies_each_fault_inside_its_window(kind):
    import rclpy
    from builtin_interfaces.msg import Time as TimeMsg
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan

    from harness.faults.injector_node import make_node, ros_scan_with_ranges

    clock = {"now": 0.0}
    rclpy.init()
    try:
        pipeline = FaultPipeline([fault(kind, 1.0, 2.0)], seed=5, rebuild=ros_scan_with_ranges)
        node = make_node(pipeline, now_fn=lambda: clock["now"], node_name=f"injector_{kind}", use_sim_time=False)
        peer = rclpy.create_node(f"peer_{kind}")
        reliable = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        scan_pub = peer.create_publisher(LaserScan, "/scan", reliable)
        peer.create_publisher(TimeMsg, "/ath/goal_dispatch", latched).publish(TimeMsg(sec=10))
        outputs = []
        peer.create_subscription(LaserScan, "/scan_ath", outputs.append, reliable)

        def spin(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=0.005)
                rclpy.spin_once(peer, timeout_sec=0.005)

        deadline = time.monotonic() + 10
        while (scan_pub.get_subscription_count() == 0 or pipeline.dispatch is None) and time.monotonic() < deadline:
            spin(0.05)
        assert pipeline.dispatch == 10.0
        sent = []
        for k in range(40):  # 10 Hz from t = 0 to 3.9 s after dispatch; the window is [1, 2)
            clock["now"] = 10.0 + k * 0.1
            msg = LaserScan()
            msg.header.stamp.sec, msg.header.stamp.nanosec = 100 + k // 10, (k % 10) * 100_000_000
            msg.angle_increment, msg.range_min, msg.range_max = INC, 0.164, 20.0
            msg.ranges = [2.0 + 0.001 * i for i in range(360)]
            scan_pub.publish(msg)
            sent.append(msg)
            spin(0.03)
        clock["now"] = 20.0
        spin(0.5)
        by_stamp = {}
        for o in outputs:
            by_stamp.setdefault((o.header.stamp.sec, o.header.stamp.nanosec), []).append(o)
        for k, msg in enumerate(sent):
            key = (msg.header.stamp.sec, msg.header.stamp.nanosec)
            inside = 10 <= k < 20
            got = by_stamp.get(key, [])
            if not inside:
                if kind != "freeze" or k != 9:
                    assert len(got) == 1 and list(got[0].ranges) == list(msg.ranges), (kind, k)
            elif kind == "scan_dropout":
                assert got == []
            elif kind == "latency":
                assert len(got) == 1 and list(got[0].ranges) == list(msg.ranges)  # released later, unchanged
            elif kind == "freeze":
                assert got == []  # every in-window output repeats the scan stamped at k = 9
            else:
                assert len(got) == 1 and list(got[0].ranges) != list(msg.ranges)
        if kind == "freeze":
            frozen_key = (sent[9].header.stamp.sec, sent[9].header.stamp.nanosec)
            assert len(by_stamp[frozen_key]) == 11  # its own passthrough plus 10 repeats in the window
        if kind == "sector_blackout":
            r = list(by_stamp[(101, 500_000_000)][0].ranges)
            assert math.isinf(r[270]) and r[90] == pytest.approx(2.09)
        node.destroy_node()
        peer.destroy_node()
    finally:
        rclpy.shutdown()
