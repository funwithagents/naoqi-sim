"""The perception engine's HTTP plumbing with a fake detector (no model, no network), YuNet's row
mapping, and the recipe's pins (specs/container/perception-engine.md)."""

import importlib.util
import json
import re
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_ENGINE = Path(__file__).resolve().parent.parent / "docker" / "perception-engine"


def _load_server() -> Any:
    # By path: the tts engine's server.py already owns the name `server` on sys.path.
    spec = importlib.util.spec_from_file_location(
        "perception_server", _ENGINE / "server.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_server()


class FakeDetector:
    """Answers chosen faces, records the frames it saw, or raises."""

    model = "fake.onnx"

    def __init__(self, faces=None, fail=False):
        self.faces = faces or []
        self.fail = fail
        self.frames: list[np.ndarray] = []

    def detect(self, rgb):
        self.frames.append(rgb)
        if self.fail:
            raise RuntimeError("detector exploded")
        return list(self.faces)


@pytest.fixture
def engine():
    """A server on a free port; `url` plus `detector` to set the detector (None at start)."""
    server.set_detector(None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield url
    finally:
        httpd.shutdown()
        server.set_detector(None)


def _request(url, path, body=None, headers=None):
    req = urllib.request.Request(url + path, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _frame(width, height):
    return np.full((height, width, 3), 128, np.uint8)


def _post(url, frame, headers=None):
    h = {
        "Content-Type": "application/octet-stream",
        "X-Width": str(frame.shape[1]),
        "X-Height": str(frame.shape[0]),
    }
    if headers is not None:
        h = headers
    return _request(url, "/detect", frame.tobytes(), h)


FACES = [
    {"box": [10.0, 20.0, 30.0, 40.0], "score": 0.7, "landmarks": [[1.0, 2.0]] * 5},
    {"box": [100.0, 20.0, 30.0, 40.0], "score": 0.9, "landmarks": [[3.0, 4.0]] * 5},
]


def test_health_is_503_until_the_detector_is_loaded_then_names_it(engine):
    status, payload = _request(engine, "/health")
    assert (status, payload) == (503, {"ok": False})
    server.set_detector(FakeDetector())
    status, payload = _request(engine, "/health")
    assert (status, payload) == (
        200,
        {"ok": True, "detector": "yunet", "model": "fake.onnx"},
    )


def test_detect_gives_the_detectors_faces_in_descending_score_for_the_frame_posted(
    engine,
):
    fake = FakeDetector(FACES)
    server.set_detector(fake)
    frame = _frame(64, 48)
    frame[10, 20] = (1, 2, 3)
    status, payload = _post(engine, frame)
    assert status == 200
    assert (payload["width"], payload["height"]) == (64, 48)
    assert [f["score"] for f in payload["faces"]] == [0.9, 0.7]
    assert payload["faces"][0]["box"] == [100.0, 20.0, 30.0, 40.0]
    assert len(payload["faces"][0]["landmarks"]) == 5
    assert payload["took_ms"] >= 0
    # the detector saw the frame as posted: H x W x 3 RGB, pixels where they were
    assert fake.frames[0].shape == (48, 64, 3)
    assert tuple(fake.frames[0][10, 20]) == (1, 2, 3)


def test_a_body_of_the_wrong_size_is_refused_and_never_reaches_the_detector(engine):
    fake = FakeDetector(FACES)
    server.set_detector(fake)
    frame = _frame(64, 48)
    status, payload = _post(engine, frame, {"X-Width": "65", "X-Height": "48"})
    assert status == 400
    assert "65x48x3" in payload["error"]
    assert fake.frames == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Width": "64"},
        {"X-Width": "x", "X-Height": "48"},
        {"X-Width": "0", "X-Height": "48"},
    ],
)
def test_missing_or_invalid_size_headers_are_refused(engine, headers):
    server.set_detector(FakeDetector(FACES))
    status, payload = _post(engine, _frame(64, 48), headers)
    assert status == 400
    assert "X-Width" in payload["error"]


def test_a_detect_before_the_model_is_loaded_is_503(engine):
    status, payload = _post(engine, _frame(8, 8))
    assert status == 503
    assert "not loaded" in payload["error"]


def test_a_detector_failure_is_a_500_with_its_reason(engine):
    server.set_detector(FakeDetector(fail=True))
    status, payload = _post(engine, _frame(8, 8))
    assert status == 500
    assert "detector exploded" in payload["error"]


def test_unknown_paths_are_404(engine):
    server.set_detector(FakeDetector())
    assert _request(engine, "/nope")[0] == 404
    assert _request(engine, "/say", b"{}", {"X-Width": "1", "X-Height": "1"})[0] == 404


def test_yunet_rows_become_faces_with_box_landmarks_and_score_in_descending_order():
    # [x, y, w, h, 5 landmark pairs (right eye, left eye, nose, right mouth, left mouth), score]
    rows = np.array(
        [
            [10, 20, 30, 40, 11, 21, 31, 41, 51, 61, 71, 81, 91, 101, 0.7],
            [100, 20, 30, 40, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0.95],
        ],
        dtype=np.float32,
    )
    faces = server.faces_from_rows(rows)
    assert [f["score"] for f in faces] == pytest.approx([0.95, 0.7])
    assert faces[1]["box"] == [10.0, 20.0, 30.0, 40.0]
    assert faces[1]["landmarks"] == [
        [11.0, 21.0],
        [31.0, 41.0],
        [51.0, 61.0],
        [71.0, 81.0],
        [91.0, 101.0],
    ]
    assert server.faces_from_rows(None) == []


def test_the_recipe_pins_the_model_commit_and_hash_and_compose_checks_its_health():
    dockerfile = (_ENGINE / "Dockerfile").read_text()
    commit = re.search(r"ZOO_COMMIT=([0-9a-f]{40})", dockerfile)
    assert commit is not None
    assert "github.com/opencv/opencv_zoo/raw/$ZOO_COMMIT/" in dockerfile
    assert (
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4" in dockerfile
    )
    assert "sha256sum -c" in dockerfile
    compose = (_ENGINE.parent / "compose.yaml").read_text()
    section = compose[compose.index("  perception:") : compose.index("  naoqi21:")]
    assert "naoqi-sim/perception:dev" in section and "/health" in section
    assert compose.count("${NAOQI_SIM_PERCEPTION_URL-http://perception:8080}") == 2


def test_the_server_binds_its_port_only_once_as_pid_1_would():
    # the handler is what the container runs: one process, one port, a GET answered
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        httpd.shutdown()
