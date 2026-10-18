"""Write config/nav2_params_ath.yaml from the installed stock nav2_params.yaml (run inside the image).

Usage: python scripts/make_nav2_params.py [--out-dir <dir>]   (default: the repository root)
Writes <out-dir>/config/nav2_params_ath.yaml and <out-dir>/docs/evidence/nav2_params_stock.yaml.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness import nav2_params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive the harness's Nav2 parameter file.")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--share-dir", type=Path, default=None, help="nav2_bringup share directory (default: installed)")
    args = parser.parse_args(argv)
    share = args.share_dir or nav2_params.stock_share_dir()
    out = args.out_dir / "config" / "nav2_params_ath.yaml"
    evidence = args.out_dir / "docs" / "evidence" / "nav2_params_stock.yaml"
    nav2_params.make(share, out, evidence)
    print(f"make_nav2_params: wrote {out} (stock copy {evidence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
