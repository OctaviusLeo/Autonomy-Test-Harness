"""Seeded Scenario generator (Requirements 3.1-3.5, 0.2, 0.3).

All randomness flows from seeds through ``numpy.random.default_rng``:

1. a set RNG seeded with the set seed draws one 31-bit Scenario seed per Scenario, in order;
2. ``generate_one(scenario_seed, ...)`` uses only its own RNG, seeded with that Scenario seed, and
   repeats until a feasible draw: obstacles (count, then per obstacle shape, size, pose), a start
   pose, then a goal pose redrawn until its distance from the start is within
   ``start_goal_distance_m`` (a sampling rule, not a rejection);
3. every value is rounded to 4 decimals before the feasibility check, so the written YAML is exactly
   what was checked; an infeasible draw is counted by reason and replaced from the same RNG, up to
   1,000 attempts, then an error names the Scenario seed;
4. each Scenario stores its own seed, so ``generate_one`` on that seed alone reproduces it.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness.generator.feasibility import REASONS, is_feasible, scenario_grid
from harness.schema.scenario import Scenario
from harness.world.arena import arena

MAX_ATTEMPTS = 1000
MAX_GOAL_DRAWS = 10000
SEED_LIMIT = 2**31

_STRICT = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Range(BaseModel):
    model_config = _STRICT

    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.max < self.min:
            raise ValueError(f"max ({self.max}) must be at least min ({self.min})")
        return self


class CountRange(BaseModel):
    model_config = _STRICT

    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "CountRange":
        if self.max < self.min:
            raise ValueError(f"max ({self.max}) must be at least min ({self.min})")
        return self


class Bounds(BaseModel):
    model_config = _STRICT

    x: Range
    y: Range


class BoxSizes(BaseModel):
    model_config = _STRICT

    x: Range
    y: Range
    z: Range


class CylinderSizes(BaseModel):
    model_config = _STRICT

    radius: Range
    height: Range


class GeneratorConfig(BaseModel):
    """design.md "GeneratorConfig"; out-of-bound values are rejected when the file is loaded."""

    model_config = _STRICT

    seed: int = Field(ge=0, lt=SEED_LIMIT)
    n: int = Field(ge=1)
    world: Literal["empty_10x10"]
    sample_bounds: Bounds
    obstacle_count: CountRange
    box_size_m: BoxSizes
    cylinder_size_m: CylinderSizes
    start_goal_distance_m: Range
    robot_radius_m: float = Field(gt=0)
    clearance_m: float = Field(ge=0)
    grid_resolution_m: float = Field(gt=0, le=0.5)
    time_limit_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_bounds(self) -> "GeneratorConfig":
        a = arena(self.world)
        for axis in (self.sample_bounds.x, self.sample_bounds.y):
            if axis.min <= -a.interior_half_m or axis.max >= a.interior_half_m:
                raise ValueError(f"sample_bounds must lie inside the arena interior (+-{a.interior_half_m} m)")
        for name, r in (("box_size_m.x", self.box_size_m.x), ("box_size_m.y", self.box_size_m.y),
                        ("box_size_m.z", self.box_size_m.z), ("cylinder_size_m.radius", self.cylinder_size_m.radius),
                        ("cylinder_size_m.height", self.cylinder_size_m.height)):
            if r.min <= 0:
                raise ValueError(f"{name}.min must be > 0")
        if self.start_goal_distance_m.min < 0:
            raise ValueError("start_goal_distance_m.min must be >= 0")
        return self


class GenerationError(RuntimeError):
    pass


@dataclasses.dataclass
class GenerationResult:
    seed: int
    scenarios: list[Scenario]
    rejections: dict[str, int]


def load_config(path: str | Path) -> GeneratorConfig:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return GeneratorConfig.model_validate(data)
    except ValidationError as exc:
        fields = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors())
        raise ValueError(f"invalid generator config '{path}': {fields}") from exc


def _r(value: float) -> float:
    r = round(float(value), 4)
    return 0.0 if r == 0 else r


def _uniform(rng: np.random.Generator, r: Range) -> float:
    return _r(rng.uniform(r.min, r.max))


def _yaw(rng: np.random.Generator) -> float:
    return _r(rng.uniform(-math.pi, math.pi))


def _sample(rng: np.random.Generator, config: GeneratorConfig, scenario_seed: int, scenario_id: str) -> Scenario:
    b = config.sample_bounds
    obstacles = []
    count = int(rng.integers(config.obstacle_count.min, config.obstacle_count.max + 1))
    for _ in range(count):
        if rng.random() < 0.5:
            s = config.box_size_m
            obstacles.append({"shape": "box",
                              "size": {"x": _uniform(rng, s.x), "y": _uniform(rng, s.y), "z": _uniform(rng, s.z)},
                              "pose": {"x": _uniform(rng, b.x), "y": _uniform(rng, b.y), "yaw": _yaw(rng)}})
        else:
            c = config.cylinder_size_m
            obstacles.append({"shape": "cylinder",
                              "size": {"radius": _uniform(rng, c.radius), "height": _uniform(rng, c.height)},
                              "pose": {"x": _uniform(rng, b.x), "y": _uniform(rng, b.y), "yaw": 0.0}})
    start = {"x": _uniform(rng, b.x), "y": _uniform(rng, b.y), "yaw": _yaw(rng)}
    d = config.start_goal_distance_m
    for _ in range(MAX_GOAL_DRAWS):
        gx, gy = _uniform(rng, b.x), _uniform(rng, b.y)
        if d.min <= math.hypot(gx - start["x"], gy - start["y"]) <= d.max:
            break
    else:
        raise GenerationError(f"scenario seed {scenario_seed}: no goal within {d.min}-{d.max} m of the start")
    goal = {"x": gx, "y": gy, "yaw": _yaw(rng)}
    return Scenario.model_validate({
        "schema_version": 1, "scenario_id": scenario_id, "seed": int(scenario_seed), "world": config.world,
        "time_limit_s": float(config.time_limit_s), "start": start, "goal": goal, "obstacles": obstacles, "faults": [],
    })


def generate_one(scenario_seed: int, config: GeneratorConfig, scenario_id: str) -> tuple[Scenario, dict[str, int]]:
    """The first feasible draw from an RNG seeded with ``scenario_seed``, and rejection counts by reason."""
    rng = np.random.default_rng(scenario_seed)
    a = arena(config.world)
    rejections = {reason: 0 for reason in REASONS}
    for _ in range(MAX_ATTEMPTS):
        candidate = _sample(rng, config, scenario_seed, scenario_id)
        grid = scenario_grid(candidate, a, config.robot_radius_m, config.clearance_m, config.grid_resolution_m)
        ok, reason = is_feasible(candidate, grid)
        if ok:
            return candidate, rejections
        rejections[reason] += 1
    raise GenerationError(f"scenario seed {scenario_seed}: no feasible scenario in {MAX_ATTEMPTS} attempts")


def scenario_seeds(seed: int, n: int) -> list[int]:
    """The per-Scenario seeds a set seed yields, in order."""
    rng = np.random.default_rng(seed)
    return [int(rng.integers(0, SEED_LIMIT)) for _ in range(n)]


def scenario_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def generate(seed: int, n: int, config: GeneratorConfig, prefix: str = "gen") -> GenerationResult:
    """Exactly ``n`` feasible Scenarios from ``seed``, with rejection counts by reason (Requirements 3.1-3.4)."""
    totals = {reason: 0 for reason in REASONS}
    scenarios = []
    for index, s in enumerate(scenario_seeds(seed, n)):
        scenario, rejections = generate_one(s, config, scenario_id(prefix, index))
        scenarios.append(scenario)
        for reason, count in rejections.items():
            totals[reason] += count
    return GenerationResult(seed=seed, scenarios=scenarios, rejections=totals)
