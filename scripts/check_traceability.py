"""Fail if a number in README.md or results/summary.md does not appear in a generated file under results/.

URLs, version strings (such as 1.3.13 or v0.38.0), and identifiers or hashes that mix digits and letters are
not treated as numbers. Logic in harness/docs.py.

Usage: python scripts/check_traceability.py [--repo .]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness import docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that every reported number comes from results/.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = docs.untraceable(args.repo)
    for problem in problems:
        print(f"check_traceability: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("check_traceability: every number in README.md and results/summary.md appears in a results file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
