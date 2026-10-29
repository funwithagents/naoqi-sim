---
code:
  - docker/perception-engine/server.py
  - docker/perception-engine/Dockerfile
  - docker/compose.yaml
  - src/naoqi_sim/docker_images.py
  - src/naoqi_sim/stack.py
tests:
  - tests/test_perception_engine.py
  - tests/test_docker_images.py
  - tests/test_stack.py
  - tests-e2e/test_perception_live.py
---

# Perception engine container

**Status:** Implemented

Design settled Oct 29, 2026 (the survey in `spike/RESULTS.md`, "Face detection and people perception survey"); built by [plans/202610291800_face-detection-and-people-perception.md](../../plans/202610291800_face-detection-and-people-perception.md).

## Purpose

A small container that finds faces in the frames the NAOqi container sends it, and answers with boxes, landmarks and scores. It knows nothing about NAOqi: the `FaceDetected` format, the people-perception contract, the extractor API, angles and frames all stay in the override modules ([face-detection.md](../services/face-detection.md), [people-perception.md](../services/people-perception.md)). It is the perception counterpart of the speech engine ([tts-engine.md](tts-engine.md)), and its own container for the same reasons: the NAOqi images (Ubuntu 14.04 and 16.04, Python 2.7, amd64 emulation on Apple Silicon) rule out any current detector, and the host stays a set of dumb devices ([devices.md](../host/devices.md)).

## Decided

### Detector: OpenCV's YuNet

- **YuNet**, through `cv2.FaceDetectorYN` of `opencv-python-headless` (pinned), with the `face_detection_yunet_2023mar.onnx` model from `opencv/opencv_zoo` at a pinned commit, fetched at the image build and hash-pinned, as the voices are for speech. Nothing of it is in the repository: 230 KB of model would fit, but the rule is one: engines' models are fetched on the user's machine.
- **Licensing.** The library and the model are Apache-2.0, compatible with naoqi-sim's MIT and free of the GPL posture the `tts` container needs; keeping the two engines apart keeps it so ([_overview.md](../_overview.md), "Licensing").
- **Why YuNet.** CPU only, 2 to 5 ms a VGA frame on a laptop, five landmarks (the eye centres, the nose tip, the mouth corners) and a score, no runtime download, no GPU; and the smallest wheel set of the candidates. Measured Oct 29, 2026 on naoqi-viewer's four portraits at the size a face prop has in the cameras: every portrait found at VGA at 1, 2 and 3 m (scores 0.79 to 0.94), and at QVGA at 1 m; the tilted-down one missed at QVGA at 2 m, which is why the modules send VGA frames. MediaPipe (heavier wheels, awkward on arm64 Linux), dlib (a slow build) and the suite's own Haar cascades (OpenCV 2.4, no landmarks, false positives) were set aside.
- **Recognition** is not in the engine today. OpenCV's SFace (Apache-2.0, the companion of YuNet) is the candidate when `learnFace` stops being a stub ([face-detection.md](../services/face-detection.md), open questions).

### HTTP API (port 8080, standard-library `ThreadingHTTPServer`)

- `POST /detect`: the frame as raw RGB bytes (`Content-Type: application/octet-stream`), its size in the headers `X-Width` and `X-Height` (a body whose length is not `width × height × 3` is a 400). Reply: `{"width": W, "height": H, "faces": [{"box": [x, y, w, h], "score": s, "landmarks": [[x, y], [x, y], [x, y], [x, y], [x, y]]}, ...], "took_ms": t}`, pixels in the frame's coordinates, the landmarks in YuNet's order (right eye, left eye, nose tip, right mouth corner, left mouth corner, as seen in the image), faces in descending score. Detection runs at the frame's own size, with a score threshold of 0.6 and a non-maximum-suppression threshold of 0.3 (the engine's constants; a config knob waits for a need).
- `GET /health`: `{"ok": true, "detector": "yunet", "model": "<file>"}` with 200 once the model is loaded, 503 before (the healthcheck's probe).
- One detector instance, guarded by a lock: `FaceDetectorYN` is not thread-safe, and one frame at a time is what the NAOqi side sends anyway.

### Image and process

- `python:3.12-slim`, native architecture, `opencv-python-headless` and `numpy` pinned; the model fetched at build from the pinned commit of `opencv_zoo` (through `github.com/.../raw/<commit>/...`, which resolves the repository's Git LFS pointer where `raw.githubusercontent.com` serves the pointer itself), its SHA-256 checked. 455 MB (the OpenCV wheel and numpy; measured Oct 29, 2026).
- The server is the container's PID 1 and exits on `SIGTERM`, as the `tts` server does ([tts-engine.md](tts-engine.md), "Image and process").
- The compose service is `perception` (image `naoqi-sim/perception:dev`, container `naoqi-sim-perception`), with a healthcheck on `/health` (every 2 s, a short start period: loading the model takes well under a second). The NAOqi services reach it at `http://perception:8080` (`NAOQI_SIM_PERCEPTION_URL`) ([container.md](container.md), "Compose").
- **Built, verified and checked with the others**: `fetch_and_build_images` builds it with the version label and the recipes digest, the verification waits for it to be healthy, `check_images` requires it, and `NaoqiSim.start()` waits for it after the `tts` container ([api.md](../runtime/api.md), "Lifecycle", "Images"). CI's image archive carries it ([ci.md](../testing/ci.md)).
- **Off by config**: `perception.enabled = false` ([config.md](../runtime/config.md)) starts no `perception` container, and `start()` does not wait for one; the NAOqi side then reaches no engine, so `ALFaceDetection` finds nothing, as a NAO in the dark, and `NaoqiSim/Perception/Source` reads `none` ([status-service.md](status-service.md)).

### Failure behaviour

- A frame the detector cannot read (a wrong size, a decode error) is a 400 with the reason; an unexpected error a 500. The NAOqi side treats both as a frame without faces and logs once per run of failures.
- The engine unreachable (not started, still loading, crashed): the NAOqi side's call fails fast (a 2 s timeout), the frame counts as empty, and the modules keep running their schedules; they log the first failure and the recovery.

### As measured

Oct 29, 2026: the four portraits pasted at the size a face prop has at 1 m on a VGA frame are found with scores 0.89 to 0.94, five landmarks each, in about 20 ms (33 ms with the HTTP round trip); a body of the wrong length is a 400; `docker stop` ends it in 0.2 s. The image is 455 MB.

## Open questions

1. **Thresholds and scale.** The score and suppression thresholds, and whether a frame should be detected at a smaller scale to save time on a slow machine, are constants until a user needs a knob.
2. **Recognition.** SFace embeddings behind `POST /embed`, when `learnFace` becomes real.
3. **Other detectors.** The engine could later serve what a NAO's other vision modules detect (NAOmarks, barcodes, the red ball), one route each; today it serves faces only.
