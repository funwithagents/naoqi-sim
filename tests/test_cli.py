"""The `naoqi-sim` command over the library: what each command prints and its exit code. `run` is
driven with a stand-in `NaoqiSim` and real signals; `status`, `cleanup` and `logs` with the fake
`docker` (tests/fake_docker.py)."""

import asyncio
import json
import signal
import sys
import threading
from pathlib import Path
from typing import ClassVar

import pytest
from ports import free_port

from naoqi_sim import cli, stack
from naoqi_sim.config import (
    AudioInputSettings,
    CameraSettings,
    ControlsSettings,
    NaoqiSettings,
    NaoqiSimConfig,
    RobotSettings,
    VideoInputSettings,
    ViewerSettings,
)
from naoqi_sim.errors import ImagesMissingError
from naoqi_sim.stack import NaoqiSimStatus

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "configs"
STATUS = NaoqiSimStatus("0.0.1", "2.8.7.4", True, "none", "none")


class StandIn:
    """Stands in for `NaoqiSim`: records its lifecycle, starts in `start_s`."""

    made: ClassVar[list["StandIn"]] = []
    start_s = 0.0
    start_error: Exception | None = None

    def __init__(self, config: NaoqiSimConfig):
        self.config = config
        self.events: list[str] = []
        StandIn.made.append(self)

    async def start(self):
        self.events.append("start")
        try:
            await asyncio.sleep(StandIn.start_s)
        except asyncio.CancelledError:
            self.events.append("start cancelled")
            raise
        if StandIn.start_error:
            raise StandIn.start_error
        self.events.append("ready")

    async def stop(self):
        if "stop" not in self.events:
            self.events.append("stop")

    async def status(self):
        return STATUS

    @property
    def url(self):
        return "tcp://127.0.0.1:9559"

    @property
    def controls_url(self):
        controls = self.config.controls
        return f"http://127.0.0.1:{controls.port}/" if controls.enabled else None


@pytest.fixture
def stand_in(monkeypatch):
    StandIn.made, StandIn.start_s, StandIn.start_error = [], 0.0, None
    monkeypatch.setattr(cli, "NaoqiSim", StandIn)
    return StandIn


def send_sigint_after(seconds: float) -> None:
    # Ctrl-C, raised in this process (os.kill on Windows terminates instead of signalling).
    threading.Timer(seconds, signal.raise_signal, (signal.SIGINT,)).start()


@pytest.fixture(params=["loop signals", "no loop signals"])
def signals(request, monkeypatch):
    """`run` both ways it hears Ctrl-C: through the event loop (Linux, macOS) and, where the loop
    has no signal handlers (Windows' loops), through a plain handler."""
    if request.param == "no loop signals":
        loop = asyncio.new_event_loop()
        loop.close()

        def unsupported(*args, **kwargs):
            raise NotImplementedError

        monkeypatch.setattr(type(loop), "add_signal_handler", unsupported)
    return request.param


def test_run_starts_until_ctrl_c_then_stops(signals, stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(
        json.dumps({"naoqi": {"version": "2.8"}, "viewer": {"headless": True}})
    )
    send_sigint_after(0.3)

    assert cli.main(["run", "--config", str(path)]) == 0

    [naoqisim] = stand_in.made
    assert naoqisim.config.naoqi.version == "2.8" and naoqisim.config.viewer.headless
    assert naoqisim.events == ["start", "ready", "stop"]
    assert (
        "NAOqi 2.8 (sim): NAOqi 2.8.7.4 ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)"
        in capsys.readouterr().out
    )


def test_run_says_where_the_controls_are(signals, stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(
        json.dumps({"naoqi": {"version": "2.1"}, "controls": {"enabled": True}})
    )
    send_sigint_after(0.3)
    assert cli.main(["run", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "NAOqi 2.1 (sim): controls at http://127.0.0.1:9564/" in out


def on(version: str, **blocks) -> NaoqiSimConfig:
    return NaoqiSimConfig(naoqi=NaoqiSettings(version=version), **blocks)  # type: ignore[arg-type]


WINDOW = ViewerSettings(headless=False, cameras_display=True, people_display=True)
RENDER, WEBCAM = CameraSettings(source="render"), CameraSettings(source="webcam")
# What each set of robot options runs: the NAOqi version's robot with nothing turned on, then
# each option's part, the viewer rendering every camera the webcam does not feed.
OPTIONS = [
    (["--naoqi", "2.1"], on("2.1")),
    (["--naoqi", "2.8"], on("2.8")),
    (
        ["--naoqi", "2.1", "--robot", "nao", "--robot-version", "v4"],
        on("2.1", robot=RobotSettings(type="nao", version="v4")),
    ),
    (
        ["--naoqi", "2.8", "--viewer"],
        on("2.8", viewer=WINDOW, video_input=VideoInputSettings(RENDER, RENDER)),
    ),
    (
        ["--naoqi", "2.8", "--webcam"],
        on("2.8", video_input=VideoInputSettings(top=WEBCAM)),
    ),
    (
        ["--naoqi", "2.8", "--viewer", "--webcam"],
        on("2.8", viewer=WINDOW, video_input=VideoInputSettings(WEBCAM, RENDER)),
    ),
    (["--naoqi", "2.1", "--mic"], on("2.1", audio_input=AudioInputSettings("mic"))),
    (
        ["--naoqi", "2.1", "--controls"],
        on("2.1", controls=ControlsSettings(enabled=True, open=True)),
    ),
]


@pytest.mark.parametrize(("options", "config"), OPTIONS)
def test_run_runs_the_robot_its_options_describe(stand_in, options, config):
    send_sigint_after(0.3)
    assert cli.main(["run", *options]) == 0
    assert stand_in.made[0].config == config


def test_the_default_robot_needs_no_extra(stand_in):
    # no window and no camera rendered or captured: neither the viewer nor OpenCV
    send_sigint_after(0.3)
    assert cli.main(["run", "--naoqi", "2.8"]) == 0
    config = stand_in.made[0].config
    assert config.viewer.headless
    assert config.video_input.sources == {"top": "none", "bottom": "none"}
    assert (config.robot.type, config.robot.version) == ("nao", "v6")
    assert config.audio_input.source == "none" and not config.controls.enabled


@pytest.mark.parametrize("command", ["run", "config"])
def test_the_naoqi_version_must_be_named(stand_in, command, capsys):
    with pytest.raises(SystemExit) as exit:
        cli.main([command])
    assert exit.value.code == 2
    assert "--naoqi 2.1 or --naoqi 2.8" in capsys.readouterr().err
    assert stand_in.made == []


@pytest.mark.parametrize(
    ("options", "key"),
    [
        (["--naoqi", "2.5"], "naoqi.version"),
        (["--naoqi", "2.8", "--robot-version", "v5"], "robot.version"),
        (["--naoqi", "2.1", "--robot", "pepper"], "robot.type"),
    ],
)
def test_a_robot_that_does_not_exist_exits_2_naming_the_key(
    stand_in, options, key, capsys
):
    assert cli.main(["run", *options]) == 2
    assert key in capsys.readouterr().err
    assert stand_in.made == []


@pytest.mark.parametrize("command", ["run", "config"])
def test_a_file_and_robot_options_together_are_refused(
    stand_in, command, tmp_path, capsys
):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"naoqi": {"version": "2.8"}}))
    with pytest.raises(SystemExit) as exit:
        cli.main([command, "--config", str(path), "--naoqi", "2.1", "--viewer"])
    assert exit.value.code == 2
    assert "drop --naoqi, --viewer" in capsys.readouterr().err
    assert stand_in.made == []


@pytest.mark.parametrize(("options", "config"), OPTIONS)
def test_config_prints_what_run_would_run(stand_in, options, config, tmp_path, capsys):
    assert cli.main(["config", *options]) == 0
    printed = capsys.readouterr().out
    assert stand_in.made == []  # starts nothing
    # every field of every block, so the file shows all there is to change
    assert json.loads(printed) == config.to_dict()
    # and saved, it runs the same robot
    path = tmp_path / "mine.json"
    path.write_text(printed)
    send_sigint_after(0.3)
    assert cli.main(["run", "--config", str(path)]) == 0
    assert stand_in.made[0].config == config


@pytest.mark.parametrize("version", ["2.1", "2.8"])
def test_the_example_files_are_what_everything_turned_on_prints(version, capsys):
    # examples/configs/<version>.json: the window, the webcam, the microphone and the controls,
    # every field written out, to read and to copy.
    everything = ["--viewer", "--webcam", "--mic", "--controls"]
    assert cli.main(["config", "--naoqi", version, *everything]) == 0
    assert capsys.readouterr().out == (EXAMPLES / f"{version}.json").read_text()
    assert sorted(p.name for p in EXAMPLES.iterdir()) == [
        "2.1.json",
        "2.8.json",
        "ci.json",
    ]


def test_config_prints_a_file_with_its_defaults_filled_in(tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"naoqi": {"version": "2.1"}}))
    assert cli.main(["config", "--config", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == on("2.1").to_dict()
    path.write_text(
        json.dumps({"naoqi": {"version": "2.1"}, "robot": {"version": "v6"}})
    )
    assert cli.main(["config", "--config", str(path)]) == 2
    assert "robot.version" in capsys.readouterr().err


def test_ctrl_c_during_the_start_cancels_it(signals, stand_in):
    stand_in.start_s = 10
    send_sigint_after(0.2)

    assert cli.main(["run", "--naoqi", "2.1"]) == 130
    assert stand_in.made[0].events == ["start", "start cancelled", "stop"]


@pytest.mark.skipif(sys.platform != "win32", reason="Ctrl-Break is Windows' signal")
def test_ctrl_break_stops_the_robot_on_windows(stand_in):
    # The console signal another process can send on Windows (CTRL_BREAK_EVENT).
    if sys.platform == "win32":
        threading.Timer(0.3, signal.raise_signal, (signal.SIGBREAK,)).start()

    assert cli.main(["run", "--naoqi", "2.1"]) == 0
    assert stand_in.made[0].events == ["start", "ready", "stop"]


def test_a_config_error_exits_2_naming_the_key(stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(
        json.dumps({"naoqi": {"version": "2.1"}, "viewer": {"variant": "shiny"}})
    )

    assert cli.main(["run", "--config", str(path)]) == 2
    assert "viewer.variant" in capsys.readouterr().err
    assert stand_in.made == []


def test_a_failed_start_exits_1_with_its_message(stand_in, capsys):
    stand_in.start_error = ImagesMissingError(
        "run `naoqi-sim fetch-and-build-images --naoqi 2.1`"
    )

    assert cli.main(["run", "--naoqi", "2.1"]) == 1
    assert "fetch-and-build-images --naoqi 2.1" in capsys.readouterr().err


def test_status_exits_0_only_when_ready(docker, monkeypatch, capsys):
    monkeypatch.setattr(stack, "read_naoqisim_status", lambda url=stack.URL: STATUS)
    assert cli.main(["status"]) == 1
    assert capsys.readouterr().out == "naoqi-sim is not running\n"

    docker.set(containers={"naoqi-sim-naoqi28": "starting", "naoqi-sim-tts": "running"})
    assert cli.main(["status"]) == 1
    assert "not reachable yet" in capsys.readouterr().out

    docker.set(containers={"naoqi-sim-naoqi28": "healthy", "naoqi-sim-tts": "running"})
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "naoqi-sim-naoqi28" in out and "(healthy)" in out
    assert "naoqi-sim 0.0.1 on NAOqi 2.8.7.4, ready: true" in out


def test_cleanup_prints_what_it_removed(docker, monkeypatch, capsys):
    monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", free_port())
    docker.set(containers={"naoqi-sim-naoqi21": "exited", "naoqi-sim-tts": "running"})

    assert cli.main(["cleanup"]) == 0
    assert capsys.readouterr().out == "removed naoqi-sim-naoqi21, naoqi-sim-tts\n"
    assert cli.main(["cleanup"]) == 0
    assert capsys.readouterr().out == "nothing to remove\n"


def test_logs_passes_its_options_to_compose(docker, capfd):
    assert cli.main(["logs", "--follow", "--tail", "20"]) == 0
    assert "fake log line" in capfd.readouterr().out
    assert docker.calls[-1] == "compose -p naoqi-sim logs --follow --tail 20"


def test_without_docker_every_command_exits_1(docker, capsys):
    docker.set(down=True)
    for command in (["status"], ["cleanup"], ["logs"]):
        assert cli.main(command) == 1
        assert "Docker is not available" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("options", "passed"),
    [
        ([], ["fetch-meshes"]),
        (["--force"], ["fetch-meshes", "--force"]),
        (["--remove"], ["fetch-meshes", "--remove"]),
        (["--archive", "meshes.bin"], ["fetch-meshes", "--archive", "meshes.bin"]),
    ],
)
def test_fetch_meshes_is_naoqi_viewers_own_command(monkeypatch, options, passed):
    from naoqi_viewer import cli as viewer_cli

    calls = []
    monkeypatch.setattr(viewer_cli, "main", lambda argv: calls.append(argv) or 3)

    # its license prompt, its download, its exit code: naoqi-sim only hands over
    assert cli.main(["fetch-meshes", *options]) == 3
    assert calls == [passed]


def test_fetch_meshes_without_the_viewer_extra_names_it(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "naoqi_viewer", None)  # as if not installed

    assert cli.main(["fetch-meshes"]) == 1
    assert "naoqi-sim[viewer]" in capsys.readouterr().err
