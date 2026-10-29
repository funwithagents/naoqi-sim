# naoqi-sim

naoqi-sim is a NAO in a box: NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and Python 2.7 override modules loaded inside it replace the services the desktop NAOqi lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no naoqi-sim-specific code.

- **Containers**: the NAOqi image per version, a `tts` speech engine and a `perception` engine (faces). Every NAOqi-specific decision stays there.
- **Host**: dumb devices named after their role (the audio output, the audio and video inputs; touch planned), Python 3.12–3.13 with libqi. Speech recognition is the clients' job, not naoqi-sim's.
- **Simulated world** (optional): the `naoqi-sim[viewer]` extra pulls naoqi-viewer, whose sim mode poses the NAO model from naoqi-sim's NAOqi in a scene and renders the head cameras that naoqi-sim injects into `ALVideoDevice`; props (faces, objects) a test puts in the scene, which naoqi-sim's own face detection and people perception (designed Oct 29, 2026) turn into faces and people the built-in awareness looks at.

Built and tested on both versions: the container, the service-replacement mechanism, the speech path (`ALTextToSpeech` replacement as a C++ front over a Python core, so the boxes stop a sentence as on a NAO; the `tts` engine), the audio output mixing named streams as a NAO's sound server, the `ALAudioPlayer` replacement (sound files through the suite's libsndfile, mixed with speech), the `NaoqiSim` status service with the Docker healthcheck, and `naoqi-sim run`: the `NaoqiSim` object with its config, the sim window and the CLI; the render cameras (the headless viewer's frames of both head cameras injected into `ALVideoDevice`) and the webcam source (a host camera on either head camera, behind the `webcam` extra), with naoqi-viewer's camera display in the window; the audio input (`ALAudioDevice` with its native relay, the host link, the fake source and the host microphone, the robot hearing its own voice); CI runs both test tiers on both versions, with a virtual audio loopback; another project depends on naoqi-sim from git with uv. Everything else is planned in [_overview.md](_overview.md), the map of the whole project.

## Specs

<!-- One row per concept spec, in the section of its folder. Keep the Status column in sync with each spec's `**Status:**` line. -->

### Project

How the repository is built and laid out.

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions; distribution as a uv git dependency (recipes as package data in the wheel, image data in the user data directory, the `viewer` and `webcam` extras, versions); `qi` from the libqi fork's package index; macOS arm64, Linux x86_64, Windows x64 | Implemented |

### Runtime: `runtime/`

The host-side front door: the config, the `NaoqiSim` object and the `naoqi-sim` command.

| Spec | Description | Status |
|---|---|---|
| [config.md](runtime/config.md) | `NaoqiSimConfig`: which NAOqi version and which host devices (the installed speech languages, `audio_output`, `audio_input`, `video_input` with a block per head camera and its frame rate, viewer with its scene, variant, camera display and people display, `perception` on or off), loaders (`from_dict`/`from_json`/`from_json_file`, `ConfigError` with key paths), embeddable as a block of another program's config, JSON | Implemented |
| [api.md](runtime/api.md) | The `NaoqiSim` object: built from a config, `start()`/`stop()`/`with` lifecycle over the containers, host devices and simulated world, `url`, `status()`, `fake_audio` and `props`, the start's progress logs, errors, `fetch_and_build_images` and `check_images`, `read_status` and `cleanup` for other terminals; the one implementation behind the CLI, the live tests and any Python caller | Implemented |
| [cli.md](runtime/cli.md) | The `naoqi-sim` command: `fetch-and-build-images`, foreground `run --config`, `cleanup`, `status`, `logs` as a thin shell over the API, exit codes; `probe` deferred | Implemented |

### Containers: `container/`

The Docker images and what makes them a NAO: the NAOqi image, how override modules get in, the identity service, the speech engine.

| Spec | Description | Status |
|---|---|---|
| [container.md](container/container.md) | NAOqi 2.1 and 2.8 images, suite and `animations` package download, package store volume, single-port network layout, compose, the entrypoint's configuration interface, the `io.naoqi-sim.version` image label; the entrypoint's autoload copy, with our modules in place of the built-ins; the build files (C++ SDKs, libqi, boost) and the native build stage | Implemented |
| [service-replacement.md](container/service-replacement.md) | Loading override modules into NAOqi, `ALModule` vs qi service per version, replacing a built-in, calling host-registered services (measured on both versions), the native relay for binary arguments, a C++ front for callers that stop by task id (`post`/`pCall`/`wait`/`stop(id)`, qi signals on it, measured on both versions) | Implemented |
| [naoqi-fidelity.md](container/naoqi-fidelity.md) | How each image compares with a NAO of the same version: the modules it runs (the built-ins the 2.1 suite ships but does not load, added), and every difference of the desktop NAOqi, each classified as by design, patched, patchable (with its lever) or a limitation (with its workaround); the levers, cheapest first; a stand-in DCM to investigate | Implemented |
| [status-service.md](container/status-service.md) | `NaoqiSim` status service: identity of a naoqi-sim target (versions, device sources, the perception engine and the stubbed modules, readiness) as a service and ALMemory keys, the entrypoint's readiness guarantees, the Docker healthcheck | Implemented |
| [tts-engine.md](container/tts-engine.md) | Speech engine container: `POST /say` items to audio with exact marker offsets (Piper, one voice per NAOqi language, the installed languages' voices in the image or fetched on first use into a volume, each voice's licence), streamed to the audio output as its `speech` stream | Implemented |
| [perception-engine.md](container/perception-engine.md) | Perception engine container: `POST /detect` a raw RGB frame to faces (boxes, five landmarks, scores) with OpenCV's YuNet, Apache-2.0, native architecture; built, verified and waited for with the others; off by `perception.enabled` | Implemented |

### NAOqi services: `services/`

The NAOqi services naoqi-sim replaces or adds, as Python 2.7 modules inside NAOqi.

| Spec | Description | Status |
|---|---|---|
| [speech.md](services/speech.md) | `ALTextToSpeech` replacement: the measured contract per caller, tags, event sequence, timing, stop, fallback clock, NAOqi's supported languages and the installed ones from the config; a C++ front over the Python core so the Say and Animated Say boxes and `ALAnimatedSpeech` stop by task id, with 2.8's hidden signals on the front | Implemented |
| [audio-device.md](services/audio-device.md) | `ALAudioDevice` replacement: registered directly, NAO's formats and methods, energy, per-subscriber delivery to `processRemote` through the native relay, as a binary | Implemented |
| [audio-player.md](services/audio-player.md) | `ALAudioPlayer` replacement with a NAO's API (files, loaded files, task volume and pan, `stop(id)`, loops, sound sets, `playSine`), decoding WAV/OGG with the suite's libsndfile as a virtual robot does, one audio output stream per task mixed with speech; no shim; a C++ front for `post`/`wait`/`stop(id)` over a Python core | Implemented |
| [face-detection.md](services/face-detection.md) | `ALFaceDetection` added: the extractor API, `FaceDetected` in a NAO's format with NAOqi's own angles and camera poses, the detector reading `ALVideoDevice` at the subscribers' period and posting VGA frames to the perception engine, recognition as empty stubs | Implemented |
| [people-perception.md](services/people-perception.md) | `ALPeoplePerception` replacement: the population built from the detected faces (ids, distance from the face's size, positions in the torso, robot and world frames), the keys and events the built-in awareness, tracker and user session react to, the settings; replaces the built-in in the autoload | Implemented |
| [perception-stubs.md](services/perception-stubs.md) | API-only stubs for the modules that depend on the built-in people perception's modularity graph (`ALEngagementZones`, `ALGazeAnalysis`, `ALSittingPeopleDetection`, `ALWavingDetection` on 2.8) and a typed `_UserIdentification` so 2.8's user sessions open; one table-driven stub per object model; 2.8's tracking processes kept, their shared settings loaded by a C++ autoload entry | Implemented |

### Host: `host/`

The simulated robot's inputs and outputs on the host, owned by a running `NaoqiSim`, each named after its role; and the simulated world.

| Spec | Description | Status |
|---|---|---|
| [devices.md](host/devices.md) | The contract every host device follows (owned by `NaoqiSim`, config block named after the device, pluggable edge, CI-testable end first, `Source` key, real time, qi when qi suffices) and the host link (port 9563, containers connect out, toolkit framing) | Implemented |
| [audio-output.md](host/audio-output.md) | The robot's loudspeakers, as a NAO's sound server: TCP PCM protocol with named streams (newest wins within a name; `stop`, `set`, `pause`/`resume`), a mixer at 48 kHz stereo with volume and pan, the `AudioSink` seam receiving the mix (device, null, WAV, memory with each stream kept), playing state, listeners (the fake room hears the mix) | Implemented |
| [audio-input.md](host/audio-input.md) | The robot's microphones: the fake source tests play sounds into and the host microphone, every format produced on the host, mono policy, 85 ms chunks (provisional), the robot hearing itself (no gate), messages on the host link, loopback tests | Implemented |
| [video-input.md](host/video-input.md) | The robot's head cameras: naoqi-viewer render and the host webcam (OpenCV behind the `webcam` extra, centre-cropped to 4:3), VGA frames of `CameraTop` and `CameraBottom` injected with `putImage` at a fixed `fps` per camera whoever subscribes, NAOqi converting per subscriber; measured on both versions | Implemented |
| [touch-input.md](host/touch-input.md) | The robot's touch sensors: clicks in the sim window and an API for tests, written to ALMemory | Draft |
| [viewer.md](host/viewer.md) | The simulated world: naoqi-viewer's sim mode driven through its public API, which viewer runs, the `viewer` extra, the window closed by the user, the camera display (both head cameras from `ALVideoDevice` in the window), the people display (a client's people from ALMemory as markers), headless with the render camera in the live tier and CI | Implemented |
| [props.md](host/props.md) | Props: what a test puts in front of the simulated robot, `sim.props` over naoqi-viewer's pool of faces and objects (spawn, place, despawn, clear), poses in the scene's frame or the robot's (naoqi-sim converts through `ALMotion.getRobotPosition`; the viewer is geometry only), the live tier's red ball in place of the pillar scene; people and video injection deferred | Implemented |

### Testing: `testing/`

How naoqi-sim is verified, locally and in CI.

| Spec | Description | Status |
|---|---|---|
| [testing.md](testing/testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, a live tier that drives its own stack per NAOqi version | Implemented |
| [ci.md](testing/ci.md) | GitHub Actions on hosted runners: `check`, `fast-tier`, an `e2e-sim` matrix over 2.1 and 2.8 that builds and caches its images, `NAOQI_SIM_E2E_VERSION` turning skips into failures, a headless viewer; a PulseAudio loopback for the audio tests; the Python 2.7 check | Implemented |

[_overview.md](_overview.md) is the overview of naoqi-sim (goals, architecture, licensing, NAOqi 2.1/2.8 differences, every concept with its state, milestones, open questions). It is reference material without a status; concept specs are extracted from it as work on each concept starts, and the overview section then summarizes and points to the spec. Still only in the overview: the capability probe and the asset guard (both deferred), and the perception measurements kept for clients.

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
