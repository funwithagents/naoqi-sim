"""The brightness statistics core (specs/services/brightness-statistics.md) with a fake
ALVideoDevice: the statistics of a covered camera and of a room, nothing raised before `_start()`
or after `_stop()`, the camera let go at `_stop()`, an unfed camera's placeholder ignored."""

import threading
import time

import naoqi_sim_brightness_statistics_core as core
import numpy as np
import pytest

pytestmark = pytest.mark.container_code

W, H = 160, 120  # QQVGA


def covered() -> bytes:
    """The top camera under a hand, in QQVGA luminance, as a real NAO's measured."""
    rows, cols = np.indices((H, W))
    return np.where((rows + cols) % 2 == 0, 17, 18).astype(np.uint8).tobytes()


def room() -> bytes:
    """A lit room: a gradient from dark to bright, as the render of a scene."""
    return np.tile(np.linspace(30, 200, W), (H, 1)).astype(np.uint8).tobytes()


class FakeVideo:
    def __init__(self, picture: bytes):
        self.picture = picture
        self.subscribed: list[tuple] = []
        self.active: set[str] = set()
        self.blank = False  # the camera gives nothing

    def subscribeCamera(self, name, camera, resolution, colorspace, fps):
        self.subscribed.append((name, camera, resolution, colorspace, fps))
        handle = f"{name}_{len(self.subscribed)}"
        self.active.add(handle)
        return handle

    def getImageRemote(self, handle):
        assert handle in self.active
        return None if self.blank else [W, H, 1, 0, 0, 0, self.picture]

    def unsubscribe(self, handle):
        self.active.discard(handle)


class Raised:
    def __init__(self):
        self.events: list[tuple[str, float]] = []
        self.lock = threading.Lock()

    def __call__(self, key, value):
        with self.lock:
            self.events.append((key, value))

    def last(self) -> dict[str, float]:
        with self.lock:
            return dict(self.events[-2:])


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_a_covered_camera_is_dark_and_a_room_is_not():
    # Life's rule: Avg < 30 and Std < 5
    assert core.statistics(covered()) == pytest.approx((17.5, 0.5))
    lit = core.statistics(room())
    assert lit is not None and lit[0] > 30 and lit[1] > 5


def test_an_unfed_cameras_placeholder_is_no_picture():
    # every byte 0: what ALVideoDevice serves a camera nobody feeds, not a hand over it
    assert core.statistics(bytes(W * H)) is None
    assert core.statistics(b"") is None


def test_raises_both_keys_from_the_top_camera_while_started():
    video, raised = FakeVideo(room()), Raised()
    stats = core.BrightnessStatistics(lambda: video, raised)
    stats.start()
    stats.start()  # a second start is the same start
    wait_until(lambda: len(raised.events) >= 4)
    assert video.subscribed == [(core.SUBSCRIBER, 0, 0, 0, 10)]  # top, QQVGA, Y, 10 Hz
    assert set(raised.last()) == {core.AVG_KEY, core.STD_KEY}
    assert raised.last()[core.AVG_KEY] > 30

    video.picture = covered()  # a hand over it
    wait_until(lambda: raised.last()[core.AVG_KEY] < 30)
    assert raised.last()[core.STD_KEY] < 5
    stats.stop()


def test_raises_ten_times_a_second():
    video, raised = FakeVideo(room()), Raised()
    stats = core.BrightnessStatistics(lambda: video, raised)
    stats.start()
    time.sleep(1.0)
    stats.stop()
    samples = len(raised.events) // 2
    assert 5 <= samples <= 11


def test_nothing_before_start_or_after_stop_and_the_camera_let_go():
    video, raised = FakeVideo(room()), Raised()
    made = []
    stats = core.BrightnessStatistics(lambda: made.append(1) or video, raised)
    time.sleep(0.2)
    assert (
        raised.events == [] and made == []
    )  # no proxy at load: ALVideoDevice comes later
    stats.start()
    wait_until(lambda: len(raised.events) >= 2)
    stats.stop()
    count = len(raised.events)
    time.sleep(0.3)
    assert len(raised.events) == count
    assert video.active == set()
    stats.stop()  # a second stop does nothing


def test_an_unfed_camera_raises_nothing_and_a_failing_one_recovers():
    video, raised = FakeVideo(bytes(W * H)), Raised()
    logged = []
    stats = core.BrightnessStatistics(
        lambda: video, raised, log=lambda **f: logged.append(f)
    )
    assert stats.sample() is None
    assert raised.events == []
    video.blank = True
    assert stats.sample() is None
    assert [f["method"] for f in logged].count("camera-failed") == 1
    video.blank = False
    video.picture = covered()
    stats.running = True  # as start() sets it, without the thread
    assert stats.sample() == pytest.approx((17.5, 0.5))
    assert "camera-recovered" in [f["method"] for f in logged]
