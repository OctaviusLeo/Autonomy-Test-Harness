"""Checks on a recorded run's bag: is /scan_ath what the Fault_Injector should have published?

Each /scan_ath message keeps the header of the /scan message it came from (a frozen scan keeps the
header of the stored pre-window scan), so outputs are paired with inputs by header stamp. Times are
simulation seconds: header stamps and the bag's receive times (recorded with ``--use-sim-time``).

- :func:`passthrough_report` (M2): with no Fault, every paired output equals its input.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Iterable

import numpy as np

RAW, OUT = "/scan", "/scan_ath"


@dataclasses.dataclass(frozen=True)
class ScanMsg:
    stamp: float          # header stamp, simulation seconds
    received: float       # bag receive time, simulation seconds
    ranges: tuple[float, ...]


def to_scan(msg, recv_ns: int) -> ScanMsg:
    return ScanMsg(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, recv_ns * 1e-9, tuple(msg.ranges))


def read_scans(bag_path: str | Path) -> tuple[list[ScanMsg], list[ScanMsg]]:
    from harness.oracle.bag_reader import read_messages

    raw, out = [], []
    for topic, msg, t_ns in read_messages(bag_path, (RAW, OUT)):
        (raw if topic == RAW else out).append(to_scan(msg, t_ns))
    return raw, out


def same_ranges(a: Iterable[float], b: Iterable[float]) -> bool:
    """Element-wise equality where two infinities (or two NaNs) count as equal."""
    a, b = np.asarray(tuple(a), dtype=float), np.asarray(tuple(b), dtype=float)
    return a.shape == b.shape and bool(np.all((a == b) | (np.isnan(a) & np.isnan(b))))


def pair_by_stamp(raw: list[ScanMsg], out: list[ScanMsg]) -> list[tuple[ScanMsg, list[ScanMsg]]]:
    """Each input with every output that carries its header stamp."""
    by_stamp: dict[float, list[ScanMsg]] = {}
    for o in out:
        by_stamp.setdefault(round(o.stamp, 6), []).append(o)
    return [(r, by_stamp.get(round(r.stamp, 6), [])) for r in raw]


def passthrough_report(raw: list[ScanMsg], out: list[ScanMsg], edge: int = 2) -> dict[str, Any]:
    """With no Fault every output equals its input; only the first or last ``edge`` inputs may lack one
    (the recorder starts after the injector and stops before it)."""
    pairs = pair_by_stamp(raw, out)
    unmatched = [i for i, (_, outs) in enumerate(pairs) if not outs]
    inner_unmatched = [i for i in unmatched if edge <= i < len(pairs) - edge]
    differing = sum(1 for r, outs in pairs for o in outs if not same_ranges(r.ranges, o.ranges))
    return {
        "raw_scans": len(raw), "out_scans": len(out),
        "paired": len(pairs) - len(unmatched), "identical": sum(len(outs) for _, outs in pairs) - differing,
        "differing": differing, "unmatched_raw": len(unmatched), "unmatched_raw_inside": len(inner_unmatched),
        "ok": len(raw) > 0 and differing == 0 and not inner_unmatched,
    }


def ground_truth_count(bag_path: str | Path) -> int:
    from harness.oracle.bag_reader import read_ground_truth

    return len(read_ground_truth(bag_path))


NAV2_SCAN_READERS = ("/amcl", "/local_costmap/local_costmap", "/global_costmap/global_costmap", "/collision_monitor")


def wiring_report(subscriptions: dict[str, list[dict]], scans: tuple[list[ScanMsg], list[ScanMsg]],
                  gt_samples: int, record: dict[str, Any]) -> dict[str, Any]:
    """M2 wiring: Nav2 reads /scan_ath, /scan_ath equals /scan without Faults, Ground_Truth exists, no leftovers."""
    readers = sorted(s["node"] for s in subscriptions.get(OUT, []))
    missing = [n for n in NAV2_SCAN_READERS if n not in readers]
    raw_readers = sorted(s["node"] for s in subscriptions.get(RAW, []))
    nav2_on_raw = [n for n in NAV2_SCAN_READERS if n in raw_readers]
    passthrough = passthrough_report(*scans)
    checks = {
        "nav2_reads_scan_ath": not missing,
        "nav2_does_not_read_scan": not nav2_on_raw,
        "scan_ath_equals_scan": passthrough["ok"],
        "ground_truth_recorded": gt_samples > 0,
        "no_leftover_processes": record.get("status") == "ok" and not record.get("leftover_processes"),
    }
    return {
        "scenario_id": record.get("scenario_id"), "scan_ath_subscribers": readers, "scan_subscribers": raw_readers,
        "missing_nav2_readers": missing, "passthrough": passthrough, "ground_truth_samples": gt_samples,
        "run_status": record.get("status"), "leftover_processes": record.get("leftover_processes"),
        "checks": checks, "ok": all(checks.values()),
    }
