---
code:
  - tests/conftest.py
  - tests/fake_docker.py
  - tests/ports.py
  - tests-e2e/conftest.py
  - tests-e2e/support.py
tests:
  - tests/test_audio_output.py
  - tests/test_speech_core.py
  - tests/test_tts_engine.py
  - tests/test_status_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_speech_live.py
  - tests-e2e/test_status_live.py
  - tests-e2e/test_audio_input_live.py
  - tests-e2e/test_audio_loopback_live.py
  - tests-e2e/test_memory_live.py
  - tests-e2e/test_motion_live.py
  - tests-e2e/test_leds_live.py
  - tests-e2e/test_behaviors_live.py
  - tests-e2e/test_sound_live.py
  - tests-e2e/test_robot_info_live.py
  - tests-e2e/test_absent_live.py
---

# Testing

**Status:** Implemented

## Purpose

naoqi-sim's testing strategy — the two-tier structure and what a good test looks like. It's a **cross-cutting practice**, not a runtime concept: nothing here ships in the library. It exists as a spec so the decisions have one honest home that stays in sync with the setup, rather than living half in [project.md](../project.md) (the tooling choices) and half in [AGENTS.md](../../AGENTS.md) (the operational how-to). The concrete shell commands to run each tier live in [AGENTS.md](../../AGENTS.md) "Testing".

## Two tiers, physically separated

Tests split into two directories, and the split is structural — a directory boundary, not a marker or an opt-out flag:

| Tier | Directory | Network | Deterministic | Runs by default |
|---|---|---|---|---|
| Unit / integration | `tests/` | never | yes | **yes** |
| Live / e2e | `tests-e2e/` | the naoqi-sim containers, started by the tests | no | **no** |

- **`tests/` is the normal dev loop.** Fast, deterministic, no real network, no credentials. `pyproject.toml`'s `testpaths = ["tests"]` points the default `uv run pytest` here, so this is what runs on every change and what any contributor or CI can run with zero credentials.
- **`tests-e2e/` is opt-in.** It builds and runs the NAOqi and `tts` containers (Docker, the user's Choregraphe suite, real timing), so it is deliberately *not* collected by the default run. Because `testpaths` already excludes it, no pytest marker or `--run-e2e` flag is needed: the physical separation is the whole mechanism. Run it explicitly (`uv run pytest tests-e2e`).

The `tests/` tier has one `test_<module>.py` per module under test: the `src/naoqi_sim/` modules and the host-importable container code (`test_speech_core.py` for `docker/naoqi/services/speech/naoqi_sim_speech_core.py`, `test_status_core.py` for `naoqi_sim_status_core.py`, `test_tts_engine.py` for `docker/tts-engine/server.py`), the container's shell scripts (`test_entrypoint.py` runs `docker/naoqi/entrypoint-2.1.sh`, `entrypoint-2.8.sh` and `healthcheck.sh` with fake `naoqi-bin` and `qicli` first on `PATH`, so the boot sequence and its failure exits are checked without Docker), plus the `test_project_map.py` drift guard. `tests/conftest.py` puts every `docker/naoqi/services/<service>/` and `docker/tts-engine` on `sys.path` (and pyright's `extraPaths`). `tests-e2e/` is organized around live scenarios rather than modules.

## What a good test asserts

- **Functional, not tautological.** Exercise what a feature actually does — inputs → outputs, state changes, side effects — not that it runs or matches its own signature. A test that would pass against a broken implementation (asserting a constant, that an object isn't `None`, that a mock was called) isn't worth writing.
- **Drive the public API like a real caller.** Prefer exercising the public surface the way a consumer would over reaching into internals; assert on the observable result.
- **In the e2e tier, assert on behavior, not exact output.** Timings and synthesized audio vary run to run, so a live test asserts a robust property ("`say()` blocked for about the audio it played", "every bookmark was raised"), never an exact duration or string.

## Platforms

The fast tier runs on the three platforms naoqi-sim installs on, Linux x86_64, macOS arm64 and Windows x64 ([project.md](../project.md), "Platforms"), each in CI ([ci.md](ci.md)), with the same tests and the same bounds:

- **`container_code`** (a marker declared in `pyproject.toml`) is on the test modules of code that runs in the Linux containers: the NAOqi modules' Python 2.7 cores (`test_audio_device_core`, `test_audio_player_core`, `test_speech_core`, `test_status_core`), the entrypoints and healthcheck (`test_entrypoint`) and the speech engine (`test_tts_engine`), 88 tests. Another host adds nothing to them, so CI runs them on Linux only (`-m "not container_code"` on macOS and Windows). Locally they run on Linux and on developers' Macs; `tests/conftest.py` skips them on Windows, where they need POSIX tools (bash, executable stand-ins with a shebang, and a connect to a closed port that fails at once, where Windows takes about 2 s).
- **Real time on a slow machine.** Many tests check real-time behavior: the mix's pacing, a stop within a tick, the speech clock, a file's playing time, the camera's frame rate. GitHub's macOS runner wakes threads up to 30 to 50 ms late (Linux 0.1 ms, Windows about 25 ms). That uncovered a real fault, fixed rather than tolerated: the audio output's mixer restarted its schedule at each late wake-up, so lateness added up in the playback ([audio-output.md](../host/audio-output.md), "The ticks keep their schedule"), which `test_late_wake_ups_do_not_drift_the_mix` now pins on any machine with a mixer whose sleeps wake 30 ms late. What remains is a single wake-up's lateness against a bound that assumed a quiet machine. `tests/conftest.py` measures it all along: a sampler thread in each worker does 5 ms waits for the whole session, living through the same load as the tests, and keeps the worst lateness seen (its first second is printed in pytest's header). A test that bounds a reaction time adds `lateness()`, read at the assertion, to its bound, which stays the spec's on a quiet machine. A figure taken once at the session's start fell short under parallel load (23 ms measured, 27 ms met). Bounds are on the behavior, not the machine: the camera's "no burst" is "no more frames than the schedule has slots" (frames put plus missed slots within the slots elapsed), which a frame woken late does not break; a gap check between frames ("no two back to back") is kept only at 10 fps, where the macOS runner's 50 ms lateness still leaves 50 ms to the next slot, since at 30 fps a frame woken 33 ms late lands right before the next slot's frame (seen on `main`'s first run after PR #7).
- **A stop may beat the audio.** The live tier's `say` stopped during synthesis plays at most a moment of audio, or none when the stop comes first (`Nao.played_if_any`). Likewise a live test that needs audio playing waits for its stream to start rather than sleeping a guessed synthesis time: a sound played into a sentence starts once the sentence plays.
- **The fake `docker`** (`tests/fake_docker.py`) is a script with a shebang first on `PATH`, and on Windows a `docker.cmd` running the same script, which naoqi-sim finds because it resolves `docker` with `shutil.which` ([project.md](../project.md), "Platforms"). So `docker_images`, `stack`, `sim` and the CLI are tested on all three.
- Ctrl-C reaches `naoqi-sim run` both ways on every platform: through the event loop and through the plain handler Windows needs ([cli.md](../runtime/cli.md)).
- **Ports.** A test that names a port before something binds it (naoqi-sim's fixed ports, moved) takes it from `tests/ports.py`: below every OS's ephemeral range, in a block per xdist worker, so neither another worker nor a client connection gets it between the reservation and the bind.

## Test isolation

If the package holds process-global or singleton state, both tiers carry an identical autouse fixture (in each tier's `conftest.py`) that resets it before and after every test, so no state — or background timers/threads — leaks across tests. The fixture is duplicated rather than shared because `tests-e2e/` isn't a package that imports from `tests/`, and it's only a few lines.

## Live tier: the tests drive the stack

naoqi-sim is tested as what it is: containers that behave like a NAO in their API, reached over qi on `127.0.0.1:9559`. The live tests bring that stack up themselves; there is no target to configure.

- **Per version.** The `nao` fixture (`tests-e2e/conftest.py`) is session-scoped and parametrized over NAOqi 2.1 and 2.8, so every live test runs once per version. For each version it first runs `check_images` ([api.md](../runtime/api.md), "Images"): current images are used as they are; missing or outdated ones (an edit under `docker/` included) are built and verified with `fetch_and_build_images` when the image data are in `docker/image-data/`, and the version skips otherwise. Then it starts a `NaoqiSim` for that version, headless and silent, as any caller does ([api.md](../runtime/api.md)), connects, and stops it at the end; a test that needs another configuration (`naoqi-sim run`, the window) stops it and starts it again. Versions run one after the other, since both publish 9559.
- **The fixtures keep the robot running; a boot is a test of its own.** The session's `Nao` does not boot at creation: before each test that needs it, an autouse fixture starts it if it is not running, the first time or after a test that stopped it for its own needs (the install test's own `naoqi-sim run`, the window, the microphone robot), so no test restores the robot in its cleanup. `test_the_robot_boots` (`tests-e2e/test_boot_live.py`) runs first for each version, a collection hook moving it to the head of the version's tests. A `NaoqiSim.start()` that raises `BootError` is retried once (the retry is printed); a boot that fails again fails the test it was started for, `test_the_robot_boots` for the first boot, or the next test that needs the robot, its message naming the test after which the robot was being brought back, or the test that restarts the robot on purpose (the packages test). Every later test of that version skips ("did not boot, the failure is reported once, above"). So a failed boot shows as one failure carrying its cause, not as every later test failing for want of a robot (seen once on CI: a 2.8 restart that did not boot turned some sixty tests red). A version whose robot does not boot still fails its CI job, through that one failure.
- **Skip, never fail, without the means.** No Docker, or neither the version's suite tarball nor its image: that version's tests skip. A contributor (or CI) without the suites is never broken.
- **Fail loudly on a conflict.** If 9559 or the audio output's 9562 is already taken (a naoqi-sim, or a stack started by hand), the tests fail with that message rather than test someone else's stack.
- **Connect in one attempt** (`support.connect`): the libqi 3.1.6 wheel failed about one connect in three against NAOqi 2.1, instantly, with `disconnected`, and the tier retried; 3.1.8, the floor ([project.md](../project.md)), fixed it (200 plain connects to 2.1: 12 failures with 3.1.6, none with 3.1.8).
- **What was played.** The `NaoqiSim` runs with a `MemorySink` ([audio-output.md](../host/audio-output.md), "Audio sinks"): the tests assert on each playback's audio, its timing and whether it was cut. What the `ALTextToSpeech` replacement received is read from its JSON log in the container.
- **What the robot hears.** The `NaoqiSim` runs the fake audio source ([audio-input.md](../host/audio-input.md), "The fake source"): a test subscribes to `ALAudioDevice` as a client does, plays sounds through `fake_audio` when it chooses, and checks what it receives against them.
- **Real devices only on a declared loopback.** The tests that use the machine's sound devices (the microphone, the robot's speech played aloud and heard back, the `DevicePlayer`) skip unless `NAOQI_SIM_E2E_AUDIO=loopback` says the default output and input are wired to each other; a developer never has the tests play into their loudspeakers or record their microphone by surprise. CI sets it over a PulseAudio null sink ([ci.md](ci.md)), where a missing loopback fails, as `NAOQI_SIM_E2E_VERSION` turns a missing version into a failure. An unknown value fails the session at collection.
- **One live tier, always run.** Every live test runs on every run, locally and in CI ([ci.md](ci.md)); there is no slower tier on a schedule. Measured Oct 14, 2026, on a Mac (OrbStack, both versions one after the other): 778 s for 220 tests, the heaviest being the end-to-end `naoqi-sim run` and install tests and the sim window (40 to 50 s each, per version); the one test per feature below adds about 1.5 minutes per version.
- **One test per feature a robot user calls.** Besides the tests of naoqi-sim's own services and devices, the live tier has a test per feature of the standard behaviors, listed from each suite's Choregraphe box library (memory, motion and postures, LEDs, behaviors, sound settings, robot information; `test_memory_live.py` ... `test_robot_info_live.py`), written as a Python 3 qi client that checks the outcome somewhere else than the call's answer where it can (the joint sensors, the odometry, the loudspeakers' mix, a recording, ALMemory). The built-ins are tested like naoqi-sim's own services: the desktop NAOqi is not a robot's ([naoqi-fidelity.md](../container/naoqi-fidelity.md)). Services a robot has and naoqi-sim leaves out are checked absent (`test_absent_live.py`).
- **A known issue is a strict expected failure.** A test checks what a real NAOqi robot does. Where naoqi-sim documents a difference (a known issue in [naoqi-fidelity.md](../container/naoqi-fidelity.md), or an open question of the service's spec), the test calls `support.known_issue(request, nao, reason, versions)`: on those versions it is an expected failure whose reason names where the issue is documented, and strict, so the day the behavior starts working the test fails and the mark goes with the fix.

## Tooling

- **The fast tier runs in parallel** (pytest-xdist, `-n logical --maxprocesses 8` in `addopts`): it is sleep-bound (the audio output, the cores and the fake `docker` run in real time), so 105 s serially take about 18 s on eight workers. Tests use free ports and their own temporary folders, so workers share nothing. `uv run pytest -n 0` runs it serially. `tests-e2e/conftest.py` forces the live tier serial: its tests share the one naoqi-sim on 9559.

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

1. **CI wiring** is built ([ci.md](ci.md)): both tiers run on GitHub's hosted runners. The live tier's rule of skipping what the machine lacks has its CI counterpart: `NAOQI_SIM_E2E_VERSION` runs one version and makes it required, so what would skip fails.
2. **Python 2.7 override modules.** The shared core (`naoqi_sim_speech_core`) is Python 2.7 code kept importable under Python 3, so the fast tier tests it on the host; the version-specific modules (`naoqi`/`qi` objects) are only exercised by the live tier. A live test (`test_modules_live.py`) compiles every module in each image with the image's own `/opt/naoqi/bin/python2`, so the live tier, and CI's entries with it, prove they are still valid Python 2.7.
