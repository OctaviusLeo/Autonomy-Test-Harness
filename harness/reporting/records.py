"""Reading and validating RunRecords for the reports (Requirement 7.5).

A report is generated only from inputs that all parse and carry the fields it needs; otherwise
:class:`ReportInputError` names the bad input and nothing is written.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

STATUSES = ("ok", "errored", "timed_out")


class ReportInputError(ValueError):
    """A report input is missing or unparsable; the message names it."""


def validate_record(record: Any, source: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ReportInputError(f"{source}: RunRecord is not a JSON object")
    for key, kind in (("scenario_id", str), ("seed", int), ("status", str), ("fault_condition", str)):
        if not isinstance(record.get(key), kind) or isinstance(record.get(key), bool):
            raise ReportInputError(f"{source}: field '{key}' is missing or not a {kind.__name__}")
    if record["status"] not in STATUSES:
        raise ReportInputError(f"{source}: field 'status' is {record['status']!r}, not one of {STATUSES}")
    verdict = record.get("verdict")
    if record["status"] != "errored":
        if not isinstance(verdict, dict) or not isinstance(verdict.get("passed"), bool):
            raise ReportInputError(f"{source}: field 'verdict' is missing or has no boolean 'passed'")
        if not verdict["passed"] and verdict.get("reason") not in ("collision", "timeout"):
            raise ReportInputError(f"{source}: field 'verdict.reason' must be collision or timeout for a failed run")
    stamp = record.get("stamp")
    if not isinstance(stamp, dict) or not {"command", "seed", "commit"} <= set(stamp):
        raise ReportInputError(f"{source}: field 'stamp' is missing command, seed, or commit")
    return record


def validate_records(records: Iterable[Any], sources: Iterable[str] | None = None) -> list[dict[str, Any]]:
    records = list(records)
    sources = list(sources) if sources is not None else [f"record {i}" for i in range(len(records))]
    if not records:
        raise ReportInputError("no RunRecords to report")
    if len(sources) != len(records):
        # zip() would silently drop the unmatched records, and with them runs from the report.
        raise ReportInputError(f"{len(records)} RunRecords but {len(sources)} sources")
    return [validate_record(r, s) for r, s in zip(records, sources)]


def load_records(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Read and validate RunRecord files; the first missing or unparsable one raises, naming its path."""
    records = []
    for path in map(Path, paths):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReportInputError(f"{path}: missing") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportInputError(f"{path}: unparsable ({exc})") from exc
        records.append(validate_record(data, str(path)))
    if not records:
        raise ReportInputError("no RunRecords to report")
    return records


def outcome(record: dict[str, Any]) -> str:
    """pass, fail (with a Verdict), errored, or timed_out."""
    if record["status"] == "errored":
        return "errored"
    if record["status"] == "timed_out":
        return "timed_out"
    return "pass" if record["verdict"]["passed"] else "fail"


def write_atomic(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def xml_text(value: Any) -> str:
    """``value`` as text that XML 1.0 allows: characters it forbids (most control characters) become '?'."""
    out = []
    for ch in str(value):
        code = ord(ch)
        allowed = (ch in "\t\n\r" or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF)
        out.append(ch if allowed else "?")
    return "".join(out)


def one_line(value: Any) -> str:
    """``value`` on a single line: every line break (including the ones str.splitlines honors) becomes a space."""
    return " ".join(xml_text(part).replace("\t", " ") for part in str(value).splitlines())