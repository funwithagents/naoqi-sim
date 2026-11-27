---
code:
  - src/naoqi_sim/controls.py
  - src/naoqi_sim/controls.html
  - src/naoqi_sim/config.py
  - src/naoqi_sim/sim.py
  - src/naoqi_sim/video_input.py
  - src/naoqi_sim/cli.py
tests:
  - tests/test_controls.py
  - tests/test_config.py
  - tests/test_sim.py
  - tests/test_cli.py
  - tests/test_video_input.py
  - tests-e2e/test_touch_live.py
---

# Controls

**Status:** Implemented

## Purpose

What a person standing next to a NAO does to it with their hands, on a simulated one: touch its head, hold three sensors for three seconds, put a hand over its camera. The controls are a small web page a running `NaoqiSim` serves, with a button for each of these, and the HTTP API behind the page, which any program can call.

The controls own no signal. Each control drives the device or module that owns its signal: the touch sensors are the touch input's ([touch-input.md](touch-input.md)), the camera cover the video input's ([video-input.md](video-input.md)). A test in Python calls those through the `NaoqiSim` object and needs no page; the page is for a person, and its HTTP API for a program that is not Python or not the one that owns the `NaoqiSim`. More signals of the simulated robot get their control here as they are built (open question 1).

## Decided

Decided Nov 25, 2026; the block's name, `controls`, is the user's.

### Why a page

- **Not the sim window.** naoqi-viewer's window ([viewer.md](viewer.md)) shows text, shapes in the scene and takes a few function keys; it has no buttons, and a mouse holds one thing at a time. The gesture that stops an activity on a NAO 2.1 is three sensors held 3 s ([touch-input.md](touch-input.md)).
- **It works without a window**: with a headless viewer, with no viewer, from another machine's browser through a tunnel.
- **No dependency**: Python's standard HTTP server and one static page; no GUI toolkit on three operating systems.
- The sim window stays where touches are seen, once naoqi-viewer shows the pressed sensors on the robot ([touch-input.md](touch-input.md), open question 1).

### The config block

```json
"controls": { "enabled": true, "port": 9564, "open": false }
```

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Serve the controls. Off by default: a library caller and a test drive the devices in Python |
| `port` | `9564` | The port, on `127.0.0.1` only |
| `open` | `false` | Open the page in the default browser once the robot is ready |

- The block is [config.md](../runtime/config.md)'s; `examples/configs/controls.json` turns it on, with both cameras rendered so the top one can be covered. `naoqi-sim run` does not turn it on by itself (decided Nov 27, 2026): off stays the default everywhere.
- `NaoqiSim.start()` checks the port is free with the others (step 1), starts the server after the input devices (step 7) and logs the page's address, which `naoqi-sim run` prints too; `stop()` stops it first and releases what it holds. `NaoqiSim.controls_url` is the address, `None` when the block is off.

### The page

One page, no build step, no external resource, shipped as package data (`src/naoqi_sim/controls.html`, served at `/`). It shows the robot's state as the server reports it, whoever changed it (the page, another page, a test in Python), polled a few times a second.

- **Touch**: an outline of the robot with its 13 sensors, the pressed ones lit, the ones the controls hold outlined. A click taps a sensor (0.2 s); a shift-click latches it until shift-clicked again, so several are held at once. "Head" presses or releases the three head sensors together; "Release all" releases everything the controls hold.
- **Hold for**: a duration field and a button, which lets go of the latched sensors and taps them together for that long.
- **Cameras**: a "covered" switch per head camera, disabled for a camera with no source.
- **Gestures**: "Stop the activity", which does the running version's gesture ([touch-input.md](touch-input.md), "What a touch does"): on 2.1 the three head sensors for 3.5 s; on 2.8 the top camera covered, the front sensor for 2 s, the camera uncovered.

### The HTTP API

JSON over HTTP on the same port; the page uses nothing else.

| Request | Body | Does |
| --- | --- | --- |
| `GET /` | | The page |
| `GET /api/state` | | `{"naoqi_version", "touch": {"pressed": [...], "held": [...]}, "cameras": {"top": {"covered": false, "fed": true}, "bottom": {...}}}`: `pressed` by anyone, `held` by the controls |
| `POST /api/touch/press` | `{"sensors": [...]}` | Presses them together |
| `POST /api/touch/release` | `{"sensors": [...]}`, or `{}` for all the controls hold | Releases them |
| `POST /api/touch/tap` | `{"sensors": [...], "duration_s": 0.2}` | Presses, waits, releases; answers at the release |
| `POST /api/cameras/<top or bottom>` | `{"covered": true}` | Covers or uncovers the camera |
| `POST /api/gestures/stop-activity` | | The version's stop gesture ("The gesture"); answers when it is done |

Every `POST` answers the state as `GET /api/state` does, after the change.

- Sensor names are the touch input's, `"Head"` included. An unknown sensor, camera or gesture, a missing sensor list or a tap's `duration_s` outside 0 to 60 s answers 400 with `{"error": ...}`; an unknown path 404; a control whose device is not running (a camera with no source) 409; a failure inside NAOqi 500, with its message. Requests are served on their own threads, so a tap or a gesture in progress does not hold the page; gestures run one at a time.
- What the controls press is theirs: the touch input keeps a sensor pressed while the controls or the Python API hold it ([touch-input.md](touch-input.md), "The device"). The server releases its holds when it stops.
- **Local only.** The server binds `127.0.0.1` and has no authentication. Because any web page open in the user's browser can send requests to a local port, it refuses a request whose `Host` is not its own address (`127.0.0.1:<port>` or `localhost:<port>`) with 403, a `POST` whose `Origin` is another site's with 403, and one whose content type is not `application/json` with 415 (a form can post `text/plain` across sites without asking).

### The gesture

`stop_activity_gesture` in `controls.py`, which `sim.stop_activity_gesture()` runs with the API's hands and the controls with theirs:

- **2.1**: the three head sensors pressed together, held 3.5 s (past the 3 s threshold, [touch-input.md](touch-input.md)), released.
- **2.8**: the top camera covered, 0.5 s for the covered frames to reach [brightness-statistics.md](../services/brightness-statistics.md), the front sensor held 2 s (inside Life's 1 to 2.9 s window) and released, 0.5 s more so the release is seen while dark, as a hand leaves the head before the forehead, then the camera uncovered, unless it was covered before the gesture. `CameraNotFedError` (409 over HTTP) without a fed top camera.

Life stops the activity a few seconds after the release on both versions (2.6 s on the 2.1 sim, 0 to 3 s on 2.8); the gesture does not wait for it.

### The camera cover

A covered camera sees what a hand over it gives, whatever feeds the camera: the video input injects a dark frame in place of its source's. On a real NAO 2.1 a hand over the top camera measures a mean of 17.5 and a deviation of 0.5 in 8-bit luminance, against 40 to 140 and 12 to 60 for the room (Nov 25, 2026); the dark frame is the grey that NAOqi turns into a luminance of 17.5 ([video-input.md](video-input.md), "The camera cover"). In Python: `await sim.cover_camera("top")`, `await sim.uncover_camera("top")`; [video-input.md](video-input.md), "The camera cover". What reads it:

- **2.8's stop gesture**, through [brightness-statistics.md](../services/brightness-statistics.md).
- **The people the robot tracks**: a covered camera loses them. On a NAO 2.1 the user session manager then asks the interactive activities to exit after 4 s, which the main dialog obeys (measured Nov 25, 2026).

### Specs this work changed

[config.md](../runtime/config.md) (the `controls` block, `controls.json`), [api.md](../runtime/api.md) (`sim.touch`, `cover_camera`, `stop_activity_gesture`, `controls_url`, `CameraNotFedError`, the lifecycle steps), [video-input.md](video-input.md) (the cover), [devices.md](devices.md) (the touch input's row; the controls are not a device), [cli.md](../runtime/cli.md) (`run` prints the address).

### Tests

- **Fast tier** (`tests/test_controls.py`): the server over the real touch input and video input on fake NAOqi services: each request changes the device as the table says and `GET /api/state` shows it; the 400, 404 and 409 answers; the refused `Host`, `Origin` and content type; the holds released at stop; the page is served, names every sensor and loads nothing external; each version's gesture, step by step.
- **Live tier** (`tests-e2e/test_touch_live.py`, the live tier runs with the controls on): through HTTP, a press reaches `ALTouch` and its event and the stop gesture stops a focused activity, on both versions.

## Open questions

Decided Nov 27, 2026: `naoqi-sim run` leaves the controls off unless the config turns them on. Every question left is a deferral.

1. **More controls.** Candidates, each added with the signal's owner, none designed: the battery level and the charger, a push and a fall, the joints' temperature, a sound played into the fake microphone ([audio-input.md](audio-input.md)), a prop put in front of the robot ([props.md](props.md)).
2. **A command.** `naoqi-sim touch Head --for 3.5` and the like from another terminal, over this API. Deferred: `curl` does it today.
3. **The page's state transport.** Polling is enough for a handful of switches; server-sent events if the page gains anything that moves fast.
