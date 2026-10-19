"""`NaoqiSim`: the one object that runs a simulated NAO on the host (specs/runtime/api.md).

Built from a `NaoqiSimConfig`, its `start()` checks the machine, starts the audio output and the host
link, the containers, the simulated world, the video input and the audio input, and returns once
the robot is ready; `stop()` takes them all down. Every step that starts something registers how to undo it, so a failed start, a
cancelled one and `stop()` share one teardown, run in reverse.
"""

import asyncio
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from naoqi_sim import docker_images, stack
from naoqi_sim.audio_input import AudioInput, FakeAudioSource, MicSource, check_mic
from naoqi_sim.audio_output import (
    AudioOutput,
    AudioSink,
    DevicePlayer,
    NullSink,
    Server,
    WavSink,
)
from naoqi_sim.config import NaoqiSettings, NaoqiSimConfig, NaoqiVersion
from naoqi_sim.errors import NaoqiSimError, NotRunningError
from naoqi_sim.host_link import HostLink
from naoqi_sim.stack import (
    AUDIO_OUTPUT_PORT,
    HOST_LINK_PORT,
    NAOQI_PORT,
    URL,
    NaoqiSimStatus,
)
from naoqi_sim.video_input import FrameSource, RenderSource, VideoInput
from naoqi_sim.viewer import SimWorld, needs_viewer, viewer_config
from naoqi_sim.webcam import Webcam, check_webcam

log = logging.getLogger(__name__)


def _sink_for(config: NaoqiSimConfig) -> AudioSink:
    settings = config.audio_output
    if settings.mode == "record":
        assert settings.record is not None  # checked by the config
        return WavSink(settings.record)
    if settings.mode == "silent":
        return NullSink()
    return DevicePlayer()


class NaoqiSim:
    """A simulated NAO: `await start()`, connect any qi client to `url`, `await stop()`."""

    def __init__(
        self,
        config: NaoqiSimConfig | NaoqiVersion | None = None,
        *,
        sink: AudioSink | None = None,
    ):
        if config is None:
            config = NaoqiSimConfig()
        elif isinstance(config, str):
            config = NaoqiSimConfig(naoqi=NaoqiSettings(version=config))
        self._config = config
        self._sink = sink if sink is not None else _sink_for(config)
        self._audio_output: AudioOutput | None = None
        self._link: HostLink | None = None
        self._audio_input: AudioInput | None = None
        self._world: SimWorld | None = None
        self._undo: list[tuple[str, Callable[[], None]]] = []
        self._running = False
        self._busy = asyncio.Lock()

    @classmethod
    def from_dict(cls, data: Any, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_dict(data), sink=sink)

    @classmethod
    def from_json(cls, text: str, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_json(text), sink=sink)

    @classmethod
    def from_json_file(cls, path: str | Path, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_json_file(path), sink=sink)

    @property
    def config(self) -> NaoqiSimConfig:
        return self._config

    @property
    def _label(self) -> str:
        return docker_images.label(self._config.naoqi.version)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def url(self) -> str:
        if not self._running:
            raise NotRunningError("this NaoqiSim is not running: await start() first")
        return URL

    @property
    def fake_audio(self) -> FakeAudioSource:
        """The fake audio source, which a test plays sounds through (specs/host/audio-input.md)."""
        self.url  # noqa: B018  (raises NotRunningError)
        source = self._audio_input.source if self._audio_input is not None else None
        if not isinstance(source, FakeAudioSource):
            raise NaoqiSimError(
                f"audio_input.source is {self._config.audio_input.source!r}, not 'fake': "
                "no fake audio source to play into"
            )
        return source

    @property
    def props(self) -> Any:
        """The props a test puts in the simulated world (specs/host/props.md): naoqi-viewer's
        `PropsClient`, positions in the scene's frame or the robot's (`frame="robot"`)."""
        self.url  # noqa: B018  (raises NotRunningError)
        if self._world is None:
            raise NaoqiSimError(
                "this config runs no viewer, so there is no world to put props in: "
                "set viewer.headless to false, or a camera's source to 'render'"
            )
        return self._world.props

    async def status(self) -> NaoqiSimStatus:
        """What the `NaoqiSim` service reports, read over qi."""
        self.url  # noqa: B018  (raises NotRunningError)
        return await asyncio.to_thread(stack.read_naoqisim_status, URL)

    # --- Lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        """Check the machine, start everything, and return once the robot is ready."""
        async with self._busy:
            if self._running:
                raise NaoqiSimError("this NaoqiSim is already running")
            log.info("%s: starting", self._label)
            abort = threading.Event()
            try:
                world_config = await self._step(abort, self._check)
                self._check_webcams()
                await self._step(abort, self._start_audio_output)
                await self._step(abort, self._start_containers)
                await self._step(abort, stack.wait_ready, self._config, abort)
                world = None
                if world_config is not None:
                    world = await self._step(abort, self._start_world, world_config)
                if any(s != "none" for s in self._config.video_input.sources.values()):
                    await self._step(abort, self._start_video_input, world)
                if self._config.audio_input.source != "none":
                    await self._step(abort, self._start_audio_input)
            except BaseException:
                await asyncio.to_thread(self._teardown, False)
                raise
            self._running = True

    @staticmethod
    async def _step[T](abort: threading.Event, fn: Callable[..., T], *args: Any) -> T:
        """One step of `start()`, on a thread. A thread can't be interrupted: cancelled, the
        step still runs to its end (after `abort` tells a waiting step to give up), so the
        teardown never races what the step is starting, such as a `compose up` in flight."""
        future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            abort.set()
            await asyncio.wait([future])
            raise

    async def stop(self) -> None:
        """Stop the audio and video inputs, the simulated world, the containers, the host link and
        the audio output; a no-op when not running. Carries on through every step and raises the
        first failure."""
        async with self._busy:
            if not self._running:
                return
            self._running = False
            log.info("%s: stopping", self._label)
            await asyncio.to_thread(self._teardown, True)
            log.info("%s: NAOqi stopped", self._label)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # --- Steps ----------------------------------------------------------------------

    def _check(self) -> Any:
        """Step 1: what the machine must offer before anything starts. Returns the viewer's
        config when the simulated world runs, else None."""
        config = self._config
        log.info("%s: checking Docker, the images and the ports", self._label)
        docker_images.require_docker()
        docker_images.check_images(config.naoqi.version)
        world_config = (
            viewer_config(config.viewer, URL) if needs_viewer(config) else None
        )
        if config.audio_input.source == "mic":
            check_mic()
        docker_images.require_free(NAOQI_PORT)
        docker_images.require_free(AUDIO_OUTPUT_PORT)
        if config.audio_input.source != "none":
            docker_images.require_free(HOST_LINK_PORT)
        return world_config

    def _webcams(self) -> dict[int, list[str]]:
        """Each webcam device the cameras' sources name, with the config keys naming it."""
        webcams: dict[int, list[str]] = {}
        for camera in self._config.video_input.cameras("webcam"):
            device = getattr(self._config.video_input, camera).device
            webcams.setdefault(device, []).append(f"video_input.{camera}")
        return webcams

    def _check_webcams(self) -> None:
        """Step 1, on the calling thread rather than a step's: on macOS, OpenCV can only ask the
        user for the camera permission from the main thread."""
        for device, keys in self._webcams().items():
            log.info(
                "%s: opening webcam %d for %s%s",
                self._label,
                device,
                ", ".join(keys),
                " (macOS may ask for the camera permission)"
                if sys.platform == "darwin"
                else "",
            )
            check_webcam(device, keys)

    def _start_audio_output(self) -> None:
        log.info(
            "%s: starting the audio output (%s)", self._label, type(self._sink).__name__
        )
        self._audio_output = AudioOutput(self._sink)
        server = Server(("0.0.0.0", AUDIO_OUTPUT_PORT), self._audio_output)
        thread = threading.Thread(
            target=server.serve_forever, name="naoqi-sim-audio-output", daemon=True
        )
        thread.start()

        def stop_audio_output() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if isinstance(self._sink, WavSink):
                self._sink.close()

        self._undo.append(("audio output", stop_audio_output))
        if self._config.audio_input.source != "none":
            # Open before the containers boot, so ALAudioDevice finds it; closed after them.
            log.info(
                "%s: opening the host link on port %d", self._label, HOST_LINK_PORT
            )
            self._link = HostLink(HOST_LINK_PORT)
            self._undo.append(("host link", self._close_link))

    def _close_link(self) -> None:
        link, self._link = self._link, None
        if link is not None:
            link.close()

    def _start_containers(self) -> None:
        version = self._config.naoqi.version
        log.info(
            "%s: starting the containers (tts, %s)",
            self._label,
            docker_images.IMAGES[version].service,
        )
        # Registered first: a failed `up` may have started some of them.
        self._undo.append(("containers", lambda: stack.down(version)))
        stack.up(self._config)

    def _start_world(self, world_config: Any) -> SimWorld:
        log.info(
            "%s: starting naoqi-viewer (%s)",
            self._label,
            "headless" if self._config.viewer.headless else "window",
        )
        world = SimWorld(world_config)
        self._undo.append(("viewer", self._close_world))
        self._world = world
        world.launch()
        return world

    def _close_world(self) -> None:
        world, self._world = self._world, None
        if world is not None:
            world.close()

    def _start_video_input(self, world: SimWorld | None) -> None:
        """The cameras the config feeds, each from its source: the viewer's render, or a webcam
        (one capture per device, which both cameras can share), captures started first."""
        settings = self._config.video_input
        log.info(
            "%s: starting the video input (%s)",
            self._label,
            ", ".join(
                f"{camera} from "
                + (f"webcam {getattr(settings, camera).device}" if s == "webcam" else s)
                for camera, s in settings.sources.items()
                if s != "none"
            ),
        )
        sources: dict[str, FrameSource] = {}
        for camera in self._config.video_input.cameras("render"):
            assert world is not None  # needs_viewer() launched it for a rendered camera
            sources[camera] = RenderSource(world, camera)
        webcams: dict[int, Webcam] = {}
        for camera in self._config.video_input.cameras("webcam"):
            index = getattr(self._config.video_input, camera).device
            if index not in webcams:
                webcams[index] = Webcam(index)
                # Registered before the video input's, so the teardown stops it after.
                self._undo.append((f"webcam {index}", webcams[index].stop))
                webcams[index].start()
            sources[camera] = webcams[index]
        device = VideoInput(sources, self._config.video_input.rates)
        # Registered after the viewer's, so the teardown stops it first.
        self._undo.append(("video input", device.stop))
        device.start()

    def _start_audio_input(self) -> None:
        settings = self._config.audio_input
        log.info(
            "%s: starting the audio input (%s source)", self._label, settings.source
        )
        assert self._link is not None and self._audio_output is not None
        source = (
            FakeAudioSource(settings.mono)
            if settings.source == "fake"
            else MicSource(settings.mono)
        )
        device = AudioInput(source, settings.mono)
        self._audio_input = device
        if isinstance(source, FakeAudioSource):  # the fake room hears the robot speak
            self._audio_output.listeners.append(source.hear)
        # Registered last, so the teardown stops it first.
        self._undo.append(("audio input", self._stop_audio_input))
        self._link.register(AudioInput.service, device)
        device.start()

    def _stop_audio_input(self) -> None:
        device, self._audio_input = self._audio_input, None
        if device is not None:
            device.stop()

    def _teardown(self, raise_first: bool) -> None:
        """Undo every started step, newest first, through failures."""
        first: BaseException | None = None
        while self._undo:
            name, undo = self._undo.pop()
            log.info("%s: stopping the %s", self._label, name)
            try:
                undo()
            except Exception as e:  # noqa: BLE001 (stop carries on through every step)
                log.error("naoqi-sim stop: %s failed: %s", name, e)
                first = first or e
        if raise_first and first is not None:
            raise first
