"""Face detection and people perception on a running naoqi-sim stack, driven by face props
(specs/services/face-detection.md, people-perception.md, perception-stubs.md): a face prop spawned
in the robot's frame gives FaceDetected at the angles the camera's pose predicts and a person
where the prop is, the built-in awareness turns the head to it, the stubs answer, and the service
list is a normal boot's plus ALFaceDetection."""

import math
import time
from collections.abc import Callable, Iterator

import pytest
from support import known_issue

WORLD = 1  # ALMotion's FRAME_WORLD
TOP_CAMERA = "CameraTop"
FACE_AHEAD = (
    1.0,
    0.3,
    0.5,
)  # a face 1 m ahead, 0.3 m to the robot's left, at head height (FRAME_ROBOT)
PLANE_HEIGHT = 0.40  # naoqi-viewer's face plane (m); the pictured face about half of it
STUBS = {
    "2.1": ["ALEngagementZones", "ALGazeAnalysis", "ALSittingPeopleDetection"],
    "2.8": [
        "ALEngagementZones",
        "ALGazeAnalysis",
        "ALSittingPeopleDetection",
        "ALWavingDetection",
        "_UserIdentification",
    ],
}


def wait_until(check: Callable[[], bool], timeout: float, what: str) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.1)
    pytest.fail(f"{what} within {timeout} s")


class Events:
    """The values an ALMemory event was raised with, as they come."""

    def __init__(self, nao, *names: str):
        self.values: list[tuple[str, object]] = []
        self.subscribers = []
        memory = nao.service("ALMemory")
        for name in names:
            subscriber = memory.subscriber(name)
            subscriber.signal.connect(
                lambda value, name=name: self.values.append((name, value))
            )
            self.subscribers.append(subscriber)

    def of(self, name: str) -> list:
        return [v for n, v in self.values if n == name]


@pytest.fixture
def standing(nao) -> Iterator[None]:
    """The robot standing, its head straight, as a NAO looking at a visitor; resting after."""
    motion = nao.service("ALMotion")
    motion.wakeUp()
    nao.service("ALRobotPosture").goToPosture("StandInit", 0.8)
    motion.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], 0.8, True)
    time.sleep(0.5)
    try:
        yield
    finally:
        motion.rest()


@pytest.fixture
def face(nao, standing):
    """A face prop in front of the robot, looking at it (its picture back along the robot's axis);
    its state, with the prop's centre in the world frame."""
    state = nao.sim.props.spawn("face", FACE_AHEAD, frame="robot")
    try:
        yield state
    finally:
        nao.sim.props.despawn(state.name)


@pytest.fixture
def faces(nao):
    """ALFaceDetection subscribed at 5 Hz, as awareness subscribes, for the test; unsubscribed after."""
    detection = nao.service("ALFaceDetection")
    detection.subscribe("test_perception_live", 200, 0.0)
    try:
        yield detection
    finally:
        detection.unsubscribe("test_perception_live")


@pytest.fixture
def people(nao):
    perception = nao.service("ALPeoplePerception")
    perception.subscribe("test_perception_live", 200, 0.0)
    try:
        yield perception
    finally:
        perception.unsubscribe("test_perception_live")


def angles_to(motion, target) -> tuple[float, float]:
    """A point's yaw and pitch from the top camera, in the camera's frame: where a pinhole
    camera at its pose sees it (NAOqi's angles: yaw positive to the left, pitch positive
    downward; the camera's own pitch is positive nose-down, so a level target in front of a
    camera tilted down appears above its axis, at a negative pitch)."""
    x, y, z, _, pitch, heading = motion.getPosition(TOP_CAMERA, WORLD, True)
    dx, dy, dz = target[0] - x, target[1] - y, target[2] - z
    yaw = math.atan2(dy, dx) - heading
    elevation = math.atan2(dz, math.hypot(dx, dy))
    return yaw, -(elevation + pitch)


def face_detected(nao):
    try:
        return nao.service("ALMemory").getData("FaceDetected")
    except RuntimeError:  # no key yet
        return None


def test_the_robot_says_its_perception_is_the_engine_and_lists_the_stubs(nao):
    status = nao.runner.run(nao.sim.status())
    assert status.perception_source == "engine"
    memory = nao.service("ALMemory")
    assert memory.getData("NaoqiSim/Perception/Source") == "engine"
    assert memory.getData("NaoqiSim/Perception/Stubs") == ",".join(
        STUBS[nao.version.name]
    )


def test_a_face_prop_is_detected_where_the_camera_pose_says(nao, face, faces):
    wait_until(lambda: bool(face_detected(nao)), 4.0, "a face detected")
    value = face_detected(nao)
    assert value is not None
    stamp, infos, pose_torso, pose_robot, camera = value
    assert (
        len(stamp) == 2
        and camera == 0
        and len(pose_torso) == 6
        and len(pose_robot) == 6
    )
    assert infos[-1] == [] and len(infos) == 2, "one face, and the reco info"
    shape, extra = infos[0]
    _, alpha, beta, size_x, size_y = shape
    yaw, pitch = angles_to(nao.service("ALMotion"), face.pos)
    assert alpha == pytest.approx(yaw, abs=0.05)
    assert beta == pytest.approx(pitch, abs=0.05)
    # the pictured face is about half the plane: about 0.2 m at 1 m, 0.18 rad at VGA
    expected = 2 * math.atan(PLANE_HEIGHT / 2 * 0.5 / 1.0)
    assert size_y == pytest.approx(expected, rel=0.25)
    assert 0 < size_x < size_y
    assert len(extra) == 9 and [len(p) for p in extra[3:]] == [14, 14, 6, 6, 6, 16]
    # the face gone: the empty value, once
    nao.sim.props.despawn(face.name)
    wait_until(lambda: face_detected(nao) == [], 3.0, "the empty value")


def test_a_face_prop_is_a_person_where_the_prop_is(nao, face, people):
    events = Events(
        nao,
        "PeoplePerception/JustArrived",
        "PeoplePerception/JustLeft",
        "PeoplePerception/PopulationUpdated",
    )
    memory = nao.service("ALMemory")
    wait_until(
        lambda: memory.getData("PeoplePerception/PeopleList") != [], 4.0, "a person"
    )
    (pid,) = memory.getData("PeoplePerception/PeopleList")
    assert memory.getData("PeoplePerception/VisiblePeopleList") == [pid]
    position = memory.getData(f"PeoplePerception/Person/{pid}/PositionInWorldFrame")
    assert position == pytest.approx(list(face.pos), abs=0.25)
    # from the camera, as a NAO measures them (people-perception.md)
    camera = nao.service("ALMotion").getPosition(TOP_CAMERA, WORLD, True)
    assert memory.getData(f"PeoplePerception/Person/{pid}/Distance") == pytest.approx(
        math.dist(camera[:3], face.pos), abs=0.25
    )
    yaw, pitch = angles_to(nao.service("ALMotion"), face.pos)
    assert memory.getData(
        f"PeoplePerception/Person/{pid}/AnglesYawPitch"
    ) == pytest.approx([yaw, pitch], abs=0.07)
    assert memory.getData(
        f"PeoplePerception/Person/{pid}/IsVisible"
    )  # a bool, an int on 2.1
    wait_until(
        lambda: len(events.of("PeoplePerception/PopulationUpdated")) >= 3,
        3.0,
        "updates at 5 Hz",
    )
    assert events.of("PeoplePerception/JustArrived") == [pid]
    update = events.of("PeoplePerception/PopulationUpdated")[-1]
    assert update[1][0][0] == pid and len(update) == 5
    # paused: no more updates, the subscription kept
    people.pause(True)
    before = len(events.of("PeoplePerception/PopulationUpdated"))
    time.sleep(1.0)
    assert len(events.of("PeoplePerception/PopulationUpdated")) == before
    assert people.isPaused()
    assert [
        "test_perception_live",
        200,
        0.0,
    ] in people.getSubscribersInfo()  # kept; life's awareness may be there too
    people.pause(False)
    # gone: the person leaves after TimeBeforePersonDisappears
    nao.sim.props.despawn(face.name)
    # gone: invisible after the built-in's 2 s, forgotten after its 10 s
    wait_until(
        lambda: memory.getData("PeoplePerception/VisiblePeopleList") == [],
        4.0,
        "the person invisible",
    )
    assert memory.getData("PeoplePerception/NonVisiblePeopleList") == [pid]
    wait_until(
        lambda: memory.getData("PeoplePerception/PeopleList") == [],
        13.0,
        "the person leaving",
    )
    assert events.of("PeoplePerception/JustLeft") == [pid]


def test_awareness_turns_the_head_toward_a_face(nao, standing):
    """The closed loop: the built-in ALBasicAwareness, fed by our people perception, turns the
    head to a face spawned to the left, and the face ends up near the camera's axis."""
    yaw = 0.4
    awareness = nao.service("ALBasicAwareness")
    motion = nao.service("ALMotion")
    # Restarted in head mode before the face appears: on 2.8 life runs awareness from boot in
    # BodyRotation mode and would track the face before the test watches, and a tracking that
    # failed once (the FastPersonTracking modularity process, naoqi-fidelity.md) leaves it deaf
    # until restarted.
    awareness.stopAwareness()
    awareness.setTrackingMode("Head")
    awareness.startAwareness()
    events = Events(nao, "ALBasicAwareness/HumanTracked")
    state = nao.sim.props.spawn(
        "face", (math.cos(yaw), math.sin(yaw), 0.5), frame="robot"
    )
    try:
        wait_until(
            lambda: bool(events.of("ALBasicAwareness/HumanTracked")),
            8.0,
            "a human tracked",
        )
        wait_until(
            lambda: abs(motion.getAngles("HeadYaw", True)[0] - yaw) < 0.15,
            6.0,
            "the head turned to the face",
        )
        alpha, _ = angles_to(motion, state.pos)
        assert abs(alpha) < 0.2, "the face near the camera's axis"
    finally:
        awareness.stopAwareness()
        nao.sim.props.despawn(state.name)


def test_awareness_follows_a_face_that_moves(nao, standing):
    """After its first look, awareness keeps the head on the person as they move. That runs
    through the fast person tracking process, which the entrypoint puts in 2D as on a real NAO:
    in the desktop's default 3D mode it looked in a depth camera nothing feeds, lost the person at
    once, and the head never followed (container/naoqi-fidelity.md)."""
    motion = nao.service("ALMotion")
    awareness = nao.service("ALBasicAwareness")
    awareness.stopAwareness()
    awareness.setTrackingMode("Head")
    awareness.startAwareness()
    camera_z = motion.getPosition(TOP_CAMERA, 2, True)[2]  # FRAME_ROBOT
    state = nao.sim.props.spawn(
        "face", (math.cos(0.3), math.sin(0.3), camera_z), frame="robot"
    )
    try:
        wait_until(
            lambda: motion.getAngles("HeadYaw", True)[0] > 0.15, 8.0, "the first look"
        )
        nao.sim.props.place(
            state.name,
            (math.cos(-0.3), math.sin(-0.3), camera_z),
            duration=1.5,
            frame="robot",
        )
        wait_until(
            lambda: motion.getAngles("HeadYaw", True)[0] < -0.12,
            8.0,
            "the head following the face to the other side",
        )
        assert nao.service("ALTracker").isTargetLost() is False
    finally:
        awareness.stopAwareness()
        nao.sim.props.despawn(state.name)


def test_awareness_raises_the_head_to_a_face_above_the_camera(nao, standing):
    """A face above the camera, as a visitor's face is above a NAO's: awareness raises the head
    until the face is on the camera's axis. Measured from the floor, the angles sent the head far
    past the face (or out of its reach for a face close by: the head never moved with a webcam);
    bobby showed they are the camera's (people-perception.md). The face sits 1.5 m ahead and
    0.2 m above the camera, about 0.13 rad up: fully in both versions' top camera, whose view ends
    about 0.42 rad up, so the detector sees it whole."""
    motion = nao.service("ALMotion")
    awareness = nao.service("ALBasicAwareness")
    awareness.stopAwareness()
    awareness.setTrackingMode("Head")
    awareness.startAwareness()
    camera_z = motion.getPosition(TOP_CAMERA, 2, True)[2]  # FRAME_ROBOT
    pitch_before = motion.getAngles("HeadPitch", True)[0]
    state = nao.sim.props.spawn("face", (1.5, 0.15, camera_z + 0.2), frame="robot")
    try:
        wait_until(
            lambda: motion.getAngles("HeadPitch", True)[0] < pitch_before - 0.06,
            8.0,
            "the head raised toward the face",
        )
        time.sleep(2.0)  # settled
        yaw, pitch = angles_to(motion, state.pos)
        assert abs(pitch) < 0.1 and abs(yaw) < 0.1, "the face on the camera's axis"
    finally:
        awareness.stopAwareness()
        nao.sim.props.despawn(state.name)


def test_the_last_subscriber_leaving_clears_the_population(nao, standing):
    """As a NAO does (bobby, Oct 29, 2026): cleared at once, with PopulationReset."""
    nao.service(
        "ALBasicAwareness"
    ).stopAwareness()  # 2.8's life runs it: no other subscriber
    perception = nao.service("ALPeoplePerception")
    assert perception.getSubscribersInfo() == []
    memory = nao.service("ALMemory")
    state = nao.sim.props.spawn("face", FACE_AHEAD, frame="robot")
    events = Events(
        nao, "PeoplePerception/PopulationReset", "PeoplePerception/JustLeft"
    )
    try:
        perception.subscribe("test_perception_live", 200, 0.0)
        wait_until(
            lambda: memory.getData("PeoplePerception/PeopleList") != [], 4.0, "a person"
        )
        perception.unsubscribe("test_perception_live")
        wait_until(
            lambda: memory.getData("PeoplePerception/PeopleList") == [],
            1.0,
            "the population cleared",
        )
        wait_until(
            lambda: bool(events.of("PeoplePerception/PopulationReset")),
            1.0,
            "PopulationReset",
        )
        assert events.of("PeoplePerception/JustLeft") == []
    finally:
        nao.sim.props.despawn(state.name)


def test_the_stubs_answer_the_extractor_api_without_detecting(nao):
    for name in STUBS[nao.version.name]:
        if name == "_UserIdentification":
            continue
        stub = nao.service(name)
        stub.subscribe("test")
        assert stub.getSubscribersInfo() == [["test", 200, 0.0]], name
        assert stub.isProcessing() is False and stub.isPaused() is False
        stub.unsubscribe("test")
        assert stub.getSubscribersInfo() == []
    zones = nao.service("ALEngagementZones")
    zones.setFirstLimitDistance(1.2)
    assert zones.getFirstLimitDistance() == pytest.approx(1.2)
    assert zones.computeEngagementZone(0.5, 0.0, 0.0) == 0


def test_the_service_list_is_a_naos_plus_face_detection(nao):
    names = {s["name"] for s in nao.session.services()}
    assert {
        "ALFaceDetection",
        "ALPeoplePerception",
        "ALBasicAwareness",
        "ALTracker",
    } <= names
    assert set(STUBS[nao.version.name]) <= names
    if nao.version.name == "2.1":
        assert "ALWavingDetection" not in names  # a real NAO 2.1 has none
        assert {"ALFastPersonTracking", "ALFindPersonHead"} <= names  # the suite's own
    else:
        assert {
            "ALUserSession",
            "ALMood",
            "ALRobotMood",
            "_UserSessionManager",
        } <= names


def test_life_opens_a_user_session_on_a_tracked_face(request, nao, standing):
    """2.8: Autonomous Life in solitary identifies the tracked person through the typed
    _UserIdentification stub and opens a session on them; 2.1's desktop life refuses setState."""
    known_issue(
        request,
        nao,
        "ALAutonomousLife.setState is refused on the 2.1 desktop suite",
        versions=("2.1",),
    )
    life = nao.service("ALAutonomousLife")
    sessions = nao.service("ALUserSession")
    # Through disabled first: 2.8 boots in solitary, and entering it again is what restarts the
    # awareness an earlier test stopped.
    life.setState("disabled")
    life.setState("solitary")
    time.sleep(2.0)
    state = nao.sim.props.spawn("face", FACE_AHEAD, frame="robot")
    try:
        wait_until(lambda: sessions.getFocusedUser() != -1, 15.0, "a user session")
        assert sessions.getOpenUserSessions() == [sessions.getFocusedUser()]
        ident = nao.service("_UserIdentification")
        # life runs from boot on 2.8: earlier faces were stored as users too
        assert sessions.getFocusedUser() in ident.getStoredUsers()
    finally:
        life.setState("disabled")
        nao.sim.props.despawn(state.name)
