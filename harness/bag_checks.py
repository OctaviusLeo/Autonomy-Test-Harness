"""Checks on a recorded run's bag: is /scan_ath what the Fault_Injector should have published?

Each /scan_ath message keeps the header of the /scan message it came from (a frozen scan keeps the
header of the stored pre-window scan), so outputs are paired with inputs by header stamp. Times are
simulation seconds: header stamps and the bag's receive times (recorded with ``--use-sim-time``).

- :func:`passthrough_report` (M2): with no Fault, every paired output equals its input.
- :func:`fault_report` (M3): a Fault's effect stays inside its window (see its docstring for each type).
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


GUARD_S = 0.05  # scans this close to a window boundary are skipped: the injector and the recorder see slightly different times


def fault_report(raw: list[ScanMsg], out: list[ScanMsg], fault_type: str, window: tuple[float, float],
                 dispatch: float, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Are a Fault's effects confined to its window (simulation seconds after ``dispatch``)?

    Inputs are classified by their bag receive time. Outside the window every input must have exactly
    its own unchanged output. Inside it: range noise, ray dropout, and sector blackout change the ranges;
    whole-scan dropout publishes nothing; a frozen scan publishes only repeats of the last pre-window
    scan; latency publishes each input unchanged, later by the configured delay (within 20%).

    The recorder subscribes to /scan and /scan_ath as it discovers them, so it can start recording /scan
    up to about a second earlier; an input outside the window counts as missing its output only while
    /scan_ath was being recorded (between its first and last recorded message).
    """
    params = params or {}
    start, end = dispatch + window[0], dispatch + window[1]
    first_out = min((o.received for o in out), default=float("inf"))
    last_out = max((o.received for o in out), default=float("-inf"))

    def zone(t: float) -> str:
        if start + GUARD_S <= t < end - GUARD_S:
            return "inside"
        if t < start - GUARD_S or t >= end + GUARD_S:
            return "outside"
        return "edge"

    pairs = pair_by_stamp(raw, out)
    outside_scans = outside_changed = outside_missing = not_recorded = 0
    inside_scans = inside_changed = inside_published = 0
    delays: list[float] = []
    for r, outs in pairs:
        where = zone(r.received)
        if where == "outside":
            own = [o for o in outs if not start <= o.received < end]  # not a frozen repeat made inside the window
            if not own and not first_out - GUARD_S <= r.received <= last_out:
                not_recorded += 1  # /scan_ath was not being recorded yet (or any more)
                continue
            outside_scans += 1
            if not own:
                outside_missing += 1
            elif not same_ranges(r.ranges, own[0].ranges):
                outside_changed += 1
        elif where == "inside":
            inside_scans += 1
            inside_published += len(outs)
            if fault_type == "latency" and outs:
                delays.append(outs[0].received - r.received)
                inside_changed += int(not same_ranges(r.ranges, outs[0].ranges))
            elif outs:
                inside_changed += int(not same_ranges(r.ranges, outs[0].ranges))
    report: dict[str, Any] = {
        "fault": fault_type, "window_s": list(window), "dispatch_sim_time_s": round(dispatch, 3),
        "raw_scans": len(raw), "out_scans": len(out), "raw_before_or_after_out_recording": not_recorded,
        "outside_scans": outside_scans, "outside_changed": outside_changed, "outside_missing": outside_missing,
        "inside_scans": inside_scans, "inside_changed": inside_changed,
    }
    ok = outside_changed == 0 and outside_missing == 0 and inside_scans > 0
    if fault_type == "scan_dropout":
        published = sum(1 for o in out if zone(o.received) == "inside")
        report["outputs_published_inside"] = published
        ok = ok and published == 0 and inside_published == 0
    elif fault_type == "freeze":
        before = [r for r in raw if r.received < start]
        anchor = round(before[-1].stamp, 6) if before else None
        inside_outputs = [o for o in out if zone(o.received) == "inside"]
        repeats = sum(1 for o in inside_outputs if round(o.stamp, 6) == anchor)
        report.update(frozen_repeats=repeats, other_outputs_inside=len(inside_outputs) - repeats,
                      outputs_with_inside_stamps=inside_published)
        ok = ok and repeats > 0 and repeats == len(inside_outputs) and inside_published == 0
    elif fault_type == "latency":
        expected = float(params.get("latency_ms", 0.0)) / 1000.0
        measured = float(np.mean(delays)) if delays else float("nan")
        within = bool(delays) and abs(measured - expected) <= 0.2 * expected
        report.update(delayed_messages=len(delays), configured_delay_s=expected,
                      measured_delay_s=round(measured, 4) if delays else None,
                      min_delay_s=round(min(delays), 4) if delays else None, within_20_percent=within)
        ok = ok and within and inside_changed == 0
    else:
        ok = ok and inside_changed > 0
    report["confined_to_window"] = ok
    return report


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
