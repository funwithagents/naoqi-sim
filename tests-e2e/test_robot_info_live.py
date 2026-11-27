"""What the Robot Information and Sensing boxes read (Battery, Has Hardware, Get Body ID, Get
Temperature, Motor Heat, Sonar, the touch and fall events, Select Camera), from a host client
(plans/202610132100_api-coverage-from-boxes.md). The touch keys are only checked as present:
raising their events is the touch input's (specs/host/touch-input.md, Draft)."""

import time

import pytest
from support import DESKTOP_FACTS, known_issue

TOUCH_EVENTS = [
    "FrontTactilTouched",
    "MiddleTactilTouched",
    "RearTactilTouched",
    "HandLeftBackTouched",
    "HandRightBackTouched",
    "LeftBumperPressed",
    "RightBumperPressed",
    "footContactChanged",
    "robotHasFallen",
]


def test_battery_charge(nao):
    assert 0 <= nao.service("ALBattery").getBatteryCharge() <= 100


def test_the_robot_model_is_a_nao_with_its_limbs(nao):
    """2.8's Has Hardware box; 2.1's ALRobotModel has none of these methods."""
    if nao.version.name != "2.8":
        pytest.skip("getRobotType and has* are 2.8's ALRobotModel")
    model = nao.service("ALRobotModel")
    assert model.getRobotType() == "Nao"
    assert model.hasArms() and model.hasHands() and model.hasLegs()


def test_body_id(request, nao):
    """Get Body ID reads the chest board's id from ALMemory: published with the robot's keys on a
    NAO V5, whose model file has one; the V6's has none (naoqi-fidelity.md)."""
    known_issue(
        request, nao, f"a NAO V6's model has no body id ({DESKTOP_FACTS})", ("2.8",)
    )
    body_id = nao.service("ALMemory").getData("Device/DeviceList/ChestBoard/BodyId")
    assert isinstance(body_id, str) and body_id


def test_joint_temperatures(request, nao):
    """Motor Heat and Get Temperature read each joint's temperature sensor in ALMemory."""
    known_issue(request, nao, f"2.8 has no Device keys ({DESKTOP_FACTS})", ("2.8",))
    memory = nao.service("ALMemory")
    joints = nao.service("ALMotion").getBodyNames("Body")
    temps = memory.getListData(
        [f"Device/SubDeviceList/{j}/Temperature/Sensor/Value" for j in joints]
    )
    assert all(isinstance(t, float) and 0 <= t < 100 for t in temps)


def test_sonar_values(nao):
    sonar = nao.service("ALSonar")
    sonar.subscribe("naoqi_sim_e2e")
    try:
        time.sleep(0.5)
        values = nao.service("ALMemory").getListData(
            [
                "Device/SubDeviceList/US/Left/Sensor/Value",
                "Device/SubDeviceList/US/Right/Sensor/Value",
            ]
        )
    finally:
        sonar.unsubscribe("naoqi_sim_e2e")
    assert all(isinstance(v, float) and v >= 0 for v in values)


def test_the_touch_and_fall_keys_exist(nao):
    """The keys the touch and fall boxes subscribe to are in ALMemory."""
    keys = set(nao.service("ALMemory").getDataListName())
    assert not set(TOUCH_EVENTS) - keys


def test_select_camera(nao):
    """Select Camera: the active camera switches, and the top camera still gets its frames."""
    video = nao.service("ALVideoDevice")
    assert video.setActiveCamera(1)
    try:
        assert video.getActiveCamera() == 1
    finally:
        assert video.setActiveCamera(0)
    assert video.getActiveCamera() == 0
    handle = video.subscribeCamera("naoqi_sim_e2e", 0, 1, 11, 15)
    stamps = []
    try:
        for _ in range(2):
            time.sleep(0.5)
            reply = video.getImageRemote(handle)
            video.releaseImage(handle)
            assert len(bytes(reply[6])) == 320 * 240 * 3
            stamps.append(reply[4] + reply[5] / 1e6)
    finally:
        video.unsubscribe(handle)
    assert stamps[1] > stamps[0]  # frames keep coming
