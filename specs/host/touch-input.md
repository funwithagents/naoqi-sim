---
code:
  - src/naoqi_sim/touch_input.py
  - src/naoqi_sim/sim.py
tests:
  - tests-e2e/test_robot_software_live.py
  - tests/test_touch_input.py
  - tests/test_sim.py
  - tests-e2e/test_touch_live.py
---

# Touch input

**Status:** Implemented

## Purpose

The robot's touch sensors as a host device ([devices.md](devices.md)): the three head tactile sensors, the six hand sensors and the four foot bumpers. On naoqi-sim a test touches the robot through the API, and a person through the controls page ([controls.md](controls.md)), so code that reacts to touch runs as on a NAO: Choregraphe's tactile head boxes, `ALBasicAwareness`'s touch stimulus, Autonomous Life's gesture that stops the running activity, a client's own handlers.

Several sensors held at once, for a chosen time, is the case that matters: it is how a person stops an activity on a NAO (below), and a mouse click on the robot cannot do it. So the API and the controls page come first, and clicks in the sim window are a later convenience.

## Decided

### The sensors

The 13 sensors `ALTouch.getSensorList()` names on both sims, as on a NAO, by those names:

| Group | Sensors |
| --- | --- |
| Head | `Head/Touch/Front`, `Head/Touch/Middle`, `Head/Touch/Rear` |
| Hands | `LHand/Touch/Back`, `LHand/Touch/Left`, `LHand/Touch/Right`, `RHand/Touch/Back`, `RHand/Touch/Left`, `RHand/Touch/Right` |
| Feet | `LFoot/Bumper/Left`, `LFoot/Bumper/Right`, `RFoot/Bumper/Left`, `RFoot/Bumper/Right` |

The chest button is left out (decided Nov 25, 2026): `ALTouch` does not list it and `ALChestButton` runs on neither sim.

### The device

- **One state, several hands.** The device holds the set of pressed sensors. The API, the controls page and later the sim window all press and release through it, so each sees what the others did, and a sensor stays pressed while at least one of them holds it.
- **Always on.** The device has no source to choose and captures nothing of the user, so it has no config block: a running `NaoqiSim` starts it with the other inputs (step 6 of "Lifecycle", [api.md](../runtime/api.md)) and stops it with them, releasing every sensor first.
- **An ordinary qi client that writes one key per sensor**, as the video input calls one method: no service is replaced. A press writes 1.0 into the sensor's value key (`Device/SubDeviceList/<sensor>/Sensor/Value`), a release 0.0, and the sims' own `ALTouch` does the rest, as it does from a NAO's sensors (measured Nov 26, 2026, the same on 2.1 and 2.8):
  - the sensor's event (`FrontTactilTouched`, `HandRightBackTouched`, `LeftBumperPressed`...) with 1.0 within 40 ms of the press and 0.0 within 30 ms of the release; the event's value reads the same afterwards (`getData`), which Life's rules on 2.8 and `ALTactileGesture` rely on;
  - `TouchChanged` at the press, with the sensor and its body part (`[["Head", true, [1]], ["Head/Touch/Front", true, [1]]]`), sensors pressed together in one event; the release's `TouchChanged` comes 2 s after the release;
  - `ALTouch.getStatus()` follows the key.
  Nothing writes the key back: neither sim has a `DCM` service. The device raises no event itself: an event raised by hand reaches its subscribers but leaves `ALTouch`'s status and the key unchanged.
- **Real time.** A touch lasts as long as it is held: a press of 3 s is a press event, 3 s, then a release event. Nothing is shortened in tests.

### The API

`sim.touch` on a running `NaoqiSim` ([api.md](../runtime/api.md)), `NotRunningError` when not running. Sensors are named as above; `"Head"` stands for the three head sensors. An unknown name raises `ValueError` before anything is pressed, and so does a `press` or `tap` that names none.

| Call | Does |
| --- | --- |
| `await sim.touch.press(*sensors)` | Presses the sensors, together (one `TouchChanged`) |
| `await sim.touch.release(*sensors)` | Releases them; with no argument, every sensor the API pressed |
| `await sim.touch.tap(*sensors, duration_s=0.2)` | Presses, waits, releases |
| `sim.touch.pressed()` | The sensors pressed now, whoever pressed them |
| `await sim.stop_activity_gesture()` | The version's gesture that stops the focused activity (below), returning once done: on 2.1 `"Head"` held 3.5 s; on 2.8 the top camera covered, the front sensor held 2 s and released, the camera uncovered ([controls.md](controls.md), "The gesture") |

```python
await sim.touch.tap("Head/Touch/Front")  # a tap on the front of the head
await sim.touch.tap("Head", duration_s=3.5)  # a NAO 2.1's stop gesture
```

### What a touch does, per version

- **Awareness.** `ALBasicAwareness` subscribes to `TouchChanged` on both versions ([_overview.md](../_overview.md), "Perception and speech recognition"); on a real NAO 2.1, `FrontTactilTouched 1.0` and `TouchChanged [["Head/Touch/Front", true]]` raised from a client give `StimulusDetected "Touch"` (measured Oct 16, 2026).
- **Stopping the running activity, 2.1.** Life itself listens to the three head events and `TouchChanged`: the three head sensors held 3 s stop the focused activity, at the release. On the 2.1 sim (Nov 26, 2026, an interactive activity focused, the keys written by a client): held 3.0, 3.1 and 3.5 s, the focus is lost 2.6 s after the release each time; held 2.0 to 2.9 s, nothing; one sensor or two held 4 s, nothing. A real NAO 2.1 does the same (Nov 25, 2026: held 3.4 s and 4.1 s, "Stopping activity" 0.1 s after the release; 1.7 to 2.5 s, nothing; the front sensor alone held 3.3 s, nothing), and the camera plays no part: the gesture worked with the camera uncovered, and covering it without a touch stopped nothing. So on 2.1 touches are enough.
- **Stopping the running activity, 2.8.** A rule of Life's configuration: the front sensor held while the top camera is dark, between 1 and 2.9 s, stops the activity at the release; 3 s puts the robot to sleep. Measured on the 2.8 sim with the two brightness keys written by a client (Nov 26, 2026): [brightness-statistics.md](../services/brightness-statistics.md), which is the camera half; the gesture as a whole is a control of [controls.md](controls.md).
- **Tactile gestures, 2.8.** `ALTactileGesture` turns head touches into named gestures (`SingleFront`, `DoubleFront`, `SingleTap` for the three sensors at once, the holds...) on its `onGesture` signal and the `ALTactileGesture/Gesture` event. It is a Python service of the robot's `altactilegesture` package, not in the desktop suite: the 2.8 image installs the robot's own, from the public robot image ([container.md](../container/container.md), "Robot packages in the image"). It subscribes to the three head events, reads their values 40 ms after one changes, calls the touch a hold after 0.8 s and joins the touches less than 0.2 s apart into one gesture, so it needs nothing more of this device. On the 2.8 sim (Nov 27, 2026), from the touch input's keys, a client on the host gets `SingleFront`, `DoubleFront`, `SingleTap` and `SingleFrontHold` on the signal and the event.
  - **The event lasts one second.** The service raises `ALTactileGesture/Gesture`, then removes the key 1 s later (`ALMemory.removeData`), and the removal takes the key's subscribers with it: a `subscriber("ALTactileGesture/Gesture")` made before a gesture gets that gesture and no other. That is the robot's package; a client subscribes again after each gesture, or connects to `onGesture`, which lasts.
  - **Life's double tap into `interactive` does not fire**, and the cause is a NAO 6's own Life configuration ([autonomous-life.md](../container/autonomous-life.md), "2.8: a NAO's Life configuration").

### Tests

- **Fast tier**: the device against a fake memory: the keys and events of a press and a release, several sensors in one `TouchChanged`, two holders of one sensor, the release at stop.
- **Live tier**, both versions: a tap raises the sensor's event and `TouchChanged`, and `ALTouch.getStatus()` follows; awareness answers `StimulusDetected "Touch"`; with Life on and an activity focused, each version's stop gesture stops it. On 2.8, `ALTactileGesture` reached from the host: a double tap gives `DoubleFront` on `onGesture` and on its event (`tests-e2e/test_robot_software_live.py`). The sims ship no interactive activity, and one borrowed from a robot lost the focus by itself now and then during the measurements, so the test installs a minimal activity of its own that keeps the focus until stopped.

## Open questions

Decided Nov 27, 2026: the device publishes no `NaoqiSim/Touch/Source` key (it is always on with one source, so the key would say nothing).

1. **Clicks in the sim window.** Deferred to naoqi-viewer. Its window has no buttons and a mouse cannot hold several sensors, so the window is not where touches are made ([controls.md](controls.md), "Why a page"). Showing the pressed sensors on the robot, and a tap by a click on a sensor, are naoqi-viewer's to add ([viewer.md](viewer.md)); which bodies of its model map to which sensors is decided with it.
2. ~~`ALTactileGesture` on the 2.8 image.~~ Settled Nov 27, 2026: the image installs the robot's package and makes it reachable from the host ("What a touch does, per version"). Of the three gaps found on Nov 26, the interpreter and the reach were the image's ([container.md](../container/container.md), "Robot software in the image"); the event seen once is the package's own design.
