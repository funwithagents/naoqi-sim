---
code:
  - src/naoqi_sim/cli.py
  - src/naoqi_sim/stack.py
  - pyproject.toml
tests:
  - tests/test_cli.py
  - tests/test_docker_images.py
  - tests-e2e/test_naoqisim_live.py
---

# CLI (`naoqi-sim`)

**Status:** Implemented

## Purpose

The `naoqi-sim` command is how a person runs a simulated NAO from a terminal. It is a thin shell over the [API](api.md): every command loads a [config](config.md), drives a `NaoqiSim` object or reads its state, and turns the API's errors into messages and exit codes. No lifecycle logic lives in the CLI, so the CLI, the live tests and any Python caller all run the same code.

## Decided

### Commands

| Command | Does |
| --- | --- |
| `naoqi-sim fetch-and-build-images --naoqi VERSION [VERSION]` | Runs `fetch_and_build_images` ([api.md](api.md), "Images"): fetches the image data, builds and verifies the images of the versions named. `--naoqi` is required, with one version or several, spelt as `run`'s: a version is gigabytes of downloads and images, so none is fetched without being asked for (until Nov 27, 2026 the versions were positional and no version meant both). The one slow step, run once before `run` and again after changing `docker/` |
| `naoqi-sim run --naoqi VERSION [options]`, or `naoqi-sim run --config FILE` | Builds the config from the robot options or loads the file (see "The robot options"), runs `NaoqiSim.start()`, prints the NAOqi version (read from the `NaoqiSim` service) and `sim.url` once ready (`NAOqi 2.8 (sim): NAOqi 2.8.7.4 ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)`) and, when the `controls` block is on, the controls' address (`NAOqi 2.8 (sim): controls at http://127.0.0.1:9564/`), then stays in the foreground until Ctrl-C (or `SIGTERM`), which runs `NaoqiSim.stop()` |
| `naoqi-sim config --naoqi VERSION [options]`, or `naoqi-sim config --config FILE` | Prints the config `run` would run with the same arguments, as JSON with every field, and starts nothing (see "The `config` command") |
| `naoqi-sim fetch-meshes [--archive PATH] [--force] [--remove]` | Hands over to naoqi-viewer's own `fetch-meshes` with the same options, and returns its exit code: Aldebaran's NAO meshes for the sim window, installed after its license prompt ([viewer.md](../host/viewer.md)). naoqi-viewer owns the license, the download and the install, and the meshes never pass through naoqi-sim; the command exists so that every step of an install is a `naoqi-sim` command (a tool install exposes only naoqi-sim's own). Without the `viewer` extra it exits 1 naming it |
| `naoqi-sim cleanup` | Removes what a run that died without stopping left behind (see "Foreground runs") |
| `naoqi-sim status` | Prints `read_status()` ([api.md](api.md), "Without a `NaoqiSim` object"): each container's state and health, then the `NaoqiSim` service's versions, readiness and device sources |
| `naoqi-sim logs [--follow] [--tail N]` | The containers' logs: `docker compose -p naoqi-sim logs`, with these two options passed through |

- `naoqi-sim probe` (the capability report, [_overview.md](../_overview.md), "Capability probe") is deferred with the probe: it gets its spec when the 2.8 validation milestone needs committed reports.
- The API is async: each command runs its coroutine with `asyncio.run`; Ctrl-C cancels it, and `run` still awaits `stop()` on the way out.
- **How `run` hears Ctrl-C.** On Linux and macOS through the event loop (`loop.add_signal_handler`, for `SIGINT` and `SIGTERM`). Windows' event loops have none (`NotImplementedError`), and Windows never delivers `SIGTERM`: there `run` installs plain handlers for `SIGINT` (Ctrl-C) and `SIGBREAK` (Ctrl-Break) that hand over to the loop (`call_soon_threadsafe`), and keeps a 0.1 s tick on the loop so that Python runs them promptly even while the loop waits for I/O. Ctrl-Break matters because it is the console signal another process can send on Windows (`CTRL_BREAK_EVENT` to a process started in its own process group, as the live tier's end-to-end `run` test does there; Windows cannot send a process `SIGINT`). The fast tier drives `run` both ways on every platform, with real signals (`signal.raise_signal`; `os.kill` on Windows terminates the process instead), and Ctrl-Break on Windows.
- `run` starts nothing itself: every check (Docker, the images, the `viewer` extra, ports) happens in `NaoqiSim.start()` ([api.md](api.md), "Lifecycle"), and the CLI prints the error's message.
- **Exit codes**: a `ConfigError` exits 2 with its message (it names the key path); any other `NaoqiSimError` exits 1 with its message; Ctrl-C after a successful start exits 0 once `stop()` has run.
- **`status` answers in its exit code** too, for scripts: 0 when the robot is ready (`NaoqiSim/Ready` read from the service), 1 otherwise, with `naoqi-sim is not running` when no container runs.
- `logging.basicConfig` is called here, never in the library; `--verbose` raises the level to `DEBUG`.
- **`run` shows the start's progress** on stderr: the INFO lines of `NaoqiSim.start()` ([api.md](api.md), "Progress"), each step, and what a slow boot is still waiting for; `--verbose` adds the container's whole log. Its own lines (ready on stdout once the start returns, start cancelled on stderr) start with the same `NAOqi <version> (sim): `.

### The robot options

`run` and `config` take the same description of the robot, in one of two ways, never both:

| Option | Sets | Needs |
| --- | --- | --- |
| `--naoqi VERSION` | `naoqi.version`: `2.1` or `2.8`. Required | |
| `--robot TYPE` | `robot.type` (`nao`); left out, the NAOqi version's default robot | |
| `--robot-version VERSION` | `robot.version` (`v4`, `v5`, `v6`); left out, the NAOqi version's default (`v5` on 2.1, `v6` on 2.8) | |
| `--viewer` | The sim window (`viewer.headless` false) with both camera pictures and the people (`cameras_display`, `people_display`), and both head cameras on `render` | The `viewer` extra |
| `--webcam` | The top camera on `webcam`. The bottom one stays as it is: `render` with `--viewer`, unfed without | The `webcam` extra |
| `--mic` | `audio_input.source` `mic`: the robot hears the host microphone | |
| `--controls` | The controls page served and opened in the browser (`controls.enabled` and `controls.open`) | |
| `--config FILE` | The whole config, from a `NaoqiSimConfig` JSON file, instead of every option above | |

- **`--naoqi` is required**: `naoqi-sim run` alone exits 2 with `which NAOqi? --naoqi 2.1 or --naoqi 2.8 (or --config FILE for a config of your own)`. There is no default NAOqi version, on the command line as in the config ([config.md](config.md)).
- **`--naoqi` alone works on a plain install**: that NAOqi's default robot, speaking on the host loudspeaker, with no window, no camera, no microphone and no page, so with no extra. Each thing a person turns on is one option, and nothing captures the host (its microphone, its webcam) without being asked.
- **The options or a file, never both.** With `--config`, any robot option is an error (`--config describes the whole robot: drop --naoqi, --viewer, or set them in the file`, exit 2): no option overrides a field of a file, so a run from a file is always reproducible from that file alone, and there is never a question of which one wins.
- **The options are the usual choices, not a second config.** Anything else (the languages, Life at boot, the posture, the scene, the audio modes, the ports) is a field of a config file. The options build a `NaoqiSimConfig` through `from_dict`, so a wrong value gets the config's own error with its key path (`naoqi-sim run --naoqi 2.8 --robot-version v5` exits 2 with `robot.version: NAOqi 2.8 does not run a nao v5; it runs: nao v6`).
- **A missing extra fails at the start, before any container**: `NaoqiSim.start()` checks it at its first step ([api.md](api.md), "Lifecycle") and the error names the extra.

### The `config` command

`naoqi-sim config` prints, on stdout, the config `run` would run with the same arguments: JSON with every field of every block at its value, the robot's type and version filled in. It checks nothing but the config (no Docker, no image, no extra) and starts nothing.

- **It is how a config file of one's own starts**: `naoqi-sim config --naoqi 2.8 --viewer --mic > my-nao.json`, change the fields, then `naoqi-sim run --config my-nao.json`. Saved and run, the output runs exactly what the options would.
- **With `--config FILE`** it prints that file with every default filled in, which checks the file and shows the fields it left out; a `ConfigError` exits 2 with its key path, as for `run`.
- A command of its own rather than a `run --print-config`: `run` always runs, and the command is listed in `naoqi-sim --help`.
- `examples/configs/2.1.json` and `2.8.json` are its output with `--viewer --webcam --mic --controls` ([config.md](config.md), "Example files").

### Foreground runs

`run` stays in the foreground: the host side of the robot (the audio output, later the audio and video inputs and the viewer window, which on macOS must stay in a process the user launched) lives in its process, and Ctrl-C stops everything in that same process with `NaoqiSim.stop()`, logs in view. There is no detached mode and no pid file. A caller that needs naoqi-sim in the background uses the API ([api.md](api.md)), or a shell's `&`, tmux and the like. The name says it: `run`, as `docker run` or `uv run`, not compose's `up`/`down` pair, which suggests a detached stack.

- **`naoqi-sim cleanup`** is for a run that died without stopping (killed, crashed, laptop closed): it runs `cleanup()` ([api.md](api.md)), which removes the `naoqi-sim` compose project's containers, every profile, keeping the package store volumes, and prints what it removed. If a run is still alive (port 9562, the audio output's, is taken), it changes nothing, says to press Ctrl-C in that run's terminal and exits 1.
- **`naoqi-sim status` and `naoqi-sim logs`** work from any terminal: they read Docker and the `NaoqiSim` service, so they need no pid file either.
- **Closing the sim window** does not end `run`: the robot keeps running and the terminal says so ([api.md](api.md), "Lifecycle"); Ctrl-C stops it.

### Existing commands

The former `naoqi-sim-fetch-suite` is now `naoqi-sim fetch-and-build-images`. The former `naoqi-sim-speaker` is gone: the audio output is part of a running `NaoqiSim` ([audio-output.md](../host/audio-output.md)) and has no command of its own. Recording what the robot says is `audio_output.mode = "record"` in the config, and debugging a stack is `naoqi-sim run` with `naoqi-sim logs`.

## Open questions

1. **A detached mode** (`run --detach`, with a pid file in the user's runtime directory) is deferred until a real need appears; it would not change the foreground default.
