"""Feature: autonomy-test-harness, Properties 6-10 (fault models) plus one unit test per Fault type.
Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.11.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harness.faults import models as m

RANGE_MIN, RANGE_MAX = 0.164, 20.0
seeds = st.integers(0, 2**31 - 1)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(0.01, 0.5), seeds, st.integers(0, 5))
def test_property_6_range_noise_sigma_is_recovered(sigma, seed, index):
    rng = np.random.default_rng(seed)
    ranges = rng.uniform(5.0, 15.0, size=5000)  # far from both limits, so clipping does not bias the estimate
    out = m.apply_range_noise(ranges, sigma, m.fault_rng(seed, index), RANGE_MIN, RANGE_MAX)
    measured = float(np.std(out - ranges, ddof=1))
    assert abs(measured - sigma) <= 0.10 * sigma


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(0.0, 1.0), seeds, st.integers(0, 5))
def test_property_7_dropout_fraction_matches_probability(p, seed, index):
    ranges = np.full(20000, 3.0)  # at least 1,000 rays (20,000 keeps sampling error far below 2 points)
    out = m.apply_ray_dropout(ranges, p, m.fault_rng(seed, index))
    dropped = float(np.mean(np.isinf(out)))
    assert abs(dropped - p) <= 0.02
    assert np.all(out[np.isfinite(out)] == 3.0)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(25.0, 1000.0), seeds)
def test_property_8_latency_matches_configuration(latency_ms, seed):
    rng = np.random.default_rng(seed)
    delay = latency_ms / 1000.0
    q = m.LatencyQueue(delay)
    arrivals = 1.0 + np.cumsum(rng.uniform(0.09, 0.11, size=150))  # >= 100 scans at about 10 Hz
    released: dict[int, float] = {}
    pending = 0
    now = 1.0
    end = arrivals[-1] + delay + 0.1
    while now <= end:  # the node's 200 Hz simulation-time check
        while pending < len(arrivals) and arrivals[pending] <= now:
            q.push(pending, arrivals[pending])
            pending += 1
        for item in q.release(now):
            released[item] = now
        now = round(now + 0.005, 6)
    assert len(released) == len(arrivals)
    delays = np.array([released[i] - arrivals[i] for i in range(len(arrivals))])
    assert np.all(delays >= delay - 1e-9)  # never released early
    assert abs(float(np.mean(delays)) - delay) <= 0.2 * delay


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.lists(st.floats(0.2, 19.0), min_size=5, max_size=40), st.integers(0, 20), st.integers(1, 20))
def test_property_9_frozen_scan_repeats_the_last_pre_window_scan(values, start, length):
    scans = [(i, v) for i, v in enumerate(values)]  # (time, payload)
    state = m.FreezeState()
    outputs = []
    for t, scan in scans:
        if start <= t < start + length:
            outputs.append((t, state.frozen(scan)))
        else:
            state.observe(scan)
            outputs.append((t, scan))
    before = [s for t, s in scans if t < start]
    for t, out in outputs:
        if start <= t < start + length:
            assert out == (before[-1] if before else scans[t][1])
        else:
            assert out == scans[t][1]


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(0.0, 359.999), st.floats(0.5, 360.0), st.floats(-math.pi, math.pi), st.integers(90, 720))
def test_property_10_sector_blackout_hits_exactly_the_sector(center, width, angle_min, n):
    inc = 2 * math.pi / n
    ranges = np.linspace(1.0, 10.0, n)
    out = m.apply_sector_blackout(ranges, angle_min, inc, center, width)
    bearings = np.mod(np.degrees(angle_min + np.arange(n) * inc), 360.0)
    for b, r_in, r_out in zip(bearings, ranges, out):
        gap = min(abs(b - center), 360.0 - abs(b - center))
        if gap < width / 2 - 1e-6:
            assert math.isinf(r_out)
        elif gap > width / 2 + 1e-6:
            assert r_out == r_in


# --------------------------------------------------------------------------- one test per Fault type
def scan360():
    return np.concatenate([np.linspace(0.5, 8.0, 350), [math.inf] * 10])


def test_range_noise_unit():
    r = scan360()
    out = m.apply_range_noise(r, 0.10, m.fault_rng(7, 0), RANGE_MIN, RANGE_MAX)
    finite = np.isfinite(r)
    assert np.all(np.isinf(out[~finite])) and np.all(out[finite] >= RANGE_MIN) and np.all(out[finite] <= RANGE_MAX)
    assert 0.08 < float(np.std(out[finite] - r[finite])) < 0.12
    assert np.array_equal(out, m.apply_range_noise(r, 0.10, m.fault_rng(7, 0), RANGE_MIN, RANGE_MAX))
    assert not np.array_equal(out, m.apply_range_noise(r, 0.10, m.fault_rng(7, 1), RANGE_MIN, RANGE_MAX))
    clipped = m.apply_range_noise(np.array([0.17, 19.99]), 5.0, m.fault_rng(1, 0), RANGE_MIN, RANGE_MAX)
    assert np.all((clipped >= RANGE_MIN) & (clipped <= RANGE_MAX))


def test_ray_dropout_unit():
    out = m.apply_ray_dropout(scan360(), 0.5, m.fault_rng(3, 1))
    assert 0.40 < float(np.mean(np.isinf(out[:350]))) < 0.60
    assert np.all(np.isinf(m.apply_ray_dropout(scan360(), 1.0, m.fault_rng(3, 1))))
    assert np.array_equal(m.apply_ray_dropout(scan360(), 0.0, m.fault_rng(3, 1)), scan360())


def test_scan_dropout_unit():
    assert m.scan_dropout_publishes() is False


def test_latency_unit():
    q = m.LatencyQueue(0.3)
    q.push("a", 10.0)
    q.push("b", 10.1)
    assert q.release(10.29) == [] and len(q) == 2
    assert q.release(10.3) == ["a"]
    assert q.release(11.0) == ["b"] and len(q) == 0


def test_freeze_unit():
    state = m.FreezeState()
    assert state.frozen("x") == "x"  # nothing stored yet: pass the scan through
    state.observe("before")
    assert state.frozen("during-1") == "before" and state.frozen("during-2") == "before"


def test_sector_blackout_unit_forward_sector():
    # The TurtleBot 4 lidar is mounted at +90 deg, so the robot's forward direction is bearing 270 deg.
    n = 360
    inc = 6.28 / 359
    out = m.apply_sector_blackout(np.full(n, 2.0), 0.0, inc, 270.0, 90.0)
    bearings = m.bearings_deg(n, 0.0, inc)
    assert np.all(np.isinf(out[(bearings >= 226) & (bearings <= 314)]))
    assert np.all(out[(bearings < 224) | (bearings > 316)] == 2.0)
    wrap = m.apply_sector_blackout(np.full(n, 2.0), 0.0, inc, 0.0, 60.0)
    assert math.isinf(wrap[0]) and math.isinf(wrap[-1]) and wrap[180] == 2.0
    assert np.all(np.isinf(m.apply_sector_blackout(np.full(n, 2.0), 0.0, inc, 10.0, 360.0)))


def test_circular_distance():
    assert m.circular_distance_deg(359.0, 1.0) == pytest.approx(2.0)
    assert m.circular_distance_deg(180.0, 0.0) == pytest.approx(180.0)
