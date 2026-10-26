# Speech languages: Piper only, NAO's language lists, voices on a volume

**Status:** Done

Implements the settled behavior in [tts-engine.md](../specs/container/tts-engine.md) ("Engine", "Languages", "Voices"), [speech.md](../specs/services/speech.md) ("Language", pitch), [config.md](../specs/runtime/config.md) (`speech.languages`), [container.md](../specs/container/container.md) ("Compose") and [api.md](../specs/runtime/api.md) (steps 3 and 4, progress, verification). It delivers one Piper voice per NAOqi language for sixteen languages, a config that installs languages as a NAO's language packs, the default voices in the image and the others fetched into a Docker volume on first use, and `getSupportedLanguages` answering NAOqi's own list. It leaves out a per-language voice override, non-commercial voices as an opt-in tier, and the five languages without a permissive voice (Arabic, Chinese, Greek, Japanese, Korean).

## Scope

- `docker/tts-engine/server.py` — Piper only (the eSpeak path and the `engine` field go; `pitch` ignored); the voice table (`VOICES`, `DEFAULT_LANGUAGES`, `VOICES_TAG`); `NAOQI_SIM_LANGUAGES`; the two voice roots (image, volume), the fetch through a temporary name with the path percent-encoded; `/health` 503 until every installed voice is loaded, the server answering while it loads; `/say` 400 for a language not installed; the process ends with the voice named when one cannot be loaded.
- `docker/tts-engine/Dockerfile` — `piper-tts` pinned; no `espeak-ng` package (Piper embeds it); the default voices under `/voices-builtin/<release>/` from `VOICES_TAG`; `NAOQI_SIM_LANGUAGES` default.
- `docker/compose.yaml` — the `piper-voices` volume on `tts`, its healthcheck (start period for a download), `NAOQI_SIM_LANGUAGES` on the three services, `NAOQI_SIM_TTS_ENGINE` gone.
- `docker/naoqi/services/speech/naoqi_sim_speech_core.py` — `SUPPORTED_LANGUAGES` (NAOqi's 21), `LOCALES`, `installed_languages` from the environment, the boot language the first installed, `Speaker.locale()`.
- `docker/naoqi/services/speech/naoqi_sim_speech_almodule.py`, `naoqi_sim_speech_qiservice.py` — `getSupportedLanguages` answers the 21, `locale` follows the language.
- `src/naoqi_sim/config.py` — `SpeechSettings.languages` in place of `engine`, `SPEECH_LANGUAGES`, the list checks, tuples as lists in `to_dict`.
- `src/naoqi_sim/stack.py` — `NAOQI_SIM_LANGUAGES` in the compose environment; `wait_ready` waits for NAOqi, then for the engine.
- `src/naoqi_sim/docker_images.py` — `wait_tts` on the engine's healthcheck (its log in the error), used by the start and the verification; `_state` shared with `wait_healthy`.
- `src/naoqi_sim/__init__.py` — exports `SPEECH_LANGUAGES`, not `SpeechEngine`.
- `examples/configs/languages.json` — three languages installed.
- `tests/test_tts_engine.py`, `tests/test_speech_core.py`, `tests/test_config.py`, `tests/test_sim.py`, `tests/test_docker_images.py`, `tests/fake_docker.py` — the functional tests below; the fake docker records `NAOQI_SIM_LANGUAGES` and gives the engine's container a health.
- `tests-e2e/conftest.py`, `tests-e2e/test_speech_live.py` — the live tier installs German as a third language; the lists, the locale and a German sentence spoken with the fetched voice.
- `README.md` — the engine's line, the example, the attribution.

## Steps

1. The engine: the table and the roots, the fetch, the readiness, Piper only (`server.py`, `Dockerfile`, `compose.yaml`).
2. The config: `languages`, its checks, the constant the engine's table is checked against.
3. The host: the compose environment and the wait for the engine, in the start and in the verification.
4. The NAOqi side: the two lists, the locale, the boot language.
5. The tests, fast then live; the specs' statuses back to `Implemented`.

## Verification

- Fast: `test_tts_engine` (the engine's and the config's lists are one; the Dockerfile bakes the default voices from the pinned release; the voice path; the installed list from the environment; a voice in the image never fetched, one in the volume reused, a missing one fetched into the volume with its key percent-encoded and no `.part` left, a download that dies leaving no half file; `/health` false until every voice is loaded; a say in a language not installed refused unsynthesized), `test_speech_core` (the installed list from the environment, the first at boot; the 21 supported; the locale), `test_config` (the default, the order kept, the errors for an empty, a non-list, a non-string, an unknown, a voiceless and a repeated language), `test_sim` (the languages reach compose; the engine's two progress lines), `test_docker_images` (an engine that cannot load its voices, or is still loading them, fails the verification).
- Live, both versions: `test_speech_live` (`getAvailableLanguages` is the config's three, `getSupportedLanguages` the 21, `locale` follows the language; German spoken with the voice fetched into the volume).
- `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; `uv run naoqi-sim fetch-and-build-images` then `uv run pytest tests-e2e -k speech` on both versions.
