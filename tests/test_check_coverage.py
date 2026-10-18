"""Unit tests for scripts/check_coverage.py (the Requirement 0.9 coverage rule)."""

from __future__ import annotations

import json
from pathlib import Path

TWO_PUBLIC = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
ONE_PUBLIC = "def a():\n    return 1\n\n\ndef _helper():\n    return 2\n"


def _report(entries: dict[str, tuple[int, int]]) -> dict:
    return {
        "files": {
            name: {"summary": {"num_statements": total, "covered_lines": covered}}
            for name, (covered, total) in entries.items()
        }
    }


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_counts_public_functions_and_methods(load_script):
    cc = load_script("check_coverage")
    source = "def a(): pass\ndef _b(): pass\nclass C:\n    def m(self): pass\n    def _n(self): pass\nclass _D:\n    def x(self): pass\n"
    assert cc.public_function_count(source) == 2


def test_source_lines_skip_blanks_and_comments(load_script):
    cc = load_script("check_coverage")
    assert cc.source_line_count("# c\n\nx = 1\n   # indented comment\ny = 2\n") == 2


def test_nontrivial_by_functions_or_length(load_script):
    cc = load_script("check_coverage")
    assert cc.is_nontrivial(TWO_PUBLIC)
    assert not cc.is_nontrivial(ONE_PUBLIC)
    assert cc.is_nontrivial("\n".join(f"x{i} = {i}" for i in range(51)))
    assert not cc.is_nontrivial("\n".join(f"x{i} = {i}" for i in range(50)))


def test_flags_nontrivial_module_under_threshold(load_script, tmp_path):
    cc = load_script("check_coverage")
    root = _tree(tmp_path, {"harness/low.py": TWO_PUBLIC, "harness/ok.py": TWO_PUBLIC, "scripts/tiny.py": ONE_PUBLIC})
    report = _report({"harness/low.py": (3, 5), "harness/ok.py": (4, 5), "scripts/tiny.py": (0, 3)})
    failures = cc.check(report, root)
    assert len(failures) == 1 and failures[0].startswith("harness/low.py: 60.0%")


def test_missing_module_counts_as_zero(load_script, tmp_path):
    cc = load_script("check_coverage")
    root = _tree(tmp_path, {"scripts/never_imported.py": TWO_PUBLIC})
    assert cc.check(_report({}), root) == ["scripts/never_imported.py: 0.0% statement coverage (needs 80%)"]


def test_absolute_paths_and_empty_modules(load_script, tmp_path):
    cc = load_script("check_coverage")
    root = _tree(tmp_path, {"harness/a.py": TWO_PUBLIC})
    report = _report({str((root / "harness/a.py").resolve()): (4, 5), "/elsewhere/x.py": (0, 9)})
    assert cc.check(report, root) == []
    assert cc.statement_percent({"summary": {"num_statements": 0, "covered_lines": 0}}) == 100.0


def test_main_exit_codes(load_script, tmp_path, capsys):
    cc = load_script("check_coverage")
    root = _tree(tmp_path, {"harness/a.py": TWO_PUBLIC})
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report({"harness/a.py": (5, 5)})))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report({"harness/a.py": (1, 5)})))
    assert cc.main([str(good), "--root", str(root)]) == 0
    assert cc.main([str(bad), "--root", str(root)]) == 1
    assert "harness/a.py" in capsys.readouterr().err
    assert cc.main([str(tmp_path / "missing.json"), "--root", str(root)]) == 2
