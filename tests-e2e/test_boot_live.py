"""The robot boots: run first for each version (tests-e2e/conftest.py moves it there), so a NAOqi
that does not boot fails this test, with the boot's error, and the version's other tests skip."""


def test_the_robot_boots(nao):
    """Booted, and as a NAO whose Life does not start at boot: Life disabled, crouched, the stiffness
    off (autonomous-life.md, "The state at boot": the default). This test runs on the fresh
    boot, before any other test moves the robot."""
    assert nao.running
    assert nao.service("NaoqiSim").isReady()
    motion = nao.service("ALMotion")
    assert nao.service("ALAutonomousLife").getState() == "disabled"
    assert not motion.robotIsWakeUp()
    assert max(motion.getStiffnesses("Body")) < 0.1
    assert nao.service("ALRobotPosture").getPosture() == "Crouch"


def test_a_client_switches_life_on_and_off(nao):
    """From the boot state, setState("solitary") stands the robot on both versions (2.1's desktop
    suite needs the entrypoint's allowance), and setState("disabled") brings it back to rest."""
    life = nao.service("ALAutonomousLife")
    motion = nao.service("ALMotion")
    posture = nao.service("ALRobotPosture")
    life.setState("solitary")
    try:
        assert life.getState() == "solitary"
        assert motion.robotIsWakeUp()
        assert posture.getPostureFamily() == "Standing"
    finally:
        life.setState("disabled")
    assert life.getState() == "disabled"
    assert not motion.robotIsWakeUp()
    assert posture.getPosture() == "Crouch"
