"""naoqi-sim's own errors, shared by its modules. Each message says what to do about it."""


class NaoqiSimError(RuntimeError):
    """The base of naoqi-sim's own errors."""


class NotRunningError(NaoqiSimError):
    """A `NaoqiSim` member that needs it running was used before `start()` or after `stop()`."""


class DockerUnavailableError(NaoqiSimError):
    """Docker is not installed or does not answer."""


class PortInUseError(NaoqiSimError):
    """A port naoqi-sim needs is taken (another naoqi-sim, a stack or audio output started by hand)."""


class ImagesMissingError(NaoqiSimError):
    """A version's images are not built, or were not verified by `fetch_and_build_images`."""


class ImagesOutdatedError(NaoqiSimError):
    """A version's images were built by another naoqi-sim version: their override modules are stale."""


class MissingExtraError(NaoqiSimError):
    """The config needs an optional dependency that is not installed (`naoqi-sim[viewer]`)."""


class DeviceNotBuiltError(NaoqiSimError):
    """The config asks for a host device source that is not built yet."""


class DeviceUnavailableError(NaoqiSimError):
    """A host device the config asks for cannot run here (no PortAudio, no input device)."""


class BootError(NaoqiSimError):
    """The NAOqi container exited, turned unhealthy or was not healthy in time."""


class FetchError(NaoqiSimError):
    """A file of the image data could not be fetched or does not have its pinned hash."""


class ImageBuildError(NaoqiSimError):
    """`docker compose build` failed."""


class CameraNotFedError(NaoqiSimError):
    """A head camera was covered or uncovered while the video input does not feed it."""
