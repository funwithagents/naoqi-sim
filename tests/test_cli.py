"""The `naoqi-sim` command over the library: what each command prints and its exit code. `run` is
driven with a stand-in `NaoqiSim` and real signals; `status`, `cleanup` and `logs` with the fake
`docker` (tests/fake_docker.py)."""

import asyncio
import json
import signal
import sys
import threading
from typing import ClassVar

import pytest
from ports import free_port

from naoqi_sim import cli, stack
from naoqi_sim.config import NaoqiSimConfig
from naoqi_sim.errors import ImagesMissingError
from naoqi_sim.stack import NaoqiSimStatus

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


def test_run_without_a_file_uses_the_defaults(signals, stand_in):
    send_sigint_after(0.3)
    assert cli.main(["run"]) == 0
    assert stand_in.made[0].config == NaoqiSimConfig()


def test_ctrl_c_during_the_start_cancels_it(signals, stand_in):
    stand_in.start_s = 10
    send_sigint_after(0.2)

    assert cli.main(["run"]) == 130
    assert stand_in.made[0].events == ["start", "start cancelled", "stop"]


@pytest.mark.skipif(sys.platform != "win32", reason="Ctrl-Break is Windows' signal")
def test_ctrl_break_stops_the_robot_on_windows(stand_in):
    # The console signal another process can send on Windows (CTRL_BREAK_EVENT).
    if sys.platform == "win32":
        threading.Timer(0.3, signal.raise_signal, (signal.SIGBREAK,)).start()

    assert cli.main(["run"]) == 0
    assert stand_in.made[0].events == ["start", "ready", "stop"]


def test_a_config_error_exits_2_naming_the_key(stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"viewer": {"variant": "shiny"}}))

    assert cli.main(["run", "--config", str(path)]) == 2
    assert "viewer.variant" in capsys.readouterr().err
    assert stand_in.made == []


def test_a_failed_start_exits_1_with_its_message(stand_in, capsys):
    stand_in.start_error = ImagesMissingError(
        "run `naoqi-sim fetch-and-build-images 2.1`"
    )

    assert cli.main(["run"]) == 1
    assert "fetch-and-build-images 2.1" in capsys.readouterr().err


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
