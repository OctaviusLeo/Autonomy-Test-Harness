"""Ground_Truth reader: republish the robot's true pose from Gazebo's own pose stream.

Gazebo's SceneBroadcaster (loaded by the arena world) publishes every dynamic entity's pose on
``/world/<world>/dynamic_pose/info``. This node runs
``gz topic -e -t /world/<world>/dynamic_pose/info --json-output``, which prints one protobuf-JSON
``gz.msgs.Pose_V`` per line, takes the entry named after the robot model, and publishes it as
``geometry_msgs/PoseStamped`` on ``/ath/ground_truth/robot_pose`` in frame ``map`` (the arena's map
frame equals the world frame), stamped with the message's simulation time. This is the simulator's
state, never the robot's estimate (Requirement 6.1), and it lands in the bag (Requirement 5.5).

Protobuf JSON writes 64-bit integers as strings and omits fields equal to zero, so every missing
field reads as zero.

Usage (inside the image): python -m harness.runner.gt_bridge --world empty_10x10 --model turtlebot4
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import subprocess
import sys
import threading
from typing import Callable, Iterable

GT_TOPIC = "/ath/ground_truth/robot_pose"


@dataclasses.dataclass(frozen=True)
class PoseSample:
    """One true robot pose at a simulation time (seconds since the simulation started)."""

    sec: int
    nanosec: int
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float

    @property
    def t(self) -> float:
        return self.sec + self.nanosec * 1e-9

    @property
    def yaw(self) -> float:
        return math.atan2(2.0 * (self.qw * self.qz + self.qx * self.qy),
                          1.0 - 2.0 * (self.qy * self.qy + self.qz * self.qz))


def pose_topic(world: str) -> str:
    return f"/world/{world}/dynamic_pose/info"


def gz_echo_command(world: str) -> list[str]:
    return ["gz", "topic", "-e", "-t", pose_topic(world), "--json-output"]


def parse_pose_line(line: str, model: str) -> PoseSample | None:
    """Parse one JSON Pose_V line. Returns None when ``model`` is not in it; raises ValueError if malformed."""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("pose line is not a JSON object")
    stamp = (data.get("header") or {}).get("stamp") or {}
    sec, nanosec = int(stamp.get("sec", 0)), int(stamp.get("nsec", 0))
    for entry in data.get("pose") or []:
        if entry.get("name") != model:
            continue
        pos = entry.get("position") or {}
        ori = entry.get("orientation") or {}
        return PoseSample(
            sec, nanosec,
            float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), float(pos.get("z", 0.0)),
            float(ori.get("x", 0.0)), float(ori.get("y", 0.0)), float(ori.get("z", 0.0)), float(ori.get("w", 0.0)),
        )
    return None


@dataclasses.dataclass
class StreamStats:
    published: int = 0
    ignored: int = 0      # lines without the robot model
    malformed: int = 0    # lines that could not be parsed (skipped and counted)


def pump(lines: Iterable[str], model: str, publish: Callable[[PoseSample], None],
         stats: StreamStats, stop: threading.Event | None = None) -> StreamStats:
    """Parse each line and publish the robot's pose; skip and count malformed lines."""
    for line in lines:
        if stop is not None and stop.is_set():
            break
        line = line.strip()
        if not line:
            continue
        try:
            sample = parse_pose_line(line, model)
        except (ValueError, TypeError, AttributeError):
            stats.malformed += 1
            continue
        if sample is None:
            stats.ignored += 1
            continue
        publish(sample)
        stats.published += 1
    return stats


def to_pose_stamped(sample: PoseSample, frame_id: str = "map"):
    from geometry_msgs.msg import PoseStamped  # ROS message types exist only in the image

    msg = PoseStamped()
    msg.header.stamp.sec = sample.sec
    msg.header.stamp.nanosec = sample.nanosec
    msg.header.frame_id = frame_id
    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = sample.x, sample.y, sample.z
    o = msg.pose.orientation
    o.x, o.y, o.z, o.w = sample.qx, sample.qy, sample.qz, sample.qw
    return msg


def from_pose_stamped(msg) -> PoseSample:
    p, o = msg.pose.position, msg.pose.orientation
    return PoseSample(msg.header.stamp.sec, msg.header.stamp.nanosec, p.x, p.y, p.z, o.x, o.y, o.z, o.w)


def make_node(model: str, lines: Iterable[str], node_name: str = "gt_bridge"):
    """Create the ROS node and start a thread that pumps ``lines`` into its publisher."""
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    class GroundTruthBridge(Node):
        def __init__(self) -> None:
            super().__init__(node_name)
            qos = QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE)
            self.publisher = self.create_publisher(_pose_stamped_type(), GT_TOPIC, qos)
            self.stats = StreamStats()
            self.stop_event = threading.Event()
            self.thread = threading.Thread(
                target=pump, args=(lines, model, self._publish, self.stats, self.stop_event), daemon=True)
            self.thread.start()

        def _publish(self, sample: PoseSample) -> None:
            self.publisher.publish(to_pose_stamped(sample))

    return GroundTruthBridge()


def _pose_stamped_type():
    from geometry_msgs.msg import PoseStamped

    return PoseStamped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Republish Gazebo's true robot pose.")
    parser.add_argument("--world", default="empty_10x10")
    parser.add_argument("--model", default="turtlebot4")
    args = parser.parse_args(argv)

    import rclpy

    proc = subprocess.Popen(gz_echo_command(args.world), stdout=subprocess.PIPE, text=True, bufsize=1)
    rclpy.init()
    node = make_node(args.model, proc.stdout)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_event.set()
        proc.terminate()
        s = node.stats
        print(f"gt_bridge: published={s.published} ignored={s.ignored} malformed={s.malformed}", file=sys.stderr)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
