"""The engagement zones core: a NAO's zone rule, its settings, and the zones of the people module's
population, written and raised as a NAO does (specs/services/engagement-zones.md)."""

import math
from typing import Any, ClassVar

import naoqi_sim_engagement_zones_core as core
import naoqi_sim_face_detection_core as fc
import naoqi_sim_people_perception_core as people_core
import naoqi_sim_perception_stubs_core as ext
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

Z = "EngagementZones/"


class Memory:
    """Records inserts, removals and events in one sequence, so the order is checkable."""

    def __init__(self):
        self.data: dict = {}
        self.sequence: list[tuple] = []

    def insert(self, key, value):
        self.data[key] = value
        self.sequence.append(("insert", key, value))

    def remove(self, key):
        del self.data[key]
        self.sequence.append(("remove", key, None))

    def raise_event(self, key, value):
        self.sequence.append(("event", key, value))

    def events(self, since=0):
        return [(k, v) for kind, k, v in self.sequence[since:] if kind == "event"]


class People:
    """The people module as the zones see it: a population source that may be processing."""

    def __init__(self):
        self.consumers: list = []
        self.processing = True

    def add_consumer(self, c):
        self.consumers.append(c)

    def isProcessing(self):
        return self.processing


class Shell:
    """The module's NAOqi methods, generated from its table as the shells generate them."""

    HANDLERS: ClassVar[dict] = {}

    def __init__(self, module):
        self.module = module

    def _call(self, name, args):
        return ext.call(self.module, self.HANDLERS, name, args)


ext.install(Shell, core.METHODS, varargs=True)


class Rig:
    def __init__(self, subscribe=True):
        self.memory = Memory()
        self.people = People()
        self.signals: list[tuple] = []
        self.module = core.Zones(
            self.people,
            self.memory.insert,
            self.memory.remove,
            self.memory.raise_event,
            signal=lambda name, *a: self.signals.append((name, *a)),
        )
        self.zones: Any = Shell(self.module)
        if subscribe:
            self.zones.subscribe("client", 200, 0.0)

    def population(self, *people):
        """People as (id, x, y): returns the events this population raised."""
        mark = len(self.memory.sequence)
        self.module.on_population([(pid, [x, y, 1.6]) for pid, x, y in people])
        return self.memory.events(mark)

    def lists(self):
        return [self.memory.data[Z + f"PeopleInZone{z}"] for z in (1, 2, 3)]


def polar(degrees, distance=1.0):
    return (
        distance * math.cos(math.radians(degrees)),
        distance * math.sin(math.radians(degrees)),
    )


@pytest.mark.parametrize(
    ("x", "y", "zone"),
    [
        (1.5, 0.0, 1),  # both limits inclusive
        (1.5001, 0.0, 2),
        (2.5, 0.0, 2),
        (2.5001, 0.0, 3),
        (0.0, 1.0, 2),  # exactly sideways: not under 90 degrees, on the side
        (0.0, 2.0, 3),
        (0.0, 0.0, 1),  # the origin
        (-1.0, 0.0, 1),  # behind counts as in front
        (-1.0, -1.0, 1),
    ],
)
def test_the_zone_of_a_point_with_the_default_limits(x, y, zone):
    assert core.zone_of(x, y, 1.5, 2.5, 90.0) == zone


def test_the_angle_is_to_the_x_axis_strictly_under_the_limit():
    # with a limit of 60: a point at 121 degrees is in front (59 to the axis), at 120 on the side
    assert core.zone_of(*polar(121), 1.5, 2.5, 60.0) == 1
    assert core.zone_of(*polar(120), 1.5, 2.5, 60.0) == 2
    assert core.zone_of(*polar(29.99), 1.5, 2.5, 30.0) == 1
    assert core.zone_of(*polar(30.01), 1.5, 2.5, 30.0) == 2


def test_compute_answers_for_a_point_at_any_height_and_for_a_camera_ray():
    zones = Rig(subscribe=False).zones  # answers without a subscriber
    assert zones.computeEngagementZone(1.4, 0.0, 5.0) == 1
    assert zones.computeEngagementZone(2.0, 0.0, -1.0) == 2
    # 2 m along the camera's axis from a camera 0.5 m up looking ahead: x 2 m, zone 2
    camera = [0.0, 0.0, 0.5, 0.0, 0.0, 0.0]
    assert zones.computeEngagementZone(0.0, 0.0, 2.0, camera) == 2
    assert zones.computeEngagementZone(0.0, 0.0, 1.0, camera) == 1
    # the camera turned 90 degrees to the left: the point is sideways, on the side
    turned = [0.0, 0.0, 0.5, 0.0, 0.0, math.pi / 2]
    assert zones.computeEngagementZone(0.0, 0.0, 1.0, turned) == 2
    # an image angle to the left, the camera ahead: in front within 90 degrees
    assert zones.computeEngagementZone(0.5, 0.0, 1.0, camera) == 1


def test_each_setter_takes_a_naos_values_raises_its_event_and_returns_nothing():
    rig = Rig()
    z = rig.zones
    assert z.setLimitAngle(60.0) is None
    assert z.setLimitAngle(0.0) is None and z.setLimitAngle(180.0) is None
    assert z.setSecondLimitDistance(3.0) is None
    assert z.setFirstLimitDistance(0.0) is None and z.setFirstLimitDistance(2.0) is None
    assert z.getLimitAngle() == 180.0
    assert (z.getFirstLimitDistance(), z.getSecondLimitDistance()) == (2.0, 3.0)
    assert rig.memory.events() == [
        (Z + "LimitAngleUpdated", 60.0),
        (Z + "LimitAngleUpdated", 0.0),
        (Z + "LimitAngleUpdated", 180.0),
        (Z + "SecondLimitDistanceUpdated", 3.0),
        (Z + "FirstLimitDistanceUpdated", 0.0),
        (Z + "FirstLimitDistanceUpdated", 2.0),
    ]
    assert rig.signals[0] == ("limitAngleChanged", 60.0)
    assert ("secondLimitChanged", 3.0) in rig.signals
    assert ("firstLimitChanged", 2.0) in rig.signals


@pytest.mark.parametrize(
    ("setter", "value", "text"),
    [
        ("setLimitAngle", -1.0, core.ANGLE_ERROR),
        ("setLimitAngle", 180.5, core.ANGLE_ERROR),
        ("setFirstLimitDistance", -0.1, core.FIRST_ERROR),
        ("setFirstLimitDistance", 2.5, core.FIRST_ERROR),  # not under the second
        ("setSecondLimitDistance", 1.5, core.SECOND_ERROR),  # not over the first
        ("setSecondLimitDistance", -1.0, core.SECOND_ERROR),
    ],
)
def test_a_refused_value_raises_a_naos_text_and_changes_nothing(setter, value, text):
    rig = Rig()
    with pytest.raises(RuntimeError, match=text):
        getattr(rig.zones, setter)(value)
    assert rig.zones.getLimitAngle() == 90.0
    assert rig.zones.getFirstLimitDistance() == 1.5
    assert rig.zones.getSecondLimitDistance() == 2.5
    assert rig.memory.events() == [] and rig.signals == []


def test_people_entering_approaching_and_moving_away():
    rig = Rig()
    # the first population, nobody in it: the lists written and the update raised
    assert rig.population() == [(Z + "PeopleInZonesUpdated", None)]
    assert rig.lists() == [[], [], []]
    # a person sorted for the first time: entered, and nothing else
    assert rig.population((1, 2.0, 0.0)) == [
        (Z + "PersonEnteredZone2", 1),
        (Z + "PeopleInZonesUpdated", None),
    ]
    assert rig.lists() == [[], [1], []]
    assert rig.memory.data["PeoplePerception/Person/1/EngagementZone"] == 2
    # nothing changed: the key is written again, no event, no list
    assert rig.population((1, 2.1, 0.0)) == []
    # closer: approached, then entered
    assert rig.population((1, 1.0, 0.0)) == [
        (Z + "PersonApproached", 1),
        (Z + "PersonEnteredZone1", 1),
        (Z + "PeopleInZonesUpdated", None),
    ]
    assert rig.lists() == [[1], [], []]
    # a second person far away while the first moves away
    assert rig.population((1, 2.0, 0.0), (2, 3.0, 0.0)) == [
        (Z + "PersonMovedAway", 1),
        (Z + "PersonEnteredZone2", 1),
        (Z + "PersonEnteredZone3", 2),
        (Z + "PeopleInZonesUpdated", None),
    ]
    assert rig.lists() == [[], [1], [2]]
    assert rig.memory.data["PeoplePerception/Person/2/EngagementZone"] == 3


def test_a_person_leaving_while_others_stay_stays_listed_until_a_change():
    rig = Rig()
    rig.population((1, 1.0, 0.0), (2, 2.0, 0.0))
    assert (
        rig.population((2, 2.0, 0.0)) == []
    )  # 1 is gone: no event, the lists unchanged
    assert rig.lists() == [[1], [2], []]
    rig.population((2, 1.0, 0.0))  # 2 changes zone: the lists are rewritten
    assert rig.lists() == [[2], [], []]
    # the population empties: the lists emptied and the update raised, once
    assert rig.population() == [(Z + "PeopleInZonesUpdated", None)]
    assert rig.lists() == [[], [], []]
    assert rig.population() == []


def test_a_changed_setting_applies_from_the_next_population():
    rig = Rig()
    rig.population((1, 2.0, 0.0))
    rig.zones.setFirstLimitDistance(2.2)
    assert rig.memory.data["PeoplePerception/Person/1/EngagementZone"] == 2
    assert (Z + "PersonApproached", 1) in rig.population((1, 2.0, 0.0))
    assert rig.memory.data["PeoplePerception/Person/1/EngagementZone"] == 1


def test_without_a_subscriber_or_paused_nothing_is_written():
    rig = Rig(subscribe=False)
    assert rig.population((1, 1.0, 0.0)) == []
    assert "PeoplePerception/Person/1/EngagementZone" not in rig.memory.data
    assert not rig.zones.isProcessing()
    rig.zones.subscribe("client", 200, 0.0)
    assert rig.zones.isProcessing()
    rig.people.processing = False  # nobody makes the people module process
    assert not rig.zones.isProcessing()
    rig.people.processing = True
    rig.zones.pause(True)
    assert rig.population((1, 1.0, 0.0)) == [] and not rig.zones.isProcessing()


def test_the_last_subscriber_leaving_empties_the_six_lists():
    rig = Rig()
    rig.population((1, 1.0, 0.0))
    mark = len(rig.memory.sequence)
    rig.zones.unsubscribe("client")
    assert rig.memory.events(mark) == [
        (Z + "PeopleInZonesUpdated", None),
        (Z + "MovementsInZonesUpdated", None),
    ]
    assert all(rig.memory.data[k] == [] for k in core.KEYS)
    # subscribed again, the person is sorted for the first time again
    rig.zones.subscribe("client", 200, 0.0)
    assert (Z + "PersonEnteredZone1", 1) in rig.population((1, 1.0, 0.0))


def test_the_movement_lists_stay_empty():
    rig = Rig()
    rig.population((1, 1.0, 0.0))
    assert all(rig.memory.data[k] == [] for k in core.MOVEMENT_LISTS)
    assert all("Movements" not in k for k, _ in rig.memory.events())


# --- with the real people module ----------------------------------------------------------

TRANSFORMS = {  # the camera 0.5 m up at the robot's origin, in the three frames
    people_core.FRAME_TORSO: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0.2, 0, 0, 0, 1],
    people_core.FRAME_ROBOT: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0.5, 0, 0, 0, 1],
    people_core.FRAME_WORLD: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0.5, 0, 0, 0, 1],
}


class Detector:
    def add_consumer(self, c):
        pass

    def poke(self):
        pass


def face_at(distance):
    size = 2 * math.atan(people_core.HEAD_HEIGHT / 2 / distance)
    return fc.Face([0, 0, 90, 106], 0.9, [], 0.0, 0.0, size * 0.85, size, 0)


def test_a_persons_zone_is_in_memory_when_the_people_events_come():
    memory = Memory()
    population = people_core.Population(
        Detector(), memory.insert, memory.remove, memory.raise_event, clock=lambda: 1.0
    )
    zones: Any = Shell(
        core.Zones(population, memory.insert, memory.remove, memory.raise_event)
    )
    population.subscribe("awareness", 200, 0.0)
    zones.subscribe("launchpad", 200, 0.0)
    population.on_detection(
        fc.Detection([face_at(1.0)], [1, 0], 0, [0.0] * 6, [0.0] * 6, TRANSFORMS)
    )
    sequence = [(kind, key) for kind, key, _ in memory.sequence]
    zone_key = sequence.index(("insert", "PeoplePerception/Person/1/EngagementZone"))
    entered = sequence.index(("event", Z + "PersonEnteredZone1"))
    arrived = sequence.index(("event", "PeoplePerception/JustArrived"))
    assert zone_key < entered < arrived  # a NAO raises both at the same moment
    assert memory.data[Z + "PeopleInZone1"] == [1]
    # the person gone, its zone key goes with its other keys
    population.reset_population()
    assert "PeoplePerception/Person/1/EngagementZone" not in memory.data
    assert memory.data[Z + "PeopleInZone1"] == []
