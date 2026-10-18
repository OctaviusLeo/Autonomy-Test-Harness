"""Pure lidar fault models (Requirements 4.3-4.9), testable without the simulator.

A ray's **bearing** is ``angle_min + i * angle_increment`` in the scan's own frame, in degrees
normalized to [0, 360). **No-return** is ``+inf``, the ROS convention for "no detection" (REP 117).
Each Fault draws from its own RNG, seeded with ``[scenario seed, fault index]`` through
``numpy.random.SeedSequence``, so Faults do not perturb one another and a re-run reproduces every draw
(Requirements 0.2, 0.3).

- range noise: finite ranges get ``N(0, sigma^2)`` added, then are clipped to [range_min, range_max];
- per-ray dropout: ray i becomes no-return iff ``u_i < p`` with ``u_i ~ Uniform[0, 1)``;
- whole-scan dropout: nothing is published while the window is active;
- added latency: :class:`LatencyQueue` releases each scan at the first check where arrival + L <= now;
- frozen scan: :class:`FreezeState` keeps the last scan before the window and repeats it, unchanged;
- blacked-out sector: rays whose bearing is within ``width_deg / 2`` of ``center_deg`` (circular
  distance) become no-return; every other ray is unchanged.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

NO_RETURN = float("inf")


def fault_rng(scenario_seed: int, fault_index: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([int(scenario_seed), int(fault_index)]))


def bearings_deg(n: int, angle_min: float, angle_increment: float) -> np.ndarray:
    """Bearing of each ray in degrees, in [0, 360)."""
    return np.mod(np.degrees(angle_min + np.arange(n) * angle_increment), 360.0)


def circular_distance_deg(a: np.ndarray | float, b: float) -> np.ndarray:
    """Smallest angle between bearings, in [0, 180]."""
    return np.abs(np.mod(np.asarray(a, dtype=float) - b + 180.0, 360.0) - 180.0)


def apply_range_noise(ranges: np.ndarray, sigma_m: float, rng: np.random.Generator,
                      range_min: float, range_max: float) -> np.ndarray:
    out = np.array(ranges, dtype=float)
    finite = np.isfinite(out)
    out[finite] = np.clip(out[finite] + rng.normal(0.0, sigma_m, size=int(finite.sum())), range_min, range_max)
    return out


def apply_ray_dropout(ranges: np.ndarray, prob: float, rng: np.random.Generator) -> np.ndarray:
    out = np.array(ranges, dtype=float)
    out[rng.random(out.shape[0]) < prob] = NO_RETURN
    return out


def apply_sector_blackout(ranges: np.ndarray, angle_min: float, angle_increment: float,
                          center_deg: float, width_deg: float) -> np.ndarray:
    out = np.array(ranges, dtype=float)
    in_sector = circular_distance_deg(bearings_deg(out.shape[0], angle_min, angle_increment), center_deg) <= width_deg / 2
    out[in_sector] = NO_RETURN
    return out


def scan_dropout_publishes() -> bool:
    """Whole-scan dropout's decision while its window is active: publish nothing."""
    return False


class LatencyQueue:
    """Hold scans and release each at the first check where ``arrival + delay <= now`` (in arrival order)."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self._queue: deque[tuple[float, Any]] = deque()

    def __len__(self) -> int:
        return len(self._queue)

    def push(self, item: Any, arrival: float) -> None:
        self._queue.append((arrival, item))

    def release(self, now: float) -> list[Any]:
        out = []
        while self._queue and self._queue[0][0] + self.delay_s <= now:
            out.append(self._queue.popleft()[1])
        return out


class FreezeState:
    """Remember the last scan seen outside the window; inside it, repeat that scan unchanged."""

    def __init__(self) -> None:
        self.stored: Any = None

    def observe(self, scan: Any) -> None:
        self.stored = scan

    def frozen(self, current: Any) -> Any:
        return current if self.stored is None else self.stored
