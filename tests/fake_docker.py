"""A fake `docker` first on PATH (a `docker.cmd` on Windows), for the tests of what naoqi-sim asks Docker.

The fake keeps its state in a JSON file: the images (ID and labels, set by `compose build` from
the environment's `NAOQI_SIM_VERSION` and `NAOQI_SIM_RECIPES`, the same ID for the same inputs, as
Docker's cache), the containers and how the NAOqi one boots (`boot`: healthy, starting,
unhealthy, exited) with the log it prints as it boots (`boot_log`: one more line each time
`docker logs` reads it, the container `starting` until all are out), how the engines'
containers turn out (`tts_health`, `perception_health`: healthy, unhealthy, exited), and whether Docker is up or a build fails.
Every invocation is logged, and `up` records the `NAOQI_SIM_LANGUAGES` and
`NAOQI_SIM_PERCEPTION_URL` it was given. A NAOqi build
reads its `image-data` context as compose does, from `$NAOQI_SIM_IMAGE_DATA/<version>`: it records the
folder, and fails as BuildKit does when the folder is not there.
"""

import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest
from ports import free_port

from naoqi_sim import docker_images
from naoqi_sim.docker_images import IMAGES, PERCEPTION_IMAGE, TTS_IMAGE

FAKE_DOCKER = textwrap.dedent(
    """\
    import hashlib, json, os, sys, time
    path = os.environ["FAKE_DOCKER_STATE"]
    state = json.load(open(path))
    args = sys.argv[1:]
    state["calls"].append(" ".join(args))
    def done(code=0):
        json.dump(state, open(path, "w"))
        sys.exit(code)
    if state.get("down"):
        done(1)
    if args[0] == "info":
        done()
    if args[:2] == ["image", "inspect"]:
        image = state["images"].get(args[2])
        if image is None:
            done(1)
        print(json.dumps([{"Id": image["Id"], "Config": {"Labels": image["Labels"]}}]))
        done()
    if args[0] == "compose":
        verb = next(a for a in args if a in ("build", "up", "down", "ps", "logs"))
        services = args[args.index(verb) + 1:]
        services = [s for s in services if not s.startswith("-")]
        if verb == "build":
            if state.get("build_fails"):
                print("failed to solve: boom", file=sys.stderr)
                done(1)
            labels = {
                "io.naoqi-sim.version": os.environ.get("NAOQI_SIM_VERSION", "dev"),
                "io.naoqi-sim.recipes": os.environ.get("NAOQI_SIM_RECIPES", ""),
            }
            for s in services:
                version = state["services"][s].get("version")
                if version is not None:
                    context = os.path.join(os.environ.get("NAOQI_SIM_IMAGE_DATA", "./image-data"), version)
                    if not os.path.isdir(context):
                        print(f"failed to solve: {context}: no such directory", file=sys.stderr)
                        done(1)
                    state.setdefault("image_data_contexts", {})[s] = context
                tag = state["services"][s]["image"]
                inputs = tag + json.dumps(labels, sort_keys=True) + state.get("source", "")
                state["images"][tag] = {
                    "Id": "sha256:" + hashlib.sha256(inputs.encode()).hexdigest(),
                    "Labels": labels,
                }
        elif verb == "up":
            if state.get("up_s"):
                # A real `up` takes seconds: it is seen starting, and its containers appear at
                # its end, whatever ran meanwhile.
                with open(path, "w") as f:
                    json.dump(state, f)
                time.sleep(state["up_s"])
                state = json.load(open(path))
            state["up_languages"] = os.environ.get("NAOQI_SIM_LANGUAGES")
            state["up_perception_url"] = os.environ.get("NAOQI_SIM_PERCEPTION_URL")
            for s in services:
                name = state["services"][s]["container"]
                if s in ("tts", "perception"):
                    state["containers"][name] = state.get(s + "_health", "healthy")
                else:
                    state["containers"][name] = state["boot"]
        elif verb == "logs":
            print("naoqi-sim-naoqi21  | [entrypoint] fake log line")
        elif verb == "ps":
            looks = {"healthy": ("running", "healthy"), "starting": ("running", "starting"),
                     "unhealthy": ("running", "unhealthy"), "exited": ("exited", ""),
                     "running": ("running", "")}
            for s, info in state["services"].items():
                status = state["containers"].get(info["container"])
                if status is not None:
                    st, health = looks[status]
                    print(json.dumps({"Name": info["container"], "Service": s,
                                      "State": st, "Health": health}))
        else:
            state["containers"] = {}
        done()
    if args[0] == "inspect":
        status = state["containers"].get(args[-1])
        if status is None:
            done(1)
        if state.get("log_shown", 0) < len(state.get("boot_log", [])):
            status = "starting"  # booting until its whole log is out
        print({"healthy": "running healthy", "starting": "running starting",
               "unhealthy": "running unhealthy", "exited": "exited ",
               "running": "running "}[status])
        done()
    if args[0] == "logs":
        if "boot_log" in state:
            # One more line each time it is read: the entrypoint's on stdout, NAOqi's on stderr.
            state["log_shown"] = min(state.get("log_shown", 0) + 1, len(state["boot_log"]))
            for line in state["boot_log"][:state["log_shown"]]:
                print(line, file=sys.stdout if line.startswith("[entrypoint]") else sys.stderr)
        else:
            print("[entrypoint] fake log line")
        done()
    done(2)
    """
)


class FakeDocker:
    def __init__(self, path: Path):
        self.path = path
        services = {
            i.service: {
                "image": i.image,
                "container": i.container,
                "version": i.version,
            }
            for i in IMAGES.values()
        }
        services["tts"] = {"image": TTS_IMAGE, "container": docker_images.TTS_CONTAINER}
        services["perception"] = {
            "image": PERCEPTION_IMAGE,
            "container": docker_images.PERCEPTION_CONTAINER,
        }
        self.write(
            {
                "calls": [],
                "images": {},
                "containers": {},
                "boot": "healthy",
                "services": services,
            }
        )

    def read(self) -> dict:
        # A slow `up` rewrites the file while the test polls it: retry a half-written read.
        for _ in range(50):
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                time.sleep(0.01)
        return json.loads(self.path.read_text())

    def write(self, state: dict) -> None:
        self.path.write_text(json.dumps(state))

    def set(self, **values) -> None:
        self.write({**self.read(), **values})

    @property
    def calls(self) -> list[str]:
        return self.read()["calls"]


@pytest.fixture
def docker(tmp_path, monkeypatch) -> FakeDocker:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        # Windows runs no shebang: a .cmd that naoqi-sim finds through PATHEXT runs the fake.
        (bin_dir / "fake_docker.py").write_text(FAKE_DOCKER, encoding="utf-8")
        (bin_dir / "docker.cmd").write_text(
            f'@"{sys.executable}" "%~dp0fake_docker.py" %*\r\n', encoding="utf-8"
        )
    else:
        script = bin_dir / "docker"
        script.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "docker.json"))
    monkeypatch.setattr(docker_images, "POLL", 0.01)
    # Verification needs the NAOqi port free; use one nothing listens on.
    monkeypatch.setattr(docker_images, "NAOQI_PORT", free_port())
    return FakeDocker(tmp_path / "docker.json")
