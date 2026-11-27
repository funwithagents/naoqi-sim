# naoqi-sim from Python

The `naoqi-sim` command is a thin layer over one object, `NaoqiSim`. A program or a test suite uses that object directly: it starts the robot, lends it senses the code controls, and stops it.

## Add it to a project

naoqi-sim supports Python 3.12 and 3.13, so the project's `requires-python` must stay inside `">=3.12,<3.14"`. Then:

```bash
uv add "naoqi-sim[viewer] @ git+https://github.com/funwithagents/naoqi-sim"
uv run naoqi-sim fetch-and-build-images --naoqi 2.8    # once per machine, per NAOqi version
```

- uv takes `qi` and naoqi-viewer from naoqi-sim's own sources: the project declares neither, and should not pin naoqi-viewer itself.
- Pin a commit or a tag (`...naoqi-sim@<commit>`) and move it on purpose: a commit that changes the images asks for `fetch-and-build-images` again.
- Leave `[viewer]` out when you need neither the window nor rendered cameras; add `webcam` for the webcam.
- On a platform without a `qi` wheel (macOS Intel, Linux arm64), `uv sync` fails for want of it.
- The images and downloads are shared by every project on the machine ([reference/troubleshooting.md](../reference/troubleshooting.md#files-on-disk)).

## Start and stop

```python
import asyncio

import qi
from naoqi_sim import NaoqiSim


async def main() -> None:
    async with NaoqiSim("2.8") as sim:
        session = qi.Session()
        session.connect(sim.url)
        session.service("ALTextToSpeech").say("Hello")


asyncio.run(main())
```

- `NaoqiSim("2.8")` is the robot of `naoqi-sim run --naoqi 2.8`: no window, no camera, no microphone.
- `async with` starts it and stops it on the way out, also after an error. `await sim.start()` and `await sim.stop()` do the same by hand.
- A start checks everything first (Docker, the images, the extras, the ports) and raises an error that says what to do before anything runs.
- `sim.url` is `tcp://127.0.0.1:9559`. Your code opens its own `qi.Session`, exactly as for a NAO; naoqi-sim gives no session of its own.
- One robot runs per machine: its ports are fixed.

## Describe the robot

A NAOqi version is enough. For anything else, give a config, from a file, from a dict, or built in code; the fields are in [reference/configuration.md](../reference/configuration.md).

```python
from naoqi_sim import NaoqiSim

sim = NaoqiSim.from_json_file("my-nao.json")

sim = NaoqiSim.from_dict(
    {
        "naoqi": {"version": "2.1"},
        "setup": {"available_languages": ["French"], "language": "French"},
        "viewer": {"headless": False},
    }
)
```

A wrong config raises `ConfigError`, naming the key, before a `NaoqiSim` exists.

## Drive the robot's senses

A running `NaoqiSim` gives a program what a person standing next to the robot would do to it.

**What the robot hears.** With `"audio_input": {"source": "fake"}`, the robot's microphones hear a quiet room in which your code plays sounds:

```python
take = sim.fake_audio.play(
    "hello.wav"
)  # a 16-bit WAV, 16 or 48 kHz; or a numpy int16 array
take.wait(5)  # until it has finished playing
```

**What the robot sees.** With a camera on `"render"`, put faces and objects in front of it. Positions are in metres, in the scene's frame or the robot's (`frame="robot"`: x ahead, y to its left, z up):

```python
face = sim.props.spawn("face", (1.0, 0.0, 0.5), frame="robot")  # a face one metre ahead
sim.props.place(
    face.name, (1.0, 0.5, 0.5), frame="robot", duration=1.0
)  # moves there in 1 s
sim.props.despawn(face.name)
```

**What the robot feels.** Its 13 touch sensors, by NAOqi's names (`Head/Touch/Front`, `LHand/Touch/Back`, `RFoot/Bumper/Left`...; `"Head"` is the three head sensors):

```python
await sim.touch.tap("Head/Touch/Front")  # pressed 0.2 s
await sim.touch.press("Head")
await sim.touch.release("Head")
await sim.cover_camera("top")  # a hand over the camera
await sim.uncover_camera("top")
await (
    sim.stop_activity_gesture()
)  # this NAOqi version's gesture to stop the running activity
```

**What the robot said.** Pass a `MemorySink` to keep the audio instead of playing it:

```python
from naoqi_sim import MemorySink, NaoqiSim

sink = MemorySink()
async with NaoqiSim("2.8", sink=sink) as sim:
    ...  # make the robot speak
    spoken = sink.wait_for(lambda playback: playback.stream == "speech")
    assert spoken.duration_s > 0.5  # spoken.pcm is the audio itself
```

Everything else is NAOqi's own API over `qi`: naoqi-sim adds no call for what a NAO already offers.

## In tests and CI

- **Nothing of the host is needed**: `"audio_output": {"mode": "silent"}` (or a `MemorySink`), `"audio_input": {"source": "fake"}`, the default `"viewer": {"headless": true}`. The robot then runs on a server with no display, no loudspeaker and no microphone.
- **Rendered cameras without a display** work too: a camera on `"render"` with `"viewer": {"headless": true, "variant": "placeholder"}`, which asks for no meshes.
- **Start the robot once per test session**, not per test: a start takes tens of seconds (NAOqi itself boots in about 5 seconds on 2.1 and 15 on 2.8, then the engines load), more on a CI runner.
- **Real time**: the robot speaks, moves and listens at the speed of a real one. Wait for NAOqi's events rather than sleeping.
- **In CI**, run `naoqi-sim fetch-and-build-images --naoqi <version>` in the job and cache the images between runs (`docker save` and `docker load`, with the download folder's `images.json`, the list of verified images); a cold build is about 20 minutes per NAOqi version. naoqi-sim's own workflow, [.github/workflows/ci.yml](../../.github/workflows/ci.yml), does this on GitHub's hosted Linux runners.
- **From another process**, `await naoqi_sim.read_status()` says what runs on the machine, and `await naoqi_sim.cleanup()` removes what a crashed run left.

## Tell a simulated robot from a real one

Only naoqi-sim has a `NaoqiSim` service:

```python
status = (
    await sim.status()
)  # version, naoqi_version, ready, camera_source, audio_source, ...
```

or, from any qi client, `session.service("NaoqiSim").getVersion()` and the `NaoqiSim/*` keys in ALMemory. Which robot it is reads as on a NAO: `RobotConfig/Body/Type` and `RobotConfig/Body/Version` in ALMemory.

The full API, with every error, is specified in [specs/runtime/api.md](../../specs/runtime/api.md).
