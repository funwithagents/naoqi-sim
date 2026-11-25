"""The whole of Life and its main dialog on both versions, as on a robot (autonomous-life.md,
"Tests"): a person walks up to the robot, Life goes to them and starts the main dialog, the person
speaks and the robot answers, the person leaves and Life goes back to watching.

With our own packages only (tests-e2e/packages/, written for these tests: no Aldebaran package can
be committed): a dialog package, and on 2.1 an interactive activity with a NAO launcher's
condition, which a NAO 2.1 user installs. 2.8 needs none: Life starts the dialog itself."""

import stat
import time
import zipfile
from pathlib import Path

import pytest
from support import recorded_sentences, say_to_the_robot, wait_until

PACKAGES = Path(__file__).parent / "packages"
DIALOG = "naoqi_sim_test_dialog"
LAUNCHER = "naoqi_sim_test_launcher"  # 2.1 only


def build(name: str, dest: Path) -> Path:
    """The package folder zipped as a .pkg, each entry with the regular-file mode bits (2.8's
    PackageManager cannot read an entry without them)."""
    pkg = dest / f"{name}.pkg"
    with zipfile.ZipFile(pkg, "w") as z:
        for path in sorted((PACKAGES / name).rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(
                    str(path.relative_to(PACKAGES / name)), (2026, 11, 25, 0, 0, 0)
                )
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    return pkg


@pytest.fixture
def installed(nao, tmp_path):
    names = [DIALOG] + ([LAUNCHER] if nao.version.name == "2.1" else [])
    pm = nao.service("PackageManager")
    for name in names:
        nao.container.copy_in(build(name, tmp_path), f"/tmp/{name}.pkg")
        assert pm.install(f"/tmp/{name}.pkg"), name
    try:
        yield
    finally:
        for name in names:
            pm.removePkg(name)


def test_a_person_walks_up_talks_and_leaves(nao, installed):
    memory = nao.service("ALMemory")
    life = nao.service("ALAutonomousLife")
    posture = nao.service("ALRobotPosture")
    sentences = recorded_sentences()
    life.setState("solitary")
    try:
        assert posture.getPostureFamily() == "Standing"
        camera_z = nao.service("ALMotion").getPosition("CameraTop", 2, True)[2]
        # a person at 2 m: seen and tracked, not close enough
        face = nao.sim.props.spawn("face", (2.0, 0.0, camera_z), frame="robot")
        wait_until(
            lambda: memory.getData("Launchpad/ZoneOfTrackedHuman") == 2,
            15.0,
            "the person tracked in zone 2",
        )
        time.sleep(1.0)
        assert life.getState() == "solitary"
        # at 1 m: Life goes to them and the main dialog starts, with our topic in it
        nao.sim.props.place(
            face.name, (1.0, 0.0, camera_z), duration=1.0, frame="robot"
        )
        wait_until(lambda: life.getState() == "interactive", 15.0, "Life interactive")
        wait_until(
            lambda: memory.getData("Dialog/IsStarted") in (1, "1", True),
            20.0,
            "the main dialog started",
        )
        dialog = nao.service("ALDialog")
        wait_until(
            lambda: "naoqi_sim_test" in dialog.getActivatedTopics(),
            20.0,
            "our topic activated in the main dialog",
        )
        time.sleep(2.0)  # the recognition listening for the dialog's phrases
        say_to_the_robot(nao, sentences, "hello robot")
        wait_until(
            lambda: memory.getData("Dialog/Answered") == "hello human",
            15.0,
            "the robot's answer",
        )
        assert memory.getData("Dialog/LastInput") == "hello robot"
        # the person leaves: Life goes back to watching
        nao.sim.props.despawn(face.name)
        wait_until(lambda: life.getState() == "solitary", 45.0, "Life solitary again")
    finally:
        nao.sim.props.clear()
        life.setState("disabled")
    assert posture.getPosture() == "Crouch"
