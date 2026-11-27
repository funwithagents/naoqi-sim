# naoqi-sim

naoqi-sim is a simulated NAOqi robot on your computer: today a NAO, on NAOqi 2.1 or 2.8. It runs Aldebaran's own NAOqi in a Docker container and gives it what a desktop NAOqi lacks to behave like the robot: a voice on your loudspeaker, your microphone for ears, your webcam or a rendered scene for eyes, speech recognition, face detection and people perception, Autonomous Life with its dialog, touch sensors, and a 3D window showing the robot. It answers on `127.0.0.1:9559`, so Choregraphe, an existing script or any `qi` client connects to it exactly as to a real robot, with no naoqi-sim-specific code.

> [!IMPORTANT]
> **Unofficial.** naoqi-sim is an independent project. It is not affiliated with or endorsed by Aldebaran or Maxtronics; NAO, NAOqi and Choregraphe are their trademarks. naoqi-sim contains none of their software: it downloads Aldebaran's publicly available NAOqi software to your machine and builds the images there, and they are never published.

[docs/features.md](docs/features.md) lists what is simulated, and [docs/reference/differences-from-a-nao.md](docs/reference/differences-from-a-nao.md) what is not.

## Quick start

You need Docker running, [uv](https://docs.astral.sh/uv/), and about 11 GB of free disk ([requirements](#requirements)). Then run these four commands, one after the other:

```bash
# 1. Install naoqi-sim
uv tool install --python 3.12 "naoqi-sim[viewer,webcam] @ git+https://github.com/funwithagents/naoqi-sim"

# 2. Download Aldebaran's NAOqi 2.8 and build the robot's images (about 20 minutes, once)
naoqi-sim fetch-and-build-images --naoqi 2.8

# 3. Optional: Aldebaran's NAO meshes for the 3D window (shows a license, type "yes")
naoqi-sim fetch-meshes

# 4. Run the robot
naoqi-sim run --naoqi 2.8 --viewer --mic --controls
```

You now have a NAO V6 in a 3D window, hearing your microphone and speaking on your loudspeaker, with its controls page open in your browser. `Ctrl-C` in the terminal stops it.

Once the terminal says `ready at tcp://127.0.0.1:9559`, connect to the robot as to a real one:

- **Choregraphe**: *Connect to* the IP `127.0.0.1`, port 9559.
- **A script**: `qi.Session().connect("tcp://127.0.0.1:9559")`.

Other ways to run it, changing only step 4:

```bash
naoqi-sim run --naoqi 2.8 --viewer --webcam --mic --controls   # the robot sees you through your webcam
naoqi-sim run --naoqi 2.8 --controls                           # no window, no microphone: the robot and its controls page
naoqi-sim run --naoqi 2.1 --viewer --mic --controls            # a NAO V5 on NAOqi 2.1 (build it first: step 2 with --naoqi 2.1)
```

The rest of this page explains each step; [docs/getting-started.md](docs/getting-started.md) goes through the first session in more detail.

## Requirements

- **macOS on Apple silicon, Linux x86_64 or Windows x64.** The `qi` wheels exist for those only. Developed on macOS, tested on Linux in CI; Windows is not tested end to end yet.
- **Docker**, running (Docker Desktop or OrbStack on macOS, Docker Engine on Linux).
- **[uv](https://docs.astral.sh/uv/)**, which installs Python 3.12 or 3.13 itself. pip is not supported: naoqi-sim takes `qi` and naoqi-viewer from their own sources, which pip ignores.
- **Disk space**: about 7 GB for NAOqi 2.1, 11 GB for 2.8, 16 GB for both. That is the downloads (0.7 GB for 2.1, 3.2 GB for 2.8), the NAOqi image built from them (4.5 GB and 6.3 GB) and the three engines' images (1.5 GB, shared by both versions).

## The steps, explained

### 1. Install

naoqi-sim is not on PyPI: it installs from GitHub. `uv tool install` puts the `naoqi-sim` command on your PATH. The part in brackets chooses the optional pieces:

| Extra | Adds | You need it for |
|---|---|---|
| *(none)* | The robot, its voice, your microphone, the controls page | `naoqi-sim run --naoqi 2.8`, a server, CI |
| `viewer` | [naoqi-viewer](https://github.com/funwithagents/naoqi-viewer) | The 3D window, and the scene rendered into the robot's cameras (`--viewer`) |
| `webcam` | OpenCV | Your webcam as the robot's top camera (`--webcam`) |

To use naoqi-sim from a Python project instead, see [Use it from Python](#use-it-from-python).

### 2. Build the images

`fetch-and-build-images` downloads Aldebaran's desktop NAOqi, the robot's animations and the C++ SDK of the version you name from Aldebaran's public repositories (hash-checked), builds the Docker images and boots the robot once to verify them.

- `--naoqi` is required: `2.1`, `2.8`, or both (`--naoqi 2.1 2.8`). Name only the versions you run, since each one is gigabytes of downloads and images.
- It is the one slow step, about 20 minutes per version, done once per machine.
- Run it again after upgrading naoqi-sim.

### 3. Get the meshes (optional)

`fetch-meshes` makes the window show the real NAO. Without it the robot is drawn with simple placeholder shapes, and everything else works the same. Aldebaran's meshes are under CC BY-NC-ND 4.0 (non-commercial): the command shows the license, waits for you to type `yes`, then installs them from [funwithagents/naoqi-meshes](https://github.com/funwithagents/naoqi-meshes), once for every project on the machine.

### 4. Run

`naoqi-sim run` starts the robot and stays in the foreground until `Ctrl-C`. Name the NAOqi version, then turn on what you want:

| Option | What it does |
|---|---|
| `--naoqi 2.1` or `--naoqi 2.8` | The NAOqi version. Required. 2.1 runs a NAO V5 (or a V4 with `--robot-version v4`), 2.8 a NAO V6 |
| `--viewer` | Opens the 3D window, and feeds the robot's cameras what it sees there |
| `--webcam` | Feeds the robot's top camera your webcam instead (macOS asks for camera access once) |
| `--mic` | Lets the robot hear your microphone |
| `--controls` | Opens a web page to wake the robot up, change its posture, switch Autonomous Life on, touch its sensors and cover its cameras |

With `--naoqi` alone the robot runs with no window, no camera and no microphone, speaking on your loudspeaker: nothing more than a plain install needs.

While it runs, from another terminal:

```bash
naoqi-sim status     # the containers and the robot's state
naoqi-sim logs -f    # the containers' logs
naoqi-sim cleanup    # after a run that died without stopping
```

### A config file of your own

Everything else (the languages, Autonomous Life at boot, the posture, the scene, recording the audio) is a field of a JSON config file. `naoqi-sim config` prints the config of the same options, to start from:

```bash
naoqi-sim config --naoqi 2.8 --viewer --mic > my-nao.json   # every field, at its value
naoqi-sim run --config my-nao.json
```

[examples/configs/](examples/configs/) has one such file per NAOqi version, and [docs/reference/configuration.md](docs/reference/configuration.md) describes every field.

## Use it from Python

Add naoqi-sim to a project whose `requires-python` is `">=3.12,<3.14"` (naoqi-sim's range):

```bash
uv add "naoqi-sim[viewer] @ git+https://github.com/funwithagents/naoqi-sim"
```

```python
import asyncio

import qi
from naoqi_sim import NaoqiSim


async def main() -> None:
    async with NaoqiSim(
        "2.8"
    ) as sim:  # starts the containers, stops them on the way out
        session = qi.Session()
        session.connect(sim.url)  # tcp://127.0.0.1:9559, as a NAO
        session.service("ALTextToSpeech").say("Hello, I am a simulated NAO.")


asyncio.run(main())
```

A `NaoqiSim` takes a NAOqi version or a full config (`NaoqiSim.from_json_file("my-nao.json")`), and gives a test what it needs to drive the robot's senses: sounds played into its microphones, faces and objects put in front of its cameras, its touch sensors. [docs/guides/python.md](docs/guides/python.md) covers it, with testing and CI.

## Compatibility

| naoqi-sim | NAOqi | Robots | Python | `qi` |
|---|---|---|---|---|
| 0.1 | 2.1.4.13 | NAO V5 (default), NAO V4 | 3.12, 3.13 | 3.1.8 or later, from [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) |
| | 2.8.7.4 | NAO V6 | | |

naoqi-viewer comes pinned to the commit naoqi-sim is tested with.

## Documentation

| | |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | The first session: install, build, run, connect Choregraphe or a script, stop |
| [docs/features.md](docs/features.md) | What is simulated, service by service |
| [docs/guides/python.md](docs/guides/python.md) | `NaoqiSim` in a program, in tests and in CI |
| [docs/reference/cli.md](docs/reference/cli.md) | Every command and option |
| [docs/reference/configuration.md](docs/reference/configuration.md) | Every config field and its default |
| [docs/reference/differences-from-a-nao.md](docs/reference/differences-from-a-nao.md) | Where the simulated robot differs from a real one |
| [docs/reference/troubleshooting.md](docs/reference/troubleshooting.md) | Ports, files on disk, common errors |

[docs/index.md](docs/index.md) lists them by task. The design behind each page is in [specs/](specs/_index.md); working on naoqi-sim itself is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

naoqi-sim's own code is Apache-2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE). What it downloads and runs on your machine keeps its own license:

- **Aldebaran's software** (the desktop NAOqi, the robot's packages, the C++ SDK) is Aldebaran's, fetched from Aldebaran's public repositories under their terms. The images built from it stay on your machine.
- **Aldebaran's NAO meshes** are CC BY-NC-ND 4.0, non-commercial, and installed only after you accept that license.
- **The voices** are [Piper](https://github.com/rhasspy/piper) voices, each under its dataset's license (CC0, public domain or CC BY 4.0), most of them fine-tuned from a research-only base voice; Piper itself is GPL and stays inside its container. [specs/container/tts-engine.md](specs/container/tts-engine.md) ("Voices") has the detail per language.
- **The speech recognition models** are [Vosk](https://alphacephei.com/vosk/) models, Apache-2.0 or MIT; **the face detector** is OpenCV's YuNet, Apache-2.0.
