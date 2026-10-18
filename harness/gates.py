"""Milestone gate checks. Each ``check_mN(repo)`` returns a list of problems; an empty list passes.

``scripts/verify_mN.sh`` runs the unit tests and then ``python scripts/verify_gate.py mN`` inside the
image, which prints every problem and exits non-zero if there is one. The checks read only
committed or generated files, so a gate is one repository command whose exit status decides it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

FULL_HASH = re.compile(r"^[0-9a-f]{40}$")

GITIGNORE_ENTRIES = (".env", "*.env", "*.pem", "*.key", "*.token", "secrets.*", "runs/", "__pycache__/",
                     ".pytest_cache/", ".hypothesis/", ".coverage", "htmlcov/", ".venv/", "*.mcap", "*.db3")
GITATTRIBUTES_ENTRIES = ("* text=auto eol=lf", "*.png binary", "*.pgm binary")
DOCKERIGNORE_ENTRIES = (".git", "runs/", ".kiro/", "results/", "__pycache__/", ".pytest_cache/", ".hypothesis/")
EVIDENCE_PATH = re.compile(r"`((?:docs|results|docker|config|ci)/[^`\s]+|uv\.lock)`")


def load_json(path: Path, problems: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{path}: cannot read JSON ({exc})")
        return None


def check_stamp(data: Any, where: str, problems: list[str]) -> None:
    stamp = data.get("stamp") if isinstance(data, dict) else None
    if not isinstance(stamp, dict) or not stamp.get("command") or "seed" not in stamp:
        problems.append(f"{where}: missing stamp with command and seed")
    elif not FULL_HASH.match(str(stamp.get("commit", ""))):
        problems.append(f"{where}: stamp commit is not a full 40-character hash")


def markdown_section(text: str, heading: str) -> str:
    """The body of the ``## heading`` section (up to the next ``## ``)."""
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return match.group(1) if match else ""


def quoted_block(text: str, title_fragment: str) -> str:
    """The ``>`` block whose first line contains ``title_fragment``."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(">") and title_fragment in line:
            block = [line]
            for follow in lines[i + 1:]:
                if not follow.startswith(">"):
                    break
                block.append(follow)
            return "\n".join(block)
    return ""


def check_entries(path: Path, required: tuple[str, ...], problems: list[str]) -> None:
    try:
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    except OSError:
        problems.append(f"{path.name}: missing")
        return
    missing = [entry for entry in required if entry not in lines]
    if missing:
        problems.append(f"{path.name}: missing entries {missing}")


def check_ignore_files(repo: Path, problems: list[str]) -> None:
    check_entries(repo / ".gitignore", GITIGNORE_ENTRIES, problems)
    check_entries(repo / ".gitattributes", GITATTRIBUTES_ENTRIES, problems)
    check_entries(repo / ".dockerignore", DOCKERIGNORE_ENTRIES, problems)


def check_cited_paths(repo: Path, text: str, where: str, problems: list[str]) -> None:
    for cited in sorted(set(EVIDENCE_PATH.findall(text))):
        if "<" in cited or "*" in cited:
            continue  # a pattern such as ath-sim:<commit>, not a file
        if not (repo / cited.rstrip("/")).exists():
            problems.append(f"{where}: cited path {cited} does not exist")


def same_bytes(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


def regenerate_m0_files(repo: Path, out: Path) -> None:
    """Write the world, map, and Nav2 parameter file into ``out`` with the repository's own scripts."""
    from harness import nav2_params
    from harness.world.arena import arena, write_map, write_world_sdf

    a = arena("empty_10x10")
    write_world_sdf(a, out / "worlds" / "empty_10x10.sdf")
    write_map(a, out / "maps" / "empty_10x10.pgm", out / "maps" / "empty_10x10.yaml")
    nav2_params.make(nav2_params.stock_share_dir(), out / "config" / "nav2_params_ath.yaml",
                     out / "docs" / "evidence" / "nav2_params_stock.yaml")


def check_m0(repo: Path, regenerate: Callable[[Path, Path], None] = regenerate_m0_files) -> list[str]:
    problems: list[str] = []
    m0 = load_json(repo / "results" / "m0_baseline.json", problems)
    if isinstance(m0, dict):
        if m0.get("nav2_result") != "SUCCEEDED":
            problems.append(f"m0_baseline.json: nav2_result is {m0.get('nav2_result')!r}, not SUCCEEDED")
        dist = m0.get("true_pose_to_goal_m")
        if not isinstance(dist, (int, float)) or dist > 0.30:
            problems.append(f"m0_baseline.json: true_pose_to_goal_m {dist!r} is not at most 0.30 m")
        if not (m0.get("render") or {}).get("method"):
            problems.append("m0_baseline.json: no render method")
        if m0.get("failed_step") is not None:
            problems.append(f"m0_baseline.json: failed_step {m0.get('failed_step')!r}")
        check_stamp(m0, "m0_baseline.json", problems)

    env_text = _read(repo / "docs" / "ENVIRONMENT.md", problems)
    for heading in ("Versions", "M0 outcome", "Headless rendering"):
        section = markdown_section(env_text, heading)
        if not section.strip():
            problems.append(f"ENVIRONMENT.md: section '{heading}' missing or empty")
        elif "TBD" in section:
            problems.append(f"ENVIRONMENT.md: section '{heading}' still has TBD")
    check_cited_paths(repo, env_text, "ENVIRONMENT.md", problems)

    design = _read(repo / ".kiro" / "specs" / "autonomy-test-harness" / "design.md", problems)
    block = quoted_block(design, "M0 outcome")
    if not block:
        problems.append("design.md: no 'M0 outcome' block")
    elif "TBD" in block:
        problems.append("design.md: 'M0 outcome' block still has TBD")

    out = repo / "runs" / "gate_m0"
    regenerate(repo, out)
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        if not same_bytes(repo / rel, out / rel):
            problems.append(f"regenerated {rel} differs from the committed file")

    check_ignore_files(repo, problems)
    return problems


SETS = (("fixed10", "config/generator_smoke.yaml", 10), ("experiment30", "config/generator.yaml", 30))


def check_m1(repo: Path, regenerated_root: Path | None = None) -> list[str]:
    """Committed scenario sets: regenerate byte for byte, right counts, valid files, stamped records."""
    from harness.generator.cli import regenerate_text
    from harness.generator.feasibility import REASONS
    from harness.schema.validate import ScenarioValidationError, load_scenario

    problems: list[str] = []
    regenerated_root = regenerated_root or repo / "runs" / "gate_m1"
    for name, config, count in SETS:
        committed, again = repo / "scenarios" / name, regenerated_root / name
        files = sorted(p.name for p in committed.glob("*.yaml"))
        if len(files) != count:
            problems.append(f"scenarios/{name}: {len(files)} Scenario files, expected {count}")
        if sorted(p.name for p in again.glob("*.yaml")) != files:
            problems.append(f"scenarios/{name}: regenerated set has different files")
        for fname in files:
            if not same_bytes(committed / fname, again / fname):
                problems.append(f"scenarios/{name}/{fname}: regenerated file differs")
            try:
                load_scenario(committed / fname)
            except ScenarioValidationError as exc:
                problems.append(f"scenarios/{name}/{fname}: does not load ({exc})")
        record = load_json(committed / "generation.json", problems)
        regenerated = load_json(again / "generation.json", problems)
        if isinstance(record, dict):
            check_stamp(record, f"scenarios/{name}/generation.json", problems)
            if set(record.get("rejections", {})) != set(REASONS):
                problems.append(f"scenarios/{name}/generation.json: rejection counts by reason missing")
            if record.get("n") != count or len(record.get("scenarios", [])) != count:
                problems.append(f"scenarios/{name}/generation.json: N is not {count}")
            if isinstance(regenerated, dict) and {k: v for k, v in record.items() if k != "stamp"} != {
                    k: v for k, v in regenerated.items() if k != "stamp"}:
                problems.append(f"scenarios/{name}/generation.json: regenerated record differs (stamp aside)")
            first = (record.get("scenarios") or [None])[0]
            if first:
                text = regenerate_text(config, first["seed"], first["scenario_id"])
                path = committed / f"{first['scenario_id']}.yaml"
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    problems.append(f"scenarios/{name}: regenerating {first['scenario_id']} from seed {first['seed']} differs")
    return problems


def smoke_selection(repo: Path) -> list[str]:
    """The Smoke_Suite's Scenario ids: config/smoke_suite.yaml's ids, or every fixed10 Scenario for 'all'."""
    import yaml

    ids = (yaml.safe_load((repo / "config" / "smoke_suite.yaml").read_text(encoding="utf-8")) or {}).get("ids", "all")
    if ids == "all":
        return sorted(p.stem for p in (repo / "scenarios" / "fixed10").glob("*.yaml"))
    return list(ids)


def check_run_records(records: list[tuple[Path, dict]], shared_runs: Path | None, where: str,
                      problems: list[str], allow_failed_verdicts: bool = True) -> None:
    for path, record in records:
        name = f"{where}/{path.parent.name}"
        check_stamp(record, name, problems)
        if record.get("status") != "ok":
            problems.append(f"{name}: status {record.get('status')} ({record.get('failing_step')}: {record.get('effect')})")
        if not record.get("verdict") or not (path.parent / "verdict.json").exists():
            problems.append(f"{name}: no Verdict")
        if record.get("leftover_processes"):
            problems.append(f"{name}: leftover processes {record['leftover_processes']}")
        if shared_runs is not None:
            bag = Path(str(record.get("bag_path", "")))
            if not bag.is_relative_to(shared_runs) or not bag.exists():
                problems.append(f"{name}: bag {bag} does not exist under {shared_runs}")


def shared_runs_dir() -> Path | None:
    import os

    shared = os.environ.get("ATH_SHARED")
    return Path(shared) / "runs" if shared else None


def check_m2(repo: Path, shared_runs: Path | None = None) -> list[str]:
    problems: list[str] = []
    shared_runs = shared_runs if shared_runs is not None else shared_runs_dir()
    if shared_runs is None:
        problems.append("ATH_SHARED is not set, so the bags cannot be checked (run through verify_m2.sh)")
    out = repo / "results" / "m2_fixed10"
    paths = sorted(out.glob("repeat_*/runs/*/run_record.json"))
    if len(paths) != 30:
        problems.append(f"results/m2_fixed10: {len(paths)} RunRecords, expected 30 (10 Scenarios x 3 repeats)")
    records = [(p, load_json(p, problems)) for p in paths]
    check_run_records([(p, r) for p, r in records if isinstance(r, dict)], shared_runs, "results/m2_fixed10", problems)
    summary = load_json(out / "summary.json", problems)
    if isinstance(summary, dict):
        check_stamp(summary, "results/m2_fixed10/summary.json", problems)
        selection = smoke_selection(repo)
        if len(selection) < 8:
            problems.append(f"Smoke_Suite selection has {len(selection)} Scenarios, fewer than 8")
        passed = {s["scenario_id"] for s in summary.get("per_scenario", []) if s.get("passed_all_repeats")}
        failing = [sid for sid in selection if sid not in passed]
        if failing or summary.get("repeats") != 3:
            problems.append(f"Smoke_Suite Scenarios not passing all three repeats: {failing}")
    wiring = load_json(repo / "docs" / "evidence" / "m2_wiring" / "wiring_check.json", problems)
    if isinstance(wiring, dict) and not (wiring.get("ok") and wiring.get("checks", {}).get("nav2_reads_scan_ath")):
        problems.append("docs/evidence/m2_wiring: Nav2 is not shown subscribed to /scan_ath")
    return problems


CONDITION_ORDER = ["none", "range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout"]
ODOM_DECISION = "**Odometry drift (Requirement 4.10): not implemented.**"


def check_m3(repo: Path) -> list[str]:
    from harness.experiment.conditions import load_conditions
    from harness.schema.scenario import FAULT_TYPES
    from harness.schema.validate import ScenarioValidationError, parse_scenario

    problems: list[str] = []
    result = load_json(repo / "results" / "m3_fault_check.json", problems)
    if isinstance(result, dict):
        check_stamp(result, "results/m3_fault_check.json", problems)
        entries = {e.get("fault"): e for e in result.get("faults", [])}
        missing = [t for t in FAULT_TYPES if t not in entries]
        if missing:
            problems.append(f"results/m3_fault_check.json: no entry for {missing}")
        for kind, entry in entries.items():
            if not entry.get("confined_to_window"):
                problems.append(f"results/m3_fault_check.json: {kind} is not confined to its window")
            if not isinstance(entry.get("verdict"), dict):
                problems.append(f"results/m3_fault_check.json: {kind} has no Verdict")
    design = _read(repo / ".kiro" / "specs" / "autonomy-test-harness" / "design.md", problems)
    if ODOM_DECISION not in design:
        problems.append("design.md does not record the odometry-drift decision")
    example = {"schema_version": 1, "scenario_id": "g-000", "seed": 0, "world": "empty_10x10", "time_limit_s": 90.0,
               "start": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "goal": {"x": 1.0, "y": 1.0, "yaw": 0.0}, "obstacles": [],
               "faults": [{"type": "odom_drift", "window": {"start_s": 1.0, "end_s": 2.0}, "params": {}}]}
    try:
        parse_scenario(example)
        problems.append("the schema accepts odom_drift")
    except ScenarioValidationError as exc:
        if "faults.0.type" not in str(exc):
            problems.append(f"the odom_drift rejection does not name the type field: {exc}")
    try:
        conditions = load_conditions(repo / "config" / "experiment.yaml")
        if list(conditions) != CONDITION_ORDER:
            problems.append(f"config/experiment.yaml: conditions {list(conditions)}, expected {CONDITION_ORDER}")
    except (OSError, ValueError, KeyError) as exc:
        problems.append(f"config/experiment.yaml: {exc}")
    return problems


def _read(path: Path, problems: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        problems.append(f"{path}: missing")
        return ""


CHECKS: dict[str, Callable[[Path], list[str]]] = {"m0": check_m0, "m1": check_m1, "m2": check_m2, "m3": check_m3}
