"""Tests for the README generator and the traceability check (harness/docs.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import docs

from conftest import DOCS_HASH as HASH
from conftest import write_file as write


@pytest.fixture
def repo(docs_repo) -> Path:
    return docs_repo


def test_build_fills_every_placeholder_from_results(repo, load_script):
    script = load_script("build_docs")
    assert script.main(["--repo", str(repo)]) == 0
    readme = (repo / "README.md").read_text()
    assert "{{" not in readme
    assert "| none | - | 27 of 30 (90.0%) | [0.7438, 0.9654] | - | - | 0 |" in readme
    assert "| latency | 5.0-65.0 | 15 of 30 (50.0%) | [0.3315, 0.6685] | 13 / 1 | 0.00183 | 0 |" in readme
    assert "Each fault starts 5.0 s after the goal is sent and lasts 60.0 s (latency)." in readme
    assert "In 1 run Nav2 reported `SUCCEEDED`" in readme and "`exp30-013` under latency (0.331 m)" in readme
    assert "Oracle's 0.3 m tolerance" in readme and "goal checker accepts 0.25 m" in readme
    assert "`exp30-008` under latency (minimum clearance -0.005 m)" in readme
    assert "`python scripts/paired_analysis.py`, seed 303" in readme
    assert "--out $ATH_SHARED/runs/m2`" in readme and "/home/u/" not in readme
    assert "Total run time: 9876.5 s (2.74 h) over 1 segment(s)" in readme
    assert f"commit `{HASH}`" in readme and "set seed 303" in readme
    assert "`latency` (latency_ms 300.0; window 5.0-65.0 s after dispatch)" in readme
    assert "footprint radius 0.18 m" in readme
    assert "repeat 1: 10 of 10" in readme and "every `fixed10` Scenario" in readme
    assert "measured delay 0.302 s" in readme and "0.1358 m from the goal" in readme
    assert "measured 2.0009 m (tolerance 0.05 m), 360 of 360 ranges finite" in readme
    assert "faults are models, not field data" in readme
    # Every line of the template without a placeholder (prose, license statement, commands) is kept verbatim.
    template = (repo / "docs" / "README.template.md").read_text()
    static = [line for line in template.splitlines() if line.strip() and "{{" not in line]
    assert [line for line in static if line not in readme] == []
    assert docs.untraceable(repo) == []
    script2 = load_script("check_traceability")
    assert script2.main(["--repo", str(repo)]) == 0


def test_untraceable_numbers_are_reported(repo, load_script):
    docs_text = docs.build(repo) + "\nA made-up rate of 0.8123 and 41 runs.\n"
    (repo / "README.md").write_text(docs_text)
    problems = docs.untraceable(repo)
    assert any("0.8123" in p for p in problems) and any(": 41 does not" in p for p in problems)
    assert load_script("check_traceability").main(["--repo", str(repo)]) == 1


def test_number_extraction_skips_urls_versions_and_ids():
    text = ("see http://127.0.0.1:8091/job/x/12/ and nav2_bringup 1.3.13-1noble.20261006, buildx v0.38.0, "
            "commit 06c1e05b, id exp30-004, rate 0.9667, -3.2 m, 95% and 8.103s")
    assert docs.numbers_in(text) == ["004", "0.9667", "3.2", "95"]


def test_selection_and_missing_inputs(repo):
    write(repo, "config/smoke_suite.yaml", "ids: [fixed10-001, fixed10-002]\n")
    assert "the smoke suite is fixed10-001, fixed10-002" in docs.build(repo)
    write(repo, "results/headless_render_check.txt", "garbled\n")
    with pytest.raises(ValueError, match="expected format"):
        docs.build(repo)
    (repo / "results/m0_baseline.json").unlink()
    with pytest.raises(FileNotFoundError, match="results/m0_baseline.json is missing"):
        docs.build(repo)
    with pytest.raises(KeyError, match="NOPE"):
        docs.render("{{NOPE}}", {})
