# Child voice: the English and French voices pitched up by resampling

**Status:** Done

Implements the settled behavior in [tts-engine.md](../specs/container/tts-engine.md) ("Rendering", pitch; "Voices", the pitch column) and [speech.md](../specs/services/speech.md) (`pitchShift`). It delivers a per-voice pitch factor, 1.15 for English and French and nothing for the other languages, applied by synthesizing slower and resampling faster so the speech keeps its length, and the say's `pitch` (NAOqi's `pitchShift`, `\vct`) multiplying it within 0.5 to 4. It leaves out a vocoder (formants apart from the pitch, a NAO's `doubleVoice`), rendered and listened to but not chosen, and any change to the other languages' voices.

## Scope

- `docker/tts-engine/server.py` — `PITCH`, `PITCH_RANGE`, `pitch_factor`, `shift`; `synth_piper` takes the pitch, slows the synthesis and shifts the audio; `render` passes the say's `pitch`.
- `tests/test_tts_engine.py` — the factors per language and with a say's pitch, the range; `shift` plays a tone faster by the factor (its length divided, its frequency multiplied); the pitch reaches the synthesis and the marks are measured on the shifted audio.
- `README.md` — one clause.

## Steps

1. The factor and the shift in the engine, the say's `pitch` wired to it.
2. The tests; the specs' pitch paragraphs and the table column.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; the live speech tier on one version to hear it (`uv run naoqi-sim fetch-and-build-images 2.1`, `uv run pytest tests-e2e/test_speech_live.py`), its durations unchanged by the shift.
