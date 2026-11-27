"""The controls' Robot panel on both versions (controls.md, "The robot"): each button, sent over
the controls' HTTP API, reaches NAOqi and shows in the state the page polls; one action at a
time. The robot is left as it boots: Life off, resting."""

import http.client
import json
import threading
from typing import Any

import pytest
from support import CONTROLS_PORT, wait_until


def send(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", CONTROLS_PORT, timeout=60)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(
        method, path, None if body is None else json.dumps(body), headers=headers
    )
    response = connection.getresponse()
    answer = json.loads(response.read())
    connection.close()
    return response.status, answer


def robot(path: str, body: dict[str, Any]) -> dict[str, Any]:
    status, state = send("POST", f"/api/robot/{path}", body)
    assert status == 200, state
    return state["robot"]


def polled() -> dict[str, Any]:
    """The robot as the page's next poll sees it."""
    return send("GET", "/api/state")[1]["robot"]


@pytest.fixture
def at_rest(nao):
    """Resting, Life off before and after."""
    nao.service("ALAutonomousLife").setState("disabled")
    nao.service("ALMotion").rest()
    yield
    nao.service("ALAutonomousLife").setState("disabled")
    nao.service("ALMotion").rest()


def test_each_robot_button_reaches_naoqi(nao, at_rest):
    status, state = send("GET", "/api/state")
    assert status == 200
    rest = state["robot"]
    assert (rest["awake"], rest["stiffness"], rest["posture"]) == (
        False,
        [0.0, 0.0],
        "Crouch",
    )
    assert (rest["life"], rest["running"]) == ("disabled", None)

    # a posture with the motors off: NAOqi stiffens the robot itself
    stand = robot("posture", {"posture": "Stand"})
    assert (stand["posture"], stand["awake"], stand["stiffness"]) == (
        "Stand",
        True,
        [1.0, 1.0],
    )

    # setStiffnesses returns before 2.1 applies it: the page's next polls show it
    robot("stiffness", {"on": False})
    wait_until(lambda: polled()["stiffness"] == [0.0, 0.0], 5.0, "stiffness off")
    off = polled()
    assert (off["awake"], off["posture"]) == (
        False,
        "Stand",
    )  # no physics: still standing
    robot("stiffness", {"on": True})
    wait_until(lambda: polled()["stiffness"] == [1.0, 1.0], 5.0, "stiffness on")

    resting = robot("motors", {"action": "rest"})
    assert (resting["awake"], resting["posture"]) == (False, "Crouch")
    awake = robot("motors", {"action": "wake_up"})
    assert (awake["awake"], awake["posture"]) == (True, "Stand")

    assert robot("life", {"on": True})["life"] == "solitary"
    life_off = robot("life", {"on": False})  # Life rests the robot as it stops
    assert (life_off["life"], life_off["awake"], life_off["posture"]) == (
        "disabled",
        False,
        "Crouch",
    )


def test_one_robot_action_at_a_time(nao, at_rest):
    robot("motors", {"action": "wake_up"})
    answers: list[tuple[int, Any]] = []
    sit = threading.Thread(
        target=lambda: answers.append(
            send("POST", "/api/robot/posture", {"posture": "Crouch"})
        )
    )
    sit.start()  # Stand to Crouch takes 9 s and more
    try:
        running = None
        for _ in range(50):
            running = polled()["running"]
            if running == "Crouch":
                break
            threading.Event().wait(0.1)
        assert running == "Crouch"
        assert send("POST", "/api/robot/motors", {"action": "rest"}) == (
            409,
            {"error": "Crouch is running"},
        )
    finally:
        sit.join(60)
    status, state = answers[0]
    assert status == 200 and state["robot"]["posture"] == "Crouch"
