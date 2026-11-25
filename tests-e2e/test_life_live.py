"""Autonomous Life with a NAO's configuration (autonomous-life.md).

2.8 only for now: its Life goes to a person by a rule of its configuration, which reads the
launchpad's people keys. Until naoqi-sim writes those keys itself (launchpad-people.md), the test
writes the one the rule reads. 2.1 goes to a person through an activity the user installs."""

import time

import pytest
from support import wait_until


@pytest.fixture
def life(nao):
    if nao.version.name != "2.8":
        pytest.skip("2.1 goes to a person through an activity the user installs")
    life = nao.service("ALAutonomousLife")
    life.setState("solitary")
    try:
        yield life
    finally:
        memory = nao.service("ALMemory")
        memory.raiseEvent("Launchpad/NumPeopleZone1", 0)
        life.setState("disabled")


def test_a_person_in_zone_1_takes_life_to_interactive_and_starts_the_dialog(nao, life):
    """The NAO rule: `Launchpad/NumPeopleZone1 > 0` for 0.25 s takes Life to interactive, and
    Life starts the main dialog. The desktop suite's own configuration has no such rule."""
    memory = nao.service("ALMemory")
    memory.raiseEvent("Launchpad/NumPeopleZone1", 0)
    time.sleep(1.0)
    assert life.getState() == "solitary"
    memory.raiseEvent("Launchpad/NumPeopleZone1", 1)
    wait_until(lambda: life.getState() == "interactive", 10.0, "Life interactive")
    wait_until(
        lambda: memory.getData("Dialog/IsStarted") in (1, "1", True),
        15.0,
        "the main dialog started",
    )
