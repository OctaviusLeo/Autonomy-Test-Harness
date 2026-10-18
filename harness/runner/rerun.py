"""Re-run one Scenario alone from its seed (Requirement 5.6); the container half of scripts/rerun_one.sh.

It finds the committed Scenario with that seed in the set generated from ``--config``, regenerates it with
``generate_one``, refuses to continue unless the regenerated YAML equals the committed file byte for byte,
applies the experiment condition if one is given, and runs it alone with the same suite runner.

Usage (inside the image):
  python -m harness.runner.rerun --config config/generator.yaml --seed <seed> [--condition <name>] --out /results
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from harness import repro
from harness.generator.cli import locate, regenerate_text
from harness.runner import suite as suite_mod
from harness.runner.run_config import load_run_config
from harness.schema.validate import dump_scenario, load_scenario

REPO = Path(__file__).resolve().parents[2]


class RerunError(RuntimeError):
    pass


def prepare(config: str, seed: int, out_dir: Path, condition: str = "none", root: Path = REPO / "scenarios",
            experiment_config: Path = REPO / "config" / "experiment.yaml") -> Path:
    """Write the regenerated (and, for a Fault condition, faulted) Scenario under ``out_dir/scenarios``."""
    committed = locate(config, seed, root)
    scenario = load_scenario(committed)
    text = regenerate_text(config, seed, scenario.scenario_id)
    if text != committed.read_text(encoding="utf-8"):
        raise RerunError(f"regenerated {scenario.scenario_id} from seed {seed} differs from {committed}")
    if condition != "none":
        from harness.experiment.conditions import apply_condition, load_conditions

        text = dump_scenario(apply_condition(scenario, load_conditions(experiment_config)[condition]))
    dest = Path(out_dir) / "scenarios" / f"{scenario.scenario_id}.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def main(argv: list[str] | None = None, deps: suite_mod.SuiteDeps | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-run one Scenario alone from its seed.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--condition", default="none")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-config", type=Path, default=REPO / "config" / "run.yaml")
    args = parser.parse_args(argv)
    try:
        path = prepare(args.config, args.seed, args.out, args.condition)
    except (LookupError, RerunError) as exc:
        print(f"rerun: {exc}")
        return 1
    deps = deps or suite_mod.SuiteDeps()
    started = time.monotonic()
    records = suite_mod.run_suite([path], load_run_config(args.run_config), args.out, args.condition, 0, deps,
                                  args.run_config)
    suite_mod.write_suite("rerun", args.out, [(args.out, r) for r in records], time.monotonic() - started,
                          repro.make_stamp(seed=args.seed), deps, {"condition": args.condition})
    record = records[0]
    print(f"rerun: {record['scenario_id']} status={record['status']} verdict={(record['verdict'] or {}).get('passed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
