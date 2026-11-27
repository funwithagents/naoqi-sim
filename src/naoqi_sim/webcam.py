"""The webcam source of the video input: a host camera through OpenCV (specs/host/video-input.md,
"The webcam source").

`cv2` comes with the `naoqi-sim[webcam]` extra and is imported only when a camera's source is
`webcam`. A `Webcam` reads its camera on a thread of its own and keeps the newest frame; the video
input takes it at its camera's `fps`, centre-cropped to the NAO camera's 4:3, scaled to VGA and
converted to RGB. A camera that stops delivering is logged once and reopened every few seconds:
the robot never stops on a camera problem.
"""

import logging
import math
import platform
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

import numpy as np

from naoqi_sim.errors import DeviceUnavailableError, MissingExtraError
from naoqi_sim.video_input import HEIGHT, JOIN_TIMEOUT_S, WIDTH, NoFrame

log = logging.getLogger(__name__)

# A camera that cannot open or stops delivering is tried again this often.
RETRY_S = 5.0
# A slot finds no frame when the newest is older than this (a camera stuck in `read`).
FRAME_TIMEOUT_S = 5.0


class Capture(Protocol):
    """The part of `cv2.VideoCapture` a webcam uses; the tests substitute their own."""

    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def getBackendName(self) -> str: ...
    def release(self) -> None: ...


def _cv2() -> Any:
    try:
        import cv2
    except ImportError:
        raise MissingExtraError(
            "a webcam source needs OpenCV: install naoqi-sim with its `webcam` extra "
            "(`naoqi-sim[webcam]`), or run without it (no --webcam; in a config file, the "
            "camera's source 'render' or 'none')"
        ) from None
    return cv2


def open_capture(device: int) -> Capture:
    """Webcam `device` on the platform's own backend (AVFoundation, V4L2, Media Foundation)."""
    return _cv2().VideoCapture(device)


def _permission_hint() -> str:
    if platform.system() != "Darwin":
        return ""
    return (
        "; on macOS, the application that started naoqi-sim (the terminal or editor) needs "
        "Camera access in System Settings > Privacy & Security > Camera"
    )


def check_webcam(
    device: int,
    keys: Iterable[str],
    opener: Callable[[int], Capture] | None = None,
) -> None:
    """Webcam `device` opens and gives a frame (step 1 of `NaoqiSim.start()`), released after.
    `keys` are the config keys whose source it is, for the error. On macOS, a first call on
    the main thread is what asks the user for the camera permission (OpenCV needs the main
    thread's run loop for that)."""
    _cv2()
    where = f"{' and '.join(f'{key}.source' for key in keys)} 'webcam'"
    capture = (opener or open_capture)(device)
    try:
        if not capture.isOpened():
            raise DeviceUnavailableError(
                f"{where}: webcam {device} does not open{_permission_hint()}"
            )
        ok, _ = capture.read()
        if not ok:
            raise DeviceUnavailableError(
                f"{where}: webcam {device} gives no frame{_permission_hint()}"
            )
    finally:
        capture.release()


def to_vga(bgr: np.ndarray) -> np.ndarray:
    """A webcam frame (OpenCV's BGR, any size) as a (480, 640, 3) RGB image: its centre cropped
    to 4:3, scaled with area interpolation, not mirrored."""
    cv2 = _cv2()
    height, width = bgr.shape[:2]
    if width * 3 > height * 4:  # wider than 4:3: the sides go
        crop = height * 4 // 3
        left = (width - crop) // 2
        bgr = bgr[:, left : left + crop]
    elif width * 3 < height * 4:  # taller: the top and bottom go
        crop = width * 3 // 4
        top = (height - crop) // 2
        bgr = bgr[top : top + crop]
    image = cv2.resize(bgr, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class Webcam:
    """One host webcam, captured from `start()` to `stop()` on its own thread: a `FrameSource`
    serving its newest frame, which one or both cameras can take."""

    name = "webcam"

    def __init__(
        self,
        device: int,
        opener: Callable[[int], Capture] | None = None,
        retry_s: float = RETRY_S,
        frame_timeout_s: float = FRAME_TIMEOUT_S,
    ):
        self.device = device
        self._opener = opener
        self._retry_s = retry_s
        self._frame_timeout_s = frame_timeout_s
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._failing = False
        self._lock = threading.Lock()
        # The newest raw frame, when it came, and its number; the last one converted.
        self._raw: np.ndarray | None = None
        self._raw_at = -math.inf
        self._raw_count = 0
        self._converted: tuple[int, np.ndarray] | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # Each run its own event: a thread left behind by a stop never resumes with the next run.
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(self._stopping,),
            name=f"naoqi-sim-webcam-{self.device}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop capturing; the capture thread releases the camera. Idempotent. A `read`
        blocked longer than the join is left behind (daemon)."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=JOIN_TIMEOUT_S)
            self._thread = None

    def frame(self) -> np.ndarray:
        with self._lock:
            raw, at, count = self._raw, self._raw_at, self._raw_count
        if raw is None or time.monotonic() - at > self._frame_timeout_s:
            raise NoFrame(f"webcam {self.device} has no frame")
        converted = self._converted
        if converted is not None and converted[0] == count:
            return converted[1]  # the other camera on this webcam took it already
        image = to_vga(raw)
        self._converted = (count, image)
        return image

    def _run(self, stopping: threading.Event) -> None:
        while not stopping.is_set():
            problem = self._capture(stopping)
            if stopping.is_set():
                return
            self._report(problem)
            stopping.wait(self._retry_s)

    def _capture(self, stopping: threading.Event) -> str:
        """Open the camera and read it until it fails or the webcam stops: what went wrong."""
        try:
            capture = (self._opener or open_capture)(self.device)
        except Exception as e:  # noqa: BLE001 (a backend error must not end the device)
            return f"cannot open it: {e}"
        live = False
        try:
            if not capture.isOpened():
                return "it does not open"
            while not stopping.is_set():
                ok, image = capture.read()
                if not ok or image is None:
                    return (
                        "it stopped delivering frames" if live else "it gives no frame"
                    )
                with self._lock:
                    self._raw = image
                    self._raw_at = time.monotonic()
                    self._raw_count += 1
                if not live:
                    live = True
                    self._failing = False
                    height, width = image.shape[:2]
                    log.info(
                        "webcam %d is live: %dx%d (%s)",
                        self.device,
                        width,
                        height,
                        _backend(capture),
                    )
            return ""
        finally:
            capture.release()
            if live:
                log.info("webcam %d is off", self.device)

    def _report(self, problem: str) -> None:
        """Logs the first failure of a run, then stays quiet until the camera is live again."""
        if self._failing:
            return
        self._failing = True
        log.error(
            "webcam %d: %s; retrying every %g s%s",
            self.device,
            problem,
            self._retry_s,
            _permission_hint(),
        )


def _backend(capture: Capture) -> str:
    try:
        return capture.getBackendName()
    except Exception:  # noqa: BLE001 (only for the log)
        return "unknown backend"
