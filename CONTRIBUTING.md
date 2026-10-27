# Contributing

## Checks to run before a commit

Without ROS 2 or Docker, from the repository root (needs [uv](https://docs.astral.sh/uv/)). These are
the two checks GitHub Actions runs on every push and pull request:

```bash
uv sync --frozen
uv run --frozen pytest -m "not sim and not ros"
uvx ruff@0.17.1 check .        # rules in ruff.toml
```

With Docker (WSL 2 or Linux; no GPU or display needed), the checks the Jenkins pipeline runs:

```bash
bash scripts/build_image.sh       # ath-sim:dev from the working tree
bash scripts/test_unit.sh         # every unit test, including those marked ros, with the coverage rule
bash scripts/run_suite.sh smoke   # the smoke suite in the simulator
```

`scripts/test_unit.sh` fails if a non-trivial module in `harness/` or `scripts/` (more than one public
function, or more than 50 source lines) is below 80% statement coverage (`scripts/check_coverage.py`).
The Jenkins controller itself is started with `bash scripts/jenkins_up.sh`; see "Continuous integration"
in the README.

## Results and the README are generated

- Never edit a file under `results/` by hand. Each one is written by the script named in its stamp
  (command, seed and commit), and a changed result comes from re-running that script on a clean commit.
- `README.md` is generated. Edit `docs/README.template.md`, then regenerate it and check that every
  number in it comes from `results/`:

  ```bash
  uv run --frozen python scripts/build_docs.py
  uv run --frozen python scripts/check_traceability.py
  ```

## Code and tests

- Logic goes in `harness/`; files in `scripts/` stay thin entry points unless they have their own tests.
- Tests use fakes for processes, Docker, Gazebo, Nav2 and clocks. Mark a test `ros` if it needs `rclpy`,
  and `sim` if it needs the running simulator. Hypothesis tests use
  `@settings(max_examples=100, derandomize=True)`.
- Every dependency is pinned to an exact version in `pyproject.toml` and locked in `uv.lock`. A new
  third-party package or asset is listed with its license in `THIRD_PARTY.md`.
- Files use LF line endings and UTF-8 without a BOM; run shell scripts as `bash scripts/<name>.sh`.
- No secrets in the repository: read them from environment variables.
