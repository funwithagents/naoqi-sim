---
code:
  - .github/workflows/ci.yml
  - .github/workflows/e2e-windows.yml
  - tests-e2e/support.py
  - tests-e2e/conftest.py
tests:
  - tests-e2e/test_modules_live.py
  - tests-e2e/test_audio_loopback_live.py
---

# Continuous integration

**Status:** Implemented

## Purpose

Both test tiers ([testing.md](testing.md)) run on GitHub's hosted runners for every pull request and every push to `main`, so the verification gate of [AGENTS.md](../../AGENTS.md) (lint, type check, tests) is a machine's verdict on each change and not only a local command. The live tier runs against real NAOqi stacks that the runner fetches, builds and verifies itself, since the image data are Aldebaran's public downloads. Like [testing.md](testing.md), this is a cross-cutting practice, not a runtime concept: it is implemented by `.github/workflows/ci.yml` and by the live tier's switch from skipping to failing (`tests-e2e/support.py`, `tests-e2e/conftest.py`).

Three jobs side by side: a static gate, the fast tier and a live matrix. The image cache follows naoqi-viewer's CI, which already builds naoqi-sim's 2.1 images on its runners.

## Decided

### The runner

- **GitHub-hosted runners, the free tier.** Runners are pinned by name (`ubuntu-24.04`, `macos-15`, `windows-2025`) rather than `*-latest`, so Docker, Mesa and the system libraries move only when a pin is bumped on purpose. No self-hosted runner.
- **Linux is the platform** because it runs the NAOqi images natively (amd64, no emulation as on Apple Silicon) and has a display-less GL backend, Mesa's EGL, for the headless viewer's renders. GitHub's macOS runners have no Docker, and its Windows runners run Windows containers only, so they run the fast tier only. A green run is also the "works on Linux" half of milestone 3's exit ([_overview.md](../_overview.md), "Milestones").
- **The fast tier on the three platforms.** naoqi-sim installs on Linux x86_64, macOS arm64 and Windows x64 ([project.md](../project.md)), each with its own `qi` wheel, and its host side meets each platform's paths, encodings, signals and process rules. So `fast-tier` is a matrix over `ubuntu-24.04`, `macos-15` and `windows-2025`, which also checks that `uv.lock` installs on each ([testing.md](testing.md), "Platforms"):
  - **Linux** runs the whole fast tier, but for the one Windows-only test (Ctrl-Break, [cli.md](../runtime/cli.md)).
  - **macOS and Windows** deselect the tests of the code that runs in the Linux containers (`-m "not container_code"`, 88 of 290): Linux tests that code, and another host adds nothing ([testing.md](testing.md), "Platforms").
  - The tests are the same everywhere, real-time ones included. The macOS runner wakes threads 25 to 50 ms late and the Windows one about 25 ms (the figure is in each job's pytest header); the first runs of the matrix failed a dozen timing tests on macOS, which led to the mixer keeping its schedule and to the measured `lateness` in the bounds of reaction times.
- **One Python**, 3.12, the floor of `requires-python` and the version `.python-version` names; uv installs it.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main` and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
| --- | --- |
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check src tests tests-e2e docker/tts-engine`, `pyright` |
| `fast-tier` | Matrix `ubuntu-24.04`, `macos-15`, `windows-2025`, `fail-fast: false`, steps in bash: the same sync; `uv run pytest -rs` (in parallel, [testing.md](testing.md), "Tooling"), with `-m "not container_code"` off Linux |
| `e2e-sim` | A matrix over the NAOqi versions (`2.1`, `2.8`), `fail-fast: false`, each entry on its own runner: restore or build the version's images, then `uv run pytest tests-e2e -rs` on that version only |

- The three jobs (seven runners: the fast tier's three entries and the live tier's two) run side by side and none waits on another: a run takes as long as its slowest job, a live entry.
- **`--locked`**: the sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock. The sync installs the `dev` group, so the `viewer` extra (naoqi-viewer, from its pinned Git commit) is there in every job.
- **The format check covers the code directories only**, since `ruff format .` would reflow the Python blocks inside Markdown files. The Python in `docker/naoqi/services/` is Python 2.7, outside ruff ([project.md](../project.md)).
- **Audio only where it is tested.** `sounddevice` is imported at the first stream of the device sink and when the microphone opens ([audio-output.md](../host/audio-output.md), [audio-input.md](../host/audio-input.md)): the `check` and `fast-tier` jobs fake it and need no sound system. The live entries get a **virtual loopback**, a PulseAudio null sink as the default output and its monitor as the default input (a virtual microphone wired to a virtual loudspeaker), so the live tier's loopback tests run on every push: the `mic` source, the robot's own speech coming back into the microphone, and the `DevicePlayer` sink ([testing.md](testing.md), "Live tier"). The `MemorySink` stays the live tier's sink for every other test.
- **One version per live entry.** Both versions publish 9559 and one naoqi-sim runs per machine, so each version gets its own runner. The entry sets `NAOQI_SIM_E2E_VERSION` to its version: the `nao` fixture then runs that version only, and a missing suite, image or Docker **fails** the entry instead of skipping it. An unknown value fails the session at collection. Without the variable (a local run) the tier keeps its rule of skipping what the machine lacks ([testing.md](testing.md), "Skip, never fail, without the means"); in CI a skip would turn the job green with nothing tested.
- **Each job carries a `timeout-minutes`** well under GitHub's default (10 for `check`, 15 for `fast-tier`, 45 for a live entry, whose cold build is the longest step), so a hung boot fails in minutes.

### The live entries

In order:

1. **Disk.** The 2.8 image is about 6.3 GB, its `docker save` archive as much again, and the suite 1.3 GB on a cold build: the entry first deletes the runner's preinstalled toolchains naoqi-sim never uses (Android SDK, .NET, GHC, CodeQL), which frees about 25 GB. Both entries do it, so they stay alike.
2. **Sync**: `uv sync --locked`.
3. **The cache key**, computed by naoqi-sim itself: `naoqi-<version>-<naoqi-sim version>-<recipes digest>-<hash of src/naoqi_sim/suite.py>`. The first two parts are what `check_images` compares to the image labels ([api.md](../runtime/api.md), "Images"), so the key changes exactly when a start would find the images outdated; the suite pins' hash covers a new suite or package, which the labels do not see.
4. **Restore** (`actions/cache/restore`): one archive per version, `docker save` of the version's NAOqi image and the `tts` image, together with `docker/image-data/images.json`, the record of the verified image IDs. On a hit, `docker load` and the archive is deleted at once to free its space: the image IDs survive the save and load, so `check_images` accepts the images as verified.
5. **On a miss**: `uv run naoqi-sim fetch-and-build-images <version>`, which fetches the pinned image data (the suite, the robot image for the `animations` package, and the build files of the native relay: the version's C++ SDK, 334 MB for 2.1 and 1.3 GB for 2.8; [container.md](../container/container.md), "Build files"), builds the images and verifies they boot, as on a user's machine; then `docker save` and **save** (`actions/cache/save`) right away, before the tests, so a failing live tier does not rebuild on the next run. The image data are never cached, as in naoqi-viewer's CI: they are needed only on a miss, and a miss downloads them from Aldebaran's repositories.
6. **System packages**: Mesa's GL and a virtual display (`xvfb`, `xauth`, `libgl1`, `libglx-mesa0`, `libegl1`, `libgl1-mesa-dri`), and audio (`pulseaudio`, `pulseaudio-utils` for `pactl`, `paplay` and `parec`, `libportaudio2`, which `sounddevice` takes from the system on Linux, and `libasound2-plugins`, which routes ALSA's default device, the one PortAudio opens, to PulseAudio).
7. **The audio loopback**: `pulseaudio --start --exit-idle-time=-1`, a null sink `ci` (`pactl load-module module-null-sink sink_name=ci`), set as the default sink with `ci.monitor` as the default source; `pactl info` and `sounddevice`'s device list in the log. Plus **a silent client at 10 ms** (`pacat --latency-msec=10 < /dev/zero`, in the background for the whole job): a null sink renders at the latency its clients ask for, and with none asking for less it renders about 1.5 s late (measured on the runner and reproduced in an Ubuntu 24.04 container), so the robot's own voice would come back into the microphone 1.5 s late. With the client, what is played is heard within a few ms.
8. **The live tier**: `uv run pytest tests-e2e -rs` with `NAOQI_SIM_E2E_VERSION` and `NAOQI_SIM_E2E_AUDIO=loopback`, under `xvfb-run`, so the sim-window test runs on the 2.1 entry instead of skipping for want of a display, and the loopback tests fail rather than skip if the loopback is missing. Warnings and errors are logged live (`-o log_cli=true --log-cli-level=WARNING`).
9. **On failure**: the end of the NAOqi and `tts` containers' logs, if any are still there (`naoqi-sim logs` needs a running stack, so the step uses `docker logs` on the containers the test left behind, and prints nothing when the `NaoqiSim` stopped cleanly).

- **Sizes.** Measured locally: the 2.1 image is 4.5 GB on disk (1.4 GB compressed), the 2.8 image 6.3 GB (2.7 GB), `tts` 0.8 GB (0.27 GB). With zstd, the two archives take about 5 GB of the repository's 10 GB cache budget; an edit under `docker/` adds a new pair, and GitHub evicts the least recently used.
- **Python 2.7 check.** A live test compiles every module in the image's `/opt/naoqi/modules/` with the image's own interpreter (`/opt/naoqi/bin/python2 -m compileall`), so a module the version does not load is still checked; both entries run it, closing [testing.md](testing.md)'s open question 2.
- **The headless viewer**: naoqi-viewer renders through EGL (`MUJOCO_GL=egl`, which it sets itself for a headless viewer on Linux, with the job's `libegl1` and `libgl1-mesa-dri`), and the live tier runs a headless viewer with the render camera and the placeholder variant, so the camera loop is tested on every push ([viewer.md](../host/viewer.md), "In the live tier and CI"). A viewer that fails to launch fails the entry. CI never accepts the meshes' license.

### The Windows live tier, by hand

A second workflow, `.github/workflows/e2e-windows.yml`, runs the live tier on Windows: naoqi-sim's host side on `windows-2025` against NAOqi in Docker Engine inside WSL 2 ([container.md](../container/container.md), "Linux containers on GitHub's Windows runner"). It is not Docker Desktop, which Windows users run, but the Windows host side against real containers, which nothing else tests: its first run found that `naoqi-sim run` ignored Ctrl-Break ([cli.md](../runtime/cli.md)).

- **Started by hand only** (`workflow_dispatch`; the Actions tab's "Run workflow", or `gh workflow run e2e-windows.yml`), never on a pull request or a push: about 20 minutes cold per version, and more moving parts (WSL, a systemd-managed Docker Engine, firewalls) than a pull request should wait on. Its own file, so that starting it runs it alone, not the whole of `ci.yml`. Worth starting before a release, and after a change to Windows-sensitive code (`cli.py`, `stack.py`, `docker_images.py`, `files.py`, `docker/compose.yaml`).
- **One runner per NAOqi version**, side by side (`fail-fast: false`): its `versions` input is `both` (the default), `2.1` or `2.8`.
- **Steps**: sync; Mesa's OpenGL next to the base `python.exe` (as naoqi-viewer's Windows fast tier) for the headless viewer; Ubuntu 24.04 under WSL 2 with `docker.io`; a Windows Firewall rule for 9562 and 9563 and WSL's Hyper-V firewall letting inbound traffic in, then a WSL restart; systemd's `dockerd` configured with a TCP socket (`"tls": false`) and `host-gateway-ip` at WSL's gateway, so the containers' `host.docker.internal` is Windows; Windows' Docker CLI at the WSL VM's address (`DOCKER_HOST`), with the buildx plugin; `naoqi-sim fetch-and-build-images <version>` from Windows; `uv run pytest tests-e2e -rs` with `NAOQI_SIM_E2E_VERSION`. Free disk is printed before and after the build.
- **No image cache** yet: each run fetches and builds, as on a user's machine. Measured cold ([run 38410829728](https://github.com/funwithagents/naoqi-sim/actions/runs/38410829728)): 17 minutes for 2.1 (54 passed, 6 skipped) and 19 for 2.8 (55 passed, 5 skipped); 2.8 leaves 21 GB in WSL's virtual disk, with 32 GB free on `C:` before the run.
- **Expected skips**: the audio loopback tests (no virtual sound device on Windows), the sim window (no display), and as on Linux the sound set and, on 2.1, the `languageTTS` test. Any other skip is a fault.
- Not a required check. The macOS live tier has no counterpart: GitHub's macOS runners give a Linux VM no nested virtualization to start in (as far as known, not probed) and have no OpenGL, so it runs on developers' Macs.

### Expected skips

The tests that skip by design on a runner; any other skip in a CI log is a fault.

| Job | Test | Why |
| --- | --- | --- |
| `e2e-sim` (2.8) | `test_naoqisim_live.py::test_the_sim_window` | The window does not depend on the NAOqi version: checked on the 2.1 entry |
| `e2e-sim` (2.1) | `test_speech_live.py`'s `languageTTS` test | `languageTTS` is a 2.8 signal |
| `e2e-sim` (both) | `test_audio_player_live.py`'s sound set test | Aldebaran's sound set (`soundsetaldebaran`) is a package the user supplies; CI has none |
| `fast-tier` (Linux, macOS) | `test_cli.py::test_ctrl_break_stops_the_robot_on_windows` | Ctrl-Break (`SIGBREAK`) exists on Windows only |

On macOS and Windows the 88 `container_code` tests are deselected, not skipped: the log counts them as deselected.

### Licensing

The runner downloads Aldebaran's suites and robot images from their public repositories and builds images from them, as a user does on their machine. The images go to the repository's private Actions cache only; nothing is pushed to a registry or attached to a release, and no workflow artifact contains a file of the image data or an image. This is the same practice as naoqi-viewer's CI, under the rule of [AGENTS.md](../../AGENTS.md): images built from the suite are never pushed.

### Secrets and protection

- **No secret is required**: every job is green with none.
- **The status checks to require on `main`** are `check`, the three `fast-tier` entries and both `e2e-sim` entries; requiring them is a repository setting on GitHub, outside the repo.

### Downstream repositories

naoqi-viewer pins a naoqi-sim commit for its own live job (`NAOQI_SIM_REF`) and bumps it on purpose. naoqi-sim's CI does not test it.

## Measured

On the first runs (PR #1, October 9, 2026):

| | Cold (build) | Cache hit |
| --- | --- | --- |
| `check` | 15 s | 12 s |
| `fast-tier` | 42 s | 43 s |
| `e2e-sim` 2.1 | 6 min 39 s (tests 2 min 16 s) | 5 min 11 s (tests 2 min 12 s) |
| `e2e-sim` 2.8 | 6 min 54 s (tests 1 min 33 s) | 3 min 49 s (tests 1 min 44 s) |

- **The cache.** The archives take 1.5 GB (2.1) and 2.9 GB (2.8), 4.5 GB of the 10 GB budget; an edit under `docker/` adds a new pair while the old one ages out. A hit loads the images and skips the build: the image IDs survive `docker save`/`docker load`, so `check_images` accepts them as verified.
- **Skips.** Only the expected one, on the 2.8 entry; the window test runs and passes under Xvfb on 2.1.

On the audio input's runs (PR #3, October 10, 2026), with the relay's build files and the audio loopback:

| | Cold (build) | Cache hit |
| --- | --- | --- |
| `check` | 16 s | 17 s |
| `fast-tier` | 70 s | 65 s |
| `e2e-sim` 2.1 | 9 min 0 s | 8 min 56 s (tests 4 min 27 s) |
| `e2e-sim` 2.8 | 13 min 13 s | 7 min 21 s |

- **The cold build** now also downloads the version's C++ SDK (334 MB, 1.3 GB), then compiles our C++ modules; the cache key covers them through `suite.py`'s hash.
- **The loopback** needed the silent low-latency client: without it, every device test failed on a 1.5 s to 1.7 s delay from playing to hearing.
- **One 2.8 boot** was not healthy in time on a runner, with the image that had booted there five times before; the re-run passed. If it recurs, look at the 2.8 boot's timing on a loaded runner.

With the tests per feature (the live tier is one tier, always run, [testing.md](testing.md)) and our modules loaded from NAOqi's autoload, on Oct 14, 2026:

| | Cold (build) | Cache hit |
| --- | --- | --- |
| `check` | 18 s | 17 s |
| `fast-tier` (Ubuntu, Windows, macOS) | 37 s, 50 s, 75 s | 37 s, 61 s, 72 s |
| `e2e-sim` 2.1 | 15 min 7 s | 9 min 49 s (tests 6 min 31 s: 94 passed, 5 skipped, 13 expected failures) |
| `e2e-sim` 2.8 | 14 min 13 s | 10 min 42 s (tests 5 min 48 s: 97 passed, 2 skipped, 13 expected failures) |

- **Against the day before** (Oct 13, cache hit), a live entry took 10 to 12 minutes without the tests per feature: the shorter 2.8 boot (about 18 s instead of 35 s) pays for most of them. Every entry stays well under its timeout.
- **Two timing tests** of the fast tier failed on the macOS runner, whose waits wake 20 to 50 ms late: the late wake-up test of the audio output and the slot count of the video input. Both now add `lateness()` to their bounds ([testing.md](testing.md), "Platforms").
- **One 2.8 live failure** (the robot heard a tone 0.68 s late, at the start of the session) did not recur on a re-run nor locally, where 2.8 hears 8 to 16 ms late from the moment it is ready. If it recurs, look at what the 2.8 boot still does on a runner once it is declared ready, about 10 s earlier than before.

## Open questions

None: the cache budget and the time budget were measured above. Revisit them if an edit under `docker/` becomes frequent enough for the eviction of the old archives to matter.
