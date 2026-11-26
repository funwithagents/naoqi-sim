# Our modules load from NAOqi's autoload, in place of the built-ins

**Status:** Done

Implements [service-replacement.md](../specs/container/service-replacement.md) ("Loading a module", "Replacing a built-in") and [container.md](../specs/container/container.md) ("The native build", "Entrypoint", "Matching a NAO's modules"). Our modules stop replacing the built-ins after the fact (let them load, `exit()` them, load ours over `ALLauncher`, relaunch or restart every module that held a proxy to them): the entrypoint starts NAOqi from an autoload copy where the built-ins' entries are left out and ours sit right after `pythonbridge`, with a new C++ loader module loading our Python modules at that point. Everything NAOqi loads afterwards finds our modules in place. Investigated before this plan. It leaves the modules themselves (cores, fronts, relay) unchanged.

## Scope

- `docker/naoqi/services/service-replacement/naoqi_sim_loader.cpp` — new: `_NaoqiSimLoader`, a C++ `ALModule` whose `init()` adds `NAOQI_SIM_MODULES_DIR` to the embedded interpreter's `sys.path` and `launchPythonModule`s each of `NAOQI_SIM_PYTHON_MODULES`, in order
- `docker/naoqi/Dockerfile.naoqi-2.1`, `docker/naoqi/Dockerfile.naoqi-2.8` — our `.so` files go to `/opt/naoqi/lib/naoqi/` (the suite's module folder), not `/opt/naoqi/lib/naoqi-sim/`; the native stage already compiles every `services/*/*.cpp`
- `docker/naoqi/entrypoint-lib.sh` — `write_autoload` (leave entries out, insert entries after others, fail when the suite's file lacks one); `exit_builtins`, `load_modules`, `load_native`, `launch_local`, `autoload_without` removed; `check_answer` also checks the added built-ins
- `docker/naoqi/entrypoint-2.1.sh`, `docker/naoqi/entrypoint-2.8.sh` — the new constants (`LEFT_OUT`, `OURS`, `MODULES`, `REPLACED`, `ADDED`, 2.1's added built-ins and `BUILTINS`, `LAST`) and sequence: write the copy, start, wait, check, ready
- `tests/test_entrypoint.py` — the fake `qicli` serves names as the autoload registered them (no launches to simulate); the sequence per version (no calls but `setReady`, the autoload copy, the exported variables); the failure checks (a replaced, added or added built-in name missing; `ALPythonBridge` or a last service never appearing; `naoqi-bin` exiting; the status module missing)
- `AGENTS.md` — the project map's `docker/` row names the `service-replacement/` folder
- The specs above, `Updated` until this plan is `Done`

## Steps

1. The loader, from the investigation's prototype, with the module list and the modules folder from the environment; compiled in both images by the existing native stage.
2. The Dockerfiles install the `.so` files in `/opt/naoqi/lib/naoqi/`.
3. `entrypoint-lib.sh`: `write_autoload <left out entries> <anchor>:<entry>,<entry>...`; remove the launch and exit helpers.
4. Both entrypoints: constants and sequence of container.md, "Entrypoint".
5. `tests/test_entrypoint.py` rewritten for the new sequence; the fast tier passes.
6. Rebuild both images (the live tier does it) and run the whole live tier on both versions; the dialog test (plan 202610132100's `test_sound_live.py`) on 2.8 and the preloaded behaviors' Play Sound on 2.1 (`test_an_installed_behavior_plays_its_sound`) must pass. Time a start of each version, cold (right after the rebuild) and warm.

## Result (Oct 14, 2026)

- Fast tier: `tests/test_entrypoint.py` rewritten (27 tests), 298 passed.
- Live tier, both images rebuilt, both versions: 180 passed, 11 skipped, 1 expected failure (2.8 Sit); the 28 failures are plan 202610132100's known gaps (LEDs, speaker volume, recording, body id, motion checks, 2.8's joint temperatures), 14 per version, as before this plan. `test_a_dialog_topic_answers_aloud` passes on 2.8 and `test_an_installed_behavior_plays_its_sound` on 2.1, with nothing restarted. The first boot of each version right after its image rebuild (cold cache) passed.
- Starts (`NaoqiSim.start()`, headless, no viewer): 2.8 about 18 s, against 35 s with the seven restarted services; 2.1 about 18 s. In the live tier, `test_packages_survive_a_restart` went from 30 to 20 s, `test_naoqi_sim_run_end_to_end` from 60 to 40 s, and the whole tier took 778 s for 220 tests (before: 621 s for 122, plus 253 s for plan 202610132100's 98).

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, `uv run pytest tests-e2e` on both versions. Then the specs go back to `Implemented` and this plan to `Done`.
