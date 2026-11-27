"""Which robot the sim is: the config's `robot`, as NAOqi's model and as the robot's own ALMemory
keys, which a client reads the same way on a robot (specs/container/container.md, "The robot
model"; specs/container/status-service.md, "The robot's keys")."""

import pytest
from conftest import live_config
from support import connect

from naoqi_sim import MemorySink, NaoqiSim
from naoqi_sim.config import RobotSettings

# Each NAOqi version's default robot, as its model file says it.
DEFAULT = {"2.1": "5.0.0", "2.8": "6.0.0"}
KEYS = [
    "RobotConfig/Body/Type",
    "RobotConfig/Head/Type",
    "RobotConfig/Body/Version",
    "RobotConfig/Head/Version",
]


def robot_keys(session) -> list[str]:
    return session.service("ALMemory").getListData(KEYS)


def test_the_default_robot_says_what_it_is_as_a_robot_does(nao):
    version = DEFAULT[nao.version.name]
    assert (nao.sim.config.robot.type, nao.sim.config.robot.version) == (
        "nao",
        f"v{version[0]}",
    )
    assert robot_keys(nao.session) == ["Nao", "Nao", version, version]
    # NAOqi itself runs that robot: a NAO's 26 joints, its hands and wrists included
    names = nao.service("ALMotion").getBodyNames("Body")
    assert len(names) == 26 and {"LWristYaw", "RHand"} <= set(names)


def test_naoqi_2_1_runs_as_a_nao_v4_when_the_config_says_so(nao):
    if nao.version.name != "2.1":
        pytest.skip("only NAOqi 2.1 runs a second robot, the NAO V4")
    config = live_config("2.1", robot=RobotSettings(version="v4"))
    sim = NaoqiSim(config, sink=MemorySink())
    nao.stop()
    try:
        nao.runner.run(sim.start())
        session = connect()
        assert robot_keys(session) == ["Nao", "Nao", "4.0.0", "4.0.0"]
        memory = session.service("ALMemory")
        assert memory.getData("RobotConfig/Body/BaseVersion") == "V4.0"
        assert len(session.service("ALMotion").getBodyNames("Body")) == 26
        # and it still stands up: the robot's keys disturb nothing
        session.service("ALMotion").wakeUp()
        session.service("ALRobotPosture").goToPosture("Stand", 0.8)
        assert session.service("ALRobotPosture").getPosture() == "Stand"
        session.close()
    finally:
        nao.runner.run(sim.stop())
