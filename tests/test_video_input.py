"""The video input against a fake NAOqi (`ALVideoDevice`, `ALMemory`) and a fake frame source:
what it injects, at what rate, what it publishes, and how it lives through a closed viewer,
refused frames and a source that blocks."""

import logging
import threading
import time

import numpy as np
import pytest

from naoqi_sim import video_input
from naoqi_sim.video_input import NoFrame, VideoInput
from naoqi_sim.viewer import WorldClosed


class FakeNaoqi:
    """A qi session to a NAOqi whose ALVideoDevice records the frames put into it."""

    def __init__(self):
        self.puts: list[tuple[int, int, int, bytes, float]] = []
        self.memory: dict[str, str] = {}
        self.memory_log: list[str] = []
        self.refuse = False
        self.closed = False

    def service(self, name):
        return {"ALVideoDevice": self, "ALMemory": self}[name]

    def putImage(self, camera, width, height, data):
        if self.refuse:
            return False
        self.puts.append((camera, width, height, data, time.monotonic()))
        return True

    def insertData(self, key, value):
        self.memory[key] = value
        self.memory_log.append(value)

    def close(self):
        self.closed = True


class Frames:
    """A world of numbered frames for both cameras: the top camera's frame n has every pixel
    at n % 128, the bottom camera's at 128 + n % 128. `source(camera)` is that camera's
    `FrameSource`."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.count = {"top": 0, "bottom": 0}
        self.closed = False
        self.failing: str | None = None  # a camera whose render raises
        self.block = threading.Event()

    def frame(self, camera):
        if self.closed:
            raise WorldClosed("the viewer is closed")
        if self.block.is_set():
            time.sleep(10)
        if camera == self.failing:
            raise RuntimeError(f"no {camera} render")
        time.sleep(self.delay)
        self.count[camera] += 1
        offset = 128 if camera == "bottom" else 0
        return np.full((480, 640, 3), offset + self.count[camera] % 128, np.uint8)

    def source(self, camera: str):
        world = self

        class Source:
            name = "render"

            def frame(self):
                return world.frame(camera)

        return Source()

    def sources(self, *cameras: str):
        return {camera: self.source(camera) for camera in cameras}


def puts_into(naoqi, camera: int):
    """The frames put into one camera: (value of the first pixel, time)."""
    return [(data[0], at) for index, _, _, data, at in naoqi.puts if index == camera]


@pytest.fixture
def naoqi():
    return FakeNaoqi()


def rates(fps, cameras=("top", "bottom")):
    """`fps` for every camera, or a dict as given."""
    return fps if isinstance(fps, dict) else dict.fromkeys(cameras, fps)


def running(world, naoqi, fps=10, cameras=("top", "bottom")) -> VideoInput:
    device = VideoInput(
        world.sources(*cameras), rates(fps, cameras), connect=lambda: naoqi
    )
    device.start()
    return device


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_injects_each_cameras_frames_into_its_index_at_vga(naoqi):
    device = running(Frames(), naoqi)
    wait_until(lambda: len(naoqi.puts) >= 4)
    device.stop()

    # Each slot: the top camera's frame, then the bottom camera's, both at VGA.
    assert [put[:3] for put in naoqi.puts[:4]] == [
        (0, 640, 480),
        (1, 640, 480),
        (0, 640, 480),
        (1, 640, 480),
    ]
    top = np.frombuffer(naoqi.puts[0][3], np.uint8).reshape(480, 640, 3)
    assert (top == 1).all()  # the source's first top frame, as it gave it
    bottom = np.frombuffer(naoqi.puts[1][3], np.uint8).reshape(480, 640, 3)
    assert (bottom == 129).all()  # the source's first bottom frame
    assert [value for value, _ in puts_into(naoqi, 0)[:2]] == [1, 2]
    assert [value for value, _ in puts_into(naoqi, 1)[:2]] == [129, 130]


class Ran:
    """The time a device ran, measured from outside: at least from after `start()` returned to
    when `stop()` was called, at most from before `start()` to after `stop()` returned. A slow
    machine stretches the sleeps in between; the device's schedule follows the time it ran."""

    def __init__(self, fps: int) -> None:
        self.fps = fps

    def start(self, source, naoqi) -> VideoInput:
        self.t0 = time.monotonic()
        device = running(source, naoqi, fps=self.fps)
        self.t1 = time.monotonic()
        return device

    def stop(self, device: VideoInput) -> None:
        self.t2 = time.monotonic()
        device.stop()
        self.t3 = time.monotonic()

    def slots(self, lateness: float, fps: int | None = None) -> tuple[float, float]:
        """The fewest and most slots of a schedule at `fps` (the device's, by default) in that
        time. A machine that wakes threads `lateness` seconds late (a CI virtual machine) loses
        slots at both ends: before the device's thread first runs, and after the last slot it
        handled when `stop()` finds it sleeping late, besides the frame in flight
        (specs/testing/testing.md, "Platforms")."""
        fps = fps or self.fps
        fewest = (self.t2 - self.t1 - 2 * lateness) * fps - 2
        return fewest, (self.t3 - self.t0) * fps + 1

    def frames(self, lateness: float) -> tuple[float, float]:
        """The fewest and most frames of the schedules in that time: one per camera per slot."""
        fewest, most = self.slots(lateness)
        return fewest * 2, most * 2


def test_each_camera_keeps_its_own_rate(naoqi, lateness):
    """A fast top camera and a slow bottom one (bandwidth, or the viewer's render budget)."""
    ran = Ran(fps=30)
    ran.t0 = time.monotonic()
    device = VideoInput(
        Frames().sources("top", "bottom"),
        {"top": 30, "bottom": 10},
        connect=lambda: naoqi,
    )
    device.start()
    ran.t1 = time.monotonic()
    time.sleep(1.0)
    ran.stop(device)

    top, bottom = len(puts_into(naoqi, 0)), len(puts_into(naoqi, 1))
    missed = device.missed_by_camera
    # Every slot of each camera's schedule put its frame or was missed, never caught up: the
    # top camera's slots are three times the bottom camera's, however many a loaded machine
    # (a CI runner waking late) misses.
    fewest, most = ran.slots(lateness())
    assert top <= most and fewest <= top + missed["top"] <= most
    fewest, most = ran.slots(lateness(), fps=10)
    assert bottom <= most and fewest <= bottom + missed["bottom"] <= most
    assert device.missed == missed["top"] + missed["bottom"]
    # (No burst check on gaps at 30 fps: a frame woken 33 ms late on GitHub's macOS runner
    # lands right before the next slot's. `top <= most` already forbids made-up frames.)


def test_paces_at_the_configured_rate(naoqi, lateness):
    ran = Ran(fps=10)
    device = ran.start(Frames(), naoqi)
    time.sleep(1.0)
    ran.stop(device)

    # Each slot puts a frame per camera, or is missed (a render or an injection stalled past
    # it, as on a loaded machine), never caught up with a second frame.
    fewest, most = ran.frames(lateness())
    assert len(naoqi.puts) <= most
    assert fewest <= len(naoqi.puts) + device.missed <= most
    assert (
        abs(len(puts_into(naoqi, 0)) - len(puts_into(naoqi, 1))) <= 1
    )  # the same rate
    gaps = np.diff([at for _, at in puts_into(naoqi, 0)])
    # Never a burst: missed slots made up would put a camera's frames back to back (well under
    # a millisecond apart), where a frame woken late (50 ms at worst on GitHub's macOS runner)
    # still lands 50 ms before the next slot's at 10 fps.
    assert gaps.min() > 0.001


def test_a_slow_source_skips_slots_and_never_catches_up(naoqi, lateness):
    source = Frames(delay=0.08)  # slower than 30 fps' 33 ms, per camera
    ran = Ran(fps=30)
    device = ran.start(source, naoqi)
    time.sleep(0.6)
    source.delay = 0.0  # fast again: the missed slots are not made up
    time.sleep(0.4)
    ran.stop(device)

    fewest, most = ran.frames(lateness())
    assert (
        device.missed >= 10
    )  # a slot every 160 ms missed slots of 33 ms, two frames each
    # Missed, not lost; and never made up: a burst of the missed frames once the source is fast
    # again would put more frames than the schedule has slots.
    assert fewest <= len(naoqi.puts) + device.missed <= most
    assert len(puts_into(naoqi, 0)) <= most / 2


def test_publishes_each_cameras_source_and_their_summary_while_it_runs(naoqi):
    device = running(Frames(), naoqi)
    assert naoqi.memory == {
        "NaoqiSim/Camera/Top/Source": "render",
        "NaoqiSim/Camera/Bottom/Source": "render",
        "NaoqiSim/Camera/Source": "render",
    }
    device.stop()

    assert set(naoqi.memory.values()) == {"none"}
    assert naoqi.memory_log[-1] == "none"  # the summary is written last
    assert naoqi.closed


def test_feeds_only_the_cameras_it_is_given(naoqi):
    device = running(Frames(), naoqi, cameras=("bottom",))
    wait_until(lambda: len(naoqi.puts) >= 2)
    assert naoqi.memory["NaoqiSim/Camera/Top/Source"] == "none"
    assert naoqi.memory["NaoqiSim/Camera/Bottom/Source"] == "render"
    assert naoqi.memory["NaoqiSim/Camera/Source"] == "render"  # the one source in use
    device.stop()

    assert {put[0] for put in naoqi.puts} == {1}


def test_the_summary_says_mixed_when_the_cameras_sources_differ(naoqi):
    world = Frames()
    webcam = world.source("top")
    webcam.name = "webcam"
    device = VideoInput(
        {"top": webcam, "bottom": world.source("bottom")},
        rates(10),
        connect=lambda: naoqi,
    )
    device.start()
    assert naoqi.memory["NaoqiSim/Camera/Top/Source"] == "webcam"
    assert naoqi.memory["NaoqiSim/Camera/Bottom/Source"] == "render"
    assert naoqi.memory["NaoqiSim/Camera/Source"] == "mixed"
    device.stop()


def test_refuses_an_unknown_camera_or_none_at_all(naoqi):
    with pytest.raises(ValueError, match="cameras must be among"):
        VideoInput(
            {"left": Frames().source("top")}, {"left": 10}, connect=lambda: naoqi
        )
    with pytest.raises(ValueError, match="cameras must be among"):
        VideoInput({}, {}, connect=lambda: naoqi)
    with pytest.raises(ValueError, match="no fps for"):
        VideoInput(
            Frames().sources("top", "bottom"), {"top": 10}, connect=lambda: naoqi
        )


def test_a_closed_viewer_stops_the_camera_and_says_so_once(naoqi, caplog):
    source = Frames()
    device = running(source, naoqi)
    wait_until(lambda: len(naoqi.puts) >= 1)

    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        source.closed = True  # the user closes the window
        wait_until(lambda: naoqi.memory["NaoqiSim/Camera/Source"] == "none")
        put = len(naoqi.puts)
        time.sleep(0.3)
        device.stop()

    assert len(naoqi.puts) == put  # nothing more injected
    assert [r.getMessage() for r in caplog.records] == [
        "the viewer is closed: the robot's top and bottom cameras get no more frames"
    ]


def test_a_closed_source_drops_its_cameras_and_the_others_carry_on(naoqi, caplog):
    """A webcam on the top camera keeps feeding when the viewer rendering the bottom one
    closes (the webcam is not built; the device is ready for it)."""
    viewer, webcam_world = Frames(), Frames()
    webcam = webcam_world.source("top")
    webcam.name = "webcam"
    device = VideoInput(
        {"top": webcam, "bottom": viewer.source("bottom")},
        rates(30),
        connect=lambda: naoqi,
    )
    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        device.start()
        wait_until(lambda: len(puts_into(naoqi, 1)) >= 1)
        viewer.closed = True
        wait_until(lambda: naoqi.memory["NaoqiSim/Camera/Bottom/Source"] == "none")
        bottom = len(puts_into(naoqi, 1))
        top = len(puts_into(naoqi, 0))
        wait_until(lambda: len(puts_into(naoqi, 0)) >= top + 3)
        device.stop()

    assert len(puts_into(naoqi, 1)) <= bottom + 1  # at most the frame in flight
    assert (
        naoqi.memory_log.count("none") >= 2
    )  # written when the viewer closed, and at stop
    assert [r.getMessage() for r in caplog.records] == [
        "the viewer is closed: the robot's bottom camera gets no more frames"
    ]
    # While it ran on the webcam alone, the summary said so.
    assert "webcam" in naoqi.memory_log


def test_a_camera_whose_render_fails_does_not_starve_the_other(naoqi, caplog):
    source = Frames()
    source.failing = "bottom"
    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        device = running(source, naoqi, fps=30)
        wait_until(lambda: len(puts_into(naoqi, 0)) >= 3)
        source.failing = None
        wait_until(lambda: len(puts_into(naoqi, 1)) >= 1)
        device.stop()

    # The top camera's frames kept coming, in order, while the bottom render failed...
    assert [value for value, _ in puts_into(naoqi, 0)[:3]] == [1, 2, 3]
    # ...and the bottom camera's first frame is its first render, once the render works.
    assert puts_into(naoqi, 1)[0][0] == 129
    assert [r.getMessage() for r in caplog.records] == [
        "video input: render bottom failed: no bottom render"
    ]


def test_a_source_with_no_frame_skips_its_slots_quietly_and_counts_them(naoqi, caplog):
    """A webcam not delivering: its camera gets nothing and nothing is logged per slot, its
    slots are counted as missed, and the other camera carries on."""
    world = Frames()
    waiting = threading.Event()  # set: the top camera's source has a frame again

    class Webcam:
        name = "webcam"

        def frame(self):
            if not waiting.is_set():
                raise NoFrame("no frame yet")
            return world.frame("top")

    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        device = VideoInput(
            {"top": Webcam(), "bottom": world.source("bottom")},
            {"top": 20, "bottom": 20},
            connect=lambda: naoqi,
        )
        device.start()
        wait_until(lambda: len(puts_into(naoqi, 1)) >= 3)
        assert puts_into(naoqi, 0) == []
        assert device.missed_by_camera["top"] >= 3
        waiting.set()
        wait_until(lambda: len(puts_into(naoqi, 0)) >= 1)
        device.stop()

    assert puts_into(naoqi, 0)[0][0] == 1  # its first frame, once there is one
    assert caplog.records == []


def test_refused_frames_warn_once_and_injection_resumes(naoqi, caplog):
    naoqi.refuse = True
    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        device = running(Frames(), naoqi, fps=30)
        time.sleep(0.3)
        naoqi.refuse = False
        wait_until(lambda: len(naoqi.puts) >= 2)
        device.stop()

    assert [r.getMessage() for r in caplog.records] == [
        "video input: putImage failed: NAOqi refused the frame"
    ]


def test_stop_does_not_wait_on_a_blocked_source(naoqi, monkeypatch):
    monkeypatch.setattr(video_input, "JOIN_TIMEOUT_S", 0.2)
    source = Frames()
    device = running(source, naoqi)
    wait_until(lambda: len(naoqi.puts) >= 1)
    source.block.set()  # the next frame takes 10 s
    time.sleep(0.2)

    started = time.monotonic()
    device.stop()
    assert time.monotonic() - started < 1.0
    assert naoqi.memory["NaoqiSim/Camera/Source"] == "none"
    device.stop()  # twice is harmless


def _frame(put) -> np.ndarray:
    return np.frombuffer(put[3], np.uint8).reshape(480, 640, 3)


def test_a_covered_camera_sees_a_hand_until_uncovered_and_the_other_its_source(naoqi):
    """A hand over the top camera: the dark frame of a real NAO's covered camera (a luminance of
    17.5 once NAOqi converts it) in place of the source's, while the bottom camera still gets its own."""
    device = running(Frames(), naoqi)
    device.cover("top")
    assert device.covered() == {"top": True, "bottom": False}
    naoqi.puts.clear()  # a frame rendered before the cover may still come: read the last ones
    wait_until(lambda: len(puts_into(naoqi, 0)) >= 3 and len(puts_into(naoqi, 1)) >= 3)
    top = _frame([p for p in naoqi.puts if p[0] == 0][-1])
    bottom = _frame([p for p in naoqi.puts if p[0] == 1][-1])
    # the grey NAOqi's studio-range conversion turns into a luminance of 17.5
    assert 16 + 219 / 255 * top.mean() == pytest.approx(17.5, abs=0.01)
    assert top.std() < 1
    assert bottom.min() >= 128  # the bottom camera's own frames

    device.cover("top", False)
    naoqi.puts.clear()
    wait_until(lambda: len(puts_into(naoqi, 0)) >= 3)
    device.stop()
    assert (
        _frame([p for p in naoqi.puts if p[0] == 0][-1]).std() == 0
    )  # the source again
    assert device.covered() == {"top": False, "bottom": False}


def test_only_a_fed_camera_can_be_covered(naoqi):
    device = VideoInput(Frames().sources("top"), {"top": 10}, connect=lambda: naoqi)
    with pytest.raises(
        video_input.CameraNotFedError, match="bottom camera gets no frames"
    ):
        device.cover("bottom")
    with pytest.raises(ValueError, match="unknown camera 'side'"):
        device.cover("side")
    assert device.covered() == {"top": False, "bottom": False}


def test_a_closed_source_uncovers_its_cameras(naoqi):
    world = Frames()
    device = running(world, naoqi, cameras=("top",))
    device.cover("top")
    world.closed = True
    wait_until(lambda: device.fed == ())
    device.stop()
    assert device.covered() == {"top": False, "bottom": False}
