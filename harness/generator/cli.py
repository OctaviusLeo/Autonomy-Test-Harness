"""Scenario-set command line (Requirements 3.2, 3.4, 3.5, 5.6).

  python -m harness.generator.cli generate --config <yaml> --out <dir> --prefix <id prefix>
      One YAML file per Scenario (<scenario_id>.yaml) plus a stamped generation.json: command, set
      seed, commit, N, the Scenario ids and seeds, and rejection counts by reason.
  python -m harness.generator.cli regenerate --config <yaml> --seed <scenario seed> --id <scenario id> [--out <file>]
      That one Scenario from its own seed (stdout unless --out); the generation half of
      scripts/rerun_one.sh.
  python -m harness.generator.cli locate --config <yaml> --seed <scenario seed> [--root scenarios]
      Print the committed Scenario file with that seed in the set generated from <yaml>.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import repro
from harness.generator.generate import generate, generate_one, load_config
from harness.schema.validate import dump_scenario, load_scenario


def write_set(config_path: str, out: Path, prefix: str) -> dict:
    config = load_config(config_path)
    result = generate(config.seed, config.n, config, prefix=prefix)
    out.mkdir(parents=True, exist_ok=True)
    for scenario in result.scenarios:
        (out / f"{scenario.scenario_id}.yaml").write_text(dump_scenario(scenario), encoding="utf-8")
    record = {
        "config": config_path,
        "set_seed": config.seed,
        "n": config.n,
        "prefix": prefix,
        "scenarios": [{"scenario_id": s.scenario_id, "seed": s.seed} for s in result.scenarios],
        "rejections": result.rejections,
    }
    repro.write_stamped_json(out / "generation.json", record, repro.make_stamp(seed=config.seed))
    return record


def regenerate_text(config_path: str, seed: int, scenario_id: str) -> str:
    scenario, _ = generate_one(seed, load_config(config_path), scenario_id)
    return dump_scenario(scenario)


def locate(config_path: str, seed: int, root: Path) -> Path:
    """The committed Scenario file with ``seed`` in the set whose generation.json names ``config_path``."""
    wanted = Path(config_path).as_posix().removeprefix("./")
    for generation in sorted(root.glob("*/generation.json")):
        record = json.loads(generation.read_text(encoding="utf-8"))
        if Path(record["config"]).as_posix().removeprefix("./") != wanted:
            continue
        for entry in record["scenarios"]:
            if entry["seed"] == seed:
                path = generation.parent / f"{entry['scenario_id']}.yaml"
                load_scenario(path)  # must still be a valid Scenario
                return path
    raise LookupError(f"no committed Scenario with seed {seed} for {config_path} under {root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.generator.cli", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--config", required=True)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--prefix", required=True)
    r = sub.add_parser("regenerate")
    r.add_argument("--config", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--id", required=True)
    r.add_argument("--out", type=Path)
    loc = sub.add_parser("locate")
    loc.add_argument("--config", required=True)
    loc.add_argument("--seed", type=int, required=True)
    loc.add_argument("--root", type=Path, default=Path("scenarios"))
    args = parser.parse_args(argv)

    if args.command == "generate":
        record = write_set(args.config, args.out, args.prefix)
        print(f"generate: {record['n']} Scenarios in {args.out}; rejections {record['rejections']}")
    elif args.command == "regenerate":
        text = regenerate_text(args.config, args.seed, args.id)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    else:
        try:
            print(locate(args.config, args.seed, args.root))
        except LookupError as exc:
            print(f"locate: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
