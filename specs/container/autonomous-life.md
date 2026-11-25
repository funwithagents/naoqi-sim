---
code:
  - docker/naoqi/services/autonomous-life/naoqi_sim_life_qiservice.py
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/Dockerfile.naoqi-2.8
  - src/naoqi_sim/suite.py
tests:
  - tests/test_entrypoint.py
  - tests/test_suite.py
  - tests-e2e/test_boot_live.py
  - tests-e2e/test_life_live.py
---

# Autonomous Life and the main dialog

**Status:** Draft

Decisions of Nov 25, 2026, on the surveys of Nov 20 and 21 (trail in `spike/RESULTS.md`, from "Life and the dialog on 2.8" on; a real NAO 2.1 measured Nov 21). The boot state and the whole chain were measured on both sims on Nov 25, 2026; the open questions are deferrals. Built so far (Nov 25, 2026): the boot state on both versions, 2.1's `setState`, and a NAO's Life configuration on 2.8; the rest has no plan yet.

## Purpose

On a NAO, Autonomous Life is what makes the robot stand, look at people and talk: in `solitary` it watches for somebody, and when a person comes close it goes `interactive` and runs the main dialog, the topics of every installed dialog package. A program can also leave Life off and drive the robot itself.

This spec says what naoqi-sim's images provide so that **Life and its main dialog run on both sims as on a robot, once a client switches Life on**: the state the sim boots in, what each version needs to accept `setState`, to go to a person and to start the dialog, and what stays the user's to install. The services Life builds on have their own specs: the people ([people-perception.md](../services/people-perception.md)), their zones ([engagement-zones.md](../services/engagement-zones.md)), the launchpad's people keys ([launchpad-people.md](../services/launchpad-people.md)), the speech recognition ([speech-recognition.md](../services/speech-recognition.md)).

## Decided

### The sim boots with Life off, at rest

On both versions, when the sim is ready:

| | Value |
|---|---|
| `ALAutonomousLife.getState()` | `disabled` |
| `ALMotion.robotIsWakeUp()` | false |
| Posture | `Crouch`, the motors off (stiffness 0) |

- This is a NAO whose Life-at-boot switch is off (the preference `com.aldebaran.debug` / `DisableLifeAndDialog` at `"1"`), found at rest in Crouch each time we connected to one.
- A client that wants the robot standing calls `ALMotion.wakeUp()`, and one that wants Life calls `ALAutonomousLife.setState("solitary")`, which stands the robot itself. A script that forgets `wakeUp()` now sees a crouched robot.
- **2.1**: the desktop suite boots standing and stiff with Life `disabled`. The entrypoint calls `ALMotion.rest()` before the sim is declared ready (measured: Crouch, stiffness 0, in 5.3 s).
- **2.8**: the desktop suite starts Life in `solitary`, which wakes the robot. Life reads the robot's switch itself when it starts: with the preference at `"1"` it stays `disabled` (measured on the sim), and a client's `setState("solitary")` still works. A module of ours, `naoqi_sim_life_qiservice`, loaded with our other modules before the package services start, sets the preference (`ALPreferenceManager.setValue`). The entrypoint then calls `ALMotion.rest()` as on 2.1, since the simulated robot is standing and stiff when Life does not start (measured; `rest()` takes 5.1 s).
- **The dialog is not preloaded at boot** when Life is off, on a robot (its boot package preloads it only when Life is on) as on the sim (measured). It is preloaded when Life is switched on, or at `_runMain()`. On 2.8 the entrypoint chooses the robot's languages before that, which is what makes the dialog write its grammar ([speech-recognition.md](../services/speech-recognition.md), "What it listens for").
- **Measured from this state**, both versions: `setState("solitary")` stands the robot (3.8 s on 2.1, as on a real NAO; 4.5 s on 2.8), `setState("disabled")` brings it back to Crouch with the motors off (5.3 s).
- **A joint command moves a joint at stiffness 0** on both sims, where a real NAO's motor does not move (measured: `angleInterpolation` and `setAngles` on the head at rest). So a script that forgets `wakeUp()` shows a crouched robot, and still works. Recorded in [naoqi-fidelity.md](naoqi-fidelity.md) as a limitation.
- **No config field for Life at boot for now** (user, Nov 25, 2026). The robot's default is Life on; a field mapped to the preference can come later.

### Switching Life on

- **2.1**: the desktop suite's `ALAutonomousLife.setState` refuses every call ("Calls to the setState method are not currently allowed") until `ALAutonomousLife._setStateChangeEnabled(True)` is called. The entrypoint makes that call once Life answers, before its `rest()`. A real NAO needs no such call (measured: `setState("solitary")` works from `disabled` and stands the robot in 3.8 s).
- **2.8**: nothing to do.
- `setState("interactive")` stays an invalid transition, as on a robot: Life enters `interactive` itself.

### Going to a person, and starting the dialog

The two versions do it differently on a robot, and so do the sims.

| | 2.1 | 2.8 |
|---|---|---|
| What takes Life to `interactive` | An activity of nature `interactive` taking the focus: by `switchFocus`, or when its launch condition holds | A rule of Life's configuration: `Launchpad/NumPeopleZone1 > 0` for 0.25 s; or an interactive activity taking the focus |
| What starts the main dialog | The focused activity's behavior, calling `ALDialog._preloadMain()` then `_runMain()` | Life itself: `ALDialog._startDialog("FullyEngaged")` when it enters `interactive` with no activity |
| On a robot | `run_dialog_dev`, from the store, launch condition `('Launchpad/ZoneOfTrackedHuman' == 1) && ('UserSession/FocusedUser' >= 0)` | The `life` package's NAO configuration |
| Back to `solitary` | The user session manager asks the activity to stop when nobody is tracked | After 10 s `interactive`, nobody tracked or the tracked human beyond zone 2 for 20 s, no activity and no dialog input for 10 s |

**naoqi-sim ships no launcher application on either version** (user, Nov 25, 2026).

- **2.8 needs none**: the mechanism is Life's. The image only needs the NAO configuration (below).
- **2.1 has no mechanism without an activity.** The launcher is not in the public robot image, so it is the user's to install, as the dialog content is. With it installed, Life goes to a person and starts the dialog by itself (measured on the sim, Nov 21, 2026, with a real robot's applications: a face at 1 m, `interactive` 0.2 s after zone 1, "hello" answered, an application started by voice, `solitary` again 4 s after the face left). Without it, a client starts the main dialog with `_preloadMain()` and `_runMain()`, or loads its own topics.

### 2.8: a NAO's Life configuration

- The desktop `life` package ships a configuration with no rule to `interactive` ("Juliette 2.0.x Compatible. Limited continuous Dialog"). A NAO 6 uses `autonomy-nao-romeo.cfg` ("Pure interactive state with Dialog") from the robot's `life` package.
- Life reads `~/.config/naoqi/autonomy.cfg` first. `fetch-and-build-images` extracts the NAO file from the public robot image, as it extracts the `animations` package ([container.md](container.md), "Image data and licensing"), and the image installs it there ([container.md](container.md), "Robot packages in the image"). Never committed.
- Of the launchpad's people keys this configuration reads two: `Launchpad/NumPeopleZone1` and `Launchpad/ZoneOfTrackedHuman`.
- Its other way into `interactive`, a double tap on the front head sensor (`ALTactileGesture/Gesture == "DoubleFront"`), is not provided: it needs the robot's `altactilegesture` package and a touch input ([touch-input.md](../host/touch-input.md), a draft). Left out of this work.
- Calls of the rules that fail harmlessly on the sim: `ALSignsAndFeedback` (unless installed, open question 4), `_ALBrightnessStatistics`, `boot-config`, the sound set when the user has not installed it.

### What stays the user's

As on a robot out of the box: the dialog content (`dialog_lexicon`, `dialog_applauncher`, ...), the applications, the sound set, and on 2.1 the dialog's launcher. A package installed in a running sim persists in its version's package store ([container.md](container.md), "Package store").

### Tests

- **Fixtures, written by us and committed** (no Aldebaran package can be: [container.md](container.md), "Image data and licensing"): a small dialog package (one topic, English and French, a few rules), the same for both versions; a small application of our own with a trigger sentence, to launch by voice; and for 2.1 a minimal interactive activity with the robot launcher's condition, calling `_preloadMain()` and `_runMain()`, installed by the test only.
- **Live tier, both versions, one scenario**, the viewer headless, perception and speech recognition on, the sentences played into the fake room:

| Step | Expected |
|---|---|
| Boot | Life `disabled`, at rest in Crouch |
| `setState("solitary")` | The robot stands, nobody focused |
| A face prop at 2 m | Tracked, zone 2, Life stays `solitary` |
| The face moves to 1 m | Zone 1, Life `interactive`, the main dialog started with our topic |
| A sentence of our topic | Recognised and answered |
| The face is removed | Life back to `solitary`, the dialog stopped |
| `setState("disabled")` | At rest again |

- The live tests that move joints wake the robot first.

## Specs this changes when it is built

[container.md](container.md) (entrypoint steps, the extracted file, `/usr/bin/python2` if needed), [naoqi-fidelity.md](naoqi-fidelity.md) (2.1's `setState` becomes patched; the launchpad lines corrected: the desktop builds hold the plugins' code and never start it; the boot posture), [speech-recognition.md](../services/speech-recognition.md) (open questions 2 and 3), [testing.md](../testing/testing.md) (the wake-up fixture), [_overview.md](../_overview.md).

## Open questions

None before `Stable`: the points to measure were measured on Nov 25, 2026.

Measured the same day, and settled:

- **2.8, the whole chain with the built speech recognition**, the NAO configuration, our dialog package next to two of the user's, the launchpad keys written by a script: a face at 2 m is tracked and Life stays `solitary`; at 1 m Life is `interactive` 2.4 s later and the main dialog started (15 topics loaded, 8 activated); "hello robot" played in the room is recognised 1.9 s after it starts and answered "hello human"; the face removed, the person is lost 1.2 s later, forgotten after 8 s more, and Life is `solitary` 21 s after the removal, the dialog stopped.
- **2.8 does not need `run_dialog_dev`**: the same run passes with the package removed; the dialog logs "No model SLM found" once and goes on. Not installed.
- **2.1 with a robot's full dialog content** (37 packages of a real NAO 2.1, its launcher included, installed for the run): `interactive` 0.4 s after the face at 1 m, the main dialog ready 2 s after it (102 topics loaded, 47 activated), the recognition listening for 10,340 phrases (1,726 more the engine has no words for), "hello" and "what can you do" recognised about 1.6 s after they start and answered, `solitary` 6 s after the face left.
- **2.8 with a robot's full dialog content** (34 packages of a NAO 6, installed for the run), from a boot with Life off: `setState("solitary")`, Life `interactive` 2.3 s after the face at 1 m, the main dialog started with 68 topics loaded and 60 activated, the recognition listening for 12,421 phrases of the dialog's grammar, `solitary` 12 s after the face left.
- **2.8, an application launched by voice** (a NAO 6's `dialog_applauncher` and a dance installed for the run): the dance's trigger sentence played in the room is recognised 1.7 s after it starts, the dialog answers and raises `Dialog/StartApp`, life focuses the application and the joints move. The dialog gives the trigger sentences to the recognition itself, as a list of its grammar ([speech-recognition.md](../services/speech-recognition.md), "What it listens for"). On 2.1 the same was measured on Nov 21, 2026.
- **`signs-and-feedback`** (2.8's bips and LEDs around listening) is not installed for now: a deferral, with `/usr/bin/python2` that its service needs.

Deferred:

4. A config field for Life at boot.
5. The double-tap trigger on 2.8.
6. A NAO 6's behaviour is judged from its public image: none at hand.
7. What a NAO does at boot with Life off (posture, stiffness): never watched, it takes a reboot of the real robot.
