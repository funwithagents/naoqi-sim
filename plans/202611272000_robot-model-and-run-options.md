# The robot model, the setup block and the run options

**Status:** Done

Implements [config.md](../specs/runtime/config.md) ("The robot", the `setup` block, the required NAOqi version, the no-window default, "Example files"), [cli.md](../specs/runtime/cli.md) ("The robot options", "The `config` command"), [container.md](../specs/container/container.md) ("The robot model") and [status-service.md](../specs/container/status-service.md) ("The robot's keys"). It delivers a config that names its NAOqi version and its robot, a command line that runs the usual setups without a file, and a sim that is the robot the config names, in NAOqi's model and in ALMemory. It leaves out a model per robot in the window (naoqi-viewer's), a second robot type (Pepper), and the user documentation, which is written on top of it.

## Scope

- `src/naoqi_sim/config.py` — `naoqi.version` required; `RobotSettings` becomes `{type, version}` with `ROBOTS`, each NAOqi version's default robot and the robots it runs; `SetupSettings` takes the languages and the state at boot; `viewer.headless` defaults to true
- `src/naoqi_sim/cli.py` — the robot options shared by `run` and `config`, the options-or-file rule, the `config` command; `fetch-and-build-images` with a required `--naoqi`; `fetch-meshes`, naoqi-viewer's own command under naoqi-sim's name
- `src/naoqi_sim/stack.py` — `NAOQI_SIM_ROBOT_TYPE` and `NAOQI_SIM_ROBOT_VERSION` in the compose environment; the `setup` block's fields
- `src/naoqi_sim/sim.py`, `docker_images.py`, `__init__.py` — a required config; `SetupSettings`; `fetch_and_build_images` with its versions required
- `docker/compose.yaml` — the two robot variables on both NAOqi services
- `docker/naoqi/entrypoint-lib.sh`, `entrypoint-2.1.sh`, `entrypoint-2.8.sh` — `robot_model`: the model preference pointed at the robot's file before NAOqi starts
- `docker/naoqi/Dockerfile.naoqi-2.8` — the build-time model switch removed
- `docker/naoqi/services/status-service/naoqi_sim_status_core.py` — the robot's keys published from the model file
- `examples/configs/2.1.json`, `2.8.json` — the `config` command's output with everything on; `ci.json` names its NAOqi version
- `tests/test_config.py`, `test_cli.py`, `test_stack.py`, `test_entrypoint.py`, `test_status_core.py`, `test_sim.py`, `test_viewer.py` — functional tests for the above; the other fast tests and `tests-e2e/` follow the renamed blocks
- `specs/`, `AGENTS.md` — the specs above, the key renames in the specs that quote them, the index, the project map

## Steps

1. Config: the required version, `ROBOTS` and the robot's defaults and refusals, the `setup` block, the no-window default. Done.
2. Command line: the robot options, the options-or-file rule, `config`; the example files regenerated from it and tied to it by a test. Done.
3. The build names its versions (`--naoqi`, required) and `fetch-meshes` hands over to naoqi-viewer. Done.
4. Container: the compose variables, `robot_model` in both entrypoints, the status module's robot keys, the Dockerfile's switch removed. Done; fast tier (fake `naoqi-bin`, fake ALMemory).
5. Rebuilt both images and ran the live tier on both versions (Nov 27, 2026): 278 passed, 19 expected failures, 18 skipped, and one failure, a race in `test_the_launchpad_keys_follow_a_person_walking_in` on 2.1 (it read the last of the launchpad keys right after the first was written), fixed in the test and passing three times in a row since. Done.
6. On the running sims: the robot's keys disturb no NAOqi module (the live tier passes with them, on a V5, a V6 and a V4 boot); as a V4 and as a V5, NAOqi 2.1 has the same joints, limits and camera positions, other reported versions and a few other masses ([container.md](../specs/container/container.md), "The robot model"). Live tests: `tests-e2e/test_robot_model_live.py`. Done.
7. The five specs back from `Updated` to `Implemented`. Done.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` (all pass as of step 4), then `uv run naoqi-sim fetch-and-build-images` and `uv run pytest tests-e2e` on both versions. All passed on Nov 27, 2026, the live tier with the one test race above fixed.
