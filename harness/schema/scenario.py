"""Scenario schema (pydantic v2): the versioned description of one test case.

Coordinate frame
----------------
Every pose in a Scenario — ``start``, ``goal``, and each obstacle ``pose`` — is
expressed in a single documented frame: the **map frame** (REP 105 ``map``).
Positions ``x``/``y`` are in **meters** and ``yaw`` is in **radians**
(Requirement 2.6).

Bounds enforced here (Requirement 2.4):

- ``schema_version`` is a supported integer (supported set = ``{1}``); an
  unsupported value is rejected with an error that names the version (Req 2.3).
- ``time_limit_s`` > 0.
- obstacle sizes > 0 (box ``x``/``y``/``z``; cylinder ``radius``/``height``).
- fault ``window.end_s`` > ``window.start_s`` >= 0.
- fault params by type: ``sigma_m`` >= 0; ``prob`` in [0, 1];
  ``latency_ms`` in [0, 1000]; sector ``width_deg`` in (0, 360].

The six required fault types are ``range_noise``, ``ray_dropout``,
``scan_dropout``, ``latency``, ``freeze``, ``sector_blackout``; ``odom_drift`` is
optional (Requirement 4.3, 4.10).
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Supported Scenario schema versions. A value outside this set is rejected with an
# error naming the offending version (Requirement 2.3).
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

# Shared model config: reject unknown fields so a stray/misspelled key is caught
# as a field-level error rather than silently ignored (Requirement 2.4).
_STRICT = ConfigDict(extra="forbid")


class Pose(BaseModel):
    """A 2D pose in the map frame: meters for x/y, radians for yaw (Req 2.6)."""

    model_config = _STRICT

    x: float
    y: float
    yaw: float


# --------------------------------------------------------------------------- #
# Obstacles — discriminated on ``shape``.
# --------------------------------------------------------------------------- #
class BoxSize(BaseModel):
    """Box extents (meters); every dimension must be > 0."""

    model_config = _STRICT

    x: float = Field(gt=0)
    y: float = Field(gt=0)
    z: float = Field(gt=0)


class CylinderSize(BaseModel):
    """Cylinder extents (meters); radius and height must be > 0."""

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


Obstacle = Annotated[
    Union[BoxObstacle, CylinderObstacle],
    Field(discriminator="shape"),
]


# --------------------------------------------------------------------------- #
# Fault window and per-type params.
# --------------------------------------------------------------------------- #
class Window(BaseModel):
    """A fault's active window: ``end_s`` > ``start_s`` >= 0."""

    model_config = _STRICT

    start_s: float = Field(ge=0)
    end_s: float

    @model_validator(mode="after")
    def _check_order(self) -> "Window":
        if not self.end_s > self.start_s:
            raise ValueError(
                f"window.end_s ({self.end_s}) must be greater than "
                f"window.start_s ({self.start_s})"
            )
        return self


class RangeNoiseParams(BaseModel):
    """Gaussian range-noise params: ``sigma_m`` >= 0 (Req 4.4)."""

    model_config = _STRICT

    sigma_m: float = Field(ge=0)


class RayDropoutParams(BaseModel):
    """Per-ray dropout params: ``prob`` in [0, 1] (Req 4.5)."""

    model_config = _STRICT

    prob: float = Field(ge=0, le=1)


class ScanDropoutParams(BaseModel):
    """Whole-scan dropout takes no params (Req 4.6)."""

    model_config = _STRICT


class LatencyParams(BaseModel):
    """Added-latency params: ``latency_ms`` in [0, 1000] (Req 4.7)."""

    model_config = _STRICT

    latency_ms: float = Field(ge=0, le=1000)


class FreezeParams(BaseModel):
    """Frozen-scan fault takes no params (Req 4.8)."""

    model_config = _STRICT


class SectorBlackoutParams(BaseModel):
    """Sector-blackout params: ``width_deg`` in (0, 360]; ``center_deg`` free (Req 4.9)."""

    model_config = _STRICT

    center_deg: float
    width_deg: float = Field(gt=0, le=360)


class OdomDriftParams(BaseModel):
    """Optional odometry-drift params (Req 4.10)."""

    model_config = _STRICT

    drift_m_per_s: float = Field(ge=0)


# --------------------------------------------------------------------------- #
# Faults — discriminated on ``type``.
# --------------------------------------------------------------------------- #
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
    params: ScanDropoutParams = Field(default_factory=ScanDropoutParams)


class LatencyFault(BaseModel):
    model_config = _STRICT

    type: Literal["latency"]
    window: Window
    params: LatencyParams


class FreezeFault(BaseModel):
    model_config = _STRICT

    type: Literal["freeze"]
    window: Window
    params: FreezeParams = Field(default_factory=FreezeParams)


class SectorBlackoutFault(BaseModel):
    model_config = _STRICT

    type: Literal["sector_blackout"]
    window: Window
    params: SectorBlackoutParams


class OdomDriftFault(BaseModel):
    model_config = _STRICT

    type: Literal["odom_drift"]
    window: Window
    params: OdomDriftParams


Fault = Annotated[
    Union[
        RangeNoiseFault,
        RayDropoutFault,
        ScanDropoutFault,
        LatencyFault,
        FreezeFault,
        SectorBlackoutFault,
        OdomDriftFault,
    ],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Top-level Scenario.
# --------------------------------------------------------------------------- #
class Scenario(BaseModel):
    """One versioned test case (Requirements 2.1–2.6)."""

    model_config = _STRICT

    schema_version: int
    scenario_id: str
    seed: int
    world: str
    start: Pose
    goal: Pose
    obstacles: list[Obstacle]
    faults: list[Fault]
    time_limit_s: float = Field(gt=0)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: int) -> int:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            supported = ", ".join(str(s) for s in sorted(SUPPORTED_SCHEMA_VERSIONS))
            raise ValueError(
                f"unsupported schema_version {v}; supported versions: {supported}"
            )
        return v
