---
code:
  - docker/tts-engine/server.py
  - docker/tts-engine/Dockerfile
  - docker/compose.yaml
tests:
  - tests/test_tts_engine.py
  - tests-e2e/test_speech_live.py
---

# TTS engine container

**Status:** Implemented

## Purpose

A small speech engine container that turns a list of text, marker and pause items into audio, in any of the languages a config installs. It streams the PCM to the host audio output ([audio-output.md](../host/audio-output.md)) and replies with the exact timings. It knows nothing about NAOqi: tags, events and `say()` semantics stay in the `ALTextToSpeech` replacement ([speech.md](../services/speech.md)).

It is its own container because:
- the NAOqi images (glibc 2.19 on 2.1, Python 2.7, amd64 emulation on Apple Silicon) rule out every current engine;
- keeping the engine off the host keeps `pip install` light and isolates the engine's models and dependencies.

## Decided

### Engine: Piper, only

- Piper (`piper-tts`, onnxruntime), pinned. No eSpeak NG path any more (dropped Oct 26, 2026: it was never justified, and its one feature a NAO has, pitch, is not worth a second code path); eSpeak NG is still inside Piper, as its phonemizer. No torch, no cloud.
- **Licensing.** `piper-tts` is GPL-3.0-or-later (it embeds eSpeak NG, GPL-3.0); naoqi-sim is MIT. The engine's container is a GPL-governed combination built on the user's machine and never pushed, and naoqi-sim distributes the recipe, not the image, so the project's own licence is unaffected ([_overview.md](../_overview.md), "Licensing"). The voices are governed by their own terms (below).

### Languages

NAOqi names a language by an English word (`English`, `French`, `Brazilian`, ...; [speech.md](../services/speech.md), "Language"), and a NAO has one or two language packs installed. The engine mirrors that:

- **One voice per language**, the table below. The engine's table (`server.py`, `VOICES`) is the one place that maps a NAOqi language name to a Piper voice; the config's `SPEECH_LANGUAGES` repeats its keys so a config is checked at load, and the fast tier checks the two lists agree.
- **The installed languages** come from `NAOQI_SIM_LANGUAGES` (comma-separated NAOqi names, the config's `speech.languages`, which `NaoqiSim.start()` passes through compose to this container and to the NAOqi one; [config.md](../runtime/config.md)). A name without a voice ends the server with the message on its output (the config refuses it first, so this catches a stack started by hand). The default is `English,French`.
- **Voices on two roots.** The image bakes the default languages' voices (`DEFAULT_LANGUAGES`, the same two the config defaults to; the fast tier checks the Dockerfile fetches exactly those) under `/voices-builtin/<release>/`, so a default config speaks with no download at run time. The compose `tts` service also mounts the named volume `piper-voices` at `/voices`: the voice of any other installed language is downloaded there, under `/voices/<release>/`, the first time it is needed (about 60 MB, a few seconds), from the pinned `rhasspy/piper-voices` release (`VOICES_TAG`, the Dockerfile's `VOICES_TAG`, the same release for both roots; a release bump ships new defaults with the image and ignores the volume's old-release files). The engine looks a voice up in the image first, then in the volume, and never copies the baked voices into the volume. A download goes through a temporary name and a rename, so a container killed mid-download leaves no half file under the final one; a voice path is percent-encoded (`pt_PT-tugão-medium` is not ASCII). One volume, not one per NAOqi version: voices do not depend on NAOqi. `docker compose down -v` empties it; the image's defaults still speak.
- **Readiness.** At start the server answers `/health` at once, 503, then loads every installed language's voice, fetching the missing ones, and answers 200 once all are loaded (about 0.5 s per voice to load; the first `say` does not pay for it). The compose service has a Docker healthcheck on `/health` (every 2 s, a start period of 10 minutes for the downloads, so a slow fetch is `starting`, never `unhealthy`), and `NaoqiSim.start()` waits for it after NAOqi's own ([api.md](../runtime/api.md), "Lifecycle"): the two containers boot in parallel, so a fetch is usually hidden by NAOqi's boot. A voice that cannot be loaded (no network for a download, a bad release) ends the server with the voice named on its output: the container exits, and the start fails with the end of its log.
- **An unknown language in `/say`** is a 400; the NAOqi side refuses it before calling, so this only catches a bug.

### Voices

One voice per language from `rhasspy/piper-voices` v1.0.0, medium quality, single speaker, chosen by ear (Oct 26, 2026) among those whose own dataset is permissive. **The engine never ships a voice**: the user's machine downloads it at the image build or on the language's first use, and the naoqi-sim repository and wheel hold only the table.

**Licensing posture (settled Oct 26, 2026).** A Piper voice carries no licence of its own: its model card states the licence of the dataset it was trained on, and a training note names the base model it was fine-tuned from. Nearly every medium voice is fine-tuned from `en_US-lessac`, whose dataset (Blizzard 2013) is research-only. Whether fine-tuned weights inherit that restriction is unsettled; the Piper project imposes no licence on its voices and leaves the judgement to the user. naoqi-sim's rule: **the voice's own dataset licence decides, the lineage is recorded**, and a voice whose own dataset is non-commercial, unknown or copyleft is never offered. "A" below is trained from scratch on permissive data; "B" is fine-tuned from lessac on a permissive dataset. A user who needs the strict set can take the "A" voices from this table (English and Swedish as they are; French, German and Dutch have from-scratch `mls` voices, multi-speaker and rougher, not chosen).

| NAOqi name | Voice | Dataset licence | Tier |
|---|---|---|---|
| English | `en_US-ljspeech-medium` | public domain (LJ Speech) | A |
| French | `fr_FR-siwis-medium` | CC BY 4.0 | B |
| German | `de_DE-thorsten-medium` | CC0 | B |
| Dutch | `nl_NL-pim-medium` | CC0 | B |
| Swedish | `sv_SE-nst-medium` | CC0 | A |
| Spanish | `es_ES-davefx-medium` | CC0 | B |
| Brazilian | `pt_BR-faber-medium` | CC0 | B |
| Czech | `cs_CZ-jirka-medium` | CC0 | B |
| Danish | `da_DK-talesyntese-medium` | CC0 | B |
| Finnish | `fi_FI-harri-medium` | CC0 | B |
| Italian | `it_IT-paola-medium` | CC0 | B |
| Norwegian | `no_NO-talesyntese-medium` | CC0 | B |
| Polish | `pl_PL-gosia-medium` | CC0 | B |
| Portuguese | `pt_PT-tugão-medium` | CC0 | B |
| Russian | `ru_RU-dmitri-medium` | CC0 | B |
| Turkish | `tr_TR-fahrettin-medium` | CC0 | B |

Of NAOqi's 21 languages, five are not offered: Arabic and Chinese (their Piper voices' datasets have no usable licence), Greek (only a low-quality voice, on a non-commercial base), Japanese and Korean (no Piper voice). CC BY 4.0 asks for attribution: the French voice's dataset (SIWIS) is credited in the README.

### HTTP API (port 8080, standard-library `ThreadingHTTPServer`)

- `POST /say` with `{"id": <say id> (optional), "language": "English", "rate": 100, "pitch": 100, "items": [...]}`. Items:
  - `{"type": "text", "text": "..."}`
  - `{"type": "mark", "id": N}`
  - `{"type": "pause", "ms": N}`

  The reply is `{"duration": s, "marks": {"N": offset_s}, "rate": sample_rate, "engine": voice, "synth_time": s}`, `engine` naming the voice used; for a say a `/stop` cancelled before it played, `{"duration": 0, "marks": {}, ..., "stopped": true}`. A `language` that is not installed: 400 `{"error": ...}`; none: the first installed. On a synthesis error: 500 `{"error": ...}`. `pitch` is accepted and ignored.
- `POST /stop {"id": <say id>}`: cancels that say wherever it is (the synthesis stops at the next item and the say is answered `stopped` with no audio; a say that has rendered but not started playing is not played; a say that has not arrived yet is cancelled when it does, the last 64 stopped ids being kept), stops the stream in progress and sends a stop of the `speech` stream to the audio output, so the sounds `ALAudioPlayer` plays go on. Returns `{"stopped": true}`. Without an `id`, only the stream and the audio output are stopped. The `ALTextToSpeech` replacement names the call's id in both `/say` and `/stop` ([speech.md](../services/speech.md), "Stop").
- `GET /health`: `{"ok", "languages": {name: {"voice", "loaded"}}, "voices_tag", "soundcard"}`, 200 once every installed language's voice is loaded, 503 before (the healthcheck's probe).

### Rendering

- Each text item is synthesized on its own and the parts are concatenated, so a marker's offset is exactly the duration of everything before it. The cost is a small prosody break at each marker.
- A pause item is silence of the given length. Offsets and durations are computed from sample counts, so they match the audio exactly.
- `rate` (percent, 100 = normal): Piper's `length_scale = 100 / max(rate, 20)`.
- The output is mono s16le at the first text item's sample rate (22050 Hz for every voice in the table; 22050 when there is no text). Other parts are resampled by linear interpolation.
- The reply is sent as soon as synthesis is done. The PCM is streamed to the audio output in a background thread, in 100 ms chunks, as its `speech` stream (`"stream": "speech"` in the `play` header, [audio-output.md](../host/audio-output.md), "Protocol"), so the caller's clock starts with the audio and sounds mix with it.
- Synthesis takes 0.1–0.3 s per sentence once the voices are loaded.

### Image and process

- `python:3.12-slim`, native architecture (no emulation), `piper-tts` pinned and `numpy`; the default voices as above. The server is the container's PID 1 and exits on `SIGTERM` (exit code 0): the kernel applies no default signal action to PID 1, so without its handler `docker stop` waited the 10 s grace period and killed it (measured: 10.2 s, exit 137; with the handler, well under a second).
- Environment: `NAOQI_SIM_SOUNDCARD` (`host:port`, default `host.docker.internal:9562`), `NAOQI_SIM_LANGUAGES` (above).

### Failure behaviour

- If the audio output is unreachable, the audio is dropped (logged) and `/say` still returns the timings, so callers keep their clock.
- A new `/say` while one is still streaming starts a new play of the `speech` stream. The audio output plays only the newest play of a stream (see [audio-output.md](../host/audio-output.md), "Streams").

## Open questions

1. **More languages.** Adding one of the five missing languages means a Piper voice with a permissive dataset, which none has today; a non-commercial voice could come as an opt-in tier, fetched after a typed acceptance as naoqi-viewer fetches the NAO meshes, never by default. A per-language voice override in the config (a NAO's `setVoice`) is a later addition if anyone wants it.
2. **Word events.** `CurrentWord` and `PositionOfCurrentWord` would need per-word timings; Piper 1.8 can return phoneme alignments, not words. Not in v1.
3. **Pitch.** `\vct` and `pitchShift` are no-ops with Piper. A pitch shift of the PCM (resampling) is a cheap approximation if a client turns out to depend on it.
4. **Stop and concurrent streams.** Settled by the ids (Oct 16, 2026): a `/stop` names its say, so one racing a new `/say` cancels that say and no other, whether it arrives before or after it. The global flag remains for an idless `/stop`.
