"""The speech recognition engine's sessions and HTTP plumbing with a fake model and a scripted
recogniser (no Vosk, no network), and the recipe's pins (specs/container/asr-engine.md)."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

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
    assert _request(engine, "/health") == (503, {"ok": False})
    server.set_models({"English": FakeModel(WORDS), "French": FakeModel(WORDS)})
    assert _request(engine, "/health") == (
        200,
        {"ok": True, "recognizer": "vosk", "languages": ["English", "French"]},
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
        ("/start", None, {"language": "German", "phrases": ["ja"]}),
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


def test_the_recipe_pins_vosk_and_the_models_hashes_and_compose_checks_its_health():
    dockerfile = (_ENGINE / "Dockerfile").read_text()
    assert "vosk==0.3.45" in dockerfile
    assert (
        "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498" in dockerfile
    )
    assert (
        "cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad" in dockerfile
    )
    assert "sha256sum -c" in dockerfile
    for name in server.MODELS.values():
        assert name in dockerfile
    compose = (_ENGINE.parent / "compose.yaml").read_text()
    section = compose[compose.index("  asr:") : compose.index("  naoqi21:")]
    assert "naoqi-sim/asr:dev" in section and "/health" in section
    assert compose.count("${NAOQI_SIM_ASR_URL-http://asr:8080}") == 2
