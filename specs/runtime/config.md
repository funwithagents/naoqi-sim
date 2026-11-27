---
code:
  - src/naoqi_sim/config.py
  - docker/compose.yaml
  - examples/configs/2.1.json
  - examples/configs/2.8.json
  - examples/configs/ci.json
tests:
  - tests/test_config.py
  - tests/test_project_map.py
---

# Configuration

**Status:** Implemented

## Purpose

One declarative description of *which simulated NAO to run and which devices to attach to it*. A [`NaoqiSim`](api.md) is built from it, the `naoqi-sim` CLI loads it from a file, and a program that runs a simulated NAO can embed it in its own config. Before it the same facts were spread over `docker compose` profiles, environment variables (`NAOQI_SIM_VERSION`, `NAOQI_SIM_LANGUAGES`) and the audio output's flags; a config file makes a setup reproducible and lets a test, a CLI user and a Python program describe the same stack the same way.

Its conventions (frozen dataclasses, three loaders sharing one validation path, unknown keys rejected, errors naming the key path; below) keep it self-contained, so a naoqi-sim config can be pasted unchanged into a larger JSON config and loaded from there with `NaoqiSimConfig.from_dict`.

This config is the **host-level** description. The container keeps its own interface, the entrypoint's environment variables ([container.md](../container/container.md), "Entrypoint"); `NaoqiSim` generates the compose environment from the config, and nobody writes those variables by hand any more.

## Decided

### `NaoqiSimConfig`: top-level structure

```json
{
  "naoqi": { "version": "2.1", "ready_timeout_s": 240 },
  "robot": { "type": "nao", "version": "v5" },
  "setup": { "available_languages": ["English", "French"], "language": "English", "posture": "crouch", "stiffness_on": false, "life_on": false },
  "audio_output": { "mode": "play", "record": null },
  "audio_input": { "source": "none", "mono": "duplicate" },
  "video_input": { "top": { "source": "none", "fps": 15, "device": 0 }, "bottom": { "source": "none", "fps": 15, "device": 0 } },
  "viewer": { "headless": true, "scene": "empty", "variant": "auto", "cameras_display": false, "people_display": false },
  "perception": { "enabled": true },
  "speech_recognition": { "enabled": true },
  "controls": { "enabled": false, "port": 9564, "open": false }
}
```

```python
@dataclass
class NaoqiSimConfig:
    naoqi: NaoqiSettings  # required
    robot: RobotSettings = field(default_factory=RobotSettings)
    setup: SetupSettings = field(default_factory=SetupSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    audio_input: AudioInputSettings = field(default_factory=AudioInputSettings)
    video_input: VideoInputSettings = field(default_factory=VideoInputSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)
    perception: PerceptionSettings = field(default_factory=PerceptionSettings)
    speech_recognition: SpeechRecognitionSettings = field(
        default_factory=SpeechRecognitionSettings
    )
    controls: ControlsSettings = field(default_factory=ControlsSettings)


@dataclass
class NaoqiSettings:
    # "2.1" | "2.8"; required, no default
    version: NaoqiVersion
    # start() waits this long for the container to be healthy
    ready_timeout_s: float = 240.0


@dataclass
class RobotSettings:
    """Which robot the NAOqi runs ("The robot")."""

    # "nao"; None takes the NAOqi version's default robot
    type: RobotType | None = None
    # a NAO's: "v4" | "v5" | "v6"; None takes the NAOqi version's default for that type
    version: str | None = None


@dataclass
class SetupSettings:
    """How the robot is set up: its language packs, and its state when the sim is ready
    (autonomous-life.md, "The state at boot")."""

    # The installed language packs, as a NAO's: what getAvailableLanguages answers and
    # setLanguage accepts on the speech, the recognition and the dialog, by NAOqi name. Each
    # needs a voice in the speech engine and a model in the speech recognition engine
    # (LANGUAGES: English, French, German, Dutch, Swedish, Spanish, Brazilian, Czech, Italian,
    # Polish, Portuguese, Russian, Turkish)
    available_languages: tuple[str, ...] = ("English", "French")
    # The language at boot, one of available_languages
    language: str = "English"
    # "crouch" | "stand" | "sit" ("sit": 2.1 only)
    posture: RobotPosture = "crouch"
    # every joint's stiffness on (1, as after wakeUp()) or off (0, as after rest())
    stiffness_on: bool = False
    # Autonomous Life running (solitary) or disabled
    life_on: bool = False


@dataclass
class AudioOutputSettings:
    """The audio output (audio-output.md)."""

    # "play" | "silent" | "record"
    mode: AudioOutputMode = "play"
    # WAV file, required by "record"
    record: Path | None = None


@dataclass
class AudioInputSettings:
    """The audio input, feeding the ALAudioDevice replacement (audio-input.md)."""

    # "none" | "mic" | "fake" (code plays sounds through NaoqiSim.fake_audio)
    source: AudioInputSource = "none"
    # "duplicate" | "silence", published as NaoqiSim/Audio/Channels
    mono: MonoPolicy = "duplicate"


@dataclass
class CameraSettings:
    """What feeds one head camera (video-input.md, "Sources")."""

    # "none" | "render" | "webcam"
    source: VideoInputSource = "none"
    # frames injected per second into this camera, 1 to 30
    fps: int = 15
    # webcam index, used by "webcam"
    device: int = 0


@dataclass
class VideoInputSettings:
    """The video input, injected into ALVideoDevice (video-input.md): a block per head camera."""

    top: CameraSettings = field(default_factory=CameraSettings)
    bottom: CameraSettings = field(default_factory=CameraSettings)


@dataclass
class ViewerSettings:
    """The simulated world (naoqi-viewer sim mode)."""

    # no window by default: a config that renders no camera then needs no extra
    headless: bool = True
    # a bundled scene name ("empty", "table") or a path to an MJCF file
    scene: str = "empty"
    # "auto" | "placeholder" | "aldebaran" (naoqi-viewer's world.variant)
    variant: ViewerVariant = "auto"
    # the head cameras as ALVideoDevice serves them, as pictures in the window
    cameras_display: bool = False
    # the people NAOqi lists in ALMemory, as markers in the window
    people_display: bool = False


@dataclass
class PerceptionSettings:
    """The perception engine (perception-engine.md): faces for ALFaceDetection and ALPeoplePerception."""

    # False starts no `perception` container: the modules still answer and find nobody
    enabled: bool = True


@dataclass
class SpeechRecognitionSettings:
    """The speech recognition engine (asr-engine.md): what ALSpeechRecognition hears."""

    # False starts no `asr` container: ALSpeechRecognition still answers and hears nothing
    enabled: bool = True


@dataclass
class ControlsSettings:
    """The controls page and its HTTP API (controls.md)."""

    enabled: bool = False
    port: int = 9564  # on 127.0.0.1 only
    open: bool = False  # open the page in the default browser once the robot is ready
```

- **Every config names its NAOqi version**: `naoqi.version` is the one required field, with no default, so a file always says which NAOqi it runs and `NaoqiSimConfig()` with no argument is not valid (in code a `TypeError`; from JSON a `ConfigError` on `naoqi`, or on `naoqi.version` when the block is there without it). The smallest config is `{"naoqi": {"version": "2.8"}}`.
- Every other block is optional. Missing blocks and fields take the defaults above. **A default is declared once**, on the dataclass field; the loaders read it from there (`dataclasses.fields`), so a default cannot drift between direct construction and JSON.
- **The device blocks are named after the device** ([devices.md](../host/devices.md)): `audio_output`, `audio_input`, `video_input`, each specified in its own spec under `host/`.
- **A language is available only with its language pack**, as on a NAO, where a language pack installs the voice, the recognition and the dialog's data together: `robot.available_languages` takes the languages that have a voice in the speech engine and a model in the speech recognition engine (`LANGUAGES`: English, French, German, Dutch, Swedish, Spanish, Brazilian, Czech, Italian, Polish, Portuguese, Russian and Turkish; the fast tier checks both engines' tables). A language with a voice only (Danish, Finnish, Norwegian) is refused, naming the languages that have one. English and French are in the images; another language's voice and model are fetched on its first use into the language packs volume ([asr-engine.md](../container/asr-engine.md), "Models"), so its first start takes longer (tens of seconds; Swedish's model is 290 MB).
- **`robot.language` is the robot's language at boot**: its speech, its recognition and its dialog, on both versions (measured Nov 25, 2026 with French, and by the French run of the Life scenario: [autonomous-life.md](../container/autonomous-life.md), "Tests"). `NaoqiSim.start()` passes the available languages to the containers with it first (`NAOQI_SIM_LANGUAGES`).
- **A config that names only its NAOqi version is valid and useful, and needs no extra**: that version's default robot ("The robot"), crouched with its stiffness off and Life off, with speech on the host loudspeaker, no window, and no video or audio input (each `NaoqiSim/*/Source` key stays `none`). What a person usually turns on (the window, the webcam, the microphone, the controls) is one option each on the command line ([cli.md](cli.md), "The robot options").
- **Three blocks say what the robot is**: `naoqi` the NAOqi it runs, `robot` which robot that is, `setup` how it is set up once ready (its language packs and language, its posture, stiffness and Life). Until Nov 27, 2026 one `robot` block held what `setup` holds now: a file with `robot.posture` or `robot.language` fails at load with an unknown key, naming it.
- The `audio_output` block picks the audio output's sink when the caller passes none ([audio-output.md](../host/audio-output.md), "Audio sinks"; [api.md](api.md)): `play` a `DevicePlayer`, `silent` a `NullSink`, `record` a `WavSink`. A sink passed in code (`MemorySink` in tests) wins over the block.
- Paths (`audio_output.record`, and `viewer.scene` when it ends in `.xml`) are resolved relative to the config file when loaded with `from_json_file`, and relative to the working directory otherwise.

### The robot

`naoqi.version` is what a NAO user chooses first; which robot runs it follows, and can be chosen where that NAOqi ran on more than one. Each NAOqi version has a default robot, the first of its row, and runs the robots of its row only:

| `naoqi.version` | Robots (`robot.type` `robot.version`), the default first |
| --- | --- |
| `2.1` | `nao` `v5`, `nao` `v4` |
| `2.8` | `nao` `v6` |

- **Type and version are two fields** because they are two things: a NAO is a V4, a V5 or a V6, another robot type has versions of its own. They are also how NAOqi itself names a robot (`RobotConfig/Body/Type`, `RobotConfig/Body/Version`), which is what the sim publishes for the robot chosen ([status-service.md](../container/status-service.md), "The robot's keys").
- **Each one left out takes its default from the NAOqi version**: the type the default robot's, the version that type's first in the row. `NaoqiSimConfig` fills them in when it is built, so `config.robot` always names both, and so does the JSON `to_dict()` gives (and `naoqi-sim config` prints).
- **The real pairs only.** A robot outside its NAOqi's row is refused at load, on `robot.type` or `robot.version`, naming the row: `robot.version: NAOqi 2.8 does not run a nao v5; it runs: nao v6`. The 2.8 suite does ship a NAO V5 model file; no NAO V5 ever ran NAOqi 2.8, so the sim does not either.
- **What the choice changes**: the model file NAOqi loads and the robot's ALMemory keys; between a NAO V4 and a V5 on 2.1, the versions `ALMotion` reports and a few masses, the joints, their limits and the cameras being the same ([container.md](../container/container.md), "The robot model"). The window shows naoqi-viewer's one NAO model whatever the robot ([viewer.md](../host/viewer.md), open questions).
- **Made for a second robot type.** A Pepper on NAOqi 2.5 is one more row (`2.5`: `pepper`, its versions) and one more `RobotType`; the rules above do not change, and 2.8's row can take it too. What depends on the robot beyond its model (the touch sensors, the postures it can take, the stop gesture) is keyed on the NAOqi version today, which is the same thing while each version runs one type; it moves to this table with the second type.
- `ROBOTS`, in `config.py`, is the table; the entrypoint maps a pair to its model file.

### Constructors and validation

- Every config class has the same three constructors: `from_dict(data)`, `from_json(text)` (parses, then calls `from_dict`), and `from_json_file(path)` (reads, then calls `from_json`; an invalid-JSON error names the path). All three share one validation path.
- Errors raise `ConfigError(ValueError)`, with a message that names the offending key path (e.g. `audio_output.record`). A block's own checks raise `ConfigError(message, key=<field>)`, and each enclosing loader prefixes `key` with its own path; the message is never parsed to find the key.
- **Unknown keys are errors**, so a typo fails when the config loads.
- **Type and range checks:** each `Literal` field takes one of its values; `controls.port` is an integer from 1 to 65535; `ready_timeout_s` is a positive, finite number; a camera's `fps` is an integer from 1 to 30 (a NAO camera's maximum) and its `device` a non-negative integer; `viewer.scene` is a non-empty string; `robot.available_languages` is a non-empty list of distinct names, each with a language pack (`LANGUAGES`), so a language NAOqi supports but naoqi-sim cannot hear or speak (`Japanese`, `Danish`) fails at load, naming the languages that have one; `robot.language` is one of them. In code a list is accepted and kept as a tuple.
- **Cross-field checks at load:** `robot` must be one its `naoqi.version` runs ("The robot"); the `setup` block takes only the states a NAO can be in, each refusal saying why ([autonomous-life.md](../container/autonomous-life.md), "The state at boot"): `posture: "stand"` needs `stiffness_on` (a NAO cannot stand with its stiffness off: that state is `crouch`), `life_on` needs `stiffness_on` and a `posture` of `stand` or `sit` (Life stands the robot up), and `sit` needs `naoqi.version` 2.1 (the 2.8 sim cannot reliably sit); `audio_output.mode = "record"` needs `audio_output.record`; `viewer.cameras_display` and `viewer.people_display` are refused with `viewer.headless` (the pictures and the markers are drawn in the window, as naoqi-viewer refuses them). Other fields that do not apply (`device` without a webcam, `record` with `play`) are validated but not applied, so switching a source is a one-word change.
- **Environment checks are not config checks.** Whether the `viewer` extra is installed, Docker answers, the images are built and verified, a webcam or a microphone exists, a language's voice can be fetched: `NaoqiSim.start()` checks these ([api.md](api.md)), so a config file stays valid on any machine.
- `config.py` imports neither `qi`, nor `naoqi_viewer`, nor `sounddevice`.

### The perception engine

`perception.enabled` (default `true`) runs the `perception` container with the stack, so `ALFaceDetection` and `ALPeoplePerception` detect for real on the frames the cameras serve ([perception-engine.md](../container/perception-engine.md), [face-detection.md](../services/face-detection.md), [people-perception.md](../services/people-perception.md)); `NaoqiSim.start()` waits for it as for the `tts` engine ([api.md](api.md), "Lifecycle"). `false` starts no container and the modules find nobody, as a NAO in the dark: for a machine that never shows the robot a face, or a client that runs its own detector and pauses the robot's. The modules and the stubs are always loaded: the service list is a NAO's either way. A NAO has no such switch, so it is not a device block ([devices.md](../host/devices.md)): it is the engine's.

### The speech recognition engine

`speech_recognition.enabled` (default `true`) runs the `asr` container with the stack, so `ALSpeechRecognition` recognises for real what the microphones hear ([asr-engine.md](../container/asr-engine.md), [speech-recognition.md](../services/speech-recognition.md)); `NaoqiSim.start()` waits for it after the perception engine. `false` starts no container and the module hears nothing, as a NAO in a silent room; `ALDialog` then answers `forceInput` only. The module is always loaded. Like the perception switch, it is the engine's, not a device block.

### The controls

`controls.enabled` (default `false`) serves the controls page and its HTTP API on `127.0.0.1:<port>` while the robot runs, and `open` opens it in the default browser once the robot is ready ([controls.md](../host/controls.md)). Off by default: a library caller and a test drive the touch input and the camera cover in Python. The touch input itself has no block: it is always on ([touch-input.md](../host/touch-input.md)).

### The video input: one block per camera

A NAO has two head cameras, and what feeds each one is a config choice: `video_input.top` and `video_input.bottom` are two `CameraSettings`, each with its `source` (`none`, `render`, `webcam`), its `fps` and, for a webcam, its `device`. So the render can feed both cameras (the live tier), or one of them to spare a small machine half the renders; and once the webcam is built, a laptop's webcam can feed the top camera with the bottom one rendered or unfed, or two webcams the two cameras. A camera on `none` is not fed: a client subscribing to it gets NAOqi's placeholder for a camera never fed ([video-input.md](../host/video-input.md), "As measured").

`fps` is per camera, each on its own schedule: a fast top camera and a slow bottom one spare bandwidth to the clients and keep the viewer within its render budget (30 frames on the top camera and 10 on the bottom one are 40 renders per second, under its ceiling of 60, where 30 on both is not; [video-input.md](../host/video-input.md), "Frames"). Both default to 15. Two cameras at the same `fps` share their slots, so a client reading both sees the same moment.

The block's shape changed on Oct 16, 2026 from one `source`/`fps`/`device` for the whole device to one per camera: a file with the old `video_input.source` or `video_input.fps` fails at load with an unknown key, naming it.

### The viewer and the video input

`viewer.headless` and the cameras' sources together decide whether the simulated world runs ([viewer.md](../host/viewer.md), "Which viewer runs"):

| `viewer.headless` | Cameras' `source` | Sim process | Needs `naoqi-sim[viewer]` |
| --- | --- | --- | --- |
| `false` | any | `NaoqiViewer` in sim mode, with its window | Yes |
| `true` | `render` on either camera | `NaoqiViewer` in sim mode, headless | Yes |
| `true` | neither camera rendered (`none` or `webcam`) | None | No |

So the default (`headless` true, no camera rendered) runs no viewer and needs no extra, which is what a server wants; the window is `{"viewer": {"headless": false}}`, or `--viewer` on the command line, which also renders both cameras ([cli.md](cli.md)); CI runs a headless viewer with the render camera instead ([ci.md](../testing/ci.md)).

The `viewer` block is naoqi-sim's own, not an embedded `NaoqiViewerConfig`: `NaoqiSim` builds the viewer's config from it as `NaoqiViewerConfig(mode="sim", headless=headless, cameras_display=cameras_display, people_display=people_display, naoqi=NaoqiSettings(url=sim.url), world=WorldSettings(scene=scene, variant=variant))`. The mode and the NAOqi URL follow from running naoqi-sim, so they are not settings; naoqi-viewer's other fields (`ghost`, `naoqi.rate_hz`, `launch_timeout_s`) keep naoqi-viewer's defaults. `cameras_display` (naoqi-viewer's camera display, from its commit `8f3976f`) shows the two head cameras in the window's top-right corner as `ALVideoDevice` serves them, read back over qi like any client: what naoqi-sim injected, render or webcam, so it checks the camera path end to end; it costs NAOqi one QVGA subscription at 10 fps, which the video input ignores like any subscriber. `people_display` (naoqi-viewer's people display) draws the people a client published under `PeoplePerception/` in ALMemory as markers in the window, never in a camera render ([viewer.md](../host/viewer.md), "Configuration"); it costs NAOqi a few ALMemory reads a second. `scene` and `variant` take naoqi-viewer's values and defaults (`empty`, `auto`); this module only checks their form (a non-empty string; one of the three variants), since `config.py` does not import `naoqi_viewer`. The rest is checked by naoqi-viewer itself, in `NaoqiSim.start()` ([api.md](api.md), "Lifecycle"): an unknown bundled scene when step 1 builds the `NaoqiViewerConfig` (re-raised as a `ConfigError` with key `viewer.scene`, before anything starts), missing meshes when the viewer launches.

### Sources not built yet

The config accepts every source value from the start (`webcam`, `render`, `mic`, `fake`), so config files written then stayed valid as the device specs landed. Until a device is built, `NaoqiSim.start()` fails with `DeviceNotBuiltError` naming the missing device instead of silently running without it. Every source is built since the webcam (Oct 16, 2026), so none fails this way today; the error stays for the next source accepted before its device.

- **The `wav` source is gone.** It was accepted from the start but never built (`NaoqiSim.start()` refused it); the `fake` source replaced it before any release ([audio-input.md](../host/audio-input.md), "Sources"), so a file that still says `"wav"`, or has a `wav` field, fails at load like any unknown value or key. `audio_input.gate_tail_s` went with the microphone gate ([audio-input.md](../host/audio-input.md), "The robot hears itself") and fails the same way.

### File format

JSON: a naoqi-sim file is pasted into another program's JSON config unchanged, and back, which a second format would break. The example files carry no comments; what each one is for is listed below and in the README.

### Embedding in other configs

- The `naoqi-sim` CLI reads a `NaoqiSimConfig` file as is (`naoqi-sim run --config sim.json`, see [cli.md](cli.md)).
- Another program embeds it as one block of its own config, exactly a `NaoqiSimConfig`: a naoqi-sim file pastes in unchanged and copies back out unchanged. The program hands that block to `NaoqiSimConfig.from_dict`, imported from `naoqi_sim.config` (which imports neither qi nor the devices' libraries); naoqi-sim knows nothing of the enclosing config.

### Example files

`examples/configs/` holds three files to read and to copy. Two are the full robot, `2.1.json` and `2.8.json`: that NAOqi's default robot with everything a person usually turns on, every field of every block written out, so a file shows all there is to change. Each is exactly what `naoqi-sim config --naoqi <version> --viewer --webcam --mic --controls` prints ([cli.md](cli.md), "The `config` command"), which the fast tier checks, so they cannot drift from the config or from the command line: the window with both camera pictures and the people, speech on the loudspeaker, the robot hearing the host microphone, seeing the host's default webcam on its top camera and the render on its bottom one, and the controls opened in the browser. They need the `viewer` and `webcam` extras, and a camera and a microphone the terminal may use (macOS asks once).

A variation (Life on, more languages, another scene) is a copy with the fields changed, or the `config` command's output for other options, not a file of its own.

`ci.json` is a robot for a CI job or a server, which needs nothing of the host: NAOqi 2.8, headless viewer with the placeholder variant (no meshes to install), both cameras on `render` so the robot still sees (the bottom one at 5 fps: a runner rendering in software has little CPU to spare), silent audio output, `audio_input.source = "fake"`. Unlike the other two it writes only what differs from the defaults, which shows that a file can be short. It is the live tier's own settings, which the live tier builds in code for each version it runs (`live_config`, `tests-e2e/conftest.py`; [viewer.md](../host/viewer.md), "In the live tier and CI"); the fast tier checks the file loads and says what it should.

## Open questions

1. **More blocks.** Candidates, each deferred until its spec needs it: `speech.language` and voice, the audio output's device and volume ([audio-output.md](../host/audio-output.md), open questions), the microphone's device ([audio-input.md](../host/audio-input.md), open questions), an image data folder other than the default ([api.md](api.md), "Files on disk"), ports (today 9559, 9562 and the host link's 9563 are fixed, so one naoqi-sim runs per machine), props spawned at start from the config ([props.md](../host/props.md), open questions). Adding a block does not break existing files.
