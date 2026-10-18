"""Shared test helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    """Import scripts/<name>.py as a module (scripts/ is not a package)."""
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ath_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def load_script():
    return _load_script


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
