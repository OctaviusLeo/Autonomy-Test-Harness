"""Read a run's MCAP bag with rosbag2_py: Ground_Truth, the dispatch time, and the AMCL estimate.

The bag is recorded with ``--use-sim-time``, and Ground_Truth messages carry Gazebo's simulation
time in their header stamps, so every time here is simulation seconds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

from harness.faults.schedule import DISPATCH_TOPIC
from harness.oracle.judge import RunTrace
from harness.runner.gt_bridge import GT_TOPIC, PoseSample, from_pose_stamped

AMCL_TOPIC = "/amcl_pose"


def read_messages(bag_path: str | Path, topics: Iterable[str]) -> Iterator[tuple[str, object, int]]:
    """Yield (topic, message, receive time in ns) for ``topics``, in recorded order."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag_path), storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    wanted = [t for t in topics if t in types]
    if not wanted:
        return
    reader.set_filter(rosbag2_py.StorageFilter(topics=wanted))
    classes = {t: get_message(types[t]) for t in wanted}
    while reader.has_next():
        topic, data, t_ns = reader.read_next()
        yield topic, deserialize_message(data, classes[topic]), t_ns


def _amcl_sample(msg) -> PoseSample:
    p, o = msg.pose.pose.position, msg.pose.pose.orientation
    return PoseSample(msg.header.stamp.sec, msg.header.stamp.nanosec, p.x, p.y, p.z, o.x, o.y, o.z, o.w)


def read_trace(bag_path: str | Path) -> RunTrace:
    gt: list[PoseSample] = []
    amcl: list[PoseSample] = []
    dispatch: float | None = None
    for topic, msg, _ in read_messages(bag_path, (GT_TOPIC, DISPATCH_TOPIC, AMCL_TOPIC)):
        if topic == GT_TOPIC:
            gt.append(from_pose_stamped(msg))
        elif topic == DISPATCH_TOPIC and dispatch is None:
            dispatch = msg.sec + msg.nanosec * 1e-9
        elif topic == AMCL_TOPIC:
            amcl.append(_amcl_sample(msg))
    return RunTrace(ground_truth=gt, dispatch_time=dispatch, estimate=amcl)


def read_ground_truth(bag_path: str | Path) -> list[PoseSample]:
    return list(read_trace(bag_path).ground_truth)
