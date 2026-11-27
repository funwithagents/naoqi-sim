"""The controls server over HTTP, with the real touch input and video input on fake NAOqi
services: what each request does to the devices, what `GET /api/state` shows, the refusals, the
holds released at stop, the page, and each version's stop gesture."""

import http.client
import json
import threading
from typing import Any

import numpy as np
import pytest
from ports import free_port
from test_audio_input import fake_sounddevice  # noqa: F401 (a fixture)
from test_touch_input import FakeMemory

from naoqi_sim import controls as controls_module
from naoqi_sim.audio_input import MicSource
from naoqi_sim.audio_output import DevicePlayer
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
        "audio": {  # neither the microphone nor the loudspeakers given: nothing to mute
            "input": {"mutable": False, "muted": False},
            "output": {"mutable": False, "muted": False},
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
        "/api/audio/",
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


# --- The robot's buttons, relayed to NAOqi ---------------------------------------------------


class FakeRobot:
    """ALMotion, ALRobotPosture and ALAutonomousLife as the sim measured them (controls.md,
    "The robot"): a posture with the stiffness off wakes the robot, Life on wakes it and
    stands it up, Life off rests it. `hold` keeps the next posture running until set."""

    def __init__(self):
        self.stiffness = [0.0] * 26
        self.posture = "Crouch"
        self.life = "disabled"
        self.calls: list[str] = []
        self.hold = threading.Event()
        self.hold.set()
        self.started = threading.Event()
        self.refuse = False
        self.closed = False

    def service(self, name: str):
        return self

    def close(self):
        self.closed = True

    # ALMotion
    def robotIsWakeUp(self):
        return min(self.stiffness) > 0

    def getStiffnesses(self, names):
        return list(self.stiffness)

    def setStiffnesses(self, names, value):
        self.calls.append(f"setStiffnesses {value}")
        self.stiffness = [value] * len(self.stiffness)

    def wakeUp(self):
        self.calls.append("wakeUp")
        self.setStiffnesses("Body", 1.0)
        if self.posture == "Crouch":
            self.posture = "Stand"

    def rest(self):
        self.calls.append("rest")
        self.posture = "Crouch"
        self.setStiffnesses("Body", 0.0)

    # ALRobotPosture
    def getPosture(self):
        return self.posture

    def goToPosture(self, posture, speed):
        self.calls.append(f"goToPosture {posture} {speed}")
        self.started.set()
        self.hold.wait(5)
        if self.refuse:
            return False
        self.setStiffnesses("Body", 1.0)
        self.posture = posture
        return True

    # ALAutonomousLife
    def getState(self):
        return self.life

    def focusedActivity(self):
        return ""

    def setState(self, state):
        self.calls.append(f"setState {state}")
        self.life = state
        if state == "solitary":
            self.wakeUp()
        else:
            self.rest()


@pytest.fixture
def robot():
    return FakeRobot()


@pytest.fixture
def robot_server(touch, video, robot):
    controls = Controls(
        free_port(), "2.8", touch, video, robot=controls_module.Robot(lambda: robot)
    )
    controls.start()
    yield controls
    controls.stop()


def test_the_robot_state_is_naoqis(robot_server, robot):
    status, state = request(robot_server, "GET", "/api/state")
    assert status == 200
    assert state["robot"] == {
        "awake": False,
        "stiffness": [0.0, 0.0],
        "posture": "Crouch",
        "life": "disabled",
        "focus": "",
        "running": None,
    }
    robot.stiffness[3] = 0.6  # a qi client stiffened one joint: partial
    assert request(robot_server, "GET", "/api/state")[1]["robot"]["stiffness"] == [
        0.0,
        0.6,
    ]


def test_each_robot_button_is_its_naoqi_call(robot_server, robot):
    def post(path, body):
        status, state = request(robot_server, "POST", f"/api/robot/{path}", body)
        assert status == 200, state
        return state["robot"]

    assert post("posture", {"posture": "Stand"})["posture"] == "Stand"
    assert post("stiffness", {"on": False})["awake"] is False
    assert post("stiffness", {"on": True})["stiffness"] == [1.0, 1.0]
    assert post("motors", {"action": "rest"})["posture"] == "Crouch"
    assert post("motors", {"action": "wake_up"})["awake"] is True
    assert post("life", {"on": True})["life"] == "solitary"
    off = post("life", {"on": False})
    assert (off["life"], off["posture"], off["awake"]) == ("disabled", "Crouch", False)
    assert robot.calls == [
        "goToPosture Stand 0.8",
        "setStiffnesses 1.0",
        "setStiffnesses 0.0",
        "setStiffnesses 1.0",
        "rest",
        "setStiffnesses 0.0",
        "wakeUp",
        "setStiffnesses 1.0",
        "setState solitary",
        "wakeUp",
        "setStiffnesses 1.0",
        "setState disabled",
        "rest",
        "setStiffnesses 0.0",
    ]


def test_one_robot_action_at_a_time(robot_server, robot):
    robot.hold.clear()  # the posture keeps running
    answers: list[tuple[int, Any]] = []
    first = threading.Thread(
        target=lambda: answers.append(
            request(robot_server, "POST", "/api/robot/posture", {"posture": "Sit"})
        )
    )
    first.start()
    assert robot.started.wait(5)
    assert request(robot_server, "GET", "/api/state")[1]["robot"]["running"] == "Sit"
    status, answer = request(
        robot_server, "POST", "/api/robot/motors", {"action": "rest"}
    )
    assert (status, answer) == (409, {"error": "Sit is running"})
    robot.hold.set()
    first.join(5)
    assert answers[0][0] == 200 and answers[0][1]["robot"]["posture"] == "Sit"
    assert "rest" not in robot.calls  # refused, never sent to NAOqi
    assert request(robot_server, "GET", "/api/state")[1]["robot"]["running"] is None


def test_naoqis_refusals_are_shown_not_guessed(robot_server, robot):
    robot.refuse = True
    status, answer = request(
        robot_server, "POST", "/api/robot/posture", {"posture": "Sit"}
    )
    assert (status, answer) == (
        409,
        {"error": 'NAOqi answered False to goToPosture("Sit")'},
    )

    def broken(state):
        raise RuntimeError("ALAutonomousLife::setState\tInvalid state transition")

    robot.setState = broken
    status, answer = request(robot_server, "POST", "/api/robot/life", {"on": True})
    assert status == 500 and "Invalid state transition" in answer["error"]


@pytest.mark.parametrize(
    ("path", "body", "error"),
    [
        (
            "posture",
            {"posture": "LyingBack"},
            "posture must be one of Stand, StandInit, Sit, Crouch",
        ),
        ("motors", {"action": "sleep"}, 'action must be "wake_up" or "rest"'),
        ("stiffness", {"on": 1}, "on must be true or false"),
        ("life", {}, "on must be true or false"),
    ],
)
def test_a_bad_robot_request_is_400(robot_server, robot, path, body, error):
    status, answer = request(robot_server, "POST", f"/api/robot/{path}", body)
    assert (status, answer) == (400, {"error": error})
    assert robot.calls == []


def test_naoqi_not_answering_leaves_the_rest_of_the_page(robot_server, robot):
    def dead(names):
        raise RuntimeError("the session is closed")

    robot.getStiffnesses = dead
    status, state = request(robot_server, "GET", "/api/state")
    assert status == 200
    assert state["robot"] == {"error": "the session is closed", "running": None}
    assert state["touch"] == {"pressed": [], "held": []}


def test_the_robot_session_closes_with_the_server(touch, video, robot):
    controls = Controls(
        free_port(), "2.8", touch, video, robot=controls_module.Robot(lambda: robot)
    )
    controls.start()
    controls.stop()
    assert robot.closed


# --- The mutes ---------------------------------------------------------------------------------


@pytest.fixture
def audio_server(touch, video, fake_sounddevice):  # noqa: F811
    streams, _ = fake_sounddevice
    mic, player = MicSource(), DevicePlayer()
    mic.open()  # the audio input started: the microphone is live
    controls = Controls(
        free_port(), "2.8", touch, video, sleep=lambda s: None, mic=mic, player=player
    )
    controls.start()
    yield controls, streams, mic, player
    controls.stop()
    mic.close()


def test_the_microphone_is_muted_and_unmuted_from_the_page(audio_server):
    controls, streams, mic, _ = audio_server
    status, state = request(controls, "POST", "/api/audio/input", {"muted": True})
    assert status == 200
    assert state["audio"]["input"] == {"mutable": True, "muted": True}
    assert streams[0].calls == ["start", "stop", "close"]  # the device is off
    assert np.abs(mic.read(0.0, 480)).max() == 0  # the robot hears silence
    status, state = request(controls, "POST", "/api/audio/input", {"muted": False})
    assert state["audio"]["input"] == {"mutable": True, "muted": False}
    assert len(streams) == 2 and streams[1].calls == ["start"]  # live again


def test_the_loudspeakers_are_muted_and_unmuted_from_the_page(audio_server):
    controls, _, _, player = audio_server
    status, state = request(controls, "POST", "/api/audio/output", {"muted": True})
    assert status == 200 and player.muted
    assert state["audio"]["output"] == {"mutable": True, "muted": True}
    player.muted = False  # unmuted from Python: the page sees it
    _, state = request(controls, "GET", "/api/state")
    assert state["audio"]["output"] == {"mutable": True, "muted": False}


@pytest.mark.parametrize("side", ["input", "output"])
def test_a_side_with_nothing_to_mute_is_409(server, side):
    status, answer = request(server, "POST", f"/api/audio/{side}", {"muted": True})
    assert status == 409 and "nothing to mute" in answer["error"]


@pytest.mark.parametrize("body", [{}, {"muted": "yes"}, {"muted": 1}])
def test_a_bad_mute_is_400_and_changes_nothing(audio_server, body):
    controls, streams, mic, player = audio_server
    for side in ("input", "output"):
        status, answer = request(controls, "POST", f"/api/audio/{side}", body)
        assert status == 400 and "muted must be true or false" in answer["error"]
    assert not mic.muted and not player.muted and len(streams) == 1
    status, _ = request(controls, "POST", "/api/audio/both", {"muted": True})
    assert status == 404


def test_the_page_has_the_two_mute_buttons_on_its_title_line(server):
    _, page = request(server, "GET", "/")
    header = page.decode().split("<header>")[1].split("</header>")[0]
    assert 'id="mute-input"' in header and 'id="mute-output"' in header
