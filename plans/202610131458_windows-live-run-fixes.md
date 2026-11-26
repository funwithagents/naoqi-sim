# Windows: what a live run against real containers found

**Status:** Done

Implements [cli.md](../specs/runtime/cli.md) ("How `run` hears Ctrl-C": Ctrl-Break on Windows), [audio-output.md](../specs/host/audio-output.md) (one end per tick) and [audio-device.md](../specs/services/audio-device.md) (2.8's subscribe waits 10 s) and records in [container.md](../specs/container/container.md) what running the live tier on GitHub's Windows runner showed. A one-off workflow on a scratch branch ran naoqi-sim's host side on Windows against NAOqi 2.1 in Docker Engine inside WSL 2 (not Docker Desktop); it is not part of CI.

## Scope

- `src/naoqi_sim/cli.py`: on loops without signal handlers (Windows), `run` also stops on `SIGBREAK` (Ctrl-Break)
- `tests/test_cli.py`: Ctrl-Break stops `run` (Windows only)
- `tests-e2e/test_naoqisim_live.py`: the end-to-end `run` test sends Ctrl-Break to a process group of its own on Windows, SIGINT elsewhere
- `tests-e2e/test_install_live.py`: the scratch project's path written with forward slashes (TOML reads backslashes as escapes); its venv's `Scripts\\` folder on Windows; Ctrl-Break to stop its `run`; its bundled files listed with forward slashes
- `.github/workflows/e2e-windows.yml`: the Windows live tier as a workflow of its own, started by hand, a runner per NAOqi version (validated in the pull request through a temporary `push` trigger, removed before merging)
- `src/naoqi_sim/audio_output.py`: each tick's end computed once, for `playing_until` and a stream ending in it (a play returned 4 ms before `playing_until` on the macOS runner)
- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_qiservice.py`: 2.8's subscribe waits up to 10 s for a client's name (3 s fell short once on a loaded runner)
- `specs/host/audio-output.md`, `specs/services/audio-device.md`, `specs/runtime/cli.md`, `specs/testing/ci.md` (the Windows-only test's expected skip), `specs/container/container.md`, `specs/_overview.md`, `specs/_index.md`, this plan, `plans/_index.md`

## Steps

1. The one-off workflow (kept local, not committed): WSL 2 with Docker Engine under systemd, configured with a TCP socket and `host-gateway-ip` at Windows; firewalls opened for 9562 and 9563; Windows' Docker CLI with buildx; Mesa for the headless viewer; `naoqi-sim fetch-and-build-images 2.1` from Windows; the live tier on Windows.
2. Its first complete run: 48 passed, 6 skipped, 1 failed, 5 errors: a Windows path in a TOML string, SIGINT sent to `naoqi-sim run` (which did not stop on Ctrl-Break).
3. The fixes, then the run again: 49 passed (the install test's venv was `Scripts\\` and it too sent SIGINT), 53 (its file list in backslashes), then **54 passed, 6 skipped** ([run 38405623737](https://github.com/funwithagents/naoqi-sim/actions/runs/38405623737)).
4. Two faults the pull request's CI found, unrelated to Windows: a play returning before `playing_until` when its last tick was fed late (macOS runner), and 2.8's 3 s wait for a client's name falling short (live 2.8).
5. `e2e-windows.yml`, manual-only, both versions by default, and its section in ci.md.
6. Statuses, once `e2e-windows.yml` and the regular CI are green: this plan `Done`; cli.md, audio-output.md, audio-device.md and ci.md `Implemented`; the temporary trigger removed.

## Verification

- Locally on macOS: lint, format, types, the fast tier (290 passed, the Windows-only test skipped).
- `e2e-windows.yml` green on both versions ([run 38410829728](https://github.com/funwithagents/naoqi-sim/actions/runs/38410829728): 2.1 54 passed, 2.8 55 passed, the expected skips), through its temporary trigger, then removed.
- The pull request's CI green ([run 38410822398](https://github.com/funwithagents/naoqi-sim/actions/runs/38410822398)): fast tier Linux 290 and macOS 202 (the Ctrl-Break test skipped), Windows 203; live 2.1 and 2.8 58 passed each.
