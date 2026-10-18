"""The harness's ROS 2 client for one run: simulation clock, scans, initial pose, Nav2 readiness,
the ``NavigateToPose`` goal, goal-dispatch publication, Ground_Truth samples, and TF.

It talks to Nav2 only through published interfaces (topics, the ``NavigateToPose`` action, the
lifecycle managers' ``is_active`` services, TF), never through Nav2's code (Requirement 0.10).
Every wait has a deadline, so a stuck Nav2 becomes a recorded failing step instead of a hang.
The node owns its executor, so tests can spin fake Nav2 servers on another thread.
"""

from __future__ import annotations

import math
import time
from typing import Callable

import rclpy
from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Time as TimeMsg
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Trigger

from harness.runner.gt_bridge import GT_TOPIC, PoseSample, from_pose_stamped

DISPATCH_TOPIC = "/ath/goal_dispatch"
LIFECYCLE_MANAGERS = ("lifecycle_manager_localization", "lifecycle_manager_navigation")
STATUS_NAMES = {
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
}

LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def finite_count(ranges) -> int:
    return sum(1 for r in ranges if math.isfinite(r))


def stamp_seconds(stamp) -> float:
    return stamp.sec + stamp.nanosec * 1e-9


class HarnessClient(Node):
    """One run's view of the simulation and Nav2."""

    def __init__(self, scan_topic: str = "/scan", node_name: str = "ath_client",
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        super().__init__(node_name)
        self._monotonic = monotonic
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self)
        self.sim_time: float | None = None
        self.last_scan: LaserScan | None = None
        self.scan_count = 0
        self.amcl_pose: PoseWithCovarianceStamped | None = None
        self.gt_samples: list[PoseSample] = []
        self.create_subscription(Clock, "/clock", self._on_clock,
                                 QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(LaserScan, scan_topic, self._on_scan,
                                 QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl_pose, LATCHED)
        self.create_subscription(PoseStamped, GT_TOPIC, self._on_gt,
                                 QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE))
        self._initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self._dispatch_pub = self.create_publisher(TimeMsg, DISPATCH_TOPIC, LATCHED)
        self._nav = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self._tf_buffer = None
        self._tf_listener = None

    # ----------------------------------------------------------------- callbacks
    def _on_clock(self, msg: Clock) -> None:
        self.sim_time = stamp_seconds(msg.clock)

    def _on_scan(self, msg: LaserScan) -> None:
        self.last_scan = msg
        self.scan_count += 1

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self.amcl_pose = msg

    def _on_gt(self, msg: PoseStamped) -> None:
        self.gt_samples.append(from_pose_stamped(msg))

    # ----------------------------------------------------------------- spinning
    def spin_for(self, wall_s: float) -> None:
        end = self._monotonic() + wall_s
        while self._monotonic() < end:
            self._executor.spin_once(timeout_sec=0.02)

    def spin_until(self, predicate: Callable[[], bool], timeout_s: float) -> bool:
        """Spin until ``predicate()`` is true or ``timeout_s`` wall seconds pass."""
        end = self._monotonic() + timeout_s
        while not predicate():
            if self._monotonic() >= end:
                return False
            self._executor.spin_once(timeout_sec=0.05)
        return True

    def _wait_future(self, future, timeout_s: float) -> bool:
        return self.spin_until(future.done, timeout_s)

    # ----------------------------------------------------------------- readiness
    def wait_for_clock(self, timeout_s: float) -> bool:
        return self.spin_until(lambda: self.sim_time is not None, timeout_s)

    def wait_for_scan(self, min_finite: int, timeout_s: float) -> bool:
        """Wait for a scan with at least ``min_finite`` finite ranges."""
        return self.spin_until(
            lambda: self.last_scan is not None and finite_count(self.last_scan.ranges) >= min_finite, timeout_s)

    def lifecycle_active(self, manager: str, timeout_s: float = 2.0) -> bool:
        client = self.create_client(Trigger, f"/{manager}/is_active")
        try:
            if not client.wait_for_service(timeout_sec=0.0) and not self.spin_until(
                    client.service_is_ready, timeout_s):
                return False
            future = client.call_async(Trigger.Request())
            return self._wait_future(future, timeout_s) and bool(future.result().success)
        finally:
            self.destroy_client(client)

    def wait_lifecycle_active(self, managers=LIFECYCLE_MANAGERS, timeout_s: float = 120.0) -> bool:
        end = self._monotonic() + timeout_s
        pending = list(managers)
        while pending:
            if self.lifecycle_active(pending[0]):
                pending.pop(0)
                continue
            if self._monotonic() >= end:
                return False
            self.spin_for(0.5)
        return True

    def set_initial_pose(self, x: float, y: float, yaw: float, timeout_s: float = 60.0) -> bool:
        """Publish /initialpose (once a second) until AMCL reports a pose near it."""
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x, msg.pose.pose.position.y = x, y
        o = msg.pose.pose.orientation
        o.x, o.y, o.z, o.w = yaw_to_quaternion(yaw)
        msg.pose.covariance[0] = msg.pose.covariance[7] = 0.25 * 0.25
        msg.pose.covariance[35] = math.radians(10) ** 2

        def near() -> bool:
            if self.amcl_pose is None:
                return False
            p = self.amcl_pose.pose.pose.position
            return math.hypot(p.x - x, p.y - y) < 0.5

        end = self._monotonic() + timeout_s
        while self._monotonic() < end:
            self._initial_pose_pub.publish(msg)
            if self.spin_until(near, 1.0):
                return True
        return False

    # ----------------------------------------------------------------- goal
    def send_goal(self, x: float, y: float, yaw: float, timeout_s: float = 30.0):
        """Send a NavigateToPose goal in the map frame; returns the accepted goal handle or None."""
        if not self.spin_until(lambda: self._nav.server_is_ready(), timeout_s):
            return None
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        o = goal.pose.pose.orientation
        o.x, o.y, o.z, o.w = yaw_to_quaternion(yaw)
        future = self._nav.send_goal_async(goal)
        if not self._wait_future(future, timeout_s):
            return None
        handle = future.result()
        return handle if handle is not None and handle.accepted else None

    def publish_dispatch(self) -> float:
        """Publish the goal-dispatch simulation time on /ath/goal_dispatch (transient local)."""
        t = self.sim_time or 0.0
        msg = TimeMsg()
        msg.sec = int(t)
        msg.nanosec = int(round((t - int(t)) * 1e9))
        self._dispatch_pub.publish(msg)
        return t

    def wait_result(self, handle, dispatch_t: float, limit_s: float, wall_timeout_s: float) -> str:
        """Wait for the goal to finish within ``limit_s`` simulation seconds after dispatch.

        Returns SUCCEEDED, ABORTED, or CANCELED from Nav2, or TIME_LIMIT when the simulation-time
        limit passed (the goal is then cancelled), or NO_RESULT if the wall-clock guard expired.
        """
        result_future = handle.get_result_async()
        over = lambda: self.sim_time is not None and self.sim_time - dispatch_t >= limit_s  # noqa: E731
        if not self.spin_until(lambda: result_future.done() or over(), wall_timeout_s):
            self._cancel(handle)
            return "NO_RESULT"
        if result_future.done():
            return STATUS_NAMES.get(result_future.result().status, f"STATUS_{result_future.result().status}")
        self._cancel(handle)
        return "TIME_LIMIT"

    def _cancel(self, handle) -> None:
        future = handle.cancel_goal_async()
        self._wait_future(future, 5.0)

    def wait_sim_seconds(self, seconds: float, wall_timeout_s: float) -> bool:
        start = self.sim_time
        if start is None:
            return False
        return self.spin_until(lambda: self.sim_time - start >= seconds, wall_timeout_s)

    # ----------------------------------------------------------------- TF
    def lookup_yaw(self, target: str, source: str, timeout_s: float = 10.0) -> float | None:
        """Yaw of ``source`` in ``target`` from TF (e.g. base_link -> rplidar_link)."""
        from rclpy.time import Time
        from tf2_ros import Buffer, TransformListener

        if self._tf_buffer is None:
            self._tf_buffer = Buffer()
            self._tf_listener = TransformListener(self._tf_buffer, self, spin_thread=False)
        ok = self.spin_until(lambda: self._tf_buffer.can_transform(target, source, Time()), timeout_s)
        if not ok:
            return None
        q = self._tf_buffer.lookup_transform(target, source, Time()).transform.rotation
        return quaternion_to_yaw(q.x, q.y, q.z, q.w)

    def close(self) -> None:
        self._executor.remove_node(self)
        self.destroy_node()


def init_ros() -> None:
    if not rclpy.ok():
        rclpy.init()


def shutdown_ros() -> None:
    if rclpy.ok():
        rclpy.shutdown()
