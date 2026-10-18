"""Enforce the coverage rule (Requirement 0.9) on a coverage.py JSON report.

A module in harness/ or scripts/ is non-trivial when it has more than one public function
(module-level functions plus public methods of module-level classes) or more than 50 source
lines (non-blank, non-comment). Every non-trivial module needs at least 80% statement
coverage; a module missing from the report counts as 0%.

Usage: python scripts/check_coverage.py runs/coverage.json [--root .]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

THRESHOLD_PERCENT = 80.0
MAX_TRIVIAL_LINES = 50
ROOTS = ("harness", "scripts")


def public_function_count(source: str) -> int:
    """Count module-level public functions and public methods of module-level classes."""
    tree = ast.parse(source)
    count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            count += 1
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
                    count += 1
    return count


def source_line_count(source: str) -> int:
    """Count lines that are neither blank nor comment-only."""
    return sum(1 for line in source.splitlines() if line.strip() and not line.strip().startswith("#"))


def is_nontrivial(source: str) -> bool:
    return public_function_count(source) > 1 or source_line_count(source) > MAX_TRIVIAL_LINES


def statement_percent(file_report: dict) -> float:
    summary = file_report["summary"]
    statements = summary["num_statements"]
    if statements == 0:
        return 100.0
    return 100.0 * summary["covered_lines"] / statements


def find_modules(root: Path) -> list[Path]:
    modules: list[Path] = []
    for top in ROOTS:
        base = root / top
        if base.is_dir():
            modules.extend(p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts)
    return modules


def check(report: dict, root: Path) -> list[str]:
    """Return one message per non-trivial module under the threshold."""
    files: dict[str, dict] = {}
    for name, data in report.get("files", {}).items():
        path = Path(name)
        if path.is_absolute():
            try:
                path = path.relative_to(root.resolve())
            except ValueError:
                continue
        files[path.as_posix()] = data

    failures = []
    for module in find_modules(root):
        rel = module.relative_to(root).as_posix()
        if not is_nontrivial(module.read_text(encoding="utf-8")):
            continue
        percent = statement_percent(files[rel]) if rel in files else 0.0
        if percent < THRESHOLD_PERCENT:
            failures.append(f"{rel}: {percent:.1f}% statement coverage (needs {THRESHOLD_PERCENT:.0f}%)")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"check_coverage: cannot read {args.coverage_json}: {exc}", file=sys.stderr)
        return 2
    failures = check(report, args.root)
    if failures:
        print("check_coverage: modules under the coverage rule:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"check_coverage: every non-trivial module in {', '.join(ROOTS)} is at or above {THRESHOLD_PERCENT:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
