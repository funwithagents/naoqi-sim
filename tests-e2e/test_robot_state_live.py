"""The robot's state when the sim is ready, from the config's setup block (autonomous-life.md,
"The state at boot"). The default, at rest with Life off, is checked by the boot test; these boot
their own sims in the other states, which each version can be in."""

import pytest
from conftest import live_config
from support import connect

from naoqi_sim import MemorySink, NaoqiSim
from naoqi_sim.config import SetupSettings

STATES = {
    "2.1": [
        SetupSettings(posture="sit"),  # sitting, stiffness off: rest() would crouch it
        SetupSettings(
            posture="sit", stiffness_on=True, life_on=True
        ),  # sitting, Life on
    ],
    "2.8": [  # 2.8 cannot sit
        SetupSettings(posture="stand", stiffness_on=True, life_on=True),
        SetupSettings(stiffness_on=True),  # crouched, stiff
    ],
}


@pytest.mark.parametrize("index", [0, 1])
def test_the_sim_is_ready_in_the_configs_state(nao, index):
    states = STATES[nao.version.name]
    if index >= len(states):
        pytest.skip(f"{nao.version.name} has {len(states)} state(s) to check")
    setup = states[index]
    sim = NaoqiSim(live_config(nao.version.name, setup=setup), sink=MemorySink())
    nao.stop()
    try:
        nao.runner.run(sim.start())
        session = connect()
        motion = session.service("ALMotion")
        posture = session.service("ALRobotPosture")
        life = session.service("ALAutonomousLife")
        assert posture.getPosture() == setup.posture.capitalize()
        assert life.getState() == ("solitary" if setup.life_on else "disabled")
        stiffness = max(motion.getStiffnesses("Body"))
        assert stiffness > 0.9 if setup.stiffness_on else stiffness < 0.1
        session.close()
    finally:
        nao.runner.run(sim.stop())
