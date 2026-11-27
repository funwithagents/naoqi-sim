"""`NaoqiSimConfig`: which simulated NAO to run and which host devices to attach (specs/runtime/config.md).

Conventions: frozen dataclasses, one per block; three
constructors on every class (`from_dict`, `from_json`, `from_json_file`) sharing one
validation path; unknown keys are errors; a `ConfigError` names the key path. A default is
declared once, on the dataclass field: a parser passes only the keys present. Imports neither
qi, nor naoqi_viewer, nor sounddevice.
"""

import json
import math
from collections.abc import Callable
from dataclasses import MISSING, asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Literal, Self, get_args

NaoqiVersion = Literal["2.1", "2.8"]
RobotType = Literal["nao"]
AudioOutputMode = Literal["play", "silent", "record"]
AudioInputSource = Literal["none", "mic", "fake"]
MonoPolicy = Literal["duplicate", "silence"]
VideoInputSource = Literal["none", "render", "webcam"]
ViewerVariant = Literal["auto", "placeholder", "aldebaran"]
RobotPosture = Literal["crouch", "stand", "sit"]

MAX_FPS = 30  # a NAO camera's highest frame rate

# The robots each NAOqi version runs, as (type, version), its default first: the real pairs only
# (a NAO V4 or V5 ran NAOqi 2.1, a NAO V6 runs 2.8), whatever model files a suite ships
# (specs/runtime/config.md, "The robot").
ROBOTS: dict[str, tuple[tuple[str, str], ...]] = {
    "2.1": (("nao", "v5"), ("nao", "v4")),
    "2.8": (("nao", "v6"),),
}


def _robot_names(naoqi_version: str) -> str:
    return ", ".join(f"{kind} {version}" for kind, version in ROBOTS[naoqi_version])


# The language packs naoqi-sim has: a language a robot speaks, hears and talks in, with a voice in
# the speech engine and a model in the speech recognition engine (docker/asr-engine/server.py,
# `MODELS`; the fast tier checks them), in the speech engine's order. What
# `setup.available_languages` may install. Danish, Finnish and Norwegian have a voice only.
LANGUAGES = (
    "English",
    "French",
    "German",
    "Dutch",
    "Swedish",
    "Spanish",
    "Brazilian",
    "Czech",
    "Italian",
    "Polish",
    "Portuguese",
    "Russian",
    "Turkish",
)

# NAOqi's language names the speech engine has a voice for, in the engine's table order
# (docker/tts-engine/server.py, `VOICES`; the fast tier checks the two lists agree)
# (specs/container/tts-engine.md, "Languages").
SPEECH_LANGUAGES = (
    "English",
    "French",
    "German",
    "Dutch",
    "Swedish",
    "Spanish",
    "Brazilian",
    "Czech",
    "Danish",
    "Finnish",
    "Italian",
    "Norwegian",
    "Polish",
    "Portuguese",
    "Russian",
    "Turkish",
)


class ConfigError(ValueError):
    """An invalid config; `key` is the offending key path (`audio_output.record`)."""

    def __init__(self, message: str, key: str | None = None):
        super().__init__(message)
        self.message = message
        self.key = key

    def within(self, path: str) -> "ConfigError":
        """The same error, its key prefixed with an enclosing block's path."""
        if not path:
            return self
        return ConfigError(self.message, f"{path}.{self.key}" if self.key else path)

    def __str__(self) -> str:
        return f"{self.key}: {self.message}" if self.key else self.message


# --- Value parsers: JSON value -> field value, or ConfigError ------------------------

Parser = Callable[[Any], Any]


def _as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"must be a string, got {value!r}")
    return value


def _as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"must be true or false, got {value!r}")
    return value


def _as_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"must be a number, got {value!r}")
    return float(value)


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"must be an integer, got {value!r}")
    return value


def _as_path(value: Any) -> Path | None:
    return None if value is None else Path(_as_str(value))


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"must be a list of strings, got {value!r}")
    return tuple(value)


def _check_choice(value: Any, kind: Any, key: str) -> None:
    choices = get_args(kind)
    if value not in choices:
        raise ConfigError(
            f"must be one of {', '.join(map(repr, choices))}, got {value!r}", key=key
        )


# What a missing required key is told: every config names its NAOqi version.
_REQUIRED = {
    "naoqi": 'is required: the NAOqi to run, as {"version": "2.1"} or {"version": "2.8"}',
    "version": "is required: the NAOqi version to run, '2.1' or '2.8'",
}


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _parse_block[T](
    cls: type[T], data: Any, path: str, parsers: dict[str, Parser]
) -> T:
    """Build `cls` from the keys present in `data`, each through its parser."""
    if not isinstance(data, dict):
        raise ConfigError(f"must be an object, got {data!r}", key=path or None)
    names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    if unknown := sorted(set(data) - names):
        prefix = f"{path}." if path else ""
        raise ConfigError(
            f"unknown key(s) {', '.join(prefix + k for k in unknown)}; "
            f"expected {', '.join(sorted(names))}",
            key=path or None,
        )
    values = {}
    for key, value in data.items():
        try:
            values[key] = parsers[key](value)
        except ConfigError as e:
            # A value's error gets its key here; a nested block's already has its full path.
            raise (e if e.key else ConfigError(e.message, _join(path, key))) from None
    for f in fields(cls):  # type: ignore[arg-type]
        if (
            f.name not in values
            and f.default is MISSING
            and f.default_factory is MISSING
        ):
            raise ConfigError(
                _REQUIRED.get(f.name, "is required"), key=_join(path, f.name)
            )
    try:
        return cls(**values)
    except ConfigError as e:
        raise e.within(path) from None


class _Loaders:
    """The three constructors every config class shares."""

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        raise NotImplementedError

    def _relative_to(self, directory: Path) -> Self:
        """Resolve the config's relative paths against `directory` (the config file's)."""
        return self

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        return cls.parse(data, "")

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigError(f"invalid JSON: {e}") from None
        return cls.from_dict(data)

    @classmethod
    def from_json_file(cls, path: str | Path) -> Self:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"cannot read {path}: {e.strerror or e}") from None
        try:
            config = cls.from_json(text)
        except ConfigError as e:
            if e.key is None:
                raise ConfigError(f"{path}: {e.message}") from None
            raise
        return config._relative_to(path.parent)

    def to_dict(self) -> dict[str, Any]:
        """Every field as JSON-compatible data; `from_dict` reads it back to an equal config."""

        def plain(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, dict):
                return {k: plain(v) for k, v in value.items()}
            if isinstance(value, tuple):
                return [plain(v) for v in value]
            return value

        return plain(asdict(self))  # type: ignore[call-overload]  # every subclass is a dataclass


def _relative(path: Path | None, directory: Path) -> Path | None:
    return directory / path if path is not None and not path.is_absolute() else path


# --- Blocks --------------------------------------------------------------------------


@dataclass(frozen=True)
class NaoqiSettings(_Loaders):
    """Which NAOqi runs, and how long `start()` waits for it. The version has no default: every
    config names it."""

    version: NaoqiVersion
    ready_timeout_s: float = 240.0

    def __post_init__(self) -> None:
        _check_choice(self.version, NaoqiVersion, "version")
        if not (math.isfinite(self.ready_timeout_s) and self.ready_timeout_s > 0):
            raise ConfigError(
                f"must be a positive number, got {self.ready_timeout_s!r}",
                key="ready_timeout_s",
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls, data, path, {"version": _as_str, "ready_timeout_s": _as_number}
        )


@dataclass(frozen=True)
class RobotSettings(_Loaders):
    """Which robot the NAOqi runs: its type and its version, as `RobotConfig/Body/Type` and
    `RobotConfig/Body/Version` say on a robot. Each left out takes the NAOqi version's default
    (`ROBOTS`: a NAO V5 on 2.1, a NAO V6 on 2.8), which `NaoqiSimConfig` fills in, so a config's
    `robot` always names both."""

    type: RobotType | None = None
    version: str | None = None  # a NAO's: "v4", "v5", "v6"

    def __post_init__(self) -> None:
        if self.type is not None:
            _check_choice(self.type, RobotType, "type")

    def for_naoqi(self, naoqi_version: str) -> "RobotSettings":
        """This robot with the NAOqi version's defaults filled in; a `ConfigError` when that
        NAOqi does not run it."""
        robots = ROBOTS[naoqi_version]
        kinds = [kind for kind, _ in robots]
        kind = self.type if self.type is not None else kinds[0]
        if kind not in kinds:
            raise ConfigError(
                f"NAOqi {naoqi_version} does not run a {kind}; it runs: "
                + _robot_names(naoqi_version),
                key="type",
            )
        versions = [version for k, version in robots if k == kind]
        version = self.version if self.version is not None else versions[0]
        if version not in versions:
            raise ConfigError(
                f"NAOqi {naoqi_version} does not run a {kind} {version}; it runs: "
                + _robot_names(naoqi_version),
                key="version",
            )
        return RobotSettings(type=kind, version=version)  # type: ignore[arg-type]

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        def optional(value: Any) -> str | None:
            return None if value is None else _as_str(value)

        return _parse_block(cls, data, path, {"type": optional, "version": optional})


@dataclass(frozen=True)
class SetupSettings(_Loaders):
    """How the robot is set up: its language packs, and its state when the sim is ready
    (specs/container/autonomous-life.md, "The state at boot"): its posture, whether its stiffness
    is on (all joints, as after `wakeUp()`) or off (as after `rest()`), whether Autonomous Life
    runs (`solitary`), and its language. The default is a NAO in English whose Life does not
    start at boot, at rest."""

    # The installed language packs, as a NAO's: what getAvailableLanguages answers and
    # setLanguage accepts, on the speech, the recognition and the dialog (`LANGUAGES`)
    available_languages: tuple[str, ...] = ("English", "French")
    # The language at boot, one of available_languages
    language: str = "English"
    posture: RobotPosture = "crouch"
    stiffness_on: bool = False
    life_on: bool = False

    def __post_init__(self) -> None:
        _check_choice(self.posture, RobotPosture, "posture")
        languages = tuple(self.available_languages)
        object.__setattr__(self, "available_languages", languages)
        if not languages:
            raise ConfigError(
                "must name at least one language", key="available_languages"
            )
        for name in languages:
            if name not in LANGUAGES:
                raise ConfigError(
                    f"{name!r} has no language pack (a voice and a recognition model); "
                    "the languages with one: " + ", ".join(LANGUAGES),
                    key="available_languages",
                )
        if len(set(languages)) != len(languages):
            raise ConfigError("names a language twice", key="available_languages")
        if self.language not in languages:
            raise ConfigError(
                f"{self.language!r} is not one of available_languages "
                f"({', '.join(languages)})",
                key="language",
            )
        if self.posture == "stand" and not self.stiffness_on:
            raise ConfigError(
                "a NAO cannot stand with its stiffness off: 'crouch' is that state",
                key="stiffness_on",
            )
        if self.life_on and not self.stiffness_on:
            raise ConfigError(
                "Autonomous Life needs the stiffness on", key="stiffness_on"
            )
        if self.life_on and self.posture == "crouch":
            raise ConfigError(
                "Autonomous Life stands the robot up: 'stand' or 'sit'", key="posture"
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "available_languages": _as_str_tuple,
                "language": _as_str,
                "posture": _as_str,
                "stiffness_on": _as_bool,
                "life_on": _as_bool,
            },
        )


@dataclass(frozen=True)
class AudioOutputSettings(_Loaders):
    """The audio output (specs/host/audio-output.md): where the robot's audio goes."""

    mode: AudioOutputMode = "play"
    record: Path | None = None  # WAV file, required by "record"

    def __post_init__(self) -> None:
        _check_choice(self.mode, AudioOutputMode, "mode")
        if self.mode == "record" and self.record is None:
            raise ConfigError("is required by mode 'record'", key="record")

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(cls, data, path, {"mode": _as_str, "record": _as_path})

    def _relative_to(self, directory: Path) -> Self:
        return replace(self, record=_relative(self.record, directory))


@dataclass(frozen=True)
class AudioInputSettings(_Loaders):
    """The audio input, feeding the ALAudioDevice replacement (specs/host/audio-input.md)."""

    # "fake": silence, plus what code plays through NaoqiSim.fake_audio
    source: AudioInputSource = "none"
    mono: MonoPolicy = "duplicate"

    def __post_init__(self) -> None:
        _check_choice(self.source, AudioInputSource, "source")
        _check_choice(self.mono, MonoPolicy, "mono")

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "source": _as_str,
                "mono": _as_str,
            },
        )


@dataclass(frozen=True)
class CameraSettings(_Loaders):
    """What feeds one head camera (specs/host/video-input.md, "Sources")."""

    source: VideoInputSource = "none"
    fps: int = 15  # frames injected per second into this camera
    device: int = 0  # webcam index, used by "webcam"

    def __post_init__(self) -> None:
        _check_choice(self.source, VideoInputSource, "source")
        if not 1 <= self.fps <= MAX_FPS:
            raise ConfigError(
                f"must be an integer from 1 to {MAX_FPS}, got {self.fps!r}", key="fps"
            )
        if self.device < 0:
            raise ConfigError(
                f"must be a non-negative integer, got {self.device!r}", key="device"
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls, data, path, {"source": _as_str, "fps": _as_int, "device": _as_int}
        )


@dataclass(frozen=True)
class VideoInputSettings(_Loaders):
    """The video input, injected into ALVideoDevice (specs/host/video-input.md): a block per
    head camera."""

    top: CameraSettings = field(default_factory=CameraSettings)
    bottom: CameraSettings = field(default_factory=CameraSettings)

    @property
    def sources(self) -> dict[str, VideoInputSource]:
        """Each camera's source, by camera name, in NAOqi's camera order."""
        return {"top": self.top.source, "bottom": self.bottom.source}

    @property
    def rates(self) -> dict[str, int]:
        """Each camera's `fps`, by camera name."""
        return {"top": self.top.fps, "bottom": self.bottom.fps}

    def cameras(self, source: VideoInputSource) -> tuple[str, ...]:
        """The cameras fed by `source`."""
        return tuple(c for c, s in self.sources.items() if s == source)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "top": lambda d: CameraSettings.parse(d, _join(path, "top")),
                "bottom": lambda d: CameraSettings.parse(d, _join(path, "bottom")),
            },
        )


@dataclass(frozen=True)
class ViewerSettings(_Loaders):
    """The simulated world (naoqi-viewer's sim mode, specs/host/viewer.md)."""

    # No window by default: a config that renders no camera then needs no `viewer` extra
    headless: bool = True
    scene: str = (
        "empty"  # a bundled scene name ("empty", "table") or an MJCF file (.xml)
    )
    variant: ViewerVariant = "auto"
    # the head cameras as ALVideoDevice serves them, as pictures in the window
    cameras_display: bool = False
    # the people NAOqi lists in ALMemory, as markers in the window
    people_display: bool = False

    def __post_init__(self) -> None:
        if not self.scene:
            raise ConfigError("must not be empty", key="scene")
        _check_choice(self.variant, ViewerVariant, "variant")
        if self.headless and self.cameras_display:
            raise ConfigError(
                "is drawn only in the window, and a headless viewer has none",
                key="cameras_display",
            )
        if self.headless and self.people_display:
            raise ConfigError(
                "is drawn only in the window, and a headless viewer has none",
                key="people_display",
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "headless": _as_bool,
                "scene": _as_str,
                "variant": _as_str,
                "cameras_display": _as_bool,
                "people_display": _as_bool,
            },
        )

    def _relative_to(self, directory: Path) -> Self:
        if self.scene.endswith(".xml") and not Path(self.scene).is_absolute():
            return replace(self, scene=str(directory / self.scene))
        return self


@dataclass(frozen=True)
class PerceptionSettings(_Loaders):
    """The perception engine (specs/container/perception-engine.md): faces for ALFaceDetection
    and ALPeoplePerception."""

    # False starts no `perception` container: the modules still answer and find nobody
    enabled: bool = True

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(cls, data, path, {"enabled": _as_bool})


@dataclass(frozen=True)
class SpeechRecognitionSettings(_Loaders):
    """The speech recognition engine (specs/container/asr-engine.md): what ALSpeechRecognition
    hears (specs/services/speech-recognition.md)."""

    # False starts no `asr` container: ALSpeechRecognition still answers and hears nothing
    enabled: bool = True

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(cls, data, path, {"enabled": _as_bool})


@dataclass(frozen=True)
class ControlsSettings(_Loaders):
    """The controls page and its HTTP API (specs/host/controls.md)."""

    enabled: bool = False
    port: int = 9564  # on 127.0.0.1 only
    open: bool = False  # open the page in the default browser once the robot is ready

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ConfigError(
                f"must be a port, 1 to 65535, got {self.port}", key="port"
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls, data, path, {"enabled": _as_bool, "port": _as_int, "open": _as_bool}
        )


@dataclass(frozen=True)
class NaoqiSimConfig(_Loaders):
    """A simulated NAO: its NAOqi, which robot it is, how it is set up, its engines, its host
    devices and its viewer."""

    naoqi: NaoqiSettings  # required: its version has no default
    robot: RobotSettings = field(default_factory=RobotSettings)
    setup: SetupSettings = field(default_factory=SetupSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    audio_input: AudioInputSettings = field(default_factory=AudioInputSettings)
    video_input: VideoInputSettings = field(default_factory=VideoInputSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)
    perception: PerceptionSettings = field(default_factory=PerceptionSettings)
    speech_recognition: SpeechRecognitionSettings = field(
        default_factory=SpeechRecognitionSettings
    )
    controls: ControlsSettings = field(default_factory=ControlsSettings)

    def __post_init__(self) -> None:
        try:
            robot = self.robot.for_naoqi(self.naoqi.version)
        except ConfigError as e:
            raise e.within("robot") from None
        object.__setattr__(self, "robot", robot)
        if self.setup.posture == "sit" and self.naoqi.version == "2.8":
            raise ConfigError(
                "the 2.8 sim cannot reliably sit (naoqi-fidelity.md: its desktop suite has no "
                "inertial sensor); 'sit' is for 2.1",
                key="setup.posture",
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "naoqi": lambda d: NaoqiSettings.parse(d, "naoqi"),
                "robot": lambda d: RobotSettings.parse(d, "robot"),
                "setup": lambda d: SetupSettings.parse(d, "setup"),
                "audio_output": lambda d: AudioOutputSettings.parse(d, "audio_output"),
                "audio_input": lambda d: AudioInputSettings.parse(d, "audio_input"),
                "video_input": lambda d: VideoInputSettings.parse(d, "video_input"),
                "viewer": lambda d: ViewerSettings.parse(d, "viewer"),
                "perception": lambda d: PerceptionSettings.parse(d, "perception"),
                "speech_recognition": lambda d: SpeechRecognitionSettings.parse(
                    d, "speech_recognition"
                ),
                "controls": lambda d: ControlsSettings.parse(d, "controls"),
            },
        )

    def _relative_to(self, directory: Path) -> Self:
        return replace(
            self,
            audio_output=self.audio_output._relative_to(directory),
            viewer=self.viewer._relative_to(directory),
        )
