"""Running a simulated NAO, on each NAOqi version, as a user and a caller do: the `NaoqiSim`
object's status, what another terminal reads (`read_status`) and refuses (`cleanup` while it
runs), `naoqi-sim run` end to end, and the sim window."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest
from conftest import live_config

from naoqi_sim import MemorySink, NaoqiSim, cleanup, read_status
from naoqi_sim.config import ViewerSettings
from naoqi_sim.docker_images import naoqi_sim_version
from naoqi_sim.errors import NaoqiSimError

NAOQI_SIM = [sys.executable, "-m", "naoqi_sim.cli"]


def test_status_reads_the_naoqisim_service(nao):
    status = nao.runner.run(nao.sim.status())

    assert status.version == naoqi_sim_version()
    assert status.naoqi_version == nao.version.naoqi_version
    assert status.ready
    assert (status.camera_source, status.audio_source) == ("render", "fake")


def test_another_terminal_sees_the_running_robot(nao):
    status = nao.runner.run(read_status())

    states = {c.service: (c.state, c.health) for c in status.containers}
    assert states[nao.version.service] == ("running", "healthy")
    assert states["tts"][0] == "running"
    assert status.ready and status.naoqi is not None
    assert status.naoqi.naoqi_version == nao.version.naoqi_version


def test_cleanup_refuses_while_the_robot_runs(nao):
    with pytest.raises(NaoqiSimError, match="Ctrl-C"):
        nao.runner.run(cleanup())
    assert nao.service("NaoqiSim").isReady()


def test_naoqi_sim_run_end_to_end(nao, tmp_path):
    config = tmp_path / "sim.json"
    config.write_text(json.dumps(live_config(nao.version.name).to_dict()))
    nao.stop()
    # Windows has no SIGINT to send another process: Ctrl-Break, to a process group of its own.
    if sys.platform == "win32":
        flags, stop = subprocess.CREATE_NEW_PROCESS_GROUP, signal.CTRL_BREAK_EVENT
    else:
        flags, stop = 0, signal.SIGINT
    run = subprocess.Popen(
        [*NAOQI_SIM, "run", "--config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=flags,
    )
    try:
        assert run.stdout is not None
        lines = []
        for line in run.stdout:
            lines.append(line)
            if "ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)" in line:
                break
        else:
            pytest.fail(
                f"naoqi-sim run exited ({run.wait()}) without being ready:\n{''.join(lines)}"
            )
        label = f"NAOqi {nao.version.name} (sim)"
        assert lines[-1] == (
            f"{label}: NAOqi {nao.version.naoqi_version} ready at "
            "tcp://127.0.0.1:9559 (Ctrl-C to stop)\n"
        )
        # The start's progress came first, NAOqi's start among it.
        assert lines.index(f"{label}: starting\n") < lines.index(
            f"{label}: NAOqi started\n"
        )

        status = subprocess.run(
            [*NAOQI_SIM, "status"], capture_output=True, text=True, check=False
        )
        assert status.returncode == 0, status.stdout + status.stderr
        assert "ready: true" in status.stdout

        run.send_signal(stop)
        assert run.wait(timeout=120) == 0
        assert f"{label}: NAOqi stopped" in run.stdout.read().splitlines()
        stopped = subprocess.run(
            [*NAOQI_SIM, "status"], capture_output=True, text=True, check=False
        )
        assert stopped.returncode == 1
        assert stopped.stdout == "naoqi-sim is not running\n"
    finally:
        if run.poll() is None:
            run.kill()
            run.wait()
            subprocess.run([*NAOQI_SIM, "cleanup"], capture_output=True, check=False)


def _display() -> bool:
    if sys.platform == "darwin":
        return not os.environ.get("CI")
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_the_sim_window(nao):
    pytest.importorskip("naoqi_viewer", reason="the viewer extra is not installed")
    if not _display():
        pytest.skip("no display for the sim window")
    if nao.version.name != "2.1":
        pytest.skip("the window does not depend on the NAOqi version: checked on 2.1")
    window = NaoqiSim(
        live_config(nao.version.name, viewer=ViewerSettings(variant="placeholder")),
        sink=MemorySink(),
    )
    nao.stop()
    try:
        nao.runner.run(window.start())  # returns once the window can render
        time.sleep(2)  # the robot in its window, for whoever watches
        assert nao.runner.run(window.status()).ready
    finally:
        nao.runner.run(window.stop())
