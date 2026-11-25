---
code:
  - docker/asr-engine/server.py
  - docker/asr-engine/Dockerfile
  - docker/compose.yaml
  - src/naoqi_sim/docker_images.py
  - src/naoqi_sim/stack.py
  - src/naoqi_sim/config.py
tests:
  - tests/test_asr_engine.py
  - tests/test_docker_images.py
  - tests/test_stack.py
  - tests/test_sim.py
  - tests/test_config.py
  - tests-e2e/test_speech_recognition_live.py
---

# Speech recognition engine container

**Status:** Implemented

Design settled Nov 21, 2026 (a trial on 80 utterances, then a throwaway engine in front of both NAOqi versions). Built by [plans/202611211500_speech-recognition.md](../../plans/202611211500_speech-recognition.md).

## Purpose

A small container that listens to the audio the NAOqi container sends it for a given list of phrases, and answers with what it heard. It knows nothing about NAOqi: the statuses, `WordRecognized`, the dialog's grammar and callbacks, the bips all stay in the override module ([speech-recognition.md](../services/speech-recognition.md)). It is the listening counterpart of the speech engine ([tts-engine.md](tts-engine.md)) and its own container for the same reasons as the perception engine ([perception-engine.md](perception-engine.md)): the NAOqi images rule out any current recogniser, and the host stays a set of dumb devices.

## Decided

### Recogniser: Vosk

- **Vosk** (`vosk`, pinned), with one small model per language: `vosk-model-small-en-us-0.15` (English) and `vosk-model-small-fr-0.22` (French), about 40 MB each, fetched at the image build from the project's model site and hash-pinned, as the perception model is. Nothing of them is in the repository.
- **Licensing.** The library and both models are Apache-2.0, as naoqi-sim is.
- **Why Vosk.** It recognises from a list of phrases, which is what a NAO's module does; CPU only, a model loaded in 0.13 s, 1 to 2 % of real time, wheels for x86_64 and arm64. Measured on 80 utterances: French 6 out of 6 for every voice, English 6 out of 6 for two voices and 2 to 3 out of 6 for two others. PocketSphinx, whisper.cpp, faster-whisper and sherpa-onnx were considered and not tried: none takes a phrase list as simply.
- **Whole phrases, not words.** Given loose words the recogniser confuses them freely (a robot's full dialog vocabulary turned "the tai chi dance" into another sentence); given the whole phrases it finds them (measured with 4,700 phrases, built in 8 ms). And it may still output a mix of the list's words: so a result counts only when it **equals** one of the phrases (with word spotting, when one of the phrases is found in it as consecutive words: measured on a real voice, a word outside the list may come out as one of the list's words).

### HTTP API (port 8080, standard-library `ThreadingHTTPServer`)

One listening session at a time, which is what one NAOqi sends.

- `POST /start`: `{"language": "English", "phrases": [...], "word_spotting": false}`. Builds the recogniser for these phrases and forgets any audio so far. A phrase is normalised (lower case; letters, digits and apostrophes kept; anything else a space). Reply: `{"phrases": n, "dropped": [...], "build_ms": t}`, `dropped` the phrases holding a word the model does not know (the recogniser would otherwise ignore the whole list). A phrase that begins or ends with `<...>` allows other speech there, as word spotting does on both sides of every phrase. An unknown language is a 400.
- `POST /audio`: raw PCM, 16 kHz mono signed 16-bit little-endian (`Content-Type: application/octet-stream`), any length. Reply: `{"speech": bool, "final": null | {"phrase": p, "confidence": c, "text": t, "lead": bool, "trail": bool}}`. `speech` is true from the first buffer in which words are being heard until the utterance's end. `final` comes with the buffer that ends an utterance (silence ends none): `phrase` is the phrase as it was given when the utterance equals one (both normalised), else `""`; `confidence` the lowest of its words' confidences; `text` what was heard. With `word_spotting`, other speech before and after is allowed around the phrase, whatever the recogniser made of it (a word it does not know may come out as one of the list's words: "please" heard as "is"), the longest phrase found as consecutive words wins, and `lead` and `trail` say whether there was speech before and after it.
- `POST /stop`: drops the session. Audio posted with no session answers `{"speech": false, "final": null}`.
- `GET /health`: `{"ok": true, "recognizer": "vosk", "languages": ["English", "French"]}` with 200 once the models are loaded, 503 before.
- The models are loaded at start and kept; a lock guards the session.

### Image and process

- `python:3.12-slim`, native architecture, `vosk` pinned, `libatomic1`; the two models fetched at build, their SHA-256 checked. 481 MB (measured Nov 21, 2026).
- The server is the container's PID 1 and exits on `SIGTERM`, as the other engines' do.
- The compose service is `asr` (image `naoqi-sim/asr:dev`, container `naoqi-sim-asr`), with a healthcheck on `/health`. The NAOqi services reach it at `http://asr:8080` (`NAOQI_SIM_ASR_URL`) ([container.md](container.md), "Compose").
- **Built, verified and checked with the others**: `fetch_and_build_images` builds it with the version label and the recipes digest, the verification waits for it to be healthy, `check_images` requires it, and `NaoqiSim.start()` waits for it after the perception engine ([api.md](../runtime/api.md)). CI's image archive carries it ([ci.md](../testing/ci.md)).
- **Off by config**: `speech_recognition.enabled = false` ([config.md](../runtime/config.md)) starts no `asr` container and `start()` waits for none; the module then hears nothing ([speech-recognition.md](../services/speech-recognition.md), "Without an engine").

### Failure behaviour

- A body that is not valid for its route is a 400 with the reason; an unexpected error a 500. The NAOqi side treats both as silence and logs once per run of failures.
- The engine unreachable: the module's call fails fast (a 2 s timeout), the buffer is lost, and it logs the first failure and the recovery.

## Open questions

1. **More languages**: other models fetched into a volume on first use, as the speech voices are ([speech-recognition.md](../services/speech-recognition.md), open question 1).
2. **Larger models**, for a user who wants better recognition than the small ones give: a build argument, when asked for.
3. **Several sessions**, should two NAOqi containers ever run at once.
