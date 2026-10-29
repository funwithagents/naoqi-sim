---
code:
  - docker/naoqi/services/face-detection/naoqi_sim_face_detection_core.py
  - docker/naoqi/services/face-detection/naoqi_sim_face_detection_almodule.py
  - docker/naoqi/services/face-detection/naoqi_sim_face_detection_qiservice.py
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_face_detection_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_perception_live.py
---

# Face detection: ALFaceDetection

**Status:** Implemented

Design settled Oct 29, 2026 (the survey in `spike/RESULTS.md`, "Face detection and people perception survey"); built by [plans/202610291800_face-detection-and-people-perception.md](../../plans/202610291800_face-detection-and-people-perception.md).

## Purpose

A NAO detects faces: `ALFaceDetection` finds them in the top camera's frames and publishes `FaceDetected` in ALMemory, which the Face Detection and Face Tracker boxes, `ALTracker`'s `Face` target (through `_FaceConverter`) and any script subscribe to. Neither desktop suite ships the module (the face engine exists only in the robot image, [naoqi-fidelity.md](../container/naoqi-fidelity.md)), so until now a client got nothing from it on naoqi-sim. This module adds `ALFaceDetection` inside NAOqi, with a NAO's API and `FaceDetected` format, detecting for real on the frames `ALVideoDevice` serves (the render of a face prop, a webcam) through the perception engine ([perception-engine.md](../container/perception-engine.md)). It is the first of the two perception replacements decided Oct 29, 2026 ([_overview.md](../_overview.md), "Perception"); [people-perception.md](people-perception.md) builds the population on its faces.

The module replaces nothing: no built-in holds the name on either version, so it is added as `ALAudioDevice` is ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in"). It is Python 2.7 only: nobody stops it by task id, and its callers connect to nothing hidden (measured: `_FaceConverter` subscribes to the `FaceDetected` event; nothing calls the module at boot). The perception engine does the detection; this module owns the camera, the schedule, the geometry and the contract.

## Decided

### The contract (from the robot's inventory, `spike/robot-2.1.json`, and the 2.1 and 2.8 documentation)

- **Extractor API**, the generics every NAOqi extractor has: `subscribe(name, period, precision)` and `subscribe(name)`, `unsubscribe(name)`, `updatePeriod(name, period)`, `updatePrecision(name, precision)`, `getCurrentPeriod`, `getCurrentPrecision`, `getMyPeriod(name)`, `getMyPrecision(name)`, `getSubscribersInfo` (rows `[name, period, precision]`, as the robot answers them), `getOutputNames`, `getEventList`, `getMemoryKeyList`, `isPaused`, `isProcessing`, `pause(bool)`. On 2.1 the one-argument `subscribe` is a second binding (`BIND_PYTHON`); on 2.8 the overloads are one varargs method, since a qi service registers one signature per method name (measured: a fixed arity made 2.8's awareness fail its `subscribe(name)` and die).
- **The module's own methods**: `setActiveCamera(int) -> bool` and `getActiveCamera` (0 the top camera, 1 the bottom one; the detection follows), `setResolution(int) -> bool` and `getResolution` (kept and answered; the detection runs at VGA whatever it says, since the engine wants the pixels, [perception-engine.md](../container/perception-engine.md)), `setFrameRate(int) -> bool` and `getFrameRate`, `setParameter(name, value)`, `setTrackingEnabled(bool)`, `isTrackingEnabled`, `enableTracking(bool)`, `setRecognitionEnabled(bool)`, `isRecognitionEnabled`, `enableRecognition(bool)`, `setRecognitionConfidenceThreshold(float)`, `getRecognitionConfidenceThreshold`, and the recognition calls below. The hidden ones the robot has (`_getDetectionMode`, `_setDetectionMode`, `_isFaceAnalysisEnabled`, `_setFaceAnalysisEnabled`, `_run`) are accepted, kept and answered too.
- **Events and keys**: `FaceDetected` (the event and the key), also under `FaceDetection/FaceDetected` on 2.1 as the robot declares it. `getEventList` and `getMemoryKeyList` answer them.
- **`FaceDetected`'s value**, the documented format, both versions: `[TimeStamp, [FaceInfo..., Time_Filtered_Reco_Info], CameraPose_InTorsoFrame, CameraPose_InRobotFrame, Camera_Id]`, with `TimeStamp = [seconds, microseconds]` of the frame, one `FaceInfo = [ShapeInfo, ExtraInfo]` per face, `ShapeInfo = [0, alpha, beta, sizeX, sizeY]` (the face centre's angles and the face's angular size, radians, in the camera's frame, NAOqi's conventions), `ExtraInfo = [faceID, scoreReco, faceLabel, leftEyePoints, rightEyePoints, leftEyebrowPoints, rightEyebrowPoints, nosePoints, mouthPoints]`, `Time_Filtered_Reco_Info = []` (no recognition), the two camera poses the 6 floats of `ALMotion.getPosition(camera, frame, True)`, and `Camera_Id` the active camera.
  - `alpha`, `beta`, `sizeX`, `sizeY` come from NAOqi's own conversions, `ALVideoDevice.getAngularPositionFromImagePosition` and `getAngularSizeFromImageSize` on the face's box, so they carry a NAO's sign conventions without naoqi-sim choosing any.
  - The point lists have the documented lengths (the eyes 14 floats each, the eyebrows 14, the nose 6, the mouth 16, angles). The engine gives five landmarks (the eye centres, the nose tip, the mouth corners): those fill the eye centres, the nose's bottom centre and the mouth's left and right limits; the other points are placed from the box at the proportions of a face (open question 2). `faceID` is the face's track id, `scoreReco` 0.0, `faceLabel` `""`.
  - **No face**: on a NAO the key is an empty value and the event is raised with it once the faces are gone. The module raises `FaceDetected` with `[]` once, at the first processed frame without a face after frames with faces, and writes the empty value; frames with faces raise it with the value above, one per processed frame.
- **Recognition is a stub**, decided Oct 29, 2026: `learnFace(name)`, `reLearnFace(name)` and `importOldDatabase(name)` return `False` and learn nothing, `forgetPerson(name)` and `clearDatabase()` return `True`, `getLearnedFacesList` answers `[]`, `isRecognitionEnabled` follows its setter. A client that learns a face is told it failed, which is the truth; SFace is the candidate when it stops being one (open question 1).
- `whoami()` names the implementation, as the other replacements do.

### Detection: the engine, the schedule, the camera

- **The detector** (`Detector` in `naoqi_sim_face_detection_core.py`) runs while the module, or the people module, has subscribers and is not paused ([people-perception.md](people-perception.md) shares it): it subscribes to the active camera on `ALVideoDevice` (`subscribeCamera`, VGA, RGB, at its rate) through the in-process API, reads a frame with `getImageRemote` (measured 1.9 ms on 2.1 and 4.2 ms on 2.8 for VGA, the pixels as a `str`), posts it to the engine and keeps the faces it answers. It unsubscribes when the last subscriber leaves. The engine's reply, with the frame's timestamp and camera, is one **detection**, which the module turns into `FaceDetected` and the people module into its population.
- **Period**: the detector runs at the smallest period among the two modules' subscribers (`getCurrentPeriod`), never under 100 ms (10 Hz: a VGA frame is 921 KB over the Docker network and the engine takes a few milliseconds; at 5 Hz, awareness's 200 ms, the load is nothing). A subscriber with no period (`subscribe(name)`) gets the module's default, 500 ms, the documentation's figure. The schedule is a fixed one, a slot missed is skipped, as the video input does.
- **Camera**: `setActiveCamera` switches the subscription; the bottom camera works the same. What the camera serves is the video input's business ([video-input.md](../host/video-input.md)): a camera on `none` serves NAOqi's placeholder, in which there is no face.
- **Geometry** stays NAOqi's: the angles from `ALVideoDevice`'s conversions (above), the camera poses from `ALMotion`, both in-process calls under a millisecond (measured).
- **`pause(True)`** stops the processing and the events while keeping the subscriptions (`isPaused` true, `isProcessing` false), as on a NAO; a client that runs its own detector silences this one so, the rule of [naoqi-fidelity.md](../container/naoqi-fidelity.md) for the robot.
- **No engine** (`perception.enabled = false`, or the container down): every frame is a frame without faces; the module keeps its schedule and logs the engine's absence once.

### Object model, boot, diagnostics

- An `ALModule` on 2.1 (`naoqi_sim_face_detection_almodule.py`), a `@qi.multiThreaded()` qi service on 2.8 (`naoqi_sim_face_detection_qiservice.py`), both thin shells over `naoqi_sim_face_detection_core.py`, which the fast tier tests on the host with a fake `ALVideoDevice`, a fake engine and a fake memory, as the other cores ([service-replacement.md](../container/service-replacement.md), "Object model per version"). Loaded by the loader after the status module; `ADDED` names it, so the entrypoint checks it answers ([container.md](../container/container.md), "Entrypoint").
- Calls and detections are logged as JSON lines, `/home/nao/face_detection.jsonl`, as the speech module's are.

### As measured

Oct 29, 2026, same setup as [people-perception.md](people-perception.md) ("As measured"): a face prop gives `FaceDetected` with `alpha` and `beta` within 0.05 rad of what the top camera's pose predicts and `sizeY` within 25 % of the face's angular height, on both versions (the live tier's check); a prop at the camera's height straight ahead reads `beta` 0.00, one below it a positive `beta`, NAOqi's convention. The engine answers a VGA frame in about 20 ms (33 ms with the round trip, native on the host's architecture), well inside awareness's 200 ms.

## Open questions

1. **Recognition.** SFace in the engine, `learnFace` storing an embedding under the name, `faceLabel` and `scoreReco` filled, `Time_Filtered_Reco_Info` as documented. Deferred until a client needs it.
2. **The point lists.** The eye, eyebrow, nose and mouth points beyond the five landmarks are placed at a face's proportions from the box; a client that reads them gets plausible, not measured, points. A richer landmark model would fill them.
3. **The robot's cadence.** Whether a NAO raises `FaceDetected` once per processed frame, and `[]` once or at every empty frame, is to confirm on a real NAO 2.1 (`bobby`); the module follows the documentation meanwhile.
4. **`ALFaceTracker` (2.1)** ships in the suite but is not loaded; a real NAO 2.1 runs it on `FaceDetected`. Loading it is a one-line entrypoint change once a client wants it ([naoqi-fidelity.md](../container/naoqi-fidelity.md), open question 1).
