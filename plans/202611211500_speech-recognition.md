# Speech recognition: the `asr` engine and `ALSpeechRecognition`

**Status:** Done

Implements [specs/container/asr-engine.md](../specs/container/asr-engine.md) and [specs/services/speech-recognition.md](../specs/services/speech-recognition.md): a fourth image with a Vosk recogniser for English and French, `ALSpeechRecognition` added inside NAOqi on both versions (and `_AsrCompiler1` on 2.8) so scripts get `WordRecognized` and `ALDialog` answers speech, `speech_recognition.enabled`, the image built and checked with the others, and live tests on sentences synthesised once and committed (`tests-e2e/speech/`). It leaves out autonomous life's side (the main dialog started by a person in zone 1, the launchpad keys, 2.8's signs-and-feedback application), more languages, and the robot's sound-set bips.

## Scope

New:

- `docker/asr-engine/Dockerfile`, `docker/asr-engine/server.py` — the engine: Vosk, the two models fetched and hash-checked at build, `/start`, `/audio`, `/stop`, `/health`
- `docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_grammar.py` — the 2.1 grammar's reader and the capped expansion to phrases; the 2.8 sentence file's reader
- `docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_core.py` — the phrase sources, the listening state machine (statuses, events, delays, bips, LEDs), the engine client, the dialog's callbacks, the per-version method tables
- `docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_almodule.py` (2.1), `naoqi_sim_speech_recognition_qiservice.py` (2.8, with `_AsrCompiler1`) — the shells
- `tests/test_asr_engine.py`, `tests/test_speech_recognition_grammar.py`, `tests/test_speech_recognition_core.py` — fast tier
- `tests-e2e/test_speech_recognition_live.py` — live tier

Changed:

- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py` — in-process listeners: a format and a callback, served like a subscriber without the relay; counted in the formats asked of the host
- `docker/naoqi/entrypoint-2.1.sh`, `entrypoint-2.8.sh` — the module first in `MODULES`, named in `ADDED`
- `docker/naoqi/Dockerfile.naoqi-2.1`, `Dockerfile.naoqi-2.8` — copy the new service folder
- `docker/naoqi/services/status-service/naoqi_sim_status_core.py` — `NaoqiSim/SpeechRecognition/Source`
- `docker/compose.yaml` — the `asr` service, `NAOQI_SIM_ASR_URL` on both NAOqi services
- `src/naoqi_sim/config.py` — the `speech_recognition` block (`enabled`, default true)
- `src/naoqi_sim/docker_images.py`, `src/naoqi_sim/stack.py` — the fourth image built, labelled, verified, checked; `wait_asr`; the engine started unless disabled; the URL passed or emptied; the status read
- `src/naoqi_sim/cli.py`, `src/naoqi_sim/__init__.py` — only where they list engines or settings
- `tests/test_config.py`, `test_docker_images.py`, `test_stack.py`, `test_sim.py`, `test_entrypoint.py`, `test_status_core.py`, `test_audio_device_core.py`, `tests/fake_docker.py` — follow the above
- `.github/workflows/ci.yml` — the format check covers `docker/asr-engine`; the image archive carries `naoqi-sim/asr:dev`
- `examples/configs/` — one line where a config lists the engines
- `pyproject.toml` — ruff covers `docker/asr-engine` as it does the other engines
- Specs: the two new ones to `Implemented` with their full frontmatter; `audio-device.md`, `config.md`, `api.md`, `container.md`, `status-service.md`, `naoqi-fidelity.md`, `service-replacement.md` (hidden methods of a Python `ALModule` on 2.1), `testing.md`, `ci.md` edited for what changes and back to `Implemented` at the end; `_overview.md` (the line on speech recognition reversed, licensing, the concept's state), `specs/_index.md`, `AGENTS.md` (the project map's `docker/` row)

## Steps

1. **The engine.** `server.py`: models loaded at start; `/start` normalises the phrases, drops those with a word the model lacks, builds the recogniser from the phrases plus the unknown-word token; `/audio` feeds it, reports `speech` from the partial result and, at an utterance's end, `final` (the phrase when the text equals one, edges of unknown speech allowed with word spotting; the lowest word confidence). `Dockerfile` as the perception engine's. `tests/test_asr_engine.py` drives the handler functions with a fake recogniser (the wheel is not in the host venv): normalisation, the dropped phrases, the equality rule, word spotting's edges, `speech` going true then false, a 400 on an unknown language.
2. **The image in the host code.** `ASR_IMAGE`, `ASR_CONTAINER`, `ASR_URL`, `ASR_TIMEOUT`; build, label, verification, `check_images`, `wait_asr`; `stack.py` starts `asr` unless `speech_recognition.enabled` is false and passes `NAOQI_SIM_ASR_URL` (empty when off); the config block; compose. Tests as for the perception engine.
3. **The grammar.** The reader for `#BNF+EMV1.1` (statements split on `;`, `!slot`, `!activatable`, rules; a tokenizer for words, `<ref>`, `<...>`, `( )`, `[ ]`, `|`, `!repeat(expr,min,max)`), the expansion of the active rules with slots, shortest first, with the two caps; the reader of 2.8's sentence lines (the user-rule prefix, `<...>`). Tests on grammars written for them: alternatives, optional parts, nested references, an inactive rule left out, a slot filled and refilled, a repeat, the caps, a wildcard.
4. **The audio device's in-process listeners**, with their tests (a listener gets the buffers of its format; the host is asked for that format while one is attached and no longer after).
5. **The core.** A `Recognition` object given its collaborators (memory writer and event raiser, the audio device's listener hook, the engine client, the bip player, the LEDs, the dialog's callbacks, a clock, the installed languages, the version): the phrase sources and which one is current; the listening condition; one worker thread that owns the state machine and the delays; the engine client over `httplib` with a 2 s timeout; the dialog's callbacks called from the worker with the audio that arrives meanwhile discarded; the reset values; the errors' texts; the method tables per version with a generic answer for the methods that only keep their arguments. Tests with fakes and a fake clock, as listed in the spec.
6. **The shells.** 2.1: an `ALModule` built from the table, the hidden methods bound by hand, the events declared, the audio device's and audio player's modules imported for the in-process hooks. 2.8: the qi service (overloads as varargs where the generics need them), `_AsrCompiler1`, the dialog's sentences fetched off the caller's thread. Entrypoints, Dockerfiles, the status key.
7. **Build both images and run each version by hand** with the recording kept on (`speech_recognition.jsonl`): a vocabulary, then a hand-loaded topic, then on 2.1 a dialog application's start; compare the calls with the survey's lists and add what is missing. Check here the three points the design assumes: that the 2.1 dialog listens on its active rules without subscribing, how long after the begin bip the microphones are clean of it, and that the engine hears our speech engine's voices in both languages (pick the test sentences accordingly). The live tests' sentences were then made committed WAV files (`tests-e2e/speech/`, with `generate.py`): Piper `en_US-ljspeech-medium` (public domain) and `fr_FR-mls-medium` speaker 14 (CC BY 4.0), both trained from scratch. No `mls` speaker said "je veux une pomme" recognisably, so the French sentence became "bonjour je voudrais une pomme rouge".
8. **Live tests** (`tests-e2e/test_speech_recognition_live.py`), per version: the committed sentences (`tests-e2e/speech/*.wav`) played into the fake room; the tests of the spec's list. A topic file for the dialog test is written into the container by the test.
9. **Specs, map, CI, examples**; statuses to `Implemented`; this plan to `Done`.

## Verification

- `uv run ruff check .`, `uv run ruff format --check` on the covered folders, `uv run pyright`, `uv run pytest` (fast tier).
- The Python 2.7 check CI runs on `docker/naoqi/services/`.
- `uv run naoqi-sim fetch-and-build-images` for both versions (the fourth image built and verified), then `uv run pytest tests-e2e` on both, the machine otherwise idle.
- By hand, once per version: a hand-loaded topic answers a sentence spoken into the host microphone.
