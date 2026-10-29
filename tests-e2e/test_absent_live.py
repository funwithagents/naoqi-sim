"""Services the Choregraphe boxes call that a NAO has and naoqi-sim does not: the desktop suites do
not ship them (perception, recognition, photo and video capture, infrared, the tablet), or they are
left out on purpose (`ALSystem`, whose absence tells a client the target is not a robot;
specs/container/naoqi-fidelity.md, "Matching a real NAOqi robot's modules"). A client calling one gets an error, as
on any target without it. A box that needs one cannot run on naoqi-sim
(plans/202610132100_api-coverage-from-boxes.md). `ALFaceDetection` is not among them since
Oct 29, 2026: naoqi-sim adds it (specs/services/face-detection.md)."""

import pytest

ABSENT = {
    "ALSystem",
    "ALSpeechRecognition",
    "ALFaceCharacteristics",
    "ALLandMarkDetection",
    "ALVisionRecognition",
    "ALPhotoCapture",
    "ALVideoRecorder",
    "ALSoundLocalization",
    "ALAudioSourceLocalization",
    "ALSoundDetection",
    "ALBacklightingDetection",
    "ALDarknessDetection",
    "ALInfrared",
    "ALTabletService",
}
# 2.8's desktop suite loads ALVisionRecognition (measured Oct 13, 2026); 2.1's does not.
PRESENT_ON = {"2.8": {"ALVisionRecognition"}}


def test_the_services_a_nao_has_and_naoqi_sim_does_not(nao):
    present = {s["name"] for s in nao.session.services()}
    assert not (ABSENT - PRESENT_ON.get(nao.version.name, set())) & present


def test_calling_an_absent_service_fails(nao):
    with pytest.raises(RuntimeError):
        nao.service("ALSystem")
