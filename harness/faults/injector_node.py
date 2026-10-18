"""Fault_Injector: a ROS 2 node between the simulated lidar and Nav2 (Requirements 4.1, 4.2).

It subscribes to ``/scan`` (published by the simulation's own bridge) and publishes ``/scan_ath``,
which Nav2 reads through ``config/nav2_params_ath.yaml``. Until the Runner publishes the goal-dispatch
simulation time on ``/ath/goal_dispatch``, and whenever no Fault is active, every scan passes through
unchanged (the same message object is republished). It also publishes the active Fault types on
``/ath/faults/active`` (a JSON list per scan) so the bag shows when each Fault was on.

:class:`FaultPipeline` is the pure core (no ROS imports), so the scheduling logic is unit-tested
without a middleware; :func:`make_node` wraps it in an ``rclpy`` node.

Usage (inside the image): python -m harness.faults.injector_node --scenario <scenario.yaml>
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Sequence

from harness.faults.schedule import DISPATCH_TOPIC, active_indices, since_dispatch

IN_TOPIC = "/scan"
OUT_TOPIC = "/scan_ath"
ACTIVE_TOPIC = "/ath/faults/active"
TICK_HZ = 200.0


class FaultPipeline:
    """Decides what to publish for each incoming scan, given the Scenario's Faults and the dispatch time."""

    def __init__(self, faults: Sequence = (), seed: int = 0) -> None:
        self.faults = list(faults)
        self.seed = seed
        self.dispatch: float | None = None

    def set_dispatch(self, t: float) -> None:
        if self.dispatch is None:
            self.dispatch = t

    def active(self, now: float) -> list[int]:
        return active_indices(self.faults, since_dispatch(now, self.dispatch))

    def active_types(self, now: float) -> list[str]:
        return [self.faults[i].type for i in self.active(now)]

    def on_scan(self, msg: Any, now: float) -> list[Any]:
        """Scans to publish now in response to ``msg`` arriving at simulation time ``now``."""
        return [msg]

    def on_tick(self, now: float) -> list[Any]:
        """Scans released by the 200 Hz tick (none without a latency Fault)."""
        return []


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


def pipeline_for(scenario) -> FaultPipeline:
    return FaultPipeline(scenario.faults, scenario.seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fault_Injector: /scan -> Faults -> /scan_ath")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--in-topic", default=IN_TOPIC)
    parser.add_argument("--out-topic", default=OUT_TOPIC)
    args = parser.parse_args(argv)

    import rclpy

    from harness.schema.validate import load_scenario

    rclpy.init()
    node = make_node(pipeline_for(load_scenario(args.scenario)), args.in_topic, args.out_topic)
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
