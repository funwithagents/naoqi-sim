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

**Status:** Implemented

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
| `NaoqiSim/Perception/Stubs` | The API-only stubs loaded, comma-separated (`ALEngagementZones,ALGazeAnalysis,...`) | Nobody: the stubs module writes it at load ([perception-stubs.md](../services/perception-stubs.md)) |

- `none` means no host device is attached to that service, so it serves nothing (no frames, no audio), or, for the perception key, no engine behind the modules (they answer and find nobody). The device specs own the other values and may add keys under the same prefixes; the host writes them as an ordinary qi client, as the overview's "Host services" prescribes. The two perception keys are written inside the container by the modules themselves, as the entrypoint's environment says. `status()` reads `NaoqiSim/Perception/Source` as `perception_source` ([api.md](../runtime/api.md)). `NaoqiSim/Perception/Source` existed before Oct 9, 2026 as a host device's key and was dropped when perception was left to the clients; it is back with another meaning.

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

`docker/naoqi/healthcheck.sh` calls `NaoqiSim.isReady` with `qicli` on the **public** port, `tcp://127.0.0.1:9559`, and succeeds when the answer is `true`. The two suites' `qicli` differ: 2.1 prints `NaoqiSim.isReady: true`, 2.8 prints `true` followed by its `[W] qitype.signal` warnings on stdout; the script reads the first line and drops any `name: ` prefix. On 2.8 that goes through the suite's gateway, so a health of `healthy` also means the relay works; on 2.1 it is the broker itself.

Both Dockerfiles declare it: `HEALTHCHECK --interval=5s --timeout=5s --start-period=120s --retries=3`. The container is `starting` during boot (about 5 s on 2.1, 15 s on 2.8, plus module loading), `healthy` within one interval of the ready line, and `unhealthy` if NAOqi stops answering. `docker compose ps` and `docker inspect -f '{{.State.Health.Status}}'` show it; `NaoqiSim.start()` (behind `naoqi-sim run`) will wait on it rather than on the log line.

### Versions

- `NAOQI_SIM_VERSION` is a build argument of both Dockerfiles, kept as an environment variable in the image (default `dev`). `docker/compose.yaml` passes `${NAOQI_SIM_VERSION:-dev}`; `naoqi-sim fetch-and-build-images` passes the installed package version (the live tests build through it too). Baked at build rather than read at run time because it describes the override modules inside the image.
- `NAOQI_SIM_NAOQI_VERSION` is set by each Dockerfile next to the suite it extracts.

- There is no `NaoqiSim/Perception/Source`: perception runs in the clients, not in naoqi-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

## Open questions

1. **Boot timing.** `NaoqiSim` does not publish how long boot took (`NaoqiSim/BootSeconds`); the capability probe would record it. Add when the probe exists.
2. **A touch source.** Whether the touch input publishes `NaoqiSim/Touch/Source` ([touch-input.md](../host/touch-input.md), open question 2), which would extend this contract. (A device writes its source key back to `none` when it stops: [devices.md](../host/devices.md), "The device contract".)
3. **`setReady` is public.** Any client can call it. Acceptable on a simulator; a hidden `_setReady` would first need the `ALModule` autobind behaviour for underscore names measured on 2.1.
