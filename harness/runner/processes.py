"""Process-group helpers for the Runner: start with a log file, stop a group, find leftovers.

Every command the Runner starts gets its own process group, so stopping it reaches every child
(``ros2 launch`` starts many). Stopping sends SIGINT, waits up to 10 s, then sends SIGKILL.
After teardown, :func:`find_leftovers` lists any process whose command line names one of the
SUT's or the harness's programs, so the next Scenario never shares the machine with the last
(Requirement 5.2). The OS calls go through :class:`ProcessApi` so tests use fakes.
"""

from __future__ import annotations

import dataclasses
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

LEFTOVER_PATTERNS = (
    "gz sim",
    "parameter_bridge",
    "image_bridge",
    "component_container",
    "robot_state_publisher",
    "ros2",
    "injector_node",
    "gt_bridge",
)
STOP_GRACE_S = 10.0


@dataclasses.dataclass(frozen=True)
class ProcInfo:
    pid: int
    cmdline: str


def _list_processes() -> list[ProcInfo]:
    procs = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if raw:
            procs.append(ProcInfo(int(entry.name), raw.replace(b"\0", b" ").decode(errors="replace").strip()))
    return procs


def _ancestors(pid: int) -> set[int]:
    seen = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            break
        pid = int(stat.rsplit(")", 1)[1].split()[1])
    return seen


@dataclasses.dataclass
class ProcessApi:
    """The OS operations the Runner needs; replace any of them in tests."""

    popen: Callable[..., subprocess.Popen] = subprocess.Popen
    killpg: Callable[[int, int], None] = os.killpg
    kill: Callable[[int, int], None] = os.kill
    list_processes: Callable[[], list[ProcInfo]] = _list_processes
    protected_pids: Callable[[], set[int]] = lambda: _ancestors(os.getpid())
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def start_group(api: ProcessApi, cmd: Sequence[str], log_path: str | Path, env: dict | None = None,
                cwd: str | Path | None = None) -> subprocess.Popen:
    """Start ``cmd`` in a new process group, with stdout and stderr appended to ``log_path``."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 - the child owns the handle for its lifetime
    try:
        return api.popen(list(cmd), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         env=env, cwd=cwd, start_new_session=True)
    finally:
        log.close()


def stop_group(api: ProcessApi, proc: subprocess.Popen, grace_s: float = STOP_GRACE_S) -> str:
    """Stop ``proc``'s process group: SIGINT, then SIGKILL after ``grace_s``. Returns how it ended."""
    if proc.poll() is not None:
        _signal_group(api, proc.pid, signal.SIGKILL)  # children may outlive the leader
        return "exited"
    _signal_group(api, proc.pid, signal.SIGINT)
    deadline = api.monotonic() + grace_s
    while api.monotonic() < deadline:
        if proc.poll() is not None:
            _signal_group(api, proc.pid, signal.SIGKILL)
            return "interrupted"
        api.sleep(0.1)
    _signal_group(api, proc.pid, signal.SIGKILL)
    proc.wait()
    return "killed"


def _signal_group(api: ProcessApi, pgid: int, sig: int) -> None:
    try:
        api.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def find_leftovers(api: ProcessApi, patterns: Iterable[str] = LEFTOVER_PATTERNS) -> list[ProcInfo]:
    """Processes (other than this one and its ancestors) whose command line contains a pattern."""
    patterns = tuple(patterns)
    protected = api.protected_pids()
    return [p for p in api.list_processes()
            if p.pid not in protected and any(pat in p.cmdline for pat in patterns)]


def kill_leftovers(api: ProcessApi, patterns: Iterable[str] = LEFTOVER_PATTERNS,
                   settle_s: float = 5.0) -> list[ProcInfo]:
    """Kill every leftover and wait until none remain (up to ``settle_s``). Returns what was found."""
    found = find_leftovers(api, patterns)
    for proc in found:
        try:
            api.kill(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = api.monotonic() + settle_s
    while find_leftovers(api, patterns) and api.monotonic() < deadline:
        api.sleep(0.2)
    return found


def clean_shm(shm_dir: str | Path = "/dev/shm", prefixes: tuple[str, ...] = ("fastrtps_", "fast_datasharing", "sem.fastrtps")) -> int:
    """Remove Fast DDS shared-memory files left by the run. Returns how many were removed."""
    removed = 0
    base = Path(shm_dir)
    if not base.is_dir():
        return 0
    for entry in base.iterdir():
        if entry.name.startswith(prefixes):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed
