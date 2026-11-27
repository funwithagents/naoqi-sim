"""Autonomous Life going to a person (autonomous-life.md): naoqi-sim writes the launchpad's people
keys while Life runs (launchpad-people.md), from our people and their engagement zones.

On 2.8 Life's NAO configuration takes it to interactive when somebody is in zone 1, and Life starts
the main dialog. On 2.1 an activity the user installs does that; here the keys are checked."""

import pytest
from support import wait_until

L = "Launchpad/"


@pytest.fixture
def life(nao):
    life = nao.service("ALAutonomousLife")
    life.setState("solitary")  # stands the robot up
    try:
        yield life
    finally:
        nao.sim.props.clear()
        life.setState("disabled")


def key(memory, name):
    try:
        return memory.getData(name)
    except RuntimeError:  # never raised yet
        return None


def test_the_launchpad_keys_follow_a_person_walking_in(nao, life):
    memory = nao.service("ALMemory")
    status = memory.getData("NaoqiSim/Life/LaunchpadPeople")
    assert L + "NumPeopleZone1" in status.split(",")
    # nobody in view, as a NAO 2.1 in solitary shows
    wait_until(
        lambda: key(memory, L + "NoPeopleInZones") is True, 5.0, "nobody in zones"
    )
    # the module writes its keys one after the other when Life starts, this one last
    wait_until(
        lambda: key(memory, L + "ZoneOfTrackedHuman") == 0, 5.0, "nobody tracked"
    )
    assert key(memory, L + "PeopleNotSeen") is True
    camera_z = nao.service("ALMotion").getPosition("CameraTop", 2, True)[2]
    state = nao.sim.props.spawn("face", (2.0, 0.0, camera_z), frame="robot")
    wait_until(
        lambda: key(memory, L + "NumPeopleZone2") == 1, 10.0, "one person in zone 2"
    )
    assert key(memory, L + "NoPeopleInZones") is False
    assert key(memory, L + "PeopleNotSeen") is False
    wait_until(
        lambda: key(memory, L + "ZoneOfTrackedHuman") == 2, 10.0, "the person tracked"
    )
    assert life.getState() == "solitary"  # zone 2 is not close enough
    nao.sim.props.place(state.name, (1.0, 0.0, camera_z), duration=1.0, frame="robot")
    wait_until(
        lambda: key(memory, L + "NumPeopleZone1") == 1, 10.0, "the person in zone 1"
    )
    if nao.version.name == "2.8":
        # Life's NAO rule, NumPeopleZone1 > 0: interactive, and the main dialog started
        wait_until(lambda: life.getState() == "interactive", 10.0, "Life interactive")
        wait_until(
            lambda: memory.getData("Dialog/IsStarted") in (1, "1", True),
            15.0,
            "the main dialog started",
        )
        assert key(memory, L + "ZoneOfTrackedHuman") == 1
    else:
        wait_until(
            lambda: key(memory, L + "ZoneOfTrackedHuman") == 1,
            10.0,
            "the tracked person in zone 1",
        )
        assert life.getState() == "solitary"  # no activity installed to go interactive


def test_the_keys_are_raised_empty_when_life_stops(nao, life):
    memory = nao.service("ALMemory")
    wait_until(
        lambda: key(memory, L + "NoPeopleInZones") is True, 5.0, "the keys written"
    )
    life.setState("disabled")
    wait_until(
        lambda: (
            key(memory, L + "DurationPeopleNotSeen") in (-1, None)
            and key(memory, L + "NumPeopleZone1") is None
        ),
        5.0,
        "the keys raised empty",
    )
    subscribers = [s[0] for s in nao.service("ALEngagementZones").getSubscribersInfo()]
    assert "_NaoqiSimLaunchpadPeople" not in subscribers
