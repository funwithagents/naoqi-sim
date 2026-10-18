import json
import re
from dataclasses import fields
from pathlib import Path

import pytest

from naoqi_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    CameraSettings,
    ConfigError,
    NaoqiSettings,
    NaoqiSimConfig,
    VideoInputSettings,
    ViewerSettings,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "configs"


def error_for(data) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        NaoqiSimConfig.from_dict(data)
    return info.value


def test_an_empty_config_is_the_defaults():
    config = NaoqiSimConfig.from_dict({})

    assert config == NaoqiSimConfig()
    assert config.naoqi.version == "2.1" and config.naoqi.ready_timeout_s == 240.0
    assert config.speech.engine == "piper"
    assert config.audio_output.mode == "play"
    assert config.audio_input.source == "none"
    assert config.video_input == VideoInputSettings(
        top=CameraSettings(source="none", fps=15, device=0),
        bottom=CameraSettings(source="none", fps=15, device=0),
    )
    assert config.viewer == ViewerSettings(
        headless=False, scene="empty", variant="auto"
    )


def test_missing_fields_keep_their_defaults_in_a_partial_block():
    config = NaoqiSimConfig.from_dict(
        {"naoqi": {"version": "2.8"}, "viewer": {"headless": True}}
    )

    assert config.naoqi == NaoqiSettings(version="2.8", ready_timeout_s=240.0)
    assert config.viewer == ViewerSettings(headless=True)


def test_to_dict_reads_back_to_an_equal_config(tmp_path):
    config = NaoqiSimConfig.from_dict(
        {
            "naoqi": {"version": "2.8", "ready_timeout_s": 60},
            "speech": {"engine": "espeak"},
            "audio_output": {"mode": "record", "record": str(tmp_path / "out.wav")},
            "audio_input": {"source": "fake", "mono": "silence"},
            "video_input": {
                "top": {"source": "webcam", "fps": 30, "device": 1},
                "bottom": {"source": "render", "fps": 5},
            },
            "viewer": {"headless": True, "scene": "table", "variant": "placeholder"},
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
        ({"naoqi": {"ready_timeout_s": 0}}, "naoqi.ready_timeout_s"),
        ({"naoqi": {"ready_timeout_s": True}}, "naoqi.ready_timeout_s"),
        ({"speech": {"engine": "festival"}}, "speech.engine"),
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
    assert NaoqiSimConfig.from_dict(
        {"video_input": {"bottom": {"fps": fps}}}
    ).video_input.rates == {"top": 15, "bottom": fps}


def test_unknown_keys_are_errors_naming_them():
    e = error_for({"viewer": {"headles": True}})
    assert e.key == "viewer"
    assert "viewer.headles" in str(e)

    assert "camera" in str(error_for({"camera": {}}))


def test_cross_field_requirements():
    assert error_for({"audio_output": {"mode": "record"}}).key == "audio_output.record"
    # A field that does not apply is validated but not required: switching is one word.
    config = NaoqiSimConfig.from_dict(
        {"audio_output": {"mode": "play", "record": "x.wav"}}
    )
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
    assert NaoqiSimConfig.from_dict(
        {"audio_input": {"source": "fake"}}
    ).audio_input == (AudioInputSettings(source="fake"))


def test_every_default_is_declared_once_on_the_dataclass():
    for cls in (
        NaoqiSettings,
        AudioOutputSettings,
        AudioInputSettings,
        VideoInputSettings,
        ViewerSettings,
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
                "audio_output": {"mode": "record", "record": "out/played.wav"},
                "viewer": {"scene": "scenes/room.xml"},
            }
        )
    )

    config = NaoqiSimConfig.from_json_file(path)
    assert config.audio_output.record == folder / "out" / "played.wav"
    assert config.viewer.scene == str(folder / "scenes" / "room.xml")
    # A bundled scene name is not a path.
    path.write_text(json.dumps({"viewer": {"scene": "table"}}))
    assert NaoqiSimConfig.from_json_file(path).viewer.scene == "table"
    # From a dict, paths stay as written (relative to the working directory).
    assert NaoqiSimConfig.from_dict(
        {"audio_output": {"mode": "record", "record": "a.wav"}}
    ).audio_output.record == Path("a.wav")


def test_the_example_files_load():
    names = sorted(p.name for p in EXAMPLES.glob("*.json"))
    assert names == [
        "2.8.json",
        "ci.json",
        "default.json",
        "headless.json",
        "mic.json",
        "webcam.json",
    ]
    default = NaoqiSimConfig.from_json_file(EXAMPLES / "default.json")
    assert default == NaoqiSimConfig()
    assert NaoqiSimConfig.from_json_file(EXAMPLES / "2.8.json") == NaoqiSimConfig(
        naoqi=NaoqiSettings(version="2.8")
    )
    headless = NaoqiSimConfig.from_json_file(EXAMPLES / "headless.json")
    assert headless.viewer.headless and headless.audio_output.mode == "silent"
    ci = NaoqiSimConfig.from_json_file(EXAMPLES / "ci.json")
    assert ci.viewer == ViewerSettings(headless=True, variant="placeholder")
    assert ci.video_input.sources == {"top": "render", "bottom": "render"}
    assert ci.video_input.rates == {"top": 15, "bottom": 5}
    assert ci.audio_output.mode == "silent"
    assert ci.audio_input.source == "fake"
    mic = NaoqiSimConfig.from_json_file(EXAMPLES / "mic.json")
    assert mic == NaoqiSimConfig(audio_input=AudioInputSettings(source="mic"))
    webcam = NaoqiSimConfig.from_json_file(EXAMPLES / "webcam.json")
    assert webcam == NaoqiSimConfig(
        video_input=VideoInputSettings(
            top=CameraSettings(source="webcam", device=0),
            bottom=CameraSettings(source="render"),
        ),
        viewer=ViewerSettings(cameras_display=True),
    )
