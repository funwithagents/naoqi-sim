# Robot packages on the sims

**Status:** Done

Implements [container.md](../specs/container/container.md) ("Image data and licensing", "Fetching the image data", "Robot packages in the image", "Robot software in the image", "Network layout", "Compose", "Entrypoint") and [status-service.md](../specs/container/status-service.md) (`NaoqiSim/Loopback9559`, "Healthcheck"): both images give robot software the robot's `/usr/bin/python2`, `python` and PyYAML; on 2.8, `127.0.0.1:9559` inside the container is NAOqi as on a robot (a loopback redirect, with the `NET_ADMIN` capability), and the robot's own `altactilegesture` and `signs-and-feedback` packages are taken from the public robot image and installed at boot. It leaves Life's double-tap rule as the robot's configuration writes it ([autonomous-life.md](../specs/container/autonomous-life.md)), and 2.1's package services on Docker Desktop (container.md, open question 3).

## Scope

- `src/naoqi_sim/suite.py` — `Version.packages`: robot packages taken whole from the robot image under a plain name; 2.8 pins `altactilegesture.pkg` and `signs-and-feedback.pkg`
- `tests/test_suite.py` — the extra packages extracted, kept, re-extracted only when missing, refused on a wrong hash; the Dockerfile copies them
- `docker/naoqi/Dockerfile.naoqi-2.1`, `docker/naoqi/Dockerfile.naoqi-2.8` — `python-yaml` in the native stage and its `yaml` folder in the final one; `/usr/bin/python2` and `python` linked to the suite's interpreter, `zz-naoqi.conf` for the linker; 2.1's `naoqi.pth`; 2.8: `iptables`, `libcap2-bin`, the file capability, the lock file, `/data/home`, the two packages, `NAOQI_SIM_HEALTH_VIA=address`
- `docker/compose.yaml` — `cap_add: [NET_ADMIN]` on `naoqi28`
- `docker/naoqi/entrypoint-lib.sh`, `entrypoint-2.1.sh`, `entrypoint-2.8.sh` — the loopback step and `NAOQI_SIM_LOOPBACK_9559`
- `docker/naoqi/healthcheck.sh` — the container's own address on 2.8
- `docker/naoqi/services/status-service/naoqi_sim_status_core.py` — `NaoqiSim/Loopback9559`
- `tests/test_entrypoint.py` — a fake `iptables` and `hostname`; the rule added once, the boot going on when it fails, the variable naoqi-bin inherits, the healthcheck's address
- `tests/test_status_core.py` — the key
- `tests-e2e/packages/naoqi_sim_test_service/` — a package of ours whose service runs `/usr/bin/python2` and registers on `127.0.0.1:9559`
- `tests-e2e/test_robot_software_live.py` — that service on both versions (reached from the host on 2.8); 2.8's two robot services: gestures from taps, `triggerBit`, the `Speaking` feedback
- `tests-e2e/test_status_live.py` — the key on both versions
- `specs/container/container.md`, `specs/container/status-service.md`, `specs/_index.md`, this plan and `plans/_index.md` — statuses back to `Implemented` and `Done`

## Steps

1. `suite.py`: a `RobotPackage(path, sha256, name)` list on `Version`, extracted in `fetch` like `animations.pkg` (one download of the robot image for everything missing), then the tests.
2. The Dockerfiles, then `compose.yaml`.
3. The entrypoints and the healthcheck, then their host-side tests with fake `iptables` and `hostname`.
4. The status key and its test.
5. `uv run ruff check .`, `ruff format`, `pyright`, `pytest` (fast tier).
6. `naoqi-sim fetch-and-build-images 2.1 2.8` with the image data of the main checkout, then the live tests: the new file, the status, touch, Life, LEDs, speech recognition and boot ones, then the whole live tier on both versions, nothing else running.
7. Statuses: the two specs `Implemented`, this plan `Done`; the PR.

## Verification

- Fast tier: `tests/test_suite.py`, `tests/test_entrypoint.py`, `tests/test_status_core.py`, `tests/test_project_map.py`, then the whole tier.
- Live tier on both versions: `tests-e2e/test_robot_software_live.py`, `test_status_live.py`, then all of `tests-e2e`.
- CI (Linux, Docker Engine) runs the live tier: it confirms the capability and the redirect there.

## Results (Nov 28, 2026, OrbStack on macOS)

- Fast tier: 650 passed, 1 skipped; ruff and pyright clean.
- Images built and verified on both versions (the first 2.1 verification, run right after 2.8's, missed `_NaoqiSimAudioRelay` in its 10 s check; the same image booted alone and verified when run again: the known 2.1 boot flake under load).
- Live tier, both versions: 267 passed, 17 skipped, 14 xfailed; 2 failures of `test_install_live.py` came from the worktree without `docker/image-data` (8 passed on 2.1 once linked), and one 2.8 run lost its NAOqi connection while the controls switched Life off, failing the tests after it. Not reproduced since: the controls test 5 times alone, then after the 35 tests before it, then the whole 2.8 tier again with NAOqi's log followed: 142 passed, 6 skipped, 11 xfailed.
