# Start progress logs

**Status:** Done

Implements the settled behavior in `specs/runtime/api.md` ("Progress") and `specs/runtime/cli.md` (`run` shows the start's progress). `NaoqiSim.start()` logs each step, the readiness wait relays what a slow boot is still waiting for, and the teardown logs what it stops, every line prefixed `NAOqi <version> (sim): `. It leaves the containers alone: no change under `docker/`, so no image rebuild.

## Scope

- `src/naoqi_sim/docker_images.py`: `label(version)`, the `NAOqi <version> (sim)` prefix of every line; `wait_healthy` logs that the containers are up and it waits for NAOqi to start (with its timeout), relays the container's log as it grows: the entrypoint's `still waiting` lines at INFO, the rest at DEBUG, then logs `NAOqi started`.
- `src/naoqi_sim/sim.py`: `starting`, then an INFO line as each step of `start()` begins; `stopping` in `stop()`, then one per undone step in `_teardown`, then `NAOqi stopped`; all with the prefix, no timings. The `naoqi-sim ready at …` line goes, since the CLI prints its own.
- `src/naoqi_sim/cli.py`: the ready and start-cancelled lines with the prefix (`stopping` moves to `stop()`); the ready line names the NAOqi version only.
- `tests/fake_docker.py`: a `boot_log` the fake NAOqi container reveals one line per `docker logs`, reporting `starting` until it is all out.
- `tests/test_docker_images.py`, `tests/test_sim.py`, `tests/test_cli.py`: functional tests on the logged and printed lines.

## Steps

1. `docker_images`: `label()`; a `_BootLog` that runs `docker logs <container>`, keeps count of the stdout and stderr lines already seen, logs new `[entrypoint] still waiting…` lines at INFO and every other non-empty line at DEBUG. `wait_healthy` logs `containers up, waiting for NAOqi to start (up to N s)`, relays after every poll, and once more when healthy before `NAOqi started`. The build and verification lines take the prefix.
2. `sim`: `starting`, then lines at each step (`checking Docker, the images and the ports`, `opening webcam N for …` with the macOS permission hint on darwin, `starting the audio output (<sink>)`, `opening the host link on port N`, `starting the containers (tts, <service>)`, `starting naoqi-viewer (window|headless)`, `starting the video input (top from …, bottom from …)`, `starting the audio input (<source> source)`). `stop()` logs `stopping`, `_teardown` `stopping the <step>` per step, then `stop()` `NAOqi stopped` once all succeeded.
3. `cli`: `NAOqi 2.8 (sim): NAOqi 2.8.7.4 ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)`, `… (sim): start cancelled`.
4. Fake Docker and tests: a boot whose log grows across polls is relayed line by line, in order, `still waiting` at INFO and the rest at DEBUG only; a start logs its steps in order and a stop its undone steps; `run` prints the ready line.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`. Then mark this plan `Done` and `api.md` and `cli.md` back to `Implemented` (files and indexes).
