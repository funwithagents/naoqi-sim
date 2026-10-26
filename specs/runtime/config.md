---
code:
  - src/naoqi_sim/config.py
  - docker/compose.yaml
  - examples/configs/default.json
  - examples/configs/2.8.json
  - examples/configs/headless.json
  - examples/configs/ci.json
  - examples/configs/mic.json
  - examples/configs/webcam.json
  - examples/configs/languages.json
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
  "speech": { "languages": ["English", "French"] },
  "audio_output": { "mode": "play", "record": null },
  "audio_input": { "source": "none", "mono": "duplicate" },
  "video_input": { "top": { "source": "none", "fps": 15, "device": 0 }, "bottom": { "source": "none", "fps": 15, "device": 0 } },
  "viewer": { "headless": false, "scene": "empty", "variant": "auto", "cameras_display": false }
}
```

```python
@dataclass
class NaoqiSimConfig:
    naoqi: NaoqiSettings = field(default_factory=NaoqiSettings)
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    audio_input: AudioInputSettings = field(default_factory=AudioInputSettings)
    video_input: VideoInputSettings = field(default_factory=VideoInputSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)


@dataclass
class NaoqiSettings:
    # "2.1" | "2.8"
    version: NaoqiVersion = "2.1"
    # start() waits this long for the container to be healthy
    ready_timeout_s: float = 240.0


@dataclass
class SpeechSettings:
    # The installed languages, as a NAO's language packs: what ALTextToSpeech.getAvailableLanguages
    # answers and setLanguage accepts, by NAOqi name; the first is the language at boot. Each needs
    # a voice in the speech engine (SPEECH_LANGUAGES, the engine's table: tts-engine.md, "Voices");
    # English's and French's are in its image, any other is fetched on its first use.
    languages: tuple[str, ...] = ("English", "French")


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

    headless: bool = False
    # a bundled scene name ("empty", "table") or a path to an MJCF file
    scene: str = "empty"
    # "auto" | "placeholder" | "aldebaran" (naoqi-viewer's world.variant)
    variant: ViewerVariant = "auto"
    # the head cameras as ALVideoDevice serves them, as pictures in the window
    cameras_display: bool = False
```

- Every block is optional. Missing blocks and fields take the defaults above. **A default is declared once**, on the dataclass field; the loaders read it from there (`dataclasses.fields`), so a default cannot drift between direct construction and JSON.
- **The device blocks are named after the device** ([devices.md](../host/devices.md)): `audio_output`, `audio_input`, `video_input`, each specified in its own spec under `host/`.
- **`NaoqiSimConfig()` is valid and useful**: NAOqi 2.1 with speech on the host loudspeaker, the viewer window on the `empty` scene, and no video or audio input (each `NaoqiSim/*/Source` key stays `none`).
- The `audio_output` block picks the audio output's sink when the caller passes none ([audio-output.md](../host/audio-output.md), "Audio sinks"; [api.md](api.md)): `play` a `DevicePlayer`, `silent` a `NullSink`, `record` a `WavSink`. A sink passed in code (`MemorySink` in tests) wins over the block.
- Paths (`audio_output.record`, and `viewer.scene` when it ends in `.xml`) are resolved relative to the config file when loaded with `from_json_file`, and relative to the working directory otherwise.

### Constructors and validation

- Every config class has the same three constructors: `from_dict(data)`, `from_json(text)` (parses, then calls `from_dict`), and `from_json_file(path)` (reads, then calls `from_json`; an invalid-JSON error names the path). All three share one validation path.
- Errors raise `ConfigError(ValueError)`, with a message that names the offending key path (e.g. `audio_output.record`). A block's own checks raise `ConfigError(message, key=<field>)`, and each enclosing loader prefixes `key` with its own path; the message is never parsed to find the key.
- **Unknown keys are errors**, so a typo fails when the config loads.
- **Type and range checks:** each `Literal` field takes one of its values; `ready_timeout_s` is a positive, finite number; a camera's `fps` is an integer from 1 to 30 (a NAO camera's maximum) and its `device` a non-negative integer; `viewer.scene` is a non-empty string; `speech.languages` is a non-empty list of distinct names, each one the engine has a voice for (`SPEECH_LANGUAGES`, which the fast tier checks against the engine's table), so a language NAOqi supports but the engine has no voice for (`Japanese`) fails at load, naming the languages that have one, rather than at the first `say`. In code a list is accepted and kept as a tuple.
- **Cross-field checks at load:** `audio_output.mode = "record"` needs `audio_output.record`; `viewer.cameras_display` is refused with `viewer.headless` (the pictures are drawn in the window, as naoqi-viewer refuses them). Other fields that do not apply (`device` without a webcam, `record` with `play`) are validated but not applied, so switching a source is a one-word change.
- **Environment checks are not config checks.** Whether the `viewer` extra is installed, Docker answers, the images are built and verified, a webcam or a microphone exists, a language's voice can be fetched: `NaoqiSim.start()` checks these ([api.md](api.md)), so a config file stays valid on any machine.
- `config.py` imports neither `qi`, nor `naoqi_viewer`, nor `sounddevice`.

### The video input: one block per camera

A NAO has two head cameras, and what feeds each one is a config choice: `video_input.top` and `video_input.bottom` are two `CameraSettings`, each with its `source` (`none`, `render`, `webcam`), its `fps` and, for a webcam, its `device`. So the render can feed both cameras (the live tier, `ci.json`), or one of them to spare a small machine half the renders; and once the webcam is built, a laptop's webcam can feed the top camera with the bottom one rendered or unfed, or two webcams the two cameras. A camera on `none` is not fed: a client subscribing to it gets NAOqi's placeholder for a camera never fed ([video-input.md](../host/video-input.md), "As measured").

`fps` is per camera, each on its own schedule: a fast top camera and a slow bottom one spare bandwidth to the clients and keep the viewer within its render budget (30 frames on the top camera and 10 on the bottom one are 40 renders per second, under its ceiling of 60, where 30 on both is not; [video-input.md](../host/video-input.md), "Frames"). Both default to 15. Two cameras at the same `fps` share their slots, so a client reading both sees the same moment.

The block's shape changed on Oct 16, 2026 from one `source`/`fps`/`device` for the whole device to one per camera: a file with the old `video_input.source` or `video_input.fps` fails at load with an unknown key, naming it.

### The viewer and the video input

`viewer.headless` and the cameras' sources together decide whether the simulated world runs ([viewer.md](../host/viewer.md), "Which viewer runs"):

| `viewer.headless` | Cameras' `source` | Sim process | Needs `naoqi-sim[viewer]` |
| --- | --- | --- | --- |
| `false` | any | `NaoqiViewer` in sim mode, with its window | Yes |
| `true` | `render` on either camera | `NaoqiViewer` in sim mode, headless | Yes |
| `true` | neither camera rendered (`none` or `webcam`) | None | No |

So a server config is `{"viewer": {"headless": true}}`, and it needs no extra; CI runs a headless viewer with the render camera instead ([ci.md](../testing/ci.md)).

The `viewer` block is naoqi-sim's own, not an embedded `NaoqiViewerConfig`: `NaoqiSim` builds the viewer's config from it as `NaoqiViewerConfig(mode="sim", headless=headless, cameras_display=cameras_display, naoqi=NaoqiSettings(url=sim.url), world=WorldSettings(scene=scene, variant=variant))`. The mode and the NAOqi URL follow from running naoqi-sim, so they are not settings; naoqi-viewer's other fields (`ghost`, `naoqi.rate_hz`, `launch_timeout_s`) keep naoqi-viewer's defaults. `cameras_display` (naoqi-viewer's camera display, from its commit `8f3976f`) shows the two head cameras in the window's top-right corner as `ALVideoDevice` serves them, read back over qi like any client: what naoqi-sim injected, render or webcam, so it checks the camera path end to end; it costs NAOqi one QVGA subscription at 10 fps, which the video input ignores like any subscriber. `scene` and `variant` take naoqi-viewer's values and defaults (`empty`, `auto`); this module only checks their form (a non-empty string; one of the three variants), since `config.py` does not import `naoqi_viewer`. The rest is checked by naoqi-viewer itself, in `NaoqiSim.start()` ([api.md](api.md), "Lifecycle"): an unknown bundled scene when step 1 builds the `NaoqiViewerConfig` (re-raised as a `ConfigError` with key `viewer.scene`, before anything starts), missing meshes when the viewer launches.

### Sources not built yet

The config accepts every source value from the start (`webcam`, `render`, `mic`, `fake`), so config files written then stayed valid as the device specs landed. Until a device is built, `NaoqiSim.start()` fails with `DeviceNotBuiltError` naming the missing device instead of silently running without it. Every source is built since the webcam (Oct 16, 2026), so none fails this way today; the error stays for the next source accepted before its device.

- **The `wav` source is gone.** It was accepted from the start but never built (`NaoqiSim.start()` refused it); the `fake` source replaced it before any release ([audio-input.md](../host/audio-input.md), "Sources"), so a file that still says `"wav"`, or has a `wav` field, fails at load like any unknown value or key. `audio_input.gate_tail_s` went with the microphone gate ([audio-input.md](../host/audio-input.md), "The robot hears itself") and fails the same way.

### File format

JSON: a naoqi-sim file is pasted into another program's JSON config unchanged, and back, which a second format would break. The example files carry no comments; what each one is for is listed below and in the README.

### Embedding in other configs

- The `naoqi-sim` CLI reads a `NaoqiSimConfig` file as is (`naoqi-sim run --config sim.json`, see [cli.md](cli.md)).
- Another program embeds it as one block of its own config, exactly a `NaoqiSimConfig`: a naoqi-sim file pastes in unchanged and copies back out unchanged. The program hands that block to `NaoqiSimConfig.from_dict`, imported from `naoqi_sim.config` (which imports neither qi nor the devices' libraries); naoqi-sim knows nothing of the enclosing config.

### Example files

`examples/configs/` holds ready-to-use files, kept in sync with this spec:

- `default.json`: 2.1, window, speech only;
- `2.8.json`: the same on 2.8;
- `headless.json`: 2.1, no window, silent audio output (servers);
- `ci.json`: 2.1, headless viewer with the placeholder variant, both cameras on `render` (the bottom one at 5 fps: a runner rendering in software has little CPU to spare), silent audio output, `audio_input.source = "fake"`: the live tier's settings, which add a test scene from `tests-e2e/` ([viewer.md](../host/viewer.md), "In the live tier and CI");
- `mic.json`: 2.1, window, speech on the loudspeaker, `audio_input.source = "mic"`: the robot hears the room, its own voice included, as a NAO does;
- `webcam.json`: 2.1, window, the host's default webcam (`device` 0) on the top camera and the render on the bottom one: the robot sees the room through its top camera, and the `mixed` summary shows; `viewer.cameras_display` on, so the window shows both cameras as `ALVideoDevice` serves them; needs the `webcam` and `viewer` extras.

## Open questions

1. **More blocks.** Candidates, each deferred until its spec needs it: `speech.language` and voice, the audio output's device and volume ([audio-output.md](../host/audio-output.md), open questions), the microphone's device ([audio-input.md](../host/audio-input.md), open questions), an image data folder other than the default ([api.md](api.md), "Files on disk"), ports (today 9559, 9562 and the host link's 9563 are fixed, so one naoqi-sim runs per machine). Adding a block does not break existing files.
