import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from naoqi_sim.config import (
    LANGUAGES,
    SPEECH_LANGUAGES,
    AudioInputSettings,
    AudioOutputSettings,
    CameraSettings,
    ConfigError,
    ControlsSettings,
    NaoqiSettings,
    NaoqiSimConfig,
    PerceptionSettings,
    RobotSettings,
    SetupSettings,
    SpeechRecognitionSettings,
    VideoInputSettings,
    ViewerSettings,
)

CI_CONFIG = Path(__file__).resolve().parent.parent / "tests-e2e" / "ci.json"


def on(version: str, **blocks) -> dict:
    """A config's data naming its NAOqi version, as every config must."""
    return {"naoqi": {"version": version}, **blocks}


def load(data: dict) -> NaoqiSimConfig:
    """`data` as a config on NAOqi 2.1, unless it names its own `naoqi` block."""
    return NaoqiSimConfig.from_dict({**on("2.1"), **data})


def defaults(version: str = "2.1") -> NaoqiSimConfig:
    return NaoqiSimConfig(naoqi=NaoqiSettings(version=version))  # type: ignore[arg-type]


def error_for(data) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        load(data)
    return info.value


def test_a_config_must_name_its_naoqi_version():
    with pytest.raises(ConfigError) as missing:
        NaoqiSimConfig.from_dict({})
    assert missing.value.key == "naoqi" and "2.1" in missing.value.message
    with pytest.raises(ConfigError) as no_version:
        NaoqiSimConfig.from_dict({"naoqi": {"ready_timeout_s": 60}})
    assert no_version.value.key == "naoqi.version"
    with pytest.raises(TypeError):
        NaoqiSimConfig()  # type: ignore[call-arg]


def test_a_config_naming_only_its_naoqi_version_is_the_defaults():
    config = NaoqiSimConfig.from_dict(on("2.1"))

    assert config == defaults()
    assert config.naoqi.version == "2.1" and config.naoqi.ready_timeout_s == 240.0
    assert config.robot == RobotSettings(type="nao", version="v5")
    assert config.setup.available_languages == ("English", "French")
    assert config.setup.language == "English"
    # a NAO whose Life does not start at boot, at rest
    assert config.setup == SetupSettings(
        posture="crouch", stiffness_on=False, life_on=False
    )
    assert config.audio_output.mode == "play"
    assert config.audio_input.source == "none"
    assert config.video_input == VideoInputSettings(
        top=CameraSettings(source="none", fps=15, device=0),
        bottom=CameraSettings(source="none", fps=15, device=0),
    )
    # no window, no camera rendered: nothing that needs the viewer
    assert config.viewer == ViewerSettings(headless=True, scene="empty", variant="auto")


@pytest.mark.parametrize(
    ("naoqi", "robot", "runs"),
    [
        ("2.1", {}, ("nao", "v5")),
        ("2.1", {"type": "nao"}, ("nao", "v5")),
        ("2.1", {"version": "v4"}, ("nao", "v4")),
        ("2.1", {"type": "nao", "version": "v5"}, ("nao", "v5")),
        ("2.8", {}, ("nao", "v6")),
        ("2.8", {"version": "v6"}, ("nao", "v6")),
        ("2.8", {"type": None, "version": None}, ("nao", "v6")),
    ],
)
def test_each_naoqi_version_has_a_default_robot_and_the_robots_it_runs(
    naoqi, robot, runs
):
    config = NaoqiSimConfig.from_dict(on(naoqi, robot=robot))
    assert (config.robot.type, config.robot.version) == runs
    # the config always names both, so its JSON does too and reads back equal
    assert config.to_dict()["robot"] == {"type": runs[0], "version": runs[1]}
    assert NaoqiSimConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize(
    ("naoqi", "robot", "key", "runs"),
    [
        ("2.8", {"version": "v5"}, "robot.version", "nao v6"),
        ("2.1", {"version": "v6"}, "robot.version", "nao v5, nao v4"),
        ("2.1", {"version": "V5"}, "robot.version", "nao v5, nao v4"),
        ("2.8", {"type": "pepper"}, "robot.type", None),
        ("2.1", {"version": 5}, "robot.version", None),
        ("2.1", {"model": "nao-v5"}, "robot", None),
    ],
)
def test_a_robot_its_naoqi_does_not_run_is_refused_naming_those_it_runs(
    naoqi, robot, key, runs
):
    with pytest.raises(ConfigError) as info:
        NaoqiSimConfig.from_dict(on(naoqi, robot=robot))
    assert info.value.key == key
    if runs:
        assert f"NAOqi {naoqi}" in info.value.message and runs in info.value.message


def test_missing_fields_keep_their_defaults_in_a_partial_block():
    config = NaoqiSimConfig.from_dict(
        {"naoqi": {"version": "2.8"}, "viewer": {"scene": "table"}}
    )

    assert config.naoqi == NaoqiSettings(version="2.8", ready_timeout_s=240.0)
    assert config.viewer == ViewerSettings(headless=True, scene="table")


def test_to_dict_reads_back_to_an_equal_config(tmp_path):
    config = NaoqiSimConfig.from_dict(
        {
            "naoqi": {"version": "2.8", "ready_timeout_s": 60},
            "robot": {"type": "nao", "version": "v6"},
            "setup": {
                "available_languages": ["French", "English"],
                "language": "French",
            },
            "audio_output": {"mode": "record", "record": str(tmp_path / "out.wav")},
            "audio_input": {"source": "fake", "mono": "silence"},
            "video_input": {
                "top": {"source": "webcam", "fps": 30, "device": 1},
                "bottom": {"source": "render", "fps": 5},
            },
            "viewer": {"headless": True, "scene": "table", "variant": "placeholder"},
            "perception": {"enabled": False},
            "speech_recognition": {"enabled": False},
        }
    )

    data = config.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert NaoqiSimConfig.from_dict(data) == config


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"naoqi": {"version": "2.5"}}, "naoqi.version"),
        ({"naoqi": {"version": 2.1}}, "naoqi.version"),
        ({"naoqi": {"version": "2.1", "ready_timeout_s": 0}}, "naoqi.ready_timeout_s"),
        (
            {"naoqi": {"version": "2.1", "ready_timeout_s": True}},
            "naoqi.ready_timeout_s",
        ),
        ({"setup": {"available_languages": []}}, "setup.available_languages"),
        ({"setup": {"available_languages": "English"}}, "setup.available_languages"),
        (
            {"setup": {"available_languages": ["English", 2]}},
            "setup.available_languages",
        ),
        (
            {"setup": {"available_languages": ["English", "Klingon"]}},
            "setup.available_languages",
        ),
        (
            {"setup": {"available_languages": ["English", "French", "French"]}},
            "setup.available_languages",
        ),
        ({"setup": {"language": "German"}}, "setup.language"),  # not installed
        ({"speech": {"languages": ["English"]}}, None),  # the block is gone
        # the robot block is which robot it is: its languages and state moved to `setup`
        ({"robot": {"language": "French"}}, "robot"),
        ({"robot": {"posture": "crouch"}}, "robot"),
        ({"audio_output": {"mode": "loud"}}, "audio_output.mode"),
        ({"audio_input": {"mono": "left"}}, "audio_input.mono"),
        ({"video_input": {"top": {"device": -1}}}, "video_input.top.device"),
        ({"video_input": {"bottom": {"device": 1.5}}}, "video_input.bottom.device"),
        ({"video_input": {"bottom": {"source": "lidar"}}}, "video_input.bottom.source"),
        ({"video_input": {"top": "render"}}, "video_input.top"),
        (
            {"video_input": {"source": "render"}},
            "video_input",
        ),  # the old shape: per camera now
        ({"video_input": {"top": {"fps": 0}}}, "video_input.top.fps"),
        ({"video_input": {"bottom": {"fps": 31}}}, "video_input.bottom.fps"),
        ({"video_input": {"top": {"fps": 12.5}}}, "video_input.top.fps"),
        ({"video_input": {"top": {"fps": "15"}}}, "video_input.top.fps"),
        ({"video_input": {"fps": 15}}, "video_input"),  # per camera now
        ({"viewer": {"headless": "yes"}}, "viewer.headless"),
        ({"viewer": {"scene": ""}}, "viewer.scene"),
        ({"viewer": {"variant": "shiny"}}, "viewer.variant"),
        ({"viewer": []}, "viewer"),
    ],
)
def test_a_bad_value_names_its_key_path(data, key):
    assert error_for(data).key == key


@pytest.mark.parametrize("fps", [1, 30])
def test_the_frame_rate_takes_a_nao_cameras_range(fps):
    assert load({"video_input": {"bottom": {"fps": fps}}}).video_input.rates == {
        "top": 15,
        "bottom": fps,
    }


def test_unknown_keys_are_errors_naming_them():
    e = error_for({"viewer": {"headles": True}})
    assert e.key == "viewer"
    assert "viewer.headles" in str(e)

    assert "camera" in str(error_for({"camera": {}}))


def test_cross_field_requirements():
    assert error_for({"audio_output": {"mode": "record"}}).key == "audio_output.record"
    # A field that does not apply is validated but not required: switching is one word.
    config = load({"audio_output": {"mode": "play", "record": "x.wav"}})
    assert config.audio_output.record == Path("x.wav")
    # The cameras' pictures are drawn in the window: a headless viewer has none.
    assert (
        error_for({"viewer": {"headless": True, "cameras_display": True}}).key
        == "viewer.cameras_display"
    )
    assert (
        error_for({"viewer": {"headless": True, "people_display": True}}).key
        == "viewer.people_display"
    )


def test_the_wav_source_is_gone():
    # Never built, replaced by the fake source: a file that still uses it fails at load.
    assert error_for({"audio_input": {"source": "wav"}}).key == "audio_input.source"
    unknown = error_for({"audio_input": {"wav": "x.wav"}})
    assert unknown.key == "audio_input" and "wav" in str(unknown)
    # The gate's tail went with the gate: the robot hears itself, as a NAO does.
    gate = error_for({"audio_input": {"gate_tail_s": 0.3}})
    assert gate.key == "audio_input" and "gate_tail_s" in str(gate)
    assert load({"audio_input": {"source": "fake"}}).audio_input == (
        AudioInputSettings(source="fake")
    )


def test_every_default_is_declared_once_on_the_dataclass():
    for cls in (
        RobotSettings,
        SetupSettings,
        AudioOutputSettings,
        AudioInputSettings,
        VideoInputSettings,
        ViewerSettings,
        PerceptionSettings,
        SpeechRecognitionSettings,
    ):
        assert cls.from_dict({}) == cls()
        assert {f.name for f in fields(cls)} == set(cls().to_dict())


def test_json_errors(tmp_path):
    with pytest.raises(ConfigError, match="invalid JSON"):
        NaoqiSimConfig.from_json("{")
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(ConfigError, match=re.escape(str(bad))):
        NaoqiSimConfig.from_json_file(bad)
    with pytest.raises(ConfigError, match="cannot read"):
        NaoqiSimConfig.from_json_file(tmp_path / "missing.json")


def test_paths_in_a_file_resolve_against_its_folder(tmp_path):
    folder = tmp_path / "configs"
    folder.mkdir()
    path = folder / "sim.json"
    path.write_text(
        json.dumps(
            {
                "naoqi": {"version": "2.1"},
                "audio_output": {"mode": "record", "record": "out/played.wav"},
                "viewer": {"scene": "scenes/room.xml"},
            }
        )
    )

    config = NaoqiSimConfig.from_json_file(path)
    assert config.audio_output.record == folder / "out" / "played.wav"
    assert config.viewer.scene == str(folder / "scenes" / "room.xml")
    # A bundled scene name is not a path.
    path.write_text(json.dumps(on("2.1", viewer={"scene": "table"})))
    assert NaoqiSimConfig.from_json_file(path).viewer.scene == "table"
    # From a dict, paths stay as written (relative to the working directory).
    assert load(
        {"audio_output": {"mode": "record", "record": "a.wav"}}
    ).audio_output.record == Path("a.wav")


def test_the_live_tiers_settings_load():
    # tests-e2e/ci.json: what the live tier runs each NAOqi version with (it adds the version).
    data = json.loads(CI_CONFIG.read_text())
    assert "naoqi" not in data
    ci = load(data)
    assert ci.viewer == ViewerSettings(headless=True, variant="placeholder")
    assert ci.video_input.sources == {"top": "render", "bottom": "render"}
    assert ci.video_input.rates == {"top": 15, "bottom": 5}
    assert ci.audio_output.mode == "silent"
    assert ci.audio_input.source == "fake"


def test_a_language_is_available_only_with_its_language_pack():
    """A voice and a recognition model, as a NAO's language pack installs them; a language with
    a voice only (Danish) is refused, naming the languages that have one."""
    config = load({"setup": {"available_languages": ["French"], "language": "French"}})
    assert config.setup.available_languages == ("French",)
    assert config.to_dict()["setup"]["available_languages"] == ["French"]
    in_code: Any = ["French"]  # a list in code is kept as a tuple
    setup = SetupSettings(available_languages=in_code, language="French")
    assert setup.available_languages == ("French",)
    german = load(
        {
            "setup": {
                "available_languages": ["German", "Portuguese"],
                "language": "German",
            }
        }
    )
    assert german.setup.available_languages == ("German", "Portuguese")
    error = error_for({"setup": {"available_languages": ["English", "Danish"]}})
    assert "'Danish' has no language pack" in str(error)
    assert "English, French, German, Dutch" in str(error)
    for voice_only in ("Danish", "Finnish", "Norwegian", "Japanese"):
        assert voice_only not in LANGUAGES
    assert set(LANGUAGES) <= set(SPEECH_LANGUAGES)  # each has a voice
    assert LANGUAGES == tuple(
        l for l in SPEECH_LANGUAGES if l in LANGUAGES
    )  # its order


def test_the_language_at_boot_must_be_available():
    error = error_for(
        {"setup": {"available_languages": ["English"], "language": "French"}}
    )
    assert error.key == "setup.language" and "'French' is not one of" in error.message


def test_the_speech_recognition_engine_is_on_unless_the_config_turns_it_off():
    assert defaults().speech_recognition == SpeechRecognitionSettings(enabled=True)
    off = load({"speech_recognition": {"enabled": False}})
    assert not off.speech_recognition.enabled
    assert load(off.to_dict()) == off
    bad = error_for({"speech_recognition": {"enabled": "off"}})
    assert bad.key == "speech_recognition.enabled"
    unknown = error_for({"speech_recognition": {"languages": ["English"]}})
    assert unknown.key == "speech_recognition"


def test_the_perception_engine_is_on_unless_the_config_turns_it_off():
    # A NAO has no such switch: the modules are always loaded, the engine is the config's.
    assert defaults().perception == PerceptionSettings(enabled=True)
    assert load({"perception": {}}).perception.enabled
    off = load({"perception": {"enabled": False}})
    assert not off.perception.enabled
    assert load(off.to_dict()) == off

    assert error_for({"perception": {"enabled": "no"}}).key == "perception.enabled"
    assert error_for({"perception": {"enabled": 1}}).key == "perception.enabled"
    unknown = error_for({"perception": {"detector": "yunet"}})
    assert unknown.key == "perception" and "perception.detector" in str(unknown)


@pytest.mark.parametrize(
    "setup",
    [
        {},
        {"stiffness_on": True},
        {"posture": "stand", "stiffness_on": True},
        {"posture": "stand", "stiffness_on": True, "life_on": True},
        {"posture": "sit"},
        {"posture": "sit", "stiffness_on": True},
        {"posture": "sit", "stiffness_on": True, "life_on": True},
    ],
)
def test_the_robot_states_a_nao_can_be_in(setup):
    config = load({"setup": setup})
    assert config.setup == SetupSettings(**setup)


@pytest.mark.parametrize(
    ("setup", "key", "why"),
    [
        (
            {"posture": "stand"},
            "setup.stiffness_on",
            "cannot stand with its stiffness off",
        ),
        (
            {"posture": "sit", "life_on": True},
            "setup.stiffness_on",
            "Life needs the stiffness on",
        ),
        (
            {"stiffness_on": True, "life_on": True},
            "setup.posture",
            "stands the robot up",
        ),
        ({"posture": "lying"}, "setup.posture", "must be one of"),
    ],
)
def test_a_state_a_nao_cannot_be_in_is_refused_saying_why(setup, key, why):
    error = error_for({"setup": setup})
    assert error.key == key and why in error.message


def test_the_2_8_sim_cannot_sit():
    error = error_for({"naoqi": {"version": "2.8"}, "setup": {"posture": "sit"}})
    assert error.key == "setup.posture" and "inertial sensor" in error.message
    assert load({"setup": {"posture": "sit"}}).setup.posture == "sit"


def test_the_controls_are_off_unless_the_config_turns_them_on():
    assert defaults().controls == ControlsSettings(enabled=False, port=9564, open=False)
    config = load({"controls": {"enabled": True, "port": 8000}})
    assert config.controls == ControlsSettings(enabled=True, port=8000)
    assert config.to_dict()["controls"] == {
        "enabled": True,
        "port": 8000,
        "open": False,
    }
    assert error_for({"controls": {"port": 0}}).key == "controls.port"
    assert error_for({"controls": {"enabled": "yes"}}).key == "controls.enabled"
    assert error_for({"controls": {"page": True}}).key == "controls"
