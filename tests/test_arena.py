"""Unit tests for the arena: world, map, and wall shapes agree (Requirements 2.6, 3.6)."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest
import yaml

from harness.world import arena as arena_mod
from harness.world.arena import FREE, OCCUPIED, Circle, Rect, arena, map_grid, read_pgm


def _inside(rect: Rect, x: float, y: float) -> bool:
    c, s = math.cos(-rect.yaw), math.sin(-rect.yaw)
    dx, dy = x - rect.x, y - rect.y
    lx, ly = c * dx - s * dy, s * dx + c * dy
    return abs(lx) <= rect.size_x / 2 and abs(ly) <= rect.size_y / 2


def test_unknown_world_is_rejected():
    with pytest.raises(ValueError, match="unsupported world"):
        arena("depot")


def test_walls_enclose_the_interior():
    a = arena()
    assert len(a.walls) == 4
    for wall in a.walls:
        assert min(wall.size_x, wall.size_y) == pytest.approx(0.2)
    # Each interior edge midpoint just outside the free region lies in a wall.
    for x, y in ((0.0, 5.05), (0.0, -5.05), (5.05, 0.0), (-5.05, 0.0), (5.1, 5.1), (-5.1, -5.1)):
        assert any(_inside(w, x, y) for w in a.walls), (x, y)


def test_map_cells_match_walls_and_interior():
    a = arena()
    grid = map_grid(a)
    assert len(grid) == a.map_cells == 220
    for j in range(a.map_cells):
        for i in range(a.map_cells):
            x, y = a.cell_center(i, j)
            if any(_inside(w, x, y) for w in a.walls):
                assert grid[j][i] == OCCUPIED, (i, j)
            if abs(x) < 5.0 and abs(y) < 5.0:
                assert grid[j][i] == FREE, (i, j)
            else:
                assert grid[j][i] == OCCUPIED, (i, j)


def test_written_map_matches_grid_and_frame(tmp_path):
    a = arena()
    arena_mod.write_map(a, tmp_path / "m.pgm", tmp_path / "m.yaml")
    width, height, pixels = read_pgm(tmp_path / "m.pgm")
    assert (width, height) == (220, 220)
    grid = map_grid(a)
    # PGM rows run top (largest y) to bottom; map_server puts the origin at the bottom-left pixel.
    assert pixels[0] == grid[height - 1][0]
    meta = yaml.safe_load((tmp_path / "m.yaml").read_text())
    assert meta["image"] == "m.pgm" and meta["mode"] == "trinary"
    ox, oy, _ = meta["origin"]
    res = meta["resolution"]
    for i, j in ((0, 0), (10, 10), (110, 57), (219, 219)):
        top_row = height - 1 - j
        assert pixels[top_row * width + i] == grid[j][i]
        assert (ox + (i + 0.5) * res, oy + (j + 0.5) * res) == pytest.approx(a.cell_center(i, j))
    # The first free cell's center is the first cell center inside the interior.
    assert a.cell_center(10, 10) == pytest.approx((-4.975, -4.975))


def test_world_sdf_parses_and_names_the_world(tmp_path):
    a = arena()
    arena_mod.write_world_sdf(a, tmp_path / "w.sdf")
    root = ET.parse(tmp_path / "w.sdf").getroot()
    world = root.find("world")
    assert world is not None and world.get("name") == "empty_10x10"
    plugins = {p.get("name") for p in world.findall("plugin")}
    assert "gz::sim::systems::SceneBroadcaster" in plugins
    assert "gz::sim::systems::Sensors" in plugins
    assert "fuel" not in (tmp_path / "w.sdf").read_text().lower()
    assert len([m for m in world.findall("model") if m.get("name", "").startswith("wall_")]) == 4


def test_regeneration_is_byte_identical(tmp_path, load_script):
    build_world = load_script("build_world")
    for out in (tmp_path / "a", tmp_path / "b"):
        assert build_world.main(["--out", str(out)]) == 0
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml"):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_obstacle_shapes():
    class _P:
        x, y, yaw = 1.0, 2.0, 0.5

    class _Box:
        shape = "box"
        pose = _P()

        class size:
            x, y, z = 0.4, 0.6, 0.8

    class _Cyl:
        shape = "cylinder"
        pose = _P()

        class size:
            radius, height = 0.3, 0.6

    class _Bad:
        shape = "cone"

    assert arena_mod.obstacle_shape(_Box()) == Rect(1.0, 2.0, 0.4, 0.6, 0.5)
    assert arena_mod.obstacle_shape(_Cyl()) == Circle(1.0, 2.0, 0.3)
    with pytest.raises(ValueError):
        arena_mod.obstacle_shape(_Bad())


def test_read_pgm_rejects_other_formats(tmp_path):
    path = tmp_path / "x.pgm"
    path.write_bytes(b"P2\n1 1\n255\n0\n")
    with pytest.raises(ValueError):
        read_pgm(path)
