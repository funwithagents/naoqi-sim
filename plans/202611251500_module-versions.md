# Module versions

**Status:** Done

Implements `specs/container/service-replacement.md` ("Object model per version", `version()`): every module of ours answers `version()` as NAOqi's built-ins do. It leaves `ALSpeechRecognition._getVersion` as it is (the recognition engine's version, its own answer).

Measured first, on Nov 25, 2026: on 2.1 the built-ins and our C++ modules answer `'2.1.4'`, as a NAO does, and our ten Python `ALModule`s answered `'PythonModule'`; on 2.8 the built-ins and our C++ modules answer `'2.8'`, and our qi services had no `version()`. On 2.1 a Python `version` method replaces the generic's answer without a binding by hand.

## Scope

- `docker/naoqi/services/*/naoqi_sim_*_almodule.py` (8 files) — each `ALModule` class defines `version`, returning `ALProxy("ALMemory").version()`; the audio player's shell imports `ALProxy` for it
- `docker/naoqi/services/*/naoqi_sim_*_qiservice.py` (8 files) — each service class defines `version`, returning `_session.service("ALMemory").version()` (`_AsrCompiler1` and `_UserIdentification` included)
- `tests-e2e/test_modules_live.py` — every name in the entrypoint's `REPLACED` and `ADDED` lists, and `NaoqiSim`, answers the version's value
- `specs/container/service-replacement.md` — the `version()` row and paragraph, the corrected rule on the generics' names

## Steps

1. Add `version` to each Python shell's classes, per version as above.
2. Add the live test, reading the names from each version's entrypoint so a module added later is covered.
3. Update the spec.

## Verification

`uv run pytest tests-e2e/test_modules_live.py` on both versions (the images rebuild, since `docker/` changed), then the whole live tier, then lint, type check and the fast tier. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
