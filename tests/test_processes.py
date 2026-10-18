"""Tests for the Runner's process-group helpers (Requirement 5.2)."""

from __future__ import annotations

import signal
import subprocess
import time

from harness.runner import processes
from harness.runner.processes import ProcessApi, ProcInfo


def test_stop_group_interrupts_a_sleeping_group(tmp_path):
    api = ProcessApi()
    proc = processes.start_group(api, ["bash", "-c", "sleep 30 & sleep 30"], tmp_path / "logs" / "a.log")
    time.sleep(0.3)
    assert processes.stop_group(api, proc, grace_s=5) == "interrupted"
    assert proc.poll() is not None
    assert (tmp_path / "logs" / "a.log").exists()


def test_stop_group_kills_after_grace_when_sigint_is_ignored(tmp_path):
    api = ProcessApi()
    proc = processes.start_group(api, ["bash", "-c", "trap '' INT; sleep 30 & wait"], tmp_path / "b.log")
    time.sleep(0.3)
    started = time.monotonic()
    assert processes.stop_group(api, proc, grace_s=0.5) == "killed"
    assert time.monotonic() - started < 5
    assert proc.returncode == -signal.SIGKILL


def test_stop_group_on_an_exited_leader(tmp_path):
    api = ProcessApi()
    proc = processes.start_group(api, ["true"], tmp_path / "c.log")
    proc.wait()
    assert processes.stop_group(api, proc) == "exited"


def test_leftovers_found_and_killed_for_real(tmp_path):
    api = ProcessApi()
    proc = subprocess.Popen(["bash", "-c", "exec -a gt_bridge_leftover sleep 30"])
    time.sleep(0.3)
    found = processes.find_leftovers(api, patterns=("gt_bridge_leftover",))
    assert [p.pid for p in found] == [proc.pid]
    killed = processes.kill_leftovers(api, patterns=("gt_bridge_leftover",))
    assert [p.pid for p in killed] == [proc.pid]
    proc.wait(timeout=5)
    assert processes.find_leftovers(api, patterns=("gt_bridge_leftover",)) == []


def test_leftover_check_with_fakes_skips_protected_and_unmatched():
    killed = []
    table = [
        ProcInfo(10, "gz sim -r -s /tmp/w.sdf"),
        ProcInfo(11, "/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge --ros-args"),
        ProcInfo(12, "python -m harness.runner.suite"),
        ProcInfo(13, "python3 -c from ros2cli.daemon.daemonize import main --name ros2-daemon"),
        ProcInfo(1, "bash ros2 launch"),
    ]

    def lister():
        return [p for p in table if p.pid not in killed]

    clock = iter(range(100))
    api = ProcessApi(list_processes=lister, protected_pids=lambda: {1}, kill=lambda pid, sig: killed.append(pid),
                     monotonic=lambda: next(clock), sleep=lambda s: None)
    found = processes.kill_leftovers(api)
    assert [p.pid for p in found] == [10, 11, 13]
    assert killed == [10, 11, 13]


def test_kill_tolerates_vanished_processes():
    def gone(pid, sig):
        raise ProcessLookupError

    api = ProcessApi(list_processes=lambda: [ProcInfo(5, "injector_node")], protected_pids=set,
                     kill=gone, killpg=gone, monotonic=iter([0, 1, 100]).__next__, sleep=lambda s: None)
    assert [p.pid for p in processes.kill_leftovers(api, settle_s=2)] == [5]


def test_real_process_listing_and_ancestors():
    procs = processes._list_processes()
    assert any(p.cmdline for p in procs)
    import os

    assert os.getpid() in processes._ancestors(os.getpid())


def test_clean_shm(tmp_path):
    (tmp_path / "fastrtps_port7400").write_text("x")
    (tmp_path / "fast_datasharing_01").write_text("x")
    (tmp_path / "other").write_text("x")
    assert processes.clean_shm(tmp_path) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["other"]
    assert processes.clean_shm(tmp_path / "missing") == 0
