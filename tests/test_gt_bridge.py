"""Tests for the Ground_Truth reader (Requirements 5.5, 6.1)."""

from __future__ import annotations

import json
import math
import time

import pytest

from harness.runner import gt_bridge
from harness.runner.gt_bridge import PoseSample, StreamStats, parse_pose_line, pump


def _line(sec="12", nsec=500000000, name="turtlebot4", x=1.5, y=-2.0, qz=None, qw=None, extra=()):
    pose = {"name": name, "id": 26, "position": {"x": x, "y": y}}
    if qz is not None or qw is not None:
        pose["orientation"] = {k: v for k, v in (("z", qz), ("w", qw)) if v is not None}
    return json.dumps({"header": {"stamp": {"sec": sec, "nsec": nsec}}, "pose": [*extra, pose]})


def test_recorded_gazebo_stream_parses(repo_root):
    lines = (repo_root / "tests" / "fixtures" / "gz_pose_stream.jsonl").read_text().splitlines()
    first = parse_pose_line(lines[0], "turtlebot4")
    assert first.sec == 106 and first.nanosec == 50000000
    assert first.x == pytest.approx(-3.0, abs=1e-3) and first.y == pytest.approx(-3.0, abs=1e-3)
    assert abs(first.yaw) < 1e-3
    assert parse_pose_line(lines[1], "turtlebot4").t == pytest.approx(106.068)


def test_missing_fields_read_as_zero():
    sample = parse_pose_line(json.dumps({"pose": [{"name": "turtlebot4", "orientation": {"w": 1}}]}), "turtlebot4")
    assert (sample.sec, sample.nanosec, sample.x, sample.y, sample.z) == (0, 0, 0.0, 0.0, 0.0)
    assert sample.qw == 1.0 and sample.yaw == 0.0


def test_yaw_from_quaternion():
    half = math.radians(120) / 2
    sample = parse_pose_line(_line(qz=math.sin(half), qw=math.cos(half)), "turtlebot4")
    assert sample.yaw == pytest.approx(math.radians(120))


def test_other_models_are_ignored_and_malformed_lines_counted():
    published: list[PoseSample] = []
    stats = StreamStats()
    lines = [
        _line(name="wall_0"),
        "not json",
        "[1, 2]",
        json.dumps({"pose": [{"name": "turtlebot4", "position": {"x": "abc"}}]}),
        "",
        _line(sec="13", extra=[{"name": "base_link", "position": {}}]),
    ]
    pump(lines, "turtlebot4", published.append, stats)
    assert [s.sec for s in published] == [13]
    assert (stats.published, stats.ignored, stats.malformed) == (1, 1, 3)


def test_pump_stops_when_asked():
    import threading

    stop = threading.Event()
    stop.set()
    stats = pump([_line()], "turtlebot4", lambda s: None, StreamStats(), stop)
    assert stats.published == 0


def test_echo_command_names_the_world_topic():
    assert gt_bridge.gz_echo_command("empty_10x10") == [
        "gz", "topic", "-e", "-t", "/world/empty_10x10/dynamic_pose/info", "--json-output"]


@pytest.mark.ros
def test_node_publishes_pose_stamped_with_sim_time():
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    rclpy.init()
    try:
        listener = rclpy.create_node("gt_listener")
        received: list = []
        listener.create_subscription(PoseStamped, gt_bridge.GT_TOPIC, received.append,
                                     QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE))

        def delayed_lines():
            time.sleep(1.0)  # let discovery match the publisher and the listener
            yield _line(sec="7", nsec=250000000, x=0.5, y=0.25, qz=0.0, qw=1.0)
            yield _line(name="other")
            yield _line(sec="8", nsec=0, x=0.75)

        node = gt_bridge.make_node("turtlebot4", delayed_lines(), node_name="gt_bridge_test")
        deadline = time.monotonic() + 10
        while len(received) < 2 and time.monotonic() < deadline:
            rclpy.spin_once(listener, timeout_sec=0.1)
            rclpy.spin_once(node, timeout_sec=0.0)
        assert len(received) == 2
        first = gt_bridge.from_pose_stamped(received[0])
        assert received[0].header.frame_id == "map"
        assert (first.sec, first.nanosec, first.x, first.y) == (7, 250000000, 0.5, 0.25)
        assert node.stats.ignored == 1
        node.destroy_node()
        listener.destroy_node()
    finally:
        rclpy.shutdown()


@pytest.mark.ros
def test_main_runs_gz_echo_and_reports_counts(monkeypatch, capsys):
    import rclpy

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.stdout = iter([_line(), "garbage"])
            self.terminated = False

        def terminate(self):
            self.terminated = True

    procs = []
    monkeypatch.setattr(gt_bridge.subprocess, "Popen", lambda cmd, **kw: procs.append(FakeProc(cmd, **kw)) or procs[-1])

    def fake_spin(node):
        node.thread.join(timeout=5)
        raise KeyboardInterrupt

    monkeypatch.setattr(rclpy, "spin", fake_spin)
    assert gt_bridge.main(["--world", "empty_10x10", "--model", "turtlebot4"]) == 0
    assert procs[0].cmd[-2:] == ["/world/empty_10x10/dynamic_pose/info", "--json-output"]
    assert procs[0].terminated
    assert "published=1 ignored=0 malformed=1" in capsys.readouterr().err
