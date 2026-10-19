"""The simulated world: naoqi-viewer's sim mode, driven through its public API (specs/host/viewer.md).

`naoqi_viewer` comes with the `naoqi-sim[viewer]` extra and is imported only when a config needs
it. Closing the window stops the viewer only: the robot keeps running, and this module logs it.
"""

import logging
import threading
from typing import Any

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


class SimWorld:
    """One `NaoqiViewer` in sim mode, owned by a running `NaoqiSim`."""

    def __init__(self, config: Any):
        from naoqi_viewer import NaoqiViewer

        self._viewer = NaoqiViewer(config)
        self._closing = False
        self._watcher: threading.Thread | None = None
        # The props of the world (specs/host/props.md): naoqi-viewer's own client, frames included.
        self.props = self._viewer.props

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

    def close(self) -> None:
        self._closing = True
        self._viewer.close()
        if self._watcher is not None:
            self._watcher.join(timeout=5)
