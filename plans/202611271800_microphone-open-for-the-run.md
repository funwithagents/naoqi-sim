# The microphone open for the whole run

**Status:** Done

Implements `specs/host/audio-input.md` ("The microphone"): with `audio_input.source = "mic"`, the microphone opens when the audio input starts and closes when it stops, as a NAO's are always on, instead of following the container side's need, which speech recognition turns on and off around each listening. Nothing else changes: the producer still runs only while audio is needed.

## Scope

- `src/naoqi_sim/audio_input.py` — the source opened in `AudioInput.start()` and closed in `stop()`; `AudioSource.skip()`, called when production resumes, drops what the microphone captured while nothing was read
- `tests/test_audio_input.py` — the microphone open from start to stop through listening turns; a resumed need gets live audio, not the backlog

## Steps

1. `AudioSource` gains `skip()`: `MicSource` clears its backlog, `FakeAudioSource` has none.
2. `AudioInput.start()` opens the source after publishing it; `stop()` closes it after the producer stopped; `_update()` no longer opens or closes it, and calls `skip()` when the producer starts.
3. The tests.

## Verification

Done Nov 27, 2026: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` (637 passed, 1 skipped); `tests/test_audio_input.py` 3 times serially.
