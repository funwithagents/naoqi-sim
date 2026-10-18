"""The simulated world's side in naoqi-sim: when a config needs naoqi-viewer, the sim-mode config it
builds (checked by the installed naoqi-viewer itself), the missing extra, and the window closed by
the user. No viewer process is launched: `NaoqiViewer` is replaced where a test needs one."""

import logging
import math
import sys
import threading

import naoqi_viewer
import numpy as np
import pytest

from naoqi_sim import viewer
from naoqi_sim.config import (
    CameraSettings,
    ConfigError,
    NaoqiSimConfig,
    VideoInputSettings,
    ViewerSettings,
)
from naoqi_sim.errors import MissingExtraError


@pytest.mark.parametrize(
    ("headless", "source", "needed"),
    [
        (False, ("none", "none"), True),
        (False, ("webcam", "none"), True),
        (True, ("render", "render"), True),
        (True, ("none", "render"), True),  # either camera rendered needs the viewer
        (True, ("none", "none"), False),
        (True, ("webcam", "webcam"), False),
    ],
)
def test_which_configs_need_the_viewer(headless, source, needed):
    top, bottom = source
    config = NaoqiSimConfig(
        viewer=ViewerSettings(headless=headless),
        video_input=VideoInputSettings(
            top=CameraSettings(source=top), bottom=CameraSettings(source=bottom)
        ),
    )
    assert viewer.needs_viewer(config) is needed


def test_the_viewer_runs_in_sim_mode_on_naoqi_sims_naoqi():
    config = viewer.viewer_config(
        ViewerSettings(headless=True, scene="table", variant="placeholder"),
        "tcp://127.0.0.1:9559",
    )

    assert isinstance(config, naoqi_viewer.NaoqiViewerConfig)
    assert config.mode == "sim" and config.headless
    assert config.naoqi.url == "tcp://127.0.0.1:9559"
    assert (config.world.scene, config.world.variant) == ("table", "placeholder")
    assert config.cameras_display is False
    assert config.ghost is False  # naoqi-viewer's other fields keep its defaults


def test_the_window_shows_the_cameras_when_asked():
    config = viewer.viewer_config(
        ViewerSettings(cameras_display=True), "tcp://127.0.0.1:9559"
    )
    assert config.cameras_display and not config.headless


def test_an_unknown_scene_is_a_config_error_on_viewer_scene():
    with pytest.raises(ConfigError) as info:
        viewer.viewer_config(ViewerSettings(scene="moon"), "tcp://127.0.0.1:9559")
    assert info.value.key == "viewer.scene"
    assert "moon" in str(info.value)


def test_without_the_extra_the_error_names_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "naoqi_viewer", None)  # makes the import fail
    with pytest.raises(MissingExtraError, match=r"naoqi-sim\[viewer\]"):
        viewer.viewer_config(ViewerSettings(), "tcp://127.0.0.1:9559")


class FakeNaoqiViewer:
    """A viewer whose window the test closes, as a user would."""

    def __init__(self, config):
        self.config = config
        self.exited = threading.Event()
        self.running = False
        self.props = None  # SimWorld wraps it; these tests don't use it

    def launch(self):
        self.running = True

    def wait(self, timeout=None):
        return self.exited.wait(timeout)

    def camera_frame(self, camera, width, height):
        if not self.running:
            raise naoqi_viewer.ViewerClosed("the viewer process has exited")
        image = np.zeros((height, width, 3), np.uint8)
        image[..., 0] = 1 if camera == "top" else 2
        return naoqi_viewer.CameraFrame(image, camera, pose_seq=1, pose_age=0.01)

    def close(self):
        self.running = False
        self.exited.set()


@pytest.fixture
def fake_viewer(monkeypatch):
    made: list[FakeNaoqiViewer] = []

    def make(config):
        made.append(FakeNaoqiViewer(config))
        return made[-1]

    monkeypatch.setattr(naoqi_viewer, "NaoqiViewer", make)
    return made


def test_a_window_closed_by_the_user_is_logged_once(fake_viewer, caplog):
    world = viewer.SimWorld("config")
    world.launch()
    assert world.running

    with caplog.at_level(logging.WARNING, logger="naoqi_sim.viewer"):
        fake_viewer[0].exited.set()  # the user closes the window
        assert world._watcher is not None
        world._watcher.join(timeout=2)

    assert [r.getMessage() for r in caplog.records] == [
        "the sim window was closed: the robot is still running (Ctrl-C to stop it)"
    ]


def test_closing_it_ourselves_logs_nothing(fake_viewer, caplog):
    world = viewer.SimWorld("config")
    world.launch()
    with caplog.at_level(logging.WARNING, logger="naoqi_sim.viewer"):
        world.close()
    assert not world.running
    assert caplog.records == []


def test_camera_frames_come_from_the_viewer_until_it_is_closed(fake_viewer):
    world = viewer.SimWorld("config")
    world.launch()

    frame = world.camera_frame("top", 640, 480)
    assert frame.shape == (480, 640, 3) and frame[0, 0, 0] == 1

    fake_viewer[0].close()  # the user closes the window
    with pytest.raises(viewer.WorldClosed):
        world.camera_frame("top", 640, 480)


class FakeProps:
    """naoqi-viewer's PropsClient, recording what it is asked."""

    def __init__(self):
        self.calls: list[tuple] = []

    def spawn(self, kind, pos, *, quat=None, **options):
        self.calls.append(("spawn", kind, pos, quat, options))
        return "state"

    def place(self, name, pos, quat, *, duration):
        self.calls.append(("place", name, pos, quat, duration))
        return "state"


def test_the_robot_frame_is_turned_and_moved_to_the_robots_odometry():
    pos, quat = viewer.robot_to_world((1.0, 2.0, math.pi / 2), (1.5, 0.0, 0.5), None)
    assert pos == pytest.approx((1.0, 3.5, 0.5))  # 1.5 m ahead of a robot facing +y
    assert quat is None
    pos, quat = viewer.robot_to_world((0.0, 0.0, -0.133), (1.0, 0.3, 0.4), (1, 0, 0, 0))
    c, s = math.cos(-0.133), math.sin(-0.133)
    assert pos == pytest.approx((c - 0.3 * s, s + 0.3 * c, 0.4))
    assert quat == pytest.approx((math.cos(-0.0665), 0, 0, math.sin(-0.0665)))


def test_sim_props_pass_world_positions_through_and_convert_robot_ones():
    props = FakeProps()
    reads: list[int] = []

    def robot_position():
        reads.append(1)
        return (0.5, 0.0, math.pi)

    sim_props = viewer.SimProps(props, robot_position)
    sim_props.spawn("object", (1.5, 0.0, 0.5), size=0.1)
    assert props.calls[-1] == ("spawn", "object", (1.5, 0.0, 0.5), None, {"size": 0.1})
    assert reads == []  # the world frame never reads the robot

    sim_props.spawn("face", (1.0, 0.0, 0.5), frame="robot", name="face_2")
    _, kind, pos, quat, options = props.calls[-1]
    assert (kind, quat, options) == ("face", None, {"name": "face_2"})
    assert pos == pytest.approx((-0.5, 0.0, 0.5))  # ahead of a robot facing -x

    sim_props.place("face_2", (2.0, 0.0, 0.5), frame="robot", duration=1.5)
    _, name, pos, _, duration = props.calls[-1]
    assert (name, duration) == ("face_2", 1.5) and pos == pytest.approx((-1.5, 0, 0.5))
    with pytest.raises(ValueError, match="frame"):
        sim_props.spawn("object", (1, 0, 0), frame="head")  # type: ignore[arg-type]


def test_the_window_shows_the_people_when_asked():
    config = viewer.viewer_config(
        ViewerSettings(people_display=True), "tcp://127.0.0.1:9559"
    )
    assert config.people_display and not config.cameras_display
