"""Feature: autonomy-test-harness, Property 2 (exactly N feasible scenarios) and Property 3 (infeasible
scenarios are rejected by reason). Validates: Requirements 3.1, 3.3, 3.4, 3.6.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.generator import feasibility, generate as gen
from harness.oracle import geometry
from harness.schema.scenario import Scenario
from harness.world.arena import Circle, Rect, arena, obstacle_shape

CONFIGS = {name: gen.load_config(f"config/{name}.yaml") for name in ("generator", "generator_smoke")}
A = arena("empty_10x10")


def _grid(s: Scenario, cfg: gen.GeneratorConfig) -> feasibility.Grid:
    return feasibility.scenario_grid(s, A, cfg.robot_radius_m, cfg.clearance_m, cfg.grid_resolution_m)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.integers(0, 2**31 - 1), st.integers(1, 3), st.sampled_from(sorted(CONFIGS)))
def test_property_2_exactly_n_feasible(seed, n, name):
    cfg = CONFIGS[name]
    result = gen.generate(seed, n, cfg, prefix="p2")
    assert len(result.scenarios) == n
    assert set(result.rejections) == set(feasibility.REASONS)
    assert [s.scenario_id for s in result.scenarios] == [f"p2-{i:03d}" for i in range(n)]
    inflate = cfg.robot_radius_m + cfg.clearance_m
    for s in result.scenarios:
        grid = _grid(s, cfg)
        start, goal = grid.cell(s.start.x, s.start.y), grid.cell(s.goal.x, s.goal.y)
        assert start is not None and goal is not None
        assert not grid.occupied[start[1], start[0]]
        assert grid.reachable(start, goal)
        # Independent of the grid: the start keeps the inflation distance from every shape,
        # up to half a cell diagonal (the grid tests cell centers).
        shapes = [*A.walls, *(obstacle_shape(o) for o in s.obstacles)]
        assert geometry.min_distance(s.start.x, s.start.y, shapes) > inflate - cfg.grid_resolution_m * math.sqrt(2) / 2
        d = math.hypot(s.goal.x - s.start.x, s.goal.y - s.start.y)
        assert cfg.start_goal_distance_m.min <= d <= cfg.start_goal_distance_m.max
        assert cfg.obstacle_count.min <= len(s.obstacles) <= cfg.obstacle_count.max


def _base(start=(-3.0, -3.0), goal=(3.0, 3.0), obstacles=()) -> Scenario:
    return Scenario.model_validate({
        "schema_version": 1, "scenario_id": "p3-000", "seed": 0, "world": "empty_10x10", "time_limit_s": 90.0,
        "start": {"x": start[0], "y": start[1], "yaw": 0.0}, "goal": {"x": goal[0], "y": goal[1], "yaw": 0.0},
        "obstacles": list(obstacles), "faults": []})


def _box(x, y, sx, sy, yaw=0.0):
    return {"shape": "box", "size": {"x": sx, "y": sy, "z": 0.8}, "pose": {"x": x, "y": y, "yaw": yaw}}


xy = st.floats(-4.0, 4.0, allow_nan=False)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(xy, xy, st.floats(0.3, 0.8), st.floats(-3.1, 3.1))
def test_property_3_start_inside_obstacle(x, y, size, yaw):
    s = _base(start=(x, y), goal=(-x, -y), obstacles=[_box(x, y, size, size, yaw)])
    assert feasibility.is_feasible(s, _grid(s, CONFIGS["generator"])) == (False, "start_inside_obstacle")


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(5.51, 50.0), st.sampled_from(["start", "goal"]), st.sampled_from([1, -1]), st.sampled_from(["x", "y"]))
def test_property_3_off_map(offset, which, sign, axis):
    point = {"x": 0.0, "y": 0.0}
    point[axis] = sign * offset
    start, goal = (-1.0, -1.0), (1.0, 1.0)
    if which == "start":
        start = (point["x"], point["y"])
    else:
        goal = (point["x"], point["y"])
    s = _base(start=start, goal=goal)
    assert feasibility.is_feasible(s, _grid(s, CONFIGS["generator"])) == (False, "off_map")


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(1.0, 3.0), st.floats(1.0, 3.0), st.floats(0.6, 1.0), st.booleans())
def test_property_3_disconnected_goal(gx, gy, half, inside):
    if inside:  # the goal itself inside an obstacle
        obstacles = [_box(gx, gy, 0.6, 0.6)]
    else:  # a closed square fence around the goal
        t = 0.2
        obstacles = [_box(gx, gy + half, 2 * half + t, t), _box(gx, gy - half, 2 * half + t, t),
                     _box(gx + half, gy, t, 2 * half + t), _box(gx - half, gy, t, 2 * half + t)]
    s = _base(start=(-3.5, -3.5), goal=(gx, gy), obstacles=obstacles)
    assert feasibility.is_feasible(s, _grid(s, CONFIGS["generator"])) == (False, "unreachable")


def test_open_scenario_is_feasible_and_grid_shape():
    s = _base()
    grid = _grid(s, CONFIGS["generator"])
    assert grid.shape == (220, 220)
    assert feasibility.is_feasible(s, grid) == (True, "")
    assert grid.cell(-5.5, -5.5) == (0, 0) and grid.cell(5.5, 0.0) is None


def test_generation_errors(monkeypatch):
    cfg = CONFIGS["generator_smoke"]
    far = cfg.model_copy(update={"start_goal_distance_m": gen.Range(min=30.0, max=40.0)})
    with pytest.raises(gen.GenerationError, match="no goal within"):
        gen.generate_one(5, far, "x-000")
    monkeypatch.setattr(gen, "is_feasible", lambda s, g: (False, "unreachable"))
    with pytest.raises(gen.GenerationError, match="scenario seed 7: no feasible scenario"):
        gen.generate_one(7, cfg, "x-000")


@pytest.mark.parametrize("change, fragment", [
    ({"n": 0}, "n:"),
    ({"seed": -1}, "seed:"),
    ({"world": "depot"}, "world:"),
    ({"obstacle_count": {"min": 3, "max": 1}}, "obstacle_count"),
    ({"start_goal_distance_m": {"min": 5.0, "max": 1.0}}, "start_goal_distance_m"),
    ({"sample_bounds": {"x": {"min": -6.0, "max": 4.5}, "y": {"min": -4.5, "max": 4.5}}}, "sample_bounds"),
    ({"box_size_m": {"x": {"min": 0.0, "max": 0.8}, "y": {"min": 0.3, "max": 0.8}, "z": {"min": 0.5, "max": 1.0}}}, "box_size_m.x"),
    ({"start_goal_distance_m": {"min": -1.0, "max": 1.0}}, "start_goal_distance_m.min"),
    ({"extra": 1}, "extra"),
])
def test_config_validation_names_the_problem(tmp_path, change, fragment):
    import yaml

    data = yaml.safe_load(open("config/generator.yaml"))
    data.update(change)
    path = tmp_path / "g.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="invalid generator config") as info:
        gen.load_config(path)
    assert fragment in str(info.value)


def test_geometry_distances():
    r = Rect(1.0, 2.0, 2.0, 1.0, math.pi / 2)  # 1 m wide along x after rotation, 2 m along y
    assert geometry.distance_to_rect(1.0, 2.0, r) == 0.0
    assert geometry.distance_to_rect(2.0, 2.0, r) == pytest.approx(0.5)
    assert geometry.distance_to_rect(1.0, 4.0, r) == pytest.approx(1.0)
    assert geometry.distance_to_rect(2.5, 4.0, r) == pytest.approx(math.hypot(1.0, 1.0))
    c = Circle(0.0, 0.0, 0.5)
    assert geometry.distance_to_circle(3.0, 4.0, c) == pytest.approx(4.5)
    assert geometry.distance_to_circle(0.1, 0.0, c) == 0.0
    assert geometry.min_distance(0.0, 0.0, []) == math.inf
    assert geometry.clearance(3.0, 4.0, [c, r], 0.18) == pytest.approx(min(4.5, geometry.distance_to_rect(3, 4, r)) - 0.18)
    xs, ys = np.array([2.0, 2.5, 3.0]), np.array([2.0, 4.0, 4.0])
    for shape in (r, c):
        expected = [geometry.distance_to_shape(x, y, shape) for x, y in zip(xs, ys)]
        assert geometry.distance_field(xs, ys, shape) == pytest.approx(expected)
    with pytest.raises(TypeError):
        geometry.distance_to_shape(0, 0, "square")
    with pytest.raises(TypeError):
        geometry.distance_field(xs, ys, "square")
