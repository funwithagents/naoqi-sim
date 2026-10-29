---
code:
  - docker/naoqi/services/perception-stubs/naoqi_sim_perception_stubs_core.py
  - docker/naoqi/services/perception-stubs/naoqi_sim_perception_stubs_almodule.py
  - docker/naoqi/services/perception-stubs/naoqi_sim_perception_stubs_qiservice.py
  - docker/naoqi/services/perception-stubs/naoqi_sim_perception_sources.cpp
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_perception_stubs_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_perception_live.py
---

# Perception stubs: the modules that depend on the people-perception library

**Status:** Implemented

Design settled Oct 29, 2026 (the survey in `spike/RESULTS.md`, "Face detection and people perception survey"); built by [plans/202610291800_face-detection-and-people-perception.md](../../plans/202610291800_face-detection-and-people-perception.md).

## Purpose

Replacing `ALPeoplePerception` ([people-perception.md](people-perception.md)) leaves the built-in's library out of NAOqi's boot, and with it the modules whose modularity processes chain to its `PeoplePerception_process`: they fail to load ("impossible to find the specified process", measured Oct 29, 2026) or, on 2.8, register and fail every call. The library also registers a hidden `_UserIdentification` object on 2.8, which the `life.usersession` package waits for silently, and `ALMood` and `ALRobotMood` wait on `ALUserSession` in turn. None of these modules ever produced anything on the desktop (their graph needs the robot's face engine, and they read no ALMemory key: a published population leaves them silent, measured), so what a NAO program can lose is only their **API**: a call that errors, a service that is not found, Autonomous Life's configurator skipping its awareness settings for want of `ALEngagementZones`.

This spec gives each of them an API-only stub, the kind the inventory analysis decided on Oct 13 to 14, 2026 for the modules the desktop suites lack: the documented methods and events, the settings kept and answered, the subscriptions listed, no detection and no event raised. With the stubs in place both images serve exactly the services of a normal boot (measured by diffing the service lists), Autonomous Life configures awareness, runs `solitary`, and on 2.8 opens a user session on a tracked person.

## Decided

### What is stubbed, per version

| Service | 2.1 | 2.8 | Own methods (beyond the extractor API) | Signals (2.8) |
| --- | --- | --- | --- | --- |
| `ALEngagementZones` | yes | yes | `setLimitAngle`/`getLimitAngle` (90°), `setFirstLimitDistance`/`getFirstLimitDistance` (1.5 m), `setSecondLimitDistance`/`getSecondLimitDistance` (2.5 m), `computeEngagementZone(x, y, z)` and `computeEngagementZone(x, y, z, cameraPose)` (0) | `limitAngleChanged(f)`, `firstLimitChanged(f)`, `secondLimitChanged(f)` |
| `ALGazeAnalysis` | yes | yes | `setFaceAnalysisEnabled`/`isFaceAnalysisEnabled`, `setTolerance`/`getTolerance` | |
| `ALSittingPeopleDetection` | yes | yes | `setSittingThreshold`/`getSittingThreshold` | |
| `ALWavingDetection` | no: a real NAO 2.1 has none ([naoqi-fidelity.md](../container/naoqi-fidelity.md)); dropped with the library, as the depth modules are | yes, until a NAO 6 says otherwise | `setMaxDistance`/`getMaxDistance`, `setMinSize`/`getMinSize` | |
| `ALFastPersonTracking` / `_ALFastPersonTracking` | public name, loads on its own: kept | hidden name: **kept, not stubbed** (below) | | |
| `ALFindPersonHead` / `_ALFindPersonHead` | kept | kept, not stubbed | | |
| `_UserIdentification` | absent on 2.1 | stubbed (below) | | its 11 properties |

- **The extractor API** is the one of [face-detection.md](face-detection.md): subscriptions kept and listed, `getCurrentPeriod` the smallest period, `pause`/`isPaused`, `isProcessing` false (nothing processes), `getEventList`/`getMemoryKeyList`/`getOutputNames` answering the documented names. What NAOqi calls on them, measured: Autonomous Life reads `ALEngagementZones.getFirstLimitDistance` when it configures awareness and `_ALFastPersonTracking.getDefaultPeriod` in `solitary`; nothing else.
- **Events** are declared (`getEventList`) and never raised; the keys never written. A client subscribing to `EngagementZones/PersonEnteredZone1` waits as it did on the desktop.
- **Settings round-trip**: each setter stores, each getter answers the last value, with the defaults above.

### The tracking processes: kept, with the sources they read (2.8)

2.8's `fastpersontracking` and `findpersonhead` libraries do not read the built-in people perception: their modularity programs (`fastpersontracking_process.mds`, `findpersonhead_process.mds`) take the top camera's image, the camera's pose and the person's last position, and output the nearest blob or the person's head. They failed to load only because they also read the segmentation settings (`Labeling_*`) of `peopleperception_sources.mds`, which the people library loads first and so went out with it ("impossible to find the specified source Labeling_Kernel", measured Oct 29, 2026). A stub is not enough for them: `ALBasicAwareness` starts tracking by setting the frequency of `FastPersonTracking_process` in `ALModularity` directly, which only the real library's process answers; without it the start fails, awareness's tracking state is left half-started and it ignores every later person until restarted (measured on 2.8 with the stubs: the head turned once, never again).

So they are kept as the suite ships them, and a small C++ autoload entry, `naoqi_sim_perception_sources` (`_NaoqiSimPerceptionSources`, in `perception-stubs/`), placed right after `modularityperception` (which registers `ALModularity`), loads `peopleperception_sources.mds` into `ALModularity` in its `init()` (`NAOQI_SIM_MODULARITY_PROGRAMS`), before the tracking libraries load. The 2.8 entrypoint checks `_ALFastPersonTracking` and `_ALFindPersonHead` answer (`KEPT`). On 2.1 the tracking libraries load on their own and nothing is needed. With them, awareness on 2.8 tracks person after person (the live tier's awareness and user-session tests, run after the others). What the processes compute on the desktop is not measured; the head turns through `ALTracker`'s `People` target, which reads the keys [people-perception.md](people-perception.md) writes.

### `_UserIdentification` (2.8)

The face-recognition user database behind `ALUserSession`: when awareness tracks a person, `_UserSessionManager` calls `match(ppid)` and expects the struct `(i[(Lfi)<RecognitionMatch,value,confidence,storage>])<RecognitionResult,status,matches>`; with `status` 1 and no match it calls `store(ppid, uid)` and opens a session on the new user (measured: "User 1 has been focused", `getFocusedUser() == 1`); with `status` 0 nothing happens. So this stub is typed and minimal rather than empty:

- `match(ppid) -> RecognitionResult`: `status` 1; `matches` empty for a person never stored, else `[(uid, 1.0, storage)]` for the uid stored for that person, so a person tracked again keeps their user. The `match(photo)` overload answers no match. The return type is declared with `qi.bind` (a plain list fails the manager's conversion, measured).
- `store(ppid, uid) -> int` records the user for the person and returns `0`, a success status (answering `uid` made the manager take it for a failure and store the person again as a new user, never focusing one, measured Oct 29, 2026); `remove(uid)`, `clear()`, `makePermanent(uid)`, `makeTemporary(uid)`, `isPermanent(uid)`, `isTemporary(uid)`, `getStoredUsers()` work on that in-memory store (temporary by default); `checkPhotoForIdentification(path)` answers 0.
- The eleven properties (`faceRecognitionThreshold`, `maxRetryRecognition`, `retryRecognitionDelay`, `enableImageFiltering`, the head angle and size limits, `filterNonFrontalFaces`, `filterCameraMovements`) are `qi.Property`s with plausible defaults.
- The store lives for the container's run: users are not persisted (`ALUserSession`'s own database persists its side in the package store, as on a robot).

### Mechanism

- **One generic stub per object model**, table-driven: `naoqi_sim_perception_stubs_core.py` holds the tables (per service: methods with arity and defaults, events, keys, settings, signals) and the `Extractor` bookkeeping; the 2.1 shell builds one `ALModule` class per stub from its table (methods generated with real argument lists, since an `ALModule` binds by argspec; the one-argument overloads bound with `BIND_PYTHON`), the 2.8 shell one qi service class per stub (overloads as one varargs method, the signals and properties declared on the instance). The survey's modules in `spike/perception_survey/` are the prototype.
- **Loaded** by the loader after the people module; the entrypoints leave the libraries out (`LEFT_OUT`: `sittingpeopledetection engagementzones gazeanalysis wavingdetection` on both versions) and check every stubbed name answers (`ADDED`) ([container.md](../container/container.md), "Entrypoint").
- **Listed**: `NaoqiSim/Perception/Stubs` holds the stubbed names ([status-service.md](../container/status-service.md)), so a client or a test tells a stub from a module that detects.
- Every call is logged as a JSON line (`/home/nao/perception_stubs.jsonl`): the stubs are also how the next caller's needs are learnt, as the survey learnt these.

### Python 2.7 rules met on the way

A function that `exec`s generated code may hold no generator expression with a free variable (the compiler refuses the `exec`; a list comprehension has no scope and is fine). A qi service's methods are read at `registerService`, so a method set on the class afterwards is not served.

## Open questions

0. **The modularity programs are text.** Found Oct 29, 2026 (and used for the tracking processes above): the modularity processes are defined by `.mds` programs the suites ship (`/opt/naoqi/share/naoqi/vision/mds/`, a `source`/`process`/`filter` language, `peopleperception_process.mds`, `fastpersontracking_process.mds`...), which `ALModularity.loadProgramFromFile` loads; the dependents' processes consume `PeoplePerception_process:population`. A program of naoqi-sim's defining a `PeoplePerception_process` from a settable `source` (an `Identity` filter) fed by `ALModularity.setData` from the population might let the dependents' own libraries load and run on it, in place of the stubs, if the `population` type can be given as an `ALValue`: a filter type to measure. Until then the stubs stand; this is the lever to try before writing real zones by hand.
1. **Real engagement zones.** `ALEngagementZones` is geometry over the population: the zone of each person from the two distances and the angle, `PeopleInZone1..3`, `PersonEnteredZone`/`PersonMovedAway`/`PersonApproached`, `computeEngagementZone` answering for a point. A client that uses the zone events, or Autonomous Life's zone conditions (which the desktop's launchpad lacks anyway), would justify it.
2. **Gaze, sitting, waving** stay stubs: a gaze estimate from the landmarks is conceivable, sitting and waving need bodies.
3. **A NAO 6's module set** (`ALWavingDetection`, the hidden trackers) is unmeasured: no 2.8 robot. The 2.8 stubs follow the desktop suite's set.
