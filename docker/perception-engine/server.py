"""naoqi-sim perception engine: OpenCV's YuNet face detector behind one HTTP endpoint, standard
library only besides numpy and cv2. It knows nothing about NAOqi (specs/container/perception-engine.md).

POST /detect  the frame as raw RGB bytes, its size in the headers X-Width and X-Height
          ->  {"width": W, "height": H, "took_ms": t,
               "faces": [{"box": [x, y, w, h], "score": s, "landmarks": [[x, y], ...5]}, ...]}
              pixels in the frame's coordinates, the faces in descending score, the landmarks in
              YuNet's order (right eye, left eye, nose tip, right mouth corner, left mouth corner,
              as seen in the image). A body that is not width*height*3 bytes, or a missing or
              invalid size header, is a 400; a detector failure a 500.
GET  /health  200 {"ok": true, "detector": "yunet", "model": <file>} once the model is loaded,
              503 {"ok": false} before.
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

MODEL = os.environ.get(
    "NAOQI_SIM_YUNET_MODEL", "/models/face_detection_yunet_2023mar.onnx"
)
SCORE_THRESHOLD = 0.6  # a face is kept above this score
NMS_THRESHOLD = 0.3  # overlapping candidates above this are merged
TOP_K = 50  # candidates kept before the suppression
DETECTOR = "yunet"
LANDMARKS = (
    5  # YuNet's: right eye, left eye, nose tip, right mouth corner, left mouth corner
)

_lock = threading.Lock()  # one detector, not thread-safe
_detector = None  # set once the model is loaded (`/health` answers 503 before)


class YuNetDetector:
    """cv2.FaceDetectorYN over the YuNet model: detect(rgb) gives the faces of one frame."""

    def __init__(self, model_path=MODEL):
        import cv2  # imported here so the HTTP plumbing is testable without OpenCV

        self.cv2 = cv2
        self.model = os.path.basename(model_path)
        self._size = (0, 0)
        self._yn = cv2.FaceDetectorYN.create(
            model_path, "", (320, 240), SCORE_THRESHOLD, NMS_THRESHOLD, TOP_K
        )

    def detect(self, rgb):
        """The faces of an (H, W, 3) uint8 RGB frame, as `faces_from_rows` lays them out."""
        height, width = rgb.shape[:2]
        if (width, height) != self._size:
            self._yn.setInputSize((width, height))
            self._size = (width, height)
        bgr = np.ascontiguousarray(rgb[..., ::-1])
        _, rows = self._yn.detect(bgr)
        return faces_from_rows(rows)


def faces_from_rows(rows):
    """YuNet's result rows ([x, y, w, h, 5 landmark pairs..., score]) as the reply's faces, in
    descending score; None (no face) is an empty list."""
    faces = []
    if rows is None:
        return faces
    for row in rows:
        values = [float(v) for v in row]
        faces.append(
            {
                "box": values[0:4],
                "score": values[4 + 2 * LANDMARKS],
                "landmarks": [
                    [values[4 + 2 * i], values[5 + 2 * i]] for i in range(LANDMARKS)
                ],
            }
        )
    faces.sort(key=lambda f: f["score"], reverse=True)
    return faces


def set_detector(detector):
    """The detector the handler uses (the real one at start, a fake in the tests); None unloads."""
    global _detector
    with _lock:
        _detector = detector


def detect(body, width, height):
    """The reply of POST /detect for a raw RGB body of width x height, or (status, error)."""
    expected = width * height * 3
    if len(body) != expected:
        return 400, {
            "error": f"body is {len(body)} bytes, not {width}x{height}x3 = {expected}"
        }
    frame = np.frombuffer(body, dtype=np.uint8).reshape((height, width, 3))
    t0 = time.perf_counter()
    with _lock:
        if _detector is None:
            return 503, {"error": "the detector is not loaded"}
        faces = sorted(_detector.detect(frame), key=lambda f: f["score"], reverse=True)
    return 200, {
        "width": width,
        "height": height,
        "faces": faces,
        "took_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


def health():
    with _lock:
        if _detector is None:
            return 503, {"ok": False}
        return 200, {"ok": True, "detector": DETECTOR, "model": _detector.model}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._reply(*health())
        else:
            self._reply(404, {"error": "unknown path"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        if self.path != "/detect":
            self._reply(404, {"error": "unknown path"})
            return
        try:
            width = int(self.headers["X-Width"])
            height = int(self.headers["X-Height"])
            if width <= 0 or height <= 0:
                raise ValueError("not positive")
        except (KeyError, TypeError, ValueError) as e:
            self._reply(
                400, {"error": f"X-Width and X-Height must be positive integers: {e}"}
            )
            return
        try:
            self._reply(*detect(body, width, height))
        except Exception as e:  # noqa: BLE001  (a detector failure: the caller gets its reason)
            self._reply(500, {"error": repr(e)})

    def log_message(self, fmt, *args):  # quieter
        pass


if __name__ == "__main__":
    # The server is the container's PID 1, to which the kernel applies no default signal action:
    # without this handler `docker stop` would wait its grace period and kill it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        set_detector(YuNetDetector(MODEL))
    except Exception as e:  # noqa: BLE001
        print(f"cannot load the face detection model {MODEL}: {e!r}", file=sys.stderr)
        sys.exit(1)
    print(f"perception engine ready: {DETECTOR}, {os.path.basename(MODEL)}", flush=True)
    while True:
        time.sleep(3600)
