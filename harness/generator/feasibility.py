"""Feasibility of a Scenario on an inflated occupancy grid (Requirements 3.3, 3.6).

The grid covers the arena's map at ``grid_resolution_m``. A cell is occupied when it lies outside
the arena's free interior or when its center is within ``robot_radius_m + clearance_m`` of a wall
or an obstacle. A Scenario is rejected with one reason, checked in this order:

- ``off_map``: the start or the goal lies outside the map;
- ``start_inside_obstacle``: the start cell is occupied;
- ``unreachable``: a 4-connected breadth-first flood fill from the start cell does not reach the
  goal cell (a goal inside an inflated obstacle is therefore unreachable).

This connectivity check is the definition of "unreachable" used everywhere: a necessary condition
for Nav2 to succeed, not a sufficient one.
"""

from __future__ import annotations

import dataclasses
from collections import deque
from typing import Iterable

import numpy as np

from harness.oracle.geometry import distance_field
from harness.world.arena import Arena, Shape, obstacle_shape

REASONS = ("start_inside_obstacle", "off_map", "unreachable")


@dataclasses.dataclass
class Grid:
    origin_x: float
    origin_y: float
    resolution: float
    occupied: np.ndarray  # [row j (y), column i (x)], True = blocked

    @property
    def shape(self) -> tuple[int, int]:
        return self.occupied.shape

    def cell(self, x: float, y: float) -> tuple[int, int] | None:
        """(i, j) of the cell containing (x, y), or None when the point is off the map."""
        i = int(np.floor((x - self.origin_x) / self.resolution))
        j = int(np.floor((y - self.origin_y) / self.resolution))
        rows, cols = self.occupied.shape
        if 0 <= i < cols and 0 <= j < rows:
            return i, j
        return None

    def reachable(self, start: tuple[int, int], goal: tuple[int, int]) -> bool:
        """4-connected breadth-first flood fill over free cells from ``start``; True if it reaches ``goal``."""
        if self.occupied[start[1], start[0]] or self.occupied[goal[1], goal[0]]:
            return False
        rows, cols = self.occupied.shape
        seen = np.zeros_like(self.occupied)
        seen[start[1], start[0]] = True
        queue = deque([start])
        while queue:
            i, j = queue.popleft()
            if (i, j) == goal:
                return True
            for ni, nj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= ni < cols and 0 <= nj < rows and not seen[nj, ni] and not self.occupied[nj, ni]:
                    seen[nj, ni] = True
                    queue.append((ni, nj))
        return False


def build_grid(arena: Arena, shapes: Iterable[Shape], inflate_m: float, resolution: float) -> Grid:
    """Occupancy grid of the arena's map: walls and ``shapes`` inflated by ``inflate_m``, outside the interior blocked."""
    n = int(round(2 * arena.map_half_m / resolution))
    ox, oy = -arena.map_half_m, -arena.map_half_m
    centers = ox + (np.arange(n) + 0.5) * resolution
    xs, ys = np.meshgrid(centers, oy + (np.arange(n) + 0.5) * resolution)
    occupied = (np.abs(xs) >= arena.interior_half_m) | (np.abs(ys) >= arena.interior_half_m)
    for shape in (*arena.walls, *shapes):
        occupied |= distance_field(xs, ys, shape) <= inflate_m
    return Grid(ox, oy, resolution, occupied)


def scenario_grid(scenario, arena: Arena, robot_radius_m: float, clearance_m: float, resolution: float) -> Grid:
    return build_grid(arena, [obstacle_shape(o) for o in scenario.obstacles], robot_radius_m + clearance_m, resolution)


def is_feasible(scenario, grid: Grid) -> tuple[bool, str]:
    """(True, "") if feasible, else (False, reason) with reason in :data:`REASONS`."""
    start = grid.cell(scenario.start.x, scenario.start.y)
    goal = grid.cell(scenario.goal.x, scenario.goal.y)
    if start is None or goal is None:
        return False, "off_map"
    if grid.occupied[start[1], start[0]]:
        return False, "start_inside_obstacle"
    if not grid.reachable(start, goal):
        return False, "unreachable"
    return True, ""
