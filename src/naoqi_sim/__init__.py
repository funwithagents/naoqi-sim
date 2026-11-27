"""naoqi-sim: a simulated NAOqi robot. The front door re-exports what a caller needs (specs/runtime/api.md)."""

from naoqi_sim.audio_input import FakeAudioSource, Take
from naoqi_sim.audio_output import (
    AudioSink,
    DevicePlayer,
    MemorySink,
    NullSink,
    Playback,
    WavSink,
)
from naoqi_sim.config import (
    LANGUAGES,
    SPEECH_LANGUAGES,
    AudioInputSettings,
    AudioInputSource,
    AudioOutputMode,
    AudioOutputSettings,
    ConfigError,
    ControlsSettings,
    MonoPolicy,
    NaoqiSettings,
    NaoqiSimConfig,
    NaoqiVersion,
    PerceptionSettings,
    RobotPosture,
    RobotSettings,
    SetupSettings,
    SpeechRecognitionSettings,
    VideoInputSettings,
    VideoInputSource,
    ViewerSettings,
    ViewerVariant,
)
from naoqi_sim.docker_images import check_images, fetch_and_build_images
from naoqi_sim.errors import (
    BootError,
    CameraNotFedError,
    DeviceNotBuiltError,
    DeviceUnavailableError,
    DockerUnavailableError,
    FetchError,
    ImageBuildError,
    ImagesMissingError,
    ImagesOutdatedError,
    MissingExtraError,
    NaoqiSimError,
    NotRunningError,
    PortInUseError,
)
from naoqi_sim.sim import NaoqiSim
from naoqi_sim.stack import (
    ContainerState,
    NaoqiSimStatus,
    StackStatus,
    cleanup,
    read_status,
)

__all__ = [
    "LANGUAGES",
    "SPEECH_LANGUAGES",
    "AudioInputSettings",
    "AudioInputSource",
    "AudioOutputMode",
    "AudioOutputSettings",
    "AudioSink",
    "BootError",
    "CameraNotFedError",
    "ConfigError",
    "ContainerState",
    "ControlsSettings",
    "DeviceNotBuiltError",
    "DevicePlayer",
    "DeviceUnavailableError",
    "DockerUnavailableError",
    "FakeAudioSource",
    "FetchError",
    "ImageBuildError",
    "ImagesMissingError",
    "ImagesOutdatedError",
    "MemorySink",
    "MissingExtraError",
    "MonoPolicy",
    "NaoqiSettings",
    "NaoqiSim",
    "NaoqiSimConfig",
    "NaoqiSimError",
    "NaoqiSimStatus",
    "NaoqiVersion",
    "NotRunningError",
    "NullSink",
    "PerceptionSettings",
    "Playback",
    "PortInUseError",
    "RobotPosture",
    "RobotSettings",
    "SetupSettings",
    "SpeechRecognitionSettings",
    "StackStatus",
    "Take",
    "VideoInputSettings",
    "VideoInputSource",
    "ViewerSettings",
    "ViewerVariant",
    "WavSink",
    "check_images",
    "cleanup",
    "fetch_and_build_images",
    "read_status",
]


def __getattr__(name: str):
    """naoqi-viewer's `PropState` and `PropError`, for the callers of `NaoqiSim.props`; they need
    the `viewer` extra, so they are imported only when asked for."""
    if name in ("PropState", "PropError"):
        import naoqi_viewer

        return getattr(naoqi_viewer, name)
    raise AttributeError(f"module 'naoqi_sim' has no attribute {name!r}")
