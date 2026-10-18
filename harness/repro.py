"""Reproducibility stamp: the command, seed, and full commit hash recorded with every reported number.

Every script that writes a result calls :func:`make_stamp` and stores the stamp in the same file as
the numbers (Requirement 0.1). Inside the ath-sim image there is no ``.git``, so the host script that
starts a reported run first runs ``scripts/require_clean.sh`` (which refuses a dirty tree and prints
HEAD) and passes that hash in as ``ATH_COMMIT``; it may also pass the top-level command line as
``ATH_COMMAND`` so the stamp names the command a reader would actually type.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

_FULL_HASH = re.compile(r"^[0-9a-f]{40}$")


class CommitError(RuntimeError):
    """The commit hash is unavailable or not a full 40-character hash."""


def commit_hash(cwd: str | Path | None = None) -> str:
    """Return ``ATH_COMMIT`` when set, otherwise ``git rev-parse HEAD``; always 40 lowercase hex characters."""
    env_value = os.environ.get("ATH_COMMIT")
    if env_value is not None:
        if not _FULL_HASH.match(env_value):
            raise CommitError(f"ATH_COMMIT is not a full 40-character commit hash: {env_value!r}")
        return env_value
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True)
    value = result.stdout.strip()
    if result.returncode != 0 or not _FULL_HASH.match(value):
        raise CommitError(f"git rev-parse HEAD failed: {result.stderr.strip() or value!r}")
    return value


def command_line(argv: list[str] | None = None) -> str:
    """The command to record: ``ATH_COMMAND`` when the host script set it, else this process's argv."""
    return os.environ.get("ATH_COMMAND") or shlex.join(sys.argv if argv is None else argv)


@dataclasses.dataclass(frozen=True)
class Stamp:
    """Who made a number: the exact command, its seed, and the commit it ran from."""

    command: str
    seed: int
    commit: str

    def __post_init__(self) -> None:
        if not _FULL_HASH.match(self.commit):
            raise CommitError(f"stamp commit is not a full 40-character hash: {self.commit!r}")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Stamp":
        return cls(command=str(data["command"]), seed=int(data["seed"]), commit=str(data["commit"]))


def make_stamp(seed: int, command: str | None = None, cwd: str | Path | None = None) -> Stamp:
    """Build a stamp for this process: its command (or ``command``), ``seed``, and the commit hash."""
    return Stamp(command=command or command_line(), seed=int(seed), commit=commit_hash(cwd))


def stamp_json(obj: dict[str, Any], stamp: Stamp) -> str:
    """Serialize ``obj`` with its stamp under the ``stamp`` key, as indented JSON ending in a newline."""
    if "stamp" in obj:
        raise ValueError("object already has a 'stamp' key")
    return json.dumps({**obj, "stamp": stamp.to_dict()}, indent=2) + "\n"


def write_text_atomic(path: str | Path, text: str) -> Path:
    """Write ``text`` to a temporary file beside ``path`` and rename it into place."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_stamped_json(path: str | Path, obj: dict[str, Any], stamp: Stamp) -> Path:
    """Write ``obj`` plus its stamp to ``path`` atomically."""
    return write_text_atomic(path, stamp_json(obj, stamp))
