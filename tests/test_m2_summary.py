"""Tests for scripts/m2_summary.py (the M2 fixed10 x3 summary)."""

from __future__ import annotations

import json
from pathlib import Path

HASH = "f" * 40
STAMP = {"command": "bash scripts/run_suite.sh smoke --repeat 3", "seed": 0, "commit": HASH}


def _record(sid, status="ok", passed=True, reason=""):
    verdict = None if status == "errored" else {"passed": passed, "reason": reason, "detail": "d"}
    return {"scenario_id": sid, "status": status, "failing_step": "spawn" if status == "errored" else None,
            "effect": "e", "verdict": verdict, "stamp": STAMP}


def _run(tmp_path: Path, outcomes: dict[int, list[dict]]) -> Path:
    run = tmp_path / "run"
    records = []
    for k, recs in outcomes.items():
        for r in recs:
            d = run / f"repeat_{k}" / "runs" / r["scenario_id"]
            d.mkdir(parents=True)
            (d / "run_record.json").write_text(json.dumps(r))
            if r["verdict"]:
                (d / "verdict.json").write_text(json.dumps(r["verdict"]))
            records.append(f"repeat_{k}/runs/{r['scenario_id']}/run_record.json")
    (run / "suite.json").write_text(json.dumps({"suite": "smoke", "scenario_ids": ["a", "b"], "records": records,
                                                "wall_time_s": 12.0, "stamp": STAMP}))
    return run


def test_summary_counts_and_changes(tmp_path, load_script, capsys):
    run = _run(tmp_path, {1: [_record("a"), _record("b")],
                          2: [_record("a"), _record("b", passed=False, reason="timeout")],
                          3: [_record("a", "timed_out", passed=False, reason="timeout"), _record("b", "errored")]})
    script = load_script("m2_summary")
    assert script.main(["--run", str(run), "--out", str(tmp_path / "out")]) == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert [r["passes"] for r in summary["per_repeat"]] == [2, 1, 0]
    assert summary["per_repeat"][1]["failures"][0]["reason"] == "timeout"
    assert summary["per_repeat"][2]["timed_out"] == ["a"] and summary["per_repeat"][2]["errored"][0]["failing_step"] == "spawn"
    assert summary["outcome_changed"] == ["a", "b"]
    assert summary["per_scenario"][0]["outcomes"] == ["pass", "pass", "timed_out"]
    assert summary["stamp"]["commit"] == HASH
    assert (tmp_path / "out" / "repeat_2" / "runs" / "b" / "verdict.json").exists()
    assert not (tmp_path / "out" / "repeat_3" / "runs" / "b" / "verdict.json").exists()
    assert "repeat 1: 2/2 passed" in capsys.readouterr().out
    # Re-running replaces the output directory.
    assert script.main(["--run", str(run), "--out", str(tmp_path / "out")]) == 0
