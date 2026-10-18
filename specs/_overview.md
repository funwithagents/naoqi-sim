# naoqi-sim — Overview

naoqi-sim is a NAO in a box. NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and override modules loaded inside it replace the services a desktop virtual robot lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no naoqi-sim-specific code.

It is unofficial and MIT-licensed, not affiliated with Aldebaran, and ships no Aldebaran assets.

This overview is the map of the whole project and the authority for naoqi-sim. Each concept gets its own spec (see [_index.md](_index.md)) when work on it starts; until then, its section here is the reference. Sections whose concept has a spec only summarize it and link to it.

## Goals

- Existing qi code, including Choregraphe behaviours, runs on naoqi-sim on NAOqi 2.1.4.13 and 2.8 and gets speech, audio and camera images through the standard NAOqi services, with their documented methods, events and timing. naoqi-sim provides what a NAO's hardware provides; perception and speech recognition run in the clients (see [Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)).
- One command (`naoqi-sim run`, after the one-time `naoqi-sim fetch-and-build-images`) reaches a running simulated NAO, given Docker and the user's Choregraphe suite, on the platforms the libqi wheels cover (macOS arm64, Linux x86_64 and Windows x64; see [Packaging](#packaging-and-platforms)).
- No Aldebaran binary, robot package, mesh or derived file lands in the repository, a package or a published image.

## Scope

| In scope | Out of scope |
| --- | --- |
| NAOqi from the user's suite, Docker only, 2.1 and 2.8 | Running NAOqi natively on the host |
| Override modules for the services the desktop NAOqi lacks: speech, audio input, sound files | Reimplementing NAOqi, its walk engine, fall manager, or vision and audio algorithms |
| Host devices: loudspeaker, microphone or sounds played from code, webcam or rendered camera | A physics simulation driving NAOqi (no simulator interface exists for it) |
| The simulated world (window, rendered head cameras), through naoqi-viewer's sim mode | ROS / ROS 2, Webots |
| A capability probe that measures what a NAOqi target offers | Client libraries: they connect to naoqi-sim as to any NAO (one may also run a `NaoqiSim` itself through the [API](runtime/api.md); naoqi-sim never depends on a client) |
|  | The NAO model, the meshes and the 3D rendering: naoqi-viewer owns them |
|  | Perception and speech recognition: no replacement of `ALFaceDetection`, `ALPeoplePerception`, `ALMovementDetection` or `ALSpeechRecognition`; clients run them on the camera and microphone streams |
|  | Robot packages beyond the `animations` package (sound set, `dialog_*`, dances): the user, or a client, installs them as on a robot |

## Architecture

Two containers and one host side. Every NAOqi-specific decision stays in the containers; the host is a set of dumb devices.

| Part | Runs where | Role | Spec |
| --- | --- | --- | --- |
| NAOqi container | Docker, `linux/amd64` | `naoqi-bin` from the user's suite, one image per version, built locally; publishes 9559 only | [container.md](container/container.md) |
| Override modules | Inside NAOqi (Python 2.7, plus one small native relay in C++ where a binary must be sent) | Replace or add NAOqi services in-process, so in-process callers (`ALAnimatedSpeech`, `ALDialog`) and host clients both reach them: `ALTextToSpeech`, `ALAudioDevice`, `ALAudioPlayer`, the `NaoqiSim` status service | [service-replacement.md](container/service-replacement.md); one spec per service in [services/](services/) |
| `tts` container | Docker, native architecture | Turns text, marker and pause items into audio with exact marker offsets (Piper, eSpeak NG) and streams it to the host | [tts-engine.md](container/tts-engine.md) |
| Host devices | Host (Python 3), owned by a running `NaoqiSim` | Audio output (plays the PCM it receives); audio, video and touch inputs planned | [devices.md](host/devices.md), one spec per device in [host/](host/) |
| `NaoqiSim` object and config | Host (Python 3), in the caller's process | Built from a `NaoqiSimConfig`; `start()`/`stop()` run the containers, the host devices and the simulated world. Behind the CLI, the live tests and any Python program that runs a simulated NAO | [api.md](runtime/api.md), [config.md](runtime/config.md) |
| Host link | Containers to host, one TCP port | Carries what qi cannot: microphone PCM into `ALAudioDevice`, its subscriptions out | [devices.md](host/devices.md), "The host link" |
| Simulated world (planned) | Host, naoqi-viewer's own viewer process, started by `NaoqiViewer.launch()` | The NAO model posed from naoqi-sim's NAOqi in a scene, the window, head-camera renders | [viewer.md](host/viewer.md) |
| `naoqi-sim` CLI | Host | `fetch-and-build-images` (built), `run`, `cleanup`, `status`, `logs`, over the `NaoqiSim` object | [cli.md](runtime/cli.md) |

- Clients reach every NAOqi service, built-in or replaced, on `127.0.0.1:9559`, as on a NAO. On 2.8, the suite's own `qi-secure-gateway` serves that port and relays the service processes, as on a NAO 6.
- The containers reach the host through `host.docker.internal` (`host-gateway` on Linux). Today only the `tts` container does, to stream speech to the audio output on 9562.
- Host code that talks to NAOqi uses `qi.Session` and `session.service()` from the libqi Python 3 wheels, never `ALProxy`. One exception lives inside the container: an override module that calls a service a host client registered goes through the broker with `naoqi.ALProxy` (see [service-replacement.md](container/service-replacement.md)).

## Status

| Concept | State |
| --- | --- |
| Container, 2.1 and 2.8 | Built and tested ([container.md](container/container.md)) |
| Service replacement mechanism | Built and tested, used by the speech path ([service-replacement.md](container/service-replacement.md)) |
| `ALTextToSpeech` replacement | Built and tested on both versions: a C++ front over the Python core, so the Say and Animated Say boxes and `ALAnimatedSpeech` stop a sentence as on a NAO ([speech.md](services/speech.md)) |
| `tts` container | Built and tested ([tts-engine.md](container/tts-engine.md)) |
| Audio output | Built and tested: named streams mixed at 48 kHz stereo as a NAO's sound server, with its audio sinks ([audio-output.md](host/audio-output.md)) |
| `NaoqiSim` status service, healthcheck | Built and tested ([status-service.md](container/status-service.md)) |
| `NaoqiSimConfig`, `NaoqiSim` object, CLI | Built and tested: `naoqi-sim run`/`status`/`cleanup`/`logs`, the live tier runs through `NaoqiSim` ([config.md](runtime/config.md), [api.md](runtime/api.md), [cli.md](runtime/cli.md)) |
| Host link | Built and tested, with the audio input ([devices.md](host/devices.md)) |
| Audio input, `ALAudioDevice` replacement | Built and tested on both versions: `ALAudioDevice` with its native relay, the fake source tests play into, the host microphone, the robot hearing its own voice; on CI over a virtual audio loopback ([audio-input.md](host/audio-input.md), [audio-device.md](services/audio-device.md)) |
| Video input | Built and tested with the render source on both versions: VGA frames of both head cameras at `video_input.fps`, NAOqi converting per subscriber; the webcam source on either camera, behind the `webcam` extra ([video-input.md](host/video-input.md)) |
| Touch input | Draft ([touch-input.md](host/touch-input.md)) |
| `ALAudioPlayer` replacement | Built and tested on both versions: a NAO's API, WAV/OGG through the suite's libsndfile, mixed with speech, a C++ front for `stop(id)` ([audio-player.md](services/audio-player.md)) |
| Simulated world (naoqi-viewer sim mode) | Built and tested: the window, and the headless viewer rendering both head cameras for the video input, in the live tier and CI ([viewer.md](host/viewer.md)) |
| Props (`sim.props`: faces and objects in the scene) | Built and tested on both versions: faces and objects spawned in the scene's or the robot's frame, the live tier's red ball and face ([props.md](host/props.md)) |
| Distribution (uv git dependency: wheel with the recipes, user data directory) | Implemented ([project.md](project.md), "Distribution") |
| CI | Implemented ([ci.md](testing/ci.md)) |
| Capability probe | Checked by hand only; deferred (see [below](#capability-probe)) |
| Asset guard | Planned, deferred (see [Licensing](#licensing)) |
| Perception, speech recognition | Not naoqi-sim's: clients |

## Licensing

The code is MIT. Nothing from Aldebaran is in the repository, a package or a published image:

| Asset | Source | How naoqi-sim uses it |
| --- | --- | --- |
| Choregraphe suite (`naoqi-bin`, the Python 2.7 SDK) | Aldebaran's downloads and GitHub repositories, under Aldebaran's terms | Downloaded from Aldebaran's GitHub repositories into `docker/image-data/<version>/` (gitignored) by `naoqi-sim fetch-and-build-images`, or placed there by the user, hash-pinned; the image is built and tagged locally and never pushed |
| `animations` package | Only inside the robot system images (`.opn`, public in the same two repositories) | Extracted from the image by `naoqi-sim fetch-and-build-images` into `docker/image-data/<version>/`, hash-pinned, built into the local image; never in the repository |
| NAOqi C++ SDKs (2.1.4.13, 2.8.7.4) | Aldebaran's public downloads (2.1: `community-static.aldebaran.com`; 2.8: the `aldebaran/nao6-doc-sdk` GitHub repository), under Aldebaran's terms | Downloaded into `docker/image-data/<version>/` by `naoqi-sim fetch-and-build-images`, hash-pinned; only their headers are used, in a builder stage of the image, to compile naoqi-sim's own C++ modules (the native relay, the C++ fronts); neither the SDK nor its headers reach the image ([container.md](container/container.md), "Build files") |
| libqi headers (BSD-3-Clause) and boost headers (Boost Software License), 2.8 only | [funwithagents/libqi](https://github.com/funwithagents/libqi), our fork of Aldebaran's libqi, at a pinned commit; boost's release archive | Same: build files of the 2.8 relay, because the public 2.8 SDK is older than the 2.8.7.4 suite |
| Sound set and other robot packages | The user's own robot (the store that sold them is gone) | Installed by the user into the running sim as on a robot; kept in a local Docker volume |
| NAO meshes and textures (CC BY-NC-ND 4.0) | `ros-naoqi/nao_meshes` installer | Never touched by naoqi-sim: naoqi-viewer fetches them after a typed license acceptance and keeps them in the user's data directory |
| libqi and its Python 3 bindings (BSD-3-Clause) | [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python), a fork of Aldebaran's libqi | Prebuilt wheels from the fork's package index on GitHub Pages, a runtime dependency |

- `.gitignore` covers suite tarballs, `docker/image-data/`, meshes and textures. An automated asset guard (tree, wheel, sdist and Docker build context) is planned and deferred: it gets its spec when packaging starts.
- The suite download fetches Aldebaran's own public files to the user's machine, as the user would by hand; nothing is redistributed. See [container.md](container/container.md).

## NAOqi 2.1 and 2.8

Both lines are supported with one host code base; only the override modules are Python 2.7, and each version has its own image and entrypoint defaults. Each image matches a real NAO **on its own version**, not the other image: the two versions' module sets differ on real robots too (2.8's expressivity and dialog packages, 2.1's removed modules). What the desktop suite leaves out of a version but a NAO on it runs is added back where the suite ships it ([naoqi-fidelity.md](container/naoqi-fidelity.md), "Matching a real NAOqi robot's modules").

| | 2.1.4.13 | 2.8.7.4 |
| --- | --- | --- |
| Image | Ubuntu 14.04, boot about 5 s | Ubuntu 16.04, NAO V6 model, boot about 15 s |
| Public port | `naoqi-bin` broker on 9559 | Suite's gateway on 9559, `naoqi-bin` on loopback 9558 |
| Override object model | `naoqi.ALModule`, registered on the broker | `qi.Session` service, `@qi.multiThreaded()` |
| Replacing a built-in | Its autoload entry left out, ours loaded in its place in NAOqi's boot | Same, in `naoqi-service`'s autoload |

Details and measurements: [container.md](container/container.md) and [service-replacement.md](container/service-replacement.md). The desktop `naoqi-bin` has no `ALSystem`, no version key in ALMemory, no `ALAudioDevice`, no face engine and a stub `ALAudioPlayer`. naoqi-sim fills the identity, audio input and sound-file gaps below; the missing face engine is left to the clients ([Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)).

## Container

Specified in [container.md](container/container.md), including the robot packages: the `animations` package (the `animations/Stand/Gestures/*` behaviours that `ALAnimatedSpeech` runs) is extracted from the public robot image and installed at boot as a system package; the user installs anything else (the sound set) as on a robot, and a volume per version keeps it. Each image also matches the modules a NAO of its version runs: on 2.1 the entrypoint launches the autonomous abilities the desktop suite ships without loading (`ALBasicAwareness`, `ALAutonomousMoves`, blinking, expressiveness), then Autonomous Life after them ("Matching a real NAOqi robot's modules").

The **`NaoqiSim` status service** ([status-service.md](container/status-service.md)) is the identity of a naoqi-sim target: the desktop `naoqi-bin` has no `ALSystem`, so this is how a client learns that the target is naoqi-sim, the naoqi-sim and NAOqi versions, which host devices are attached (`NaoqiSim/Camera/Source`, `NaoqiSim/Audio/Source`, `none` until the devices are built; `NaoqiSim/Audio/Channels` comes with the audio input) and whether boot is complete (`NaoqiSim/Ready`). The Docker healthcheck calls it. naoqi-viewer already relies on it (service exists means `naoqi-sim`), so the name and the keys are a contract between the packages.

## Host services

Specified in [devices.md](host/devices.md): the simulated robot's inputs and outputs, as dumb devices owned by a running `NaoqiSim` ([api.md](runtime/api.md)) in the process that started it (`naoqi-sim run`, a test, a Python program). Each is named after its role and has its own spec in [host/](host/):

| Device | Spec | Through |
| --- | --- | --- |
| Audio output (loudspeaker, WAV, memory) | [audio-output.md](host/audio-output.md) | Its own TCP protocol on 9562, fed by the `tts` engine and later `ALAudioPlayer` |
| Audio input (fake source driven from code, host microphone); the robot hears itself | [audio-input.md](host/audio-input.md) | The host link, into the `ALAudioDevice` replacement |
| Video input (naoqi-viewer render, webcam) | [video-input.md](host/video-input.md) | qi: `ALVideoDevice.putImage` |
| Touch input (clicks in the sim window, the API in tests) | [touch-input.md](host/touch-input.md) | qi: ALMemory |

- The host knows nothing about NAOqi: no tags, no events, no `say()` semantics. Where it needs NAOqi (video injection, touch, the viewer reading joint state), it is an ordinary qi client.
- The **host link** carries only what qi cannot: microphone PCM into the container and the `ALAudioDevice` subscriptions out, on one port the containers connect out to, with the toolkit's framing ([devices.md](host/devices.md), "The host link").
- Each device is built with the end CI can test first (memory sinks, the fake audio source, the render camera), then the one that captures the user. The webcam and the microphone are off by default, enabled by explicit options, with an indicator while live.

## Simulated world: naoqi-viewer

Specified in [viewer.md](host/viewer.md). naoqi-viewer is a separate package (its own repository) that owns the NAO MuJoCo model, the license-gated meshes and the 3D rendering, a kinematic mirror rather than a physics simulation. naoqi-sim drives its **sim mode** through its public API (`NaoqiViewer(config).launch()`, `camera_frame`, `props`, `status()`, `close()`), from its own `viewer` block (`{headless, scene, variant, cameras_display, people_display}`), behind the `naoqi-sim[viewer]` extra:

- a window showing the robot posed from naoqi-sim's NAOqi in a scene (`empty` by default);
- the head-camera renders the video input injects into `ALVideoDevice` (`source = "render"` on a camera of the `video_input` block), which close the loop: NAOqi moves the head, the viewer renders what that camera sees;
- the props a test puts in the scene through `sim.props` ([props.md](host/props.md)): portrait faces for a client's detector to find, coloured objects for the camera to see, spawned, moved and hidden while the robot runs, in the scene's frame or the robot's;
- the people a client publishes in ALMemory, drawn as markers in the window (`viewer.people_display`);
- later, clicks on the robot that the touch input turns into touches.

The viewer process only reads NAOqi; everything NAOqi-specific stays in naoqi-sim. Without the extra, naoqi-sim runs with no window and no render camera, and every NAOqi API still works. The live tier and CI run it headless with the render camera from the start ([ci.md](testing/ci.md)).

## Speech

`ALTextToSpeech.say()` is served by a replacement loaded inside NAOqi. It sends each sentence to the `tts` container, which synthesizes it and streams the PCM to the host audio output, and it raises the NAOqi events itself, on its own clock, from the timings the engine returns. Specified in [speech.md](services/speech.md), [tts-engine.md](container/tts-engine.md) and [audio-output.md](host/audio-output.md). The robot hears its own voice through its microphones, as a NAO does ([audio-input.md](host/audio-input.md), "The robot hears itself"). Kept here: the fallback.

### Fallback: listening to TTS events

If a NAOqi version did not allow replacing the built-in `ALTextToSpeech`, the host would listen to its ALMemory events and speak each sentence. The built-in's simulated clock then decides alone when a sentence ends (0.204 s per token, measured on 2.1), so:

- a blocking `say()` returns before the voice finishes;
- `ALAnimatedSpeech` gestures follow NAOqi's timeline, not the voice, and drift;
- `ALDialog` may take its turn too early.

No such version is known: the replacement works on 2.1 and 2.8. The probe's TTS timing check would size the error for a version that needed it.

## Media: camera and microphone

Clients get camera images and microphone audio through the standard NAOqi services, with NAO conventions throughout: resolutions (QVGA, VGA), colorspace names, the NAO cameras' field of view, microphone names (front, rear, left, right), and timestamps on every frame and chunk. naoqi-sim publishes its sources in ALMemory, so a client can tell, for example, a mono microphone duplicated to four channels.

| | NAOqi side | Host side |
| --- | --- | --- |
| Video | `ALVideoDevice` as shipped (`VideoDevice.xml` already selects the simulator), fed with the public `putImage`: no module | [video-input.md](host/video-input.md): naoqi-viewer render first, webcam after; VGA frames of both head cameras at a fixed rate, NAOqi converting per subscriber |
| Audio in | A replacement `ALAudioDevice`, [audio-device.md](services/audio-device.md) | [audio-input.md](host/audio-input.md): the fake source first, host microphone after; the robot hears itself |
| Sound files | A replacement `ALAudioPlayer`, mixed with speech in the audio output, [audio-player.md](services/audio-player.md) | [audio-output.md](host/audio-output.md) |

## Perception and speech recognition: on the clients

naoqi-sim provides what a NAO's hardware provides (camera images, microphone audio, a loudspeaker, touch) through the standard NAOqi services, and replaces no perception or speech recognition module. Face, people and movement detection and speech recognition run in the clients on the frames they read from `ALVideoDevice` and the audio they read from `ALAudioDevice`, so the same code runs on naoqi-sim and on a real NAO. As a consequence, code that relies on NAOqi's own detectors or recognizer (`FaceDetected` events, `ALDialog`, the Choregraphe face and speech recognition boxes) gets no results on naoqi-sim.

What was measured on both desktop suites (Oct 8, 2026) stays here as the reference for those clients:

- Neither suite ships a face engine: 2.1 has no `ALFaceDetection`; 2.8 launches `HumanPerception` as `hp.registerWithoutOkao` and it is not running. The face engine only exists in the robot system image.
- `ALPeoplePerception` and `ALMovementDetection` exist on both and run their `ALModularity` processes on the injected frames (bound at 5 Hz, frames read back correctly), yet produce nothing: an empty population on 2.8, no output on 2.1, no movement events even with moving frames. The modularity graph cannot be fed from outside and its programs are compiled into the libraries: a dead end, not a bug.
- Once started, `ALBasicAwareness` subscribes to exactly three inputs on both versions: `PeoplePerception/PopulationUpdated`, `MovementDetection/MovementDetected` and `TouchChanged` (plus preference events). It tracks people with `ALTracker`'s `People` target, which reads the `PeoplePerception/Person/<id>/Position*` keys.
- **The built-in `ALBasicAwareness` and `ALTracker` work on naoqi-sim once a client publishes the people-perception contract in ALMemory.** Fake-population test: the host inserts `PeoplePerception/PeopleList`, `VisiblePeopleList`, `NonVisiblePeopleList` and the `Person/<id>/` keys (`PositionInTorsoFrame`, `PositionInRobotFrame`, `PositionInWorldFrame`, `Distance`, `AnglesYawPitch`, `IsVisible`, `IsFaceDetected`, `NotSeenSince`, `PresentSince`, `RealHeight`), raises `JustArrived` once and `PopulationUpdated` plus `PeopleDetected` at 5 Hz. On 2.1 and 2.8, `ALBasicAwareness` raises `StimulusDetected "People"` and `HumanTracked 42`, `ALTracker` switches to its servoing target, and the head turns toward the person (HeadYaw 0.74 rad for a person at 0.6 rad). 2.8 briefly reports `HumanLost` then re-tracks, to tune with the update cadence. Both built-ins are kept as they are.
- 2.1 does not autoload `basicawareness`; `ALLauncher.launchLocal("basicawareness")` registers it (only its sound stimulus fails to initialise). On 2.8 it is the `expressivity.basicawareness` package service, running by default. A NAO has it on both versions, so naoqi-sim's 2.1 entrypoint launches it ([naoqi-fidelity.md](container/naoqi-fidelity.md), "Matching a real NAOqi robot's modules").
- Sound stimulus: 2.8's awareness logs "Desktop detected, ALSoundLocalization won't be used", a hard-coded check. 2.1: with a stub `ALSoundLocalization` registered first, the stimulus initialises, but a `SoundLocated` event raised from the host produced no reaction.

## CLI

Specified in [cli.md](runtime/cli.md).

| Command | Purpose |
| --- | --- |
| `naoqi-sim fetch-and-build-images [2.1] [2.8]` | Fetch the image data, build and verify the images: the one slow step, before `run` ([api.md](runtime/api.md), "Images") |
| `naoqi-sim run [--config FILE]` | Load a `NaoqiSimConfig` ([config.md](runtime/config.md); none: the defaults), start a `NaoqiSim` ([api.md](runtime/api.md)) and stay in the foreground until Ctrl-C, which stops everything |
| `naoqi-sim cleanup` | Remove the containers a run that died without stopping left behind |
| `naoqi-sim status` / `naoqi-sim logs` | Health of the containers, the overrides and the host link |

`naoqi-sim probe` (the capability report below) is deferred with the probe.

The CLI is a thin shell over the `NaoqiSim` object: `run` is `NaoqiSim.from_json_file(FILE).start()` then waiting for Ctrl-C, and every check (Docker, verified images, the viewer extra) happens in `start()`. The live tests run their stacks through `NaoqiSim` too.

## Capability probe

Deferred: the probe gets its spec when the NAOqi 2.8 validation milestone needs committed reports; the live tier checks most of these facts meanwhile. `naoqi-sim probe` would measure what a NAOqi target offers, from a Python 3 qi client on the host, and saves a JSON report, so the specs rely on measured facts. It runs against the plain container (overrides off) to learn the baseline, and against naoqi-sim with the overrides on. Reports go to `capabilities/<naoqi-version>-<plain|naoqi-sim>.json` and are committed (facts only, no Aldebaran content).

| Check | Why it matters |
| --- | --- |
| A module loaded into NAOqi registers a service a host client can call | Foundation of the overrides. 2.1 and 2.8: pass |
| A service registered by a host client can be called from inside the container | `ALAudioDevice` calls `processRemote` on host subscribers. 2.1: pass through the broker; fails from a module's own `qi.Session`. 2.8: to confirm |
| Full service list (`session.services()`) | Which modules exist on this target |
| Smoke calls: `ALTextToSpeech.say`, `ALBehaviorManager.getInstalledBehaviors`, `ALAnimatedSpeech`, `ALPackageManager` | Which high-level modules work |
| `ALAudioDevice` registered; is the name free | How the audio override is installed |
| `ALVideoDevice` accepts `SimulatorCam` and `putImage`; frame read back with `getImageRemote` | Camera injection |
| TTS events and timing: `say()` blocking time, start-to-done delay, events raised | Size of the error if the speech fallback were ever needed |
| The built-in `ALTextToSpeech` can be removed and the name re-registered | The speech path. 2.1 and 2.8: pass |
| Recording proxy: a replacement that forwards every call to the renamed built-in and logs calls, arguments and events, driven by `ALAnimatedSpeech`, a Choregraphe Say box and an `ALDialog` topic | The exact contract per caller, without reading Aldebaran code |
| Perception modules loaded, results from injected frames | Documents for clients that the built-in detectors give nothing on naoqi-sim ([Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)) |

These checks are run by hand today, with local scripts.

## Packaging and platforms

Built as [project.md](project.md) ("Distribution") specifies: another project depends on naoqi-sim from GitHub with uv, pinned to a commit or tag; the container recipes ship as package data in the wheel and the image data go to the user data directory; the `viewer` extra; versions baked into the images.

- The libqi wheels (`qi>=3.1.8,<4`, from the fork's package index) exist for macOS 11+ arm64, Linux x86_64 (glibc 2.28+) and Windows x64, Python 3.10–3.15. Installation elsewhere (Intel macOS, Linux arm64) fails by design: naoqi-sim's host side cannot work without qi ([project.md](project.md)). The fast tier runs on all three in CI; the live tier on Linux, and locally on macOS.
- pip is not supported: it ignores uv's sources. It would find `qi` on the libqi index (`--extra-index-url`), but not naoqi-viewer's git pin ([project.md](project.md), open questions).
- Containers: Docker Engine on Linux, Docker Desktop or OrbStack on macOS (amd64 emulation for the NAOqi images on Apple Silicon; the `tts` container is native), Docker Desktop on Windows. Measured on OrbStack and Linux's Docker Engine only.

## Testing

Two tiers ([testing.md](testing/testing.md)): a fast, deterministic `tests/` tier with no Docker, and an opt-in `tests-e2e/` tier that builds, starts and stops each version's stack itself. CI ([ci.md](testing/ci.md)) runs both on GitHub's hosted `ubuntu-24.04` runners, with no self-hosted runner: a static gate, the fast tier, and a live matrix over 2.1 and 2.8 that fetches, builds and caches the images itself (never pushed), with a headless viewer and the render camera. Downstream repositories (naoqi-viewer, client libraries) pin a naoqi-sim commit for their own live jobs; naoqi-sim's CI does not test them.

## Milestones

The toolkit document numbers the milestones across the three packages; naoqi-sim's share is below, with the toolkit's number.

1. **Validation** (done, Oct 8, 2026; toolkit 1): a module loaded into NAOqi serves a host client; a host-registered service is called back from the container; the built-in `ALTextToSpeech` is replaced, with `ALAnimatedSpeech` using the replacement. On 2.1 and 2.8.
2. **Speech path** (done except subtitles; toolkit 7): `ALTextToSpeech` replacement, `tts` container, audio output, under test on both versions (plan [202610081257](../plans/202610081257_baseline-tests-speech-path.md)).
   - Done Oct 12, 2026: the Say and Animated Say boxes stop as on a NAO (the C++ front), and sound files play through the `ALAudioPlayer` replacement, mixed with speech. Still to exit: a Choregraphe behaviour with animated speech and the `animations` package runs with gestures on their words; reference sentences within the agreed duration tolerance.
3. **naoqi-sim run and CI** (done, Oct 9, 2026; toolkit 2 and 4): status service, healthcheck and `fetch-and-build-images`; `NaoqiSimConfig` and the `NaoqiSim` object with the audio sinks and the sim window, `naoqi-sim run`/`cleanup`/`status`/`logs` ([config.md](runtime/config.md), [api.md](runtime/api.md), [cli.md](runtime/cli.md), [audio-output.md](host/audio-output.md), [viewer.md](host/viewer.md)), CI on both versions ([ci.md](testing/ci.md)), the distribution as a uv git dependency ([project.md](project.md)) (all done).
   - Exit (met): `naoqi-sim run` works on Linux and macOS; CI green on both versions.
4. **Media** (toolkit 6), in this order: the render camera ([video-input.md](host/video-input.md), the viewer's headless renders), so CI tests the camera loop from the start (done, Oct 9, 2026); the host link, `ALAudioDevice` and the audio input with the fake source and the host microphone, tested on CI over a virtual audio loopback (done, Oct 10, 2026; [devices.md](host/devices.md), [audio-device.md](services/audio-device.md), [audio-input.md](host/audio-input.md)); the `ALAudioPlayer` replacement with mixing in the audio output (done, Oct 12, 2026; [audio-player.md](services/audio-player.md), [audio-output.md](host/audio-output.md)); the webcam (done, Oct 16, 2026; [video-input.md](host/video-input.md)); then touch ([touch-input.md](host/touch-input.md)).
   - Exit: a vision script and an audio script written against the standard NAOqi services run unchanged on naoqi-sim.
5. **NAOqi 2.8 validation** (toolkit 8): the capability probe and its committed reports for 2.1 and 2.8.

Perception and speech recognition are the clients' ([Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)); naoqi-sim's part is the camera and microphone of milestone 4.

## Open questions and risks

Questions that belong to a concept live in its spec; these cross several.

- [ ] **libqi wheels**: platform coverage beyond macOS arm64, Linux x86_64 and Windows x64 (Intel macOS, Linux arm64), and Python 3.14 for naoqi-sim ([project.md](project.md)).
- [x] **Connect retries**: libqi 3.1.6's `qi.Session.connect()` failed about once in three against NAOqi 2.1 (`disconnected`, instant); 3.1.8 fixed it in the fork (200 plain connects: none failed), and naoqi-sim connects in one attempt.
- [ ] **libqi fork, legacy clients**: the fork's server binds objects only after a service-0 capability message that libqi 2.1 clients never send, so a 2.1 client opening a fresh connection to a libqi 3 service fails. Not needed by this design; patch only if a use case appears.
- [ ] **Docker Desktop**: everything was measured on OrbStack and Linux's Docker Engine; Docker Desktop on macOS, Linux and Windows is to confirm. GitHub's Windows runner can run Linux containers in WSL 2, reachable both ways once its firewalls are opened ([container.md](container/container.md), "Linux containers on GitHub's Windows runner"), and the live tier passed there once (54 passed), host side on Windows, NAOqi 2.1 in WSL 2; Docker Desktop itself is still to run.
- [ ] **Speech duration tolerance**: how close `say()` must be to a NAO's own durations (proposed ±20% per sentence), and the reference values ([speech.md](services/speech.md)).
- **Emulation speed**: the NAOqi images run under amd64 emulation on Apple Silicon. Measured boot is about 5 s (2.1) and 15 s (2.8) with no visible lag; the probe records timing if that changes.
- [ ] **Injecting stimuli into NAOqi** (decided Oct 18, 2026, deferred): a fake population written to ALMemory as the people-perception contract (which the built-in `ALBasicAwareness` and `ALTracker` react to, [above](#perception-and-speech-recognition-on-the-clients)), located sounds and other stimuli, so tests drive behaviours without a detector. A client (naoqi-bridge) will want the same on a real robot, so it is not naoqi-sim's alone; where it lives is to decide with it. The props of [props.md](host/props.md) cover what the cameras see meanwhile.
- [ ] **Injecting images into the video input** (deferred Oct 18, 2026): a `fake` source taking images or recordings from code, the counterpart of `sim.fake_audio`, for recorded faces or pixel-exact fixtures without a viewer. Props cover the tests at hand; the video input's source seam makes it a small addition when one needs it.

Moved to their specs: the sound set ([audio-player.md](services/audio-player.md)), the virtual robot sensors, the sim window's lifecycle and the NAO V6 geometry ([viewer.md](host/viewer.md)), the render-camera throughput ([video-input.md](host/video-input.md)).

## References

- [Simulated robots – Aldebaran 2.1 docs](https://fileadmin.cs.lth.se/robot/nao/doc/dev/tools/robot-simulation.html): what the virtual robot lacks
- [ALTextToSpeech](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/altexttospeech.html) and [ALSpeechRecognition](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/alspeechrecognition.html): TTS and ASR on virtual robots
- [ALVideoDevice](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice.html) and [ALVideoDevice advanced](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice-indepth.html): `SimulatorCam`, `VideoInput.xml`, `putImage`
- [Aldebaran NAO 6 downloads](https://support.aldebaran.com/support/solutions/articles/80001018812-nao-6-downloads): Choregraphe and SDK for NAOqi 2.8
- [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources) and [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries): the pinned suite sources
- [cyberbotics/naoqisim](https://github.com/cyberbotics/naoqisim): deprecated Webots bridge, reference for how NAOqi was wired to a simulator
- [Dutch Nao Team labbook 2026](https://staff.science.uva.nl/a.visser/research/nao/Labbook2026.html): download failures, GitHub mirror, bundled Python 2
- [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python): libqi Python 3 bindings, BSD-3-Clause
