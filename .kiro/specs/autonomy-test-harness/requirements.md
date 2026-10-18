# Requirements Document

## Introduction

Autonomy Test Harness is a scenario-based test system that drives a ROS 2 Jazzy navigation robot in Gazebo Harmonic through randomized scenarios, injects sensor faults on a schedule, judges each run pass or fail from simulator ground truth, and runs headless in Docker under a Jenkins pipeline. The system under test is Nav2 with its minimal TurtleBot simulation for Jazzy; the harness tests Nav2 but does not change Nav2's algorithms. The project is portfolio evidence for verification and validation, simulation test, and integration roles, so every reported number must be reproducible from a script in this repository, and every third-party dependency must be proven on the target machine and license-checked.

The work is organized into milestones M0 through M5, each ending in an automated verification gate (a repository command whose exit status decides pass or fail). M0 proves the Nav2 TurtleBot simulation runs headless and reaches one goal sent from a script. M1 delivers the scenario schema, the generator, and their tests. M2 delivers the runner and oracle on 10 fixed scenarios without faults. M3 delivers the fault-injection node with tests. M4 delivers the reports and the Docker image. M5 delivers the Jenkins pipeline, the paired experiment, and the README, and is the primary acceptance gate (Gate A).

This document defines the requirements only. The exact Nav2 package set, the headless-rendering method inside Docker, the scenario-generation algorithm, and all other implementation details are deferred to the design phase.

## Glossary

- **System**: The complete Autonomy Test Harness, comprising the scenario schema, the generator, the fault-injection node, the runner, the oracle, the reports, and the CI configuration.
- **SUT**: The System Under Test — Nav2 and its minimal TurtleBot simulation for ROS 2 Jazzy, driven through the `NavigateToPose` action. The System tests the SUT and does not modify the SUT's algorithms.
- **Nav2**: The ROS 2 Navigation 2 stack (apt packages `ros-jazzy-navigation2`, `ros-jazzy-nav2-bringup`, and the `ros-jazzy-nav2-minimal-tb*` simulation packages).
- **Simulation**: One Gazebo Harmonic instance running headless with the TurtleBot model and the scenario world.
- **Scenario**: A single versioned description of one test case: world, start pose, goal pose, obstacles, faults with timing, time limit, and random seed.
- **Scenario_Schema**: The versioned YAML schema that defines the structure and bounds of a Scenario.
- **Generator**: The component that produces N Scenarios from a single seed with randomized obstacles, start poses, and goal poses, rejecting infeasible ones.
- **Infeasible_Scenario**: A Scenario whose start pose lies inside an obstacle, or whose goal pose is unreachable on the map, or whose start or goal lies off the map.
- **Fault_Injector**: The ROS 2 node placed between the simulated sensors and Nav2 that applies sensor faults on a schedule.
- **Fault**: A scheduled modification of a sensor stream: lidar range noise, per-ray dropout, whole-scan dropout, added latency, frozen scans, a blacked-out sector, or (optional) odometry drift.
- **Runner**: The component that, for each Scenario, starts a clean headless Simulation, spawns obstacles, sends the goal through Nav2's `NavigateToPose` action, records a ROS_Bag, enforces a hard timeout, and tears everything down.
- **Oracle**: The component that judges each run pass or fail from Ground_Truth and records the verdict, metrics, and failure reason.
- **Ground_Truth**: The noise-free state the Simulation knows exactly: the true robot pose, the true obstacle poses, and contact-sensor state, obtained from the simulator and not from the robot's own estimate.
- **Verdict**: The pass-or-fail judgment the Oracle assigns to a run, with the metrics and the reason for any failure.
- **Collision**: A run condition in which the robot footprint is closer to an obstacle than a configured threshold, or a contact sensor reports contact, as determined from Ground_Truth.
- **Goal_Reached**: A run condition in which the robot's true pose is within the configured position and orientation tolerance of the goal pose.
- **Time_To_Goal**: The elapsed simulation time from goal dispatch to Goal_Reached.
- **ROS_Bag**: A ROS 2 bag recording of the topics for one run.
- **JUnit_Report**: The JUnit XML report in which each Scenario appears as one test case so Jenkins displays per-scenario results.
- **Summary_Report**: The generated Markdown or HTML summary with pass rate per Fault type, failure reasons, and a link to the ROS_Bag for each failed run.
- **Smoke_Suite**: The subset of about 10 Scenarios run on every change in CI.
- **Full_Suite**: The complete set of Scenarios run nightly in CI.
- **Paired_Experiment**: The experiment that runs the same set of at least 30 Scenarios with no Fault and under each Fault type, so differences come from the Fault alone.
- **Confidence_Interval**: A 95% confidence interval reported for a pass rate in the Paired_Experiment.
- **Gate_A**: The M5 acceptance gate: the Jenkins pipeline builds the image, runs unit tests and the Smoke_Suite on a change, the Paired_Experiment runs end to end, and the README reports its results.
- **Measured_Value**: A number produced by a script in this repository, recorded with its command, seed, and full commit hash.
- **Configured_Value**: A parameter value set in a Scenario or Fault configuration before a run.
- **ENVIRONMENT_Doc**: The file `docs/ENVIRONMENT.md` recording exact tool and dependency versions proven on the machine.
- **THIRD_PARTY_Doc**: The file `THIRD_PARTY.md` recording each third-party dependency and its license.

## Requirements

### Requirement 0: Governing non-functional requirements

**User Story:** As the repository owner, I want every result reproducible and every dependency proven and license-checked, so that I can defend every line of the project in an interview.

#### Acceptance Criteria

1. WHERE a number is reported in the README, in `docs/`, or in a Summary_Report, THE System SHALL produce that number from a script in this repository and SHALL record, in the same document and within the same section as the number, the generating command, the seed, and the full commit hash.
2. WHERE a System component uses randomness, THE System SHALL expose a configurable seed through a documented configuration parameter.
3. WHEN two runs of the Generator execute with the same seed and the same configuration, THE Generator SHALL produce byte-for-byte identical Scenarios, excluding timestamps and absolute file paths.
4. IF a run fails or misses a stated target, THEN THE System SHALL report, in the run output, the actual result and the identified cause, and SHALL leave the stated target and the test unchanged.
5. THE System SHALL record, in the ENVIRONMENT_Doc, the exact version string of every tool, package, and dependency it relies on, including the operating system, ROS 2 Jazzy, Gazebo Harmonic, and the Nav2 packages.
6. WHEN a dependency version is recorded in the ENVIRONMENT_Doc, THE System SHALL include, alongside that version, at least one of the following verifiable artifacts obtained on the target machine: a package-manager query result showing that exact version, a documentation reference for that exact version, or a minimal test that passes against that exact version.
7. WHERE a third-party package or asset is added to the repository, THE System SHALL record, in the THIRD_PARTY_Doc, the package or asset name, its version, and its license identifier.
8. THE System SHALL read every secret from an environment variable and SHALL list every secret-bearing file in `.gitignore` so that no such file is tracked in version control.
9. WHERE a module contains more than one public function or exceeds 50 source lines, THE System SHALL provide unit tests for that module, and THE README SHALL state the exact single command that runs those tests.
10. THE System SHALL NOT modify the SUT's navigation algorithms, and SHALL interact with the SUT only through its published interfaces (topics, the `NavigateToPose` action, TF, and launch arguments).

### Requirement 1: Platform baseline (M0)

**User Story:** As the repository owner, I want the Nav2 TurtleBot simulation proven to run headless and reach a goal from a script, so that the harness is built on a validated foundation.

#### Acceptance Criteria

1. THE System SHALL target Ubuntu 24.04 with ROS 2 Jazzy and Gazebo Harmonic, and SHALL NOT target Windows for running the Simulation.
2. WHEN the M0 baseline procedure runs, THE System SHALL confirm on the target machine the presence and exact version of the Nav2 packages it depends on (`ros-jazzy-navigation2`, `ros-jazzy-nav2-bringup`, and the `ros-jazzy-nav2-minimal-tb*` packages) and SHALL record each confirmed version with a package-manager query result in the ENVIRONMENT_Doc.
3. WHEN the Nav2 TurtleBot simulation is launched with its headless argument set so that no graphical window opens, THE System SHALL bring up the Simulation and Nav2 without an unhandled error.
4. WHEN a script sends one goal to the running SUT through the `NavigateToPose` action, THE SUT SHALL report the goal succeeded and the robot's true pose SHALL be within a stated position tolerance of the goal pose, and THE System SHALL record the command, seed, and full commit hash of this run.
5. IF the headless launch or the single-goal run fails on the target machine, THEN THE System SHALL record, in the ENVIRONMENT_Doc, the failing step and its observed effect, and SHALL NOT proceed to later milestones until M0 passes.

### Requirement 2: Scenario format

**User Story:** As a user, I want a versioned, validated scenario format, so that every test case is explicit, reproducible, and machine-checkable.

#### Acceptance Criteria

1. THE Scenario_Schema SHALL define a Scenario containing a schema version, a world identifier, a start pose, a goal pose, a list of obstacles, a list of faults with timing, a time limit, and a random seed.
2. THE Scenario_Schema SHALL define each obstacle with a shape, a size, and a pose.
3. THE Scenario_Schema SHALL carry a schema version field, and THE System SHALL reject a Scenario whose schema version it does not support, emitting an error that identifies the unsupported version.
4. WHEN a Scenario is loaded, THE System SHALL validate it against the Scenario_Schema and, IF any required field is missing, any value is out of its stated bound, or any field has the wrong type, THEN THE System SHALL reject the Scenario and emit an error that identifies the offending field.
5. THE Scenario SHALL be expressed in YAML and SHALL be readable by the Generator, the Runner, and the Oracle without manual conversion.
6. THE System SHALL express the start pose, the goal pose, and every obstacle pose in a single documented coordinate frame, and SHALL state that frame in the Scenario_Schema documentation.

### Requirement 3: Scenario generator

**User Story:** As a user, I want a seeded generator that produces feasible randomized scenarios, so that I can create large, reproducible test suites.

#### Acceptance Criteria

1. WHEN the Generator runs with a seed and a requested count N, THE Generator SHALL produce N valid Scenarios whose obstacles, start poses, and goal poses are randomized from that seed.
2. WHEN the Generator runs twice with the same seed and the same configuration, THE Generator SHALL produce byte-for-byte identical Scenarios, excluding timestamps and absolute file paths.
3. WHEN the Generator produces a Scenario, THE Generator SHALL reject it as an Infeasible_Scenario IF the start pose lies inside an obstacle, IF the start or goal pose lies off the map, or IF the goal pose is unreachable from the start pose on the map, and SHALL replace it so that exactly N feasible Scenarios are returned.
4. WHEN the Generator rejects an Infeasible_Scenario, THE Generator SHALL record a count of rejections by reason so that the rejection rate is observable.
5. WHEN the Generator writes a Scenario, THE Generator SHALL write the seed used for that Scenario into the Scenario so that the Scenario can be regenerated and re-run alone.
6. WHERE the Generator determines goal reachability, THE System SHALL state in `design.md` the exact reachability check used (for example, an occupancy-grid connectivity check between start and goal cells) so that "unreachable" is defined and testable.

### Requirement 4: Fault injection

**User Story:** As a user, I want a fault-injection node between the sensors and Nav2, so that I can test how Nav2 behaves under degraded sensor data.

#### Acceptance Criteria

1. THE Fault_Injector SHALL be a ROS 2 node that subscribes to the simulated sensor topics and republishes modified topics to Nav2, so that it sits between the simulated sensors and Nav2 without modifying the SUT.
2. THE Fault_Injector SHALL apply each Fault only during the time window configured for that Fault in the Scenario, and SHALL pass the sensor stream through unmodified outside every configured Fault window.
3. THE Fault_Injector SHALL support lidar range noise, per-ray dropout, whole-scan dropout, added latency, frozen scans, and a blacked-out sector, each configurable from the Scenario.
4. WHEN lidar range noise is configured with standard deviation sigma and estimated from at least 1000 affected ray returns, THE measured standard deviation of the difference between the modified range and the input range SHALL match sigma within plus or minus 10 percent.
5. WHEN per-ray dropout is configured with probability p and estimated from at least 1000 affected rays, THE measured fraction of dropped rays SHALL match p within plus or minus 2 percentage points.
6. WHEN whole-scan dropout is configured for a window, THE Fault_Injector SHALL publish no scan during that window and SHALL resume publishing after it.
7. WHEN added latency is configured with delay L and estimated from at least 100 affected messages, THE measured delay between a message's input time and its republished time SHALL match L within plus or minus 20 percent.
8. WHEN a frozen-scan Fault is configured for a window, THE Fault_Injector SHALL republish the last scan captured before the window, unchanged, for the duration of the window.
9. WHEN a blacked-out-sector Fault is configured with an angular sector, THE Fault_Injector SHALL mark every ray whose bearing falls inside that sector as no-return and SHALL leave every ray outside the sector unchanged.
10. WHERE odometry drift is implemented, THE Fault_Injector SHALL apply a configurable drift to the intercepted odometry or TF stream; this Fault is optional and is implemented only if intercepting odometry and TF proves practical, which THE System SHALL record in `design.md`.
11. THE System SHALL provide a unit test for each supported Fault that shows the republished output matches the configured effect.

### Requirement 5: Scenario runner

**User Story:** As a user, I want a runner that executes each scenario cleanly end to end, so that runs are isolated, recorded, and never hang the suite.

#### Acceptance Criteria

1. WHEN the Runner executes a Scenario, THE Runner SHALL start a clean headless Simulation for that Scenario, spawn the Scenario's obstacles, start the Fault_Injector with the Scenario's faults, send the goal through Nav2's `NavigateToPose` action, and record a ROS_Bag of the run.
2. WHEN a run ends for any reason, THE Runner SHALL tear down the Simulation, Nav2, and the Fault_Injector so that no process from that run remains before the next run starts.
3. THE Runner SHALL enforce a hard timeout per run, and IF a run exceeds its time limit, THEN THE Runner SHALL stop the run, mark it timed out, and proceed to the next Scenario so that one hung run does not block the suite.
4. WHEN the Runner records a ROS_Bag, THE Runner SHALL name and store the ROS_Bag so that the bag for a given Scenario can be located from the Scenario identifier.
5. WHEN the Runner finishes a Scenario, THE Runner SHALL pass the recorded Ground_Truth and run metadata to the Oracle for judging.
6. THE System SHALL provide a command that re-runs any single Scenario alone from its seed and produces the same Scenario as in the suite.
7. IF starting the Simulation, spawning obstacles, or sending the goal fails for a Scenario, THEN THE Runner SHALL record that Scenario as errored with the failing step and SHALL continue with the next Scenario.

### Requirement 6: Oracle

**User Story:** As a user, I want each run judged from ground truth, so that the verdict reflects what actually happened and not the robot's own estimate.

#### Acceptance Criteria

1. WHEN the Oracle judges a run, THE Oracle SHALL use Ground_Truth from the Simulation and SHALL NOT use the robot's own pose estimate to decide the Verdict.
2. WHEN the robot footprint comes closer to an obstacle than the configured collision threshold, or a contact sensor reports contact, THE Oracle SHALL record a Collision and SHALL fail the run with the reason "collision".
3. WHEN the robot's true pose is within the configured position tolerance and orientation tolerance of the goal pose, THE Oracle SHALL record Goal_Reached.
4. IF a run reaches the goal within tolerance and within the time limit and without a Collision, THEN THE Oracle SHALL pass the run; OTHERWISE THE Oracle SHALL fail the run.
5. IF a run does not reach the goal within the time limit, THEN THE Oracle SHALL fail the run with the reason "timeout".
6. WHEN the Oracle judges a run, THE Oracle SHALL record the Verdict, the Time_To_Goal, the minimum distance between the robot footprint and any obstacle, and the reason for any failure.
7. THE System SHALL provide unit tests for the Oracle's collision, goal-reached, and timeout decisions against constructed Ground_Truth inputs with known answers.

### Requirement 7: Reports

**User Story:** As a user, I want machine- and human-readable reports, so that Jenkins shows per-scenario results and I can diagnose every failure.

#### Acceptance Criteria

1. WHEN a suite completes, THE System SHALL write a JUnit_Report in which each Scenario appears as exactly one test case, a failing Scenario appears as a failed test case carrying its failure reason, and an errored Scenario appears as an errored test case.
2. WHEN a suite completes, THE System SHALL write a Summary_Report in Markdown or HTML that states the pass rate per Fault type, lists the failure reason for each failed Scenario, and links to the ROS_Bag for each failed run.
3. WHEN a Scenario fails, THE Summary_Report SHALL include the exact command, with seed, that re-runs that Scenario alone.
4. THE Summary_Report and the JUnit_Report SHALL be generated files produced by a repository script, and SHALL NOT be hand-edited.
5. IF the inputs needed to produce a report are missing or unparsable, THEN THE System SHALL terminate without writing a partial report and SHALL emit an error that identifies the missing or unparsable input.

### Requirement 8: Docker and headless rendering

**User Story:** As a user, I want the harness to run headless in Docker, so that it runs the same way on my machine and in CI.

#### Acceptance Criteria

1. THE System SHALL provide a Dockerfile based on an official ROS 2 Jazzy image that installs Gazebo Harmonic and the Nav2 packages at pinned versions.
2. WHEN the Simulation runs inside the container with no display attached, THE System SHALL render sensor data (for example the lidar scan) headlessly, and THE System SHALL state in `docs/` the headless-rendering method used (for example EGL or software rendering).
3. THE System SHALL provide, inside the container, a check that proves headless sensor rendering works by producing non-empty sensor output from a scene with known geometry, and THE System SHALL record that check's command and output.
4. THE System SHALL pin the base image and every installed package version so that an image build is reproducible, and SHALL record the versions in the ENVIRONMENT_Doc.
5. WHEN the container runs the Smoke_Suite, THE System SHALL complete the suite inside the container without requiring an X server on the host.

### Requirement 9: Continuous integration (Jenkins)

**User Story:** As the repository owner, I want a Jenkins pipeline, so that every change is tested and the full suite runs nightly.

#### Acceptance Criteria

1. THE System SHALL provide a Jenkinsfile that, on every change, builds the Docker image, runs the unit tests, and runs the Smoke_Suite of about 10 Scenarios.
2. THE System SHALL configure the Jenkins pipeline to run the Full_Suite nightly.
3. IF the unit tests or the Smoke_Suite fail during a change build, THEN THE pipeline SHALL report a failed status for that build.
4. WHEN a pipeline run completes, THE pipeline SHALL publish the JUnit_Report so that Jenkins displays each Scenario as a test case.
5. THE System SHALL commit a log of one successful Jenkins run into the repository as evidence.
6. THE README SHALL state the exact command that runs the unit tests and the exact command that runs the Smoke_Suite locally, matching what the pipeline runs.

### Requirement 10: Paired experiment

**User Story:** As a reader, I want Nav2's pass rate measured with and without each fault, so that I can see the effect of each fault with a stated confidence.

#### Acceptance Criteria

1. WHEN the Paired_Experiment runs, THE System SHALL run the same set of at least 30 Scenarios with no Fault and under each Fault type, so that each Fault condition uses the same Scenarios as the no-Fault condition and differences come from the Fault alone.
2. WHEN the Paired_Experiment completes, THE System SHALL report Nav2's pass rate per condition as a Measured_Value with a 95% Confidence_Interval, and SHALL state in `design.md` the method used to compute the Confidence_Interval.
3. WHEN the Paired_Experiment completes, THE System SHALL report the total run time of the experiment as a Measured_Value.
4. THE System SHALL produce the Paired_Experiment results from a single repository command with a fixed seed, recorded with its command, seed, and full commit hash.
5. IF a condition's pass rate is lower than the no-Fault condition, THEN THE System SHALL report the real measured rates and SHALL NOT loosen any Oracle threshold or time limit to change the outcome.

### Requirement 11: README and acceptance (Gate A)

**User Story:** As a reader, I want a README with the architecture, the format, run instructions, the results, and the limitations, so that I can understand and reproduce the project.

#### Acceptance Criteria

1. THE README SHALL contain an architecture diagram, a description of the Scenario format, instructions to run locally and in Jenkins, the Paired_Experiment results, and a known-limitations section.
2. THE known-limitations section SHALL state that the injected faults are models rather than field data.
3. THE README SHALL present the Paired_Experiment results — pass rate per condition with 95% Confidence_Intervals and the total run time — sourced from the generated Summary_Report, with the generating command, seed, and full commit hash.
4. WHEN M5 completes, THE System SHALL satisfy Gate_A by: a Jenkins pipeline run that builds the image, runs the unit tests, and runs the Smoke_Suite with a reported status; a Paired_Experiment that runs end to end from the Generator through the reports without unhandled failure; and all unit tests passing.

## Out of Scope

The following are explicitly out of scope: modifying Nav2's algorithms, real hardware, Isaac Sim, and multiple robots.
