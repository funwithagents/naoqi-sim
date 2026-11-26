# Video input: the render camera

**Status:** Done

Implements [video-input.md](../specs/host/video-input.md) for the `render` source ("Sources", "Frames: fixed rate, VGA, top camera, whoever subscribes", "In a running `NaoSim`"), the `video_input.fps` field of [config.md](../specs/runtime/config.md), the new start and stop order of [api.md](../specs/runtime/api.md) ("Lifecycle": simulated world before the host devices), and the headless viewer with the render camera in the live tier of [viewer.md](../specs/host/viewer.md) ("In the live tier and CI"). Left out: the `webcam` source (still refused at start with `DeviceNotBuiltError`), the bottom camera, and anything driven by `ALVideoDevice`'s subscribers.

## Scope

- `src/nao_sim/video_input.py` (new) — `VideoInput`: a qi client injecting VGA RGB frames into `CameraTop` at `fps` from a frame source, render and inject threads, `NaoSim/Camera/Source`
- `src/nao_sim/config.py` — `VideoInputSettings.fps` (int, 1 to 30, default 15)
- `src/nao_sim/viewer.py` — `SimWorld.camera_frame(camera, width, height)`, passing nao-viewer's `ViewerClosed` through as nao-sim's own signal
- `src/nao_sim/sim.py` — `render` no longer refused in step 1; step 5 the world, step 6 the video input; teardown order follows from the undo stack
- `tests/test_video_input.py` (new) — the device against a fake `ALVideoDevice`/`ALMemory` and a fake frame source
- `tests/test_config.py`, `tests/test_sim.py`, `tests/test_viewer.py` — `fps` validation; `render` starts the device after the viewer and stops it first; `webcam` still refused
- `tests-e2e/conftest.py` — `live_config` runs the headless viewer with the placeholder variant and `video_input.source = "render"`
- `tests-e2e/test_video_input_live.py` (new) — the camera loop on both versions
- `tests-e2e/scenes/camera-target.xml` (new) — the live tier's scene: a red pillar 1.5 m ahead, for a test that checks the camera sees what the head faces
- `examples/configs/ci.json` (new) — the live tier's config ([config.md](../specs/runtime/config.md), "Example files")
- `specs/host/video-input.md`, `specs/host/viewer.md`, `specs/runtime/config.md`, `specs/runtime/api.md`, `specs/testing/ci.md`, `specs/_index.md`, `specs/_overview.md`, `AGENTS.md` — frontmatter, "As measured", statuses, the project map row, wording that said "once built"

## Steps

1. **Measure the bottom camera first** (a measurement script, both versions): subscribe to `CameraBottom` on a fresh stack, with nothing ever injected into it, and record what `getImageRemote` returns (`None`, an error, a blank frame). Write the result into video-input.md's "As measured". If it raises in a way a NAO never does, stop and bring it back to the spec before going on (injecting one black frame at start is the fallback the discussion named).
2. **Config.** `VideoInputSettings.fps: int = 15`, parsed with `_as_int`, `ConfigError(key="fps")` outside 1..30. Tests: default, bounds (0, 1, 30, 31), a float or a string refused, the key path `video_input.fps` in the message.
3. **The device, `video_input.py`.**
   - `FrameSource` protocol: `frame() -> np.ndarray` (480×640×3 `uint8` RGB). `RenderSource(world)` calls `world.camera_frame("top", 640, 480)`.
   - `VideoInput(source, session_factory, fps, name)` with `start()`/`stop()`. `start()` opens a qi session (`stack.connect`, with its retry), gets `ALVideoDevice` and `ALMemory`, writes `NaoSim/Camera/Source` = `name` with `insertData`, then starts two daemon threads:
     - **render thread**: on a fixed schedule `t0 + k / fps`, calls `source.frame()` and stores it in a one-slot holder (newest wins), notifying the inject thread; a slot whose deadline already passed is skipped (`k` jumps to the next future slot), never caught up.
     - **inject thread**: waits for a new frame, calls `putImage(0, 640, 480, frame.tobytes())`. A `False` return or an exception is logged; a run of failures logs once at warning level until a success resets it.
   - The source raising `WorldClosed` (below) ends the device: log once at warning level that the camera has no frames any more, write `none`, stop both threads. Other source errors follow the failure-run rule above.
   - `stop()`: sets the stop event, joins both threads (timeout 5 s), writes `none` (best effort, logged at debug if NAOqi is gone), closes the session. Idempotent.
4. **Viewer.** `SimWorld.camera_frame(camera, width, height) -> np.ndarray` returns `NaoViewer.camera_frame(...).image`; nao-viewer's `ViewerClosed` is re-raised as `WorldClosed` (defined in `viewer.py`), so `video_input.py` never imports `nao_viewer`.
5. **`NaoSim`.**
   - `_check`: only `audio_input` sources and `video_input.source = "webcam"` raise `DeviceNotBuiltError`.
   - `start()`: after `wait_ready`, step 5 launches the world when the config needs one; step 6 starts `VideoInput(RenderSource(world), ...)` for `render`, appending `("video input", device.stop)` to the undo stack after the viewer's, so teardown stops it first.
   - Tests (fake viewer extended with `camera_frame`, `stack.connect` patched to a fake session): `render` with `headless = true` launches the viewer then the device, which injects frames; `stop()` stops the device before closing the viewer; a viewer that fails to launch never starts the device; `webcam` is still refused before anything starts.
6. **Fast tier for the device** (`tests/test_video_input.py`, fakes only):
   - injects 640×480 RGB bytes on camera 0, the bytes the source returned;
   - paces at `fps`: over 1 s at 10 fps, between 8 and 11 injections; a slow source (40 ms per frame at 30 fps) yields fewer frames, never a burst after it speeds up;
   - writes `NaoSim/Camera/Source` = `render` at start and `none` at stop;
   - a source raising `WorldClosed` stops injection, writes `none` and logs one warning;
   - `putImage` returning `False` repeatedly logs one warning, and injection resumes on success;
   - `stop()` returns within a second even while the source blocks, and twice is harmless.
7. **Live tier.**
   - `live_config` defaults to `viewer = {headless: true, variant: "placeholder"}`, `video_input = {source: "render"}`, and `examples/configs/ci.json` holds the same plus silent audio output. The sim-window test keeps its own config.
   - `tests-e2e/test_video_input_live.py`, both versions: `NaoSim/Camera/Source` reads `render`; a client subscribed to `CameraTop` at QVGA RGB 30 fps gets 320×240 frames that are not uniform and whose timestamps advance at about `fps` (15 ± 3 per second over 2 s); a BGR subscriber gets the same pixels with the channels swapped; the live tier's scene holds a red pillar 1.5 m ahead (`tests-e2e/scenes/camera-target.xml`), and for HeadYaw 0, ±0.25 and ±1.2 the pillar appears at the column the top camera's world pose predicts (±15 px at QVGA, a pinhole with NAO's 60.97° field of view) or not at all once out of view, so the test checks the render's geometry rather than "the image changed"; the bottom camera behaves as step 1 measured.
   - CI needs no workflow change: nao-viewer selects EGL itself for a headless viewer on Linux, and the `e2e-sim` job already installs `libegl1` and `libgl1-mesa-dri`. ci.md's "once built" wording becomes the present tense.
8. **Specs and map.**
   - `video-input.md`: frontmatter adds `src/nao_sim/video_input.py`, `tests/test_video_input.py`, `tests-e2e/test_video_input_live.py`; the bottom-camera measurement; status `Implemented`.
   - `viewer.md`: "As built" says the headless viewer runs with the render camera; status `Implemented`.
   - `config.md`, `api.md`: back to `Implemented`.
   - `AGENTS.md` project map: a `src/nao_sim/video_input.py` row (role: the video input device, render source, injection into `ALVideoDevice`; specs `video-input.md`, `devices.md`).
   - `_index.md` and `_overview.md`: statuses, the "Built and tested" line, the video input and simulated world rows.

## Verification

- `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (including `tests/test_project_map.py` for the new module and frontmatter).
- `uv run pytest tests-e2e` on 2.1 and 2.8, with the new camera test and every existing live test passing under the new `live_config` (the viewer is now in every live run).
- CI green on both matrix entries.
- Mark this plan `Done` here and in [_index.md](_index.md) only once all pass.
