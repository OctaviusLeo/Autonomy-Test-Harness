"""One Scenario's lifecycle -> RunRecord (Requirements 5.1, 5.2, 5.4, 5.5, 5.7, 0.10).

Steps (design.md, "Runner design"):

1. **Isolate:** ``ROS_DOMAIN_ID`` 1 + run index mod 100, localhost-only discovery, ``GZ_PARTITION=ath_<index>``.
2. **Launch** the stock ``tb4_simulation_launch.py`` with the arena world and map, ``config/nav2_params_ath.yaml``,
   and the start pose. Ready means ``gz model --list`` lists the robot and ``/scan`` publishes; otherwise the
   run is errored at step ``launch``.
3. **Spawn** each obstacle with ``ros2 run ros_gz_sim create``; a failure or a model missing from the list is
   step ``spawn``.
4. **Start** the Ground_Truth reader, the Fault_Injector with the Scenario's Faults, and
   ``ros2 bag record --use-sim-time`` (MCAP, ``zstd_fast``) to ``bags/<scenario_id>/``.
5. **Initial pose** and Nav2 activation (step ``nav2_activate``).
6. **Goal** through ``NavigateToPose`` (step ``goal`` if rejected); on acceptance publish the dispatch time.
7. **Run** until the action finishes or ``time_limit_s`` of simulation time passes (then cancel), and record
   ``settle_s`` more simulation seconds.
8. **Teardown:** stop the recorder (so the bag is closed), the nodes, and the launch group; kill and record
   leftovers.
9. **Judge** from the bag's Ground_Truth (step ``ground_truth`` if there is none) and write
   ``run_record.json`` and ``verdict.json``.

Usage (inside the image; the suite runs it in a child process):
  python -m harness.runner.run_scenario --scenario <yaml> --out <dir> --run-index <n> [--condition <name>]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from harness import repro
from harness.oracle.judge import judge_trace
from harness.runner import session as session_mod
from harness.runner.run_config import RunConfig, load_run_config
from harness.runner.session import LaunchSpec, Session
from harness.schema.validate import load_scenario
from harness.world.arena import arena

REPO = Path(__file__).resolve().parents[2]
STEPS = ("launch", "spawn", "nav2_activate", "goal", "ground_truth")


class StepFailed(Exception):
    def __init__(self, step: str, effect: str) -> None:
        super().__init__(f"{step}: {effect}")
        self.step = step
        self.effect = effect


@dataclasses.dataclass
class RunnerDeps:
    """Everything the lifecycle touches outside its own logic; tests replace these."""

    make_session: Callable[[Path, dict], Session] = lambda out, env: Session(out, env)
    make_client: Callable[[str], Any] = None  # set by main(): nav_client.HarnessClient (needs rclpy)
    read_trace: Callable[[Path], Any] = None  # set by main(): bag_reader.read_trace (needs rosbag2_py)
    env: Callable[[], dict] = lambda: dict(os.environ)
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def bag_dir(out_dir: Path, scenario_id: str) -> Path:
    """Where a Scenario's bag lives: locatable from its id alone (Requirement 5.4)."""
    return Path(out_dir) / "bags" / scenario_id


def obstacle_sdf(obstacle, name: str) -> str:
    """A static model for one obstacle (box or cylinder), standing on the ground."""
    if obstacle.shape == "box":
        geometry = f"<box><size>{obstacle.size.x} {obstacle.size.y} {obstacle.size.z}</size></box>"
    else:
        geometry = f"<cylinder><radius>{obstacle.size.radius}</radius><length>{obstacle.size.height}</length></cylinder>"
    return (f'<?xml version="1.0"?>\n<sdf version="1.6"><model name="{name}"><static>true</static>'
            f'<link name="link"><collision name="collision"><geometry>{geometry}</geometry></collision>'
            f'<visual name="visual"><geometry>{geometry}</geometry>'
            f"<material><ambient>0.8 0.3 0.1 1</ambient><diffuse>0.8 0.3 0.1 1</diffuse></material>"
            f"</visual></link></model></sdf>\n")


def obstacle_height(obstacle) -> float:
    return obstacle.size.z if obstacle.shape == "box" else obstacle.size.height


def spawn_command(world: str, sdf_path: Path, name: str, obstacle) -> list[str]:
    p = obstacle.pose
    return ["ros2", "run", "ros_gz_sim", "create", "-world", world, "-file", str(sdf_path), "-name", name,
            "-x", f"{p.x}", "-y", f"{p.y}", "-z", f"{obstacle_height(obstacle) / 2}", "-Y", f"{p.yaw}"]


def bag_command(out: Path, topics: list[str]) -> list[str]:
    return ["ros2", "bag", "record", "--use-sim-time", "-s", "mcap", "--storage-preset-profile", "zstd_fast",
            "-o", str(out), *topics]


class ScenarioRun:
    def __init__(self, scenario, scenario_path: Path, cfg: RunConfig, out_dir: Path, run_index: int,
                 condition: str, deps: RunnerDeps, repo: Path = REPO, wiring: bool = False) -> None:
        self.scenario = scenario
        self.scenario_path = Path(scenario_path)
        self.cfg = cfg
        self.out_dir = Path(out_dir)
        self.run_index = run_index
        self.condition = condition
        self.deps = deps
        self.repo = Path(repo)
        self.wiring = wiring
        self.session: Session | None = None
        self.client = None
        self.nav2_result = "NOT_SENT"
        self.extra: dict[str, Any] = {}

    def scenario_dir(self) -> Path:
        return self.out_dir / "runs" / self.scenario.scenario_id

    def launch(self) -> None:
        s = self.scenario
        env = session_mod.isolation_env(self.deps.env(), self.run_index)
        self.session = self.deps.make_session(self.scenario_dir(), env)
        spec = LaunchSpec(str(self.repo / "worlds" / f"{s.world}.sdf"), str(self.repo / "maps" / f"{s.world}.yaml"),
                          str(self.repo / "config" / "nav2_params_ath.yaml"), s.start.x, s.start.y, s.start.yaw)
        self.session.start_launch(spec)
        end = self.deps.monotonic() + self.cfg.startup_timeout_s
        models: list[str] = []
        while self.deps.monotonic() < end and self.session.alive("launch"):
            models = self.session.models()
            if self.cfg.robot_name in models:
                break
            self.deps.sleep(2.0)
        if self.cfg.robot_name not in models:
            raise StepFailed("launch", f"{self.cfg.robot_name} not listed by gz model --list (saw {models})")
        self.client = self.deps.make_client(self.cfg.raw_scan_topic)
        if not self.client.wait_for_scan(1, max(end - self.deps.monotonic(), 10.0)):
            raise StepFailed("launch", f"no message on {self.cfg.raw_scan_topic}")

    def spawn(self) -> None:
        s = self.scenario
        names = []
        for k, obstacle in enumerate(s.obstacles):
            name = f"obs_{k}"
            sdf = self.scenario_dir() / "obstacles" / f"{name}.sdf"
            sdf.parent.mkdir(parents=True, exist_ok=True)
            sdf.write_text(obstacle_sdf(obstacle, name), encoding="utf-8")
            result = self.session.run(spawn_command(s.world, sdf, name, obstacle), timeout=60.0, env=self.session.env)
            if result.returncode != 0:
                raise StepFailed("spawn", f"create {name} exited {result.returncode}: {result.stderr.strip()[-300:]}")
            names.append(name)
        if names:
            models = self.session.models()
            missing = [n for n in names if n not in models]
            if missing:
                raise StepFailed("spawn", f"not listed after spawning: {missing}")

    def start_recording(self) -> None:
        s = self.scenario
        self.session.start_gt_bridge(s.world, self.cfg.robot_name)
        self.session.start("injector", [self.session.python, "-m", "harness.faults.injector_node",
                                        "--scenario", str(self.scenario_path),
                                        "--in-topic", self.cfg.raw_scan_topic, "--out-topic", self.cfg.faulted_scan_topic])
        bag = bag_dir(self.out_dir, s.scenario_id)
        bag.parent.mkdir(parents=True, exist_ok=True)
        self.session.start("bag", bag_command(bag, self.cfg.bag_topics))
        # The recorder and this client both subscribe to Ground_Truth; wait for both before dispatching.
        if not self.client.wait_for_subscribers(self.cfg.ground_truth_topic, 2, 30.0):
            raise StepFailed("launch", "the bag recorder did not subscribe to Ground_Truth within 30 s")

    def activate(self) -> None:
        c, s = self.client, self.scenario
        if not c.wait_for_clock(30.0):
            raise StepFailed("nav2_activate", "no /clock message within 30 s")
        if not c.wait_lifecycle_active(("lifecycle_manager_localization",), timeout_s=120.0):
            raise StepFailed("nav2_activate", "localization lifecycle manager not active within 120 s")
        if not c.set_initial_pose(s.start.x, s.start.y, s.start.yaw, timeout_s=60.0):
            raise StepFailed("nav2_activate", "AMCL did not report a pose near the initial pose within 60 s")
        if not c.wait_lifecycle_active(("lifecycle_manager_navigation",), timeout_s=120.0):
            raise StepFailed("nav2_activate", "navigation lifecycle manager not active within 120 s")

    def navigate(self) -> None:
        c, s = self.client, self.scenario
        handle = c.send_goal(s.goal.x, s.goal.y, s.goal.yaw, timeout_s=30.0)
        if handle is None:
            self.nav2_result = "REJECTED"
            raise StepFailed("goal", "NavigateToPose goal was not accepted within 30 s")
        dispatch = c.publish_dispatch()
        self.extra["dispatch_sim_time_s"] = round(dispatch, 3)
        if self.wiring:
            self.capture_wiring()
        self.nav2_result = c.wait_result(handle, dispatch, s.time_limit_s, wall_timeout_s=s.time_limit_s * 3)
        end = c.sim_time
        self.extra["result_sim_time_s"] = None if end is None else round(end - dispatch, 3)
        c.wait_sim_seconds(self.cfg.settle_s, wall_timeout_s=30.0)

    def capture_wiring(self) -> None:
        """Evidence that Nav2 reads the injector's output: graph API plus `ros2 topic info -v` (no daemon)."""
        wiring = self.scenario_dir() / "wiring"
        wiring.mkdir(parents=True, exist_ok=True)
        info = {t: self.client.subscriptions_info(t) for t in (self.cfg.faulted_scan_topic, self.cfg.raw_scan_topic)}
        (wiring / "subscriptions.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        for topic in (self.cfg.faulted_scan_topic, self.cfg.raw_scan_topic):
            result = self.session.run(["ros2", "topic", "info", "-v", "--no-daemon", "--spin-time", "10", topic],
                                      timeout=60.0, env=self.session.env)
            (wiring / f"topic_info{topic.replace('/', '_')}.txt").write_text(result.stdout + result.stderr,
                                                                             encoding="utf-8")

    def teardown(self) -> list[str]:
        if self.session is None:
            return []
        leftovers = self.session.teardown(order=("bag", "injector", "gt_bridge", "launch"))
        self.session = None
        return leftovers

    def judge(self):
        bag = bag_dir(self.out_dir, self.scenario.scenario_id)
        try:
            trace = self.deps.read_trace(bag)
        except Exception as exc:  # noqa: BLE001 - any unreadable bag is the ground_truth step failing
            raise StepFailed("ground_truth", f"cannot read bag {bag}: {exc}") from exc
        if not trace.ground_truth:
            raise StepFailed("ground_truth", "no Ground_Truth sample in the bag")
        try:
            return judge_trace(trace, self.scenario, arena(self.scenario.world), self.cfg.thresholds, self.nav2_result)
        except ValueError as exc:
            raise StepFailed("ground_truth", str(exc)) from exc

    def run(self, stamp: repro.Stamp) -> dict[str, Any]:
        started = self.deps.monotonic()
        status, failing_step, effect, verdict = "ok", None, None, None
        try:
            self.launch()
            self.spawn()
            self.start_recording()
            self.activate()
            self.navigate()
        except StepFailed as exc:
            status, failing_step, effect = "errored", exc.step, exc.effect
        except Exception as exc:  # noqa: BLE001 - a harness defect is recorded, never left running
            status, failing_step, effect = "errored", "harness", f"{type(exc).__name__}: {exc}"
        finally:
            if self.client is not None:
                self.client.close()
                self.client = None
            leftovers = self.teardown()
        if status == "ok":
            try:
                verdict = self.judge()
            except StepFailed as exc:
                status, failing_step, effect = "errored", exc.step, exc.effect
        record = {
            "scenario_id": self.scenario.scenario_id,
            "seed": self.scenario.seed,
            "fault_condition": self.condition,
            "run_index": self.run_index,
            "bag_path": str(bag_dir(self.out_dir, self.scenario.scenario_id)),
            "status": status,
            "failing_step": failing_step,
            "effect": effect,
            "nav2_result": self.nav2_result,
            "wall_time_s": round(self.deps.monotonic() - started, 1),
            "leftover_processes": leftovers,
            "verdict": None if verdict is None else verdict.to_dict(),
            **self.extra,
            "stamp": stamp.to_dict(),
        }
        out = self.scenario_dir()
        out.mkdir(parents=True, exist_ok=True)
        repro.write_text_atomic(out / "run_record.json", json.dumps(record, indent=2) + "\n")
        if verdict is not None:
            repro.write_text_atomic(out / "verdict.json", json.dumps(verdict.to_dict(), indent=2) + "\n")
        return record


def run_scenario(scenario, scenario_path: Path, run_config: RunConfig, out_dir: Path, run_index: int,
                 condition: str = "none", deps: RunnerDeps | None = None, stamp: repro.Stamp | None = None,
                 repo: Path = REPO, wiring: bool = False) -> dict[str, Any]:
    """Run one Scenario end to end and return its RunRecord (also written to disk)."""
    stamp = stamp or repro.make_stamp(seed=scenario.seed)
    return ScenarioRun(scenario, scenario_path, run_config, out_dir, run_index, condition, deps or RunnerDeps(),
                       repo, wiring).run(stamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Scenario end to end.")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-index", type=int, default=0)
    parser.add_argument("--condition", default="none")
    parser.add_argument("--run-config", type=Path, default=REPO / "config" / "run.yaml")
    parser.add_argument("--wiring", action="store_true", help="also save who subscribes to the scan topics")
    args = parser.parse_args(argv)
    os.environ.update(session_mod.isolation_env(os.environ, args.run_index))  # before rclpy reads ROS_DOMAIN_ID

    from harness.oracle import bag_reader
    from harness.runner import nav_client

    nav_client.init_ros()
    deps = RunnerDeps(make_client=lambda topic: nav_client.HarnessClient(scan_topic=topic),
                      read_trace=bag_reader.read_trace)
    record = run_scenario(load_scenario(args.scenario), args.scenario, load_run_config(args.run_config), args.out,
                          args.run_index, args.condition, deps, wiring=args.wiring)
    nav_client.shutdown_ros()
    print(f"run_scenario: {record['scenario_id']} status={record['status']} "
          f"verdict={(record['verdict'] or {}).get('passed')} nav2={record['nav2_result']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
