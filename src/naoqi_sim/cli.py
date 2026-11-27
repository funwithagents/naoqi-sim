"""The `naoqi-sim` command: a thin shell over the library, which owns every check and step
(specs/runtime/cli.md).

`run` and `config` take the same description of the robot: either the robot options (`--naoqi`,
required, and what to turn on) or a `--config` file, never both. A `ConfigError` prints its message
and exits 2, as do argument errors (argparse); any other `NaoqiSimError` exits 1. `run` exits 0
once Ctrl-C (or SIGTERM) has stopped the robot.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from naoqi_sim import docker_images, stack
from naoqi_sim.config import ROBOTS, ConfigError, NaoqiSimConfig
from naoqi_sim.errors import MissingExtraError, NaoqiSimError
from naoqi_sim.sim import NaoqiSim

# The robot options of `run` and `config`, as argparse destinations with the option each is.
_ROBOT_OPTIONS = {
    "naoqi": "--naoqi",
    "robot": "--robot",
    "robot_version": "--robot-version",
    "viewer": "--viewer",
    "webcam": "--webcam",
    "mic": "--mic",
    "controls": "--controls",
}


def _add_robot_options(command: argparse.ArgumentParser) -> None:
    """What describes the robot, on `run` and `config` alike."""
    robots = sorted({kind for pairs in ROBOTS.values() for kind, _ in pairs})
    versions = sorted({version for pairs in ROBOTS.values() for _, version in pairs})
    described = command.add_argument_group(
        "the robot",
        "Either --naoqi and what to turn on, or a --config file for anything else "
        "(`naoqi-sim config` prints one to start from).",
    )
    described.add_argument(
        "--naoqi",
        metavar="VERSION",
        help=f"the NAOqi version to run: {', '.join(ROBOTS)} (required without --config)",
    )
    described.add_argument(
        "--robot",
        metavar="TYPE",
        help=f"the robot: {', '.join(robots)} (default: the NAOqi version's)",
    )
    described.add_argument(
        "--robot-version",
        metavar="VERSION",
        help=f"the robot's version: {', '.join(versions)} "
        "(default: the NAOqi version's, v5 on 2.1 and v6 on 2.8)",
    )
    described.add_argument(
        "--viewer",
        action="store_true",
        help="open the sim window and feed the robot's cameras its render "
        "(needs the `viewer` extra)",
    )
    described.add_argument(
        "--webcam",
        action="store_true",
        help="feed the robot's top camera your webcam (needs the `webcam` extra)",
    )
    described.add_argument(
        "--mic", action="store_true", help="let the robot hear your microphone"
    )
    described.add_argument(
        "--controls",
        action="store_true",
        help="serve the controls page and open it in your browser",
    )
    described.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="a NaoqiSimConfig JSON file, instead of the options above",
    )


def _config(ap: argparse.ArgumentParser, a: argparse.Namespace) -> NaoqiSimConfig:
    """The config `run` and `config` were asked for: the file's, or the robot options'."""
    given = [option for dest, option in _ROBOT_OPTIONS.items() if getattr(a, dest)]
    if a.config:
        if given:
            ap.error(
                f"--config describes the whole robot: drop {', '.join(given)}, "
                "or set them in the file"
            )
        return NaoqiSimConfig.from_json_file(a.config)
    if not a.naoqi:
        ap.error(
            f"which NAOqi? --naoqi {' or --naoqi '.join(ROBOTS)} "
            "(or --config FILE for a config of your own)"
        )
    robot = {"type": a.robot, "version": a.robot_version}
    data: dict[str, object] = {
        "naoqi": {"version": a.naoqi},
        "robot": {key: value for key, value in robot.items() if value},
    }
    cameras = {}
    if a.viewer:
        data["viewer"] = {
            "headless": False,
            "cameras_display": True,
            "people_display": True,
        }
        cameras = {"top": {"source": "render"}, "bottom": {"source": "render"}}
    if a.webcam:
        cameras["top"] = {"source": "webcam"}
    if cameras:
        data["video_input"] = cameras
    if a.mic:
        data["audio_input"] = {"source": "mic"}
    if a.controls:
        data["controls"] = {"enabled": True, "open": True}
    return NaoqiSimConfig.from_dict(data)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="naoqi-sim", description="A simulated NAOqi robot on your computer.")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    commands = ap.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "fetch-and-build-images",
        help="fetch the image data, build the images and verify they boot",
        description="Fetch the pinned Choregraphe suite and the robot's animations package "
        "(Aldebaran's software, from Aldebaran's GitHub repositories, hash-checked), build "
        "the NAOqi image and the engines' images (speech, perception, speech recognition), "
        "and verify they boot. Run once per NAOqi version before starting naoqi-sim, "
        "and again after upgrading it.",
    )
    build.add_argument(
        "--naoqi",
        dest="versions",
        nargs="+",
        required=True,
        metavar="VERSION",
        help=f"the NAOqi version(s) to fetch and build: {', '.join(docker_images.IMAGES)}; "
        "each is gigabytes of downloads and images, so name only those you run",
    )
    build.add_argument(
        "--image-data",
        type=Path,
        default=docker_images.IMAGE_DATA,
        help="default: %(default)s",
    )
    run = commands.add_parser(
        "run",
        help="run a simulated NAO in the foreground, until Ctrl-C",
        description="Start a simulated NAO and keep it running until Ctrl-C: the robot of "
        "the NAOqi version you name, speaking on your loudspeaker, with what you turn on.",
    )
    _add_robot_options(run)
    config = commands.add_parser(
        "config",
        help="print the config of a robot, to start a config file of your own",
        description="Print, as JSON with every field, the config `naoqi-sim run` would run "
        "with the same options: redirect it to a file, change it, and run it with "
        "`naoqi-sim run --config FILE`. Starts nothing.",
    )
    _add_robot_options(config)
    meshes = commands.add_parser(
        "fetch-meshes",
        help="install Aldebaran's NAO meshes for the sim window, after a license prompt",
        description="Install Aldebaran's NAO meshes, so the sim window shows the real robot "
        "instead of placeholder shapes. They are under CC BY-NC-ND 4.0 (non-commercial): "
        "the license is shown and nothing is installed until you type `yes`. Optional, once "
        "per machine; this is naoqi-viewer's own `fetch-meshes` (needs the `viewer` extra).",
    )
    meshes.add_argument(
        "--archive",
        type=Path,
        metavar="PATH",
        help="a local copy of the naoqi-meshes archive (checked like a download)",
    )
    meshes.add_argument(
        "--force", action="store_true", help="install again even if already installed"
    )
    meshes.add_argument(
        "--remove", action="store_true", help="delete the installed meshes instead"
    )
    commands.add_parser(
        "status",
        help="the containers and the robot's state; exits 0 when it is ready",
    )
    commands.add_parser(
        "cleanup",
        help="remove the containers a run that died without stopping left behind",
    )
    logs = commands.add_parser("logs", help="the containers' logs")
    logs.add_argument("--follow", "-f", action="store_true", help="keep following")
    logs.add_argument("--tail", type=int, metavar="N", help="only the last N lines")
    return ap


def _route_signals(
    loop: asyncio.AbstractEventLoop, handler: Callable[[], None]
) -> Callable[[], None]:
    """Call `handler` on the loop for Ctrl-C and SIGTERM; returns what undoes it.

    Windows' event loops have no `add_signal_handler`: there, plain handlers for Ctrl-C and
    Ctrl-Break (SIGTERM is never delivered on Windows; Ctrl-Break is the console signal another
    process can send) hand over to the loop. Python runs those handlers only when the main thread
    runs Python code, which a loop waiting for I/O may not do for a long time: a tick every 0.1 s
    makes them run promptly on any loop.
    """
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handler)
    except NotImplementedError:
        plain = [signal.SIGINT]
        if (
            ctrl_break := getattr(signal, "SIGBREAK", None)
        ) is not None:  # Windows only
            plain.append(ctrl_break)
        previous = {
            sig: signal.signal(sig, lambda *_: loop.call_soon_threadsafe(handler))
            for sig in plain
        }
        tick: asyncio.TimerHandle | None = None

        def ticking() -> None:
            nonlocal tick
            tick = loop.call_later(0.1, ticking)

        ticking()

        def restore_plain() -> None:
            if tick is not None:
                tick.cancel()
            for sig, before in previous.items():
                signal.signal(sig, before)

        return restore_plain

    def restore() -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)

    return restore


def _fetch_meshes(a: argparse.Namespace) -> int:
    """naoqi-viewer's own `fetch-meshes`, which owns the license prompt, the download and the
    install: the meshes never pass through naoqi-sim (specs/host/viewer.md)."""
    try:
        from naoqi_viewer import cli as viewer_cli
    except ImportError:
        raise MissingExtraError(
            "the meshes are the sim window's: install naoqi-sim with its `viewer` extra "
            "(`naoqi-sim[viewer]`) first"
        ) from None
    argv = ["fetch-meshes"]
    if a.archive:
        argv += ["--archive", str(a.archive)]
    if a.force:
        argv.append("--force")
    if a.remove:
        argv.append("--remove")
    return viewer_cli.main(argv)


async def _run(sim: NaoqiSim) -> int:
    """Start, wait for Ctrl-C or SIGTERM, stop. A signal during the start cancels it."""
    loop = asyncio.get_running_loop()
    label = docker_images.label(sim.config.naoqi.version)
    stop = asyncio.Event()
    starting = asyncio.create_task(sim.start())

    def on_signal() -> None:
        if starting.done():
            stop.set()
        else:
            starting.cancel()

    restore = _route_signals(loop, on_signal)
    try:
        try:
            await starting
        except asyncio.CancelledError:
            print(f"{label}: start cancelled", file=sys.stderr)
            return 130
        status = await sim.status()
        print(
            f"{label}: NAOqi {status.naoqi_version} ready at {sim.url} (Ctrl-C to stop)",
            flush=True,
        )
        if sim.controls_url is not None:
            print(f"{label}: controls at {sim.controls_url}", flush=True)
        await stop.wait()
        await sim.stop()
        return 0
    finally:
        restore()
        await sim.stop()  # a no-op once stopped; covers a failure after the start


def _print_status(status: stack.StackStatus) -> None:
    if not status.containers:
        print("naoqi-sim is not running")
        return
    for c in status.containers:
        print(f"{c.name:<20} {c.state}{f' ({c.health})' if c.health else ''}")
    if status.naoqi is None:
        print(
            "NaoqiSim service: not reachable yet (the NAOqi container is not healthy)"
        )
        return
    n = status.naoqi
    print(
        f"naoqi-sim {n.version} on NAOqi {n.naoqi_version}, ready: {str(n.ready).lower()}"
    )
    print(f"camera source: {n.camera_source}, audio source: {n.audio_source}")


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    a = ap.parse_args(argv)
    if unknown := [
        v for v in getattr(a, "versions", []) if v not in docker_images.IMAGES
    ]:
        ap.error(
            f"unknown version(s) {', '.join(unknown)}; choose from {', '.join(docker_images.IMAGES)}"
        )
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )
    try:
        if a.command == "fetch-and-build-images":
            asyncio.run(
                docker_images.fetch_and_build_images(
                    a.versions, image_data=a.image_data
                )
            )
        elif a.command == "run":
            return asyncio.run(_run(NaoqiSim(_config(ap, a))))
        elif a.command == "config":
            print(json.dumps(_config(ap, a).to_dict(), indent=2))
        elif a.command == "fetch-meshes":
            return _fetch_meshes(a)
        elif a.command == "status":
            status = asyncio.run(stack.read_status())
            _print_status(status)
            return 0 if status.ready else 1
        elif a.command == "cleanup":
            removed = asyncio.run(stack.cleanup())
            print(f"removed {', '.join(removed)}" if removed else "nothing to remove")
        elif a.command == "logs":
            return stack.show_logs(follow=a.follow, tail=a.tail)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except NaoqiSimError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
