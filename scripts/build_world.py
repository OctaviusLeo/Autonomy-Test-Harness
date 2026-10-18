"""Write the arena's Gazebo world and Nav2 map from harness/world/arena.py.

Usage: python scripts/build_world.py [--out <dir>]   (default: the repository root)
Writes <out>/worlds/empty_10x10.sdf and <out>/maps/empty_10x10.{pgm,yaml}.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.world.arena import arena, write_map, write_world_sdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the arena world SDF and map.")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    a = arena("empty_10x10")
    write_world_sdf(a, args.out / "worlds" / f"{a.world_id}.sdf")
    write_map(a, args.out / "maps" / f"{a.world_id}.pgm", args.out / "maps" / f"{a.world_id}.yaml")
    print(f"build_world: wrote {args.out / 'worlds'} and {args.out / 'maps'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
