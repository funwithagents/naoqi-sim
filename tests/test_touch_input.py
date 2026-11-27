"""The touch input against a fake ALMemory: the keys a press and a release write, sensors pressed
together, two holders of one sensor, the release at stop, and the `sim.touch` API over it."""

import asyncio
import time

import pytest

from naoqi_sim.touch_input import HEAD, KEY, SENSORS, Touch, TouchInput, resolve


class FakeMemory:
    """A qi session whose ALMemory records every write, in order."""

    def __init__(self):
        self.writes: list[tuple[str, float, float]] = []
        self.closed = False

    def service(self, name):
        assert name == "ALMemory"
        return self

    def insertData(self, key, value):
        self.writes.append((key, value, time.monotonic()))

    def close(self):
        self.closed = True

    def values(self) -> list[tuple[str, float]]:
        return [(key, value) for key, value, _ in self.writes]


def key(sensor: str) -> str:
    return KEY.format(sensor)


@pytest.fixture
def memory():
    return FakeMemory()


@pytest.fixture
def device(memory):
    device = TouchInput(connect=lambda: memory)
    device.start()
    yield device
    device.stop()


def test_the_thirteen_sensors_are_altouchs():
    assert len(SENSORS) == 13
    assert "ChestBoard/Button" not in SENSORS
    assert resolve(["RFoot/Bumper/Left", "Head"]) == [*HEAD, "RFoot/Bumper/Left"]
    with pytest.raises(ValueError, match="unknown touch sensor 'Head/Touch/Top'"):
        resolve(["Head/Touch/Top"])


def test_a_press_writes_1_and_a_release_0_into_the_sensors_value_key(device, memory):
    device.press("api", ["Head/Touch/Front"])
    assert device.pressed() == ["Head/Touch/Front"]
    device.release("api", ["Head/Touch/Front"])
    assert memory.values() == [
        ("Device/SubDeviceList/Head/Touch/Front/Sensor/Value", 1.0),
        ("Device/SubDeviceList/Head/Touch/Front/Sensor/Value", 0.0),
    ]
    assert device.pressed() == []


def test_head_presses_the_three_head_sensors_together(device, memory):
    device.press("api", ["Head"])
    assert memory.values() == [(key(s), 1.0) for s in HEAD]
    # written back to back, so ALTouch (which reads them every 40 ms) sees one touch
    times = [at for _, _, at in memory.writes]
    assert times[-1] - times[0] < 0.04
    device.release("api")
    assert memory.values()[3:] == [(key(s), 0.0) for s in HEAD]


def test_a_sensor_stays_pressed_while_one_holder_holds_it(device, memory):
    device.press("api", ["Head/Touch/Front"])
    device.press("controls", ["Head/Touch/Front", "LHand/Touch/Back"])
    assert memory.values() == [
        (key("Head/Touch/Front"), 1.0),  # pressed once, not twice
        (key("LHand/Touch/Back"), 1.0),
    ]
    device.release("api")
    assert device.pressed() == ["Head/Touch/Front", "LHand/Touch/Back"]
    assert device.held("api") == []
    assert device.held("controls") == ["Head/Touch/Front", "LHand/Touch/Back"]
    assert len(memory.writes) == 2  # the controls still hold the front sensor
    device.release("controls", ["Head/Touch/Front"])
    assert memory.values()[-1] == (key("Head/Touch/Front"), 0.0)
    assert device.pressed() == ["LHand/Touch/Back"]


def test_releasing_what_a_holder_does_not_hold_writes_nothing(device, memory):
    device.press("controls", ["RHand/Touch/Left"])
    device.release("api", ["RHand/Touch/Left", "Head/Touch/Rear"])
    assert memory.values() == [(key("RHand/Touch/Left"), 1.0)]


def test_stop_releases_every_sensor_then_closes(memory):
    device = TouchInput(connect=lambda: memory)
    device.start()
    device.press("api", ["Head/Touch/Rear"])
    device.press("controls", ["LFoot/Bumper/Left"])
    device.stop()
    assert memory.values()[-2:] == [
        (key("Head/Touch/Rear"), 0.0),
        (key("LFoot/Bumper/Left"), 0.0),
    ]
    assert memory.closed
    device.stop()  # idempotent
    with pytest.raises(RuntimeError, match="not started"):
        device.press("api", ["Head"])


def test_the_api_taps_for_the_time_asked(device, memory):
    touch = Touch(device)
    asyncio.run(touch.tap("Head/Touch/Middle", duration_s=0.3))
    (_, pressed, at_press), (_, released, at_release) = memory.writes
    assert (pressed, released) == (1.0, 0.0)
    assert at_release - at_press >= 0.3
    assert touch.pressed() == []


def test_the_api_releases_only_what_it_pressed(device, memory):
    touch = Touch(device)
    device.press("controls", ["Head/Touch/Front"])
    asyncio.run(touch.press("Head"))
    asyncio.run(touch.release())
    assert touch.pressed() == ["Head/Touch/Front"]


def test_the_api_refuses_an_unknown_sensor_before_pressing_anything(device, memory):
    touch = Touch(device)
    with pytest.raises(ValueError, match="unknown touch sensor"):
        asyncio.run(touch.press("Head", "Tail"))
    with pytest.raises(ValueError, match="at least one sensor"):
        asyncio.run(touch.tap())
    assert memory.writes == []
