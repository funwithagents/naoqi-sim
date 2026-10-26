---
code:
  - docker/naoqi/Dockerfile.naoqi-2.1
  - docker/naoqi/Dockerfile.naoqi-2.8
  - docker/compose.yaml
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/healthcheck.sh
  - docker/naoqi/Dockerfile.naoqi-2.1.dockerignore
  - docker/naoqi/Dockerfile.naoqi-2.8.dockerignore
  - src/naoqi_sim/suite.py
  - src/naoqi_sim/docker_images.py
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_relay.cpp
  - docker/naoqi/services/speech/naoqi_sim_speech_front.cpp
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_front.cpp
  - docker/naoqi/services/naoqi_sim_front_core.h
  - docker/naoqi/services/service-replacement/naoqi_sim_loader.cpp
tests:
  - tests/test_suite.py
  - tests/test_docker_images.py
  - tests-e2e/test_docker_images_live.py
  - tests-e2e/test_speech_live.py
  - tests/test_suite.py
  - tests/test_entrypoint.py
  - tests-e2e/test_packages_live.py
  - tests-e2e/test_status_live.py
  - tests-e2e/test_modules_live.py
---

# NAOqi container

**Status:** Implemented

## Purpose

The container gives the desktop `naoqi-bin` from the user's Choregraphe suite the old Linux it expects, on every platform, and exposes it on one port as a real robot would: `127.0.0.1:9559`. It is the only way naoqi-sim runs NAOqi (there is no native mode). How built-in services are replaced inside it is in [service-replacement.md](service-replacement.md); this spec covers the image, the network layout, boot and the entrypoint's configuration interface. How each image compares with a NAO of the same version, module by module and difference by difference, is in [naoqi-fidelity.md](naoqi-fidelity.md).

## Decided

### Image data and licensing

Each image is built from two Aldebaran files per version, kept in the image data folder's `<version>/` (`docker/image-data/` in a checkout, gitignored; the user data directory for an installed naoqi-sim; [api.md](../runtime/api.md), "Files on disk"): the Choregraphe suite and the robot's `animations` package. The image is built locally, tagged locally (`naoqi-sim/naoqi:<version>`) and never pushed: it contains Aldebaran's software.

| Version | Suite (from the repository's `Choregraphe/Linux/Binaries` or root) | Robot image the package comes from | `animations.pkg` |
| --- | --- | --- | --- |
| 2.1.4.13 (NAO V4/V5) | [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources), `choregraphe-suite-2.1.4.13-linux64.tar.gz` (431 MB), SHA-256 `bad0212956e2223f36736cff33bdc1e008311b8bf9efd81a52dcf05895c8abce` | Same repository, `NAOqi 2.1.4.13/NAOqi Images/opennao-atom-system-image-2.1.4.13_2015-08-27.opn` (377 MB), SHA-256 `5d18427ba6f5199d30cf29941b20ad5fa6a06b8f64a29126953cdfa33dbb9a24`; package at `/usr/share/naoqi/apps/animations.pkg` | version 5.0.9, SHA-256 `a1d46221f5f28b91c8e7564ade4532f390e5911f14210787b3352a84c2b507e1` |
| 2.8.7.4 (NAO V6) | [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries), branch `master`, `choregraphe-suite-2.8.7.4-linux64.tar.gz` (1.33 GB), SHA-256 `edf95da2ae8ec7573e3a590b6db47a472f9d2733280a4a597841fbf0c1e6c63c` | Same repository, `nao-x86-2.8.7.4_20210820_094013.opn` (732 MB), SHA-256 `d82e5dd221712555f20c430f3ebcbe46825d5179f1bc0e2594629489855e24a4`; package at `/opt/aldebaran/share/naoqi/apps/animations.pkg` | version 7.0.3, SHA-256 `8866ddf4bb45eab79068cfe5746c66f3b8f507356fd93affed204bc834002f2c` |

- All files are Git LFS: they are downloaded from `media.githubusercontent.com/media/aldebaran/<repo>/<branch>/<path>` (the raw URL returns a pointer). The pins (URL, file name, SHA-256, path inside the image) live in `src/naoqi_sim/suite.py`.
- Use the Binaries tarball, not the 2.1 `.run` setup: it is a static self-extractor that crashes under Rosetta (`bss_size overflow`).
- Neither suite has the `animations` package (the `animations/Stand/Gestures/*` behaviours that `ALAnimatedSpeech` runs): the robot image is its only public source. Both versions' packages are behaviours (`.xar`) and `.ogg` only, no native code, with the same 224 `Stand/Gestures` behaviours. The robot images have no sound set: that stays the user's to install (see "Package store").
- The download fetches Aldebaran's own public files to the user's machine, as the user would by hand; nothing is redistributed.

#### Build files: the C++ SDK

Our C++ NAOqi modules (the native relay, [service-replacement.md](service-replacement.md), "Binary arguments: the native relay", and the C++ fronts) are compiled in the image build against the version's own C++ SDK, kept in the same `<version>/` folder and fetched by the same step. It never reaches the final image: only the compiled modules do.

| Version | File | Source | SHA-256 | Used for |
| --- | --- | --- | --- | --- |
| 2.1 | `naoqi-sdk-2.1.4.13-linux64.tar.gz` (334 MB) | Aldebaran's public C++ SDK, `https://community-static.aldebaran.com/resources/2.1.4.13/sdk-c%2B%2B/` | `a1669524819088b7aac82e04450e2c5dce6ffdd11c968444db89b6831955683b` | The NAOqi module API (`alcommon`, `alvalue`, `alerror`), libqi (`qi`, `qitype`, `qimessaging`) and boost 1.55 headers: the same release as the suite |
| 2.8 | `naoqi-sdk-2.8.7.4-linux64.tar.gz` (1.3 GB) | Aldebaran's GitHub repository `aldebaran/nao6-doc-sdk` (Git LFS, `https://media.githubusercontent.com/media/aldebaran/nao6-doc-sdk/master/`) | `e42c8b95e6e3de349cf76100d006a9f5b48bd625f0236b0a0fe094fc29970967` | The NAOqi module API, libqi (`qi`, `ka`) and boost 1.64 headers: the same release as the suite |

- The pins live in `src/naoqi_sim/suite.py` with the others, and follow the same rules (kept when the hash matches, `.part` and hash check, `FetchError`). 2.8's SDK comes from GitHub like its suite and robot image (`aldebaran/nao6-binaries`); 2.1's from Aldebaran's download site, since no repository holds it (`aldebaran/NAO-V5-ressources` has the suite and image only).
- Each SDK is its suite's own release, so the header code compiled into our modules (the `ALProxy` and `qi::AnyObject` call templates) matches the suite's libraries. Until Oct 12, 2026 the 2.8 build used the 2.8.5.10 SDK's module API headers with libqi `qi-framework-v1.8.7` (our fork) and boost 1.64 first on the include path: it linked and the relay worked, but those libqi headers differ from 2.8.7.4's in 57 files, and typed calls from C++ to Python services sent "Invalid" values that crashed `naoqi-service` (measured Oct 12, 2026, building the speech front).
- Like the suite, the SDKs are Aldebaran's public files downloaded to the user's machine; nothing is redistributed, and an image that contains the relay is local, as every naoqi-sim image is.

#### Fetching the image data

The first step of `naoqi-sim fetch-and-build-images [2.1] [2.8] [--image-data DIR]` ([api.md](../runtime/api.md), "Images"; default: both versions into the image data folder, `docker/image-data/` in a checkout, see api.md's "Files on disk"), which then builds and verifies the images. `suite.fetch` (`src/naoqi_sim/suite.py`) makes `<image-data>/<version>/` hold the pinned suite and `animations.pkg`.

- A file already there with the pinned hash is kept, so re-running is cheap: nothing is downloaded, and a file whose size and modification time match its entry in `<image-data>/hashes.json` (written after each verification) is not even hashed again. A missing or unreadable record only means hashing again.
- A file there with another hash (a Git LFS pointer, a partial copy) is an error and is left untouched; the user deletes it to fetch again.
- Every download goes to `<file>.part`, is hashed while it streams and takes its final name only if the hash matches; otherwise it is deleted and the step fails with a `FetchError` (the command exits 1).
- `animations.pkg`, when missing, is extracted from the version's robot image:
  1. The image (`.opn`) is used from `<image-data>/<version>/` if the user put it there with the pinned hash, otherwise downloaded there and deleted after the extraction (a user's own copy is kept).
  2. Layout of a `.opn`: a 4096-byte `ALDIMAGE` header, an installer shell script whose variables give `MAGIC_SIZE`, `SIZE_BASE`, `INSTALLER_SIZE` and `IMAGE_CMP_SIZE`, then the compressed ext3 root filesystem at byte `MAGIC_SIZE + INSTALLER_SIZE × SIZE_BASE`, `IMAGE_CMP_SIZE × SIZE_BASE` bytes long (bzip2 on 2.1, gzip on 2.8, told apart by their magic bytes). The host decompresses it in Python.
  3. No host tool reads ext3 on macOS, and naoqi-sim needs Docker anyway: the decompressed filesystem is streamed into `docker run -i --rm alpine:3.20`, which installs `e2fsprogs-extra`, stores it in the container and writes the package to stdout with `debugfs -R "cat <path>"`. The container is removed with its copy; nothing is mounted, no root is needed on the host.
  4. The package goes through the same `.part`, hash check and rename.
- Output is progress lines on stderr.

### Robot packages in the image

- The Dockerfile copies `animations.pkg` from the `image-data` build context (`COPY --from=image-data`) to `/opt/naoqi/share/naoqi/apps/animations.pkg`. At boot, NAOqi's `PackageManager` installs every `.pkg` in that directory as a *system* package, as a robot does with its factory packages (the 2.8 suite installs its own `core`, `dialog`, `expressivity`, `life` and `semantic` this way). Measured on both versions: `Successfully installed system package` in the log, `PackageManager.hasPackage("animations")` and `ALBehaviorManager.isBehaviorInstalled("animations/Stand/Gestures/Hey_1")` are true once the entrypoint is ready.
- Copying the unzipped package into the package store does not work: `PackageManager` only knows the packages in its registry (`~/.local/share/PackageManager/pm.db`, SQLite, table `packages(uuid, path, installer)`).
- Once built, the image needs neither the suite nor the package. A rebuild (after changing the modules or the entrypoint) still needs both in the image data folder: Docker checks every file a `COPY` uses, even for a cached step. The same holds for the build files.

### The native build

Each Dockerfile has three stages, so the compiler and the headers never reach the image:

1. **`suite`**: the suite extracted to `/opt/naoqi`.
2. **`native`**, `FROM suite`: installs `g++` from the base's own Ubuntu (the suite's compiler generation), extracts the version's headers from the C++ SDK (`COPY --from=image-data`), and compiles every `services/*/*.cpp` of `docker/naoqi/` into `lib<name>.so`: today `naoqi_sim_audio_device_relay.cpp`, the native relay, `naoqi_sim_loader.cpp`, which loads our Python modules from the autoload ([service-replacement.md](service-replacement.md), "Replacing a built-in"), and the C++ fronts `naoqi_sim_speech_front.cpp` (`ALTextToSpeech`, [speech.md](../services/speech.md), "Architecture") and `naoqi_sim_audio_player_front.cpp` (`ALAudioPlayer`, [audio-player.md](../services/audio-player.md)), with `services/naoqi_sim_front_core.h` beside them; 2.8 compiles with `-DNAOQISIM_NAOQI_28`, which switches on the fronts' 2.8 parts. Each is linked against the suite's libraries in `/opt/naoqi/lib`, and `ldd -r` must report no undefined symbol.
3. The final stage, `FROM suite`: our files, the Python of `services/*/` copied flat to `/opt/naoqi/modules/`, and only the `.so` files from `native`, in `/opt/naoqi/lib/naoqi/` beside the suite's modules, where an autoload entry `foo` finds `libfoo.so`.

| | 2.1 | 2.8 |
| --- | --- | --- |
| Compiler | g++ 4.8 (Ubuntu 14.04); the suite was built with gcc 4.6.3, same C++ library ABI | g++ 5.4 (Ubuntu 16.04), as the suite |
| Flags | `-std=gnu++98` | `-std=gnu++14 -D_GLIBCXX_USE_CXX11_ABI=0` (the suite uses the old string ABI) |
| Include path | The SDK's `include/` | The SDK's `include/` |

- `ALCALL` (the module entry points' export macro) is defined by qibuild, not by the SDK's headers: the source defines it as default visibility when absent.
- Measured on Oct 10, 2026: both relays compile, load with `launchLocal` and deliver correct buffers; a 2.8 relay built against the 2.8.5 SDK's own libqi headers does not load on 2.8.7.4.

### Package store

`PackageManager` keeps installed packages under `/home/nao/.local/share/PackageManager` (the unzipped `apps/<uuid>/` plus `pm.db`). Packages the user installs (`PackageManager.install` over qi, or Choregraphe), such as the sound set, go there as on a robot.

- Each NAOqi compose service mounts a named volume there (`packages-2.1`, `packages-2.8`), so user-installed packages survive `docker compose down` and `up`, not only a stop and start. One volume per version: packages are version-specific.
- The image creates that directory owned by `nao`, so Docker initialises a new volume with that owner (an empty volume would otherwise be owned by root and `PackageManager` could not write).
- A package built with Python's `zipfile` must give each entry regular-file mode bits (`external_attr = (stat.S_IFREG | 0o644) << 16`, as `zip` on Linux writes): 2.8's `PackageManager` cannot read back an entry without them (`Invalid manifest`), which `ZipFile.writestr(name, data)` produces. 2.1 accepts both.
- `docker compose down -v` deletes the volumes: back to the image's factory packages, reinstalled at the next boot.
- The system packages (`animations`, and the 2.8 suite's own) are reinstalled from the image when missing from the store, so a volume created before an image change still gets them.

### Images

One image per version, `linux/amd64`, suite extracted to `/opt/naoqi`, override modules copied to `/opt/naoqi/modules/`, entrypoint at `/opt/naoqi/bin/naoqi-sim-entrypoint.sh`, healthcheck at `/opt/naoqi/bin/naoqi-sim-healthcheck.sh` ([status-service.md](status-service.md)).

- The build context is the image's own folder, `docker/naoqi/` (`naoqi_sim/docker/naoqi/` when installed); the speech engine's is `docker/tts-engine/`. The image data come from a second, named build context, `image-data`: compose sets it per service to `${NAOQI_SIM_IMAGE_DATA:-./image-data}/<version>`, so a build uploads only its own version's folder, and the Dockerfile copies from it with `COPY --from=image-data <file>`. Each Dockerfile keeps its own ignore file (`Dockerfile.naoqi-<version>.dockerignore`, read by BuildKit next to the Dockerfile), which leaves Python caches out of the context; the image data are in no build context but their own. BuildKit's named contexts need Docker Compose 2.17 or later.

| | 2.1 (`Dockerfile.naoqi-2.1`) | 2.8 (`Dockerfile.naoqi-2.8`) |
| --- | --- | --- |
| Base | Ubuntu 14.04 | Ubuntu 16.04 |
| Extra packages | `libglib2.0-0` | `libglib2.0-0 libsqlite3-0 libdbus-1-3 libpulse0` (without sqlite, `packagemanager` aborts) |
| Robot model | NAO by default | The suite defaults to Pepper (`JULIETTEY20B2C.xml`); `etc/naoqi/ALRobotModel.xml` is switched to `NAOH25V60.xml` ("Nao", 26 joints) |
| Boot to ready | about 5 s | about 15 s |

- `naoqi-bin` refuses to run as root: the image runs as user `nao` (uid 1000), which owns `/opt/naoqi`.
- Labels `io.naoqi-sim.version` and `io.naoqi-sim.recipes` on the NAOqi and `tts` images, set by compose (`build.labels`, from `NAOQI_SIM_VERSION` and `NAOQI_SIM_RECIPES`) so neither Dockerfile changes; `check_images` reads them to refuse an image built by another naoqi-sim version or from other recipes ([api.md](../runtime/api.md), "Images").
- Environment: `PATH`, `LD_LIBRARY_PATH=/opt/naoqi/lib`, `PYTHONPATH=/opt/naoqi/lib:/opt/naoqi/modules`, `NAOQI_SIM_NAOQI_VERSION` (the suite's full version) and `NAOQI_SIM_VERSION` (build argument, default `dev`; see [status-service.md](status-service.md)). The per-version boot facts are constants in each version's entrypoint (see "Entrypoint"), not environment variables.

### Network layout

Port 9559 is the only port, published on the host as `127.0.0.1:9559`.

- **2.1**: `naoqi-bin -b 0.0.0.0 -p 9559`. The broker is the public endpoint; every in-process service is served on it.
- **2.8**: `naoqi-bin` is only a launcher (ServiceDirectory, `ALServiceManager`, `PackageManager`). The services run in child processes (`naoqi-service`, one `qilaunch` per package service), each on its own random port, some on loopback only. The `core` package's `qi-secure-gateway` binds `0.0.0.0:9559` and relays every service, as on a real NAO 6. So `naoqi-bin` listens on `tcp://127.0.0.1:9558` (`--qi-listen-url`), leaving 9559 to the gateway; every service then advertises `tcp://<container>:9559` and `tcp://127.0.0.1:9559`.

### Compose

`docker/compose.yaml` has three services:

- `tts`: the speech engine ([tts-engine.md](tts-engine.md)), native architecture, with the named volume `piper-voices` at `/voices` for the voices of the languages its image lacks, and a healthcheck on its `/health` (healthy once every installed language's voice is loaded).
- `naoqi21` (2.1, profile `2.1`).
- `naoqi28` (2.8, profile `2.8`).

Each NAOqi service sits behind its version's profile, with symmetric names (`naoqi21`/`naoqi28`, containers `naoqi-sim-naoqi21`/`naoqi-sim-naoqi28`), so a version is always named: `docker compose --profile 2.1 up -d tts naoqi21`. A bare `docker compose up` starts only `tts`.

Both NAOqi services publish `127.0.0.1:9559`, so only one runs at a time, and each mounts its package store volume (`packages-2.1`, `packages-2.8`; see "Package store"). They reach the engine at `http://tts:8080` (`NAOQI_SIM_TTS_URL`) and the host through `host.docker.internal` (`host-gateway` on Linux): the host link at `NAOQI_SIM_HOST_LINK=host.docker.internal:9563` ([devices.md](../host/devices.md), "The host link"). `NAOQI_SIM_LANGUAGES` (the config's `speech.languages`, `English,French` when unset) goes to the `tts` service and the NAOqi one alike: the engine loads those voices, `ALTextToSpeech` lists them ([speech.md](../services/speech.md), "Language"). A NAOqi service depends on `tts` being started, not healthy: the two boot in parallel and `NaoqiSim.start()` waits for each ([api.md](../runtime/api.md), "Lifecycle"). `docker compose down` keeps the three volumes; `down -v` removes them, the voices included (the image's default voices remain).

### Entrypoint

One script per version, each reading top to bottom as that version's procedure: `entrypoint-2.1.sh` and `entrypoint-2.8.sh`, copied to `/opt/naoqi/bin/naoqi-sim-entrypoint.sh` in their image. What they share is in `entrypoint-lib.sh`, which both source (copied next to them): writing the autoload copy, starting `naoqi-bin`, waiting for a settled service list, checking the replacements, marking boot complete. Our modules load inside NAOqi's own boot, from the autoload copy ([service-replacement.md](service-replacement.md), "Replacing a built-in"): the entrypoint loads, exits and restarts nothing. The version's facts are constants at the top of its script, not image environment variables:

| | `entrypoint-2.1.sh` | `entrypoint-2.8.sh` |
| --- | --- | --- |
| `naoqi-bin` | `-b 0.0.0.0 -p 9559`: the broker is the public port | `--qi-listen-url tcp://127.0.0.1:9558`, behind the suite's gateway on 9559 |
| Reached from inside on | `tcp://127.0.0.1:9559` | `tcp://127.0.0.1:9558`, exported as `NAOQI_SIM_INTERNAL_PORT` for our qi services |
| `LEFT_OUT` (the replaced built-ins' autoload entries, commented out of the copy as `#replaced <entry>`) | `audioout` | `audioplayer ttsinterface` |
| `OURS` (our autoload entries, right after `pythonbridge`, in order) | `naoqi_sim_audio_device_relay naoqi_sim_loader naoqi_sim_speech_front naoqi_sim_audio_player_front` | Same |
| `MODULES` (our Python modules, which the loader loads in order; exported as `NAOQI_SIM_PYTHON_MODULES`, with `NAOQI_SIM_MODULES_DIR=/opt/naoqi/modules`) | `naoqi_sim_status_almodule naoqi_sim_speech_almodule naoqi_sim_audio_device_almodule naoqi_sim_audio_player_almodule` | `naoqi_sim_status_qiservice naoqi_sim_speech_qiservice naoqi_sim_audio_device_qiservice naoqi_sim_audio_player_qiservice` |
| `REPLACED` (the built-in names our fronts take) | `ALTextToSpeech ALAudioPlayer` | Same |
| `ADDED` (names no built-in holds, which our modules and the relay register) | `ALAudioDevice _NaoqiSimAudioRelay _NaoqiSimTextToSpeech _NaoqiSimAudioPlayer` | Same |
| Added built-ins (entries a NAO autoloads that the desktop suite ships but does not; see [naoqi-fidelity.md](naoqi-fidelity.md), "Matching a real NAOqi robot's modules"), written into the copy | `expressiveness` after `behaviormanager`; `basicawareness autonomousblinking autonomousmoves` after `alpanoramacompass`, so before `autonomouslife`, as on a NAO. `BUILTINS`, the names they register, are checked: `_ALExpressiveness ALBasicAwareness _ALAutonomousBlinking ALAutonomousMoves` | None |
| `LAST` (registered last at boot, waited for) | `ALDialog` (`dialog`, the last autoload entry) | `ALPanoramaCompass` (the last autoload entry) and the package services `ALAnimatedSpeech ALDialog ALAutonomousLife` |

The tunables below exist so the host-side tests can run the scripts against fake `naoqi-bin` and `qicli`; the images never set them: `NAOQI_SIM_READY_TRIES` (polls, one per second, before giving up on NAOqi; 120), `NAOQI_SIM_SETTLE_POLLS` (consecutive polls the service list must stay unchanged; 3), `NAOQI_SIM_POLL_INTERVAL` (seconds between polls; 1), `NAOQI_SIM_QICLI_TIMEOUT` (seconds a `qicli` call may take before it is killed; 5), `NAOQI_SIM_QICLI_HANGS` (consecutive timed-out polls that fail the boot; 3), `NAOQI_HOME`.

Sequence (both versions):

1. Write the autoload copy: the suite's `autoload.ini` with `LEFT_OUT` commented out, `OURS` after `pythonbridge` and, on 2.1, the added built-ins at their places. Export `NAOQI_SIM_PYTHON_MODULES` and `NAOQI_SIM_MODULES_DIR`, and start `naoqi-bin` with the copy.
2. Poll the service list (`qicli info`) until `ALLauncher`, `ALPythonBridge` and every `LAST` service are registered **and** the list has not changed for `NAOQI_SIM_SETTLE_POLLS` polls. If `naoqi-bin` exits, `NAOQI_SIM_READY_TRIES` polls fail, or three polls in a row time out (NAOqi stopped answering), exit 1; every 10 polls, log what is still awaited ([status-service.md](status-service.md), "Readiness"). On 2.8 the package services keep registering for a few seconds after the last autoload entry; the settling waits for them.
3. Check that every replaced, every added and (2.1) every added built-in name answers (up to 10 s each). `launchPythonModule` does not report an import failure and a library may register nothing, so a missing name is how a failed load shows. If one does not answer, exit 1.
4. Call `NaoqiSim.setReady` (exit 1 if it fails: the status module is missing), print `[entrypoint] naoqi-sim ready` and wait on `naoqi-bin`. `SIGTERM`/`SIGINT` are forwarded to it.

Every exit 1 terminates `naoqi-bin` first, so a failed boot shows as an exited container, never as a running one without its overrides. The healthcheck ([status-service.md](status-service.md)) reports `healthy` only after step 4.

### Platforms

| Platform | How it runs | Note |
| --- | --- | --- |
| Linux x86\_64 | Docker Engine | No emulation |
| macOS Intel | Docker Desktop | No libqi wheel, so naoqi-sim's host side does not install ([project.md](../project.md), "Platforms") |
| macOS Apple Silicon | Docker Desktop or OrbStack, amd64 emulation (Rosetta) | Measured on OrbStack: boot times above, no visible lag. The `tts` container is native |
| Windows | Docker Desktop (WSL 2) | The host side installs and its fast tier runs on Windows in CI ([ci.md](../testing/ci.md)); the stack itself has not been run there yet (open question 1) |

### Linux containers on GitHub's Windows runner (measured)

Whether CI could run the live tier on Windows, measured on GitHub's hosted `windows-2025` runner (Windows Server 2025, 4 vCPUs) in October 2026, with a throwaway workflow on a scratch branch:

- **The preinstalled Docker runs Windows containers only** (`OSType=windows`): a Linux image fails with `no matching manifest for linux/amd64`. Docker Desktop is not installed.
- **WSL 2 works.** The runner exposes virtualization (Hyper-V, Virtual Machine Platform and WSL enabled); `Vampire/setup-wsl` installs Ubuntu 24.04 as a WSL 2 distribution (kernel `6.18.33.2-microsoft-standard-WSL2`) in about a minute.
- **Docker Engine inside WSL 2 runs Linux containers** (`docker.io` from Ubuntu, `dockerd` started by hand; amd64 images, no emulation).
- **Windows reaches a container's published port** (`-p 8080:80`, then `127.0.0.1:8080` from Windows): WSL forwards localhost, as clients would reach NAOqi on 9559.
- **A container reaches a server on Windows only once the firewalls let it**, which naoqi-sim needs (the containers connect out to 9562 and 9563). With WSL's default NAT networking, both WSL and its containers reach Windows at WSL's default gateway (`ip route show default`, a `172.x.y.1` address), after a Windows Firewall rule for the port and WSL's Hyper-V firewall set to inbound `Allow` (`Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow`), then a WSL restart (`wsl --shutdown`): the Hyper-V firewall applies when the VM starts. Before that, ping goes through and TCP does not.
- **Mirrored networking is not available** on that runner: WSL answers `The specified request is unsupported` (`0x803b0015`) and falls back to no network.

**The live tier on Windows, measured once** (a one-off workflow on a scratch branch, never merged): naoqi-sim's host side on Windows against NAOqi 2.1 in Docker Engine inside WSL 2, in about 20 minutes cold. It took:

- **Docker Engine under systemd**, which Ubuntu's WSL distribution boots: `docker.io` starts a `dockerd` of its own, so it is configured (`/etc/docker/daemon.json`: `hosts` with a TCP socket, `"tls": false`, which Docker 27+ requires on a plain TCP socket, and `host-gateway-ip` at WSL's gateway, so the containers' `host.docker.internal` is Windows) with a unit override dropping its `-H fd://`, rather than doubled;
- **Windows' Docker CLI at the WSL VM's own address** (`DOCKER_HOST=tcp://<VM>:2375`): WSL's localhost relay did not carry `dockerd`'s socket, though it does carry a container published on `127.0.0.1` (NAOqi's 9559 is reached on `127.0.0.1` as on the other hosts), and the buildx plugin, which Compose builds with and Windows' CLI lacks;
- **the images built from Windows** (`naoqi-sim fetch-and-build-images 2.1`, through that CLI);
- **paths handed to WSL computed in PowerShell**, as `wsl.exe` passes its arguments to a Linux shell, which eats backslashes and `$`.

Result: **54 passed, 6 skipped** (the audio loopback, which has no virtual sound device on Windows; the sim window, no display; the sound set; a 2.8 signal). On the way it found a gap in naoqi-sim (`naoqi-sim run` did not stop on Ctrl-Break, the console signal another process can send on Windows, [cli.md](../runtime/cli.md)) and four faults in the live tests (SIGINT sent to a process, a Windows path in a TOML string, the venv's `Scripts\` folder, backslashes in a file list). It is not Docker Desktop, which is what users run: open question 1 stands for it.

## Open questions

1. **Docker Desktop.** Everything was measured on OrbStack and Linux's Docker Engine; Docker Desktop on macOS, Linux and Windows is still to confirm. GitHub's Windows runner has no Docker Desktop, but runs Linux containers in WSL 2, and the live tier passed there once against them ("Linux containers on GitHub's Windows runner", above); Docker Desktop itself is what users run, and is still to run.
2. **Starting the stack.** `naoqi-sim run` and `cleanup` ([cli.md](../runtime/cli.md)) are not built; today it is `docker compose` by hand (see [README.md](../../README.md)). `NaoqiSim.start()` waits on the container's health rather than on the log line ([api.md](../runtime/api.md)).
