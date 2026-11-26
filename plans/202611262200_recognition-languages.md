# Recognition languages

**Status:** Done

Implements the settled behaviour in `specs/container/asr-engine.md` ("Models", "Image and process"), `specs/services/speech-recognition.md` ("Languages") and `specs/runtime/config.md` (the language packs): the speech recognition engine gets one Vosk model for each speech engine language that has one, thirteen in all. English and French stay in the image. The others are fetched on first use, hash-checked, into a language packs volume that the two engines and both NAOqi versions share. The config accepts those thirteen. It leaves out the languages with a voice but no model (Danish, Finnish, Norwegian) and those with a model but no voice (Japanese, Korean, Chinese, Arabic).

## Scope

- `docker/asr-engine/server.py`: the `MODELS` table and `MODEL_SHA256`, the installed languages from `NAOQI_SIM_LANGUAGES`, models looked up in the image and then the volume, a first use's download (SHA-256 checked, unpacked, renamed into place), a shared model loaded once, `/health` naming the models.
- `docker/asr-engine/Dockerfile`: the default models under `/asr-models-builtin`, the environment.
- `docker/tts-engine/server.py`, `Dockerfile`: the voices volume moves to `/language-packs/tts-voices`.
- `docker/compose.yaml`: `language-packs` (replacing `piper-voices`) mounted in `tts` and `asr`; `asr` gets `NAOQI_SIM_LANGUAGES` and a 10-minute start period.
- `docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_core.py`: `LANGUAGES`, the thirteen.
- `src/naoqi_sim/config.py`: `LANGUAGES`, the thirteen.
- `src/naoqi_sim/stack.py`, `docker_images.py`: `wait_asr` names the languages it waits for, with a fresh `ready_timeout_s` for a first use's downloads.
- `tests/test_asr_engine.py`, `test_config.py`, `test_speech_recognition_core.py`, `test_entrypoint.py`, `test_sim.py`: the tables agree, the fetch (image, volume, download, wrong hash, a download that dies), the shared model, the shared volume; the language without a model is now Danish.
- `tests-e2e/test_speech_recognition_live.py`: a comment (German now has a model but isn't installed).
- `examples/configs/languages.json`, `README.md`: German installed in the example.
- `tests-e2e/test_speech_recognition_live.py`: a sim that boots in German, heard and talked to in German.

## Steps

1. The engine's table, the fetch and the readiness, with their fast tests. Done.
2. The volume: one, `language-packs`, shared by both engines and both versions (a volume per version was tried and dropped the same day). Done.
3. The config's and the module's lists. Done.
4. The engine checked with its real models (Nov 26, 2026). It was built under a separate tag, every model was fetched into an empty volume, and the speech engine's voices said the test phrases (the results are in asr-engine.md, "Models"). Done.
5. Measure on a running sim, both versions, with `available_languages` English, French and German: the boot (the entrypoint's `ALDialog.setLanguage German` on 2.8), `ALSpeechRecognition` hearing German, and a German topic loaded and answering. Then adjust the entrypoint if the dialog refuses a language without its data, update the example config and the README, and add a live test. Done (Nov 26, 2026): both versions boot with German, hear it and answer a German topic, so the entrypoint is unchanged. `examples/configs/languages.json` installs German. The live test `test_a_sim_that_boots_in_german_speaks_hears_and_talks_german` boots in German and plays the robot's own German speech back into the room, preceded by silence (the module's 0.35 s guard ate the first word without it).

## Verification

Lint, type check and the fast tier pass. Then step 5's measurements, and the live tier on both versions, which this machine's sims run only with the user's go-ahead. Mark this plan `Done` and the specs `Implemented` once they pass. Done Nov 26, 2026: lint, type check and the fast tier pass, and the full live tier passed on both versions (256 passed, 12 skipped, 20 expected failures), the German test included.
