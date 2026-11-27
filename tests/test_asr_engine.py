"""The speech recognition engine's sessions and HTTP plumbing with a fake model and a scripted
recogniser (no Vosk, no network), and the recipe's pins (specs/container/asr-engine.md)."""

import hashlib
import importlib.util
import io
import json
import re
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from naoqi_sim.config import LANGUAGES, SPEECH_LANGUAGES, RobotSettings

_ENGINE = Path(__file__).resolve().parent.parent / "docker" / "asr-engine"


def _load_server() -> Any:
    # By path: the other engines' server.py also want the name `server`.
    spec = importlib.util.spec_from_file_location("asr_server", _ENGINE / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_server()


class ScriptedRecognizer:
    """Plays a script, one step per buffer: ("partial", text) while hearing, ("silence",) for
    nothing, ("final", text, [confidences]) to end an utterance with that text."""

    def __init__(self, grammar, script):
        self.grammar = grammar
        self.script = list(script)
        self.buffers: list[bytes] = []
        self._step: tuple = ("silence",)

    def AcceptWaveform(self, pcm):
        self.buffers.append(pcm)
        self._step = self.script.pop(0) if self.script else ("silence",)
        return self._step[0] == "final"

    def PartialResult(self):
        text = self._step[1] if self._step[0] == "partial" else ""
        return json.dumps({"partial": text})

    def Result(self):
        _, text, confidences = self._step
        words = [{"word": w, "conf": c} for w, c in zip(text.split(), confidences)]
        return json.dumps({"text": text, "result": words})


class FakeModel:
    """Knows the words given; every recogniser it builds plays `script`."""

    def __init__(self, words, script=()):
        self.words = set(words)
        self.script = list(script)
        self.recognizers: list[ScriptedRecognizer] = []

    def knows(self, word):
        return word in self.words

    def recognizer(self, phrases):
        rec = ScriptedRecognizer(phrases + [server.UNKNOWN], self.script)
        self.recognizers.append(rec)
        return rec


WORDS = [
    "hello",
    "robot",
    "what",
    "time",
    "is",
    "it",
    "je",
    "veux",
    "une",
    "pomme",
    "quelle",
    "heure",
    "est",
    "il",
    "yes",
    "no",
]


def _session(script, phrases=("hello robot", "what time is it"), spotting=False):
    model = FakeModel(WORDS, script)
    return server.Session(model, list(phrases), spotting), model


def test_each_language_pack_has_a_recognition_model():
    """The config's languages are the ones with a voice and a model: the engine has the models
    of exactly those (Danish, Finnish and Norwegian have a voice only), each hash-pinned."""
    assert tuple(server.MODELS) == LANGUAGES
    assert set(LANGUAGES) == set(SPEECH_LANGUAGES) - {"Danish", "Finnish", "Norwegian"}
    assert set(server.MODEL_SHA256) == set(server.MODELS.values())
    assert (
        server.MODELS["Portuguese"] == server.MODELS["Brazilian"]
    )  # no model of its own
    assert server.DEFAULT_LANGUAGES == RobotSettings().available_languages


def test_the_installed_languages_are_named_once_each_and_need_a_model():
    assert server.installed_languages("German, English ,German") == (
        "German",
        "English",
    )
    assert server.installed_languages("") == server.DEFAULT_LANGUAGES
    with pytest.raises(ValueError, match="no model for Danish"):
        server.installed_languages("English,Danish")


# -- models: the image, the volume, a first use's download -------------------------


@pytest.fixture
def model_roots(tmp_path, monkeypatch):
    """An image root and a volume root for the models, both empty."""
    builtin, volume = tmp_path / "builtin", tmp_path / "volume"
    monkeypatch.setattr(server, "BUILTIN_DIR", str(builtin))
    monkeypatch.setattr(server, "MODEL_DIR", str(volume))
    return builtin, volume


def put_model(root: Path, name: str) -> Path:
    (root / name / "conf").mkdir(parents=True)
    return root / name


def archive(name: str) -> bytes:
    """A model's archive as the model site serves it: one folder named after the model."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{name}/conf/model.conf", "--min-active=200\n")
        z.writestr(f"{name}/am/final.mdl", b"weights")
    return buffer.getvalue()


@pytest.fixture
def model_site(monkeypatch):
    """A fake model site: the URLs fetched, each answered with the model's archive, whose hash
    the engine is pinned to."""
    urls: list[str] = []
    archives: dict[str, bytes] = {}

    def urlopen(url, timeout=0):
        urls.append(url)
        name = url.rsplit("/", 1)[1].removesuffix(".zip")
        return io.BytesIO(archives.setdefault(name, archive(name)))

    pins = {
        name: hashlib.sha256(archive(name)).hexdigest() for name in server.MODEL_SHA256
    }
    monkeypatch.setattr(server, "MODEL_SHA256", pins)
    monkeypatch.setattr(server.urllib.request, "urlopen", urlopen)
    return urls, archives


def test_a_model_in_the_image_is_never_fetched(model_roots, model_site):
    builtin, _ = model_roots
    path = put_model(builtin, server.MODELS["English"])
    assert server.ensure_model("English") == str(path)
    assert model_site[0] == []


def test_a_model_the_volume_has_is_reused(model_roots, model_site):
    _, volume = model_roots
    path = put_model(volume, server.MODELS["German"])
    assert server.ensure_model("German") == str(path)
    assert model_site[0] == []


def test_a_missing_model_is_fetched_into_the_volume_checked_and_unpacked(
    model_roots, model_site
):
    _, volume = model_roots
    name = server.MODELS["Spanish"]
    path = server.ensure_model("Spanish")
    assert model_site[0] == [f"https://alphacephei.com/vosk/models/{name}.zip"]
    assert path == str(volume / name)
    assert (volume / name / "am" / "final.mdl").read_bytes() == b"weights"
    assert sorted(p.name for p in volume.iterdir()) == [
        name
    ]  # no archive, no temp folder
    assert server.ensure_model("Spanish") == path and len(model_site[0]) == 1


def test_a_model_with_the_wrong_hash_is_refused_and_leaves_nothing(
    model_roots, model_site
):
    _, volume = model_roots
    name = server.MODELS["Italian"]
    model_site[1][name] = archive(name) + b"tampered"
    with pytest.raises(ValueError, match=f"{name}.zip has SHA-256"):
        server.ensure_model("Italian")
    assert list(volume.iterdir()) == []


def test_a_download_that_dies_leaves_no_half_model(model_roots, monkeypatch):
    _, volume = model_roots

    class Dies(io.BytesIO):
        def read(self, size=-1, /):
            raise OSError("connection reset")

    monkeypatch.setattr(server.urllib.request, "urlopen", lambda url, timeout=0: Dies())
    with pytest.raises(OSError):
        server.ensure_model("Russian")
    assert list(volume.iterdir()) == []


def test_the_installed_languages_models_are_loaded_once_each(model_roots, model_site):
    """Portuguese and Brazilian share one model, loaded once; English comes from the image."""
    builtin, _ = model_roots
    put_model(builtin, server.MODELS["English"])
    loaded: list[str] = []

    class Loaded:
        def __init__(self, path):
            loaded.append(Path(path).name)

    models = server.load_models(("English", "Brazilian", "Portuguese"), Loaded)
    assert list(models) == ["English", "Brazilian", "Portuguese"]
    assert models["Brazilian"] is models["Portuguese"]
    assert loaded == [server.MODELS["English"], server.MODELS["Brazilian"]]
    assert model_site[0] == [
        f"https://alphacephei.com/vosk/models/{server.MODELS['Brazilian']}.zip"
    ]


def test_phrases_are_normalised_and_those_with_unknown_words_dropped():
    session, model = _session(
        [], ["Hello, Robot!", "Quelle heure est-il ?", "hello robot", "bonjour kiwi"]
    )
    assert sorted(session.phrases) == ["hello robot", "quelle heure est il"]
    assert session.dropped == ["bonjour kiwi"]
    # the recogniser gets each phrase once, normalised, and the unknown-speech token
    assert model.recognizers[0].grammar == [
        "hello robot",
        "quelle heure est il",
        "[unk]",
    ]


def test_an_utterance_equal_to_a_phrase_gives_the_phrase_as_given_and_its_lowest_confidence():
    session, _ = _session(
        [
            ("partial", "hello"),
            ("partial", "hello robot"),
            ("final", "hello robot", [0.9, 0.7]),
        ],
        phrases=["Hello robot"],
    )
    replies = [session.feed(b"\0\0") for _ in range(3)]
    assert [r["speech"] for r in replies] == [True, True, False]
    assert replies[0]["final"] is None and replies[1]["final"] is None
    assert replies[2]["final"] == {
        "phrase": "Hello robot",
        "confidence": 0.7,
        "text": "hello robot",
        "lead": False,
        "trail": False,
    }


@pytest.mark.parametrize(
    "heard",
    [
        "hello what",  # a mix of the list's words
        "[unk] hello robot",  # unknown speech before, without word spotting
        "hello robot [unk]",
        "hello [unk] robot",
        "[unk]",
    ],
)
def test_anything_not_equal_to_a_phrase_is_unknown_speech(heard):
    session, _ = _session([("partial", heard), ("final", heard, [1.0] * 4)])
    session.feed(b"\0\0")
    final = session.feed(b"\0\0")["final"]
    assert final["phrase"] == "" and final["confidence"] == 0.0
    assert final["text"] == heard


def test_word_spotting_allows_unknown_speech_around_a_phrase_and_says_where():
    session, _ = _session(
        [("final", "[unk] what time is it [unk]", [1.0, 0.8, 0.8, 0.8, 0.8, 1.0])],
        spotting=True,
    )
    final = session.feed(b"\0\0")["final"]
    assert final["phrase"] == "what time is it"
    assert final["lead"] and final["trail"]
    assert final["confidence"] == 0.8


def test_word_spotting_finds_a_phrase_among_words_of_the_list_heard_around_it():
    # measured on a real voice: "tell me what time is it please" with only "what time is it"
    # in the list, "please" heard as "is"
    session, _ = _session(
        [("final", "[unk] what time is it is", [1.0, 0.9, 0.9, 0.6, 0.9, 0.3])],
        spotting=True,
    )
    final = session.feed(b"\0\0")["final"]
    assert final["phrase"] == "what time is it"
    assert final["lead"] and final["trail"]
    assert final["confidence"] == 0.6  # the phrase's own words, not the stray "is"


def test_without_word_spotting_words_of_the_list_around_a_phrase_reject_it():
    session, _ = _session([("final", "what time is it is", [1.0] * 5)])
    assert session.feed(b"\0\0")["final"]["phrase"] == ""


def test_word_spotting_prefers_the_longest_phrase_heard():
    session, _ = _session(
        [("final", "[unk] hello robot what time is it", [1.0] * 7)],
        phrases=["hello robot", "what time is it", "robot"],
        spotting=True,
    )
    final = session.feed(b"\0\0")["final"]
    assert final["phrase"] == "what time is it"
    assert final["lead"] and not final["trail"]


def test_a_phrase_with_markers_allows_unknown_speech_only_where_it_has_them():
    phrases = ["<...> hello robot", "what time is it <...>"]
    for heard, expected in [
        ("[unk] hello robot", "<...> hello robot"),
        ("hello robot [unk]", ""),
        ("what time is it [unk]", "what time is it <...>"),
        ("[unk] what time is it", ""),
    ]:
        session, _ = _session([("final", heard, [1.0] * 6)], phrases=phrases)
        assert session.feed(b"\0\0")["final"]["phrase"] == expected, heard


def test_silence_ends_no_utterance_but_speech_that_fades_out_does():
    session, _ = _session(
        [("silence",), ("final", "", []), ("partial", "[unk]"), ("final", "", [])]
    )
    assert session.feed(b"\0\0") == {"speech": False, "final": None}
    assert session.feed(b"\0\0") == {
        "speech": False,
        "final": None,
    }  # Vosk's empty segment
    assert session.feed(b"\0\0") == {"speech": True, "final": None}
    final = session.feed(b"\0\0")["final"]  # something was heard: it must end
    assert final is not None and final["phrase"] == ""


# --- HTTP -----------------------------------------------------------------------------------


@pytest.fixture
def engine():
    server.set_models(None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        server.set_models(None)


def _request(url, path, body=None, json_body=None):
    headers = {}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url + path, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_is_503_until_the_models_are_loaded_then_names_the_languages(engine):
    assert _request(engine, "/health") == (
        503,
        {"ok": False, "languages": list(server.LANGUAGES)},
    )
    server.set_models({"French": FakeModel(WORDS), "German": FakeModel(WORDS)})
    assert _request(engine, "/health") == (
        200,
        {
            "ok": True,
            "recognizer": "vosk",
            "languages": ["French", "German"],
            "models": {
                "French": "vosk-model-small-fr-0.22",
                "German": "vosk-model-small-de-0.15",
            },
        },
    )


def test_a_session_over_http_hears_a_phrase_then_stop_forgets_it(engine):
    model = FakeModel(WORDS, [("partial", "yes"), ("final", "yes", [0.95])])
    server.set_models({"English": model})
    status, reply = _request(
        engine,
        "/start",
        json_body={"language": "English", "phrases": ["yes", "no", "maybe"]},
    )
    assert status == 200
    assert reply["phrases"] == 2 and reply["dropped"] == ["maybe"]
    assert _request(engine, "/audio", b"\1\0" * 160) == (
        200,
        {"speech": True, "final": None},
    )
    status, reply = _request(engine, "/audio", b"\1\0" * 160)
    assert reply["final"]["phrase"] == "yes" and reply["final"]["confidence"] == 0.95
    assert model.recognizers[0].buffers == [b"\1\0" * 160] * 2
    assert _request(engine, "/stop", b"")[0] == 200
    assert _request(engine, "/audio", b"\1\0" * 160) == (
        200,
        {"speech": False, "final": None},
    )


def test_a_new_start_forgets_the_previous_session(engine):
    model = FakeModel(WORDS)
    server.set_models({"English": model})
    _request(engine, "/start", json_body={"language": "English", "phrases": ["yes"]})
    _request(engine, "/audio", b"\0\0" * 8)
    _request(engine, "/start", json_body={"language": "English", "phrases": ["no"]})
    _request(engine, "/audio", b"\0\0" * 8)
    assert [r.grammar for r in model.recognizers] == [["yes", "[unk]"], ["no", "[unk]"]]
    assert [len(r.buffers) for r in model.recognizers] == [1, 1]


@pytest.mark.parametrize(
    "path, body, json_body",
    [
        ("/start", None, {"language": "Danish", "phrases": ["ja"]}),
        ("/start", None, {"language": "English", "phrases": "yes"}),
        ("/start", b"not json", None),
        ("/audio", b"\0\0\0", None),  # an odd length is not 16-bit samples
    ],
)
def test_bad_requests_are_400(engine, path, body, json_body):
    server.set_models({"English": FakeModel(WORDS)})
    _request(engine, "/start", json_body={"language": "English", "phrases": []})
    assert _request(engine, path, body, json_body)[0] == 400


def test_a_start_before_the_models_are_loaded_is_503_and_unknown_paths_404(engine):
    assert (
        _request(engine, "/start", json_body={"language": "English", "phrases": []})[0]
        == 503
    )
    assert _request(engine, "/detect", b"")[0] == 404


def test_the_recipe_bakes_the_default_languages_models_hash_checked():
    dockerfile = (_ENGINE / "Dockerfile").read_text()
    assert "vosk==0.3.45" in dockerfile
    assert "sha256sum -c" in dockerfile
    baked = re.findall(r"ARG \w+_MODEL=(\S+)", dockerfile)
    assert baked == [server.MODELS[lang] for lang in server.DEFAULT_LANGUAGES]
    for name in baked:
        assert server.MODEL_SHA256[name] in dockerfile
    # the image's models where the server looks for them first
    assert f"WORKDIR {server.BUILTIN_DIR}" in dockerfile


def test_compose_gives_the_engine_the_languages_and_the_shared_language_packs_volume():
    compose = (_ENGINE.parent / "compose.yaml").read_text()
    section = compose[compose.index("  asr:") : compose.index("  naoqi21:")]
    tts = compose[compose.index("  tts:") : compose.index("  perception:")]
    assert "naoqi-sim/asr:dev" in section and "/health" in section
    assert "NAOQI_SIM_LANGUAGES: ${NAOQI_SIM_LANGUAGES:-English,French}" in section
    # one volume for the voices and the models, at the root both engines' folders are under
    assert "- language-packs:/language-packs" in section
    assert "- language-packs:/language-packs" in tts
    assert server.MODEL_DIR == "/language-packs/asr-models"
    # one volume for both NAOqi versions: no per-version name
    volumes = compose[compose.index("\nvolumes:") :]
    assert "  language-packs:\n" in volumes and "name:" not in volumes
    assert compose.count("${NAOQI_SIM_ASR_URL-http://asr:8080}") == 2
