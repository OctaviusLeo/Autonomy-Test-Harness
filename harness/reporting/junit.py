"""JUnit XML report: one test case per Scenario run (Requirements 7.1, 7.4, 7.5, 9.4).

One ``<testsuite>`` per suite (or experiment condition) and one ``<testcase>`` per RunRecord, named by
``scenario_id`` with ``[condition]`` appended when the run had a Fault condition. A failed Verdict adds
``<failure message="collision|timeout">detail</failure>``; an errored run adds
``<error message="errored: <step>">effect</error>``; a run killed at the hard limit is a failure with reason
``timeout``. Inputs are validated first and the file is written to a temporary name and renamed, so a bad
input leaves no partial report.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from harness.reporting.records import outcome, validate_records, write_atomic, xml_text


def case_name(record: dict[str, Any]) -> str:
    condition = record["fault_condition"]
    return record["scenario_id"] if condition == "none" else f"{record['scenario_id']}[{condition}]"


def junit_xml(records: Iterable[dict[str, Any]], suite_name: str, sources: Iterable[str] | None = None) -> str:
    records = validate_records(records, sources)
    suite = ET.Element("testsuite", name=suite_name, tests=str(len(records)))
    failures = errors = 0
    total_time = 0.0
    for record in records:
        seconds = float(record.get("wall_time_s") or 0.0)
        total_time += seconds
        case = ET.SubElement(suite, "testcase", classname=f"ath.{suite_name}", name=case_name(record),
                             time=f"{seconds:.1f}")
        result = outcome(record)
        if result == "errored":
            errors += 1
            error = ET.SubElement(case, "error", message=xml_text(f"errored: {record.get('failing_step')}"))
            error.text = xml_text(record.get("effect") or "")
        elif result in ("fail", "timed_out"):
            failures += 1
            verdict = record["verdict"]
            failure = ET.SubElement(case, "failure", message=xml_text(verdict["reason"]))
            failure.text = xml_text(verdict.get("detail") or "")
        ET.SubElement(case, "system-out").text = xml_text(
            f"seed={record['seed']} bag={record.get('bag_path', '')} nav2_result={record.get('nav2_result', '')}")
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    suite.set("time", f"{total_time:.1f}")
    ET.indent(suite)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"


def write_junit(records: Iterable[dict[str, Any]], path: str | Path, suite_name: str,
                sources: Iterable[str] | None = None) -> Path:
    return write_atomic(path, junit_xml(records, suite_name, sources))
