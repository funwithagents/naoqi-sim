"""The containers of a running naoqi-sim, and what other terminals read from them (specs/runtime/api.md).

`up`/`down`/`wait_ready` are the container steps of `NaoqiSim.start()` and `stop()`.
`read_status` and `cleanup` serve `naoqi-sim status` and `naoqi-sim cleanup`, run from any
terminal: they read Docker and the `NaoqiSim` service, so they need no `NaoqiSim` object.
"""

import asyncio
import json
import logging
import subprocess
import threading
from dataclasses import dataclass

from naoqi_sim import docker_images, files
from naoqi_sim.config import NaoqiSimConfig
from naoqi_sim.docker_images import COMPOSE, IMAGES, run
from naoqi_sim.errors import BootError, NaoqiSimError

log = logging.getLogger(__name__)

PROJECT = "naoqi-sim"
URL = "tcp://127.0.0.1:9559"
NAOQI_PORT = docker_images.NAOQI_PORT
AUDIO_OUTPUT_PORT = 9562  # the tts container streams to host.docker.internal:9562
HOST_LINK_PORT = (
    9563  # the containers' services connect out to host.docker.internal:9563
)


@dataclass(frozen=True)
class NaoqiSimStatus:
    """What the `NaoqiSim` service inside NAOqi reports (specs/container/status-service.md)."""

    version: str
    naoqi_version: str
    ready: bool
    camera_source: str
    audio_source: str
    # "engine" when the perception engine serves the modules, "none" when they find nobody
    perception_source: str = "none"


@dataclass(frozen=True)
class ContainerState:
    name: str
    service: str
    state: str  # running, exited, ...
    health: str  # healthy, starting, unhealthy, or "" without a healthcheck


@dataclass(frozen=True)
class StackStatus:
    """Whatever naoqi-sim runs on this machine: its containers, and its `NaoqiSim` service once
    the NAOqi container is healthy."""

    containers: list[ContainerState]
    naoqi: NaoqiSimStatus | None

    @property
    def ready(self) -> bool:
        return self.naoqi is not None and self.naoqi.ready


# --- The container steps of NaoqiSim.start() and stop() -------------------------------


def services(config: NaoqiSimConfig) -> list[str]:
    """The compose services a config runs: the engines, then the version's NAOqi service."""
    engines = ["tts", "perception"] if config.perception.enabled else ["tts"]
    return [*engines, IMAGES[config.naoqi.version].service]


def compose_env(config: NaoqiSimConfig) -> dict[str, str]:
    """The environment every compose call of a run gets, from the config: the installed
    languages, and the perception engine's URL, empty when the engine is off so the NAOqi
    modules reach none (compose keeps an empty value as is)."""
    return {
        **files.compose_env(),
        "NAOQI_SIM_LANGUAGES": ",".join(config.speech.languages),
        "NAOQI_SIM_PERCEPTION_URL": docker_images.PERCEPTION_URL
        if config.perception.enabled
        else "",
    }


def up(config: NaoqiSimConfig) -> None:
    """Start the engines the config runs and the version's NAOqi service from the verified
    images."""
    images = IMAGES[config.naoqi.version]
    res = run(
        *images.compose(),
        "up",
        "-d",
        "--no-build",
        *services(config),
        timeout=300,
        env=compose_env(config),
    )
    if res.returncode != 0:
        raise BootError(
            f"docker compose up failed for NAOqi {images.version}:\n{res.stderr[-3000:]}"
        )


def wait_ready(config: NaoqiSimConfig, abort: threading.Event | None = None) -> None:
    """Until NAOqi is healthy, then until the speech engine is, then until the perception engine
    is when the config runs it: they boot in parallel, and the speech engine's first use of a
    language downloads its voice, which NAOqi's boot usually hides."""
    images = IMAGES[config.naoqi.version]
    docker_images.wait_healthy(
        images, timeout=config.naoqi.ready_timeout_s, abort=abort
    )
    docker_images.wait_tts(
        images,
        config.speech.languages,
        timeout=config.naoqi.ready_timeout_s,
        abort=abort,
    )
    if config.perception.enabled:
        docker_images.wait_perception(
            images, timeout=config.naoqi.ready_timeout_s, abort=abort
        )


def down(version: str) -> None:
    """`docker compose down`: removes the containers, keeps the package store volumes."""
    res = run(*IMAGES[version].compose(), "down", timeout=300, env=files.compose_env())
    if res.returncode != 0:
        raise NaoqiSimError(
            f"docker compose down failed for NAOqi {version}:\n{res.stderr[-3000:]}"
        )


# --- Without a NaoqiSim object --------------------------------------------------------


def _containers() -> list[ContainerState]:
    res = run("docker", "compose", "-p", PROJECT, "ps", "-a", "--format", "json")
    if res.returncode != 0:
        raise NaoqiSimError(f"docker compose ps failed:\n{res.stderr[-3000:]}")
    # One JSON object per line (Compose 2.21+), or one array (older releases).
    text = res.stdout.strip()
    rows = (
        json.loads(text)
        if text.startswith("[")
        else [json.loads(line) for line in text.splitlines() if line.strip()]
    )
    return sorted(
        (
            ContainerState(
                r.get("Name", ""),
                r.get("Service", ""),
                r.get("State", ""),
                r.get("Health", ""),
            )
            for r in rows
        ),
        key=lambda c: c.name,
    )


def connect(url: str = URL):
    """A qi session to the robot, in one attempt (libqi 3.1.8 fixed the failed connects that
    3.1.6 needed retries for)."""
    import qi

    session = qi.Session()
    try:
        session.connect(url)
    except RuntimeError as e:
        session.close()
        raise NaoqiSimError(f"could not connect to {url}: {e}") from None
    return session


def read_naoqisim_status(url: str = URL) -> NaoqiSimStatus:
    """Read the `NaoqiSim` service and its ALMemory keys over qi."""
    session = connect(url)
    try:
        naoqisim = session.service("NaoqiSim")
        memory = session.service("ALMemory")
        try:
            perception_source = memory.getData("NaoqiSim/Perception/Source")
        except RuntimeError:  # an image built before the perception modules
            perception_source = "none"
        return NaoqiSimStatus(
            version=naoqisim.getVersion(),
            naoqi_version=naoqisim.getNaoqiVersion(),
            ready=bool(naoqisim.isReady()),
            camera_source=memory.getData("NaoqiSim/Camera/Source"),
            audio_source=memory.getData("NaoqiSim/Audio/Source"),
            perception_source=str(perception_source),
        )
    finally:
        session.close()


def _read_status() -> StackStatus:
    docker_images.require_docker()
    containers = _containers()
    naoqi_healthy = any(
        c.service in {i.service for i in IMAGES.values()}
        and c.state == "running"
        and c.health == "healthy"
        for c in containers
    )
    return StackStatus(containers, read_naoqisim_status() if naoqi_healthy else None)


async def read_status() -> StackStatus:
    """The state of whatever naoqi-sim runs on this machine."""
    return await asyncio.to_thread(_read_status)


def _cleanup() -> list[str]:
    docker_images.require_docker()
    try:
        docker_images.require_free(AUDIO_OUTPUT_PORT)
    except NaoqiSimError:
        raise NaoqiSimError(
            "a naoqi-sim is still running (its audio output holds port "
            f"{AUDIO_OUTPUT_PORT}): press Ctrl-C in its terminal to stop it"
        ) from None
    names = [c.name for c in _containers()]
    res = run(
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "--profile",
        "*",
        "down",
        timeout=300,
        env=files.compose_env(),
    )
    if res.returncode != 0:
        raise NaoqiSimError(f"docker compose down failed:\n{res.stderr[-3000:]}")
    return names


async def cleanup() -> list[str]:
    """Remove what a `NaoqiSim` that died without stopping left behind; returns the containers
    removed. Refuses while a naoqi-sim is still running."""
    return await asyncio.to_thread(_cleanup)


def show_logs(follow: bool = False, tail: int | None = None) -> int:
    """`docker compose logs` on the naoqi-sim project, straight to the terminal."""
    docker_images.require_docker()
    args = ["docker", "compose", "-p", PROJECT, "logs"]
    if follow:
        args.append("--follow")
    if tail is not None:
        args += ["--tail", str(tail)]
    try:
        return subprocess.run(docker_images.resolve(args), check=False).returncode
    except KeyboardInterrupt:
        return 0
