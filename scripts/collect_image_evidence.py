"""Write version and license evidence from inside the ath-sim image (harness/evidence.py does the work).

Usage: python scripts/collect_image_evidence.py [--out docs/evidence]
"""

from __future__ import annotations

import argparse
import platform
from pathlib import Path

from harness import evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect image version and license evidence.")
    repo = Path(__file__).resolve().parents[1]
    parser.add_argument("--out", type=Path, default=repo / "docs" / "evidence")
    args = parser.parse_args(argv)
    data = evidence.collect(repo, args.out, (repo / "docker" / "apt-pins.txt").read_text(encoding="utf-8"))
    (args.out / "image_python.txt").write_text(f"Python {platform.python_version()}\n", encoding="utf-8")
    print(f"collect_image_evidence: {len(data['apt'])} apt and {len(data['python'])} Python packages -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
