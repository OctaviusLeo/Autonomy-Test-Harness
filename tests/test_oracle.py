"""Feature: autonomy-test-harness, Property 11 (collision decision), Property 12 (goal-and-timeout
decision), Property 13 (the Oracle ignores the robot's own estimate), plus known-answer unit tests.
Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.7.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.oracle.judge import RunTrace, Thresholds, Verdict, judge, judge_trace
from harness.runner.gt_bridge import PoseSample
from harness.runner.run_config import load_run_config
from harness.schema.scenario import Scenario
from harness.world.arena import arena

A = arena()
CFG = load_run_config("config/run.yaml")
T = CFG.thresholds
DISPATCH = 10.0


def sample(t: float, x: float, y: float, yaw: float = 0.0) -> PoseSample:
    sec = int(math.floor(t))
    return PoseSample(sec, int(round((t - sec) * 1e9)), x, y, 0.0, 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))


def scenario(goal=(3.0, 3.0, 0.0), obstacles=(), limit=90.0) -> Scenario:
    return Scenario.model_validate({
        "schema_version": 1, "scenario_id": "o-000", "seed": 1, "world": "empty_10x10", "time_limit_s": limit,
        "start": {"x": -3.0, "y": -3.0, "yaw": 0.0}, "goal": {"x": goal[0], "y": goal[1], "yaw": goal[2]},
        "obstacles": list(obstacles), "faults": []})


def cylinder(x, y, r):
    return {"shape": "cylinder", "size": {"radius": r, "height": 0.6}, "pose": {"x": x, "y": y, "yaw": 0.0}}


inside = st.floats(-4.0, 4.0, allow_nan=False)
points = st.lists(st.tuples(inside, inside), min_size=1, max_size=30)
circles = st.lists(st.tuples(st.floats(-3.5, 3.5), st.floats(-3.5, 3.5), st.floats(0.15, 0.4)), max_size=4)


def expected_min_clearance(path, obstacles, footprint):
    best = math.inf
    for x, y in path:
        wall = min(5.0 - abs(x), 5.0 - abs(y))  # the walls' inner faces are at |x| = 5 and |y| = 5
        best = min(best, wall - footprint)
        for cx, cy, r in obstacles:
            best = min(best, max(math.hypot(x - cx, y - cy) - r, 0.0) - footprint)
    return best


@settings(max_examples=100, derandomize=True)
@given(points, circles)
def test_property_11_collision_decision(path, obstacles):
    s = scenario(obstacles=[cylinder(*c) for c in obstacles])
    samples = [sample(DISPATCH + i, x, y) for i, (x, y) in enumerate(path)]
    v = judge(samples, DISPATCH, s, A, T, "SUCCEEDED")
    expected = expected_min_clearance(path, obstacles, T.footprint_radius_m)
    assert v.min_clearance_m == pytest.approx(expected, abs=1e-4)
    if expected < T.collision_threshold_m - 1e-9:
        assert not v.passed and v.reason == "collision"
    elif expected > T.collision_threshold_m + 1e-9:
        assert v.reason != "collision"


track = st.lists(st.tuples(st.floats(0.0, 200.0), st.floats(-3.0, 3.0), st.floats(-3.0, 3.0),
                           st.floats(-math.pi, math.pi)), min_size=1, max_size=30)


@settings(max_examples=100, derandomize=True)
@given(track, st.floats(-2.5, 2.5), st.floats(-2.5, 2.5), st.floats(-math.pi, math.pi), st.floats(5.0, 150.0),
       st.booleans())
def test_property_12_goal_and_timeout(points_, gx, gy, gyaw, limit, near_goal):
    if near_goal:  # make some samples land close to the goal
        points_ = [(t, gx + (x / 30), gy + (y / 30), gyaw + yaw / 20) for t, x, y, yaw in points_]
    s = scenario(goal=(gx, gy, gyaw), limit=limit)
    samples = [sample(DISPATCH + t, x, y, yaw) for t, x, y, yaw in points_]
    v = judge(samples, DISPATCH, s, A, T, "ABORTED")
    reached = [smp.t - DISPATCH for smp in sorted(samples, key=lambda q: q.t)
               if smp.t - DISPATCH <= limit
               and math.hypot(smp.x - gx, smp.y - gy) <= T.goal_position_tol_m
               and abs(math.atan2(math.sin(smp.yaw - gyaw), math.cos(smp.yaw - gyaw))) <= T.goal_orientation_tol_rad]
    assert v.reason != "collision"  # every point stays at least 1.82 m inside the walls
    if reached:
        assert v.passed and v.reason == "" and v.time_to_goal_s == pytest.approx(reached[0], abs=1e-3)
    else:
        assert not v.passed and v.reason == "timeout" and v.time_to_goal_s is None


@settings(max_examples=100, derandomize=True)
@given(track, track, st.sampled_from(["SUCCEEDED", "ABORTED", "CANCELED", "TIME_LIMIT"]))
def test_property_13_estimate_is_ignored(truth, estimate, nav2_result):
    s = scenario(goal=(1.0, 1.0, 0.5))
    gt = [sample(DISPATCH + t, x, y, yaw) for t, x, y, yaw in truth]
    est = [sample(DISPATCH + t, x, y, yaw) for t, x, y, yaw in estimate]
    with_estimate = judge_trace(RunTrace(gt, DISPATCH, est), s, A, T, nav2_result)
    with_truth_as_estimate = judge_trace(RunTrace(gt, DISPATCH, gt), s, A, T, "SUCCEEDED")
    without = judge_trace(RunTrace(gt, DISPATCH), s, A, T, nav2_result)
    assert with_estimate == without
    assert (with_estimate.passed, with_estimate.reason, with_estimate.time_to_goal_s, with_estimate.min_clearance_m) == (
        with_truth_as_estimate.passed, with_truth_as_estimate.reason, with_truth_as_estimate.time_to_goal_s,
        with_truth_as_estimate.min_clearance_m)


# --------------------------------------------------------------------------- known answers
EXACT = Thresholds(footprint_radius_m=0.25, collision_threshold_m=0.125, goal_position_tol_m=0.25,
                   goal_orientation_tol_rad=0.25)


def test_clearance_exactly_at_the_threshold_is_not_a_collision():
    s = scenario(obstacles=[cylinder(0.0, 0.0, 0.5)], goal=(0.875, 0.0, 0.0))
    at = judge([sample(DISPATCH, 0.875, 0.0)], DISPATCH, s, A, EXACT, "SUCCEEDED")
    assert at.min_clearance_m == 0.125 and at.reason == "" and at.passed
    below = judge([sample(DISPATCH, 0.875 - 2**-20, 0.0)], DISPATCH, s, A, EXACT, "SUCCEEDED")
    assert below.reason == "collision" and not below.passed


def test_goal_reached_exactly_at_each_tolerance():
    s = scenario(goal=(1.0, 1.0, 0.0))
    at_pos = judge([sample(DISPATCH + 1, 1.25, 1.0)], DISPATCH, s, A, EXACT, "SUCCEEDED")
    assert at_pos.passed and at_pos.time_to_goal_s == 1.0
    beyond = judge([sample(DISPATCH + 1, 1.25 + 2**-20, 1.0)], DISPATCH, s, A, EXACT, "SUCCEEDED")
    assert beyond.reason == "timeout"
    turned = sample(DISPATCH + 1, 1.0, 1.0, 0.25)
    tol = Thresholds(0.25, 0.125, 0.25, abs(turned.yaw))
    assert judge([turned], DISPATCH, s, A, tol, "SUCCEEDED").passed
    tighter = Thresholds(0.25, 0.125, 0.25, math.nextafter(abs(turned.yaw), 0.0))
    assert judge([turned], DISPATCH, s, A, tighter, "SUCCEEDED").reason == "timeout"


def test_goal_reached_exactly_at_the_time_limit():
    s = scenario(goal=(1.0, 1.0, 0.0), limit=90.0)
    on_time = judge([sample(DISPATCH + 90.0, 1.0, 1.0)], DISPATCH, s, A, T, "SUCCEEDED")
    assert on_time.passed and on_time.time_to_goal_s == 90.0
    late = judge([sample(DISPATCH + 90.5, 1.0, 1.0)], DISPATCH, s, A, T, "SUCCEEDED")
    assert late.reason == "timeout" and late.time_to_goal_s is None


def test_wall_collision():
    v = judge([sample(DISPATCH, 0.0, 0.0), sample(DISPATCH + 1, 4.9, 0.0)], DISPATCH, scenario(), A, T, "ABORTED")
    assert v.reason == "collision" and v.min_clearance_m == pytest.approx(0.1 - 0.18)
    assert "nav2_result=ABORTED" in v.detail


def test_collision_takes_precedence_over_reaching_the_goal():
    s = scenario(goal=(1.0, 0.0, 0.0), obstacles=[cylinder(1.4, 0.0, 0.3)])  # clearance 0.1 - 0.18 < 0.02
    v = judge([sample(DISPATCH + 1, 1.0, 0.0)], DISPATCH, s, A, T, "SUCCEEDED")
    assert v.reason == "collision" and v.time_to_goal_s == 1.0 and not v.passed


def test_nav2_success_with_the_true_pose_outside_tolerance_fails_as_timeout():
    s = scenario(goal=(2.0, 2.0, 0.0))
    v = judge([sample(DISPATCH + 1, 0.0, 0.0), sample(DISPATCH + 20, 2.4, 2.0)], DISPATCH, s, A, T, "SUCCEEDED")
    assert not v.passed and v.reason == "timeout"
    assert "nav2_result=SUCCEEDED" in v.detail and "0.400 m from goal" in v.detail


def test_samples_before_dispatch_are_ignored_and_errors():
    s = scenario(goal=(0.0, 0.0, 0.0))
    v = judge([sample(DISPATCH - 5, 0.0, 0.0), sample(DISPATCH + 1, 2.0, 2.0)], DISPATCH, s, A, T, "ABORTED")
    assert v.reason == "timeout"
    with pytest.raises(ValueError, match="no Ground_Truth"):
        judge([sample(1.0, 0, 0)], DISPATCH, s, A, T, "ABORTED")
    with pytest.raises(ValueError, match="dispatch"):
        judge_trace(RunTrace([sample(DISPATCH, 0, 0)], None), s, A, T, "ABORTED")


def test_verdict_round_trip_and_run_config(tmp_path):
    v = Verdict(False, "timeout", "d", None, 0.5)
    assert Verdict.from_dict(v.to_dict()) == v
    assert Verdict.from_dict(Verdict(True, "", "d", 12.5, 0.3).to_dict()).time_to_goal_s == 12.5
    assert CFG.robot_name == "turtlebot4" and CFG.hard_limit_s(90.0) == 180 + 270 + 60
    assert "/scan_ath" in CFG.bag_topics and "/ath/ground_truth/robot_pose" in CFG.bag_topics
    bad = tmp_path / "run.yaml"
    bad.write_text("footprint_radius_m: -1\n")
    with pytest.raises(ValueError, match="footprint_radius_m"):
        load_run_config(bad)


@pytest.mark.ros
def test_bag_round_trip(tmp_path):
    import rosbag2_py
    from builtin_interfaces.msg import Time as TimeMsg
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from rclpy.serialization import serialize_message

    from harness.oracle import bag_reader
    from harness.runner.gt_bridge import GT_TOPIC, to_pose_stamped

    uri = tmp_path / "bag"
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(uri), storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
    for i, (name, kind) in enumerate([(GT_TOPIC, "geometry_msgs/msg/PoseStamped"),
                                      ("/ath/goal_dispatch", "builtin_interfaces/msg/Time"),
                                      ("/amcl_pose", "geometry_msgs/msg/PoseWithCovarianceStamped")]):
        writer.create_topic(rosbag2_py.TopicMetadata(id=i, name=name, type=kind, serialization_format="cdr"))
    dispatch = TimeMsg(sec=10, nanosec=500000000)
    writer.write("/ath/goal_dispatch", serialize_message(dispatch), 10_500_000_000)
    writer.write("/ath/goal_dispatch", serialize_message(TimeMsg(sec=99)), 10_600_000_000)
    for k in range(5):
        writer.write(GT_TOPIC, serialize_message(to_pose_stamped(sample(10.0 + k, 0.5 * k, 0.0))), (10 + k) * 10**9)
    amcl = PoseWithCovarianceStamped()
    amcl.pose.pose.position.x = 7.0
    writer.write("/amcl_pose", serialize_message(amcl), 11 * 10**9)
    del writer
    trace = bag_reader.read_trace(uri)
    assert trace.dispatch_time == 10.5
    assert [s.x for s in trace.ground_truth] == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert trace.estimate[0].x == 7.0
    assert len(bag_reader.read_ground_truth(uri)) == 5
    assert list(bag_reader.read_messages(uri, ["/not_recorded"])) == []
    assert isinstance(PoseStamped(), PoseStamped)
