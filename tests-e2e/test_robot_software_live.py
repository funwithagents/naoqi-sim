"""Robot software on both versions (container.md, "Robot software in the image" and "Robot packages
in the image"): a package written as for a robot, whose service runs `/usr/bin/python2` and registers
on `127.0.0.1:9559`, starts and serves, and on 2.8 the host reaches it as it reaches NAOqi's own; the
robot's `altactilegesture` and `signs-and-feedback`, installed in the 2.8 image, answer as on a NAO 6.
The service package is ours (tests-e2e/packages/naoqi_sim_test_service)."""

import asyncio
import time

import pytest
from support import wait_until
from test_life_scenario_live import build

SERVICE_PACKAGE = "naoqi_sim_test_service"
SERVICE = "NaoqiSimTestService"

# Run inside NAOqi, as a robot's own software would: the service through 127.0.0.1:9559.
FROM_THE_ROBOT = """
def run():
    import qi
    session = qi.Session()
    session.connect("tcp://127.0.0.1:9559")
    service = session.service("NaoqiSimTestService")
    return [service.where(), service.echo("from the robot")]
"""


def only_on_2_8(nao) -> None:
    if nao.version.name != "2.8":
        pytest.skip(
            "the robot's altactilegesture and signs-and-feedback are NAO 6 packages"
        )


@pytest.fixture
def robot_service(nao, tmp_path):
    """Our service package installed; removed after the test, its service stopped first."""
    pm = nao.service("PackageManager")
    if pm.hasPackage(SERVICE_PACKAGE):  # left by an interrupted run: the volume keeps it
        nao.service("ALServiceManager").stopService(SERVICE)
        pm.removePkg(SERVICE_PACKAGE)
    nao.container.copy_in(
        build(SERVICE_PACKAGE, tmp_path), f"/tmp/{SERVICE_PACKAGE}.pkg"
    )
    assert pm.install(f"/tmp/{SERVICE_PACKAGE}.pkg")
    try:
        wait_until(
            lambda: SERVICE in {s["name"] for s in nao.session.services()},
            30.0,
            f"{SERVICE} registered",
        )
        yield
    finally:
        try:
            nao.service("ALServiceManager").stopService(SERVICE)
        finally:
            pm.removePkg(SERVICE_PACKAGE)


def test_a_robot_packages_service_runs_with_the_robots_python(nao, robot_service):
    managed = {s["name"]: s for s in nao.service("ALServiceManager").services()}
    assert managed[SERVICE]["running"]
    assert managed[SERVICE]["execStart"].startswith("/usr/bin/python2 ")
    assert nao.run_in_naoqi(FROM_THE_ROBOT) == ["/usr/bin/python2", "from the robot"]


def test_2_8_the_host_reaches_a_service_registered_on_the_robots_port(
    nao, robot_service
):
    only_on_2_8(nao)
    # Registered with NAOqi itself (the loopback redirect), so advertised on 9559, the gateway.
    endpoints = next(s for s in nao.session.services() if s["name"] == SERVICE)[
        "endpoints"
    ]
    assert endpoints and all(e.endswith(":9559") for e in endpoints), endpoints
    service = nao.service(SERVICE)
    assert service.where() == "/usr/bin/python2"
    assert service.echo("from the host") == "from the host"


async def double_tap(touch) -> None:
    await touch.tap("Head/Touch/Front", duration_s=0.12)
    await asyncio.sleep(0.09)
    await touch.tap("Head/Touch/Front", duration_s=0.12)


def test_2_8_tactile_gestures_from_the_touch_input(nao):
    only_on_2_8(nao)
    gestures = nao.service("ALTactileGesture")
    memory = nao.service("ALMemory")
    seen: list[str] = []
    events: list[str] = []
    link = gestures.onGesture.connect(seen.append)
    try:
        touch = nao.sim.touch
        for gesture, expected in (
            (lambda: touch.tap("Head/Touch/Front", duration_s=0.12), "SingleFront"),
            (lambda: double_tap(touch), "DoubleFront"),
            (lambda: touch.tap("Head", duration_s=0.12), "SingleTap"),
        ):
            # The service removes its event one second after each gesture, its subscribers with
            # it (touch-input.md): subscribe again for each.
            subscriber = memory.subscriber("ALTactileGesture/Gesture")
            subscriber.signal.connect(events.append)
            nao.runner.run(gesture())
            wait_until(lambda e=expected: e in seen, 5.0, f"{expected} on onGesture")
            wait_until(lambda e=expected: e in events, 5.0, f"{expected} as the event")
            time.sleep(1.5)  # past the event's removal
    finally:
        gestures.onGesture.disconnect(link)
    assert seen == ["SingleFront", "DoubleFront", "SingleTap"]


def test_2_8_signs_and_feedback_reads_a_naos_configuration(nao):
    only_on_2_8(nao)
    feedback = nao.service("ALSignsAndFeedback")
    bits = set(feedback._getBitsNames())
    # The NAO configuration's bits: the listening feedback and the LED reset Life asks for.
    assert {"BeginSpeechRecognition", "EndSpeechRecognition", "AllLedsReset"} <= bits
    feedback.triggerBit("AllLedsReset")  # as Life does after an application


def test_2_8_signs_and_feedback_follows_the_robot_speaking(nao):
    only_on_2_8(nao)
    seen: list[float] = []
    subscriber = nao.service("ALMemory").subscriber("ALSignsAndFeedback/Speaking")
    subscriber.signal.connect(lambda _: seen.append(time.monotonic()))
    nao.service("ALTextToSpeech").say("hello")
    wait_until(lambda: bool(seen), 5.0, "ALSignsAndFeedback/Speaking")
