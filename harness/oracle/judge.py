"""The Oracle: a Verdict from Ground_Truth only (Requirements 6.1-6.6).

Inputs are the true robot poses from Gazebo (``/ath/ground_truth/robot_pose``), the goal-dispatch
simulation time, the Scenario's obstacles, and the arena's walls. The robot's own estimate (AMCL,
odometry) is never read; :func:`judge_trace` takes a whole :class:`RunTrace` and uses only its
Ground_Truth part, so that independence is testable (Property 13).

- **Collision (6.2):** for every sample at or after dispatch, the clearance is the distance from the
  robot's center to the nearest obstacle or wall minus ``footprint_radius_m``; a Collision is the
  minimum clearance dropping below ``collision_threshold_m``. The TurtleBot 4 model has no contact
  sensor, so the contact clause cannot trigger.
- **Goal_Reached (6.3):** the first sample whose true position is within ``goal_position_tol_m`` and
  true yaw within ``goal_orientation_tol_rad`` of the goal.
- **Verdict (6.4, 6.5):** pass iff Goal_Reached happens within ``time_limit_s`` after dispatch and no
  Collision occurs. Reason ``"collision"`` takes precedence over ``"timeout"`` (goal not reached in
  time). ``detail`` records Nav2's action result and the end time, so "Nav2 reported success but the
  robot was not at the goal" is visible.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Sequence

from harness.oracle.geometry import min_distance
from harness.runner.gt_bridge import PoseSample
from harness.world.arena import Arena, obstacle_shape


@dataclasses.dataclass(frozen=True)
class Thresholds:
    footprint_radius_m: float
    collision_threshold_m: float
    goal_position_tol_m: float
    goal_orientation_tol_rad: float


@dataclasses.dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str  # "", "collision", or "timeout"
    detail: str
    time_to_goal_s: float | None
    min_clearance_m: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        return cls(bool(data["passed"]), str(data["reason"]), str(data["detail"]),
                   None if data["time_to_goal_s"] is None else float(data["time_to_goal_s"]),
                   float(data["min_clearance_m"]))


@dataclasses.dataclass(frozen=True)
class RunTrace:
    """What a run's bag holds for judging: Ground_Truth, dispatch time, and (ignored) estimates."""

    ground_truth: Sequence[PoseSample]
    dispatch_time: float | None
    estimate: Sequence[PoseSample] = ()


def angle_error(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def judge(gt_samples: Sequence[PoseSample], dispatch_time: float, scenario, arena: Arena, thresholds: Thresholds,
          nav2_result: str) -> Verdict:
    """Judge one run from its Ground_Truth samples. Raises ValueError if no sample follows dispatch."""
    samples = sorted((s for s in gt_samples if s.t >= dispatch_time), key=lambda s: s.t)
    if not samples:
        raise ValueError("no Ground_Truth sample at or after goal dispatch")
    shapes = [*arena.walls, *(obstacle_shape(o) for o in scenario.obstacles)]
    goal, limit = scenario.goal, scenario.time_limit_s
    min_clearance = math.inf
    reached_at: float | None = None
    for s in samples:
        min_clearance = min(min_clearance, min_distance(s.x, s.y, shapes) - thresholds.footprint_radius_m)
        elapsed = s.t - dispatch_time
        if (reached_at is None and elapsed <= limit
                and math.hypot(s.x - goal.x, s.y - goal.y) <= thresholds.goal_position_tol_m
                and angle_error(s.yaw, goal.yaw) <= thresholds.goal_orientation_tol_rad):
            reached_at = elapsed
    collision = min_clearance < thresholds.collision_threshold_m
    last = samples[-1]
    end = (f"nav2_result={nav2_result}; end_t={last.t - dispatch_time:.3f}s after dispatch; "
           f"final true pose ({last.x:.3f}, {last.y:.3f}, yaw {last.yaw:.3f}); "
           f"{math.hypot(last.x - goal.x, last.y - goal.y):.3f} m from goal")
    if collision:
        reason = "collision"
        detail = f"min clearance {min_clearance:.3f} m < {thresholds.collision_threshold_m} m; {end}"
    elif reached_at is None:
        reason = "timeout"
        detail = f"goal not reached within {limit:.1f} s; {end}"
    else:
        reason = ""
        detail = f"goal reached at {reached_at:.3f} s; {end}"
    return Verdict(passed=reason == "", reason=reason, detail=detail,
                   time_to_goal_s=None if reached_at is None else round(reached_at, 3),
                   min_clearance_m=round(min_clearance, 4))


def judge_trace(trace: RunTrace, scenario, arena: Arena, thresholds: Thresholds, nav2_result: str) -> Verdict:
    """Judge a recorded run; only ``trace.ground_truth`` and ``trace.dispatch_time`` are read."""
    if trace.dispatch_time is None:
        raise ValueError("the bag has no goal-dispatch time")
    return judge(trace.ground_truth, trace.dispatch_time, scenario, arena, thresholds, nav2_result)
