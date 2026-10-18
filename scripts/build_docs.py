"""Generate README.md from docs/README.template.md and the files under results/ (harness/docs.py).

Usage: python scripts/build_docs.py [--repo .] [--out README.md]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness import docs, repro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate README.md from results/.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or args.repo / "README.md"
    repro.write_text_atomic(out, docs.build(args.repo))
    print(f"build_docs: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
