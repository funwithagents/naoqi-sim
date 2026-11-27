# The config file

A config file describes the whole simulated robot in JSON: which NAOqi, which robot, how it is set up, and what your machine lends it for senses. `naoqi-sim run --config FILE` runs it, and `NaoqiSim.from_json_file(FILE)` does the same from Python.

You rarely write one from nothing. `naoqi-sim config` prints the file of a set of options, with every field ([cli.md](cli.md#config)), and [examples/configs/](../../examples/configs/) has one per NAOqi version:

```bash
naoqi-sim config --naoqi 2.8 --viewer --mic > my-nao.json
```

## The whole file

Every block and field, with its default. Only `naoqi.version` is required; leave out anything you do not change.

```json
{
  "naoqi": { "version": "2.8", "ready_timeout_s": 240 },
  "robot": { "type": "nao", "version": "v6" },
  "setup": {
    "available_languages": ["English", "French"],
    "language": "English",
    "posture": "crouch",
    "stiffness_on": false,
    "life_on": false
  },
  "audio_output": { "mode": "play", "record": null },
  "audio_input": { "source": "none", "mono": "duplicate" },
  "video_input": {
    "top": { "source": "none", "fps": 15, "device": 0 },
    "bottom": { "source": "none", "fps": 15, "device": 0 }
  },
  "viewer": {
    "headless": true,
    "scene": "empty",
    "variant": "auto",
    "cameras_display": false,
    "people_display": false
  },
  "perception": { "enabled": true },
  "speech_recognition": { "enabled": true },
  "controls": { "enabled": false, "port": 9564, "open": false }
}
```

A misspelt or unknown key, a wrong value or an impossible combination is refused when the file loads, with the key named: `setup.language: 'German' is not one of available_languages (English, French)`.

## `naoqi`: which NAOqi

| Field | Values | Default | |
|---|---|---|---|
| `version` | `"2.1"`, `"2.8"` | Required | The NAOqi version: 2.1.4.13 or 2.8.7.4 |
| `ready_timeout_s` | A positive number | `240` | How long a start waits for NAOqi to be ready before failing |

## `robot`: which robot

| Field | Values | Default | |
|---|---|---|---|
| `type` | `"nao"` | The NAOqi version's robot | The robot's type |
| `version` | `"v4"`, `"v5"`, `"v6"` | `"v5"` on NAOqi 2.1, `"v6"` on 2.8 | The robot's version |

Each NAOqi version runs the robots that really ran it: 2.1 a NAO V5 or V4, 2.8 a NAO V6. Any other pair is refused. The robot chosen is the model NAOqi loads, and what its `RobotConfig/Body/Type` and `RobotConfig/Body/Version` keys say, as on a robot. The window draws the same NAO for all three.

## `setup`: how the robot is set up

| Field | Values | Default | |
|---|---|---|---|
| `available_languages` | A list of language names | `["English", "French"]` | The languages installed on the robot, for its voice, its recognition and its dialog: what `getAvailableLanguages` answers |
| `language` | One of them | `"English"` | The robot's language when it is ready |
| `posture` | `"crouch"`, `"stand"`, `"sit"` | `"crouch"` | Its posture when it is ready. `"sit"` is for NAOqi 2.1 only |
| `stiffness_on` | `true`, `false` | `false` | Its motors on, as after `wakeUp()`, or off, as after `rest()` |
| `life_on` | `true`, `false` | `false` | Autonomous Life running, or off |

- **The languages**: English, French, German, Dutch, Swedish, Spanish, Brazilian, Czech, Italian, Polish, Portuguese, Russian, Turkish. English and French are in the images; another one is downloaded the first time a robot starts with it, so that start takes longer.
- **Only states a NAO can be in**: standing needs the stiffness on; Autonomous Life needs the stiffness on and a posture of `"stand"` or `"sit"`, since Life stands the robot up.
- A NAO whose Life starts at boot is `{"posture": "stand", "stiffness_on": true, "life_on": true}`.

## `audio_output`: the robot's loudspeakers

| Field | Values | Default | |
|---|---|---|---|
| `mode` | `"play"`, `"silent"`, `"record"` | `"play"` | On your loudspeaker, nowhere, or into a WAV file |
| `record` | A file path | `null` | The WAV file, required by `"record"`; relative to the config file |

## `audio_input`: the robot's microphones

| Field | Values | Default | |
|---|---|---|---|
| `source` | `"none"`, `"mic"`, `"fake"` | `"none"` | Nothing, your default microphone, or silence plus the sounds a Python program plays ([guides/python.md](../guides/python.md)) |
| `mono` | `"duplicate"`, `"silence"` | `"duplicate"` | A one-channel source on all four of the robot's microphones, or on the front one with the others silent |

With `"none"`, a module that subscribes to the microphones receives nothing, and the robot recognises no speech.

## `video_input`: the robot's cameras

One block per head camera, `top` and `bottom`:

| Field | Values | Default | |
|---|---|---|---|
| `source` | `"none"`, `"render"`, `"webcam"` | `"none"` | Not fed, the 3D scene as that camera sees it, or a webcam |
| `fps` | 1 to 30 | `15` | Frames per second given to that camera |
| `device` | 0 or more | `0` | Which webcam, for `"webcam"` |

`"render"` needs the `viewer` extra, with or without a window; `"webcam"` needs the `webcam` extra. A webcam does not turn with the robot's head ([cli.md](cli.md#run)).

## `viewer`: the 3D scene and its window

| Field | Values | Default | |
|---|---|---|---|
| `headless` | `true`, `false` | `true` | No window, or the window |
| `scene` | A scene name, or the path of a MuJoCo `.xml` file | `"empty"` | What surrounds the robot: `"empty"`, `"table"`, or a scene of yours, relative to the config file |
| `variant` | `"auto"`, `"placeholder"`, `"aldebaran"` | `"auto"` | How the robot is drawn: with Aldebaran's meshes when installed, with simple shapes, or with the meshes or fail |
| `cameras_display` | `true`, `false` | `false` | The robot's two camera images in the window |
| `people_display` | `true`, `false` | `false` | The people the robot perceives, as markers in the window |

The window, or a camera on `"render"`, needs the `viewer` extra. The two displays need the window.

## `perception` and `speech_recognition`: the engines

| Field | Values | Default | |
|---|---|---|---|
| `perception.enabled` | `true`, `false` | `true` | Face detection. Off, the robot's vision modules still answer and find nobody |
| `speech_recognition.enabled` | `true`, `false` | `true` | Speech recognition. Off, `ALSpeechRecognition` still answers and hears nothing |

Turning one off spares its container on a machine that does not use it.

## `controls`: the controls page

| Field | Values | Default | |
|---|---|---|---|
| `enabled` | `true`, `false` | `false` | Serves the page on `127.0.0.1` |
| `port` | 1 to 65535 | `9564` | Its port |
| `open` | `true`, `false` | `false` | Opens it in your browser once the robot is ready |

## In another program's config

A naoqi-sim config pastes unchanged as one block of a larger JSON config; the program hands that block to `NaoqiSimConfig.from_dict`. The design, with the reasons behind each default, is in [specs/runtime/config.md](../../specs/runtime/config.md).
