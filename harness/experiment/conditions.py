"""Experiment conditions: a base Scenario plus at most one Fault (Requirement 10.1).

``config/experiment.yaml`` names the seven conditions in run order (``none`` first, then one per Fault
type) with each Fault's window; parameters default to ``config/faults.yaml``. Every built Fault is
validated by the Scenario schema, so a condition outside the schema's bounds is rejected on load. The
values are fixed before any run and never changed to alter a result (Requirement 10.5).

  python -m harness.experiment.conditions write --base <scenario.yaml> --out <dir> [--suffix-ids]
      One file per condition (<out>/<condition>/<id>.yaml), or, with --suffix-ids, every variant in
      <out> itself with the condition appended to its id (<id>.<condition>.yaml) so they can run as one suite.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError

from harness.schema.scenario import FAULT_TYPES, Fault, Scenario
from harness.schema.validate import dump_scenario, load_scenario

REPO = Path(__file__).resolve().parents[2]
_FAULT = TypeAdapter(Fault)


@dataclasses.dataclass(frozen=True)
class Condition:
    name: str
    fault: Any  # a validated schema Fault, or None for the no-Fault condition


def load_fault_defaults(path: str | Path) -> dict[str, dict[str, float]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    unknown = sorted(set(data) - set(FAULT_TYPES))
    if unknown:
        raise ValueError(f"{path}: unknown Fault types {unknown}")
    return {kind: dict((spec or {}).get("params") or {}) for kind, spec in data.items()}


def load_conditions(path: str | Path = REPO / "config" / "experiment.yaml",
                    faults_path: str | Path | None = None) -> dict[str, Condition]:
    """The experiment's conditions in run order, each Fault validated against the schema's bounds."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = load_fault_defaults(faults_path or path.parent / "faults.yaml")
    conditions: dict[str, Condition] = {}
    for entry in data["conditions"]:
        name = entry["name"]
        if name in conditions:
            raise ValueError(f"{path}: condition {name!r} appears twice")
        if name == "none":
            conditions[name] = Condition(name, None)
            continue
        if name not in FAULT_TYPES:
            raise ValueError(f"{path}: condition {name!r} is not a Fault type")
        raw = {"type": name, "window": entry["window"], "params": {**defaults.get(name, {}), **(entry.get("params") or {})}}
        try:
            conditions[name] = Condition(name, _FAULT.validate_python(raw, strict=True))
        except ValidationError as exc:
            raise ValueError(f"{path}: condition {name!r}: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}") from exc
    return conditions


def apply_condition(scenario: Scenario, condition: Condition, suffix_id: bool = False) -> Scenario:
    """``scenario`` with the condition's one Fault added (``none`` returns it unchanged)."""
    if condition.fault is None:
        return scenario
    data = scenario.model_dump()
    data["faults"] = [*data["faults"], condition.fault.model_dump()]
    if suffix_id:
        data["scenario_id"] = f"{scenario.scenario_id}.{condition.name}"
    return Scenario.model_validate(data)


def write_variants(base: Path, out: Path, conditions: dict[str, Condition], suffix_ids: bool,
                   include_none: bool = True) -> list[Path]:
    scenario = load_scenario(base)
    written = []
    for name, condition in conditions.items():
        if name == "none" and not include_none:
            continue
        variant = apply_condition(scenario, condition, suffix_id=suffix_ids)
        path = out / f"{variant.scenario_id}.yaml" if suffix_ids else out / name / f"{variant.scenario_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_scenario(variant), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.experiment.conditions")
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write")
    w.add_argument("--base", type=Path, required=True)
    w.add_argument("--out", type=Path, required=True)
    w.add_argument("--conditions", type=Path, default=REPO / "config" / "experiment.yaml")
    w.add_argument("--suffix-ids", action="store_true")
    w.add_argument("--faults-only", action="store_true", help="skip the no-Fault condition")
    args = parser.parse_args(argv)
    written = write_variants(args.base, args.out, load_conditions(args.conditions), args.suffix_ids,
                             include_none=not args.faults_only)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
