---
code:
  - docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_core.py
  - docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_grammar.py
  - docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_almodule.py
  - docker/naoqi/services/speech-recognition/naoqi_sim_speech_recognition_qiservice.py
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py
  - docker/naoqi/services/status-service/naoqi_sim_status_core.py
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_speech_recognition_core.py
  - tests/test_speech_recognition_grammar.py
  - tests/test_audio_device_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_speech_recognition_live.py
---

# Speech recognition: ALSpeechRecognition

**Status:** Implemented

Design settled Nov 21, 2026, from a survey with recording modules on both images, a throwaway engine on real audio, and measurements on a real NAO 2.1 (2.1.4.13, French). Built by [plans/202611211500_speech-recognition.md](../../plans/202611211500_speech-recognition.md).

## Purpose

A NAO recognises speech: `ALSpeechRecognition` listens to the microphones for the phrases it was given and publishes `WordRecognized`, which scripts, the Speech Reco box and `ALDialog` build on. Neither desktop suite has the module, so until now a client heard nothing from it on naoqi-sim and `ALDialog` only answered `forceInput`. This module adds `ALSpeechRecognition` inside NAOqi with a NAO's API, statuses and events, recognising for real on what the simulated microphones hear (the fake room a test plays sounds into, the host microphone, the robot's own voice) through the speech recognition engine ([asr-engine.md](../container/asr-engine.md)). It reverses the overview's line that speech recognition is the clients' job, as face detection and people perception did for perception.

It serves two kinds of callers, and both are part of the contract:

- **A script or a box**: `setVocabulary`, `subscribe`, the `WordRecognized` event.
- **`ALDialog`**, hand-loaded topics and the main dialog: the dialog adopts a module of this name on both versions (measured), gives it its grammar, and takes its results. This is what makes a dialog answer speech on naoqi-sim.

The module replaces nothing: no built-in holds the name. The engine does the acoustic work; this module owns the microphones' audio, the phrases, the statuses, the bips, the LEDs and the dialog's contract.

## Decided

### Languages

- **English and French**, the two models the engine has ([asr-engine.md](../container/asr-engine.md)). `getAvailableLanguages()` answers those of the two that are among the installed languages ([config.md](../runtime/config.md), `robot.available_languages`), in NAOqi's names; `getLanguage()` starts as the robot's language (`robot.language`). `setLanguage` to any other raises "This engine does not support the following language: <name>" and keeps the language, as measured on the robot. With neither installed the module answers its API and recognises nothing.

### What it listens for

One list of phrases at a time, built from whichever caller set it last:

- **A vocabulary**: `setVocabulary(phrases, wordSpotting)` and `setWordListAsVocabulary(phrases)` (no word spotting). The grammar's name in `WordRecognizedAndGrammar` is `modifiable_grammar`, or `modifiable_grammar_wordspotting` with word spotting (measured). Changing the vocabulary while listening raises "You need to stop or pause the ASR engine to be able to make this call.", as on the robot.
- **The 2.1 dialog's grammar.** The 2.1 dialog writes its grammar as text and calls `compile(bnf, lcf, language)`, then `addContext(lcf, name)`, `activateRule(name, rule)`, `deactivateRule`, `deactivateAllRules`, `addWordListToSlot(name, slot, words)`, `removeContext`, `removeAllContext` (measured). The module reads the grammar text (`#BNF+EMV1.1`: rules with alternatives, groups, optional parts, references, `!repeat`, `!slot`, `!activatable`, `<...>`), keeps one grammar per context, and expands the rules that are active to phrases: slots filled with their word lists, a repeat taken once, `<...>` as the word-spotting marker. `compile` also writes the `.lcf` file (empty) so the dialog finds the name it expects. The expansion is capped (1,000 alternatives per position, 3,000 phrases per alternative of the start rule, shortest first). A real NAO 2.1's full dialog content (its `BNFwelcomeEnglish.bnf` and `BNFwelcomeFrench.bnf`, 47 topics active) expands to 12,104 and 15,417 phrases in 20 ms each (measured).
- **The 2.8 dialog's grammar.** The 2.8 dialog works as the 2.1 one, through a second service:
  - It writes the same grammar text, `BNF<bundle><Language>.bnf` in its data folder (`BNFwelcomeEnglish.bnf` for the main dialog), and gives it to the service `_AsrCompiler1`: `compile(bnf, lcf, language)`. Then, on the recognition: `createContext(lcf, name)`, `activateRule(name, "start")`, `activateRule(name, "<topic> trig")`, the context sets, and `addWordListToSlot(name, slot, words)` for the lists it keeps itself (measured). `_AsrCompiler1` shares the recognition's state: its `compile` is the one above, and `createContext` is `addContext`.
  - **The lists the dialog fills are slots**, as on 2.1. With an application installed, the dialog calls `addWordListToSlot("BNFwelcomeEnglish", "app-trigger", [the applications' trigger sentences])` and `"app-name"` with their names (measured): saying an application's trigger sentence starts it, with nothing about applications in this module.
  - **The dialog writes a grammar only for the languages chosen through `ALDialog.setLanguage`**, and writes it at its next preload (measured: `Dialog.language: New language detected` at the call, then, at the preload, `Using file …/BNFwelcomeEnglish.bnf for bundle welcome` and `Compiling in new ASR module`). A language it already speaks is not a choice ("Set language to same language"). On a NAO 6 the settings page makes that choice when its user picks a language: `setLanguage` on `ALTextToSpeech`, `ALSpeechRecognition`, then `ALDialog`. The 2.8 entrypoint does the same once NAOqi is up, for each installed language in turn, the robot's own (the first) last ([container.md](../container/container.md), "Entrypoint"), so the dialog has a grammar in every installed language the recognition has. A language without a model in the engine (`getAvailableLanguages` does not list it) is not chosen, on any of the three: it stays a language the robot can speak when asked.
  - **Without that choice the dialog names a compiled file it never asked for** (`createContext(".../.lcf", "")`, and `BNFwelcomeEnglish.lcf does not exist` in its log): the context exists and holds nothing to listen for, which the module logs.
  - The preload happens when Autonomous Life is switched on, or at `_runMain()`; the sim boots with Life off ([autonomous-life.md](../container/autonomous-life.md)), so the languages are chosen before it.
  - Measured with a NAO 6's dialog content (34 packages: 68 topics loaded, 60 activated): the two grammars written and compiled in a second at the preload, 12,421 phrases listened for (709 more the engine has no words for), an application's trigger sentence said in the room recognised 1.8 s after it starts, the application started.

### Listening: statuses, events, timing

The sequence measured on the robot, which the module reproduces with its own delays:

| Moment | What the module does |
|---|---|
| Listening starts (`subscribe`, `pause(False)`, the dialog's rules active) | the begin bip, then `ALSpeechRecognition/Status` `ListenOn`, `ALSpeechRecognition/IsRunning` true, `ALSpeechRecognition/ActiveListening` true |
| Speech starts | `SpeechDetected` 1, `Status` `SpeechDetected` |
| Speech ends | `SpeechDetected` 0, `Status` `ListenOff`, the end bip, `ActiveListening` false |
| A phrase was recognised | `WordRecognizedAndGrammar` `[phrase, confidence, grammar]`, `WordRecognized` `[phrase, confidence]`, `LastWordRecognized`, `RecoLatency` (ms), then `Status` `EndOfProcess` and `SpeechRecognition/endOfProcess` 1 |
| Nothing was recognised | `RecoLatency`, `Status` `EndOfProcess`, `SpeechRecognition/endOfProcess` 1: no word event |
| Then | the begin bip, `Status` `ListenOn`, `ActiveListening` true: it listens again by itself |
| Listening stops (`unsubscribe` of the last subscriber, `pause(True)`) | `SpeechDetected` 0; on `unsubscribe` also `RecoLatency` 0, `NoiseRecognized` 0, `WordRecognized` `["", -3.0]`, `WordRecognizedAndGrammar` `["", -3.0, ""]`; `Status` `Stop` then `ListenOff`, the end bip, `ActiveListening` false, and `IsRunning` false on `unsubscribe` |

- **When it listens.** While it has a subscriber and is not paused (the extractor methods `getSubscribersInfo`, `getCurrentPeriod`, `getMyPeriod` and the others answer as every NAOqi extractor's; a subscriber's period is 30 unless given, as the robot lists them). **The dialog subscribes through ALMemory**: the module declares its events with itself as their extractor, so when a module subscribes to one of them, ALMemory calls its `subscribe(<module><event>, period, precision)`. The dialog appears as `ALDialogWordRecognized` (30, 0.0), as on the robot. The 2.1 dialog subscribes when a script subscribes the dialog (measured on the robot and the sim), `ALAnimatedSpeech`'s own subscription to `WordRecognized` at boot does not (measured on both). **The 2.8 dialog subscribes from boot**, so on 2.8 the module listens from boot, with no phrase until a topic is activated, and a script pauses it before `setVocabulary`, which is what the robot's error asks for (measured on the sim; no NAO 6 at hand).
- **Word spotting.** A phrase found inside other speech is published as `<...> phrase <...>`, the markers on both sides whatever the phrase's place (measured).
- **The value when nothing is listening** is `["", -3.0]`: a reset, not a rejection.
- **Confidence** is the engine's, between 0 and 1; a caller filters as on a robot (the dialog at 0.5 on 2.1 and 0.48 on 2.8). It is not a robot's scale, by decision: the robot gives 0.55 to 0.7 for a right phrase and returns a wrong one at 0.25 to 0.3 for unknown speech, where naoqi-sim returns no word.
- **With the bips on, each step waits for its bip** (measured: 150 ms from `subscribe` to its return against 25 ms without, 220 ms from the end of speech to the word against 40 ms).
- **The robot's own voice is heard**, on both versions, as on the robot: nothing mutes the module while `ALTextToSpeech` speaks (measured on the robot: a `say` during a subscription is recognised when its words are in the vocabulary, with the usual statuses). A script that does not want it pauses the module or unsubscribes while it speaks, as on a NAO.
- **A dialog's answer is not heard, because the module is not listening then**: when a result is ready the module has already left `ListenOn`, it hands the result to the dialog, and the dialog's `endOfUtteranceCallback` returns only once the answer has been said (measured on both versions: 4.6 s for a long answer, 0.9 s for a one-word one, at once when nothing matches). The module listens again when the callback returns, which is the robot's sequence (measured: `EndOfProcess` through the whole answer, `ListenOn` at its end). So the audio that arrives between the end of an utterance and the next `ListenOn` is discarded, never kept for later.
- **Its own bips** are not given to the engine: audio is taken from the end of the begin bip.

### The audio

The front microphone at 16 kHz, from our `ALAudioDevice` ([audio-device.md](audio-device.md)), taken inside the process: the device's core hands the module each buffer of that format while it listens, with no qi call per buffer. So whatever the audio input serves reaches the recognition ([audio-input.md](../host/audio-input.md)). The module posts each buffer (85 ms) to the engine and reads its answer; with no audio source nothing is detected.

### The dialog's contract

- **Results go to the dialog through its two callbacks**, `ALDialog.wordsRecognizedCallback([phrase, confidence, grammar], wordCount)` then `ALDialog.endOfUtteranceCallback()`, whenever the list being listened for is a dialog's; the public events are raised as well. Raising `WordRecognized` alone does not reach the dialog (measured).
- **Every method the dialog may call is answered**, since a missing one fails without a word and the dialog gives up (measured: the 2.8 main dialog never started without `_connectRemote`; a 2.1 dialog application failed to load without `_getVersion`). The module answers the whole method list of a robot's module, the hidden ones included: on both versions `_enableAudioLogging`, `_enableFreeSpeechToText`, `_disableFreeSpeechToText`, `_isFreeSpeechToTextAvailable` (false), `_remoteConsumptionOk` (0), `_getVersion` (`"4.5"`, a NAO 2.1.4.13's answer, not NAOqi's version; 2.8 unmeasured, the same answer), `_silentNextBipOn`, `_silentNextBipOff`, `_setDefaultLanguage`, `_enableRealTimeThread`, `pushContexts`, `popContexts`, `setContextParam`, `getContextParam`, `saveContextSet`, `loadContextSet`, `eraseContextSet`, `loadVocabulary`, `removeWordListFromSlot`, `getRules`; on 2.8 also `createContext`, `deleteContext`, `getContexts`, `createContextSet`, `addContextSet`, `addContextToSet`, `removeContextFromSet`, `removeContextSet`, `deleteAllContextSets`, `getContextSets`, `activateAllRules`, `_connectRemote`, `_disconnectRemote`, `_enableBeamformer`, `_disableBeamformer`, `_beamformerEnabled`, and the six feedback methods below. Those with nothing to do keep their arguments and answer.
- **2.8's `_AsrCompiler1`**: a second service the 2.8 dialog waits for and gives its grammar to, with `init`, `compile(bnf, lcf, language)` and `destroy` ("What it listens for").
- **No second pass.** A robot's 2.1 main dialog asks for a second recognition, from a statistical model, when the first is under its threshold. The module gives none, and the dialog then treats the utterance as not understood (measured).
- **`getParameter`/`setParameter`**: `Sensitivity` (0.5) and, per context, `AccuracyRatio` (1.0) are kept and answered; `NbHypotheses` is accepted on 2.8, where the dialog sets it; any other name raises "This engine does not support <name> setting.", as measured.

### Bips and LEDs

- **The bips are our own**: two short tones the module plays through our `ALAudioPlayer` ([audio-player.md](audio-player.md)), a rising one (900 to 1,500 Hz) to begin and a falling one to end, 110 ms each. The microphones hear them: the audio of the 0.35 s after listening starts is not listened to (measured: no false detection). A robot plays `begin_reco` and `end_reco` from its sound set, which is Aldebaran's and in no public image. `setAudioExpression(False)` silences them, `getAudioExpression()` answers.
- **The LEDs follow the default behaviour only**, by decision: while listening the eyes go blue and turn (`ALLeds.rotateEyes`, 0.8 s a turn) and the ears turn; a recognition flashes the eyes green; when listening stops the eyes are white and the ears on. `setVisualExpression(False)` switches this off and `True` on; `setVisualExpressionMode` is accepted and treats any mode other than 0 as on.
- **On 2.1 the module plays the bips and drives the LEDs itself**, around each listening, as the robot does.
- **On 2.8 it does neither by itself**: a NAO 6's feedback comes from its signs-and-feedback application, which calls the module's hidden `_playBipStart`, `_playBipStop`, `_startEyesRotation`, `_stopEyesRotation`, `_startEarsRotation`, `_stopEarsRotation`. The module offers those six, doing the same bips and turns, so the feedback appears when that application is installed (open question 2).

### Without an engine

`speech_recognition.enabled = false` ([config.md](../runtime/config.md)) or the engine down: the module answers its whole API, the statuses follow `subscribe` and `pause` as above, and nothing is ever detected, as a NAO in a silent room. `ALDialog` then works as it did before, through `forceInput`. `NaoqiSim/SpeechRecognition/Source` reads `engine` or `none` ([status-service.md](../container/status-service.md)).

### Object model, boot, diagnostics

- An `ALModule` on 2.1 (`naoqi_sim_speech_recognition_almodule.py`), a `@qi.multiThreaded()` qi service on 2.8 (`naoqi_sim_speech_recognition_qiservice.py`, which also registers `_AsrCompiler1`), thin shells over `naoqi_sim_speech_recognition_core.py` (the listening, the statuses, the engine client) and `naoqi_sim_speech_recognition_grammar.py` (the dialog's grammar reader and the phrase expansion), both tested by the fast tier on the host with fakes ([service-replacement.md](../container/service-replacement.md), "Object model per version").
- **2.1 binds its hidden methods by hand**: the Python `ALModule` binds no method whose name starts with `_` (measured), so the shell binds each one itself.
- **Loaded first**, before the dialog looks for the name; `ADDED` names it, so the entrypoint checks it answers ([container.md](../container/container.md), "Entrypoint"). No C++ front: nobody stops it by task id.
- Calls, phrase lists (their sizes) and results are logged as JSON lines, `/home/nao/speech_recognition.jsonl`.

### Tests

- **Fast tier**: the grammar reader and the expansion on grammars of our own; the status and event sequences against a fake engine, a fake memory and a fake clock (a recognition, a rejection, word spotting, `pause`, `unsubscribe`, the vocabulary refused while listening, the dialog's callbacks, the audio of a dialog's answer discarded); the method lists per version.
- **Live tier**, both versions, the sentences played into the fake room from committed WAV files (`tests-e2e/speech/`: a person's voice recorded through a NAO's front microphone, fan noise included, `record.py` next to them to record again): a vocabulary alone (the word, its grammar, the status sequence, `LastWordRecognized`); a sentence outside the vocabulary (no word); word spotting; French, and a language without a model refused; the vocabulary refused while listening; `pause`; `unsubscribe` (the reset on 2.1, the dialog's subscription kept on 2.8); the bips on 2.1 and none with the audio expression off; **a hand-loaded dialog topic** (`loadTopic`, `activateTopic`, `ALDialog.subscribe`) answering a spoken sentence, the robot's answer not listened to; every method the dialog calls there, `_AsrCompiler1` on 2.8; the engine named in the status.
- The main dialog under autonomous life is not in this tier yet: it needs life's own pieces (open question 3).

### As measured

Nov 21, 2026. On the robot: the sequence, delays, values and error texts above. On both images with a recording module: the dialog's calls, the callbacks, the methods whose absence stops it. On real audio through a throwaway engine: "what can you do" recognised 3 times out of 3 and answered by the 2.8 main dialog, a sentence outside it rejected 2 out of 2; on 2.1, a robot's full dialog content installed, "hello" and an application's trigger sentence recognised and acted on.

Nov 21, 2026, the module built, on both versions, by hand: our speech engine's English and French sentences recognised at confidence 1.0 about 0.25 s after their end, a sentence outside the vocabulary rejected, word spotting marked, `subscribe` returning after `ListenOn` (0.2 s on 2.1 with the bip, 0.02 s on 2.8); a hand-loaded topic answering both its sentences on both versions, listening again only once each answer was said.

## Open questions

1. **More languages.** The engine has models for most of NAOqi's languages; they would be fetched into a volume as the speech voices are. Deferred until a client needs one.
2. **2.8's feedback.** Whether a NAO 6 gives no bip and no LED animation on a plain `subscribe` is judged from its public image, not measured (no NAO 6 at hand), and its signs-and-feedback application is not installed in the image yet: that belongs to the autonomous-life work.
3. **The main dialog under autonomous life** (a person in zone 1, life's dialog application) and its live test, with a dialog package of our own: the next work, on life.
4. **The sound set's bips.** Playing `begin_reco` and `end_reco` when the user has installed the robot's sound set.
5. **A single chosen language that is the dialog's own at boot** (English alone, or English with languages the recognition does not have): choosing it changes nothing for the dialog, so it writes no grammar. Not handled: the default config has English and French.
6. **`loadVocabulary(file)` and the context sets' files**: answered, doing nothing.
7. **The speech service's `synchroTTS` signal.** A robot's speech service has this hidden signal and its speech recognition listens to it; what it changes was not measured (a plain `say` during a subscription is heard in full on the robot). Ours declares the signal on 2.8 and never fires it ([speech.md](speech.md)); to revisit if a caller shows a difference.
