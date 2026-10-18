"""ROS tests for the harness client against a fake Nav2 in the same process (Requirement 0.10 interfaces)."""

from __future__ import annotations

import math
import threading
import time

import pytest

pytestmark = pytest.mark.ros


@pytest.fixture
def ros():
    import rclpy

    rclpy.init()
    yield rclpy
    rclpy.shutdown()


class FakeNav2:
    """Clock, scan, AMCL, lifecycle managers, NavigateToPose, and TF, as Nav2 and Gazebo expose them."""

    def __init__(self, mode="succeed", active=True):
        from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
        from nav2_msgs.action import NavigateToPose
        from rclpy.action import ActionServer, CancelResponse, GoalResponse
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import LaserScan
        from std_srvs.srv import Trigger
        from tf2_ros import StaticTransformBroadcaster

        from harness.runner.nav_client import LATCHED

        self.node = Node("fake_nav2")
        self.mode = mode
        self.sim = 0.0
        group = ReentrantCallbackGroup()
        self.clock_pub = self.node.create_publisher(Clock, "/clock", 10)
        self.scan_pub = self.node.create_publisher(LaserScan, "/scan", 10)
        self.amcl_pub = self.node.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", LATCHED)
        self.node.create_subscription(PoseWithCovarianceStamped, "/initialpose", self.amcl_pub.publish, 10)
        for manager in ("lifecycle_manager_localization", "lifecycle_manager_navigation"):
            def handler(request, response, ok=active):
                response.success = ok
                return response
            self.node.create_service(Trigger, f"/{manager}/is_active", handler)
        self.node.create_timer(0.01, self._tick, callback_group=group)

        def goal_cb(goal):
            return GoalResponse.REJECT if mode == "reject" else GoalResponse.ACCEPT

        self.server = ActionServer(self.node, NavigateToPose, "navigate_to_pose", self._execute,
                                   goal_callback=goal_cb, cancel_callback=lambda gh: CancelResponse.ACCEPT,
                                   callback_group=group)
        tf = TransformStamped()
        tf.header.frame_id, tf.child_frame_id = "base_link", "rplidar_link"
        tf.transform.rotation.z, tf.transform.rotation.w = math.sin(math.pi / 4), math.cos(math.pi / 4)
        self.tf = StaticTransformBroadcaster(self.node)
        self.tf.sendTransform(tf)
        self._scan_type = LaserScan
        self._clock_type = Clock
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def _tick(self):
        self.sim += 0.05
        msg = self._clock_type()
        msg.clock.sec, msg.clock.nanosec = int(self.sim), int((self.sim % 1) * 1e9)
        self.clock_pub.publish(msg)
        scan = self._scan_type()
        scan.ranges = [2.0] * 350 + [math.inf] * 10
        self.scan_pub.publish(scan)

    def _execute(self, goal_handle):
        from nav2_msgs.action import NavigateToPose

        if self.mode == "succeed":
            time.sleep(0.2)
            goal_handle.succeed()
        else:  # "hang": run until cancelled
            while not goal_handle.is_cancel_requested:
                time.sleep(0.02)
            goal_handle.canceled()
        return NavigateToPose.Result()

    def close(self):
        self.executor.shutdown()
        self.node.destroy_node()


def test_full_goal_flow(ros):
    from harness.runner.nav_client import HarnessClient

    nav = FakeNav2("succeed")
    client = HarnessClient()
    try:
        assert client.wait_for_clock(10)
        assert client.wait_for_scan(300, 10) and client.scan_count >= 1
        assert not client.wait_for_scan(355, 0.3)
        assert client.wait_lifecycle_active(timeout_s=10)
        assert client.set_initial_pose(-3.0, -3.0, 0.0, timeout_s=10)
        handle = client.send_goal(3.0, 3.0, 1.57, timeout_s=10)
        assert handle is not None
        dispatch = client.publish_dispatch()
        assert dispatch > 0
        assert client.wait_result(handle, dispatch, limit_s=60.0, wall_timeout_s=10) == "SUCCEEDED"
        assert client.wait_sim_seconds(0.5, wall_timeout_s=10)
        assert client.lookup_yaw("base_link", "rplidar_link", timeout_s=10) == pytest.approx(math.pi / 2)
        assert client.lookup_yaw("base_link", "no_such_frame", timeout_s=0.3) is None
    finally:
        client.close()
        nav.close()


def test_time_limit_cancels_the_goal(ros):
    from harness.runner.nav_client import HarnessClient

    nav = FakeNav2("hang")
    client = HarnessClient()
    try:
        assert client.wait_for_clock(10)
        handle = client.send_goal(1.0, 1.0, 0.0, timeout_s=10)
        assert client.wait_result(handle, client.publish_dispatch(), limit_s=1.0, wall_timeout_s=10) == "TIME_LIMIT"
        handle2 = client.send_goal(1.0, 1.0, 0.0, timeout_s=10)
        assert client.wait_result(handle2, client.sim_time, limit_s=1000.0, wall_timeout_s=0.3) == "NO_RESULT"
    finally:
        client.close()
        nav.close()


def test_rejected_goal_and_inactive_nav2(ros):
    from harness.runner.nav_client import HarnessClient

    nav = FakeNav2("reject", active=False)
    client = HarnessClient()
    try:
        assert client.wait_for_clock(10)
        assert client.send_goal(1.0, 1.0, 0.0, timeout_s=10) is None
        assert not client.wait_lifecycle_active(timeout_s=1.0)
        assert not client.lifecycle_active("lifecycle_manager_missing", timeout_s=0.3)
    finally:
        client.close()
        nav.close()


def test_no_action_server_and_no_clock(ros):
    from harness.runner.nav_client import HarnessClient

    client = HarnessClient(node_name="lonely_client")
    try:
        assert not client.wait_for_clock(0.3)
        assert not client.wait_sim_seconds(1.0, 0.1)
        assert client.send_goal(0.0, 0.0, 0.0, timeout_s=0.3) is None
        assert not client.set_initial_pose(0.0, 0.0, 0.0, timeout_s=0.5)
        client.spin_for(0.05)
    finally:
        client.close()


def test_ground_truth_and_dispatch_topics(ros):
    import rclpy
    from builtin_interfaces.msg import Time as TimeMsg
    from geometry_msgs.msg import PoseStamped

    from harness.runner import nav_client
    from harness.runner.gt_bridge import GT_TOPIC

    client = nav_client.HarnessClient()
    other = rclpy.create_node("gt_source")
    try:
        received = []
        other.create_subscription(TimeMsg, nav_client.DISPATCH_TOPIC, received.append, nav_client.LATCHED)
        pub = other.create_publisher(PoseStamped, GT_TOPIC, 10)
        client.sim_time = 12.25
        assert client.publish_dispatch() == 12.25
        msg = PoseStamped()
        msg.header.stamp.sec = 3
        deadline = time.monotonic() + 10
        while (not client.gt_samples or not received) and time.monotonic() < deadline:
            pub.publish(msg)
            rclpy.spin_once(other, timeout_sec=0.05)
            client.spin_for(0.05)
        assert client.gt_samples[0].sec == 3
        assert (received[0].sec, received[0].nanosec) == (12, 250000000)
    finally:
        other.destroy_node()
        client.close()


def test_pure_helpers():
    from harness.runner import nav_client

    q = nav_client.yaw_to_quaternion(1.2)
    assert nav_client.quaternion_to_yaw(*q) == pytest.approx(1.2)
    assert nav_client.finite_count([1.0, math.inf, math.nan, 2.0]) == 2
    nav_client.init_ros()
    nav_client.init_ros()
    nav_client.shutdown_ros()
    nav_client.shutdown_ros()
