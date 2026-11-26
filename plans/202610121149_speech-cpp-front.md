# Speech: a C++ front for ALTextToSpeech, so the boxes and ALAnimatedSpeech stop by task id

**Status:** Done

After [202610121143_naoqi-2-8-sdk.md](202610121143_naoqi-2-8-sdk.md) (`Done`): our C++ is compiled against each suite's own SDK, which makes the front's typed calls safe on 2.8.

Implements:
- [speech.md](../specs/services/speech.md), "Architecture: a C++ front over the Python core" and the behaviour it changes ("Blocking", "Ids", "Stop by id"): the Say and Animated Say boxes and `ALAnimatedSpeech` start, wait for and stop a sentence by task id on 2.1 and 2.8, as on a NAO.
- From [service-replacement.md](../specs/container/service-replacement.md): "Task ids, `wait` and `stop(id)`: a C++ front", including signals on the front, built here first and reused by the audio player plan that follows.

Left out: speech.md's other open questions (`getLanguageEncoding`, `sayToFileAndPlay`, subtitles, the duration tolerance, word events) and everything of the audio player plan (mixing, the `speech` stream name), which follows this one.

The design was measured before writing this plan (Oct 12, 2026). Today the Say box's `stop(id)` is ignored on 2.1 and the Say box fails on 2.8; a stop on `ALAnimatedSpeech` never reaches the speech on either version.

## Scope

**Container**
- `docker/naoqi/services/speech/nao_sim_speech_front.cpp` (new): `ALTextToSpeech`, the C++ front, from the measurement's prototypes.
- `docker/naoqi/services/speech/nao_sim_speech_core.py`: `Speaker` takes the call's id, `stop(id)`, a queue of waiting calls, `is_done(id)`, `new_id()`; signals through a callback the shells give it.
- `docker/naoqi/services/speech/nao_sim_speech_almodule.py`, `docker/naoqi/services/speech/nao_sim_speech_qiservice.py`: registered as `_NaoSimTextToSpeech`; the start/poll methods the front calls; on 2.8 no signals of their own (the front's), `_fire` called on the front.
- `docker/naoqi/Dockerfile.naoqi-2.1`, `docker/naoqi/Dockerfile.naoqi-2.8`: the front built in the `native` stage with the relay's flags, `ldd -r` checked, copied next to the relay.
- `docker/naoqi/entrypoint-lib.sh`: `load_native <path> <name>` generalizing `load_relay` (the relay becomes one of its uses).
- `docker/naoqi/entrypoint-2.1.sh`, `docker/naoqi/entrypoint-2.8.sh`: `MODULES` load the core; the front loaded after the modules and before the dependents come back; `ADDED` gains `_NaoSimTextToSpeech`; `REPLACED` (`ALTextToSpeech`) now answered by the front.

**Tests**
- `tests/test_speech_core.py`: the core's ids and stops.
- `tests/test_entrypoint.py`: the load order (relay, modules, front, dependents) and that a front that registers nothing fails the boot.
- `tests-e2e/test_speech_live.py`: the boxes' patterns and `ALAnimatedSpeech`'s stop, on both versions.

**Specs**
- Frontmatter of `speech.md` and `service-replacement.md` (the new `.cpp`); `speech.md` and `service-replacement.md` statuses.

## Steps

1. **The core, per call.** `Speaker.say(text, call_id)` (and its language variant) gives every call the id it is passed; `new_id()` hands out ids for blocking calls from a range that cannot meet the broker's task ids (from 1 000 000). Calls still serialize on the lock, in arrival order; `stop(call_id)` on the speaking call does what `stop_all` does (stop flag, engine `/stop`, `TextInterrupted 1`, unreached bookmarks dropped), on a waiting call marks it so it returns without speaking or raising events, on an unknown id does nothing. `Status [id, ...]` uses the call's id. `start(call_id, text, lang)` runs `say` on a thread and returns at once; `wait_done(call_id, timeout_s)` waits at most that long for it to be over (an unknown or finished id is done). Signals go through the `signal(name, *args)` callback as today.
2. **Fast tier for the core.** `stop(id)` of the speaking call interrupts it and the next waiting call then speaks; `stop(id)` of a waiting call skips it with no events; ids appear in `Status`; `stop_all` still ends the current call; an unknown id is a no-op; `start`/`wait_done` around a blocking engine stub; a call speaks in the language it was given only.
3. **The shells.** Both register `_NaoSimTextToSpeech` with every method of the contract forwarded to the `Speaker`, plus `start`, `waitDone`, `stopCall` (not `stop`, the `ALModule` generic) and `newId`. On 2.1 the instance is exported under the module's name (`__all__`: the broker finds a Python `ALModule` by name, and `from <module> import *` skips underscore names). 2.1: an `ALModule`. 2.8: a `@qi.multiThreaded()` qi service; its `signal` callback calls the front's `_fire(name, text)` through the module's session (`_started` and `languageTTS`, the ones fired today).
4. **The front.** `nao_sim_speech_front.cpp`: an `ALModule` named `ALTextToSpeech` binding every method of speech.md's contract, with `say(text)` and `say(text, language)` as two bindings and, built for 2.8 only (`-DNAOSIM_NAOQI_28`), `_sayWithLocale(text, locale, uuid)`, `_pause`, `_resume`, `reset`, `_fire(name, text)` and the three signals advertised with `getBuilder().advertiseSignal`. A small `Core` wrapper reaches the core with typed calls: `ALProxy` on 2.1, a `qi::AnyObject` from `getParentBroker()->session()` on 2.8. `say`: `id = getMethodID()`, or `core.newId()` when `-1`; `core.start(id, ...)`; `core.waitDone(id, 20)` until true, `core.stopCall(id)` once when `isStopRequired(id)`. 2.8's `_sayWithLocale` (called by `ALAnimatedSpeech` as a qi call it stops by cancelling) returns a `qi::Future<void>` from a `qi::Promise` whose cancel callback calls `core.stopCall(id)`, completed by a detached thread that waits for the sentence (cancelled or done). The locale struct is taken as a `qi::AnyValue`. `whoami` names the front and the core.
5. **Build and boot.** The front built in each Dockerfile's `native` stage beside the relay (same flags, against the suite's own SDK). The entrypoints: `exit_builtins ALTextToSpeech`, `load_native` the relay, `load_modules` (the core among them), `load_native` the front, then the dependents (`launch_local` on 2.1, `startService` on 2.8), then the readiness checks. `ALAnimatedSpeech` 2.8 must find `_started` on the front at its start: it comes back after the front, as today after the qi service.
6. **Live tier** (`test_speech_live.py`, both versions):
    - The existing tests pass unchanged through the front (blocking, bookmarks with `ALAnimatedSpeech`, `stopAll`, during synthesis).
    - The Say box's pattern from NAOqi's Python: 2.1 `post.say`, `wait(id, 0)`, `ALProxy('ALTextToSpeech', True).stop(id)` at 0.8 s ends the sentence (`TextInterrupted 1`, the `MemorySink` playback interrupted) and `wait` returns then; 2.8 the same with `pCall("say", ...)`, `wait(id)` and `stop(id)` on qi service objects.
    - Of two posted sentences, stopping the second while the first speaks: the first plays to its end, the second is never spoken.
    - The Animated Say pattern: `stop(id)` on `ALAnimatedSpeech` during its sentence interrupts the speech and its `wait` returns early.
    - `Status` events carry the posted task id.
    - 2.8: `ALAnimatedSpeech` is alive after boot (it connected to `_started`) and `setLanguage` emits `languageTTS` to a host client.
7. **Specs.** `speech.md` frontmatter gains `docker/naoqi/services/speech/nao_sim_speech_front.cpp`, `service-replacement.md`'s too; both specs to `Implemented` (service-replacement.md's "Task ids" section is built here; the player plan only reuses it), with their rows in `specs/_index.md`; the overview's speech line and milestone 2 exit; this plan `Done` here and in [_index.md](_index.md).

## Verification

- `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (fast tier, including `test_speech_core.py`, `test_entrypoint.py`, `test_project_map.py`).
- `uv run pytest tests-e2e` on 2.1 and 2.8 (images rebuilt), including `test_modules_live.py`'s Python 2.7 compile check.
- CI green on both versions.
- Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
