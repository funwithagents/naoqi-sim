"""The people perception core: the population built from the face detector's detections, the
keys and events of the people-perception contract (specs/services/people-perception.md)."""

import math
from typing import Any, ClassVar

import naoqi_sim_face_detection_core as fc
import naoqi_sim_people_perception_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

CAMERA_Z = 0.5
# the camera 0.5 m up, the world frame 2 m behind the robot's: the three transforms
TRANSFORMS = {
    core.FRAME_TORSO: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, CAMERA_Z - 0.3, 0, 0, 0, 1],
    core.FRAME_ROBOT: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, CAMERA_Z, 0, 0, 0, 1],
    core.FRAME_WORLD: [1, 0, 0, 2.0, 0, 1, 0, 0, 0, 0, 1, CAMERA_Z, 0, 0, 0, 1],
}


def size_at(distance):
    """The angular height of a face box at that distance: what gives the distance back."""
    return 2 * math.atan(core.HEAD_HEIGHT / 2 / distance)


def face(alpha=0.0, beta=0.0, distance=1.0, track_id=0):
    return fc.Face(
        [0, 0, 90, 106],
        0.9,
        [],
        alpha,
        beta,
        size_at(distance) * 0.85,
        size_at(distance),
        track_id,
    )


def detection(faces, t=100.0, camera=0):
    return fc.Detection(
        faces, [int(t), int((t % 1) * 1e6)], camera, [0.0] * 6, [0.1] * 6, TRANSFORMS
    )


class FakeDetector:
    def __init__(self):
        self.consumers = []
        self.pokes = 0

    def add_consumer(self, c):
        self.consumers.append(c)

    def poke(self):
        self.pokes += 1


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

    def events(self, name=None):
        return [
            (k, v)
            for kind, k, v in self.sequence
            if kind == "event" and (name is None or k == name)
        ]

    def person(self, pid, key):
        return self.data[f"PeoplePerception/Person/{pid}/{key}"]


class Rig:
    def __init__(self, version="2.1"):
        self.t = 100.0
        self.detector = FakeDetector()
        self.memory = Memory()
        self.signals: list[tuple] = []
        self.population = core.Population(
            self.detector,
            self.memory.insert,
            self.memory.remove,
            self.memory.raise_event,
            signal=lambda name, *a: self.signals.append((name, *a)),
            version=version,
            clock=lambda: self.t,
        )
        self.population.subscribe("ALBasicAwareness", 200, 0.0)

    def see(self, faces, dt=0.2):
        self.t += dt
        self.population.on_detection(detection(faces, self.t))


def test_a_face_becomes_a_person_at_the_distance_its_size_gives_in_the_three_frames():
    rig = Rig()
    rig.see([face(alpha=0.0, beta=0.0, distance=1.0)])
    m = rig.memory
    assert (
        m.data["PeoplePerception/PeopleList"]
        == [1]
        == m.data["PeoplePerception/VisiblePeopleList"]
    )
    assert m.data["PeoplePerception/NonVisiblePeopleList"] == []
    assert m.person(1, "PositionInRobotFrame") == pytest.approx([1.0, 0.0, CAMERA_Z])
    assert m.person(1, "PositionInTorsoFrame") == pytest.approx(
        [1.0, 0.0, CAMERA_Z - 0.3]
    )
    assert m.person(1, "PositionInWorldFrame") == pytest.approx([3.0, 0.0, CAMERA_Z])
    assert m.person(1, "Distance") == pytest.approx(math.hypot(1.0, CAMERA_Z))
    yaw, pitch = m.person(1, "AnglesYawPitch")
    assert yaw == pytest.approx(0.0) and pitch == pytest.approx(
        -math.atan2(CAMERA_Z, 1.0)
    )
    assert m.person(1, "IsVisible") is True and m.person(1, "IsFaceDetected") is True
    assert m.person(1, "NotSeenSince") == 0.0 and m.person(1, "PresentSince") == 0.0
    assert m.person(1, "RealHeight") == pytest.approx(CAMERA_Z + core.HEAD_TOP)


def test_the_angles_place_the_person_to_the_left_and_the_events_follow_the_keys():
    rig = Rig()
    rig.see([face(alpha=0.3, distance=2.0)])
    m = rig.memory
    x, y, _ = m.person(1, "PositionInRobotFrame")
    assert (
        y > 0
        and math.atan2(y, x) == pytest.approx(0.3)
        and math.hypot(x, y) == pytest.approx(2.0)
    )
    assert m.person(1, "AnglesYawPitch")[0] == pytest.approx(0.3)
    kinds = [(kind, key) for kind, key, _ in m.sequence]
    last_insert = max(i for i, (kind, _) in enumerate(kinds) if kind == "insert")
    first_event = min(i for i, (kind, _) in enumerate(kinds) if kind == "event")
    assert last_insert < first_event  # the tracker reads the keys when the event comes
    assert [k for k, _ in m.events()] == [
        "PeoplePerception/JustArrived",
        "PeoplePerception/PopulationUpdated",
        "PeoplePerception/PeopleDetected",
    ]
    assert m.events("PeoplePerception/JustArrived") == [
        ("PeoplePerception/JustArrived", 1)
    ]
    stamp, people, _, pose_robot, camera = m.events(
        "PeoplePerception/PopulationUpdated"
    )[0][1]
    assert stamp == [100, 200000] and camera == 0 and pose_robot == [0.1] * 6
    ((pid, distance, _, yaw),) = people
    assert (
        pid == 1
        and distance == pytest.approx(math.hypot(2.0, CAMERA_Z))
        and yaw == pytest.approx(0.3)
    )
    assert rig.signals == [("justArrived", 1)]


def test_a_face_keeps_its_person_while_it_moves_a_little_and_two_faces_are_two_people():
    rig = Rig()
    rig.see([face(alpha=0.0), face(alpha=0.5, track_id=1)])
    assert rig.memory.data["PeoplePerception/PeopleList"] == [1, 2]
    rig.see(
        [face(alpha=0.1), face(alpha=0.55, track_id=1)]
    )  # 0.1 m and 0.05 m away: the same people
    assert rig.memory.data["PeoplePerception/PeopleList"] == [1, 2]
    assert rig.memory.person(1, "AnglesYawPitch")[0] == pytest.approx(0.1)
    rig.see([face(alpha=-0.4)])  # 0.4 m from either: a third person
    assert rig.memory.data["PeoplePerception/PeopleList"] == [1, 2, 3]
    # the head turns 0.3 rad: the face's angles change, the person's position in the world does not
    turned = detection([face(alpha=-0.7)], rig.t + 0.2)
    turned.transforms = {
        f: [
            math.cos(0.3),
            -math.sin(0.3),
            0,
            m[3],
            math.sin(0.3),
            math.cos(0.3),
            0,
            m[7],
            0,
            0,
            1,
            m[11],
            0,
            0,
            0,
            1,
        ]
        for f, m in TRANSFORMS.items()
    }
    rig.t += 0.2
    before = rig.memory.person(3, "PositionInWorldFrame")
    rig.population.on_detection(turned)
    assert rig.memory.data["PeoplePerception/PeopleList"] == [
        1,
        2,
        3,
    ]  # no fourth person
    assert rig.memory.person(3, "PositionInWorldFrame") == pytest.approx(
        before, abs=0.02
    )
    assert rig.memory.person(3, "AnglesYawPitch")[0] == pytest.approx(
        -0.4
    )  # the robot's frame, unchanged
    assert [v for k, v in rig.memory.events("PeoplePerception/JustArrived")] == [
        1,
        2,
        3,
    ]


def test_a_person_turns_invisible_then_leaves_after_the_two_delays():
    rig = Rig()
    rig.see([face()])
    rig.see([], dt=1.5)
    m = rig.memory
    assert (
        m.data["PeoplePerception/VisiblePeopleList"] == [1]
        and m.person(1, "IsVisible") is True
    )
    rig.see([], dt=0.6)  # 2.1 s unseen: past TimeBeforeVisiblePersonDisappears
    assert m.data["PeoplePerception/VisiblePeopleList"] == [] and m.data[
        "PeoplePerception/NonVisiblePeopleList"
    ] == [1]
    assert m.person(1, "IsVisible") is False and m.person(
        1, "NotSeenSince"
    ) == pytest.approx(2.1)
    assert m.data["PeoplePerception/PeopleList"] == [1]
    assert (
        m.events("PeoplePerception/PopulationUpdated")[-1][1][1] == []
    )  # nobody visible
    rig.see([], dt=8.0)  # 10.1 s: past TimeBeforePersonDisappears
    assert (
        m.data["PeoplePerception/PeopleList"] == []
        and m.data["PeoplePerception/NonVisiblePeopleList"] == []
    )
    assert m.events("PeoplePerception/JustLeft") == [("PeoplePerception/JustLeft", 1)]
    assert not [k for k in m.data if k.startswith("PeoplePerception/Person/")]
    assert ("justLeft", 1) in rig.signals
    rig.see([face()])
    assert m.data["PeoplePerception/PeopleList"] == [2]  # ids are never reused


def test_the_delays_and_the_range_are_settings():
    rig = Rig()
    p = rig.population
    p.set("TimeBeforeVisiblePersonDisappears", 0.1)
    p.set("TimeBeforePersonDisappears", 0.3)
    rig.see([face()])
    rig.see([], dt=0.2)
    assert rig.memory.data["PeoplePerception/NonVisiblePeopleList"] == [1]
    rig.see([], dt=0.2)
    assert rig.memory.data["PeoplePerception/PeopleList"] == []
    rig.see([face(distance=4.0)])  # beyond the default 3.5 m: not a person
    assert rig.memory.data["PeoplePerception/PeopleList"] == []
    p.set_maximum_detection_range(5.0)
    assert rig.memory.events("PeoplePerception/MaximumDetectionRangeUpdated") == [
        ("PeoplePerception/MaximumDetectionRangeUpdated", 5.0)
    ]
    assert ("maximumDetectionRangeChanged", 5.0) in rig.signals
    rig.see([face(distance=4.0)])
    assert rig.memory.data["PeoplePerception/PeopleList"] == [2]


def test_reset_population_forgets_everyone_and_face_detection_off_sees_nobody():
    rig = Rig()
    rig.see([face(), face(alpha=0.5)])
    rig.population.reset_population()
    m = rig.memory
    assert m.data["PeoplePerception/PeopleList"] == [] and not [
        k for k in m.data if "/Person/" in k
    ]
    assert m.events("PeoplePerception/PopulationReset") == [
        ("PeoplePerception/PopulationReset", 0)
    ]
    assert ("populationReset",) in rig.signals
    rig.population.set("FaceDetectionEnabled", False)
    rig.see([face()])
    assert m.data["PeoplePerception/PeopleList"] == []


def test_the_module_wants_detections_only_while_subscribed_and_not_paused():
    rig = Rig()
    assert rig.population.wants() == 200 and rig.detector.pokes >= 1
    rig.population.pause(True)
    assert rig.population.wants() is None and not rig.population.isProcessing()
    rig.population.pause(False)
    rig.population.unsubscribe("ALBasicAwareness")
    assert rig.population.wants() is None
    assert (
        rig.population.getEventList() == core.EVENTS
        and rig.population.getMemoryKeyList() == core.KEYS
    )


def test_the_table_serves_every_setting_and_the_hidden_methods():
    rig = Rig()

    import naoqi_sim_perception_stubs_core as ext

    class Shell:
        HANDLERS: ClassVar[dict] = {}

        def _call(self, name, args):
            return ext.call(rig.population, Shell.HANDLERS, name, args)

    ext.install(Shell, core.METHODS)
    s: Any = Shell()
    s.setTimeBeforePersonDisappears(3.5)
    assert s.getTimeBeforePersonDisappears() == 3.5
    s.setFastModeEnabled(True)
    assert s.isFastModeEnabled() is True
    s.setMaximumDetectionRange(1.0)
    assert s.getMaximumDetectionRange() == 1.0 and rig.signals[-1] == (
        "maximumDetectionRangeChanged",
        1.0,
    )
    assert (
        s._getLTMContent() == []
        and s._matchInDatabase(3) == -1
        and s._removeAllFromLTM() is True
    )
    s._setDetectionMode("fast")
    assert s._getDetectionMode() == "fast"
    assert "ALPeoplePerception" in s.whoami()
