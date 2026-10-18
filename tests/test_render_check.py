"""Tests for the headless-render check with fake processes and a fake lidar (Requirements 8.2, 8.3)."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import render_check as rc
from harness import repro

INC = 6.28 / 359


def scan_with_forward(range_m: float, finite: int = 360):
    ranges = [3.0] * 360
    i = rc.beam_index(360, 0.0, INC, 270.0)
    ranges[i] = range_m
    for k in range(360 - finite):
        ranges[(i + 100 + k) % 360] = math.inf
    return SimpleNamespace(ranges=ranges, angle_min=0.0, angle_increment=INC,
                           header=SimpleNamespace(stamp=SimpleNamespace(sec=4, nanosec=500_000_000)))


class Fakes:
    def __init__(self, models=("turtlebot4",), spawn_rc=0, box_listed=True, scan=None, got_scan=True):
        self.models_list = list(models)
        self.spawn_rc, self.box_listed, self.scan, self.got_scan = spawn_rc, box_listed, scan, got_scan
        self.started, self.torn_down, self.closed = [], False, False

    def deps(self):
        fakes = self
        clock = iter(range(0, 10**6, 5))

        class Session:
            def __init__(self, out, env):
                self.env = env

            def start_launch(self, spec):
                fakes.started.append(spec.command())

            def models(self):
                return fakes.models_list

            def run(self, cmd, timeout, env):
                if fakes.box_listed and fakes.spawn_rc == 0:
                    fakes.models_list = [*fakes.models_list, "render_box"]
                return subprocess.CompletedProcess(cmd, fakes.spawn_rc, "", "")

            def teardown(self, order=(), clean_shm=False):
                fakes.torn_down = True
                return []

        class Client:
            scan_count = 3

            def wait_for_scan(self, n, timeout_s):
                return fakes.got_scan

            def spin_until(self, predicate, timeout_s):
                self.scan_count += 10
                return predicate()

            @property
            def last_scan(self):
                return fakes.scan

            def close(self):
                fakes.closed = True

        return rc.RenderDeps(make_session=Session, make_client=Client,
                             read_text=lambda p: "GL_RENDERER = llvmpipe (LLVM 20.1.2, 256 bits)\n",
                             copy=lambda a, b: None, env=lambda: {"ATH_RENDER_MODE": "egl"},
                             monotonic=lambda: next(clock), sleep=lambda s: None)


def run(fakes, tmp_path):
    return rc.run_check(tmp_path, fakes.deps(), Path("/opt/ath"), "/stock/nav2_params.yaml")


def test_known_scene_passes(tmp_path):
    fakes = Fakes(scan=scan_with_forward(2.004))
    result = run(fakes, tmp_path)
    assert result["passed"] and result["measured_range_m"] == 2.004 and result["finite_ranges"] == 360
    assert result["renderer"].startswith("llvmpipe") and result["display"] is None
    assert result["box"]["center_x"] == pytest.approx(-0.04 + 2.0 + 0.5)
    assert (tmp_path / "box.sdf").exists() and fakes.torn_down and fakes.closed
    assert "use_rviz:=False" in fakes.started[0] and "x_pose:=0.0000" in fakes.started[0]
    text = rc.report_text(result, repro.Stamp("bash scripts/check_headless_render.sh", 0, "c" * 40))
    assert "Result: PASS" in text and "measured 2.004 m" in text and "Command: bash scripts/check_headless_render.sh" in text


@pytest.mark.parametrize("fakes_kwargs, problem", [
    ({"models": ()}, "robot never appeared"),
    ({"spawn_rc": 1}, "box was not spawned"),
    ({"box_listed": False}, "box was not spawned"),
    ({"got_scan": False}, "no /scan"),
])
def test_setup_failures(tmp_path, fakes_kwargs, problem):
    fakes = Fakes(scan=scan_with_forward(2.0), **fakes_kwargs)
    result = run(fakes, tmp_path)
    assert not result["passed"] and problem in result["problem"] and fakes.torn_down
    assert "Problem: " in rc.report_text(result, repro.Stamp("c", 0, "c" * 40))


def test_wrong_range_or_too_few_returns_fail(tmp_path):
    assert not run(Fakes(scan=scan_with_forward(2.2)), tmp_path)["passed"]
    assert not run(Fakes(scan=scan_with_forward(math.inf)), tmp_path)["passed"]
    few = run(Fakes(scan=scan_with_forward(2.0, finite=250)), tmp_path)
    assert not few["passed"] and few["finite_ranges"] == 250
    assert "Result: FAIL" in rc.report_text(few, repro.Stamp("c", 0, "c" * 40))


def test_beam_index_finds_the_forward_ray():
    i = rc.beam_index(360, 0.0, INC, 270.0)
    assert abs(math.degrees(i * INC) - 270.0) < INC * 90 / math.pi
    assert rc.beam_index(4, -math.pi, math.pi / 2, 0.0) == 2
