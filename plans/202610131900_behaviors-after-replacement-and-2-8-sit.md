# Preloaded behaviors after the replacements, and 2.8's Sit

**Status:** Done

Implements [container.md](../specs/container/container.md) ("Entrypoint": `behaviormanager` among the 2.1 dependents; "Desktop NAOqi facts": 2.8's Sit) and [service-replacement.md](../specs/container/service-replacement.md) ("Replacing a built-in", step 1). Two differences from a NAO found by a client's live tests at `be69728`. On 2.1, every behavior `ALBehaviorManager` preloaded at boot whose box calls a replaced service failed its first run with "module destroyed" (`animations/Stand/Emotions/Positive/Happy_1` to `_3`); fixed. On 2.8, `ALRobotPosture` cannot reliably reach Sit; investigated, found to come from the suite's virtual robot, and documented.

## Scope

- `docker/naoqi/entrypoint-2.1.sh`: `behaviormanager` first in `LATE`, launched after our modules
- `tests/test_entrypoint.py`: the 2.1 sequence with `behaviormanager` first among the late launches
- `tests-e2e/test_audio_player_live.py`: `Happy_1` through `ALBehaviorManager` ends without error and its sound reaches the audio output
- `specs/container/container.md`: `behaviormanager` among the dependents and in `LATE`, the 2.1 and 2.8 `MODULES` (the audio player modules were missing); 2.8's Sit in "Desktop NAOqi facts"
- `specs/container/service-replacement.md`: step 1 of "Replacing a built-in" on 2.1
- this plan, `plans/_index.md`

## Steps

1. **2.1, reproduced:** `Happy_1`, `_2` and `_3` failed on their first run and worked on the second; `Happy_4` and the Sit ones have no sound box, or skip it while standing. `ALBehaviorManager` had preloaded 601 behaviors at boot, before the entrypoint `exit()`ed the built-in `ALAudioPlayer`. A Play Sound box makes `ALProxy('ALAudioPlayer')` in its constructor, so a preloaded box held the destroyed module, and a failed run unloaded it. Say boxes hold `ALTextToSpeech` the same way.
2. **The fix:** `behaviormanager` is deferred from the autoload file and launched first in `LATE`, before `animatedspeech` as in a NAO's autoload order. Measured after it: the four Happy behaviors run at once, and 78 behaviors are preloaded (the BodyTalk animations `ALAnimatedSpeech` preloads) instead of 601. A behavior first run costs no visible time (`Happy_2`: 1.8 s, as before).
3. **2.8, investigated:** `PostureManager: Perturbation during gotoPosture` in NAOqi's log. The posture manager reads inertial angles, and the 2.8 virtual robot has no inertial sensor (2.1's reads 0). The robot model files hold no sensor list. Inserting the inertial keys in ALMemory, turning off foot contact protection, and `_setUseAutoBalance(False)` and `_setUseAntiCollision(False)` changed nothing. The cause: 2.8's desktop suite has no DCM, so no inertial sensor. Documented in container.md as a known issue with its workaround.

## Verification

- Lint, format, types, the fast tier.
- Live, 2.1: `test_audio_player_live.py`, `test_modules_live.py`, `test_speech_live.py`, `test_status_live.py`: 28 passed, 2 skipped. 2.8: `test_audio_player_live.py`, `test_status_live.py`: 15 passed, 1 skipped.
