"""The NaoqiSim status service on a running naoqi-sim stack, on each NAOqi version: how a client
learns the target is naoqi-sim, its versions and device sources, and the Docker healthcheck."""


def test_the_target_identifies_as_naoqi_sim(nao):
    naoqisim = nao.service("NaoqiSim")
    memory = nao.service("ALMemory")
    built_with = nao.container.image_env()["NAOQI_SIM_VERSION"]

    assert "NaoqiSim" in {s["name"] for s in nao.session.services()}
    assert naoqisim.getVersion() == built_with
    assert naoqisim.getNaoqiVersion() == nao.version.naoqi_version
    assert memory.getData("NaoqiSim/Version") == built_with
    assert memory.getData("NaoqiSim/NaoqiVersion") == nao.version.naoqi_version
    assert (
        memory.getData("NaoqiSim/Camera/Source") == "render"
    )  # the live tier's render camera
    assert (
        memory.getData("NaoqiSim/Audio/Source") == "fake"
    )  # the live tier's fake source
    assert memory.getData("NaoqiSim/Audio/Channels") == "duplicate"
    # The face detection and people perception modules say whether an engine is behind them
    # (specs/container/status-service.md); the live tier runs it.
    assert memory.getData("NaoqiSim/Perception/Source") == "engine"


def test_ready_means_the_replacements_answer(nao):
    assert nao.service("NaoqiSim").isReady() is True
    assert nao.service("ALMemory").getData("NaoqiSim/Ready") == 1
    assert nao.version.implementation in nao.service("ALTextToSpeech").whoami()


def test_the_container_turns_healthy(nao):
    assert nao.container.wait_healthy(timeout=30) == "healthy"
