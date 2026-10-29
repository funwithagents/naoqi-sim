---
code:
  - src/naoqi_sim/viewer.py
  - src/naoqi_sim/sim.py
  - pyproject.toml
tests:
  - tests/test_viewer.py
  - tests-e2e/test_video_input_live.py
  - tests/test_sim.py
  - tests-e2e/test_naoqisim_live.py
---

# Viewer: the simulated world

**Status:** Implemented

## Purpose

The NAO in its scene: a window showing the robot posed from naoqi-sim's NAOqi, the head-camera renders the video input injects ([video-input.md](video-input.md)), and later the clicks the touch input turns into touches ([touch-input.md](touch-input.md)). It comes from naoqi-viewer, a separate package that owns the NAO MuJoCo model, the license-gated meshes and the 3D rendering; naoqi-sim drives its **sim mode**, built and specified with naoqi-viewer (its `specs/api.md` and `specs/config.md`).

naoqi-viewer is a kinematic mirror, not a physics simulation: it reads joint angles and the torso pose from NAOqi over qi (`ALMotion.getAngles("Body", True)` and `getTransform("Torso", 1, True)` at 50 Hz), writes them into the model and renders at 60 Hz. The viewer is not a device ([devices.md](devices.md)), but it lives on the host and a running `NaoqiSim` owns it as it owns the devices.

## Decided

### Who does what

| | naoqi-viewer (viewer process) | naoqi-sim (host process) |
| --- | --- | --- |
| Process | Started by `NaoqiViewer.launch()` as its own process (`mjpython` on macOS when windowed), so MuJoCo's window, OpenGL and the macOS main-thread rule stay out of naoqi-sim | Builds the `NaoqiViewer`, launches it, and closes it when the `NaoqiSim` stops |
| Robot pose | Reads it from naoqi-sim's NAOqi over qi, like any client | Nothing: NAOqi is the source of truth |
| Scene | Loads and renders it: a bundled scene (`empty`, the default: a floor and a light; `table`: a low table with objects in front of the robot) or a user MJCF file | Chooses it (`viewer.scene`) |
| Head cameras | Renders RGB frames of `CameraTop`/`CameraBottom` on request, at the robot's current pose | Decides which camera, resolution and rate, converts, calls `putImage` ([video-input.md](video-input.md)) |
| Model variant | Aldebaran's meshes if the user ran `naoqi-viewer fetch-meshes`, else the placeholder visuals | Passes `viewer.variant` through; the meshes never pass through naoqi-sim |
| Props | Appends a pool of hidden faces and objects to every sim-mode scene; spawns, moves and hides them on request, the window and the camera renders agreeing (naoqi-viewer's `props.md`) | Exposes them as `sim.props` and manages NAOqi's frames: a pose relative to the robot converted to the scene's, through `ALMotion.getRobotPosition` ([props.md](props.md)) |
| People markers | Reads `PeoplePerception/` from ALMemory and draws one marker per person in the window, never in a camera render (naoqi-viewer's `people.md`) | Passes `viewer.people_display` through; what writes the keys is a client's detector, not naoqi-sim |

- The viewer process only reads NAOqi. Everything NAOqi-specific (colorspaces, subscriptions, `putImage`, touch events) stays in naoqi-sim, which keeps the viewer generic.

### Configuration

naoqi-sim's `viewer` block ([config.md](../runtime/config.md), "The viewer and the video input") is its own subset, `{headless, scene, variant, cameras_display, people_display}`, not an embedded `NaoqiViewerConfig`. naoqi-sim builds `NaoqiViewerConfig(mode="sim", headless=viewer.headless, cameras_display=viewer.cameras_display, people_display=viewer.people_display, naoqi.url=sim.url, world={scene, variant})`: the mode and the URL follow from running naoqi-sim, so they are not settings; naoqi-viewer's other fields keep its defaults.

`viewer.cameras_display` (off by default, refused with `headless`) turns on naoqi-viewer's camera display, pinned from its commit `8f3976f`: both head cameras as pictures in the window's top-right corner (F10 toggles them), read back from `ALVideoDevice` over qi as any client reads them. On naoqi-sim that is what the video input injected, render or webcam, so the pictures check the camera path end to end and go stale if it stalls; a camera not fed shows NAOqi's placeholder or nothing. Its one QVGA subscription at 10 fps is ignored by the video input, which never looks at subscribers ([video-input.md](video-input.md), "Frames").

`viewer.people_display` (off by default, refused with `headless`) turns on naoqi-viewer's people display: the people NAOqi lists under `PeoplePerception/` in ALMemory, read over qi at 10 Hz while the display subscribes to `ALPeoplePerception` at 200 ms (as the camera display subscribes to `ALVideoDevice`), so the people are computed while someone watches, with no other subscriber needed (naoqi-viewer's commit `bd3b71f`), drawn as labelled spheres at their world positions in the window and never in a camera render. On naoqi-sim those keys come from its own `ALPeoplePerception` replacement, which builds the population from the faces it detects ([people-perception.md](../services/people-perception.md); decided Oct 29, 2026, before that a client had to publish them), so a scene with a face prop shows the portrait and a marker on it, and the gap between the two is the detector's error; a client publishing its own population is drawn the same way.

### Which viewer runs

`viewer.headless` decides the window; the video input decides whether a headless run needs the viewer at all:

| `viewer.headless` | The cameras' `source` | Viewer | Needs `naoqi-sim[viewer]` |
| --- | --- | --- | --- |
| `false` | any | `NaoqiViewer` in sim mode, with its window | Yes |
| `true` | `render` on either camera | `NaoqiViewer` in sim mode, headless (offscreen renders, no display; Mesa's EGL on Linux) | Yes |
| `true` | neither camera rendered (`none` or `webcam`) | None | No |

When the extra is needed and missing, `NaoqiSim.start()` fails before starting anything, with a message naming the extra ([api.md](../runtime/api.md), "Lifecycle").

### The public API only

- `NaoqiViewer(config).launch()` starts the process and returns once it can render (`LaunchError` otherwise, which fails `NaoqiSim.start()` like any other step); `camera_frame(camera, width, height)`; `props` (its `PropsClient`, wrapped as `sim.props`, [props.md](props.md)); `status()`; `close()`. A window closed by the user makes the next call raise `ViewerClosed`.
- Importing `naoqi_viewer` loads neither MuJoCo nor qi, and naoqi-sim imports it lazily, only when the config needs it. The API is synchronous; `NaoqiSim` calls it through `asyncio.to_thread`.
- The viewer process exits when its caller's connection closes, so a `NaoqiSim` that dies never leaves a window behind.

### Window closed

Closing the sim window stops the viewer only; the robot keeps running, and the `NaoqiSim` logs it once and does not reopen the window ([api.md](../runtime/api.md), "Lifecycle"). A NAO does not stop when nobody watches it, and an application or a test that owns the `NaoqiSim` must not lose its robot to a click. Ctrl-C (or `NaoqiSim.stop()`) stops the run.

### Dependency

Through the `naoqi-sim[viewer]` extra, which pulls naoqi-viewer and with it MuJoCo. Without it, naoqi-sim runs with no window and no render camera: every NAOqi API, speech, the audio input and the webcam all work, which suits servers. naoqi-viewer depends on libqi only, never on naoqi-sim, so the chain stays one-way.

- naoqi-viewer is not on PyPI: `[tool.uv.sources]` takes it from its GitHub repository (`funwithagents/naoqi-viewer`), pinned to a commit, as the libqi wheels are taken from theirs, and a project depending on naoqi-sim from git gets that pin with it ([project.md](../project.md), "Distribution"). Its meshes, fetched with `naoqi-viewer fetch-meshes`, are shared by every environment on the machine. The pin is naoqi-viewer's commit `bd3b71f`: its face props show a life-size face ([props.md](props.md), "Where to put things"), which naoqi-sim's people perception sizes its distances on (since `8d696b8`), and its people display subscribes to `ALPeoplePerception`.
- The dev environment installs the extra, so the code that drives the viewer type-checks against naoqi-viewer's real API; the fast tier never launches it.

### In the live tier and CI

The live tier runs the viewer from the start, headless, with the render camera and the placeholder variant: `{"viewer": {"headless": true, "variant": "placeholder"}, "video_input": {"top": {"source": "render"}, "bottom": {"source": "render", "fps": 5}}}`, on naoqi-viewer's `empty` scene. That tests the whole camera loop (a client subscribes, the viewer renders, `putImage` injects, the client reads the frame back) on a runner with no display ([ci.md](../testing/ci.md)). What the cameras look at is spawned through `sim.props` ([props.md](props.md)) and cleared after: a red ball on the floor 1.5 m ahead in the robot's frame, so a test checks that the camera sees it where the top camera's world pose says it should (`ALMotion.getPosition("CameraTop", FRAME_WORLD, True)` against the world position `spawn` returned, a pinhole with 60.97° across), with the head aimed at it and 0.25 rad either side, and loses it when the head turns 1.2 rad away; with the head raised, the bottom camera sees it on the row its pose predicts (a pinhole 47.64° tall) and the top camera looks over it. The robot's frame, not the scene's, because naoqi-viewer places the robot at NAOqi's world pose, which is odometry: -0.133 rad from boot on both versions, and further after gestures (about -0.25 after one wave); `sim.props` converts (`frame="robot"`). Placing the robot at the scene's origin at start is a naoqi-viewer change, to come. The placeholder visuals are enough to assert frames, and CI never accepts the meshes' license.

The window itself needs a display and is checked by a live test that skips without one.

### As built

Both viewers are built: `NaoqiSim` launches the viewer for `headless = false` or `render` on either camera of `video_input`, before the video input, which renders both head cameras through `SimWorld.camera_frame` ([video-input.md](video-input.md)); `stop()` stops the video input, then closes the viewer; a window closed by the user is logged, and the video input stops with it. The live tier runs the headless viewer with the render camera on both versions.

## Open questions

1. **Subtitles.** Showing what the robot says in the window, from the `ALTextToSpeech` replacement's sentences ([speech.md](../services/speech.md)); needs a naoqi-viewer operation.
2. **Virtual robot sensors.** What `getAngles(..., True)` and the ALMemory sensor keys return on the desktop NAOqi (likely the commanded values); it decides how faithful the pose, and so the render camera, are.
3. **NAO V6 geometry.** naoqi-viewer's model is V5; whether 2.8 (NAO V6) needs its own model is open on the naoqi-viewer side.
4. **Indicators and overlays in the window.** The webcam and the microphone show their indicator in the terminal ([devices.md](devices.md), "Off unless asked"); one in the window, like the subtitles, waits for a naoqi-viewer operation.
