"""The controls: a web page a running `NaoqiSim` serves, and its HTTP API (specs/host/controls.md).

A person's hands on the simulated robot: touches held together, a camera covered, the gesture
that stops the running activity. The controls own no signal: each request drives the device that
owns it, the touch input (holder `controls`) or the video input. Python's standard HTTP server on
127.0.0.1, one thread per request; the page is package data and uses nothing but this API.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import urlsplit

from naoqi_sim.config import NaoqiVersion
from naoqi_sim.errors import CameraNotFedError
from naoqi_sim.touch_input import TouchInput, resolve
from naoqi_sim.video_input import CAMERAS, VideoInput

log = logging.getLogger(__name__)

HOLDER = "controls"
HOST = "127.0.0.1"
MAX_BODY = 64 * 1024
MAX_TAP_S = 60.0  # a request holds its thread while the tap lasts

# The gesture that stops the focused activity, per version (specs/host/touch-input.md, "What a
# touch does, per version"): on 2.1 the three head sensors held 3 s, past the threshold; on 2.8
# the front sensor held between 1 and 2.9 s while the top camera is covered.
STOP_HOLD_21_S = 3.5
STOP_HOLD_28_S = 2.0
COVER_SETTLE_S = (
    0.5  # covered frames reach _ALBrightnessStatistics, which raises at 10 Hz
)


def stop_activity_gesture(
    version: NaoqiVersion,
    touch: TouchInput,
    video: VideoInput | None,
    holder: str,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Does `version`'s stop gesture with `holder`'s hands; returns once it is done (the
    activity stops a few seconds later, Life's own delay). On 2.8 `CameraNotFedError` when the
    top camera gets no frames: there is no camera to cover."""
    if version == "2.1":
        touch.press(holder, ["Head"])
        try:
            sleep(STOP_HOLD_21_S)
        finally:
            touch.release(holder, ["Head"])
        return
    if video is None:
        raise CameraNotFedError(
            "the top camera gets no frames (video_input.top.source is none), and 2.8's stop "
            "gesture covers it"
        )
    was_covered = video.covered()["top"]
    video.cover("top", True)
    try:
        sleep(COVER_SETTLE_S)
        touch.press(holder, ["Head/Touch/Front"])
        try:
            sleep(STOP_HOLD_28_S)
        finally:
            touch.release(holder, ["Head/Touch/Front"])
        sleep(
            COVER_SETTLE_S
        )  # released while still dark, as a hand leaves the head first
    finally:
        if not was_covered:
            video.cover("top", False)


class RequestError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def page() -> bytes:
    """The controls page, shipped as package data."""
    return (resources.files("naoqi_sim") / "controls.html").read_bytes()


class Controls:
    """The server, from `start()` to `stop()`; `stop()` releases what the controls hold."""

    def __init__(
        self,
        port: int,
        version: NaoqiVersion,
        touch: TouchInput,
        video: VideoInput | None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.port = port
        self.version: NaoqiVersion = version
        self.touch = touch
        self.video = video
        self.sleep = sleep
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._gesture = threading.Lock()  # one gesture at a time

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def start(self) -> None:
        self._server = ThreadingHTTPServer((HOST, self.port), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            args=(0.1,),  # the poll interval: how long stop() may wait
            name="naoqi-sim-controls",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the controls' holds. Idempotent."""
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            self.touch.release(HOLDER)
        except RuntimeError:  # the touch input already stopped, releasing everything
            pass

    # --- What each request does --------------------------------------------------------

    def state(self) -> dict[str, Any]:
        covered = self.video.covered() if self.video is not None else {}
        fed = self.video.fed if self.video is not None else ()
        return {
            "naoqi_version": self.version,
            "touch": {
                "pressed": self.touch.pressed(),
                "held": self.touch.held(HOLDER),
            },
            "cameras": {
                camera: {"covered": covered.get(camera, False), "fed": camera in fed}
                for camera in CAMERAS
            },
        }

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        parts = path.strip("/").split("/")
        match parts:
            case ["api", "touch", "press"]:
                self.touch.press(HOLDER, _sensors(body, required=True))
            case ["api", "touch", "release"]:
                sensors = _sensors(body, required=False)
                self.touch.release(HOLDER, sensors or None)
            case ["api", "touch", "tap"]:
                sensors = _sensors(body, required=True)
                duration = body.get("duration_s", 0.2)
                if (
                    isinstance(duration, bool)
                    or not isinstance(duration, (int, float))
                    or not 0 <= duration <= MAX_TAP_S
                ):
                    raise RequestError(
                        HTTPStatus.BAD_REQUEST,
                        f"duration_s must be a number of seconds, 0 to {MAX_TAP_S:g}",
                    )
                self.touch.press(HOLDER, sensors)
                try:
                    self.sleep(float(duration))
                finally:
                    self.touch.release(HOLDER, sensors)
            case ["api", "cameras", camera]:
                if camera not in CAMERAS:
                    raise RequestError(
                        HTTPStatus.BAD_REQUEST, f"unknown camera {camera!r}"
                    )
                covered = body.get("covered")
                if not isinstance(covered, bool):
                    raise RequestError(
                        HTTPStatus.BAD_REQUEST, "covered must be true or false"
                    )
                if self.video is None:
                    raise CameraNotFedError(
                        f"the {camera} camera gets no frames, so there is nothing to cover"
                    )
                self.video.cover(camera, covered)
            case ["api", "gestures", "stop-activity"]:
                with self._gesture:
                    stop_activity_gesture(
                        self.version, self.touch, self.video, HOLDER, self.sleep
                    )
            case ["api", "gestures", name]:
                raise RequestError(HTTPStatus.BAD_REQUEST, f"unknown gesture {name!r}")
            case _:
                raise RequestError(HTTPStatus.NOT_FOUND, f"no such request: {path}")
        return self.state()

    # --- HTTP ----------------------------------------------------------------------------

    def _allowed_hosts(self) -> set[str]:
        return {f"{HOST}:{self.port}", f"localhost:{self.port}"}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        controls = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "naoqi-sim-controls"

            def log_message(self, format: str, *args: Any) -> None:
                log.debug("controls: " + format, *args)

            def do_GET(self) -> None:
                if not self._host_ok():
                    return
                path = urlsplit(self.path).path
                if path in ("/", "/index.html"):
                    self._send(HTTPStatus.OK, page(), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._json(HTTPStatus.OK, controls.state())
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": f"no such page: {path}"})

            def do_POST(self) -> None:
                if not self._host_ok():
                    return
                origin = self.headers.get("Origin")
                if origin is not None and urlsplit(origin).netloc not in (
                    controls._allowed_hosts()
                ):
                    self._json(
                        HTTPStatus.FORBIDDEN, {"error": f"refused origin {origin}"}
                    )
                    return
                kind = (self.headers.get("Content-Type") or "").split(";")[0].strip()
                if kind != "application/json":
                    self._json(
                        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                        {"error": "the body must be application/json"},
                    )
                    return
                try:
                    body = self._body()
                    answer = controls.post(urlsplit(self.path).path, body)
                except RequestError as e:
                    self._json(e.status, {"error": e.message})
                except ValueError as e:  # an unknown sensor or camera
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                except CameraNotFedError as e:
                    self._json(HTTPStatus.CONFLICT, {"error": str(e)})
                except Exception as e:  # noqa: BLE001 (NAOqi stopping: say it, carry on)
                    log.warning("controls: %s failed: %s", self.path, e)
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})
                else:
                    self._json(HTTPStatus.OK, answer)

            def _host_ok(self) -> bool:
                """A page of another site can reach a local port by a name of its own pointing
                at 127.0.0.1: only our own address is served."""
                if self.headers.get("Host") in controls._allowed_hosts():
                    return True
                self._json(HTTPStatus.FORBIDDEN, {"error": "refused Host"})
                return False

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise RequestError(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large"
                    )
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError as e:
                    raise RequestError(HTTPStatus.BAD_REQUEST, f"bad JSON: {e}") from e
                if not isinstance(body, dict):
                    raise RequestError(
                        HTTPStatus.BAD_REQUEST, "the body must be an object"
                    )
                return body

            def _json(self, status: HTTPStatus, value: Any) -> None:
                self._send(status, json.dumps(value).encode(), "application/json")

            def _send(self, status: HTTPStatus, data: bytes, kind: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

        return Handler


def _sensors(body: dict[str, Any], *, required: bool) -> list[str]:
    sensors = body.get("sensors", [])
    if not isinstance(sensors, list) or not all(isinstance(s, str) for s in sensors):
        raise RequestError(HTTPStatus.BAD_REQUEST, "sensors must be a list of names")
    if required and not sensors:
        raise RequestError(HTTPStatus.BAD_REQUEST, "name at least one sensor")
    resolve(sensors)  # ValueError: 400
    return sensors
