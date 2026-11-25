"""The robot's state when the sim is ready, from the config's robot block (autonomous-life.md,
"The state at boot"). The default, at rest with Life off, is checked by the boot test; these boot
their own sims in the other states, which each version can be in."""

import pytest
from conftest import live_config
from support import connect

from naoqi_sim import MemorySink, NaoqiSim
from naoqi_sim.config import RobotSettings

STATES = {
    "2.1": [
        RobotSettings(posture="sit"),  # sitting, motors off: rest() would crouch it
        RobotSettings(posture="sit", motors=True, life=True),  # sitting, Life on
    ],
    "2.8": [RobotSettings(posture="stand", motors=True, life=True)],  # 2.8 cannot sit
}


@pytest.mark.parametrize("index", [0, 1])
def test_the_sim_is_ready_in_the_configs_state(nao, index):
    states = STATES[nao.version.name]
    if index >= len(states):
        pytest.skip(f"{nao.version.name} has {len(states)} state(s) to check")
    robot = states[index]
    sim = NaoqiSim(live_config(nao.version.name, robot=robot), sink=MemorySink())
    nao.stop()
    try:
        nao.runner.run(sim.start())
        session = connect()
        motion = session.service("ALMotion")
        posture = session.service("ALRobotPosture")
        life = session.service("ALAutonomousLife")
        assert posture.getPosture() == {"sit": "Sit", "stand": "Stand"}[robot.posture]
        assert life.getState() == ("solitary" if robot.life else "disabled")
        stiffness = max(motion.getStiffnesses("Body"))
        assert stiffness > 0.9 if robot.motors else stiffness < 0.1
        session.close()
    finally:
        nao.runner.run(sim.stop())
