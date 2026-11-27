"""Touches on both versions (touch-input.md, controls.md and brightness-statistics.md, "Tests"):
a tap reaches the robot's own `ALTouch` and its events, and each version's gesture stops the
focused activity as on a NAO, from Python and through the controls' HTTP API. The activity is
ours (tests-e2e/packages/naoqi_sim_test_activity): it keeps the focus until it is stopped."""

import http.client
import json
import time
from pathlib import Path
from typing import Any

import pytest
from support import CONTROLS_PORT, wait_until
from test_life_scenario_live import build

ACTIVITY = "naoqi_sim_test_activity/."
FRONT_KEY = "Device/SubDeviceList/Head/Touch/Front/Sensor/Value"


def post(path: str, body: dict[str, Any], timeout: float = 15.0) -> tuple[int, Any]:
    """A request to the controls, as a program other than the test's Python would send it."""
    connection = http.client.HTTPConnection("127.0.0.1", CONTROLS_PORT, timeout=timeout)
    connection.request(
        "POST", path, json.dumps(body), headers={"Content-Type": "application/json"}
    )
    response = connection.getresponse()
    answer = json.loads(response.read())
    connection.close()
    return response.status, answer


class Events:
    """The events a test watches, with the time each came."""

    def __init__(self, memory, *names: str):
        self.seen: list[tuple[str, Any, float]] = []
        self._subscribers = []
        for name in names:
            subscriber = memory.subscriber(name)
            subscriber.signal.connect(
                lambda value, name=name: self.seen.append(
                    (name, value, time.monotonic())
                )
            )
            self._subscribers.append(subscriber)

    def values(self, name: str) -> list[Any]:
        return [value for n, value, _ in self.seen if n == name]


def test_a_tap_reaches_altouch_and_its_events(nao):
    memory = nao.service("ALMemory")
    events = Events(memory, "FrontTactilTouched", "TouchChanged", "HandLeftBackTouched")
    nao.runner.run(nao.sim.touch.tap("Head/Touch/Front", duration_s=0.5))
    wait_until(
        lambda: events.values("FrontTactilTouched") == [1.0, 0.0], 5.0, "press, release"
    )
    touched = events.values("TouchChanged")[0]
    assert ["Head/Touch/Front", True, [1]] in [list(t) for t in touched]
    assert memory.getData(FRONT_KEY) == 0.0

    # through the controls: pressed, as ALTouch reports it, then released
    status, state = post("/api/touch/press", {"sensors": ["LHand/Touch/Back"]})
    assert status == 200 and state["touch"]["pressed"] == ["LHand/Touch/Back"]
    wait_until(
        lambda: events.values("HandLeftBackTouched") == [1.0], 5.0, "the hand's event"
    )
    pressed = [row[0] for row in nao.service("ALTouch").getStatus() if row[1]]
    assert "LHand/Touch/Back" in pressed
    post("/api/touch/release", {})
    wait_until(
        lambda: events.values("HandLeftBackTouched") == [1.0, 0.0], 5.0, "released"
    )


@pytest.fixture
def activity(nao, tmp_path: Path):
    """Life on, our activity installed and focused; Life off and the package removed after."""
    name = ACTIVITY.split("/")[0]
    nao.container.copy_in(build(name, tmp_path), f"/tmp/{name}.pkg")
    pm = nao.service("PackageManager")
    if pm.hasPackage(
        name
    ):  # left by a run that did not finish: the package store persists
        pm.removePkg(name)
    assert pm.install(f"/tmp/{name}.pkg")
    life = nao.service("ALAutonomousLife")
    life.setState("solitary")
    try:
        yield life
    finally:
        try:
            if life.focusedActivity():
                life.stopFocus()
        finally:
            life.setState("disabled")
            pm.removePkg(name)


def focus(life) -> None:
    life.switchFocus(ACTIVITY)
    wait_until(lambda: life.focusedActivity() == ACTIVITY, 20.0, "our activity focused")
    time.sleep(3.0)  # settled: Life's rules see the focus
    assert life.focusedActivity() == ACTIVITY


def stops(life, within: float) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if life.focusedActivity() != ACTIVITY:
            return True
        time.sleep(0.1)
    return False


def test_a_touch_that_is_not_the_gesture_stops_nothing(nao, activity):
    focus(activity)
    if nao.version.name == "2.1":
        nao.runner.run(
            nao.sim.touch.tap("Head/Touch/Front", "Head/Touch/Middle", duration_s=3.5)
        )
    else:  # the front sensor held with the camera uncovered
        nao.runner.run(nao.sim.touch.tap("Head/Touch/Front", duration_s=2.0))
    assert not stops(activity, 6.0)


def test_the_stop_gesture_stops_the_focused_activity(nao, activity):
    focus(activity)
    nao.runner.run(nao.sim.stop_activity_gesture())
    assert stops(activity, 8.0), "the activity stopped after the gesture"


def test_the_stop_gesture_through_the_controls(nao, activity):
    focus(activity)
    status, state = post("/api/gestures/stop-activity", {})
    assert status == 200 and state["touch"]["pressed"] == []
    assert state["cameras"]["top"]["covered"] is False
    assert stops(activity, 8.0), "the activity stopped after the gesture"


def test_the_brightness_statistics_follow_the_camera_while_life_runs(nao, activity):
    if nao.version.name != "2.8":
        pytest.skip("2.8 only: a NAO 2.1 has no _ALBrightnessStatistics")
    memory = nao.service("ALMemory")
    events = Events(memory, "_ALBrightnessStatistics/Avg")
    wait_until(lambda: len(events.seen) >= 3, 10.0, "Life started the statistics")
    assert memory.getData("_ALBrightnessStatistics/Std") > 0  # the rendered scene
    nao.runner.run(nao.sim.cover_camera("top"))
    try:
        wait_until(
            lambda: (
                memory.getData("_ALBrightnessStatistics/Avg") < 30
                and memory.getData("_ALBrightnessStatistics/Std") < 5
            ),
            5.0,
            "dark under a hand",
        )
    finally:
        nao.runner.run(nao.sim.uncover_camera("top"))
    activity.setState("disabled")  # Life stops the statistics
    time.sleep(1.0)
    count = len(events.seen)
    time.sleep(1.0)
    assert len(events.seen) == count
