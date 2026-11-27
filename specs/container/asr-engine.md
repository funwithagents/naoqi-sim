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

Design settled Nov 21, 2026 (a trial on 80 utterances, then a throwaway engine in front of both NAOqi versions). Built by [plans/202611211500_speech-recognition.md](../../plans/202611211500_speech-recognition.md). Languages beyond English and French settled Nov 26, 2026, built by [plans/202611262200_recognition-languages.md](../../plans/202611262200_recognition-languages.md).

## Purpose

A small container that listens to the audio the NAOqi container sends it for a given list of phrases, and answers with what it heard. It knows nothing about NAOqi: the statuses, `WordRecognized`, the dialog's grammar and callbacks, the bips all stay in the override module ([speech-recognition.md](../services/speech-recognition.md)). It is the listening counterpart of the speech engine ([tts-engine.md](tts-engine.md)) and its own container for the same reasons as the perception engine ([perception-engine.md](perception-engine.md)): the NAOqi images rule out any current recogniser, and the host stays a set of dumb devices.

## Decided

### Recogniser: Vosk

- **Vosk** (`vosk`, pinned), with one small model per language ("Models" below). Nothing of them is in the repository.
- **Licensing.** The library is Apache-2.0, as naoqi-sim is; each model's licence is in the table below, all Apache-2.0 or MIT.
- **Why Vosk.** It recognises from a list of phrases, which is what a NAO's module does; CPU only, a model loaded in 0.13 s, 1 to 2 % of real time, wheels for x86_64 and arm64. Measured on 80 utterances: French 6 out of 6 for every voice, English 6 out of 6 for two voices and 2 to 3 out of 6 for two others. PocketSphinx, whisper.cpp, faster-whisper and sherpa-onnx were considered and not tried: none takes a phrase list as simply.
- **Whole phrases, not words.** Given loose words the recogniser confuses them freely (a robot's full dialog vocabulary turned "the tai chi dance" into another sentence); given the whole phrases it finds them (measured with 4,700 phrases, built in 8 ms). And it may still output a mix of the list's words: so a result counts only when it **equals** one of the phrases (with word spotting, when one of the phrases is found in it as consecutive words: measured on a real voice, a word outside the list may come out as one of the list's words).

### Models

NAOqi names a language by an English word, and a NAO's language pack installs its voice, its recognition and its dialog together. The engine mirrors the speech engine's languages ([tts-engine.md](tts-engine.md), "Languages"):

- **One small model per language**, the table below. The engine's table (`server.py`, `MODELS`, with each archive's SHA-256 in `MODEL_SHA256`) is the one place that maps a NAOqi language name to a Vosk model; the config's `LANGUAGES` and the NAOqi module's `LANGUAGES` repeat its keys, and the fast tier checks the three agree and that they are the speech engine's languages less the three without a model.
- **The installed languages** come from `NAOQI_SIM_LANGUAGES`, as for the speech engine (the config's `setup.available_languages`, which `NaoqiSim.start()` passes through compose; `English,French` when unset). A name without a model ends the server with the message on its output (the config refuses it first, so this catches a stack started by hand).
- **Models on two roots.** The image bakes the default languages' models (`DEFAULT_LANGUAGES`, English and French, the config's default; the fast tier checks the Dockerfile fetches exactly those, hash-checked) under `/asr-models-builtin/`, so a default config hears with no download at run time. Any other installed language's model is downloaded the first time it is needed into the language packs volume, under `/language-packs/asr-models/` ("Image and process"): the archive from the project's model site, its SHA-256 checked against the table (a mismatch fails the load and leaves nothing), unpacked beside it and renamed into place, so a container killed mid-download leaves no half model under the final name. The engine looks a model up in the image first, then in the volume.
- **Readiness.** At start the server answers `/health` at once, 503, then loads every installed language's model, fetching the missing ones, and answers 200 once all are loaded. A model that two languages share is loaded once. Measured Nov 26, 2026, all thirteen fetched into an empty volume: 1.5 to 4.4 s per download for the 30 to 50 MB ones, 18 s for Swedish (290 MB), each then loaded in 0.1 to 1 s; 1.4 GB in the volume. A model that cannot be fetched (no network, a wrong hash) ends the server with the language named on its output, and the start fails with the end of its log.

| NAOqi name | Model | Licence | Archive |
|---|---|---|---|
| English | `vosk-model-small-en-us-0.15` | Apache-2.0 | 40 MB, in the image |
| French | `vosk-model-small-fr-0.22` | Apache-2.0 | 41 MB, in the image |
| German | `vosk-model-small-de-0.15` | Apache-2.0 | 45 MB |
| Dutch | `vosk-model-small-nl-0.22` | Apache-2.0 | 39 MB |
| Swedish | `vosk-model-small-sv-rhasspy-0.15` | MIT | 290 MB |
| Spanish | `vosk-model-small-es-0.42` | Apache-2.0 | 39 MB |
| Brazilian | `vosk-model-small-pt-0.3` | Apache-2.0 | 31 MB |
| Czech | `vosk-model-small-cs-0.4-rhasspy` | MIT | 44 MB |
| Italian | `vosk-model-small-it-0.22` | Apache-2.0 | 48 MB |
| Polish | `vosk-model-small-pl-0.22` | Apache-2.0 | 50 MB |
| Portuguese | `vosk-model-small-pt-0.3` (the Brazilian one) | Apache-2.0 | shared |
| Russian | `vosk-model-small-ru-0.22` | Apache-2.0 | 44 MB |
| Turkish | `vosk-model-small-tr-0.3` | Apache-2.0 | 35 MB |

- **Not offered.** Danish, Finnish and Norwegian have a voice but no Vosk model, so they have no language pack. Japanese, Korean, Chinese and Arabic have small Apache-2.0 models but no voice, so they are not taken either (decided Nov 26, 2026: a language is a voice and a model, [config.md](../runtime/config.md)). Greek has only a 1 GB server model, and no voice.
- **Portuguese recognises with the Brazilian model** (decided Nov 26, 2026): Vosk has no European Portuguese model, and the accent is what fails. Measured Nov 26, 2026 with eight short phrases said by Piper's voices: the European voice (`pt_PT-tugão`, the speech engine's) 1 of 8, the four Brazilian ones 4 to 8 of 8. With word spotting, the European "que horas são" was recognised. A European speaker should expect much the same.
- **The Brazilian model is the weakest of the thirteen, and drops a short first word.** Vosk's own figures put it at 32.6 % word error on Common Voice, against 9.9 % for English and 13.8 % for German. Measured Nov 26, 2026:
  - **Synthetic voices:** every miss lost the phrase's first short word ("olá", "que", "me"), more often in fast voices. The speech engine's `pt_BR-faber` said "olá robô" in 0.64 s and only "robô" was heard, but "olá, robô!" and "olá robô, tudo bem" were recognised whole. The slowest voice, `pt_BR-cadu`, got all eight phrases.
  - **Real speech** (FLEURS, read sentences, the 40 sentences of a sample with no word the model lacks, as the phrase list): 29 of 40 Brazilian sentences recognised whole, at 4 % word error, against 35 of 40 at 3 % for German under the same test.
  - **So** a short, quick command in Brazilian is where it fails; longer phrases work.
- **Swedish's model has no phrase lists.** The rhasspy repackage carries a static graph (`HCLG.fst`), not the runtime one the others have (`HCLr.fst`, `Gr.fst`): Vosk ignores the phrase list and recognises freely, and the engine's rule that an utterance must equal a phrase still applies to what it heard. Measured: the three test phrases recognised, a sentence outside them heard word for word and rejected.
- **Measured per language** (Nov 26, 2026; the speech engine's own voice saying three phrases of a five-phrase list and one sentence outside it, 16 kHz, one second of silence before): every phrase recognised in English, French, German, Dutch, Swedish, Spanish, Czech, Italian, Polish, Russian and Turkish, at confidence 0.78 to 1.0, and every outside sentence rejected; Brazilian two of three (a 0.64 s "olá robô": nothing heard, or only "robô", depending on the phrase list); Portuguese above. A phrase holding a word a model does not know is dropped at `/start`, as before (Czech "robote", where "robot" is known).

### HTTP API (port 8080, standard-library `ThreadingHTTPServer`)

One listening session at a time, which is what one NAOqi sends.

- `POST /start`: `{"language": "English", "phrases": [...], "word_spotting": false}`. Builds the recogniser for these phrases and forgets any audio so far. A phrase is normalised (lower case; letters, digits and apostrophes kept; anything else a space). Reply: `{"phrases": n, "dropped": [...], "build_ms": t}`, `dropped` the phrases holding a word the model does not know (the recogniser would otherwise ignore the whole list). A phrase that begins or ends with `<...>` allows other speech there, as word spotting does on both sides of every phrase. An unknown language is a 400.
- `POST /audio`: raw PCM, 16 kHz mono signed 16-bit little-endian (`Content-Type: application/octet-stream`), any length. Reply: `{"speech": bool, "final": null | {"phrase": p, "confidence": c, "text": t, "lead": bool, "trail": bool}}`. `speech` is true from the first buffer in which words are being heard until the utterance's end. `final` comes with the buffer that ends an utterance (silence ends none): `phrase` is the phrase as it was given when the utterance equals one (both normalised), else `""`; `confidence` the lowest of its words' confidences; `text` what was heard. With `word_spotting`, other speech before and after is allowed around the phrase, whatever the recogniser made of it (a word it does not know may come out as one of the list's words: "please" heard as "is"), the longest phrase found as consecutive words wins, and `lead` and `trail` say whether there was speech before and after it.
- `POST /stop`: drops the session. Audio posted with no session answers `{"speech": false, "final": null}`.
- `GET /health`: `{"ok": true, "recognizer": "vosk", "languages": [...], "models": {language: model}}` with 200 once every installed language's model is loaded, `{"ok": false, "languages": [...]}` with 503 before (the healthcheck's probe).
- The models are loaded at start and kept; a lock guards the session.

### Image and process

- `python:3.12-slim`, native architecture, `vosk` pinned, `libatomic1`; the default languages' two models fetched at build, their SHA-256 checked. 481 MB (measured Nov 21, 2026).
- **The language packs volume.** The compose `asr` service mounts the named volume `language-packs` at `/language-packs`, as the `tts` service does: one volume for both engines' fetched data, a NAO's language pack being its voice and its recognition together, the voices under `tts-voices/` and the models under `asr-models/`. **One volume for both NAOqi versions** (`naoqi-sim_language-packs`; decided Nov 26, 2026): which languages a run installs is the config's choice, per run, and the volume only keeps what was fetched, so a language is fetched once whichever version uses it. `docker compose down -v` empties it; the image's English and French remain.
- Environment: `NAOQI_SIM_LANGUAGES` (above).
- The server is the container's PID 1 and exits on `SIGTERM`, as the other engines' do.
- The compose service is `asr` (image `naoqi-sim/asr:dev`, container `naoqi-sim-asr`), with a healthcheck on `/health` (every 2 s, a start period of 10 minutes for the downloads, so a slow fetch is `starting`, never `unhealthy`). The NAOqi services reach it at `http://asr:8080` (`NAOQI_SIM_ASR_URL`) ([container.md](container.md), "Compose").
- **Built, verified and checked with the others**: `fetch_and_build_images` builds it with the version label and the recipes digest, the verification waits for it to be healthy (the image's models), `check_images` requires it, and `NaoqiSim.start()` waits for it after the perception engine, with the config's `ready_timeout_s`, so a first use's download is waited for ([api.md](../runtime/api.md)). CI's image archive carries it ([ci.md](../testing/ci.md)).
- **Off by config**: `speech_recognition.enabled = false` ([config.md](../runtime/config.md)) starts no `asr` container and `start()` waits for none; the module then hears nothing ([speech-recognition.md](../services/speech-recognition.md), "Without an engine").

### Failure behaviour

- A body that is not valid for its route is a 400 with the reason; an unexpected error a 500. The NAOqi side treats both as silence and logs once per run of failures.
- The engine unreachable: the module's call fails fast (a 2 s timeout), the buffer is lost, and it logs the first failure and the recovery.

## Open questions

1. **More languages.** Settled Nov 26, 2026 ("Models"). Danish, Finnish and Norwegian come when Vosk has a small model for them; Japanese, Korean, Chinese and Arabic when the speech engine has a voice.
2. **Larger models**, for a user who wants better recognition than the small ones give: a build argument, when asked for.
3. **Several sessions**, should two NAOqi containers ever run at once.
