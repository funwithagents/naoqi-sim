"""The launchpad's people keys: what naoqi-sim writes for Autonomous Life about the people around
the robot, in a robot's launchpad plugins' place (specs/services/launchpad-people.md)."""

import time

import naoqi_sim_launchpad_people_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

L = "Launchpad/"


class Extractor:
    """The people module or the zones, as subscriptions."""

    def __init__(self):
        self.subscribers: dict = {}

    def subscribe(self, name, period, precision):
        self.subscribers[name] = period

    def unsubscribe(self, name):
        self.subscribers.pop(name, None)


class Rig:
    def __init__(self, version="2.1"):
        self.data: dict = {}
        self.raised: list[tuple] = []
        self.t = 1000.0
        self.people = Extractor()
        self.zones = Extractor()
        self.launchpad = core.LaunchpadPeople(
            self.people,
            self.zones,
            self.get_data,
            lambda key, value: self.raised.append((key, value)),
            version=version,
            clock=lambda: self.t,
        )

    def get_data(self, key):
        if key not in self.data:
            raise RuntimeError("ALMemory::getData\n\tData not found " + key)
        return self.data[key]

    def event(self, name, value=None):
        """Handles one event; returns the keys it raised."""
        mark = len(self.raised)
        self.launchpad.handle(name, value)
        return self.raised[mark:]

    def zone_lists(self, z1=(), z2=(), z3=()):
        for z, ids in zip((1, 2, 3), (z1, z2, z3)):
            self.data[f"EngagementZones/PeopleInZone{z}"] = list(ids)
        return self.event(core.ZONES_UPDATED)

    def visible(self, *ids):
        self.data["PeoplePerception/VisiblePeopleList"] = list(ids)
        return self.event(core.POPULATION, [])

    def person(self, pid, **keys):
        for key, value in keys.items():
            self.data[f"PeoplePerception/Person/{pid}/{key}"] = value


def test_nothing_is_written_while_life_is_disabled():
    rig = Rig()
    assert rig.event(core.LIFE_STATE, "disabled") == []
    assert rig.zone_lists(z1=[1]) == [] and rig.visible(1) == []
    assert rig.people.subscribers == {} and rig.zones.subscribers == {}


def test_solitary_starts_it_with_nobody_in_view_as_a_nao_21_shows():
    rig = Rig()
    started = rig.event(core.LIFE_STATE, "solitary")
    # as a robot's plugin, at 200 ms, so the zones are computed without any client
    assert rig.people.subscribers == {core.NAME: 200} == rig.zones.subscribers
    # every key raised at start, measured on a real NAO 2.1 with nobody in view
    assert dict(started) == {
        L + "NumPeopleZone1": 0,
        L + "NumPeopleZone2": 0,
        L + "NumPeopleZone3": 0,
        L + "NoPeopleInZones": True,
        L + "PeopleNotSeen": True,
        L + "DurationPeopleNotSeen": 0,
        L + "ZoneOfTrackedHuman": 0,
        L + "TrackedHumanIsLookingAtRobot": 0,
        L + "SameTrackedHuman": 0,
    }


def test_a_person_walking_in_tracked_then_lost():
    rig = Rig()
    rig.event(core.LIFE_STATE, "solitary")
    rig.person(4, EngagementZone=2, IsLookingAtRobot=False)
    assert rig.zone_lists(z2=[4]) == [
        (L + "NumPeopleZone2", 1),
        (L + "NoPeopleInZones", False),
    ]
    assert rig.visible(4) == [(L + "PeopleNotSeen", False)]
    # awareness tracks the person: the same human from now on, in zone 2
    assert rig.event(core.TRACKED, 4) == [
        (L + "SameTrackedHuman", 0),
        (L + "SameTrackedHuman", 1),
        (L + "ZoneOfTrackedHuman", 2),
    ]
    # the tracked human enters zone 1; another person's zone does not count
    assert rig.event("EngagementZones/PersonEnteredZone1", 7) == []
    assert rig.event("EngagementZones/PersonEnteredZone1", 4) == [
        (L + "ZoneOfTrackedHuman", 1)
    ]
    assert rig.zone_lists(z1=[4]) == [
        (L + "NumPeopleZone1", 1),
        (L + "NumPeopleZone2", 0),
    ]
    assert rig.event(core.LOST, 4) == [
        (L + "SameTrackedHuman", 0),
        (L + "ZoneOfTrackedHuman", 0),
    ]


def test_another_tracked_human_restarts_same_tracked_human():
    rig = Rig()
    rig.event(core.LIFE_STATE, "solitary")
    rig.person(1, EngagementZone=1)
    rig.person(2, EngagementZone=3)
    rig.event(core.TRACKED, 1)
    assert rig.event(core.TRACKED, 2) == [
        (L + "SameTrackedHuman", 0),
        (L + "SameTrackedHuman", 1),
        (L + "ZoneOfTrackedHuman", 3),
    ]
    assert rig.event(core.TRACKED, 2) == []  # the same one again: nothing changes
    assert rig.event(core.TRACKED, -1) == [
        (L + "SameTrackedHuman", 0),
        (L + "ZoneOfTrackedHuman", 0),
    ]


def test_the_duration_counts_whole_seconds_since_somebody_was_visible():
    rig = Rig()
    rig.event(core.LIFE_STATE, "solitary")
    rig.visible(1)
    rig.t += 0.4
    assert rig.visible() == [(L + "PeopleNotSeen", True)]  # 0 s: unchanged
    rig.t += 0.7
    assert rig.visible() == [(L + "DurationPeopleNotSeen", 1)]
    rig.t += 0.5
    assert rig.visible() == []  # still 1
    rig.t += 3.0
    assert rig.visible() == [(L + "DurationPeopleNotSeen", 4)]
    assert rig.visible(1) == [
        (L + "PeopleNotSeen", False),
        (L + "DurationPeopleNotSeen", 0),
    ]


def test_21_stops_in_interactive_and_raises_every_key_empty():
    rig = Rig()
    rig.event(core.LIFE_STATE, "solitary")
    stopped = rig.event(core.LIFE_STATE, "interactive")
    assert rig.people.subscribers == {} and rig.zones.subscribers == {}
    assert dict(stopped) == {key: None for key in core.keys("2.1")} | {
        L + "DurationPeopleNotSeen": -1
    }
    assert rig.zone_lists(z1=[1]) == []  # stopped: nothing written
    # back to solitary, every key raised again, changed or not
    assert len(rig.event(core.LIFE_STATE, "solitary")) == len(core.keys("2.1"))


def test_28_runs_while_interactive_and_writes_the_tracked_humans_distance():
    rig = Rig("2.8")
    rig.event(core.LIFE_STATE, "solitary")
    assert L + "DurationPeopleNotSeen" not in dict(rig.raised)
    rig.person(3, EngagementZone=1, Distance=1.2)
    assert (L + "DistanceOfTrackedHuman", 1.2) in rig.event(core.TRACKED, 3)
    assert rig.event(core.LIFE_STATE, "interactive") == []  # still running
    rig.person(3, Distance=2.6)
    assert (L + "DistanceOfTrackedHuman", 2.6) in rig.visible(3)
    stopped = rig.event(core.LIFE_STATE, "disabled")
    assert dict(stopped) == {key: None for key in core.keys("2.8")}
    assert rig.people.subscribers == {}


def test_the_tracked_human_is_followed_while_stopped_and_written_at_start():
    rig = Rig()
    rig.person(5, EngagementZone=1)
    rig.event(core.TRACKED, 5)  # Life disabled: followed, not written
    assert rig.raised == []
    started = dict(rig.event(core.LIFE_STATE, "solitary"))
    assert started[L + "ZoneOfTrackedHuman"] == 1
    assert started[L + "SameTrackedHuman"] == 1


def test_the_gaze_events_of_the_tracked_human():
    rig = Rig()
    rig.event(core.LIFE_STATE, "solitary")
    rig.person(2, EngagementZone=1)
    rig.event(core.TRACKED, 2)
    assert rig.event(core.STARTS_LOOKING, 2) == [
        (L + "TrackedHumanIsLookingAtRobot", 1)
    ]
    assert rig.event(core.STOPS_LOOKING, 9) == []
    assert rig.event(core.STOPS_LOOKING, 2) == [(L + "TrackedHumanIsLookingAtRobot", 0)]


def test_events_posted_from_callbacks_are_handled_in_order_off_the_callers_thread():
    rig = Rig()
    rig.launchpad.start_worker()
    rig.data["EngagementZones/PeopleInZone1"] = [1]
    rig.launchpad.post(core.LIFE_STATE, "solitary")
    rig.launchpad.post(core.ZONES_UPDATED, None)
    deadline = time.monotonic() + 2.0
    while (L + "NumPeopleZone1", 1) not in rig.raised and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (L + "NumPeopleZone1", 1) in rig.raised


def test_the_status_key_names_the_keys_naoqi_sim_writes():
    assert core.status("2.1").split(",") == core.keys("2.1")
    assert "Launchpad/DistanceOfTrackedHuman" in core.status("2.8")
    assert "Launchpad/DurationPeopleNotSeen" not in core.status("2.8")
