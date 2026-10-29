"""What other terminals read and do without a `NaoqiSim` object, against the fake `docker`
(tests/fake_docker.py): `read_status` and `cleanup`. The qi read of the `NaoqiSim` service is
replaced; the live tier covers it."""

import asyncio
import socket
import threading
import time

import pytest
from ports import free_port

from naoqi_sim import stack
from naoqi_sim.config import NaoqiSettings, NaoqiSimConfig, PerceptionSettings
from naoqi_sim.errors import DockerUnavailableError, NaoqiSimError
from naoqi_sim.stack import ContainerState, NaoqiSimStatus

STATUS = NaoqiSimStatus("0.0.1", "2.1.4.13", True, "none", "none", "engine")


@pytest.fixture
def qi_reads(monkeypatch) -> list[str]:
    reads: list[str] = []

    def read(url=stack.URL):
        reads.append(url)
        return STATUS

    monkeypatch.setattr(stack, "read_naoqisim_status", read)
    return reads


def test_nothing_running(docker, qi_reads):
    status = asyncio.run(stack.read_status())

    assert status.containers == [] and status.naoqi is None and not status.ready
    assert qi_reads == []


def test_a_ready_robot(docker, qi_reads):
    docker.set(
        containers={
            "naoqi-sim-naoqi28": "healthy",
            "naoqi-sim-tts": "running",
            "naoqi-sim-perception": "healthy",
        }
    )

    status = asyncio.run(stack.read_status())

    assert status.containers == [
        ContainerState("naoqi-sim-naoqi28", "naoqi28", "running", "healthy"),
        ContainerState("naoqi-sim-perception", "perception", "running", "healthy"),
        ContainerState("naoqi-sim-tts", "tts", "running", ""),
    ]
    assert status.naoqi == STATUS and status.ready
    assert STATUS.perception_source == "engine"  # what `naoqi-sim status` prints
    assert qi_reads == ["tcp://127.0.0.1:9559"]


@pytest.mark.parametrize("boot", ["starting", "unhealthy", "exited"])
def test_the_service_is_read_only_once_naoqi_is_healthy(docker, qi_reads, boot):
    docker.set(containers={"naoqi-sim-naoqi21": boot, "naoqi-sim-tts": "running"})

    status = asyncio.run(stack.read_status())

    assert len(status.containers) == 2
    assert status.naoqi is None and not status.ready
    assert qi_reads == []


def test_cleanup_removes_what_a_dead_run_left(docker, monkeypatch):
    monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", free_port())
    docker.set(
        containers={
            "naoqi-sim-naoqi21": "healthy",
            "naoqi-sim-tts": "running",
            "naoqi-sim-perception": "running",
        }
    )

    removed = asyncio.run(stack.cleanup())

    assert removed == ["naoqi-sim-naoqi21", "naoqi-sim-perception", "naoqi-sim-tts"]
    assert docker.read()["containers"] == {}
    assert any("--profile * down" in c for c in docker.calls)
    assert asyncio.run(stack.cleanup()) == []


def test_cleanup_refuses_while_a_run_is_alive(docker, monkeypatch):
    docker.set(containers={"naoqi-sim-naoqi21": "healthy", "naoqi-sim-tts": "running"})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", s.getsockname()[1])
        with pytest.raises(NaoqiSimError, match="Ctrl-C"):
            asyncio.run(stack.cleanup())
    assert len(docker.read()["containers"]) == 2
    assert not any("down" in c for c in docker.calls)


def test_both_need_docker(docker):
    docker.set(down=True)
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.read_status())
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.cleanup())


def test_the_services_and_environment_follow_the_perception_switch():
    on = NaoqiSimConfig(naoqi=NaoqiSettings(version="2.8"))
    off = NaoqiSimConfig(perception=PerceptionSettings(enabled=False))
    assert stack.services(on) == ["tts", "perception", "naoqi28"]
    assert stack.services(off) == ["tts", "naoqi21"]
    assert stack.compose_env(on)["NAOQI_SIM_PERCEPTION_URL"] == "http://perception:8080"
    assert stack.compose_env(off)["NAOQI_SIM_PERCEPTION_URL"] == ""


def test_a_status_without_the_perception_key_reads_none(monkeypatch):
    # An image built before the perception modules has no NaoqiSim/Perception/Source key.
    class Memory:
        def getData(self, key):
            if key.startswith("NaoqiSim/Perception"):
                raise RuntimeError("ALMemory::getData\n\tData not found " + key)
            return "render" if "Camera" in key else "fake"

    class NaoqiSim:
        def getVersion(self):
            return "0.0.1"

        def getNaoqiVersion(self):
            return "2.1.4.13"

        def isReady(self):
            return True

    class Session:
        def service(self, name):
            return Memory() if name == "ALMemory" else NaoqiSim()

        def close(self):
            pass

    monkeypatch.setattr(stack, "connect", lambda url=stack.URL: Session())
    assert stack.read_naoqisim_status() == NaoqiSimStatus(
        "0.0.1", "2.1.4.13", True, "render", "fake", "none"
    )


def test_a_failed_connect_is_not_retried():
    # A server that hangs up at once, as NAOqi 2.1 seemed to for libqi 3.1.6 (an instant
    # `disconnected`): one attempt, then NaoqiSimError naming the URL.
    accepted: list[socket.socket] = []
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(0.1)

        def hang_up() -> None:
            while server.fileno() != -1:
                try:
                    peer, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:  # the server closed
                    return
                accepted.append(peer)
                peer.close()

        threading.Thread(target=hang_up, daemon=True).start()
        url = f"tcp://127.0.0.1:{server.getsockname()[1]}"
        with pytest.raises(NaoqiSimError, match=url):
            stack.connect(url)
        time.sleep(1.0)  # room for a retry (the old one came after 0.5 s)
    assert len(accepted) == 1
