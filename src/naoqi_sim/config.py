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
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Literal, Self, get_args

NaoqiVersion = Literal["2.1", "2.8"]
SpeechEngine = Literal["piper", "espeak"]
AudioOutputMode = Literal["play", "silent", "record"]
AudioInputSource = Literal["none", "mic", "fake"]
MonoPolicy = Literal["duplicate", "silence"]
VideoInputSource = Literal["none", "render", "webcam"]
ViewerVariant = Literal["auto", "placeholder", "aldebaran"]

MAX_FPS = 30  # a NAO camera's highest frame rate


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


def _check_choice(value: Any, kind: Any, key: str) -> None:
    choices = get_args(kind)
    if value not in choices:
        raise ConfigError(
            f"must be one of {', '.join(map(repr, choices))}, got {value!r}", key=key
        )


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
            return value

        return plain(asdict(self))  # type: ignore[call-overload]  # every subclass is a dataclass


def _relative(path: Path | None, directory: Path) -> Path | None:
    return directory / path if path is not None and not path.is_absolute() else path


# --- Blocks --------------------------------------------------------------------------


@dataclass(frozen=True)
class NaoqiSettings(_Loaders):
    """Which NAOqi runs, and how long `start()` waits for it."""

    version: NaoqiVersion = "2.1"
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
class SpeechSettings(_Loaders):
    """The tts container's engine."""

    engine: SpeechEngine = "piper"

    def __post_init__(self) -> None:
        _check_choice(self.engine, SpeechEngine, "engine")

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(cls, data, path, {"engine": _as_str})


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

    headless: bool = False
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
class NaoqiSimConfig(_Loaders):
    """A simulated NAO: its NAOqi, its speech engine, its host devices and its viewer."""

    naoqi: NaoqiSettings = field(default_factory=NaoqiSettings)
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    audio_input: AudioInputSettings = field(default_factory=AudioInputSettings)
    video_input: VideoInputSettings = field(default_factory=VideoInputSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return _parse_block(
            cls,
            data,
            path,
            {
                "naoqi": lambda d: NaoqiSettings.parse(d, "naoqi"),
                "speech": lambda d: SpeechSettings.parse(d, "speech"),
                "audio_output": lambda d: AudioOutputSettings.parse(d, "audio_output"),
                "audio_input": lambda d: AudioInputSettings.parse(d, "audio_input"),
                "video_input": lambda d: VideoInputSettings.parse(d, "video_input"),
                "viewer": lambda d: ViewerSettings.parse(d, "viewer"),
            },
        )

    def _relative_to(self, directory: Path) -> Self:
        return replace(
            self,
            audio_output=self.audio_output._relative_to(directory),
            viewer=self.viewer._relative_to(directory),
        )
