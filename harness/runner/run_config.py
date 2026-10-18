"""RunConfig (config/run.yaml): Oracle thresholds, timeouts, topics, and the bag topic list.

These are fixed before any run and never changed to alter a result (Requirement 0.4).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.oracle.judge import Thresholds


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    footprint_radius_m: float = Field(gt=0)
    collision_threshold_m: float = Field(ge=0)
    goal_position_tol_m: float = Field(gt=0)
    goal_orientation_tol_rad: float = Field(gt=0)
    startup_timeout_s: float = Field(gt=0)
    settle_s: float = Field(ge=0)
    raw_scan_topic: str
    faulted_scan_topic: str
    ground_truth_topic: str
    robot_name: str
    bag_topics: list[str] = Field(min_length=1)

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(self.footprint_radius_m, self.collision_threshold_m,
                          self.goal_position_tol_m, self.goal_orientation_tol_rad)

    def hard_limit_s(self, time_limit_s: float) -> float:
        """The suite's wall-clock kill limit for one Scenario: startup + 3 x time limit + 60 s."""
        return self.startup_timeout_s + 3 * time_limit_s + 60


def load_run_config(path: str | Path) -> RunConfig:
    try:
        return RunConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except ValidationError as exc:
        fields = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors())
        raise ValueError(f"invalid run config '{path}': {fields}") from exc
