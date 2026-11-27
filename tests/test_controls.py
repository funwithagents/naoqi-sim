"""The controls server over HTTP, with the real touch input and video input on fake NAOqi
services: what each request does to the devices, what `GET /api/state` shows, the refusals, the
holds released at stop, the page, and each version's stop gesture."""

import http.client
import json
from typing import Any

import pytest
from ports import free_port
from test_touch_input import FakeMemory

from naoqi_sim import controls as controls_module
from naoqi_sim.controls import Controls, stop_activity_gesture
from naoqi_sim.errors import CameraNotFedError
from naoqi_sim.touch_input import KEY, SENSORS, TouchInput
from naoqi_sim.video_input import VideoInput


class Source:
    name = "render"

    def frame(self):  # never called: the video input is not started
        raise AssertionError


class Recorder:
    """A sleep that records, in order, what the devices were doing when it was called."""

    def __init__(self, touch: TouchInput, video: VideoInput | None):
        self.touch, self.video = touch, video
        self.steps: list[tuple[float, list[str], bool]] = []

    def __call__(self, seconds: float) -> None:
        covered = self.video.covered()["top"] if self.video is not None else False
        self.steps.append((seconds, self.touch.pressed(), covered))


@pytest.fixture
def memory():
    return FakeMemory()


@pytest.fixture
def touch(memory):
    device = TouchInput(connect=lambda: memory)
    device.start()
    yield device
    device.stop()


@pytest.fixture
def video():
    return VideoInput({"top": Source()}, {"top": 10}, connect=lambda: None)


@pytest.fixture
def server(touch, video):
    controls = Controls(free_port(), "2.8", touch, video, sleep=lambda s: None)
    controls.start()
    yield controls
    controls.stop()


def request(
    server: Controls,
    method: str,
    path: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    sent = {"Content-Type": "application/json"} if body is not None else {}
    sent.update(headers or {})
    connection.request(
        method, path, None if body is None else json.dumps(body), headers=sent
    )
    response = connection.getresponse()
    data = response.read()
    connection.close()
    kind = response.getheader("Content-Type") or ""
    return response.status, json.loads(data) if kind == "application/json" else data


def test_state_shows_the_version_the_touches_and_the_cameras(server, touch):
    touch.press(
        "api", ["LHand/Touch/Back"]
    )  # pressed from Python: the page sees it too
    status, state = request(server, "GET", "/api/state")
    assert status == 200
    assert state == {
        "naoqi_version": "2.8",
        "touch": {"pressed": ["LHand/Touch/Back"], "held": []},
        "cameras": {
            "top": {"covered": False, "fed": True},
            "bottom": {"covered": False, "fed": False},
        },
    }


def test_press_and_release_hold_sensors_together_until_released(server, memory):
    status, state = request(server, "POST", "/api/touch/press", {"sensors": ["Head"]})
    assert status == 200
    assert state["touch"]["held"] == [
        "Head/Touch/Front",
        "Head/Touch/Middle",
        "Head/Touch/Rear",
    ]
    assert [v for _, v in memory.values()] == [1.0, 1.0, 1.0]
    request(server, "POST", "/api/touch/release", {"sensors": ["Head/Touch/Middle"]})
    _, state = request(
        server, "POST", "/api/touch/release", {}
    )  # all the controls hold
    assert state["touch"]["pressed"] == []
    assert [v for _, v in memory.values()] == [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]


def test_a_tap_answers_once_released(server, memory):
    status, state = request(
        server,
        "POST",
        "/api/touch/tap",
        {"sensors": ["RFoot/Bumper/Right"], "duration_s": 0.1},
    )
    assert status == 200
    assert state["touch"]["pressed"] == []
    assert memory.values() == [
        (KEY.format("RFoot/Bumper/Right"), 1.0),
        (KEY.format("RFoot/Bumper/Right"), 0.0),
    ]


def test_the_controls_release_only_their_own_holds(server, touch):
    touch.press("api", ["Head/Touch/Front"])
    request(server, "POST", "/api/touch/press", {"sensors": ["Head/Touch/Front"]})
    _, state = request(server, "POST", "/api/touch/release", {})
    assert state["touch"]["pressed"] == ["Head/Touch/Front"]  # the API still holds it


def test_a_camera_is_covered_and_uncovered(server, video):
    status, state = request(server, "POST", "/api/cameras/top", {"covered": True})
    assert status == 200 and state["cameras"]["top"]["covered"] is True
    assert video.covered()["top"] is True
    request(server, "POST", "/api/cameras/top", {"covered": False})
    assert video.covered()["top"] is False


@pytest.mark.parametrize(
    ("path", "body", "status", "error"),
    [
        ("/api/touch/press", {"sensors": ["Tail"]}, 400, "unknown touch sensor 'Tail'"),
        ("/api/touch/press", {"sensors": []}, 400, "at least one sensor"),
        ("/api/touch/press", {"sensors": "Head"}, 400, "list of names"),
        ("/api/touch/tap", {"sensors": ["Head"], "duration_s": -1}, 400, "duration_s"),
        ("/api/touch/tap", {"sensors": ["Head"], "duration_s": "1"}, 400, "duration_s"),
        ("/api/cameras/side", {"covered": True}, 400, "unknown camera 'side'"),
        ("/api/cameras/top", {"covered": "yes"}, 400, "true or false"),
        ("/api/cameras/bottom", {"covered": True}, 409, "bottom camera gets no frames"),
        ("/api/gestures/wave", {}, 400, "unknown gesture 'wave'"),
        ("/api/nothing", {}, 404, "no such request"),
    ],
)
def test_a_bad_request_says_what_is_wrong_and_changes_nothing(
    server, memory, path, body, status, error
):
    got, answer = request(server, "POST", path, body)
    assert got == status
    assert error in answer["error"]
    assert memory.writes == []


def test_requests_from_another_site_are_refused(server, memory):
    # a page elsewhere reaching the port by a name of its own, or posting from its origin
    status, _ = request(
        server, "GET", "/api/state", headers={"Host": "evil.example:9564"}
    )
    assert status == 403
    status, _ = request(
        server,
        "POST",
        "/api/touch/press",
        {"sensors": ["Head"]},
        headers={"Origin": "https://evil.example"},
    )
    assert status == 403
    # a form posting without JSON's content type, which needs no preflight
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    connection.request(
        "POST",
        "/api/touch/press",
        '{"sensors": ["Head"]}',
        headers={"Content-Type": "text/plain"},
    )
    assert connection.getresponse().status == 415
    connection.close()
    assert memory.writes == []
    # the page itself, from its own origin
    status, _ = request(
        server,
        "POST",
        "/api/touch/press",
        {"sensors": ["Head"]},
        headers={"Origin": f"http://localhost:{server.port}"},
    )
    assert status == 200


def test_stop_releases_the_controls_holds(touch, video, memory):
    server = Controls(free_port(), "2.1", touch, video)
    server.start()
    request(server, "POST", "/api/touch/press", {"sensors": ["LFoot/Bumper/Left"]})
    touch.press("api", ["Head/Touch/Rear"])
    server.stop()
    assert touch.pressed() == ["Head/Touch/Rear"]
    with pytest.raises(OSError):
        request(server, "GET", "/api/state")


def test_the_page_names_every_sensor_and_calls_the_api(server):
    status, page = request(server, "GET", "/")
    assert status == 200
    text = page.decode()
    for sensor in SENSORS:
        assert f'data-sensor="{sensor}"' in text
    for path in (
        "/api/state",
        "/api/touch/tap",
        "/api/cameras/",
        "/api/gestures/stop-activity",
    ):
        assert path in text
    assert "http://" not in text.replace(
        "http://www.w3.org/2000/svg", ""
    )  # nothing external


def test_the_21_stop_gesture_holds_the_three_head_sensors_3_5_s(touch):
    sleep = Recorder(touch, None)
    stop_activity_gesture("2.1", touch, None, "controls", sleep)
    assert sleep.steps == [
        (3.5, ["Head/Touch/Front", "Head/Touch/Middle", "Head/Touch/Rear"], False)
    ]
    assert touch.pressed() == []


def test_the_28_stop_gesture_holds_the_front_sensor_2_s_under_a_covered_camera(
    touch, video
):
    sleep = Recorder(touch, video)
    stop_activity_gesture("2.8", touch, video, "controls", sleep)
    settle = controls_module.COVER_SETTLE_S
    assert sleep.steps == [
        (settle, [], True),  # covered first, so the statistics say dark
        (2.0, ["Head/Touch/Front"], True),
        (settle, [], True),  # released while still dark
    ]
    assert touch.pressed() == [] and video.covered()["top"] is False


def test_the_28_stop_gesture_leaves_a_camera_covered_by_hand_covered(touch, video):
    video.cover("top")
    stop_activity_gesture("2.8", touch, video, "controls", lambda s: None)
    assert video.covered()["top"] is True


def test_the_28_stop_gesture_needs_a_top_camera(touch, memory):
    with pytest.raises(CameraNotFedError):
        stop_activity_gesture("2.8", touch, None, "controls", lambda s: None)
    bottom_only = VideoInput({"bottom": Source()}, {"bottom": 10}, connect=lambda: None)
    with pytest.raises(CameraNotFedError):
        stop_activity_gesture("2.8", touch, bottom_only, "controls", lambda s: None)
    assert memory.writes == []


def test_the_gesture_over_http(server, memory):
    status, _ = request(server, "POST", "/api/gestures/stop-activity", {})
    assert status == 200
    assert memory.values() == [
        (KEY.format("Head/Touch/Front"), 1.0),
        (KEY.format("Head/Touch/Front"), 0.0),
    ]
