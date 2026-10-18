"""Distances from a point (the robot's center) to footprint shapes, scalar and vectorized.

Shapes are :class:`~harness.world.arena.Rect` (oriented rectangle) and
:class:`~harness.world.arena.Circle`. The distance is 0 inside a shape. The Generator inflates its
occupancy grid with these distances, and the Oracle computes clearance as distance minus the robot's
footprint radius (Requirement 6.2).
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from harness.world.arena import Circle, Rect, Shape


def distance_to_rect(x: float, y: float, r: Rect) -> float:
    c, s = math.cos(r.yaw), math.sin(r.yaw)
    dx, dy = x - r.x, y - r.y
    lx, ly = c * dx + s * dy, -s * dx + c * dy
    ex, ey = max(abs(lx) - r.size_x / 2, 0.0), max(abs(ly) - r.size_y / 2, 0.0)
    return math.hypot(ex, ey)


def distance_to_circle(x: float, y: float, c: Circle) -> float:
    return max(math.hypot(x - c.x, y - c.y) - c.radius, 0.0)


def distance_to_shape(x: float, y: float, shape: Shape) -> float:
    if isinstance(shape, Rect):
        return distance_to_rect(x, y, shape)
    if isinstance(shape, Circle):
        return distance_to_circle(x, y, shape)
    raise TypeError(f"unknown shape {shape!r}")


def min_distance(x: float, y: float, shapes: Iterable[Shape]) -> float:
    """Distance to the nearest shape (infinity when there is none)."""
    return min((distance_to_shape(x, y, s) for s in shapes), default=math.inf)


def clearance(x: float, y: float, shapes: Iterable[Shape], footprint_radius_m: float) -> float:
    """Gap between a disk footprint centered at (x, y) and the nearest shape (negative when overlapping)."""
    return min_distance(x, y, shapes) - footprint_radius_m


def distance_field(xs: np.ndarray, ys: np.ndarray, shape: Shape) -> np.ndarray:
    """Vectorized :func:`distance_to_shape` over arrays of points."""
    if isinstance(shape, Rect):
        c, s = math.cos(shape.yaw), math.sin(shape.yaw)
        dx, dy = xs - shape.x, ys - shape.y
        lx, ly = c * dx + s * dy, -s * dx + c * dy
        ex = np.maximum(np.abs(lx) - shape.size_x / 2, 0.0)
        ey = np.maximum(np.abs(ly) - shape.size_y / 2, 0.0)
        return np.hypot(ex, ey)
    if isinstance(shape, Circle):
        return np.maximum(np.hypot(xs - shape.x, ys - shape.y) - shape.radius, 0.0)
    raise TypeError(f"unknown shape {shape!r}")
