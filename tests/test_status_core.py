"""The NaoqiSim status service's shared logic: what it publishes in ALMemory and when it is ready."""

import naoqi_sim_status_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code


class FakeMemory:
    """Records insertData/raiseEvent as the real ALMemory would see them."""

    def __init__(self):
        self.data: dict[str, object] = {}
        self.events: list[tuple[str, object]] = []

    def insert(self, key, value):
        self.data[key] = value

    def raise_event(self, key, value):
        self.data[key] = value
        self.events.append((key, value))


ENV = {"NAOQI_SIM_VERSION": "0.3.1", "NAOQI_SIM_NAOQI_VERSION": "2.8.7.4"}


def test_publishes_versions_and_idle_sources_at_load():
    memory = FakeMemory()
    status = core.Status(memory.insert, memory.raise_event, env=ENV)

    assert status.version == "0.3.1"
    assert status.naoqi_version == "2.8.7.4"
    assert memory.data == {
        "NaoqiSim/Version": "0.3.1",
        "NaoqiSim/NaoqiVersion": "2.8.7.4",
        "NaoqiSim/Ready": 0,
        "NaoqiSim/Camera/Source": "none",
        "NaoqiSim/Camera/Top/Source": "none",
        "NaoqiSim/Camera/Bottom/Source": "none",
        "NaoqiSim/Audio/Source": "none",
        "NaoqiSim/Audio/Channels": "none",
        "NaoqiSim/Perception/Source": "none",
        "NaoqiSim/Perception/Stubs": "",
    }


def test_versions_default_when_the_image_sets_none():
    assert core.versions({}) == ("dev", "unknown")
    assert core.versions({"NAOQI_SIM_VERSION": "", "NAOQI_SIM_NAOQI_VERSION": ""}) == (
        "dev",
        "unknown",
    )


def test_not_ready_until_set_ready_then_the_event_is_raised():
    memory = FakeMemory()
    status = core.Status(memory.insert, memory.raise_event, env=ENV)
    assert status.ready is False
    assert memory.events == [("NaoqiSim/Ready", 0)]

    status.set_ready()

    assert status.ready is True
    assert memory.data["NaoqiSim/Ready"] == 1
    assert memory.events[-1] == ("NaoqiSim/Ready", 1)
