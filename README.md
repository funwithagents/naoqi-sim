# naoqi-sim (prototype)

A NAO in a box: NAOqi 2.1.4.13 (`naoqi-bin` from the Choregraphe suite) running in a local
Docker image with our Python 2.7 override modules loaded into its process. Unofficial, MIT;
the image is built locally from the user's suite and is never published.

Status: validation spike done on NAOqi 2.1.4.13 and 2.8.7.4, see [spike/RESULTS.md](spike/RESULTS.md).

## Layout

- `docker/naoqi/Dockerfile.naoqi-2.1`: Ubuntu 14.04 amd64 + 2.1.4.13 suite tarball at `/opt/naoqi`, non-root user, entrypoint.
- `docker/naoqi/Dockerfile.naoqi-2.8`: Ubuntu 16.04 amd64 + 2.8.7.4 suite, NAO V6 model, `naoqi-bin` behind the suite's gateway on 9559 (compose profile `2.8`; 2.1 is profile `2.1`).
- `docker/naoqi/entrypoint-2.1.sh`, `docker/naoqi/entrypoint-2.8.sh`: each version's boot procedure, top to bottom: write a copy of the suite's `autoload.ini` without the built-ins we replace and with our modules in their place (right after `pythonbridge`: the native relay, the loader that loads our Python modules, the C++ fronts), start `naoqi-bin` with it, wait for a settled service list, check the replacements and the added services answer and mark `NaoqiSim` ready. Any failure exits non-zero. Any failure exits non-zero. `docker/naoqi/entrypoint-lib.sh` holds the steps both share.
- `docker/naoqi/healthcheck.sh`: the Docker healthcheck, `NaoqiSim.isReady` on 9559.
- `docker/naoqi/services/`: the code that runs inside NAOqi, one folder per service, its Python 2.7 core and per-version shells (`ALModule` on 2.1, qi service on 2.8) with its C++:
  - `status-service/`: `naoqi_sim_status_*`, the `NaoqiSim` service (versions, device sources, readiness, as a service and `NaoqiSim/*` ALMemory keys).
  - `speech/`: `naoqi_sim_speech_front.cpp`, `ALTextToSpeech` itself, a C++ front so callers can start, wait for and stop a sentence by task id as on a NAO, over `naoqi_sim_speech_core` (tag parsing, engine call, events) and its shells.
  - `audio-player/`: `naoqi_sim_audio_player_front.cpp`, `ALAudioPlayer` itself, a C++ front over `naoqi_sim_audio_player_core` (sound files decoded with the suite's libsndfile, volumes, loops, sound sets, each sound a stream of the host audio output, which mixes it with the speech).
  - `audio-device/`: `naoqi_sim_audio_device_*`, the `ALAudioDevice` the desktop suites lack (subscribers, formats, the host link client), and `naoqi_sim_audio_device_relay.cpp`, a small C++ module that hands each microphone buffer to a subscriber's `processRemote` as a binary, as a NAO's C++ `ALAudioDevice` does (Python 2.7 inside NAOqi cannot send one).

  Each image compiles the C++ in a builder stage against the version's own C++ SDK (2.8's from [aldebaran/nao6-doc-sdk](https://github.com/aldebaran/nao6-doc-sdk)) and keeps only the `.so` files.
- `docker/tts-engine/`: the speech engine container (Piper, `POST /say`, streams PCM to the host audio output), one voice per NAOqi language for sixteen of them: the config's `speech.languages` installs them as a NAO's language packs (English and French by default, their voices in the image; any other language's voice is fetched into a Docker volume on first use). The voices come from `rhasspy/piper-voices` and are never in this repository; each voice's dataset licence is CC0, public domain or CC BY 4.0 (the French voice is trained on the SIWIS French speech synthesis database, CC BY 4.0), most voices being fine-tuned from a research-only base, as `specs/container/tts-engine.md` ("Voices") records. Piper itself is GPL and stays inside that container, built on your machine and never pushed.
- `src/naoqi_sim/sim.py`, `config.py`, `stack.py`, `viewer.py`, `cli.py`: the `NaoqiSim` object, its `NaoqiSimConfig` (JSON, examples in `examples/configs/`), the containers, the sim window (naoqi-viewer, the `viewer` extra) and the `naoqi-sim` command.
- `src/naoqi_sim/audio_output.py`: the host audio output a `NaoqiSim` runs, the robot's loudspeakers as its sound server: it mixes the named streams the containers send (the `speech` stream, one `player:<id>` per sound) at 48 kHz stereo, and the mix goes to a sink: the output device, nothing (`silent`), a WAV file (`record`) or memory (tests, which also keeps each stream).
- `src/naoqi_sim/audio_input.py`, `host_link.py`: the robot's microphones, served to `ALAudioDevice` over the host link (port 9563): the host microphone (`audio_input.source = "mic"`) or the fake source (`"fake"`: silence plus what code plays with `sim.fake_audio.play("hello.wav")`, for tests). Either way the robot hears its own voice, as a NAO does.
- `src/naoqi_sim/files.py`: where the recipes (`docker/`, shipped in the wheel as package data) and the image data are, in a checkout or installed.
- `src/naoqi_sim/docker_images.py` and `src/naoqi_sim/suite.py`: `naoqi-sim fetch-and-build-images`, which fills the image data folder (`docker/image-data/<version>/` in a checkout) with the pinned Choregraphe suite, the `animations` package extracted from the public robot image and the relay's build files (the version's C++ SDK, 334 MB for 2.1 and 1.3 GB for 2.8), all public and hash-checked; it keeps what is already there, builds the images with the naoqi-sim version as label, and boots them once to verify them (`docker/image-data/images.json`).
- `docker/image-data/`: gitignored; `2.1/` and `2.8/` each hold the suite tarball, `animations.pkg` and the relay's build files; `images.json` lists the verified images.
- `docker/compose.yaml`: also a package store volume per version, so packages installed over qi or Choregraphe (the sound set) survive `docker compose down`; `down -v` resets them.
- `tests/`, `tests-e2e/`: the fast tier and the live tier, which starts the containers itself.

## Run

Python 3.12 or 3.13 on macOS (arm64), Linux (x86_64) or Windows (x64): the libqi wheels (`qi`, from
[funwithagents/libqi-python](https://github.com/funwithagents/libqi-python)'s package index,
`https://funwithagents.github.io/libqi-python/simple/`) exist for those only. The containers need
Docker (Docker Desktop on macOS and Windows; Windows is not tested end to end yet).

```bash
uv sync --dev
uv run naoqi-sim fetch-and-build-images   # fetch, build and verify the 2.1 and 2.8 images (or: 2.1 / 2.8); rerun after changing docker/
uv run naoqi-sim run                      # NAOqi 2.1 with the sim window, speech on the loudspeaker; Ctrl-C stops it
uv run naoqi-sim run --config examples/configs/2.8.json       # or NAOqi 2.8; headless.json: no window, silent
uv run naoqi-sim run --config examples/configs/mic.json       # the robot hears through your microphone
uv run naoqi-sim run --config examples/configs/webcam.json    # its top camera sees through your webcam (macOS: Camera access for the terminal)
# A webcam does not turn with the head: the robot detects you and the people markers are right, but
# ALBasicAwareness keeps turning the head while you stay off-centre. Check head tracking with the
# render camera and face props (specs/host/video-input.md, "The webcam source").
uv run naoqi-sim run --config examples/configs/languages.json # English, French and German installed (German's voice fetched once)
uv run naoqi-sim status                   # from another terminal: the containers and the robot's state
uv run naoqi-sim logs --follow            # the containers' logs
uv run naoqi-sim cleanup                  # after a run that died without stopping
```

Then connect any qi client to `tcp://127.0.0.1:9559`, as to a NAO. The `NaoqiSim` service tells a client it is on naoqi-sim (`getVersion`, `getNaoqiVersion`, `isReady`; `NaoqiSim/*` keys in ALMemory): it reports the naoqi-sim version the images were built with. The compose project is `naoqi-sim`, so the package store volumes are `naoqi-sim_packages-2.1` and `naoqi-sim_packages-2.8`.

## Use from another project

naoqi-sim is not on PyPI: a project depends on it from GitHub, with uv, pinned to a commit or tag.
In the project's `pyproject.toml`:

```toml
[project]
requires-python = ">=3.12,<3.14"            # naoqi-sim's range
dependencies = ["naoqi-sim[viewer]"]          # or "naoqi-sim": no window, no render camera; add "webcam" for the webcam source

[tool.uv.sources]
naoqi-sim = { git = "https://github.com/funwithagents/naoqi-sim", rev = "<commit or tag>" }
```

uv takes `qi` (from the libqi index) and naoqi-viewer from naoqi-sim's own sources, so the project
declares neither (and should not pin naoqi-viewer at another commit), nor the platforms: on a machine
the libqi wheels don't cover, `uv sync` fails for want of a `qi` wheel. Then, once per machine:

```bash
uv sync
uv run naoqi-sim fetch-and-build-images   # the images; the suites go to the user data directory
uv run naoqi-viewer fetch-meshes          # optional: Aldebaran's meshes in the window (license prompt)
uv run naoqi-sim run                      # or a NaoqiSim in the project's code
```

An installed naoqi-sim reads its recipes from its package and keeps the image data (1.8 GB for
both versions), `hashes.json` and `images.json` in the user data directory
(`~/Library/Application Support/naoqi-sim/image-data` on macOS, `~/.local/share/naoqi-sim/image-data` on
Linux, `%LOCALAPPDATA%\naoqi-sim\image-data` on Windows). `NAOQI_SIM_IMAGE_DATA=<folder>` points it, or a checkout, at another image data folder, so a
checkout and the projects depending on naoqi-sim can share one copy. naoqi-viewer's meshes are shared
by every environment on the machine already. pip is not supported: it ignores uv's sources, so
it would miss naoqi-viewer's git pin.

## Test

```bash
uv run pytest             # fast tier: no Docker, no suite
uv run pytest tests-e2e   # live tier: builds the images if needed, runs 2.1 and 2.8 with NaoqiSim
```

Stop any running naoqi-sim before the live tier: it needs ports 9559 and 9562.
