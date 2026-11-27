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


ENV = {
    "NAOQI_SIM_VERSION": "0.3.1",
    "NAOQI_SIM_NAOQI_VERSION": "2.8.7.4",
    "NAOQI_SIM_LOOPBACK_9559": "naoqi",
}


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
        "NaoqiSim/SpeechRecognition/Source": "none",
        "NaoqiSim/Loopback9559": "naoqi",
    }


@pytest.mark.parametrize(
    ("set_by_entrypoint", "published"),
    [("naoqi", "naoqi"), ("gateway", "gateway"), (None, "unknown")],
)
def test_publishes_what_robot_software_reaches_on_the_loopback(
    set_by_entrypoint, published
):
    env = {**ENV, "NAOQI_SIM_LOOPBACK_9559": set_by_entrypoint or ""}
    memory = FakeMemory()
    core.Status(memory.insert, memory.raise_event, env=env)
    assert memory.data["NaoqiSim/Loopback9559"] == published


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


V5_MODEL = """<?xml version="1.0" encoding="UTF-8" ?>
<ModulePreference name="aldebaran-robotics.com@Device_Head">
    <Preference name="Key3" memoryName="RobotConfig/Head/BaseVersion" description="" value="V5.0" type="string" /> <!-- deprecated use RobotConfig/Head/Version -->
    <Preference name="Key11" memoryName="RobotConfig/Body/Device/LeftArm/Version" description="" value="3" type="string" /> <!-- -1 no arm, 2 extended arm V3.3 -->
    <Preference name="Key13" memoryName="RobotConfig/Body/Version" description="" value="5.0.0" type="string" />
    <Preference name="Key15" memoryName="RobotConfig/Body/Type" description="" value="Nao" type="string" />
    <!-- <Preference memoryName="RobotConfig/Body/Color" description="" value="Blue" type="string" /> -->
</ModulePreference>
"""
# 2.8's model files name no `name` attribute
V6_MODEL = """<ModulePreference>
    <Preference memoryName="RobotConfig/Body/Version" description="" value="6.0.0" type="string" />
    <Preference memoryName="RobotConfig/Body/Type" description="" value="Nao" type="string" />
</ModulePreference>
"""


@pytest.mark.parametrize(
    ("model", "keys"),
    [
        (
            V5_MODEL,
            {
                "RobotConfig/Head/BaseVersion": "V5.0",
                "RobotConfig/Body/Device/LeftArm/Version": "3",
                "RobotConfig/Body/Version": "5.0.0",
                "RobotConfig/Body/Type": "Nao",
            },
        ),
        (
            V6_MODEL,
            {"RobotConfig/Body/Version": "6.0.0", "RobotConfig/Body/Type": "Nao"},
        ),
    ],
)
def test_publishes_the_robots_own_keys_from_its_model_file(tmp_path, model, keys):
    path = tmp_path / "model.xml"
    path.write_text(model)
    memory = FakeMemory()
    core.Status(
        memory.insert,
        memory.raise_event,
        env={**ENV, "NAOQI_SIM_ROBOT_MODEL_FILE": str(path)},
    )
    robot = {k: v for k, v in memory.data.items() if not k.startswith("NaoqiSim/")}
    assert (
        robot == keys
    )  # as a robot's: under their own names, commented entries left out


def test_without_a_model_file_no_robot_key_is_published(tmp_path):
    for env in (ENV, {**ENV, "NAOQI_SIM_ROBOT_MODEL_FILE": str(tmp_path / "gone.xml")}):
        memory = FakeMemory()
        core.Status(memory.insert, memory.raise_event, env=env)
        assert all(key.startswith("NaoqiSim/") for key in memory.data)
