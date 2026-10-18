---
code:
  - src/naoqi_sim/sim.py
  - src/naoqi_sim/stack.py
  - src/naoqi_sim/__init__.py
  - src/naoqi_sim/errors.py
  - src/naoqi_sim/docker_images.py
  - src/naoqi_sim/files.py
  - src/naoqi_sim/audio_output.py
  - docker/compose.yaml
  - tests-e2e/conftest.py
  - tests-e2e/support.py
tests:
  - tests/test_files.py
  - tests/test_sim.py
  - tests/test_stack.py
  - tests/test_docker_images.py
  - tests-e2e/test_naoqisim_live.py
  - tests-e2e/test_docker_images_live.py
  - tests-e2e/test_speech_live.py
---

# API: the simulated NAO (`NaoqiSim`)

**Status:** Implemented

## Purpose

`NaoqiSim` is the one object that runs a simulated NAO on the host: built from a [config](config.md), its `start()` brings up the containers, the host devices and the simulated world, and its `stop()` takes them all down. Every way of running naoqi-sim goes through it, so there is one implementation of the stack's lifecycle:

- the `naoqi-sim` CLI ([cli.md](cli.md)), whose `run` loads a config file, starts a `NaoqiSim` and stays in the foreground;
- the live tests (`tests-e2e/`), which build their stacks from configs instead of driving `docker compose` themselves;
- any Python caller that wants a NAO for the duration of a script, a test or an application: it either awaits a `NaoqiSim`'s start and stops it when done, or uses the naoqi-sim already running on the machine (found with `read_status()`, below) and leaves it running; either way it then talks to the robot with its ordinary qi client, as to a NAO.

It replaces the overview's "one host process started by `naoqi-sim up`" (now `naoqi-sim run`): the host services are what a running `NaoqiSim` owns. A client of the simulated robot never needs it: once started, naoqi-sim is reached at `sim.url` with any qi client, as a NAO.

## Decided

### Construction

- `NaoqiSim(config: NaoqiSimConfig | NaoqiVersion | None = None, *, sink: AudioSink | None = None)`. With no config it uses `NaoqiSimConfig()` ([config.md](config.md)). A bare version string is shorthand for `NaoqiSimConfig(naoqi=NaoqiSettings(version=...))`, so `NaoqiSim("2.8")` is the one-liner.
- `sink` is where the audio output's audio goes ([audio-output.md](../host/audio-output.md), "Audio sinks"). Without one, the config's `audio_output` block picks it: `play` a `DevicePlayer`, `silent` a `NullSink`, `record` a `WavSink`. A test passes a `MemorySink` and asserts on the audio actually played. As in tts-engine, the sink is fixed for the object's lifetime.
- `NaoqiSim.from_dict(data)`, `from_json(text)` and `from_json_file(path)` build the config, then the object (they take the same `sink=`).
- Constructing it does nothing else: no Docker call, no thread, no port opened.
- `config` (read-only) and `running: bool`.

### Lifecycle

The API is **async**: `await sim.start()`, `await sim.stop()`, `async with NaoqiSim(...) as sim:`. Blocking work (Docker, qi calls) runs in `asyncio.to_thread`; the host devices run on their own threads, so nothing they do blocks the caller's event loop. An async caller awaits it directly; the CLI wraps it in `asyncio.run`.

**`await start()`** runs these steps in order, and returns once the robot is ready:

1. **Environment checks**, before anything starts, each failing with its own error (see "Errors"):
   - Docker answers;
   - the images are there: the version's NAOqi image and the `tts` image exist, carry the installed naoqi-sim version (image label `io.naoqi-sim.version`), were built from the recipes as they are now (`io.naoqi-sim.recipes`) and were verified by `fetch_and_build_images` (see "Images"). `start()` never downloads or builds;
   - the `viewer` extra is installed when the config needs it (`headless = false`, or `render` on either camera of `video_input`; the error names the extra), and the `NaoqiViewerConfig` built from the `viewer` block is valid (naoqi-viewer's own check of the scene, re-raised as a `ConfigError` with key `viewer.scene`);
   - every configured source is built (see [config.md](config.md), "Sources not built yet");
   - the audio input's source can run ([audio-input.md](../host/audio-input.md), "Sources"): for `mic`, `sounddevice` imports and a default input device exists (`DeviceUnavailableError`);
   - each webcam a camera's source names can run ([video-input.md](../host/video-input.md), "The webcam source"): the `webcam` extra is installed (`MissingExtraError` naming it), and the `device` opens and gives a frame (`DeviceUnavailableError` naming the device, with the macOS camera permission hint);
   - ports 9559, 9562 and, when the audio input has a source, the host link's 9563 are free (another naoqi-sim, a hand-started stack or audio output).
2. **Audio output and host link**: start the audio output ([audio-output.md](../host/audio-output.md)) in-process, feeding the sink, and, when the audio input has a source, open the host link ([devices.md](../host/devices.md), "The host link") so the containers find it when they boot.
3. **Containers**: `docker compose up -d` (no build) for the `tts` service and the version's NAOqi service, with the environment generated from the config (`NAOQI_SIM_TTS_ENGINE` = `speech.engine`, the version's profile, `2.1` or `2.8`). The compose project is always `naoqi-sim`.
4. **Ready**: wait until the NAOqi container is `healthy` ([status-service.md](../container/status-service.md), "Healthcheck"), up to `naoqi.ready_timeout_s`. A container that exits or turns `unhealthy` fails the start at once, with the end of its log in the error. Verified images can still fail here (a volume, the host), so this wait happens on every start.
5. **Simulated world**: when the config calls for it ([viewer.md](../host/viewer.md), "Which viewer runs"), build a `NaoqiViewer` in sim mode from the `viewer` block and `url`, and `launch()` it (in `asyncio.to_thread`; naoqi-viewer's API is synchronous). Its `LaunchError` fails the start like any other step.
6. **Host devices**: the video input and the audio input, as the config's sources ask ([video-input.md](../host/video-input.md), [audio-input.md](../host/audio-input.md)), after the simulated world because the render camera draws its frames from the viewer; a webcam's capture starts just before the video input and stops just after it. Each writes its `NaoqiSim/*/Source` key. The audio input serves the host link from then on; a fake source also listens to the audio output, so the robot hears its own voice ([audio-input.md](../host/audio-input.md), "The robot hears itself").

**The window closed by the user** stops the viewer only: the robot keeps running, as a NAO does when nobody watches it, so an application or a test that owns the `NaoqiSim` never loses its robot to a click. A `NaoqiSim` notices it from a thread waiting on the viewer (`NaoqiViewer.wait()`) and logs it once, at warning level, saying the robot is still running; it does not reopen the window. What the render camera does then is the video input's business ([video-input.md](../host/video-input.md)).

If any step fails, everything already started is stopped, in reverse order, and the error propagates. Calling `start()` on a running `NaoqiSim` raises `NaoqiSimError`.

**A cancelled `start()`** (Ctrl-C in `naoqi-sim run`) stops what it started too, and only then raises `CancelledError`. A step runs on a thread, which a cancel can't interrupt, so the step in flight runs to its end first (`asyncio.shield`): otherwise the teardown's `compose down` would race a `compose up` still running, and the containers would come up after it. The readiness wait is the exception: an abort event makes it give up at its next poll (1 s), rather than wait out `ready_timeout_s`. The fast tier pins it with a fake `docker` whose `up` takes its time.

**`await stop()`** stops the host devices, the simulated world, the containers (`docker compose down`, keeping the package store volumes), the host link and the audio output, in that order. It carries on through every step even if one fails, then raises the first failure. It is a no-op when not running, and `start()` may follow it.

**`async with NaoqiSim(...) as sim:`** runs `start()` then `stop()` on every way out.

### Progress

A start takes from a few seconds to a minute, most of it in the readiness wait. It logs what it is doing, so a person watching `naoqi-sim run` (or a caller that shows the library's logs) can see it advance and tell where it stalls. Everything goes through `logging.getLogger(__name__)`, at INFO unless said otherwise:

- **`starting`, then each step of `start()` as it begins**: the checks, a webcam being opened (on macOS, with a hint that the system may ask for the camera permission, which otherwise looks like a hang), the audio output and its sink, the containers with their services, the wait for NAOqi to start inside its container (the containers are up by then; it says its timeout) and `NAOqi started` once it is, the viewer (window or headless), the video input with each camera's source, the audio input with its source. No timings: the caller's ready line marks the end.
- **The readiness wait** (`wait_healthy`, shared with the verification of `fetch_and_build_images`) relays the NAOqi container's log as it grows: the entrypoint's `still waiting …` lines at INFO, which a slow boot prints every 10 s naming what it waits for ([status-service.md](../container/status-service.md), "Readiness"), and everything else at DEBUG (the entrypoint's other lines, NAOqi's own output). A boot that goes well adds nothing between the wait and `NAOqi started`. It reads the log with one `docker logs` per poll, keeping count of the lines already relayed; it changes nothing in the containers, so no rebuild is needed.
- **`stopping`** (`stop()`), then each step the teardown undoes, newest first (a failed or cancelled start too), so a `compose down` that takes seconds is visible, and `NAOqi stopped` once every step is undone (a `stop()` that fails raises instead).

Every line starts with `NAOqi <version> (sim): ` (`docker_images.label`), as do those of `fetch_and_build_images` and the lines `naoqi-sim run` prints itself ([cli.md](cli.md)). The ready line belongs to the caller: `naoqi-sim run` prints its own.

### Images: `fetch_and_build_images`

Everything slow or downloaded happens once, before any start, in `await fetch_and_build_images(versions=None)` (CLI: `naoqi-sim fetch-and-build-images [2.1] [2.8]`, [cli.md](cli.md)); with no versions, both. For each version, in order:

1. **Fetch** the image data: the pinned suite and `animations.pkg`, with the rules of [container.md](../container/container.md) ("Fetching the image data": kept when the hash matches, `.part` downloads, extraction from the robot image). It replaces the former `naoqi-sim-fetch-suite` command.
2. **Build** the version's NAOqi image and the `tts` image with the installed naoqi-sim version as build argument (`NAOQI_SIM_VERSION`) and as the label `io.naoqi-sim.version`, and the digest of the recipes as the label `io.naoqi-sim.recipes`: SHA-256 over every file under `docker/` with its relative path, leaving out `image-data/` (pinned by hash already), hidden files and Python caches. Docker's cache keeps a rebuild cheap.
3. **Verify**: boot the version's containers (compose project `naoqi-sim`) until the NAOqi one is `healthy` (within 240 s) and the `tts` engine answers its `/health`, then take them down, whatever happened. The verified image IDs are recorded (`images.json`, see "Files on disk"). A build that does not boot is reported with the end of its log and not recorded.

An unknown version is a `ValueError`. Docker is checked first (`DockerUnavailableError`), and each verification needs port 9559 free (`PortInUseError`); the audio output's 9562 is not used by a boot, so a running audio output does not stop it.

So `start()` only checks: an image missing or not verified raises `ImagesMissingError`, an image built by another naoqi-sim version or from other recipes raises `ImagesOutdatedError` (its override modules are stale, or `docker/` was edited since); both name the command to run. Working on `docker/naoqi/services/` means rerunning `fetch-and-build-images`; the live tier runs it only for a version whose images fail `check_images`.

### Files on disk

| What | From a checkout | Installed (a git dependency) |
| --- | --- | --- |
| Recipes (compose, `naoqi/`: Dockerfiles, entrypoints, healthcheck, `services/`; `tts-engine/`) | `docker/` | `naoqi_sim/docker/`, the package data ([project.md](../project.md), "Distribution") |
| Image data (suites, `animations.pkg`, `hashes.json`) | `docker/image-data/<version>/` | `platformdirs.user_data_dir("naoqi-sim")/image-data/<version>/` |
| `images.json` (verified image IDs) | `docker/image-data/images.json` (gitignored with the image data) | Next to the image data |
| Build context | The recipes folder, with the image data folder of the version as a second, named context | The same |

- `src/naoqi_sim/files.py` decides, once: the recipes are `naoqi_sim/docker/` when the package holds them (an installed wheel), else the checkout's `docker/` (the editable install has no package data). The image data folder is `NAOQI_SIM_IMAGE_DATA` when set, else `docker/image-data/` in a checkout and the user data directory when installed. Every default that names the image data folder (`fetch_and_build_images`, `check_images`, `NaoqiSim.start()`, `--image-data`) comes from there.
- **`NAOQI_SIM_IMAGE_DATA`** lets a machine keep one copy of the suites (1.8 GB for both versions) for a checkout and the projects that depend on naoqi-sim, and lets a test point an installed naoqi-sim at a checkout's image data and verified images.
- **The `image-data` build context.** naoqi-sim passes the image data folder to every `docker compose` call as `NAOQI_SIM_IMAGE_DATA`; compose gives each NAOqi build `additional_contexts: image-data: ${NAOQI_SIM_IMAGE_DATA:-./image-data}/<version>`, and the Dockerfile copies the suite and `animations.pkg` with `COPY --from=image-data` ([container.md](../container/container.md), "Images"). So the recipes are never copied next to the image data, the package data is read in place, and `--image-data DIR` builds from `DIR` (it used to download there while the build still read `docker/image-data/`). A `docker compose` run by hand from a checkout falls back to `./image-data`.

### What a running `NaoqiSim` offers

| Member | Returns | Meaning |
| --- | --- | --- |
| `url` | `str` | `tcp://127.0.0.1:9559`, the address any qi client connects to |
| `await status()` | `NaoqiSimStatus` | Read from the `NaoqiSim` service over qi, in one connect attempt (libqi 3.1.8 fixed the failed connects 3.1.6 needed retries for): `version`, `naoqi_version`, `ready`, `camera_source`, `audio_source` |
| `fake_audio` | `FakeAudioSource` | The fake audio source a test plays sounds through ([audio-input.md](../host/audio-input.md), "The fake source"); `NotRunningError` when not running, `NaoqiSimError` when `audio_input.source` is not `fake` |
| `config` | `NaoqiSimConfig` | The config it was built from |
| `running` | `bool` | Between a successful `start()` and `stop()` |

- `NaoqiSim` holds no qi session of its own for clients: callers open their own (`qi.Session().connect(sim.url)`), exactly as on a NAO. `status()` opens and closes one.
- `url` and `status()` raise `NotRunningError` when not running.

### Without a `NaoqiSim` object

Two functions serve the commands run from another terminal than the one that started naoqi-sim ([cli.md](cli.md)), so the CLI holds no Docker or qi logic of its own:

- **`await read_status() -> StackStatus`**: the state of whatever runs on this machine. `containers` lists each container of the `naoqi-sim` compose project with its service, state and health (empty when nothing runs); `naoqi` is the `NaoqiSimStatus` read from the `NaoqiSim` service on `tcp://127.0.0.1:9559` (with the connect retry), or `None` when no NAOqi container is `healthy`. `NaoqiSim.status()` uses the same reader for its `NaoqiSimStatus`.
- **`await cleanup() -> list[str]`**: removes what a `NaoqiSim` that died without stopping left behind (killed, crashed): `docker compose --profile '*' down` on the `naoqi-sim` project, keeping the package store volumes, and returns the names of the containers removed. If a naoqi-sim is still running (port 9562, the audio output's, is taken), it removes nothing and raises `NaoqiSimError` saying so.

Both check Docker first (`DockerUnavailableError`).

### Errors

| Error | Raised for |
| --- | --- |
| `NaoqiSimError(RuntimeError)` | The base of naoqi-sim's own errors; raised as such for lifecycle misuse (a double `start()`) |
| `NotRunningError(NaoqiSimError)` | `url` or `status()` when not running |
| `DockerUnavailableError`, `ImagesMissingError`, `ImagesOutdatedError`, `MissingExtraError`, `DeviceNotBuiltError`, `DeviceUnavailableError`, `PortInUseError` (each a `NaoqiSimError`) | Step 1 of `start()`, each naming what to do (start Docker, run `naoqi-sim fetch-and-build-images`, `naoqi-sim[viewer]` or `naoqi-sim[webcam]`, which device is missing, which host device or library is unavailable (no PortAudio, no default input device, a webcam that does not open), which port is taken) |
| `BootError(NaoqiSimError)` | The NAOqi container exited, turned `unhealthy` or was not `healthy` within `ready_timeout_s` (at start or at verification); carries the end of its log |
| `FetchError(NaoqiSimError)`, `ImageBuildError(NaoqiSimError)` | `fetch_and_build_images`: a download or hash failure (naming the file), a failed `docker build` (with the end of its output) |

`ConfigError` ([config.md](config.md)) comes from the loaders, before a `NaoqiSim` exists.

### Naming

The `NaoqiSim` *class* (`naoqi_sim.NaoqiSim`, on the host) keeps the name of the `NaoqiSim` *service* inside NAOqi ([status-service.md](../container/status-service.md)), which naoqi-viewer already relies on: the class starts the stack, the service reports on it from inside, and `status()` reads the service. Specs and logs say "the `NaoqiSim` object" or "the `NaoqiSim` service".

### Front door

`from naoqi_sim import NaoqiSim` re-exports what a caller needs: `NaoqiSim`, `NaoqiSimStatus`, `fetch_and_build_images`, `read_status` and `StackStatus`, `cleanup`, the config classes (`NaoqiSimConfig` and its blocks, the `Literal` types), the audio sinks (`AudioSink`, `DevicePlayer`, `NullSink`, `WavSink`, `MemorySink`), `ConfigError` and the errors above. Library modules only use `logging.getLogger(__name__)`; `logging.basicConfig` belongs to the CLI.

### One naoqi-sim per machine

Ports 9559, 9562 and 9563 are fixed, the compose project name is fixed and the containers have fixed names, so one `NaoqiSim` runs per machine. A second `start()` (in another process or the same one) fails at step 1 with `PortInUseError`. Several instances are a later option (ports in the config; see [config.md](config.md), open questions).

## Open questions

None currently.
