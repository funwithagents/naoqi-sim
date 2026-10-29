"""The Docker images a simulated NAO runs on: fetched, built and verified once, checked at every start.

`fetch_and_build_images` does everything slow or downloaded, per NAOqi version: it fetches the
image data (`suite.fetch`), builds the version's NAOqi image, the `tts` image and the
`perception` image with the installed naoqi-sim version and the digest of the `docker/` recipes
as labels, then boots them until the NAOqi container is healthy and the two engines answer, and
takes them down. Only the image IDs that booted are
recorded, in `images.json` next to the image data.

`check_images` is what a start runs instead: the images exist, carry this naoqi-sim's version,
were built from the recipes as they are now (so an edit under `docker/` asks for a rebuild) and
were verified. It never downloads or builds.
"""

import asyncio
import hashlib
import importlib.metadata
import json
import logging
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from naoqi_sim import files, suite
from naoqi_sim.config import SpeechSettings
from naoqi_sim.errors import (
    BootError,
    DockerUnavailableError,
    FetchError,
    ImageBuildError,
    ImagesMissingError,
    ImagesOutdatedError,
    PortInUseError,
)

log = logging.getLogger(__name__)

DOCKER = (
    files.RECIPES
)  # the package data when installed, the checkout's docker/ otherwise
COMPOSE = DOCKER / "compose.yaml"
IMAGE_DATA = files.IMAGE_DATA
RECORD = "images.json"  # in the image data folder, gitignored with it
LABEL = "io.naoqi-sim.version"
RECIPES_LABEL = "io.naoqi-sim.recipes"
TTS_IMAGE = "naoqi-sim/tts:dev"
TTS_CONTAINER = "naoqi-sim-tts"
PERCEPTION_IMAGE = "naoqi-sim/perception:dev"
PERCEPTION_CONTAINER = "naoqi-sim-perception"
PERCEPTION_URL = "http://perception:8080"  # where the NAOqi services reach the engine
NAOQI_PORT = 9559
READY_TIMEOUT = 240.0  # seconds for the NAOqi container to turn healthy
TTS_TIMEOUT = (
    60.0  # seconds for the tts engine to load its voices once NAOqi is healthy
)
PERCEPTION_TIMEOUT = 60.0  # seconds for the perception engine to load its model
POLL = 1.0


@dataclass(frozen=True)
class Images:
    version: str
    image: str  # the NAOqi image tag
    service: str  # its compose service
    container: str
    profile: (
        str  # its compose profile: every NAOqi service has one, so one runs at a time
    )

    def compose(self) -> list[str]:
        return ["docker", "compose", "-f", str(COMPOSE), "--profile", self.profile]

    @property
    def tags(self) -> tuple[str, ...]:
        """Every image a start of this version needs, the engines' included."""
        return (self.image, TTS_IMAGE, PERCEPTION_IMAGE)


IMAGES = {
    "2.1": Images(
        "2.1", "naoqi-sim/naoqi:2.1.4.13", "naoqi21", "naoqi-sim-naoqi21", "2.1"
    ),
    "2.8": Images(
        "2.8", "naoqi-sim/naoqi:2.8.7.4", "naoqi28", "naoqi-sim-naoqi28", "2.8"
    ),
}


def label(version: str) -> str:
    """What every line naoqi-sim logs or prints about a version's simulated NAO starts with."""
    return f"NAOqi {version} (sim)"


def naoqi_sim_version() -> str:
    """The installed naoqi-sim version, built into the images and checked at start."""
    return importlib.metadata.version("naoqi-sim")


def _command(version: str) -> str:
    return f"run `naoqi-sim fetch-and-build-images {version}`"


def resolve(args: Iterable[str]) -> list[str]:
    """`args` with its command found on PATH as a shell finds it: on Windows, `subprocess` looks
    for `<name>.exe` only, where `shutil.which` follows PATHEXT (`.cmd`, `.bat`...)."""
    command, *rest = args
    return [shutil.which(command) or command, *rest]


def run(
    *args: str, timeout: float = 120, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve(args),
        capture_output=True,
        encoding="utf-8",  # docker's own output, whatever the locale (Windows' isn't UTF-8)
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
    )


def recipes_digest(docker: Path | None = None) -> str:
    """SHA-256 of what the images are built from, besides the image data (pinned by hash):
    every file under `docker/` with its relative path, skipping `image-data/`, hidden files and
    Python caches."""
    root = docker or DOCKER
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (
            not path.is_file()
            or rel.parts[0] == "image-data"
            or any(part.startswith(".") or part == "__pycache__" for part in rel.parts)
            or path.suffix == ".pyc"
        ):
            continue
        h.update(rel.as_posix().encode() + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class _Found:
    id: str
    version: str | None
    recipes: str | None


def _inspect(tag: str) -> _Found | None:
    """The image's ID and naoqi-sim labels, or None if there is no such image."""
    res = run("docker", "image", "inspect", tag)
    if res.returncode != 0:
        return None
    info = json.loads(res.stdout)[0]
    labels = (info.get("Config") or {}).get("Labels") or {}
    return _Found(info["Id"], labels.get(LABEL), labels.get(RECIPES_LABEL))


def _verified(image_data: Path) -> dict[str, str]:
    """Image tag to the ID that last passed verification."""
    path = image_data / RECORD
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["verified"]


def _record(image_data: Path, verified: dict[str, str]) -> None:
    image_data.mkdir(parents=True, exist_ok=True)
    (image_data / RECORD).write_text(
        json.dumps({"verified": verified}, indent=2) + "\n", encoding="utf-8"
    )


def check_images(version: str, image_data: Path = IMAGE_DATA) -> None:
    """Raise unless the version's NAOqi image, the tts image and the perception image are built
    by this naoqi-sim version, from the recipes as they are now, and verified (the perception
    image whether or not a config runs the engine). Needs Docker; downloads and builds nothing."""
    images = IMAGES[version]
    want = naoqi_sim_version()
    recipes = recipes_digest()
    verified = _verified(image_data)
    for tag in images.tags:
        found = _inspect(tag)
        if found is None:
            raise ImagesMissingError(f"{tag} is not built: {_command(version)}")
        if found.version != want:
            raise ImagesOutdatedError(
                f"{tag} was built by naoqi-sim {found.version or '(unknown)'}, this is "
                f"naoqi-sim {want}: {_command(version)}"
            )
        if found.recipes != recipes:
            raise ImagesOutdatedError(
                f"{tag} was built from other recipes (docker/ changed since): "
                + _command(version)
            )
        if verified.get(tag) != found.id:
            raise ImagesMissingError(f"{tag} was not verified: {_command(version)}")


def require_docker() -> None:
    if shutil.which("docker") is None or run("docker", "info").returncode != 0:
        raise DockerUnavailableError(
            "Docker is not available: install it or start it (Docker Desktop, OrbStack)"
        )


def require_free(port: int) -> None:
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise PortInUseError(
                f"127.0.0.1:{port} is taken: stop the running naoqi-sim (or the stack "
                "started by hand) first"
            )


def container_logs(container: str) -> str:
    res = run("docker", "logs", "--tail", "60", container)
    return (res.stdout + res.stderr).strip()


class _BootLog:
    """The NAOqi container's log as it boots: the entrypoint's `still waiting` lines at INFO,
    which name what a slow boot waits for, the rest at DEBUG. Reads the whole log each time and
    counts the lines already relayed."""

    def __init__(self, images: Images):
        self._prefix = label(images.version)
        self._container = images.container
        self._seen = [0, 0]  # stdout, stderr lines already relayed

    def relay(self) -> None:
        res = run("docker", "logs", self._container)
        if res.returncode != 0:
            return
        for i, text in enumerate((res.stdout, res.stderr)):
            lines = text.splitlines()
            for line in lines[self._seen[i] :]:
                said = line.removeprefix("[entrypoint] ")
                if said != line and said.startswith("still waiting"):
                    log.info("%s: %s", self._prefix, said)
                elif line.strip():
                    log.debug("%s | %s", self._prefix, line)
            self._seen[i] = len(lines)


def wait_healthy(
    images: Images, timeout: float | None = None, abort: threading.Event | None = None
) -> None:
    """Until the version's NAOqi container is healthy; `BootError` if it exits, turns
    unhealthy or takes longer than `timeout` (default `READY_TIMEOUT`), with the end of its log,
    or as soon as `abort` is set. Relays the container's log as it grows."""
    timeout = READY_TIMEOUT if timeout is None else timeout
    log.info(
        "%s: containers up, waiting for NAOqi to start (up to %.0f s)",
        label(images.version),
        timeout,
    )
    boot_log = _BootLog(images)
    end = time.monotonic() + timeout
    while True:
        state = _state(images.container)
        if state == ["running", "healthy"]:
            boot_log.relay()
            log.info("%s: NAOqi started", label(images.version))
            return
        if state[0] != "running" or state[1:] == ["unhealthy"]:
            raise BootError(
                f"NAOqi {images.version} did not boot ({' '.join(state)}):\n"
                + container_logs(images.container)
            )
        if time.monotonic() > end:
            raise BootError(
                f"NAOqi {images.version} not healthy after {timeout:.0f} s:\n"
                + container_logs(images.container)
            )
        boot_log.relay()
        if abort is not None and abort.wait(POLL):
            raise BootError(f"waiting for NAOqi {images.version} was cancelled")
        if abort is None:
            time.sleep(POLL)


def _state(container: str) -> list[str]:
    """`[status, health]` of a container (`["missing"]` when Docker does not know it)."""
    res = run(
        "docker",
        "inspect",
        "-f",
        "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
        container,
    )
    return res.stdout.split() if res.returncode == 0 else ["missing"]


def wait_tts(
    images: Images,
    languages: Iterable[str],
    timeout: float | None = None,
    abort: threading.Event | None = None,
) -> None:
    """Until the speech engine's container is healthy: every installed language's voice loaded,
    a language's first use downloading its voice (tts-engine.md, "Languages"). `BootError` if it
    exits, turns unhealthy or takes longer than `timeout` (default `TTS_TIMEOUT`), with the end
    of its log, or as soon as `abort` is set."""
    timeout = TTS_TIMEOUT if timeout is None else timeout
    log.info(
        "%s: waiting for the speech engine to load the voices of %s "
        "(a language's first use downloads its voice)",
        label(images.version),
        ", ".join(languages),
    )
    _engine_wait(
        "tts",
        TTS_CONTAINER,
        timeout,
        abort,
        f"{label(images.version)}: speech engine ready",
    )


def _engine_wait(
    name: str,
    container: str,
    timeout: float,
    abort: threading.Event | None,
    ready: str,
) -> None:
    """Until an engine's container is healthy; `BootError` if it exits, turns unhealthy or
    takes longer than `timeout`, with the end of its log, or as soon as `abort` is set."""
    end = time.monotonic() + timeout
    while True:
        state = _state(container)
        if state == ["running", "healthy"]:
            log.info(ready)
            return
        if state[0] != "running" or state[1:] == ["unhealthy"]:
            raise BootError(
                f"the {name} engine did not start ({' '.join(state)}):\n"
                + container_logs(container)
            )
        if time.monotonic() > end:
            raise BootError(
                f"the {name} engine not healthy after {timeout:.0f} s:\n"
                + container_logs(container)
            )
        if abort is not None and abort.wait(POLL):
            raise BootError(f"waiting for the {name} engine was cancelled")
        if abort is None:
            time.sleep(POLL)


def wait_perception(
    images: Images,
    timeout: float | None = None,
    abort: threading.Event | None = None,
) -> None:
    """Until the perception engine's container is healthy: its model loaded (perception-engine.md,
    "Image and process"). `BootError` as `wait_tts`, default `PERCEPTION_TIMEOUT`."""
    timeout = PERCEPTION_TIMEOUT if timeout is None else timeout
    log.info("%s: waiting for the perception engine", label(images.version))
    _engine_wait(
        "perception",
        PERCEPTION_CONTAINER,
        timeout,
        abort,
        f"{label(images.version)}: perception engine ready",
    )


def _build(images: Images, env: dict[str, str]) -> None:
    log.info(
        "%s: building %s, %s and %s",
        label(images.version),
        images.image,
        TTS_IMAGE,
        PERCEPTION_IMAGE,
    )
    res = run(
        *images.compose(),
        "build",
        "tts",
        "perception",
        images.service,
        timeout=3600,
        env=env,
    )
    if res.returncode != 0:
        raise ImageBuildError(
            f"docker compose build failed for NAOqi {images.version}:\n"
            + (res.stdout + res.stderr)[-3000:]
        )


def _verify(images: Images, env: dict[str, str]) -> None:
    log.info("%s: verifying the images boot", label(images.version))
    require_free(NAOQI_PORT)
    try:
        res = run(
            *images.compose(), "up", "-d", "tts", "perception", images.service, env=env
        )
        if res.returncode != 0:
            raise BootError(
                f"docker compose up failed for NAOqi {images.version}:\n{res.stderr[-3000:]}"
            )
        wait_healthy(images)
        wait_tts(images, SpeechSettings().languages)  # the image has their voices
        wait_perception(images)
    finally:
        run(*images.compose(), "down", timeout=300, env=env)


def _fetch_build_verify(images: Images, image_data: Path) -> None:
    try:
        suite.fetch(suite.VERSIONS[images.version], image_data)
    except OSError as e:  # network or disk; hash failures are FetchError already
        raise FetchError(f"fetching the NAOqi {images.version} image data: {e}") from e
    env = {
        **files.compose_env(
            image_data
        ),  # the image data folder is the build's `image-data` context
        "NAOQI_SIM_VERSION": naoqi_sim_version(),
        "NAOQI_SIM_RECIPES": recipes_digest(),
    }
    _build(images, env)
    _verify(images, env)
    verified = _verified(image_data)
    for tag in images.tags:
        found = _inspect(tag)
        if found is None:  # removed while verifying
            raise ImagesMissingError(f"{tag} disappeared: {_command(images.version)}")
        verified[tag] = found.id
    _record(image_data, verified)
    log.info("%s: images built and verified", label(images.version))


async def fetch_and_build_images(
    versions: Iterable[str] | None = None, *, image_data: Path = IMAGE_DATA
) -> None:
    """Fetch, build and verify the images of each version (default: all), in order."""
    names = list(versions or IMAGES)
    if unknown := [v for v in names if v not in IMAGES]:
        raise ValueError(
            f"unknown NAOqi version(s) {', '.join(unknown)}; choose from {', '.join(IMAGES)}"
        )
    await asyncio.to_thread(require_docker)
    for name in names:
        await asyncio.to_thread(_fetch_build_verify, IMAGES[name], image_data)
