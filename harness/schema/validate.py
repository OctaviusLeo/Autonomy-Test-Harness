"""Load, validate, and write Scenarios as YAML.

``load_scenario(path)`` reads a YAML file and validates it against
:class:`~harness.schema.scenario.Scenario`. Every missing field, out-of-bound value, wrong type,
unknown field, unsupported world or Fault type, and unsupported schema version is reported in one
:class:`ScenarioValidationError` whose message names each offending field path (or the
unsupported version) (Requirements 2.3, 2.4, 2.5).

``dump_scenario(scenario)`` writes deterministic YAML: keys in the model's field order, floats
rounded to 4 decimals (and ``-0.0`` written as ``0.0``), so the same Scenario always gives the same
bytes (Requirement 3.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from harness.schema.scenario import Scenario

FLOAT_DECIMALS = 4


class ScenarioValidationError(Exception):
    """A scenario file cannot be read or fails validation; the message names the offending fields."""


def format_validation_error(source: str, error: ValidationError) -> str:
    lines = [f"invalid scenario '{source}':"]
    for err in error.errors():
        parts = [str(part) for part in err["loc"]]
        if err["type"] in ("union_tag_invalid", "union_tag_not_found"):
            # An unknown or missing Fault type / obstacle shape: name the tag field itself.
            parts.append(str(err.get("ctx", {}).get("discriminator", "")).strip("'"))
        loc = ".".join(parts) or "<root>"
        lines.append(f"  - field '{loc}': {err['msg']}")
    return "\n".join(lines)


def parse_scenario(data: Any, source: str = "<data>") -> Scenario:
    """Validate already-parsed YAML data; raise :class:`ScenarioValidationError` naming each bad field."""
    if not isinstance(data, dict):
        raise ScenarioValidationError(
            f"scenario '{source}' must be a YAML mapping at the top level, got {type(data).__name__}")
    try:
        return Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioValidationError(format_validation_error(source, exc)) from exc


def load_scenario(path: str | Path) -> Scenario:
    """Read and validate a scenario YAML file, returning a :class:`Scenario`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioValidationError(f"cannot read scenario '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScenarioValidationError(f"cannot parse scenario YAML '{path}': {exc}") from exc
    return parse_scenario(data, str(path))


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        r = round(value, FLOAT_DECIMALS)
        return 0.0 if r == 0 else r
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def scenario_data(scenario: Scenario) -> dict[str, Any]:
    """The Scenario as plain data with floats rounded the way :func:`dump_scenario` writes them."""
    return _rounded(scenario.model_dump(mode="python"))


def dump_scenario(scenario: Scenario) -> str:
    """Deterministic YAML for ``scenario``. Raises ValueError if rounding would make it invalid."""
    data = scenario_data(scenario)
    try:
        Scenario.model_validate(data)
    except ValidationError as exc:
        raise ValueError(format_validation_error(scenario.scenario_id, exc)) from exc
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=4096, allow_unicode=False)
