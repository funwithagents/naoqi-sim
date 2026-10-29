"""The face detection core: the detector's schedule, camera and engine, and ALFaceDetection's
FaceDetected over them (specs/services/face-detection.md), with fake NAOqi services."""

import math
import threading
import time
from itertools import pairwise
from typing import Any, ClassVar

import naoqi_sim_face_detection_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

HFOV, VFOV = math.radians(60.97), math.radians(47.64)
W, H = 640, 480


class FakeVideo:
    """ALVideoDevice as the detector uses it: NAOqi's angle conventions (yaw positive to the left,
    pitch positive downward), a frame with a timestamp, the subscriptions recorded."""

    def __init__(self):
        self.subscriptions: list[tuple] = []
        self.active: set[str] = set()
        self.reads = 0
        self.fail = False

    def subscribeCamera(self, name, camera, resolution, colorspace, fps):
        self.subscriptions.append((name, camera, resolution, colorspace, fps))
        handle = f"{name}_{len(self.subscriptions)}"
        self.active.add(handle)
        return handle

    def unsubscribe(self, handle):
        self.active.discard(handle)

    def getImageRemote(self, handle):
        assert handle in self.active
        if self.fail:
            raise RuntimeError("camera gone")
        self.reads += 1
        return [W, H, 3, core.RGB, 100 + self.reads, 250000, b"\x80" * (W * H * 3), 0]

    def getAngularPositionFromImagePosition(self, camera, p):
        return [(0.5 - p[0]) * HFOV, (p[1] - 0.5) * VFOV]

    def getAngularSizeFromImageSize(self, camera, s):
        return [s[0] * HFOV, s[1] * VFOV]


class FakeMotion:
    def getPosition(self, name, frame, sensors):
        return [0.0, 0.0, 0.5, 0.0, 0.0, frame * 0.1]

    def getTransform(self, name, frame, sensors):
        return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0.5, 0, 0, 0, 1]


class FakeEngine:
    def __init__(self, faces=None, url="http://perception:8080"):
        self.url = url
        self.faces = faces or []
        self.calls: list[tuple[int, int, int]] = []
        self.fail = False

    @property
    def available(self):
        return bool(self.url)

    def detect(self, width, height, rgb):
        self.calls.append((width, height, len(rgb)))
        if self.fail:
            raise OSError("engine unreachable")
        return self.faces


def a_face(cx=320.0, cy=240.0, w=90.0, h=106.0, score=0.9):
    x, y = cx - w / 2, cy - h / 2
    return {
        "box": [x, y, w, h],
        "score": score,
        "landmarks": [
            [cx - 20, cy - 15],
            [cx + 20, cy - 15],
            [cx, cy + 10],
            [cx - 18, cy + 35],
            [cx + 18, cy + 35],
        ],
    }


class Memory:
    def __init__(self):
        self.data: dict = {}
        self.events: list[tuple[str, object]] = []

    def insert(self, key, value):
        self.data[key] = value

    def raise_event(self, key, value):
        self.events.append((key, value))


class Rig:
    def __init__(self, version="2.1", engine=None):
        self.video = FakeVideo()
        self.engine = FakeEngine() if engine is None else engine
        self.log: list[dict] = []
        self.detector = core.Detector(
            lambda: self.video,
            FakeMotion,
            self.engine,
            log=lambda **f: self.log.append(f),
        )
        self.memory = Memory()
        self.module = core.FaceModule(
            self.detector,
            self.memory.insert,
            self.memory.raise_event,
            version,
            log=lambda **f: self.log.append(f),
        )

    def api(self) -> Any:
        """The module as a shell serves it: the table's methods over the core (dynamic, hence Any)."""
        import naoqi_sim_perception_stubs_core as ext

        module = self.module

        class Shell:
            HANDLERS: ClassVar[dict] = {}

            def _call(self, name, args):
                return ext.call(module, Shell.HANDLERS, name, args)

        ext.install(Shell, core.METHODS)
        return Shell()

    def cycle(self):
        """One slot of the detector's loop, without its thread."""
        detection = self.detector.capture()
        if detection is not None:
            self.module.on_detection(detection)
        return detection

    def logged(self, method):
        return [f for f in self.log if f["method"] == method]


def test_the_detector_runs_only_while_someone_subscribes_and_never_faster_than_10_hz():
    rig = Rig()
    assert rig.detector.period_ms() is None
    rig.module.subscribe("box")  # no period: the module's default
    assert rig.detector.period_ms() == core.DEFAULT_PERIOD_MS == 500
    rig.module.subscribe("fast", 10, 0.0)
    assert rig.detector.period_ms() == core.MIN_PERIOD_MS == 100
    rig.module.updatePeriod("fast", 200)
    assert rig.detector.period_ms() == 200
    rig.module.pause(True)
    assert rig.detector.period_ms() is None and rig.module.getSubscribersInfo() == [
        ["box", 500, 0.0],
        ["fast", 200, 0.0],
    ]
    rig.module.pause(False)
    rig.module.unsubscribe("box")
    rig.module.unsubscribe("fast")
    assert rig.detector.period_ms() is None


def test_a_cycle_subscribes_the_active_camera_at_vga_and_the_subscribers_rate_and_posts_the_frame():
    rig = Rig()
    rig.module.subscribe("awareness", 200, 0.0)
    rig.cycle()
    assert rig.video.subscriptions == [(core.SUBSCRIBER, 0, core.VGA, core.RGB, 5)]
    assert rig.engine.calls == [(W, H, W * H * 3)]
    rig.cycle()
    assert len(rig.video.subscriptions) == 1  # kept between cycles
    rig.module.unsubscribe("awareness")
    rig.detector._unsubscribe() if rig.detector.period_ms() is None else None
    assert rig.video.active == set()


def test_face_detected_carries_the_documented_shape_with_naoqis_angles():
    rig = Rig(engine=FakeEngine([a_face(cx=420.0, cy=240.0)]))
    rig.module.subscribe("box", 200, 0.0)
    detection = rig.cycle()
    assert detection is not None and len(detection.faces) == 1
    value = rig.memory.data["FaceDetected"]
    stamp, faces, pose_torso, pose_robot, camera = value
    assert stamp == [101, 250000] and camera == 0
    assert pose_torso == [0.0, 0.0, 0.5, 0.0, 0.0, 0.0] and pose_robot == [
        0.0,
        0.0,
        0.5,
        0.0,
        0.0,
        0.2,
    ]
    assert faces[-1] == []  # Time_Filtered_Reco_Info: no recognition
    ((shape, extra),) = faces[:-1]
    assert shape[0] == 0
    alpha, beta, size_x, size_y = shape[1:]
    # a face centred 100 px right of the centre: a negative yaw (NAOqi's: positive to the left)
    assert alpha == pytest.approx(-100 / W * HFOV) and beta == pytest.approx(0.0)
    assert size_x == pytest.approx(90 / W * HFOV) and size_y == pytest.approx(
        106 / H * VFOV
    )
    (
        face_id,
        score_reco,
        label,
        left_eye,
        right_eye,
        left_brow,
        right_brow,
        nose,
        mouth,
    ) = extra
    assert (face_id, score_reco, label) == (0, 0.0, "")
    assert [
        len(p) for p in (left_eye, right_eye, left_brow, right_brow, nose, mouth)
    ] == [14, 14, 6, 6, 6, 16]
    # the subject's left eye is the image's right one: smaller yaw than the right eye's
    assert left_eye[0] < right_eye[0]
    assert all(isinstance(v, float) for p in (left_eye, nose, mouth) for v in p)
    # the event, on both names on 2.1
    assert [k for k, _ in rig.memory.events] == [
        "FaceDetected",
        "FaceDetection/FaceDetected",
    ]
    assert rig.memory.events[0][1] == value


def test_on_2_8_only_face_detected_is_declared_and_raised():
    rig = Rig(version="2.8", engine=FakeEngine([a_face()]))
    rig.module.subscribe("box", 200, 0.0)
    rig.cycle()
    assert rig.module.getEventList() == ["FaceDetected"]
    assert [k for k, _ in rig.memory.events] == ["FaceDetected"]


def test_the_empty_value_is_raised_once_when_the_faces_are_gone():
    engine = FakeEngine([a_face()])
    rig = Rig(engine=engine)
    rig.module.subscribe("box", 200, 0.0)
    rig.cycle()
    engine.faces = []
    rig.cycle()
    assert rig.memory.data["FaceDetected"] == []
    assert [k for k, v in rig.memory.events if k == "FaceDetected"] == [
        "FaceDetected",
        "FaceDetected",
    ]
    rig.cycle()
    rig.cycle()
    assert (
        len([k for k, v in rig.memory.events if k == "FaceDetected"]) == 2
    )  # nothing more while empty
    engine.faces = [a_face()]
    rig.cycle()
    assert len(rig.memory.data["FaceDetected"][1]) == 2  # one face and the reco info


def test_an_engine_failure_or_absence_is_a_frame_without_faces_logged_once():
    engine = FakeEngine([a_face()])
    engine.fail = True
    rig = Rig(engine=engine)
    rig.module.subscribe("box", 200, 0.0)
    for _ in range(3):
        detection = rig.cycle()
        assert detection is not None and detection.faces == []
    assert len(rig.logged("engine-failed")) == 1
    engine.fail = False
    rig.cycle()
    assert (
        len(rig.logged("engine-ok")) == 1
        and len(rig.memory.data["FaceDetected"][1]) == 2
    )
    quiet = Rig(
        engine=FakeEngine([a_face()], url="")
    )  # perception.enabled = false: no engine
    quiet.module.subscribe("box", 200, 0.0)
    quiet.cycle()
    quiet.cycle()
    assert quiet.engine.calls == [] and len(quiet.logged("no-engine")) == 1
    assert "FaceDetected" not in quiet.memory.data


def test_a_camera_that_stops_delivering_skips_the_slot_and_is_logged_once():
    rig = Rig(engine=FakeEngine([a_face()]))
    rig.module.subscribe("box", 200, 0.0)
    rig.video.fail = True
    assert rig.cycle() is None and rig.cycle() is None
    assert len(rig.logged("camera-failed")) == 1 and rig.engine.calls == []
    rig.video.fail = False
    assert rig.cycle() is not None and len(rig.logged("camera-recovered")) == 1


def test_the_active_camera_switches_the_subscription():
    rig = Rig(engine=FakeEngine([a_face()]))
    rig.module.subscribe("box", 200, 0.0)
    rig.cycle()
    api = rig.api()
    assert api.setActiveCamera(1) is True and api.getActiveCamera() == 1
    rig.cycle()
    assert [s[1] for s in rig.video.subscriptions] == [0, 1] and len(
        rig.video.active
    ) == 1
    assert rig.memory.data["FaceDetected"][4] == 1
    assert api.setActiveCamera(2) is False and api.getActiveCamera() == 1


def test_settings_and_recognition_stubs_answer_as_a_nao_does_without_learning():
    rig = Rig()
    m = rig.api()
    assert (
        m.setResolution(2) is True
        and m.getResolution() == 2
        and m.setResolution(9) is False
    )
    assert (
        m.setFrameRate(10) is True
        and m.getFrameRate() == 10
        and m.setFrameRate(0) is False
    )
    m.setRecognitionEnabled(False)
    assert m.isRecognitionEnabled() is False
    m.enableRecognition(True)
    assert m.isRecognitionEnabled() is True
    m.setTrackingEnabled(True)
    assert m.isTrackingEnabled() is True
    m.setParameter("minSize", 0.1)
    assert rig.module.params == {"minSize": 0.1}
    assert (
        m.learnFace("bob") is False
        and m.reLearnFace("bob") is False
        and m.importOldDatabase("x") is False
    )
    assert (
        m.getLearnedFacesList() == []
        and m.forgetPerson("bob") is True
        and m.clearDatabase() is True
    )
    assert (
        m.getMemoryKeyList() == ["FaceDetected"]
        and m.getOutputNames() == m.getEventList()
    )
    assert "engine" in m.whoami()


def test_the_source_key_says_whether_an_engine_is_configured():
    written = {}
    core.write_source_key(written.__setitem__, "http://perception:8080")
    assert written == {"NaoqiSim/Perception/Source": "engine"}
    core.write_source_key(written.__setitem__, "")
    assert written == {"NaoqiSim/Perception/Source": "none"}


def test_the_thread_paces_detections_at_the_period_and_stops_cleanly():
    rig = Rig(engine=FakeEngine([a_face()]))
    got = []
    done = threading.Event()

    class Consumer:
        service = "test"

        def wants(self):
            return 100

        def on_detection(self, d):
            got.append(time.monotonic())
            if len(got) >= 4:
                done.set()

    rig.detector.add_consumer(Consumer())
    rig.detector.start()
    try:
        assert done.wait(5.0), "four detections within 5 s"
    finally:
        rig.detector.stop()
    gaps = [b - a for a, b in pairwise(got)]
    assert min(gaps) >= 0.09, gaps  # never faster than the 100 ms floor
    assert rig.video.active == set()  # unsubscribed at stop
    assert (
        len(rig.memory.data) == 0
    )  # the module had no subscriber: it published nothing
