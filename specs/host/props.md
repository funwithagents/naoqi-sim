---
code:
  - src/naoqi_sim/viewer.py
  - src/naoqi_sim/sim.py
tests:
  - tests/test_viewer.py
  - tests/test_sim.py
  - tests-e2e/test_video_input_live.py
---

# Props: objects placed in the simulated world

**Status:** Implemented

## Purpose

What a test puts in front of the simulated robot: a face for a client's detector to find, a red ball for the camera to see where the robot's pose says it is. The simulated world ([viewer.md](viewer.md)) is naoqi-viewer's, and so are the props: naoqi-viewer appends a pool of hidden bodies to every sim-mode scene and shows, moves and hides them on request (naoqi-viewer's `specs/props.md`). naoqi-sim's part is small: a running `NaoqiSim` exposes them as `sim.props`, one call per naoqi-viewer call, and adds what only naoqi-sim knows, the robot's frames. The window and the rendered head cameras are the same model, so what the API says is what the camera sees, at the next frame.

A prop is **sim only**: a real NAO's cameras cannot see a MuJoCo body, and a naoqi-sim without a viewer has no world to put it in. A test that needs a prop runs against a `NaoqiSim` whose config runs the viewer, as the live tier does, and nothing in naoqi-sim pretends otherwise.

Props are the first of the test helpers discussed on Oct 18, 2026. Two others are deferred, as recorded in [_overview.md](../_overview.md) ("Open questions and risks"): injecting people, located sounds and other stimuli straight into ALMemory, which a client will want on a real robot too and so is not naoqi-sim's alone; and injecting images or recordings into the video input, which props cover for the tests at hand. Audio injection exists: `sim.fake_audio` ([audio-input.md](audio-input.md)).

## Decided

### `sim.props`

A running `NaoqiSim` whose config runs the viewer ([viewer.md](viewer.md), "Which viewer runs") has `sim.props`: naoqi-viewer's own `PropsClient`, handed out by the simulated world (`SimWorld.props` in `src/naoqi_sim/viewer.py`) with nothing added:

```python
ball = sim.props.spawn(
    "object", (1.5, 0.0, 0.5), size=0.1, frame="robot"
)  # a red sphere 1.5 m ahead
face = sim.props.spawn(
    "face", (1.0, 0.3, 0.5), frame="robot"
)  # face_1, looking at the robot
sim.props.place(
    face.name, (1.0, -0.3, 0.5), duration=2.0, frame="robot"
)  # walks across in 2 s
sim.props.list()  # {name: PropState}
sim.props.despawn(face.name)
sim.props.clear()
```

- **naoqi-viewer's five calls** (`list`, `spawn`, `place`, `despawn`, `clear`), with its arguments (`frame` among them), kinds (`face`, `object`), shapes, sizes, colours, durations, pool and errors: `PropState` and `PropError` are naoqi-viewer's, re-exported by `naoqi_sim` for callers that want to catch or type them. naoqi-sim adds no prop of its own and keeps no state: `list()` is what the viewer answers.
- **Not running, or no viewer**: `sim.props` raises `NotRunningError` before `start()` and after `stop()`, and `NaoqiSimError` when the config runs no viewer (`viewer.headless` with no camera on `render`), saying what to change. A window closed by the user makes the next call raise naoqi-viewer's `ViewerClosed`, as the video input sees it ([viewer.md](viewer.md), "Window closed").
- **Calls are synchronous**, as naoqi-viewer's API is; a test calls them from its thread, and an `asyncio` caller wraps them in `asyncio.to_thread` as `NaoqiSim` does for the viewer.

### Frames

Positions and orientations are in the **scene's frame** by default (`frame="world"`), which naoqi-viewer identifies with NAOqi's `FRAME_WORLD`: it places the robot at `ALMotion.getTransform("Torso", FRAME_WORLD, True)`. That pose is odometry, about -0.13 rad of heading at boot on both versions and more after gestures ([viewer.md](viewer.md), "In the live tier and CI"), so "1.5 m along x" is not 1.5 m ahead of the robot. `frame="robot"` gives them in NAOqi's `FRAME_ROBOT` instead: origin on the floor at the middle of the feet, x ahead, y to the robot's left.

- **The frame is naoqi-viewer's** (its `props.md`, "Frames"): it computes `FRAME_ROBOT` from the feet it draws, as NAOqi computes `getRobotPosition` from its own, and converts. naoqi-sim passes `frame` through like every other argument, and reads nothing from NAOqi for it.
- The conversion is done once, when the call is answered; a robot that walks afterwards leaves the prop where it was, as a real object stays. The `PropState` returned, like `list()`, is always in the scene's frame. A face's default orientation (looking at the robot) is the viewer's too, in either frame.

### Where to put things

For a standing NAO (`StandInit`), what the head cameras see, from naoqi-viewer's V5 geometry and the pinhole the video input's live test uses (60.97° across VGA, a focal length of 543 pixels):

| Prop | In `FRAME_ROBOT` | In the top camera, head straight |
| --- | --- | --- |
| A face to detect | `(1.0, y, 0.5)`, `|y|` up to 0.4 | Centred in height; the face itself about 70 pixels tall at VGA, 35 at 2 m |
| An object to see | `(1.5, 0, 0.5)`, a sphere of radius 0.1 | About 36 pixels across, a little below the centre row |
| An object for the bottom camera | `(0.6, 0, 0.1)` on the floor | In the bottom camera's view, out of the top's |

The robot's head height varies with the posture (`Crouch` is 0.1 m lower than `StandInit`); a test that needs exact pixels reads the camera's pose from `ALMotion.getPosition("CameraTop", FRAME_ROBOT, True)` and projects, as the live test does.

### In the live tier and CI

The live tier's scene becomes naoqi-viewer's `empty` scene, and each test spawns what it needs and `clear()`s after itself (a fixture): the red pillar of `tests-e2e/scenes/camera-target.xml` and the scene file go, replaced by a red ball (radius 0.1 m) spawned on the floor 1.5 m ahead in `FRAME_ROBOT`, so the pinhole tests of [video-input.md](video-input.md) aim at the world position `spawn` returns: the top camera sees the ball's centre on the column its pose predicts as the head turns, and with the head raised the bottom camera sees it on the row its pose predicts while the top camera looks over it. naoqi-sim does not test the props themselves: `sim.props` is naoqi-viewer's client as is, and what a spawned face or object looks like, upright, unmirrored, where its frame puts it, is naoqi-viewer's fast and live tiers' to check (its `props.md`, "Testing"). The ball tests use a prop only to give the cameras something to look at. The props run headless on CI's software renderer like the rest of the camera loop ([ci.md](../testing/ci.md)).

## Open questions

1. **Props from the config.** `naoqi-sim run` has no way to put a face or an object in the scene without code; a `viewer.props` list in the config (kind, position, frame) spawned at start would give a demo something to look at. Deferred until a user wants it; the `table` scene serves meanwhile.
2. **The robot at the scene's origin**, which would make the two frames coincide at boot: a naoqi-viewer change (its `props.md`, open question 1). The `robot` frame is the answer until then.
3. **A people injector.** A face prop is only a picture; nothing publishes it in ALMemory, so `ALBasicAwareness` ignores it until a client's detector publishes the people-perception contract ([_overview.md](../_overview.md), "Perception and speech recognition", which proved the built-ins react to it). An injector that writes those keys, from a prop's true pose or from positions a test gives, and more generally fake stimuli (located sounds), is deferred: a client will want the same on a real robot, so it is not naoqi-sim's alone.
