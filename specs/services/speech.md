---
code:
  - docker/naoqi/services/speech/naoqi_sim_speech_core.py
  - docker/naoqi/services/speech/naoqi_sim_speech_almodule.py
  - docker/naoqi/services/speech/naoqi_sim_speech_qiservice.py
  - docker/naoqi/services/speech/naoqi_sim_speech_front.cpp
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_speech_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_speech_live.py
---

# Speech: ALTextToSpeech replacement

**Status:** Implemented

## Purpose

On naoqi-sim, `ALTextToSpeech.say()` speaks with a real voice and keeps NAOqi's contract: it blocks for the real audio and raises the events and bookmarks that `ALAnimatedSpeech`, Choregraphe boxes and existing scripts rely on.

The desktop virtual robot's built-in TTS is a simulator, so it is replaced inside NAOqi ([service-replacement.md](../container/service-replacement.md)) rather than listened to. The replacement:
- parses NAOqi's tags;
- asks the engine ([tts-engine.md](../container/tts-engine.md)) to speak; the engine streams to the host audio output ([audio-output.md](../host/audio-output.md));
- raises the events on its own clock, from the timings the engine returns.

Only one request and one reply cross from the NAOqi container per sentence, and no events travel back. Clients call `say()` and listen to the events exactly as on a NAO: nothing in them is naoqi-sim-specific.

## Decided

### Why replace rather than listen (measured on 2.1.4.13)

- The desktop `naoqi-bin` has no speech engine plugin. `ALTextToSpeech` runs in a simulated mode: `say()` blocks 0.204 s per whitespace-separated token, whatever `setParameter("speed", N)` says (tested 50, 100, 200), and tags count as tokens (`\pau=2000\` costs 0.2 s).
- It raises the full event sequence on that clock, but the clock cannot be calibrated to a real voice. It is off by about a factor of two on normal speech (0.4 s per word), so a host listening to its events would speak out of sync:
  - `say()` returns early;
  - consecutive sentences overlap;
  - gestures land on simulated bookmarks.
- Event listening stays a documented fallback only for a version where replacement is impossible ([_overview.md](../_overview.md), "Fallback: listening to TTS events"). No such version is known.

### The contract (measured on 2.1.4.13 and 2.8.7.4)

- **Methods of the built-in** (2.1 MetaObject): `say(str)`, `say(str, str)`, `sayToFile`, `sayToFileAndPlay`, `stopAll`, `setLanguage`, `getLanguage`, `getLanguageEncoding`, `getAvailableLanguages`, `getSupportedLanguages`, `resetSpeed`, `setParameter`, `getParameter`, `setVoice`, `getVoice`, `getAvailableVoices`, `setVolume`, `getVolume`, `locale`, `loadVoicePreference`, `setLanguageDefaultVoice`, `enableNotifications`, `disableNotifications`, plus the `ALModule` generics, and the signal `synchroTTS(timeval)`.
- **Events**: `ALTextToSpeech/TextStarted`, `TextDone`, `TextInterrupted`, `CurrentSentence`, `CurrentWord`, `PositionOfCurrentWord`, `CurrentBookMark`, `Status`. At idle only `ALAnimatedSpeech` subscribes, to `CurrentBookMark` and `Status`; `ALDialog` subscribes only while a topic runs.
- **`ALAnimatedSpeech` 2.1** calls `enableNotifications()` once at load. Then, per `say`, it calls `getLanguage()` and the one-argument `say(text)` with annotated text: `\pau=500\ \mrk=1\ text \mrkpause=2\`. It adds `\pau=500\` in every mode, including contextual and disabled.
  - It waits for `CurrentBookMark N` for every `\mrk=N\` **and** every `\mrkpause=N\`; otherwise it fails with "instruction N has not been received in time".
  - It also waits for `Status [id, "done"]`.
- **`ALAnimatedSpeech` 2.8** never calls `say`. It calls the hidden `_sayWithLocale(text, locale, uuid)`, where `locale` is a struct `{language, region}` and `uuid` is per call.
  - The text carries `\mrk=N\` only (no `\pau=500\`). In contextual mode it also contains the module's own auto-inserted `\mrk=N\` tags.
  - At start it connects to the hidden signal `_started`, and dies without it.
  - Bookmark and `Status` expectations are as on 2.1.
- **How `ALAnimatedSpeech` stops the speech** (measured Oct 12, 2026: today a stop on it never reaches the Python replacement, and the sentence plays to its end):
  - 2.1: it posts `say` and, when stopped, calls `ALTextToSpeech`'s generic `stop(id)` on that call, polling `isRunning(id)` (its library's own messages; the C++ front's live test passes through this path).
  - 2.8: it calls `_sayWithLocale` as a qi call and, when stopped, cancels that call's future: `qicli trace ALTextToSpeech` shows `locale`, `_sayWithLocale` and nothing else, no `stop` and no `stopAll`.
- **Choregraphe box library** (all 160 boxes of the 2.1 suite scanned):
  - Say box: `id = post.say(text)`, `wait(id, 0)`, and `stop(id)` from a second proxy (2.1); on 2.8, `id = pCall("say", text)`, `wait(id)` and `stop(id)` on qi service objects. `stop(id)` and `wait` are the `ALModule` generics, which a Python replacement cannot serve (measured Oct 12, 2026: [service-replacement.md](../container/service-replacement.md), "Task ids, `wait` and `stop(id)`").
  - Animated Say: goes through `ALAnimatedSpeech`, with the same pattern on `ALAnimatedSpeech`.
  - About a dozen boxes: `getLanguage`.
  - Language boxes: `setLanguage`.
  - Nothing else.
- `ALDialog` is not a v1 target.

### Architecture: a C++ front over the Python core

Only a C++ `ALModule` serves `post`/`pCall`, `wait(id)`, `stop(id)` and `isRunning(id)` as a NAO's built-in does, on both versions ([service-replacement.md](../container/service-replacement.md), "Task ids, `wait` and `stop(id)`: a C++ front"). So the replacement is split, as `ALAudioPlayer`'s ([audio-player.md](audio-player.md)):

- **`ALTextToSpeech`, the C++ front** (`docker/naoqi/services/speech/naoqi_sim_speech_front.cpp`, one source for both versions, built in the native build stage and loaded with `launchLocal`): every method of the contract above, each forwarding to the core. `say` (both overloads) takes the task id with `getMethodID()` (a new id from the core when called blocking), starts the sentence in the core and polls every 20 ms until the core reports it done, calling the core's `stop(id)` when `isStopRequired(id)` turns true. On 2.8, `_sayWithLocale` answers with a `qi::Future` whose cancel calls the core's `stop(id)`, a thread following the sentence completing it ([service-replacement.md](../container/service-replacement.md), "Stopped by a cancel"). The generics (`pCall`, `wait`, `stop`, `isRunning`) are the front's own, so the Say and Animated Say boxes and `ALAnimatedSpeech` work unchanged.
- **The front reaches the core** through `ALProxy` on 2.1 and a `qi::AnyObject` from the broker's session on 2.8, with typed calls.
- **The hidden signals are the front's** (2.8): `_started (s)`, `synchroTTS (L)` and `languageTTS (s)` are advertised on the C++ module with `getBuilder().advertiseSignal` and fired as member signals, which a client in another process (`ALAnimatedSpeech` runs in `qilaunch`) receives (measured). The core asks the front to fire them through a hidden method (`_fire(name, text)`); the core never connects to them. `synchroTTS` is declared, never fired, as today.
- **`_NaoqiSimTextToSpeech`, the Python core**: today's `naoqi_sim_speech_core.Speaker` and its shells, registered under the hidden name instead of `ALTextToSpeech` (an `ALModule` on 2.1, a qi service on 2.8), with the per-call ids and stops below. It is what the fast tier tests.
- **Boot:** the loader loads the core, then the front loads, both from NAOqi's autoload in place of the built-in ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in"); the readiness check covers both names. Every module NAOqi loads afterwards (`ALAnimatedSpeech`, `ALDialog`, the behaviors' boxes) finds the front.

### Behaviour

- **Event sequence** for one `say`, matching the built-in's:
  1. `Status [id, "enqueued"]`, `TextStarted 1`, `TextDone 0`.
  2. After the engine replies: `Status [id, "started"]`, `CurrentSentence text`, and the `_started` signal (2.8).
  3. `CurrentBookMark N` at each marker offset.
  4. At the end: `TextInterrupted 1` (only if stopped), `Status [id, "done"]`, `CurrentSentence ""`, `TextDone 1`, `CurrentBookMark 0`, `TextStarted 0`.
- **Blocking**: `say()` returns when the engine's `duration` has elapsed from the reply, on `stopAll`, or on a `stop(id)` of that call. Calls are serialized by a lock: a second `say` waits until the first is done.
- **Ids**: each call's id is its task id from the front (the id `post`/`pCall` returned, or one from the core for a blocking call), and it is the id of its `Status [id, ...]` events, so a caller that posted the call can match them.
- **Stop by id**: `stop(id)` on the call that is speaking ends it as `stopAll` does (`TextInterrupted 1`, the engine's `/stop`); on a call still waiting for the lock, it returns at once without being spoken; on an unknown or finished id, nothing happens.
- **Stop**: `stopAll()` ends the current `say` at once, including while the engine is still synthesizing: `say()` waits for the engine's reply on a thread and watches the stop flag meanwhile (every 20 ms), so a stop during synthesis tells the engine to abandon that say (`/stop` with the call's id, [tts-engine.md](../container/tts-engine.md)) and `say()` returns without the reply, interrupted, instead of after a synthesis that takes about 3 s for a long text on a GitHub runner (the cause of a flaky live test). The engine knows each say by the call's id (`/say` carries it), so a stop that reaches the engine before its say, or after its last item, cancels it too, and the engine then plays nothing and answers `stopped`, which `say()` ends on as interrupted. The stop flag is cleared when `say()` starts, not when the engine replies, so a stop before a `say` does not cut it. Bookmarks not yet reached are not raised. The engine's `/stop` cuts the audio (measured within about 0.1 s).
- **Tags** (`naoqi_sim_speech_core.parse`):
  - `\pau=N\` becomes a pause item; `\mrk=N\` and `\mrkpause=N\` become mark items.
  - `\rspd=N\` and `\vct=N\` set rate and pitch; `\rst\` resets both to 100.
  - `\vol`, `\emph`, `\bound`, `\readmode`, `\tn` are ignored.
  - Rate and pitch apply to the whole call (the value in force at the end of the text) and carry over to later calls, like NAOqi's.
- **Parameters**:
  - `setParameter("speed"|"defaultVoiceSpeed", N)` sets the rate (percent).
  - `setParameter("pitchShift", x)` sets the pitch (x times 100 when x < 10). The pitch is carried to the engine and ignored there: Piper has none ([tts-engine.md](../container/tts-engine.md), open questions), so `\vct` and `pitchShift` are no-ops that round-trip through `getParameter`.
  - `resetSpeed` sets the rate back to 100.
- **Language**: two lists, as on a NAO, which has one or two language packs installed out of the twenty-one NAOqi knows:
  - `getSupportedLanguages` answers NAOqi's own list (`naoqi_sim_speech_core.SUPPORTED_LANGUAGES`: Arabic, Brazilian, Chinese, Czech, Danish, Dutch, English, Finnish, French, German, Greek, Italian, Japanese, Korean, Norwegian, Polish, Portuguese, Russian, Spanish, Swedish, Turkish, as the 2.8 documentation's "Supported languages" page lists them for `ALTextToSpeech`; 2.1 is taken to be the same list, still to confirm on a robot), whatever is installed.
  - `getAvailableLanguages` answers the **installed** languages (`LANGUAGES`): the config's `speech.languages` ([config.md](../runtime/config.md)), which `NaoqiSim.start()` passes to the container as `NAOQI_SIM_LANGUAGES` (comma-separated NAOqi names; `English,French` when unset), in the config's order. Each has a voice in the engine ([tts-engine.md](../container/tts-engine.md), "Languages"): the config refuses one that has none. The language at boot (`getLanguage`) is the first installed.
  - `say(text, language)` switches language for that call only (2.1: explicit second binding; 2.8: varargs). `setLanguage` also emits `languageTTS` (2.8). `locale` answers the current language's locale (`en_US`, `fr_FR`, `pt_BR`, ...; `LOCALES`), as a NAO's does.
  - **A language that is not installed raises**, as on a NAO, where clients rely on the error to tell the user a language is missing: `setLanguage` raises a `RuntimeError` naming the language and the available ones, and the language and `languageTTS` stay as they were; `say(text, language)` raises the same way before anything is spoken (the core checks it before starting the call, so the error reaches the front's caller). The names are matched exactly, as `getAvailableLanguages` spells them. A supported language that is not installed (`Japanese`) raises like any other.
- **Fallback clock**: if the engine is unreachable, `say()` still blocks for 0.3 s per token and raises bookmarks on that clock, so behaviours keep running without sound.
- **Stubs**: `setVoice`, `loadVoicePreference`, `setLanguageDefaultVoice`, `enableNotifications`, `disableNotifications` and `sayToFile` are accepted and logged, with no effect. `getVoice` returns `"naoqisim"` (one voice per language, the engine's). 2.8 also has `_pause`, `_resume` and `reset`.
- **Diagnostics**: `whoami()` names the implementation. Calls are logged as JSON lines to `/home/nao/speech_almodule.jsonl` (2.1) or `/home/nao/speech_qiservice.jsonl` (2.8).
- **Measured end to end**:
  - 2.1: `say` blocked 4.74 s for 3.91 s of audio on the first call; `ALAnimatedSpeech` bookmarks arrived about 0.17 s after the engine's offsets (reply latency).
  - 2.8: `say` blocked 4.01 s for 3.69 s of audio.

## Open questions

1. **Missing methods.** `getLanguageEncoding` and `sayToFileAndPlay` are not implemented. (Closed: the Say box. It calls `id = tts.post.say(...)`, `tts.wait(id, 0)` and stops with `ALProxy('ALTextToSpeech', True).stop(id)`. Measured Oct 12, 2026: on 2.1 `post` and `wait` work but `stop(id)` is ignored (the sentence plays to its end); on 2.8, against the qi service, `post.say` blocks for the whole sentence and returns `-1`, then `wait` raises "Can't find method", so the Say box fails. The fix, decided Oct 12, 2026, is the C++ front above, which also carries 2.8's hidden signals.)
2. **Subtitles** are not built: they belong to the viewer ([viewer.md](../host/viewer.md), open questions). The robot hears its own speech, as a NAO does; no microphone gate ([audio-input.md](../host/audio-input.md), "The robot hears itself").
3. **Duration tolerance** against a NAO's own `say()` (proposed ±20% per sentence) is not agreed. The reference durations, measured on a real NAO 2.1 (2.1.4.13) on Oct 16, 2026 as `TextStarted 1` to `TextDone 1` at speed 100 with the robot's `naoenu` and `naofrf` voices: "Hello." 0.81 s; "Hello, I am a simulated NAO speaking through the engine container." 4.23 s; the live tests' long sentence ("This is a long sentence that will be interrupted by stop all before it finishes, and it goes on and on so that there is plenty of audio left to cut.") 8.17 s; "Bonjour, je suis un robot NAO et je mesure la durée de mes phrases." 4.52 s; "Volume check." 1.09 s. On the robot `say()` returns 2 to 5 ms after `TextDone 1`, and `TextStarted 1` comes 6 to 10 ms after the call. Through `ALAnimatedSpeech` standing (same day), "I am measuring how long my sentences take while I move my arms as I talk to you." takes 4.43 s with body language `disabled`, 4.57 s `random` and 5.11 s `contextual` (the speech itself 4.40, 4.44 and 4.99 s), and `EndOfAnimatedSpeech` follows `TextDone 1` by 40 to 80 ms.
4. **Word events**: `CurrentWord` and `PositionOfCurrentWord` are not raised in v1 (see [tts-engine.md](../container/tts-engine.md)). A real NAO 2.1 raises `PositionOfCurrentWord` (the 1-based character index of the word in the text) then `CurrentWord` as each word starts, 0.1 to 0.7 s apart, and resets both (`0`, `""`) with `CurrentSentence ""` after `TextDone 1` (measured Oct 16, 2026).
5. **The robot's sequence and timing**, measured on a real NAO 2.1 (2.1.4.13) on Oct 16, 2026, to compare with "Behaviour" above: per `say`, `Status [id, "enqueued"]`, then within 3 ms `TextDone 0`, `Status [id, "started"]` and `TextStarted 1` (their order varies), then `CurrentSentence text`; the words; `Status [id, "done"]` about 0.28 s **before** `TextDone 1`; then `CurrentBookMark 0`, `TextStarted 0` and the word resets. On `stopAll` from a client: `TextInterrupted 1` and `Status [id, "stopped"]` (not `"done"`) 0.24 s after the call, `TextDone 1` 0.15 s later, when `say()` returns. The Say box's calls, run inside the robot's NAOqi: `post.say` answers its task id in 9 ms (the id of the `Status` events, as here), `stop(id)` from a second proxy takes 47 ms, and the posted call's `wait(id, 0)` returns false (the call returned) when `TextDone 1` comes, 0.5 s after the stop. The `"stopped"` status and the gap between `"done"` and `TextDone` are the differences with ours; whether a client depends on them is not known.
