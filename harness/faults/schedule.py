"""Which Faults are active at a given time (pure; Requirement 4.2).

Times are seconds of simulation time after the goal was dispatched. Before dispatch (``t`` is
None) no Fault is active, so the stream passes through unchanged. Afterwards a Fault is active
iff ``window.start_s <= t < window.end_s``.
"""

from __future__ import annotations

from typing import Sequence

# The Runner publishes the goal-dispatch simulation time here (builtin_interfaces/Time, transient local).
DISPATCH_TOPIC = "/ath/goal_dispatch"


def is_active(window, t: float | None) -> bool:
    return t is not None and window.start_s <= t < window.end_s


def active_indices(faults: Sequence, t: float | None) -> list[int]:
    """Indices (Scenario order) of the Faults active at ``t``."""
    return [i for i, fault in enumerate(faults) if is_active(fault.window, t)]


def since_dispatch(now: float, dispatch: float | None) -> float | None:
    """Seconds since dispatch, or None before the dispatch time is known."""
    return None if dispatch is None else now - dispatch
