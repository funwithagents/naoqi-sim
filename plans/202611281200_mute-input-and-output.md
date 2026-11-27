# Mute the microphone and the loudspeakers

**Status:** Done

Implements the mutes in `specs/host/audio-input.md` ("Muting the microphone"), `specs/host/audio-output.md` ("Muting the loudspeakers"), `specs/host/controls.md` (the title line's two toggles, `/api/audio/*`) and `specs/runtime/api.md` (`mute_input`, `mute_output`): the user silences their microphone (the `mic` source: the device is closed, the robot hears silence) or their loudspeakers (the `play` mode: zeros to the device, the robot plays on), from Python, over HTTP or from two buttons at the right of the controls page's title line. No mute for the fake source or the other sinks, and nothing on the NAOqi side.

## Scope

- `src/naoqi_sim/audio_input.py` — `MicSource.mute(muted)` and `muted`: closes the input stream while muted, reopens it on unmute while the input runs; `read()` gives silence while closed
- `src/naoqi_sim/audio_output.py` — `DevicePlayer.muted`: `feed` writes zeros of the same length while set
- `src/naoqi_sim/sim.py` — `await mute_input(muted=True)`, `await mute_output(muted=True)`, `NaoqiSimError` when the source is not `mic` or the sink not a `DevicePlayer`; the output mute reset at start; the controls get the microphone and the player
- `src/naoqi_sim/controls.py` — `audio` in the state, `POST /api/audio/input` and `/api/audio/output`, 409 when not mutable
- `src/naoqi_sim/controls.html` — the two toggles at the right of the title line, shown only when mutable
- `tests/test_audio_input.py`, `tests/test_audio_output.py`, `tests/test_controls.py`, `tests/test_sim.py` — the tests below
- `docs/` — the controls page's description and the Python guide

## Steps

1. `MicSource`: a lock around the device; `open()` marks the source active and opens the stream unless muted; `close()` marks it inactive and closes the stream; `mute(m)` records `m` and, while active, closes or reopens the stream; the logs say muted or unmuted.
2. `DevicePlayer.muted`, a plain attribute; `feed` writes `bytes(len(chunk))` while it is set.
3. `NaoqiSim.mute_input` / `mute_output`, each run in a thread; the output's `muted` set back to `False` when the audio output starts.
4. `Controls(..., mic=None, player=None)`: `state()["audio"] = {"input": {"mutable", "muted"}, "output": {...}}`; the two requests, 400 for a missing or non-boolean `muted`, 409 when that side is not mutable.
5. The page: two buttons in the header, pushed right, hidden unless mutable, filled and labelled "muted" while muted, `aria-pressed`, a tooltip.
6. Docs and the specs' statuses.

## Verification

Fast tier: the microphone muted closes its stream and the producer sends zeros on time, unmuted reopens it, a mute before `start()` keeps it closed through `start()`; the player writes zeros of the right length while muted and the listeners still get the mix; the sim's two calls and their errors; the controls' state and requests, the 400 and 409, the page's two buttons. Then `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`.

Done Nov 27, 2026: ruff, pyright and the fast tier pass (725 passed, 1 skipped); the mute tests 3 times serially. Not run: the live tier (nothing on the NAOqi side changed) and the page in a browser.
