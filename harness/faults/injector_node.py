"""Fault_Injector: a ROS 2 node between the simulated lidar and Nav2 (Requirements 4.1-4.3).

It subscribes to ``/scan`` (published by the simulation's own bridge) and publishes ``/scan_ath``,
which Nav2 reads through ``config/nav2_params_ath.yaml``. Until the Runner publishes the goal-dispatch
simulation time on ``/ath/goal_dispatch``, and whenever no Fault is active, every scan passes through
unchanged (the same message object is republished). It also publishes the active Fault types on
``/ath/faults/active`` (a JSON list per scan) so the bag shows when each Fault was on.

Active Faults apply in Scenario order, each with its own seeded RNG (``harness.faults.models``):
range noise, per-ray dropout, and sector blackout rewrite the ranges; a frozen scan replaces the
incoming scan with the last one seen before its window (same header); whole-scan dropout publishes
nothing; added latency queues the scan and a 200 Hz simulation-time timer releases it once
``arrival + L <= now``.

:class:`FaultPipeline` is the pure core (no ROS imports), so the scheduling and fault logic is unit-tested
without a middleware; :func:`make_node` wraps it in an ``rclpy`` node.

Usage (inside the image): python -m harness.faults.injector_node --scenario <scenario.yaml>
"""

from __future__ import annotations

import argparse
import copy
import json
from typing import Any, Callable, Sequence

import numpy as np

from harness.faults import models
from harness.faults.schedule import DISPATCH_TOPIC, active_indices, since_dispatch

IN_TOPIC = "/scan"
OUT_TOPIC = "/scan_ath"
ACTIVE_TOPIC = "/ath/faults/active"
TICK_HZ = 200.0


def copy_with_ranges(msg: Any, ranges: np.ndarray) -> Any:
    """A shallow copy of ``msg`` with new ranges (for plain objects; the node uses :func:`ros_scan_with_ranges`)."""
    out = copy.copy(msg)
    out.ranges = [float(r) for r in ranges]
    return out


class FaultPipeline:
    """Decides what to publish for each incoming scan, given the Scenario's Faults and the dispatch time."""

    def __init__(self, faults: Sequence = (), seed: int = 0,
                 rebuild: Callable[[Any, np.ndarray], Any] = copy_with_ranges) -> None:
        self.faults = list(faults)
        self.seed = seed
        self.rebuild = rebuild
        self.dispatch: float | None = None
        self.rngs = [models.fault_rng(seed, i) for i in range(len(self.faults))]
        self.freeze = {i: models.FreezeState() for i, f in enumerate(self.faults) if f.type == "freeze"}
        self.latency = {i: models.LatencyQueue(f.params.latency_ms / 1000.0)
                        for i, f in enumerate(self.faults) if f.type == "latency"}

    def set_dispatch(self, t: float) -> None:
        if self.dispatch is None:
            self.dispatch = t

    def active(self, now: float) -> list[int]:
        return active_indices(self.faults, since_dispatch(now, self.dispatch))

    def active_types(self, now: float) -> list[str]:
        return [self.faults[i].type for i in self.active(now)]

    def on_scan(self, msg: Any, now: float) -> list[Any]:
        """Scans to publish now in response to ``msg`` arriving at simulation time ``now``."""
        active = self.active(now)
        for i, state in self.freeze.items():
            if i not in active:
                state.observe(msg)
        if not active:
            return [msg]
        current, queue = msg, None
        for i in active:
            fault = self.faults[i]
            kind = fault.type
            if kind == "scan_dropout":
                return []
            if kind == "freeze":
                current = self.freeze[i].frozen(current)
            elif kind == "latency":
                queue = self.latency[i]
            else:
                ranges = np.asarray(current.ranges, dtype=float)
                if kind == "range_noise":
                    ranges = models.apply_range_noise(ranges, fault.params.sigma_m, self.rngs[i],
                                                      current.range_min, current.range_max)
                elif kind == "ray_dropout":
                    ranges = models.apply_ray_dropout(ranges, fault.params.prob, self.rngs[i])
                else:  # sector_blackout
                    ranges = models.apply_sector_blackout(ranges, current.angle_min, current.angle_increment,
                                                          fault.params.center_deg, fault.params.width_deg)
                current = self.rebuild(current, ranges)
        if queue is not None:
            queue.push(current, now)
            return []
        return [current]

    def on_tick(self, now: float) -> list[Any]:
        """Scans the latency queues release at ``now`` (the node calls this at 200 Hz of simulation time)."""
        released: list[Any] = []
        for queue in self.latency.values():
            released.extend(queue.release(now))
        return released


def ros_scan_with_ranges(msg, ranges: np.ndarray):
    """A new LaserScan with ``msg``'s header and geometry and the given ranges (float32)."""
    import array

    from sensor_msgs.msg import LaserScan

    out = LaserScan()
    out.header = msg.header
    out.angle_min, out.angle_max, out.angle_increment = msg.angle_min, msg.angle_max, msg.angle_increment
    out.time_increment, out.scan_time = msg.time_increment, msg.scan_time
    out.range_min, out.range_max = msg.range_min, msg.range_max
    values = array.array("f")
    values.frombytes(np.asarray(ranges, dtype=np.float32).tobytes())
    out.ranges = values
    out.intensities = msg.intensities
    return out


def make_node(pipeline: FaultPipeline, in_topic: str = IN_TOPIC, out_topic: str = OUT_TOPIC,
              now_fn: Callable[[], float] | None = None, node_name: str = "injector_node",
              use_sim_time: bool = True):
    """Create the ROS node around ``pipeline`` (``now_fn`` overrides the clock in tests)."""
    from builtin_interfaces.msg import Time as TimeMsg
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String

    reliable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)

    class InjectorNode(Node):
        def __init__(self) -> None:
            super().__init__(node_name, parameter_overrides=[Parameter("use_sim_time", value=use_sim_time)])
            self.pipeline = pipeline
            self.received = 0
            self.published = 0
            self.scan_pub = self.create_publisher(LaserScan, out_topic, reliable)
            self.active_pub = self.create_publisher(String, ACTIVE_TOPIC, reliable)
            self.create_subscription(LaserScan, in_topic, self._on_scan, reliable)
            self.create_subscription(TimeMsg, DISPATCH_TOPIC, self._on_dispatch, latched)
            self.create_timer(1.0 / TICK_HZ, self._on_tick)

        def now(self) -> float:
            return now_fn() if now_fn is not None else self.get_clock().now().nanoseconds * 1e-9

        def _on_dispatch(self, msg) -> None:
            self.pipeline.set_dispatch(msg.sec + msg.nanosec * 1e-9)

        def _on_scan(self, msg) -> None:
            now = self.now()
            self.received += 1
            self._publish(self.pipeline.on_scan(msg, now))
            self.active_pub.publish(String(data=json.dumps(self.pipeline.active_types(now))))

        def _on_tick(self) -> None:
            self._publish(self.pipeline.on_tick(self.now()))

        def _publish(self, scans) -> None:
            for scan in scans:
                self.scan_pub.publish(scan)
                self.published += 1

    return InjectorNode()


def pipeline_for(scenario, rebuild: Callable[[Any, np.ndarray], Any] = copy_with_ranges) -> FaultPipeline:
    return FaultPipeline(scenario.faults, scenario.seed, rebuild)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fault_Injector: /scan -> Faults -> /scan_ath")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--in-topic", default=IN_TOPIC)
    parser.add_argument("--out-topic", default=OUT_TOPIC)
    args = parser.parse_args(argv)

    import rclpy

    from harness.schema.validate import load_scenario

    rclpy.init()
    node = make_node(pipeline_for(load_scenario(args.scenario), ros_scan_with_ranges), args.in_topic, args.out_topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"injector_node: received={node.received} published={node.published}", flush=True)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
