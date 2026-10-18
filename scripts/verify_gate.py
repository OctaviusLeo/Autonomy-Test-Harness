"""Run one milestone gate's file checks (harness/gates.py) and exit non-zero if any fails.

Usage: python scripts/verify_gate.py <m0|m1|m2|m3|m4|m5> [--repo <dir>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness import gates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone gate checks.")
    parser.add_argument("gate", choices=sorted(gates.CHECKS))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = gates.CHECKS[args.gate](args.repo)
    for problem in problems:
        print(f"verify_{args.gate}: FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"verify_{args.gate}: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
