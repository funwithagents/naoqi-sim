"""The simulated world: naoqi-viewer's sim mode, driven through its public API (specs/host/viewer.md).

`naoqi_viewer` comes with the `naoqi-sim[viewer]` extra and is imported only when a config needs
it. Closing the window stops the viewer only: the robot keeps running, and this module logs it.
"""

import logging
import math
import threading
from collections.abc import Callable, Sequence
from typing import Any, Literal

from naoqi_sim.config import ConfigError, NaoqiSimConfig, ViewerSettings
from naoqi_sim.errors import MissingExtraError

log = logging.getLogger(__name__)


class WorldClosed(Exception):
    """The viewer is gone (its window closed by the user): it renders no more frames."""


def needs_viewer(config: NaoqiSimConfig) -> bool:
    """A window, or a headless viewer for a rendered camera (viewer.md, "Which viewer runs")."""
    return not config.viewer.headless or "render" in config.video_input.sources.values()


def viewer_config(settings: ViewerSettings, url: str) -> Any:
    """The `NaoqiViewerConfig` of naoqi-viewer's sim mode for naoqi-sim's NAOqi at `url`, checked by
    naoqi-viewer itself (an unknown bundled scene is a `ConfigError` on `viewer.scene`)."""
    try:
        import naoqi_viewer
    except ImportError:
        raise MissingExtraError(
            "this config needs the viewer (a window, or the render camera): "
            "depend on `naoqi-sim[viewer]` instead of `naoqi-sim`, or set viewer.headless to true"
        ) from None
    try:
        return naoqi_viewer.NaoqiViewerConfig(
            mode="sim",
            headless=settings.headless,
            cameras_display=settings.cameras_display,
            people_display=settings.people_display,
            naoqi=naoqi_viewer.NaoqiSettings(url=url),
            world=naoqi_viewer.WorldSettings(
                scene=settings.scene,
                variant=settings.variant,  # type: ignore[arg-type]  # the same three variants
            ),
        )
    except naoqi_viewer.ConfigError as e:
        key = getattr(e, "key", None)
        raise ConfigError(
            str(getattr(e, "message", e)), f"viewer.{key or 'scene'}"
        ) from None


Frame = Literal["world", "robot"]
FRAMES: tuple[Frame, ...] = ("world", "robot")


def robot_to_world(
    robot: Sequence[float], pos: Sequence[float], quat: Sequence[float] | None
) -> tuple[tuple[float, float, float], tuple[float, float, float, float] | None]:
    """`pos` and `quat` given in NAOqi's FRAME_ROBOT, in FRAME_WORLD, for the robot at `robot`:
    `[x, y, theta]`, what `ALMotion.getRobotPosition(True)` answers."""
    x, y, theta = (float(v) for v in robot)
    px, py, pz = (float(v) for v in pos)
    c, s = math.cos(theta), math.sin(theta)
    world_pos = (x + c * px - s * py, y + s * px + c * py, pz)
    if quat is None:
        return world_pos, None
    w, qx, qy, qz = (float(v) for v in quat)
    hw, hz = math.cos(theta / 2), math.sin(theta / 2)  # the heading, about the vertical
    world_quat = (
        hw * w - hz * qz,
        hw * qx - hz * qy,
        hw * qy + hz * qx,
        hw * qz + hz * w,
    )
    return world_pos, world_quat


class SimProps:
    """naoqi-viewer's props, one call per viewer call, with positions in the scene's frame
    (`frame="world"`, NAOqi's FRAME_WORLD) or the robot's (`frame="robot"`, FRAME_ROBOT, read
    from `ALMotion.getRobotPosition` at the call) (specs/host/props.md)."""

    def __init__(self, props: Any, robot_position: Callable[[], Sequence[float]]):
        self._props = props
        self._robot_position = robot_position

    def list(self) -> dict[str, Any]:
        return self._props.list()

    def spawn(
        self,
        kind: str,
        pos: Sequence[float],
        *,
        frame: Frame = "world",
        quat: Sequence[float] | None = None,
        **options: Any,
    ) -> Any:
        pos, quat = self._to_world(frame, pos, quat)
        return self._props.spawn(kind, pos, quat=quat, **options)

    def place(
        self,
        name: str,
        pos: Sequence[float] | None = None,
        quat: Sequence[float] | None = None,
        *,
        frame: Frame = "world",
        duration: float = 0.0,
    ) -> Any:
        if pos is not None:
            pos, quat = self._to_world(frame, pos, quat)
        elif quat is not None and frame == "robot":
            _, quat = robot_to_world(self._robot_position(), (0, 0, 0), quat)
        return self._props.place(name, pos, quat, duration=duration)

    def despawn(self, name: str) -> Any:
        return self._props.despawn(name)

    def clear(self) -> dict[str, Any]:
        return self._props.clear()

    def _to_world(
        self, frame: Frame, pos: Sequence[float], quat: Sequence[float] | None
    ) -> tuple[Any, Any]:
        if frame not in FRAMES:
            raise ValueError(f"frame must be 'world' or 'robot', got {frame!r}")
        if frame == "world":
            return pos, quat
        return robot_to_world(self._robot_position(), pos, quat)


class SimWorld:
    """One `NaoqiViewer` in sim mode, owned by a running `NaoqiSim`."""

    def __init__(self, config: Any):
        from naoqi_viewer import NaoqiViewer

        self._viewer = NaoqiViewer(config)
        self._closing = False
        self._watcher: threading.Thread | None = None
        self._session: Any = None  # for the robot's frame, opened at its first use
        self._session_lock = threading.Lock()
        self.props = SimProps(self._viewer.props, self._robot_position)

    @property
    def running(self) -> bool:
        return self._viewer.running

    def launch(self) -> None:
        """Start the viewer process; returns once it can render (`LaunchError` otherwise)."""
        self._viewer.launch()
        self._watcher = threading.Thread(
            target=self._watch, name="naoqi-sim-viewer-watch", daemon=True
        )
        self._watcher.start()

    def _watch(self) -> None:
        self._viewer.wait()
        if not self._closing:
            log.warning(
                "the sim window was closed: the robot is still running (Ctrl-C to stop it)"
            )

    def camera_frame(self, camera: str, width: int, height: int) -> Any:
        """What a head camera (`top`, `bottom`) sees: a (height, width, 3) uint8 RGB array.
        Raises `WorldClosed` once the viewer is gone."""
        from naoqi_viewer import ViewerClosed

        try:
            return self._viewer.camera_frame(camera, width, height).image  # type: ignore[arg-type]
        except ViewerClosed:
            raise WorldClosed("the viewer is closed") from None

    def _robot_position(self) -> Sequence[float]:
        from naoqi_sim import stack

        with self._session_lock:
            if self._session is None:
                self._session = stack.connect()  # naoqi-sim's NAOqi, on its fixed URL
            return self._session.service("ALMotion").getRobotPosition(True)

    def close(self) -> None:
        self._closing = True
        with self._session_lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()
        self._viewer.close()
        if self._watcher is not None:
            self._watcher.join(timeout=5)
