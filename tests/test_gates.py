"""Tests for the milestone gate checks (harness/gates.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness import gates

HASH = "b" * 40


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def m0_repo(tmp_path, repo_root) -> Path:
    repo = tmp_path / "repo"
    for rel in (".gitignore", ".gitattributes", ".dockerignore"):
        _write(repo, rel, (repo_root / rel).read_text())
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo_root / rel, repo / rel)
    _write(repo, "results/m0_baseline.json", json.dumps({
        "nav2_result": "SUCCEEDED", "true_pose_to_goal_m": 0.12, "render": {"method": "egl"}, "failed_step": None,
        "stamp": {"command": "bash scripts/run_m0.sh", "seed": 0, "commit": HASH}}))
    _write(repo, "docs/evidence/a.txt", "x")
    _write(repo, "docs/ENVIRONMENT.md",
           "# Env\n## Versions\n| a | 1 | `docs/evidence/a.txt` |\n## M0 outcome\nok `results/m0_baseline.json`, "
           "image `ath-sim:<commit>`\n## Headless rendering\nEGL\n## Jenkins\nTBD later\n")
    _write(repo, ".kiro/specs/autonomy-test-harness/design.md",
           "text\n> **M0 outcome (filled):**\n> - done\n\nafter TBD\n")
    return repo


def _copy_regen(repo: Path, out: Path) -> None:
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "maps/empty_10x10.yaml",
                "config/nav2_params_ath.yaml", "docs/evidence/nav2_params_stock.yaml"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo / rel, out / rel)


def test_m0_gate_passes_on_a_complete_repo(m0_repo):
    assert gates.check_m0(m0_repo, regenerate=_copy_regen) == []


def test_m0_gate_reports_each_problem(m0_repo):
    _write(m0_repo, "results/m0_baseline.json", json.dumps({
        "nav2_result": "ABORTED", "true_pose_to_goal_m": 0.5, "render": {}, "failed_step": "goal",
        "stamp": {"command": "c", "seed": 0, "commit": "abc"}}))
    env = (m0_repo / "docs/ENVIRONMENT.md").read_text().replace("EGL", "TBD").replace("a.txt", "missing.txt")
    _write(m0_repo, "docs/ENVIRONMENT.md", env)
    _write(m0_repo, ".kiro/specs/autonomy-test-harness/design.md", "> **M0 outcome:**\n> - TBD\n")
    _write(m0_repo, ".gitattributes", "* text=auto eol=lf\n")

    def bad_regen(repo, out):
        _copy_regen(repo, out)
        (out / "maps/empty_10x10.yaml").write_text("changed")

    problems = "\n".join(gates.check_m0(m0_repo, regenerate=bad_regen))
    for fragment in ("not SUCCEEDED", "not at most 0.30", "no render method", "failed_step 'goal'",
                     "40-character", "'Headless rendering' still has TBD", "missing.txt does not exist",
                     "'M0 outcome' block still has TBD", "maps/empty_10x10.yaml differs", "*.png binary"):
        assert fragment in problems


def test_m0_gate_missing_files(tmp_path):
    problems = gates.check_m0(tmp_path, regenerate=lambda repo, out: None)
    text = "\n".join(problems)
    assert "cannot read JSON" in text and "ENVIRONMENT.md" in text and "no 'M0 outcome' block" in text
    assert ".gitignore: missing" in text


def test_stamp_check_and_helpers():
    problems: list[str] = []
    gates.check_stamp({"stamp": {"seed": 1}}, "x", problems)
    gates.check_stamp([], "y", problems)
    assert len(problems) == 2
    assert gates.markdown_section("## A\none\n## B\ntwo\n", "B").strip() == "two"
    assert gates.markdown_section("## A\n", "C") == ""
    assert gates.quoted_block("no block", "M0") == ""


def test_verify_gate_script(m0_repo, load_script, monkeypatch, capsys):
    script = load_script("verify_gate")
    monkeypatch.setitem(gates.CHECKS, "m0", lambda repo: gates.check_m0(repo, regenerate=_copy_regen))
    assert script.main(["m0", "--repo", str(m0_repo)]) == 0
    (m0_repo / "results/m0_baseline.json").unlink()
    assert script.main(["m0", "--repo", str(m0_repo)]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_real_regeneration_matches_committed_files(repo_root, tmp_path):
    gates.regenerate_m0_files(repo_root, tmp_path)
    for rel in ("worlds/empty_10x10.sdf", "maps/empty_10x10.pgm", "config/nav2_params_ath.yaml"):
        assert gates.same_bytes(repo_root / rel, tmp_path / rel)


@pytest.fixture
def m1_repo(tmp_path, repo_root, monkeypatch) -> tuple[Path, Path]:
    """A copy of the committed sets plus a fresh regeneration of both."""
    from harness.generator import cli

    monkeypatch.setenv("ATH_COMMIT", HASH)
    repo = tmp_path / "repo"
    shutil.copytree(repo_root / "scenarios", repo / "scenarios")
    regen = tmp_path / "regen"
    for name, config, _ in gates.SETS:
        prefix = json.loads((repo_root / "scenarios" / name / "generation.json").read_text())["prefix"]
        cli.write_set(config, regen / name, prefix)
    return repo, regen


def test_m1_gate_passes_on_the_committed_sets(m1_repo):
    repo, regen = m1_repo
    assert gates.check_m1(repo, regenerated_root=regen) == []


def test_m1_gate_reports_problems(m1_repo):
    repo, regen = m1_repo
    (repo / "scenarios/fixed10/fixed10-003.yaml").write_text((repo / "scenarios/fixed10/fixed10-003.yaml").read_text() + "# edit\n")
    (repo / "scenarios/fixed10/fixed10-000.yaml").write_text("schema_version: 2\n")
    (repo / "scenarios/experiment30/exp30-029.yaml").unlink()
    record = json.loads((repo / "scenarios/fixed10/generation.json").read_text())
    record["rejections"] = {"unreachable": 1}
    record["stamp"]["commit"] = "short"
    (repo / "scenarios/fixed10/generation.json").write_text(json.dumps(record))
    problems = "\n".join(gates.check_m1(repo, regenerated_root=regen))
    for fragment in ("fixed10-003.yaml: regenerated file differs", "fixed10-000.yaml: does not load",
                     "experiment30: 29 Scenario files", "regenerated set has different files",
                     "rejection counts by reason missing", "40-character", "regenerated record differs",
                     "regenerating fixed10-000 from seed"):
        assert fragment in problems


@pytest.fixture
def m2_repo(tmp_path, repo_root) -> tuple[Path, Path]:
    repo, shared = tmp_path / "repo", tmp_path / "shared" / "runs"
    shutil.copytree(repo_root / "scenarios" / "fixed10", repo / "scenarios" / "fixed10")
    _write(repo, "config/smoke_suite.yaml", "ids: all\n")
    ids = sorted(p.stem for p in (repo / "scenarios" / "fixed10").glob("*.yaml"))
    per_scenario = []
    for sid in ids:
        per_scenario.append({"scenario_id": sid, "outcomes": ["pass"] * 3, "changed_between_repeats": False,
                             "passed_all_repeats": True})
        for k in (1, 2, 3):
            bag = shared / "m2" / f"repeat_{k}" / "bags" / sid
            bag.mkdir(parents=True)
            d = repo / "results" / "m2_fixed10" / f"repeat_{k}" / "runs" / sid
            verdict = {"passed": True, "reason": ""}
            _write(repo, str((d / "run_record.json").relative_to(repo)), json.dumps({
                "scenario_id": sid, "status": "ok", "verdict": verdict, "leftover_processes": [], "bag_path": str(bag),
                "stamp": {"command": "bash scripts/run_suite.sh smoke --repeat 3", "seed": 1, "commit": HASH}}))
            _write(repo, str((d / "verdict.json").relative_to(repo)), json.dumps(verdict))
    _write(repo, "results/m2_fixed10/summary.json", json.dumps({
        "repeats": 3, "per_scenario": per_scenario, "stamp": {"command": "c", "seed": 0, "commit": HASH}}))
    _write(repo, "docs/evidence/m2_wiring/wiring_check.json", json.dumps({"ok": True, "checks": {"nav2_reads_scan_ath": True}}))
    return repo, shared


def test_m2_gate_passes(m2_repo):
    repo, shared = m2_repo
    assert gates.check_m2(repo, shared_runs=shared) == []


def test_m2_gate_reports_problems(m2_repo, monkeypatch):
    repo, shared = m2_repo
    rec_path = repo / "results/m2_fixed10/repeat_2/runs/fixed10-003/run_record.json"
    rec = json.loads(rec_path.read_text())
    rec.update(status="errored", failing_step="spawn", leftover_processes=["gz sim"])
    rec_path.write_text(json.dumps(rec))
    (rec_path.parent / "verdict.json").unlink()
    shutil.rmtree(shared / "m2" / "repeat_1" / "bags" / "fixed10-001")
    (repo / "results/m2_fixed10/repeat_3/runs/fixed10-009/run_record.json").unlink()
    summary = json.loads((repo / "results/m2_fixed10/summary.json").read_text())
    summary["per_scenario"][4]["passed_all_repeats"] = False
    (repo / "results/m2_fixed10/summary.json").write_text(json.dumps(summary))
    _write(repo, "docs/evidence/m2_wiring/wiring_check.json", json.dumps({"ok": False, "checks": {}}))
    text = "\n".join(gates.check_m2(repo, shared_runs=shared))
    for fragment in ("29 RunRecords", "status errored (spawn", "fixed10-003: no Verdict", "leftover processes",
                     "fixed10-001: bag", "not passing all three repeats: ['fixed10-004']", "m2_wiring"):
        assert fragment in text
    _write(repo, "config/smoke_suite.yaml", "ids: [fixed10-000]\n")
    assert "fewer than 8" in "\n".join(gates.check_m2(repo, shared_runs=shared))
    monkeypatch.delenv("ATH_SHARED", raising=False)
    assert "ATH_SHARED is not set" in "\n".join(gates.check_m2(repo))
    monkeypatch.setenv("ATH_SHARED", str(shared.parent))
    assert gates.shared_runs_dir() == shared


@pytest.fixture
def m3_repo(tmp_path, repo_root) -> Path:
    repo = tmp_path / "repo"
    for rel in ("config/experiment.yaml", "config/faults.yaml", ".kiro/specs/autonomy-test-harness/design.md"):
        _write(repo, rel, (repo_root / rel).read_text() if (repo_root / rel).exists() else gates.ODOM_DECISION)
    faults = [{"fault": t, "confined_to_window": True, "verdict": {"passed": True}}
              for t in ("range_noise", "ray_dropout", "scan_dropout", "latency", "freeze", "sector_blackout")]
    _write(repo, "results/m3_fault_check.json", json.dumps({"faults": faults, "stamp": {"command": "c", "seed": 0, "commit": HASH}}))
    return repo


def test_m3_gate_passes(m3_repo):
    assert gates.check_m3(m3_repo) == []


def test_m3_gate_reports_problems(m3_repo):
    data = json.loads((m3_repo / "results/m3_fault_check.json").read_text())
    data["faults"] = data["faults"][:5]
    data["faults"][0]["confined_to_window"] = False
    data["faults"][1]["verdict"] = None
    (m3_repo / "results/m3_fault_check.json").write_text(json.dumps(data))
    (m3_repo / ".kiro/specs/autonomy-test-harness/design.md").write_text("no decision here")
    (m3_repo / "config/experiment.yaml").write_text("conditions:\n  - name: none\n")
    text = "\n".join(gates.check_m3(m3_repo))
    for fragment in ("no entry for ['sector_blackout']", "range_noise is not confined", "ray_dropout has no Verdict",
                     "odometry-drift decision", "conditions ['none']"):
        assert fragment in text
    (m3_repo / "config/experiment.yaml").unlink()
    assert "config/experiment.yaml" in "\n".join(gates.check_m3(m3_repo))


@pytest.fixture
def m4_repo(tmp_path, repo_root) -> Path:
    from harness.reporting.junit import junit_xml
    from harness.reporting.summary import summary_markdown

    repo = tmp_path / "repo"
    shutil.copytree(repo_root / "scenarios" / "fixed10", repo / "scenarios" / "fixed10")
    _write(repo, "config/smoke_suite.yaml", "ids: all\n")
    _write(repo, "results/headless_render_check.txt", "Command: bash scripts/check_headless_render.sh\nResult: PASS\n")
    _write(repo, ".kiro/specs/autonomy-test-harness/design.md", "> **Headless-rendering outcome (filled):**\n> - EGL\n")
    stamp = {"command": "bash scripts/run_suite.sh smoke", "seed": 0, "commit": HASH}
    records = [{"scenario_id": sid, "seed": 1, "fault_condition": "none", "status": "ok",
                "verdict": {"passed": True, "reason": ""}, "stamp": stamp} for sid in gates.smoke_selection(repo)]
    _write(repo, "results/smoke/junit.xml", junit_xml(records, "smoke"))
    _write(repo, "results/smoke/summary.md", summary_markdown(records, "smoke", stamp))
    _write(repo, "results/smoke/suite.json", json.dumps({"suite": "smoke", "stamp": stamp}))
    return repo


def test_m4_gate_passes(m4_repo):
    assert gates.check_m4(m4_repo) == []


def test_m4_gate_reports_problems(m4_repo):
    _write(m4_repo, "results/headless_render_check.txt", "Result: FAIL\n")
    _write(m4_repo, ".kiro/specs/autonomy-test-harness/design.md", "> **Headless-rendering outcome:**\n> - TBD\n")
    junit = (m4_repo / "results/smoke/junit.xml").read_text()
    junit = junit.replace('name="fixed10-009" time="0.0">', 'name="fixed10-009" time="0.0"><failure message="timeout">x</failure>')
    junit = junit.replace('<testcase classname="ath.smoke" name="fixed10-000"', '<testcase classname="ath.smoke" name="other"')
    (m4_repo / "results/smoke/junit.xml").write_text(junit)
    (m4_repo / "results/smoke/summary.md").write_text("# no stamp\n")
    text = "\n".join(gates.check_m4(m4_repo))
    for fragment in ("does not show a PASS", "'Headless-rendering outcome'", "!= Smoke_Suite",
                     "failing or errored test cases ['fixed10-009']", "summary.md has no stamp"):
        assert fragment in text
    (m4_repo / "results/smoke/junit.xml").write_text("<testsuite")
    assert "does not parse" in "\n".join(gates.check_m4(m4_repo))
