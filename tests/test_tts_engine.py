import io
import json
import re
import socket
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import server

from naoqi_sim.config import SPEECH_LANGUAGES, SpeechSettings

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

DOCKERFILE = (
    Path(__file__).resolve().parent.parent / "docker" / "tts-engine" / "Dockerfile"
)


class Calls(list[tuple[str, str]]):
    """The (language, text) of each synthesis, and the pitch each was given."""

    def __init__(self) -> None:
        super().__init__()
        self.pitches: list[float] = []


@pytest.fixture
def synth(monkeypatch):
    """A fake Piper: a text item "<seconds>@<rate>" synthesizes that many seconds at that rate."""
    calls = Calls()
    pitches = calls.pitches

    def synthesize(text, lang, rate, pitch=100):
        calls.append((lang, text))
        pitches.append(pitch)
        seconds, sr = text.split("@")
        return (
            np.full(round(float(seconds) * int(sr)), 1000, dtype=np.int16),
            int(sr),
            server.VOICES[lang],
        )

    monkeypatch.setattr(server, "synth_piper", synthesize)
    return calls


def text(t):
    return {"type": "text", "text": t}


def mark(i):
    return {"type": "mark", "id": i}


def pause(ms):
    return {"type": "pause", "ms": ms}


# -- languages and voices -----------------------------------------------------


def test_the_engine_and_the_config_name_the_same_languages():
    """The config refuses a language the engine has no voice for, so the two lists are one."""
    assert tuple(server.VOICES) == SPEECH_LANGUAGES
    assert server.DEFAULT_LANGUAGES == SpeechSettings().languages


def test_the_image_bakes_the_default_languages_voices_from_the_pinned_release():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    tag = re.search(r"^ARG VOICES_TAG=(\S+)", dockerfile, re.MULTILINE)
    assert tag is not None and tag.group(1) == server.VOICES_TAG
    baked = re.findall(
        r"\b([a-z]{2}/[a-z]{2}_[A-Z]{2}/\S+/\S+/\S+-\S+-\S+)\b", dockerfile
    )
    assert sorted(baked) == sorted(
        server.voice_path(server.VOICES[lang]) for lang in server.DEFAULT_LANGUAGES
    )


def test_a_voice_path_follows_piper_voices_layout():
    assert server.voice_path("en_US-ljspeech-medium") == (
        "en/en_US/ljspeech/medium/en_US-ljspeech-medium"
    )
    assert (
        server.voice_path("pt_PT-tugão-medium")
        == "pt/pt_PT/tugão/medium/pt_PT-tugão-medium"
    )


def test_installed_languages_come_from_the_environment_in_order():
    assert server.installed_languages("German, English ,French") == (
        "German",
        "English",
        "French",
    )
    assert server.installed_languages("") == server.DEFAULT_LANGUAGES
    with pytest.raises(ValueError, match="no voice for Klingon"):
        server.installed_languages("English,Klingon")


@pytest.fixture
def voice_roots(tmp_path, monkeypatch):
    """An image root and a volume root for the voices, both empty."""
    builtin, volume = tmp_path / "builtin", tmp_path / "volume"
    monkeypatch.setattr(server, "BUILTIN_DIR", str(builtin))
    monkeypatch.setattr(server, "VOICE_DIR", str(volume))
    return builtin / server.VOICES_TAG, volume / server.VOICES_TAG


def put_voice(root: Path, key: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{key}.onnx").write_bytes(b"model")
    (root / f"{key}.onnx.json").write_text("{}")
    return root / f"{key}.onnx"


@pytest.fixture
def downloads(monkeypatch):
    """A fake piper-voices: the URLs fetched, each answered with a small file."""
    urls: list[str] = []

    def urlopen(url, timeout=0):
        urls.append(url)
        return io.BytesIO(b"model" if url.endswith(".onnx") else b"{}")

    monkeypatch.setattr(server.urllib.request, "urlopen", urlopen)
    return urls


def test_a_voice_in_the_image_is_never_fetched(voice_roots, downloads):
    builtin, volume = voice_roots
    onnx = put_voice(builtin, "fr_FR-siwis-medium")

    assert server.ensure_voice("French") == str(onnx)
    assert downloads == [] and not volume.exists()


def test_a_voice_the_volume_has_is_reused(voice_roots, downloads):
    _, volume = voice_roots
    onnx = put_voice(volume, "de_DE-thorsten-medium")

    assert server.ensure_voice("German") == str(onnx)
    assert downloads == []


def test_a_missing_voice_is_fetched_into_the_volume_from_the_pinned_release(
    voice_roots, downloads
):
    _, volume = voice_roots

    onnx = server.ensure_voice("Portuguese")

    assert onnx == str(volume / "pt_PT-tugão-medium.onnx")
    assert Path(onnx).read_bytes() == b"model"
    assert json.loads(Path(onnx + ".json").read_text()) == {}
    base = server.VOICES_URL + "pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium"
    assert downloads == [base + ".onnx.json", base + ".onnx"]  # the key percent-encoded
    assert not list(volume.glob("*.part"))


def test_a_download_that_dies_leaves_no_half_file(voice_roots, monkeypatch):
    _, volume = voice_roots

    class Dies(io.BytesIO):
        def read(self, size=-1, /):
            raise OSError("connection reset")

    monkeypatch.setattr(server.urllib.request, "urlopen", lambda url, timeout=0: Dies())
    with pytest.raises(OSError):
        server.ensure_voice("Czech")

    assert not (volume / "cs_CZ-jirka-medium.onnx.json").exists()
    assert server.find_voice("cs_CZ-jirka-medium") is None


def test_health_is_ok_once_every_installed_voice_is_loaded(monkeypatch):
    monkeypatch.setattr(server, "LANGUAGES", ("English", "German"))
    monkeypatch.setattr(server, "_voices", {"English": object()})
    monkeypatch.setattr(server, "_ready", {"ok": False})

    ok, reply = server.health()
    assert not ok
    assert reply["languages"] == {
        "English": {"voice": "en_US-ljspeech-medium", "loaded": True},
        "German": {"voice": "de_DE-thorsten-medium", "loaded": False},
    }
    assert reply["voices_tag"] == server.VOICES_TAG

    server._voices["German"] = object()
    server._ready["ok"] = True
    ok, reply = server.health()
    assert ok and reply["ok"] and reply["languages"]["German"]["loaded"]


def test_a_say_in_a_language_not_installed_is_refused_unsynthesized(synth, monkeypatch):
    monkeypatch.setattr(server, "LANGUAGES", ("English",))

    with pytest.raises(server.UnknownLanguage, match="French"):
        server.render({"language": "French", "items": [text("0.1@22050")]})
    assert synth == []

    _, _, _, used = server.render({"items": [text("0.1@22050")]})  # the first installed
    assert used == "en_US-ljspeech-medium" and synth == [("English", "0.1@22050")]


# -- pitch ---------------------------------------------------------------------


def test_the_english_and_french_voices_are_pitched_up_the_others_not():
    assert server.pitch_factor("English", 100) == pytest.approx(1.15)
    assert server.pitch_factor("French", 100) == pytest.approx(1.15)
    assert server.pitch_factor("German", 100) == 1.0
    assert server.pitch_factor("Turkish", None) == 1.0


def test_the_says_pitch_multiplies_the_voices_within_a_naos_range():
    assert server.pitch_factor("English", 200) == pytest.approx(2.3)  # \vct=200\
    assert server.pitch_factor("German", 150) == pytest.approx(1.5)  # pitchShift 1.5
    assert server.pitch_factor("English", 400) == 4.0  # pitchShift 4, the top
    assert server.pitch_factor("German", 10) == 0.5


def test_shifting_plays_the_audio_faster_by_the_factor():
    t = np.arange(22050) / 22050.0  # 1 s of a 220 Hz tone
    tone = (10000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)

    shifted = server.shift(tone, 1.15)

    assert len(shifted) == pytest.approx(22050 / 1.15, abs=1)
    spectrum = np.abs(np.fft.rfft(shifted.astype(np.float64)))
    peak_hz = np.argmax(spectrum) * 22050 / len(shifted)
    assert peak_hz == pytest.approx(220 * 1.15, abs=3)  # a 253 Hz tone now
    assert server.shift(tone, 1.0) is tone


def test_the_pitch_reaches_the_synthesis_and_the_marks_follow_the_shifted_audio(synth):
    pcm, _, marks, _ = server.render(
        {"pitch": 150, "items": [text("1.0@22050"), mark(1), text("0.5@22050")]}
    )

    assert synth.pitches == [150, 150]
    assert marks == {"1": 1.0}  # offsets are measured on the audio as it will play
    assert len(pcm) == int(1.5 * 22050)


# -- rendering -----------------------------------------------------------------


def test_marks_sit_at_the_audio_before_them(synth):
    pcm, sr, marks, used = server.render(
        {"items": [mark(1), text("1.0@22050"), mark(2), text("0.5@22050"), mark(3)]}
    )

    assert marks == {"1": 0.0, "2": 1.0, "3": 1.5}
    assert (len(pcm), sr, used) == (int(1.5 * 22050), 22050, "en_US-ljspeech-medium")


def test_pauses_add_exact_silence(synth):
    pcm, _, marks, _ = server.render(
        {"items": [text("0.2@22050"), pause(300), mark(1), text("0.1@22050")]}
    )

    assert marks == {"1": 0.5}
    assert len(pcm) == int(0.6 * 22050)
    silence = pcm[int(0.2 * 22050) : int(0.5 * 22050)]
    assert not silence.any()


def test_parts_are_resampled_to_the_first_rate(synth):
    pcm, sr, marks, _ = server.render(
        {"items": [text("1.0@22050"), mark(1), text("0.5@16000"), mark(2)]}
    )

    assert sr == 22050
    assert marks == {"1": 1.0, "2": pytest.approx(1.5, abs=1e-3)}
    assert len(pcm) / sr == pytest.approx(1.5, abs=1e-3)


def test_empty_text_items_are_skipped(synth):
    pcm, _, marks, _ = server.render(
        {"items": [text("   "), mark(1), text(""), text("0.3@16000")]}
    )

    assert synth == [("English", "0.3@16000")]
    assert marks == {"1": 0.0}
    assert len(pcm) == int(0.3 * 16000)


def test_without_text_the_rate_is_22050(synth):
    pcm, sr, marks, _ = server.render({"items": [pause(100), mark(1)]})
    assert (sr, len(pcm), marks) == (22050, 2205, {"1": 0.1})

    pcm, sr, marks, _ = server.render({"items": []})
    assert (sr, len(pcm), marks) == (22050, 0, {})


def test_the_request_selects_the_language(synth):
    _, _, _, used = server.render({"language": "French", "items": [text("0.1@22050")]})

    assert used == "fr_FR-siwis-medium"
    assert synth == [("French", "0.1@22050")]


@pytest.fixture(autouse=True)
def no_cancelled_says():
    server._cancelled.clear()
    yield
    server._cancelled.clear()


def test_a_stop_naming_the_say_cancels_it_between_items(synth, monkeypatch):
    """The stop arrives while the first item is being synthesized: the second item is never
    synthesized and the say is reported stopped."""
    real = server.synth_piper

    def stopping(text, lang, rate, pitch=100):
        server.stop_say(7)  # the /stop lands during this item's synthesis
        return real(text, lang, rate, pitch)

    monkeypatch.setattr(server, "synth_piper", stopping)
    with pytest.raises(server.Cancelled):
        server.render({"id": 7, "items": [text("0.1@22050"), text("0.2@22050")]})
    assert [t for _, t in synth] == ["0.1@22050"]


def test_a_stop_that_beats_its_say_cancels_it_before_any_synthesis(synth):
    server.stop_say(8)
    with pytest.raises(server.Cancelled):
        server.render({"id": 8, "items": [text("0.1@22050")]})
    assert synth == []


def test_a_stop_names_one_say_only(synth):
    server.stop_say(9)
    pcm, sr, _, _ = server.render({"id": 10, "items": [text("0.1@22050")]})
    assert len(pcm) == 2205 and sr == 22050
    pcm, _, _, _ = server.render(
        {"items": [text("0.1@22050")]}
    )  # no id: never cancelled
    assert len(pcm) == 2205


@pytest.fixture
def audio_output(monkeypatch):
    """A stand-in audio output on a free port: the header line of every connection it gets."""
    listener = socket.create_server(("127.0.0.1", 0))
    monkeypatch.setattr(server, "SOUNDCARD", f"127.0.0.1:{listener.getsockname()[1]}")
    headers: list[dict] = []

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn, conn.makefile("rb") as f:
                headers.append(json.loads(f.readline()))
                f.read()

    threading.Thread(target=serve, daemon=True).start()
    yield headers
    listener.close()


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition not met in time"
        time.sleep(0.01)


def test_speech_plays_as_the_speech_stream(audio_output):
    server.stream_to_soundcard(np.zeros(2205, dtype=np.int16), 22050)
    wait_for(lambda: audio_output)

    assert audio_output == [
        {
            "cmd": "play",
            "stream": "speech",
            "rate": 22050,
            "channels": 1,
            "format": "s16le",
        }
    ]


def test_stop_stops_the_speech_stream_only(audio_output):
    server.soundcard_stop()
    wait_for(lambda: audio_output)

    assert audio_output == [{"cmd": "stop", "stream": "speech"}]


def test_a_stopped_say_is_not_streamed(audio_output):
    """Stopped between its last item and the stream (or before): nothing reaches the audio
    output, not even a header."""
    server.stop_say(11)
    server.stream_to_soundcard(np.zeros(22050, dtype=np.int16), 22050, say_id=11)
    time.sleep(0.2)
    assert audio_output == []

    server.stream_to_soundcard(np.zeros(2205, dtype=np.int16), 22050, say_id=12)
    wait_for(lambda: audio_output)
    assert audio_output[0]["cmd"] == "play"  # another say streams as usual
