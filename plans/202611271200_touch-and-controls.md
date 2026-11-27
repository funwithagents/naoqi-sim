# Touch input, controls page and 2.8's brightness statistics

**Status:** Done

Implements [touch-input.md](../specs/host/touch-input.md), [controls.md](../specs/host/controls.md) and [brightness-statistics.md](../specs/services/brightness-statistics.md): a test or a person touches the simulated robot (several sensors held at once, for a chosen time), covers its camera, and does the gesture that stops the focused activity on each version. Leaves out clicks in the sim window (naoqi-viewer's) and `ALTactileGesture` (deferred, touch-input.md open question 2).

## Scope

- `src/naoqi_sim/touch_input.py` — new: the sensors, `resolve`, `TouchInput` (pressed set by holder, value keys written over qi), `Touch` (`sim.touch`)
- `src/naoqi_sim/video_input.py` — the camera cover: `COVERED`, `cover()`, `covered()`, `fed`
- `src/naoqi_sim/controls.py`, `src/naoqi_sim/controls.html` — new: the server, its HTTP API and checks, the page, `stop_activity_gesture`
- `src/naoqi_sim/config.py` — `ControlsSettings`, the `controls` block
- `src/naoqi_sim/sim.py` — the touch input at step 6, the controls at step 7; `touch`, `cover_camera`, `uncover_camera`, `stop_activity_gesture`, `controls_url`
- `src/naoqi_sim/errors.py`, `src/naoqi_sim/__init__.py` — `CameraNotFedError`, `ControlsSettings` exported
- `src/naoqi_sim/cli.py` — `run` prints the controls' address
- `docker/naoqi/services/brightness-statistics/` — new: the core and the 2.8 qi service shell
- `docker/naoqi/entrypoint-2.8.sh` — the module loaded, its name waited for
- `examples/configs/controls.json` — new
- `tests/test_touch_input.py`, `tests/test_controls.py`, `tests/test_brightness_statistics_core.py` — new; `tests/test_video_input.py`, `tests/test_sim.py`, `tests/test_config.py`, `tests/test_cli.py`, `tests/test_entrypoint.py` — extended
- `tests-e2e/test_touch_live.py`, `tests-e2e/packages/naoqi_sim_test_activity/` — new: the live test and the activity it focuses; `tests-e2e/conftest.py`, `tests-e2e/support.py` — the live tier runs with the controls on
- Specs: the three above (Draft → Stable → Implemented), [api.md](../specs/runtime/api.md), [config.md](../specs/runtime/config.md), [cli.md](../specs/runtime/cli.md), [devices.md](../specs/host/devices.md), [video-input.md](../specs/host/video-input.md), [_overview.md](../specs/_overview.md); `AGENTS.md`'s map

## Steps

1. The touch input and `sim.touch`, always on after the other inputs; released at stop.
2. The camera cover in the video input; `sim.cover_camera`/`uncover_camera`.
3. `_ALBrightnessStatistics` on 2.8: the core (statistics of a QQVGA luminance picture at 10 Hz between `_start()` and `_stop()`, the unfed placeholder ignored) and its qi shell, loaded by the 2.8 entrypoint.
4. `stop_activity_gesture` per version; `sim.stop_activity_gesture()`.
5. The `controls` block, the server and its page; `controls_url`; `run` prints it.
6. The live test with an activity of its own, on both versions.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; then `uv run pytest tests-e2e/test_touch_live.py` on both versions (images rebuilt). Mark `Done` and the three specs `Implemented` once all pass.
