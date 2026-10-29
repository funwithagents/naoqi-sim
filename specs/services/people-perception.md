---
code:
  - docker/naoqi/services/people-perception/naoqi_sim_people_perception_core.py
  - docker/naoqi/services/people-perception/naoqi_sim_people_perception_almodule.py
  - docker/naoqi/services/people-perception/naoqi_sim_people_perception_qiservice.py
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_people_perception_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_perception_live.py
---

# People perception: ALPeoplePerception replacement

**Status:** Implemented

Design settled Oct 29, 2026 (the survey in `spike/RESULTS.md`, "Face detection and people perception survey"); built by [plans/202610291800_face-detection-and-people-perception.md](../../plans/202610291800_face-detection-and-people-perception.md).

## Purpose

A NAO's `ALPeoplePerception` turns what the cameras see into a population: people with ids, positions in the robot's frames and distances, published under `PeoplePerception/` in ALMemory, which `ALBasicAwareness` subscribes to and `ALTracker` reads to turn the head toward a person, and which Autonomous Life's user-session manager watches to open a session on the tracked human. Both desktop suites ship the module, but it runs on a modularity graph that nothing can feed without the robot's face engine: it writes an empty `PeopleList` once and never raises an event (measured Oct 29, 2026, with frames injected and awareness subscribed). The fake-population test of Oct 8 proved that the built-in awareness, tracker and, on 2.8, user session react to the published contract exactly as on a robot. This replacement publishes that contract from the faces [face-detection.md](face-detection.md) detects, so the built-ins work for real on naoqi-sim: a face prop in the scene, or a person in front of the webcam, becomes a person the robot looks at.

It **replaces** the built-in, in the autoload, as `ALTextToSpeech` is replaced ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in"): a module publishing beside the built-in was measured viable but pointless, since the built-in's dependents consume its graph, not ALMemory, and stay dead either way. Leaving the library out takes its dependents with it, so they are stubbed ([perception-stubs.md](perception-stubs.md)); with the stubs in place both versions serve exactly their baseline's services plus `ALFaceDetection`, and Autonomous Life runs as before.

## Decided

### The contract (from the robot's inventory and the fake-population test)

- **Extractor API**, as in [face-detection.md](face-detection.md) (the overload rule on 2.8 included). What NAOqi's own modules call, measured on both versions: awareness calls `subscribe(name, 30, 0.0)` on 2.1 and `subscribe(name)` on 2.8, then `updatePeriod(name, 200)`, and `unsubscribe(name)` when it stops; the tracker calls nothing (`_PeopleConverter` subscribes to `PeopleDetected`); nothing calls the module at boot.
- **Own methods**: `getMaximumDetectionRange`/`setMaximumDetectionRange(float)` (people beyond it are not published; the setter raises `MaximumDetectionRangeUpdated` and the signal), `getTimeBeforePersonDisappears`/`setTimeBeforePersonDisappears(float)`, `getTimeBeforeVisiblePersonDisappears`/`setTimeBeforeVisiblePersonDisappears(float)`, `isFastModeEnabled`/`setFastModeEnabled`, `isGraphicalDisplayEnabled`/`setGraphicalDisplayEnabled`, `isMovementDetectionEnabled`/`setMovementDetectionEnabled`, `isFaceDetectionEnabled`/`setFaceDetectionEnabled` (off, no people are detected: the faces are the only source), `getMinimumBodyHeight`/`setMinimumBodyHeight`, `getMaximumBodyHeight`/`setMaximumBodyHeight` (kept, not applied: a face gives no body), `resetPopulation()` (forgets everyone, raises `PopulationReset` and the signal). The hidden ones the robot has (`_getDetectionMode`, `_setDetectionMode`, the `_FaceRecognitionThreshold`, `_MaximumColorDistance` and `_TimeBeforeMTMPruning` pairs, `_getLTMContent`, `_matchInDatabase`, `_matchInDatabaseNoCreate`, `_matchInLTM`, `_storeInLTM`, `_removeFromLTM`, `_removeAllFromLTM`) are accepted, kept and answered with empty results.
- **Signals** (2.8, where a qi service can declare them): `justArrived(i)`, `justLeft(i)`, `populationReset()`, `maximumDetectionRangeChanged(f)`, fired with the events of the same name.
- **Keys**, written by the module, read by the tracker, the viewer's people display and clients: `PeoplePerception/PeopleList`, `VisiblePeopleList`, `NonVisiblePeopleList` (lists of ids), and per person `PeoplePerception/Person/<id>/PositionInTorsoFrame`, `PositionInRobotFrame`, `PositionInWorldFrame` (`[x, y, z]`, the head's position), `Distance`, `AnglesYawPitch`, `IsVisible`, `IsFaceDetected`, `NotSeenSince`, `PresentSince`, `RealHeight`. A person's keys are removed when the person leaves.
- **Events**: `PeoplePerception/JustArrived(id)` once per new person; `PopulationUpdated` and `PeopleDetected` at every processed detection, both with the documented value `[TimeStamp, [[id, distance, pitch, yaw], ...], CameraPose_InTorsoFrame, CameraPose_InRobotFrame, Camera_Id]`; `JustLeft(id)` when a person is forgotten; `PopulationReset`; `MaximumDetectionRangeUpdated(range)`. `RemovedPersonFromMemory` is declared, never raised. `getEventList` and `getMemoryKeyList` answer the documented lists.

### The population from the faces

- **One detection, two modules.** The face module's `Detector` ([face-detection.md](face-detection.md), "Detection") runs while either module has subscribers and is not paused, at the smallest period of both; this module registers as its consumer and gets each detection (the faces with their angles and sizes, the frame's timestamp, the camera poses). Its own `isProcessing` is true while it has subscribers, is not paused and the detector runs.
- **A face is a person.** Each face of a detection is matched to a known person by the distance between its head's world position and the person's last one (the nearest within `MATCH_DISTANCE`, 0.35 m; in the world frame, so a head turning between two frames, which moves every face's angles, keeps the people: matching by angles gave a second id to a person while awareness turned the head, measured Oct 29, 2026); an unmatched face is a new person with the next id (increasing integers, never reused during a run, as a NAO's ids are not). A person not seen for `TimeBeforeVisiblePersonDisappears` (default 2.0 s) moves from `VisiblePeopleList` to `NonVisiblePeopleList` with `IsVisible` false and `NotSeenSince` counting; one not seen for `TimeBeforePersonDisappears` (default 10.0 s) is forgotten: keys removed, `JustLeft`. The defaults are the built-in's, read from the suite's own `peopleperception_sources.mds` (`Tracker_TimeBeforeVisiblePersonDisappears`, `Tracker_TimeBeforeNonVisiblePersonDisappears`, `NearPopulation_MaximumDetectionRange`).
- **Distance from the face's angular height**: `distance = HEAD_HEIGHT / (2 tan(sizeY / 2))`, with `HEAD_HEIGHT` the real height of what the detector boxes, 0.20 m (a face from the brow to the chin and a little more, the box YuNet draws). A NAO has no depth camera either and estimates from the face's size the same way. The naoqi-viewer face props show their face life-size for this ([props.md](../host/props.md), "Where to put things"), so a prop at 1 m reads about 1 m, as a person at 1 m in front of a webcam does.
- **Positions**: the head is at `distance` along the ray of the face's angles in the camera's frame (`ALVideoDevice`'s angles, so NAOqi's signs); the point is moved into the torso, robot and world frames with `ALMotion.getTransform(camera, FRAME, True)` at the detection (in-process, under a millisecond). `Distance` is the distance from the robot's frame origin to the head, `AnglesYawPitch` the head's yaw and pitch in the robot frame, `RealHeight` the head's height above the floor plus 0.12 m (the top of the head), as a NAO fills it for a standing person.
- **Range**: a person farther than `MaximumDetectionRange` (default 3.5 m, the built-in's) is not published.
- **Rate**: everything above runs inside the detector's cycle, so the population follows the faces at the subscribers' period, 5 Hz for awareness, and the keys are written before the events are raised, as the tracker expects.

### The dependents

Leaving `peopleperception` out of the autoload copy removes, on both versions, the modules whose modularity processes read the built-in's population: `ALSittingPeopleDetection`, `ALEngagementZones`, `ALGazeAnalysis`, `ALWavingDetection`; and on 2.8 the hidden `_UserIdentification` the library registers too, which `ALUserSession`, then `ALMood` and `ALRobotMood` wait for (measured Oct 29, 2026). Their libraries are left out with it and [perception-stubs.md](perception-stubs.md) serves their names, so a client's and NAOqi's own calls on them answer, Autonomous Life configures itself without error and user sessions open. 2.8's `_ALFastPersonTracking` and `_ALFindPersonHead` read only the shared segmentation settings, which naoqi-sim loads in the library's place, so they stay the suite's own (perception-stubs.md, "The tracking processes").

### Object model, boot, diagnostics

- An `ALModule` on 2.1, a `@qi.multiThreaded()` qi service on 2.8 with the four signals, both shells over `naoqi_sim_people_perception_core.py`, which the fast tier tests with fake detections, a fake `ALMotion` and a fake memory. Loaded by the loader after the face module (it imports the face core to register with its detector); the entrypoints leave `peopleperception` out (`LEFT_OUT`) and check the name answers (`REPLACED`), as for the speech library ([container.md](../container/container.md), "Entrypoint").
- Calls and population changes are logged as JSON lines, `/home/nao/people_perception.jsonl`.

### In the live tier

With a face prop spawned in the robot's frame ([props.md](../host/props.md)): the population has one person within a second, `PositionInWorldFrame` within 0.25 m of the world position `spawn` returned, `JustArrived` once; the viewer's people display puts a marker on the portrait with no client; `despawn` makes the person invisible after 2 s and gives `JustLeft` after `TimeBeforePersonDisappears`; and awareness, started on either version, turns the head toward a face spawned at a yaw and ends with it near the top camera's axis: the closed loop the project was missing. On 2.8, Autonomous Life in `solitary` opens a user session on the tracked person.

### As measured

Oct 29, 2026, OrbStack on Apple Silicon, the headless viewer rendering both cameras, naoqi-viewer's life-size face props:

- A face prop 1 m ahead at head height becomes a person within a second, at 0.03 m (2.8) and 0.07 m (2.1) of the prop's world position; its distance reads 1.02 m (2.8) and 1.07 m (2.1). Distances at 2 m and beyond are not measured yet.
- **A face cut by the frame's edge reads too far**: a prop 0.3 m above the head (0.37 rad up, at the top edge of the 2.1 top camera's view) gave a person at 2.09 m, its box shortened by the edge. A NAO's own estimate has the same weakness; a client that cares checks that the face lies inside the frame.
- The population follows awareness's 200 ms: 40 `PopulationUpdated` in 8 s on both versions. The awareness loop closes: a face spawned at a yaw of 0.4 rad has the head at 0.36 to 0.40 rad within a second, on both versions; on 2.8, life in `solitary` opens a user session on it.

## Open questions

1. **Several faces close together.** The angular match may swap two faces crossing each other; a NAO's tracker does better with its own filtering. Fine for tests with distinct props; a client with crowds will tell.
2. **`HEAD_HEIGHT`** (0.20 m) is to check with a webcam measurement on real faces. The other defaults are the built-in's (above); a real NAO's getters would confirm them.
3. **Movement detection** (`setMovementDetectionEnabled`) is kept, not applied: `ALMovementDetection` stays the built-in, which detects nothing on the desktop, and awareness's movement stimulus stays silent. A replacement from frame differences is a later concept.
4. **Engagement zones from the population** would make `ALEngagementZones` real: a few lines of geometry over these keys ([perception-stubs.md](perception-stubs.md), open question 1).
