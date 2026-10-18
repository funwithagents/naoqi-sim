"""naoqi-sim: a NAO in a box. The front door re-exports what a caller needs (specs/runtime/api.md)."""

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
    AudioInputSettings,
    AudioInputSource,
    AudioOutputMode,
    AudioOutputSettings,
    ConfigError,
    MonoPolicy,
    NaoqiSettings,
    NaoqiSimConfig,
    NaoqiVersion,
    SpeechEngine,
    SpeechSettings,
    VideoInputSettings,
    VideoInputSource,
    ViewerSettings,
    ViewerVariant,
)
from naoqi_sim.docker_images import check_images, fetch_and_build_images
from naoqi_sim.errors import (
    BootError,
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
    "AudioInputSettings",
    "AudioInputSource",
    "AudioOutputMode",
    "AudioOutputSettings",
    "AudioSink",
    "BootError",
    "ConfigError",
    "ContainerState",
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
    "Playback",
    "PortInUseError",
    "SpeechEngine",
    "SpeechSettings",
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
