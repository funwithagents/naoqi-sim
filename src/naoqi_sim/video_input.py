"""The video input: the robot's head cameras, fed into `ALVideoDevice` (specs/host/video-input.md).

An ordinary qi client: at each camera's `fps` it takes a 640x480 RGB frame of that camera from
its source (the viewer's render of `CameraTop` and `CameraBottom`, back to back at the same pose
when their rates are equal; or a host webcam's newest frame, `naoqi_sim.webcam`) and injects it with the public `putImage` into the camera's index,
whoever subscribes. NAOqi serves every subscriber of a camera from that one frame, in the
subscriber's own resolution and colorspace. Rendering and injecting run on separate threads,
the newest frame of each camera winning, so a `putImage` never makes the next render miss the
viewer's tick.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import numpy as np

from naoqi_sim import stack
from naoqi_sim.errors import CameraNotFedError
from naoqi_sim.viewer import SimWorld, WorldClosed

log = logging.getLogger(__name__)

# VGA: the largest size both versions' putImage accepts (2.8 refuses anything above it).
WIDTH, HEIGHT = 640, 480
# NAOqi's camera indices by camera name, in injection order.
CAMERAS: dict[str, int] = {"top": 0, "bottom": 1}
# The summary key `status()` reads, and one key per camera (specs/container/status-service.md).
SOURCE_KEY = "NaoqiSim/Camera/Source"
MIXED = "mixed"  # the summary when the fed cameras have different sources


def camera_key(camera: str) -> str:
    return f"NaoqiSim/Camera/{camera.capitalize()}/Source"


def covered_frame() -> np.ndarray:
    """What a camera sees with a hand over it (specs/host/controls.md, "The camera cover"): the
    grey NAOqi turns into a luminance of mean 17.5, as a real NAO's top camera measured under a
    hand. NAOqi converts an injected RGB frame to luminance in studio range, Y = 16 + 219/255 *
    RGB (measured: a grey of 17.5 read 31), so the grey is 1.75: in each 2x2 block, three pixels
    at 2 and one at 1."""
    rows, cols = np.indices((HEIGHT, WIDTH))
    grey = np.where((rows % 2 == 1) & (cols % 2 == 1), 1, 2).astype(np.uint8)
    return np.repeat(grey[:, :, None], 3, axis=2)


COVERED = covered_frame()


# How long stop() waits for each thread: a source blocked longer is left behind (daemon).
JOIN_TIMEOUT_S = 1.0


class NoFrame(Exception):
    """A source has no frame for this slot (a webcam not delivering): the slot is skipped,
    counted as missed and not logged; the source says itself what is wrong."""


class FrameSource(Protocol):
    """Where one camera's frames come from; `name` is what its `NaoqiSim/Camera/*/Source` says."""

    name: str

    def frame(self) -> np.ndarray:
        """A (480, 640, 3) uint8 RGB image; `NoFrame` when there is none for now, `WorldClosed`
        when there will be no more."""
        ...


class RenderSource:
    """One head camera as naoqi-viewer renders it, at the robot's current pose."""

    name = "render"

    def __init__(self, world: SimWorld, camera: str):
        self._world = world
        self._camera = camera

    def frame(self) -> np.ndarray:
        return self._world.camera_frame(self._camera, WIDTH, HEIGHT)


class VideoInput:
    """Injects each camera's source's frames into that camera at that camera's `fps`, from
    `start()` to `stop()`. `sources` maps camera names (`top`, `bottom`) to their sources and
    `fps` to their rates; a camera left out is not fed."""

    def __init__(
        self,
        sources: Mapping[str, FrameSource],
        fps: Mapping[str, int],
        connect: Callable[[], Any] | None = None,
    ):
        unknown = set(sources) - set(CAMERAS)
        if unknown or not sources:
            raise ValueError(
                f"cameras must be among {list(CAMERAS)}, got {list(sources)}"
            )
        if missing := set(sources) - set(fps):
            raise ValueError(f"no fps for {sorted(missing)}")
        # In injection order; the render thread drops a camera whose source is closed.
        self._cameras = [
            (camera, sources[camera]) for camera in CAMERAS if camera in sources
        ]
        self._periods = {camera: 1.0 / fps[camera] for camera in sources}
        self._connect = connect or (lambda: stack.connect())  # a qi session
        self._session: Any = None
        self._video: Any = None
        self._memory: Any = None
        self._stopping = threading.Event()
        self._ready = threading.Condition()
        self._frames: dict[int, np.ndarray] = {}  # by camera index, awaiting injection
        self._failing: set[str] = set()
        self._covered: set[str] = (
            set()
        )  # cameras fed the covered frame in place of their source's
        self._threads: list[threading.Thread] = []
        # Frames of each camera's schedule that never reached NAOqi: a slot skipped by a render
        # that ran late, or a frame replaced by the next one before injection. Frames put +
        # missed = the schedule, per camera.
        self.missed_by_camera: dict[str, int] = dict.fromkeys(sources, 0)

    @property
    def missed(self) -> int:
        """The frames of every schedule that never reached NAOqi."""
        return sum(self.missed_by_camera.values())

    @property
    def fed(self) -> tuple[str, ...]:
        """The cameras this device feeds, in NAOqi's camera order."""
        return tuple(camera for camera, _ in self._cameras)

    def covered(self) -> dict[str, bool]:
        """Whether each camera (`top`, `bottom`) is covered."""
        return {camera: camera in self._covered for camera in CAMERAS}

    def cover(self, camera: str, covered: bool = True) -> None:
        """Covers the camera (a hand over it: `COVERED` injected in place of its source's frames)
        or uncovers it. `ValueError` for an unknown camera, `CameraNotFedError` for one this
        device does not feed."""
        if camera not in CAMERAS:
            raise ValueError(
                f"unknown camera {camera!r}: expected one of {list(CAMERAS)}"
            )
        if camera not in self.fed:
            raise CameraNotFedError(
                f"the {camera} camera gets no frames (video_input.{camera}.source is none, or "
                "its source closed), so there is nothing to cover"
            )
        if covered:
            self._covered.add(camera)
        else:
            self._covered.discard(camera)

    def start(self) -> None:
        self._session = self._connect()
        self._video = self._session.service("ALVideoDevice")
        self._memory = self._session.service("ALMemory")
        self._publish({camera: source.name for camera, source in self._cameras})
        for name, target in (("render", self._render), ("inject", self._inject)):
            thread = threading.Thread(
                target=target, name=f"naoqi-sim-video-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Stop both threads, write `none` back and close the session. Idempotent."""
        self._halt()
        for thread in self._threads:
            thread.join(timeout=JOIN_TIMEOUT_S)
        self._threads = []
        if self._session is not None:
            self._publish({})
            self._session.close()
            self._session = None

    def _halt(self) -> None:
        with self._ready:
            self._stopping.set()
            self._ready.notify_all()

    def _render(self) -> None:
        """Takes each camera's frame per slot of that camera's fixed schedule, all the schedules
        starting together; a missed slot is skipped, not caught up."""
        due = dict.fromkeys(self._periods, time.monotonic())
        while True:
            next_due = min(due[camera] for camera, _ in self._cameras)
            if self._stopping.wait(max(0.0, next_due - time.monotonic())):
                return
            now = time.monotonic()
            images: dict[int, np.ndarray] = {}
            for camera, source in list(self._cameras):
                if due[camera] > now:
                    continue  # not this camera's slot
                try:
                    image = source.frame()  # rendered even when covered: a closed
                    # viewer is noticed, and the scene's time keeps its pace
                    images[CAMERAS[camera]] = (
                        COVERED if camera in self._covered else image
                    )
                except NoFrame:
                    if camera in self._covered:
                        # a hand over the lens is dark whether or not the source delivers
                        images[CAMERAS[camera]] = COVERED
                    else:
                        self.missed_by_camera[camera] += 1
                except WorldClosed:
                    if self._stopping.is_set():
                        return
                    self._closed(source.name)
                    if not self._cameras:
                        self._halt()
                        return
                    continue
                except Exception as e:  # noqa: BLE001 (a bad frame must not end the device)
                    self._failed(f"render {camera}", e)
                else:
                    self._succeeded(f"render {camera}")
                period = self._periods[camera]
                due[camera] += period
                late = time.monotonic() - due[camera]
                if late >= 0:  # this camera's next slot is already past: skipped
                    skipped = int(late / period) + 1
                    self.missed_by_camera[camera] += skipped
                    due[camera] += skipped * period
            if images:
                with self._ready:
                    for camera, source in self._cameras:
                        index = CAMERAS[camera]
                        if index in images:
                            if index in self._frames:  # not injected yet: replaced
                                self.missed_by_camera[camera] += 1
                            self._frames[index] = images[index]
                    self._ready.notify_all()

    def _closed(self, name: str) -> None:
        """A source has no more frames (the viewer's window closed): every camera it fed is
        dropped, said once, and its keys go back to `none`; the other cameras carry on."""
        gone = [camera for camera, source in self._cameras if source.name == name]
        self._cameras = [(c, s) for c, s in self._cameras if s.name != name]
        self._covered.difference_update(gone)
        log.warning(
            "the viewer is closed: the robot's %s camera%s get%s no more frames",
            " and ".join(gone),
            "s" if len(gone) > 1 else "",
            "" if len(gone) > 1 else "s",
        )
        self._publish({camera: source.name for camera, source in self._cameras})

    def _inject(self) -> None:
        while True:
            with self._ready:
                while not self._frames and not self._stopping.is_set():
                    self._ready.wait()
                if self._stopping.is_set():
                    return
                pending = sorted(self._frames.items())
                self._frames.clear()
            for index, image in pending:
                try:
                    accepted = self._video.putImage(
                        index, WIDTH, HEIGHT, image.tobytes()
                    )
                except Exception as e:  # noqa: BLE001 (NAOqi may be busy; try the next frame)
                    self._failed("putImage", e)
                else:
                    if accepted:
                        self._succeeded("putImage")
                    else:
                        self._failed("putImage", "NAOqi refused the frame")

    def _failed(self, stage: str, error: object) -> None:
        """Logs the first failure of a run, then stays quiet until the stage succeeds again."""
        if stage not in self._failing:
            self._failing.add(stage)
            log.warning("video input: %s failed: %s", stage, error)

    def _succeeded(self, stage: str) -> None:
        if stage in self._failing:
            self._failing.discard(stage)
            log.info("video input: %s works again", stage)

    def _publish(self, fed: dict[str, str]) -> None:
        """Each camera's key (`none` for one not fed), then the summary: `none` when no camera
        is fed, the one source feeding them, or `mixed`."""
        names = set(fed.values())
        summary = "none" if not names else names.pop() if len(names) == 1 else MIXED
        for key, value in (
            *((camera_key(camera), fed.get(camera, "none")) for camera in CAMERAS),
            (SOURCE_KEY, summary),
        ):
            try:
                self._memory.insertData(key, value)
            except Exception as e:  # noqa: BLE001 (best effort: NAOqi may be stopping too)
                log.debug("video input: could not write %s = %s: %s", key, value, e)
