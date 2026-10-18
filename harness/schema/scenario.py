"""Scenario schema (pydantic v2): the versioned description of one test case.

Coordinate frame
----------------
Every pose in a Scenario (``start``, ``goal``, and each obstacle ``pose``) is in one frame: the
**map frame** (REP 105 ``map``). The arena's map is built so that map coordinates equal Gazebo
world coordinates, so the same numbers place the robot in Gazebo, seed AMCL, and judge the run.
Positions ``x``/``y`` are in meters and ``yaw`` in radians (Requirement 2.6).

Timing
------
A Fault's ``window`` is in seconds of simulation time after the goal is dispatched (``start_s`` is
inclusive, ``end_s`` exclusive). ``time_limit_s`` is also simulation seconds after dispatch.

Bounds enforced here (Requirement 2.4); any violation, wrong type, missing field, or unknown field
is rejected naming the field path:

- ``schema_version`` in ``{1}``; another value is rejected naming the version (Requirement 2.3);
- ``world`` in the supported set (``empty_10x10``);
- ``seed`` >= 0; ``scenario_id`` letters, digits, ``_``, ``.``, ``-``;
- ``time_limit_s`` > 0; obstacle sizes > 0;
- fault ``window.end_s`` > ``window.start_s`` >= 0;
- ``sigma_m`` >= 0; ``prob`` in [0, 1]; ``latency_ms`` in [0, 1000];
  sector ``width_deg`` in (0, 360] and ``center_deg`` in [0, 360).

The six Fault types are ``range_noise``, ``ray_dropout``, ``scan_dropout``, ``latency``,
``freeze``, and ``sector_blackout``. Odometry drift (Requirement 4.10) is not implemented
(design.md, "Fault models"), so ``odom_drift`` is rejected as an unknown ``type``.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.world.arena import SUPPORTED_WORLDS

# Supported Scenario schema versions; any other value is rejected naming the version (Req 2.3).
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})
FAULT_TYPES = ("range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout")

# Reject unknown fields (a misspelled key is an error, not silently ignored), reject values of the
# wrong type instead of coercing them (strict), and reject NaN and infinity.
_STRICT = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Pose(BaseModel):
    """A 2D pose in the map frame: meters for x/y, radians for yaw (Req 2.6)."""

    model_config = _STRICT

    x: float
    y: float
    yaw: float


# --------------------------------------------------------------------------- obstacles (by shape)
class BoxSize(BaseModel):
    """Box extents in meters; every dimension > 0."""

    model_config = _STRICT

    x: float = Field(gt=0)
    y: float = Field(gt=0)
    z: float = Field(gt=0)


class CylinderSize(BaseModel):
    """Cylinder extents in meters; radius and height > 0."""

    model_config = _STRICT

    radius: float = Field(gt=0)
    height: float = Field(gt=0)


class BoxObstacle(BaseModel):
    """A box obstacle: shape, size {x, y, z}, pose (Req 2.2)."""

    model_config = _STRICT

    shape: Literal["box"]
    size: BoxSize
    pose: Pose


class CylinderObstacle(BaseModel):
    """A cylinder obstacle: shape, size {radius, height}, pose (Req 2.2)."""

    model_config = _STRICT

    shape: Literal["cylinder"]
    size: CylinderSize
    pose: Pose


Obstacle = Annotated[Union[BoxObstacle, CylinderObstacle], Field(discriminator="shape")]


# --------------------------------------------------------------------------- fault window and params
class Window(BaseModel):
    """Seconds of simulation time after goal dispatch: active iff start_s <= t < end_s."""

    model_config = _STRICT

    start_s: float = Field(ge=0)
    end_s: float

    @model_validator(mode="after")
    def _check_order(self) -> "Window":
        if not self.end_s > self.start_s:
            raise ValueError(f"window.end_s ({self.end_s}) must be greater than window.start_s ({self.start_s})")
        return self


class RangeNoiseParams(BaseModel):
    """Gaussian range noise: ``sigma_m`` >= 0 (Req 4.4)."""

    model_config = _STRICT

    sigma_m: float = Field(ge=0)


class RayDropoutParams(BaseModel):
    """Per-ray dropout: ``prob`` in [0, 1] (Req 4.5)."""

    model_config = _STRICT

    prob: float = Field(ge=0, le=1)


class NoParams(BaseModel):
    """Whole-scan dropout and frozen scans take no params (Req 4.6, 4.8)."""

    model_config = _STRICT


class LatencyParams(BaseModel):
    """Added latency: ``latency_ms`` in [0, 1000] (Req 4.7)."""

    model_config = _STRICT

    latency_ms: float = Field(ge=0, le=1000)


class SectorBlackoutParams(BaseModel):
    """Blacked-out sector in the scan's own frame: ``center_deg`` in [0, 360), ``width_deg`` in (0, 360] (Req 4.9)."""

    model_config = _STRICT

    center_deg: float = Field(ge=0, lt=360)
    width_deg: float = Field(gt=0, le=360)


# --------------------------------------------------------------------------- faults (by type)
class RangeNoiseFault(BaseModel):
    model_config = _STRICT

    type: Literal["range_noise"]
    window: Window
    params: RangeNoiseParams


class RayDropoutFault(BaseModel):
    model_config = _STRICT

    type: Literal["ray_dropout"]
    window: Window
    params: RayDropoutParams


class ScanDropoutFault(BaseModel):
    model_config = _STRICT

    type: Literal["scan_dropout"]
    window: Window
    params: NoParams = Field(default_factory=NoParams)


class LatencyFault(BaseModel):
    model_config = _STRICT

    type: Literal["latency"]
    window: Window
    params: LatencyParams


class FreezeFault(BaseModel):
    model_config = _STRICT

    type: Literal["freeze"]
    window: Window
    params: NoParams = Field(default_factory=NoParams)


class SectorBlackoutFault(BaseModel):
    model_config = _STRICT

    type: Literal["sector_blackout"]
    window: Window
    params: SectorBlackoutParams


Fault = Annotated[
    Union[RangeNoiseFault, RayDropoutFault, ScanDropoutFault, LatencyFault, FreezeFault, SectorBlackoutFault],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- Scenario
class Scenario(BaseModel):
    """One versioned test case (Requirements 2.1-2.6). Field order here is the YAML key order."""

    model_config = _STRICT

    schema_version: int
    scenario_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    seed: int = Field(ge=0)
    world: str
    time_limit_s: float = Field(gt=0)
    start: Pose
    goal: Pose
    obstacles: list[Obstacle]
    faults: list[Fault]

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: int) -> int:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            supported = ", ".join(str(s) for s in sorted(SUPPORTED_SCHEMA_VERSIONS))
            raise ValueError(f"unsupported schema_version {v}; supported versions: {supported}")
        return v

    @field_validator("world")
    @classmethod
    def _check_world(cls, v: str) -> str:
        if v not in SUPPORTED_WORLDS:
            raise ValueError(f"unsupported world {v!r}; supported worlds: {', '.join(SUPPORTED_WORLDS)}")
        return v
