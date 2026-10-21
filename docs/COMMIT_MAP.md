# Commit map for result stamps

Every result in `results/`, the evidence under `docs/evidence/`, the scenario-set stamps, and the Jenkins run
log under `ci/jenkins_run_log/` name the commit that produced them. Those commits are from this repository's
history before it was rewritten to drop local IDE files (`.kiro/steering/` and
`.kiro/specs/autonomy-test-harness/.config.kiro`) from every commit. The rewrite changed every commit hash
and nothing else: for each stamped commit below, the commit in the current history with the same author date
and message has a byte-identical tree once those IDE files are left out (checked by comparing every file's
blob hash).

| Stamped commit | Same code in this history | Commit message |
| --- | --- | --- |
| `4849ce0e6aa64c9da66078c9eaddeb5043d76320` | `67c34bcdc7a609094c24b061678efe2225ae6782` | task 6.5: Properties 17 and 18, Wilson known values, resume and retry tests |
| `61efb3b8a43b7b657c11229d3f5d477ec3c0c69e` | `65c974aa23a97d7dfa9209a408e7ea5de4ee1aa5` | task 6.3: ignore ci-out/ and clear it per build (build 2 failed: the reused workspace looked dirty) |
| `340cbcf9c8a8fa521809fd06f07dfa0d4ec6d5fd` | `99cd42d0f7f36ef19332f45c5df526232124b1c4` | Revert "task 6.3: deliberately failing unit test to prove the pipeline reports a red build" |
| `3fd8a2d7c9a1f0b995bd25699359e06dea90850d` | `5602ba433ce125ce86dcb46df7a70256d01fe024` | task 6.3: deliberately failing unit test to prove the pipeline reports a red build |
| `814a2c39bed7ff27bb2f3c8a87d1d108db3c3047` | `a54668997cd187deee60a5b8c08653fbfc7c4afa` | task 1.4: M0 baseline (versions, EGL/Xvfb render rule, single goal, true-pose error, lidar yaw) and run_m0.sh |
| `eab421795f3efad6cf9e0ef2269c98b714bc47ed` | `eb607184ba470ec1a7c7ceeadfc1e0a88cb46027` | task 5.4: headless-render check (known box 2.0 m ahead, forward beam within 0.05 m, >= 300 finite ranges) |
| `b06c031f8945fd526723032ba29741793be5db1b` | `46331c034e6205faad389cd2bba18d5016e9c065` | task 4.6: fault-window bag check (bag_checks.fault_report) and scripts/m3_fault_check.py |
| `9802096a254218a45ab504ce255bd789b6a793e0` | `b0092882e00986fa54ccc96313edd329c860aa58` | task 2.7: generate_sets.sh (stamped scenario-set generation in the image) |
| `73a0d036dd438fe3616569ed31eac9b999c0b74a` | `99064bbda084fce672effdfc4915a24bef2af68b` | task 3.7: one Scenario end to end; wiring evidence (Nav2 reads /scan_ath, passthrough identical, GT recorded, no leftovers) |
| `5a615def950b16031a5c367a74f8678d30aafa12` | `732d7701f117b13e9d0cf48a734d7a2ef14e0c47` | task 3.6: Runner unit tests (hard limit, spawn failure, leftovers, bag path, stamp, rerun) |
| `06c1e056bc5df774b9211563ac368ff397cccebc` | `07df1d2c56781ebbaff93a0eae6d1a7f903aff2e` | task 5.4: headless-render check PASS in the container (2.0009 m vs 2.0 m); outcome recorded |
| `b72ca89712cfba92aa57218bee97e2e9eafa08b4` | `61c8dc270a456e3588d77f458c5707a802992662` | task 4.6: fault check judges only the span /scan_ath was recorded; record the checking commit |
| `1aa425ec2d14e543729c83cf6c2ace5b20f04ac6` | `a81d01833d4293cbb4116bbdd3af2bfe7399829d` | task 6.2: controller up; job, triggers, Docker CLI verified; Jenkins and plugin versions and licenses recorded |
