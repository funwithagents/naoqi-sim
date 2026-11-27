---
code:
  - docker/naoqi/services/brightness-statistics/naoqi_sim_brightness_statistics_core.py
  - docker/naoqi/services/brightness-statistics/naoqi_sim_brightness_statistics_qiservice.py
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_brightness_statistics_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_touch_live.py
---

# Brightness statistics

**Status:** Implemented

## Purpose

`_ALBrightnessStatistics`, added to the 2.8 image: the hidden service that tells Autonomous Life how bright and how uniform the top camera's picture is, which is how a NAO 6 knows a hand is over its forehead. Life's stop gesture on 2.8 is the front head sensor touched while the camera is covered; the desktop suite ships Life's rules but not this service, so on the sim the rules can never hold. With the touch input ([touch-input.md](../host/touch-input.md)) and the camera cover ([controls.md](../host/controls.md)), this service makes the gesture work as on a robot.

**2.8 only.** A NAO 2.1 has no such service (nothing on a real one names it, Nov 25, 2026), and its stop gesture uses the head sensors alone.

## Decided

### What Life does with it

From Life's configuration (`autonomy.cfg`: the desktop suite's file, and a NAO's, which the Autonomous Life work installs; both hold these rules); `dark` below stands for `'_ALBrightnessStatistics/Avg' < 30.0 && '_ALBrightnessStatistics/Std' < 5.0`:

| Rule | Condition, Life `solitary` or `interactive` | Action |
| --- | --- | --- |
| Start, stop the service | Life `solitary` or `interactive`; Life `disabled` | `_ALBrightnessStatistics._start()`; `_stop()` |
| Freeze, unfreeze the head | `'FrontTactilTouched' && dark`; no longer | The head chain frozen, released |
| Validation 1 and 2 | Held 1 s; 2 s; not asleep | The sound `sfx_validation_1` |
| Stop running activities | Held at least 1 s, less than 2.9 s, now released; not asleep | Feedback off, face LEDs, the sound `sfx_confirmation_1`, `StopAll` (reason `user-stop`), LEDs reset |
| Held 3 s | Not asleep | Another rule (sleep) |

Every rule also needs `_AutonomousLife/_ForbidStopCommands` false (it is, on the sim) and a focused activity other than `store-access/interactive`. The file's own comments give the scale: with a hand on the camera the average has never been seen under 16, and the deviation falls to 0 with a still hand and reaches 4 to 5 when it moves.

### Measured on the 2.8 sim

With the two keys raised by a client ten times a second in place of the service, an interactive activity focused and the front sensor's key written (Nov 26, 2026):

| Front sensor | Camera | Held | Result |
| --- | --- | --- | --- |
| touched | bright (100, 30) | 2.0 s | nothing |
| not touched | dark (17.5, 0.5) | 2.0 s | nothing |
| touched | dark | 0.6 s, 0.9 s | the head frozen and released, nothing else |
| touched | dark | 1.3 s, 2.0 s, 2.8 s | the activity stopped, the focus lost 3 s after the release |
| touched | dark | 3.5 s | the robot asleep (`AutonomousLife/Asleep` 1), the activity stopped |

- **The keys may come late.** At its start Life's condition checker logs that the two keys do not exist and evaluate to false "until it exists"; when they first appear it logs that they are found, and the rules work. So the service has no boot order to respect.
- **A failed call does not stop a rule.** On a default sim three of the rule's calls fail: the two sounds (no sound set) and `_ALBrightnessStatistics._start` and `_stop` themselves before this service exists. `ALSignsAndFeedback.triggerBit`, which failed too (not in the desktop suite), answers since the image has the robot's package ([container.md](../container/container.md), "Robot packages in the image"). Life logs each and carries on to `StopAll`.

### The service

- **Name and API**: `_ALBrightnessStatistics`, with `_start()` and `_stop()`, the two calls Life makes. Both answer at once; `_start()` twice is one start.
- **While started**, it reads the top camera from `ALVideoDevice` (QQVGA, luminance) ten times a second, and raises `_ALBrightnessStatistics/Avg` and `_ALBrightnessStatistics/Std`: the mean and the standard deviation of the picture's luminance, 0 to 255. Stopped, it unsubscribes from the camera and raises nothing.
- **No picture is not a dark one.** A camera nobody feeds serves NAOqi's placeholder, all zeros in luminance ([video-input.md](../host/video-input.md), "As measured"), which would read as a covered camera and let a front touch of 1 to 2.9 s stop the activity on a sim with no camera source. The service raises nothing for a picture whose every byte is 0, so the keys keep their last values, or never appear: the rule never holds without a camera, and the gesture needs a fed top camera (the cover refuses an unfed one).
- **The scale is ours.** No NAO 6 was measured: the keys' meaning is taken from the rule's thresholds and comments. They agree with a real NAO 2.1's top camera under a hand, mean 17.5 and deviation 0.5, against 40 to 140 and 12 to 60 uncovered (Nov 25, 2026), which is also the luminance the camera cover gives: on the 2.8 sim, covered, the service raises a mean of 18 and a deviation of 0 (the cover is uniform at QQVGA, a still hand), and 120 to 125 and about 14 for the live tier's rendered scene (Nov 27, 2026).
- **Where it runs**: a Python 2.7 module of ours inside the 2.8 NAOqi ([service-replacement.md](../container/service-replacement.md)), in `docker/naoqi/services/brightness-statistics/`: a core tested on the host with a fake camera and a fake memory, under a qi service shell. It reads frames as the face detector does ([face-detection.md](face-detection.md)).
- It is not in the `NaoqiSim` service's list of stubs ([status-service.md](../container/status-service.md)): it does what its name says.

### Tests

- **Fast tier**: the core: the cover's frame gives an average under 30 and a deviation under 5, a room's frame neither; the placeholder raises nothing; ten pictures a second; nothing raised before `_start()` or after `_stop()`; the camera subscription released at `_stop()`. The entrypoint test checks the 2.8 boot loads it and waits for its name.
- **Live tier**, 2.8 (`tests-e2e/test_touch_live.py`): with Life on the keys follow the rendered camera, fall under the thresholds with it covered, and stop with Life; with an activity focused, the camera covered and the front sensor held 2 s then released, the activity loses the focus (at the release, measured Nov 27, 2026; Life stays `interactive`); the same touch with the camera uncovered stops nothing.

## Open questions

Every question left is a deferral.

1. **The rate.** Ten times a second fits rules timed to 0.1 s, and is what the measurement fed; what it costs inside the 2.8 NAOqi under emulation is to measure.
2. **Other readers.** Nothing else on the 2.8 image is known to read the two keys.
3. **The feedback a robot gives.** The validation and confirmation sounds need the sound set, which stays the user's to install; without it the gesture works silently. The LED reset is the robot's `signs-and-feedback` package's, installed in the 2.8 image.
