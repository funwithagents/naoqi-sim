---
code:
  - docker/naoqi/services/status-service/naoqi_sim_status_core.py
  - docker/naoqi/services/status-service/naoqi_sim_status_almodule.py
  - docker/naoqi/services/status-service/naoqi_sim_status_qiservice.py
  - docker/naoqi/healthcheck.sh
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/Dockerfile.naoqi-2.1
  - docker/naoqi/Dockerfile.naoqi-2.8
  - docker/compose.yaml
tests:
  - tests/test_status_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_status_live.py
---

# NaoqiSim status service and healthcheck

**Status:** Updated

## Purpose

The desktop `naoqi-bin` has no `ALSystem` and no version key in ALMemory ([naoqi-fidelity.md](naoqi-fidelity.md), "Desktop NAOqi facts"), so a client has no standard way to learn what it is talking to. The `NaoqiSim` service is naoqi-sim's identity: its existence says the target is naoqi-sim, it reports the naoqi-sim and NAOqi versions, publishes which host devices are attached (camera, microphone), and says whether boot is complete. The Docker healthcheck is built on it, and so will `naoqi-sim run` and `naoqi-sim status` be.

It is also a contract with its clients: naoqi-viewer's pose source identifies a target as `naoqi-sim` when the `NaoqiSim` service exists, and reads the NAOqi version it shows from `NaoqiSim/NaoqiVersion`, and any client can tell naoqi-sim from a NAO the same way. The service name and these keys do not change without a coordinated release.

## Decided

### The service

The service is called `NaoqiSim`. It exists only on naoqi-sim: no real robot or plain desktop NAOqi has it. Its name is free on both versions, so it is registered directly (no built-in to remove), as the first entry of each entrypoint's `MODULES` ([container.md](container.md), "Entrypoint").

| Method | Returns | Meaning |
| --- | --- | --- |
| `getVersion()` | string | The naoqi-sim version the image was built with (`NAOQI_SIM_VERSION`, see "Versions") |
| `getNaoqiVersion()` | string | The suite's full NAOqi version: `2.1.4.13` or `2.8.7.4` |
| `isReady()` | bool | `true` once the entrypoint has finished its sequence (see "Readiness") |
| `setReady()` | — | Marks boot complete. Called by the entrypoint as the last step; publishes `NaoqiSim/Ready` |

- Method names stay clear of the `ALModule` generics (`version`, `ping`, `exit`, `stop`...), since on 2.1 the service is an `ALModule`.
- Object model per version as in [service-replacement.md](service-replacement.md): `naoqi_sim_status_almodule` (2.1, `naoqi.ALModule` on the broker) and `naoqi_sim_status_qiservice` (2.8, `qi.Session` service relayed by the gateway). Both are thin shells over `naoqi_sim_status_core`, Python 2.7 code kept importable under Python 3 so the fast tier tests it on the host.
- `naoqi-bin --version` prints only the two-component version (`2.1`, `2.8`), so the full version comes from the Dockerfile (`NAOQI_SIM_NAOQI_VERSION`).

### ALMemory keys

The module writes these at load. All values are plain strings except `NaoqiSim/Ready`.

| Key | Value at boot | Who changes it later |
| --- | --- | --- |
| `NaoqiSim/Version` | naoqi-sim version | Nobody |
| `NaoqiSim/NaoqiVersion` | `2.1.4.13` or `2.8.7.4` | Nobody |
| `NaoqiSim/Ready` | `0`; `1` after `setReady()`. Raised as an event, so a client can wait on it | The entrypoint, through `setReady()` |
| `NaoqiSim/Camera/Top/Source`, `NaoqiSim/Camera/Bottom/Source` | `none` | The video input: what feeds each head camera (`render`, `webcam`), [video-input.md](../host/video-input.md) |
| `NaoqiSim/Camera/Source` | `none` | The video input: the two cameras' keys summarized, for `status()` and a client that only wants to know whether the robot sees: `none` when no camera is fed, the one source feeding them, `mixed` when they differ |
| `NaoqiSim/Audio/Source` | `none` | The audio input (`fake`, `mic`), [audio-input.md](../host/audio-input.md) |
| `NaoqiSim/Audio/Channels` | `none` | The audio input's mono policy (`duplicate`, `silence`), [audio-input.md](../host/audio-input.md) |
| `NaoqiSim/Perception/Source` | `engine` when `NAOQI_SIM_PERCEPTION_URL` names the perception engine, `none` when it is empty (`perception.enabled = false`) | Nobody: the face module writes it at load ([face-detection.md](../services/face-detection.md), [perception-engine.md](perception-engine.md)) |
| `NaoqiSim/SpeechRecognition/Source` | `none`; `engine` once `ALSpeechRecognition` loads with `NAOQI_SIM_ASR_URL` set | Nobody: the speech recognition module writes it at load ([speech-recognition.md](../services/speech-recognition.md)) |
| `NaoqiSim/Perception/Stubs` | The API-only stubs loaded, comma-separated (`ALGazeAnalysis,ALSittingPeopleDetection,...`) | Nobody: the stubs module writes it at load ([perception-stubs.md](../services/perception-stubs.md)) |
| `NaoqiSim/Loopback9559` | What a robot package inside the container reaches on `127.0.0.1:9559`, from the entrypoint (`NAOQI_SIM_LOOPBACK_9559`): `naoqi` as on a robot (2.1's broker; 2.8's NAOqi through the loopback redirect), `gateway` on a 2.8 host that refused the redirect, so the services robot packages register stay out of the host's reach ([container.md](container.md), "Network layout"); `unknown` without the variable | Nobody |
| `NaoqiSim/Life/LaunchpadPeople` | The `Launchpad/` keys naoqi-sim writes in the robot's plugins' place, comma-separated (`Launchpad/NumPeopleZone1,...`) | Nobody: the launchpad people module writes it at load ([launchpad-people.md](../services/launchpad-people.md)) |

- `none` means no host device is attached to that service, so it serves nothing (no frames, no audio), or, for the perception key, no engine behind the modules (they answer and find nobody). The device specs own the other values and may add keys under the same prefixes; the host writes them as an ordinary qi client, as the overview's "Host services" prescribes. The two perception keys are written inside the container by the modules themselves, as the entrypoint's environment says. `status()` reads `NaoqiSim/Perception/Source` as `perception_source` and `NaoqiSim/SpeechRecognition/Source` as `speech_recognition_source` ([api.md](../runtime/api.md)). `NaoqiSim/Perception/Source` existed before Oct 9, 2026 as a host device's key and was dropped when perception was left to the clients; it is back with another meaning.

### The robot's keys

A robot's NAOqi publishes what the robot is under `RobotConfig/` (`RobotConfig/Body/Type` is `Nao` and `RobotConfig/Body/Version` `5.0.0` on a NAO V5, as read on one); the desktop NAOqi loads the same model file and publishes none of it. The status module publishes them in its place, at load, right after its own keys: every key the model file the entrypoint chose lists, with the file's value, as a string ([container.md](container.md), "The robot model"; the file's path comes in `NAOQI_SIM_ROBOT_MODEL_FILE`).

| Key | NAO V4 | NAO V5 | NAO V6 |
| --- | --- | --- | --- |
| `RobotConfig/Body/Type`, `RobotConfig/Head/Type` | `Nao` | `Nao` | `Nao` |
| `RobotConfig/Body/Version`, `RobotConfig/Head/Version` | `4.0.0` | `5.0.0` | `6.0.0` |
| `RobotConfig/Body/BaseVersion`, `RobotConfig/Head/BaseVersion` (deprecated, the files say) | `V4.0` | `V5.0` | Not in the file |

- These are the robot's own names, not `NaoqiSim/` ones: a client reads which robot it is on the same way on a NAO and on naoqi-sim, and `NaoqiSim/` stays for what only a simulator has. Nothing under `NaoqiSim/` repeats them.
- **Everything the file lists**, not a chosen few: the hardware versions (`RobotConfig/Body/Device/Hand/Left/Version`, `.../Legs/Version`, `RobotConfig/Head/Device/Camera/Version`...), `RobotConfig/Body/SoftwareRequirement` and, on a V4 or V5, the file's placeholder identity: `RobotConfig/Head/HeadId` `0000`, `Device/DeviceList/ChestBoard/BodyId` `00000ALDR1008E000000` and `Device/DeviceList/ChestBoard/BodyNickName` `Nao0000` (the Get Body ID box reads the body id). The V6 file has no identity and no `BaseVersion`.
- A commented-out entry is not published. Without the variable or the file (the module run outside the entrypoint), no robot key is published and the module loads all the same.
- Written once, after NAOqi's own modules have loaded their model: whether any of them reacts to a key appearing is to confirm on the running sims (open question 4).

### Readiness

"Ready" means the whole entrypoint sequence ([container.md](container.md), "Entrypoint") completed: NAOqi booted from the autoload copy with our modules in place of the built-ins, its service list settled with every needed service present, and **every replaced and every added name answers**. Only then does the entrypoint call `NaoqiSim.setReady` and print `[entrypoint] naoqi-sim ready`.

The entrypoint exits non-zero (after terminating `naoqi-bin`) instead of carrying on when:

- NAOqi does not answer after `NAOQI_SIM_READY_TRIES` polls (default 120, one per second);
- NAOqi stops answering: three polls in a row whose `qicli info` takes longer than 5 s. Every `qicli` call the entrypoint makes is killed after 5 s, so a call that hangs fails the boot in seconds, with its reason in the log, instead of freezing it silently until Docker calls the container unhealthy minutes later (seen once on CI, a 2.8 restart whose log stopped after its last service registered);
- a replaced name (`REPLACED`) does not answer within 10 s of loading the modules (a replacement that failed at import, which `launchPythonModule` does not report);
- `NaoqiSim.setReady` fails (the status module itself did not load).

While it waits, the entrypoint says so every 10 polls (`still waiting for: <services>`, or `the service list is still changing`), and logs each timed-out poll, so the tail of a failed boot's log, which a `BootError` carries, names what it was waiting for.

So a container that is `running` and printed the ready line has its overrides in place, and one whose boot failed shows as `exited`, not as a half-robot. This replaces the earlier behaviour where both failure modes were silent (the former open questions of [container.md](container.md) and [service-replacement.md](service-replacement.md)).

### Healthcheck

`docker/naoqi/healthcheck.sh` calls `NaoqiSim.isReady` with `qicli` on the **public** port and succeeds when the answer is `true`. On 2.1 that is `tcp://127.0.0.1:9559`. On 2.8 it is the container's own address (`hostname -I`, its first), port 9559: the image sets `NAOQI_SIM_HEALTH_VIA=address`, because the loopback redirect sends `127.0.0.1:9559` to NAOqi itself, past the gateway a host client goes through ([container.md](container.md), "Network layout"); `127.0.0.1` when the container has no address. The two suites' `qicli` differ: 2.1 prints `NaoqiSim.isReady: true`, 2.8 prints `true` followed by its `[W] qitype.signal` warnings on stdout; the script reads the first line and drops any `name: ` prefix. On 2.8 that goes through the suite's gateway, so a health of `healthy` also means the relay works; on 2.1 it is the broker itself.

Both Dockerfiles declare it: `HEALTHCHECK --interval=5s --timeout=5s --start-period=120s --retries=3`. The container is `starting` during boot (about 5 s on 2.1, 15 s on 2.8, plus module loading), `healthy` within one interval of the ready line, and `unhealthy` if NAOqi stops answering. `docker compose ps` and `docker inspect -f '{{.State.Health.Status}}'` show it; `NaoqiSim.start()` (behind `naoqi-sim run`) will wait on it rather than on the log line.

### Versions

- `NAOQI_SIM_VERSION` is a build argument of both Dockerfiles, kept as an environment variable in the image (default `dev`). `docker/compose.yaml` passes `${NAOQI_SIM_VERSION:-dev}`; `naoqi-sim fetch-and-build-images` passes the installed package version (the live tests build through it too). Baked at build rather than read at run time because it describes the override modules inside the image.
- `NAOQI_SIM_NAOQI_VERSION` is set by each Dockerfile next to the suite it extracts.

- There is no `NaoqiSim/Perception/Source`: perception runs in the clients, not in naoqi-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

## Open questions

1. **Boot timing.** `NaoqiSim` does not publish how long boot took (`NaoqiSim/BootSeconds`); the capability probe would record it. Add when the probe exists.
2. **A touch source.** Whether the touch input publishes `NaoqiSim/Touch/Source` ([touch-input.md](../host/touch-input.md), open question 2), which would extend this contract. (A device writes its source key back to `none` when it stops: [devices.md](../host/devices.md), "The device contract".)
3. **`setReady` is public.** Any client can call it. Acceptable on a simulator; a hidden `_setReady` would first need the `ALModule` autobind behaviour for underscore names measured on 2.1.
4. **The robot's keys on a running NAOqi.** That publishing them disturbs none of NAOqi's modules (the hardware versions are the candidates), on both versions; if one does, publish the identity keys only (`Type`, `Version`, `BaseVersion`).
