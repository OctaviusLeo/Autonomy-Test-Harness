"""Load and validate a Scenario from YAML with clear, field-level errors.

``load_scenario(path)`` reads a YAML file and validates it against the
:class:`~harness.schema.scenario.Scenario` model. Any missing field,
out-of-bound value, wrong type, or unsupported schema version is reported as a
:class:`ScenarioValidationError` whose message names the offending field path
(or the unsupported version value) so the failure is actionable
(Requirements 2.3, 2.4, 2.5).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from harness.schema.scenario import Scenario


class ScenarioValidationError(Exception):
    """Raised when a scenario file cannot be read or fails validation.

    The message names the offending field(s) or the unsupported schema version.
    """


def _format_validation_error(path: Path, error: ValidationError) -> str:
    lines = [f"invalid scenario '{path}':"]
    for err in error.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - field '{loc}': {err['msg']}")
    return "\n".join(lines)


def load_scenario(path: str | Path) -> Scenario:
    """Read and validate a scenario YAML file, returning a :class:`Scenario`.

    Raises :class:`ScenarioValidationError` on a missing file, unparsable YAML,
    a non-mapping document, or any schema violation. The error message names the
    offending field or, for an unsupported ``schema_version``, the version value.
    """
    path = Path(path)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioValidationError(f"cannot read scenario '{path}': {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScenarioValidationError(
            f"cannot parse scenario YAML '{path}': {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ScenarioValidationError(
            f"scenario '{path}' must be a YAML mapping at the top level, "
            f"got {type(data).__name__}"
        )

    try:
        return Scenario(**data)
    except ValidationError as exc:
        raise ScenarioValidationError(_format_validation_error(path, exc)) from exc
