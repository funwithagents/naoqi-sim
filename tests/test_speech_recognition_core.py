"""ALSpeechRecognition's core with fake NAOqi services and a scripted engine: the statuses and
events in a NAO's order, vocabularies and word spotting, pause and unsubscribe, the dialog's
grammar and callbacks, the methods each version answers (specs/services/speech-recognition.md)."""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import naoqi_sim_speech_recognition_core as core
import pytest

pytestmark = pytest.mark.container_code

LISTEN_ON = [
    ("bip", "begin"),
    ("ALSpeechRecognition/Status", "ListenOn"),
    ("ALSpeechRecognition/IsRunning", True),
    ("ALSpeechRecognition/ActiveListening", True),
    ("leds", "listening"),
]


class Trace:
    """One ordered list of what the module did: memory events, bips, LEDs, dialog calls."""

    def __init__(self):
        self.items: list[tuple] = []
        self.inserted: dict[str, Any] = {}
        self.changed = threading.Condition()

    def add(self, item):
        with self.changed:
            self.items.append(item)
            self.changed.notify_all()

    def wait(self, predicate: Callable[[list], bool], timeout=3.0):
        with self.changed:
            assert self.changed.wait_for(lambda: predicate(self.items), timeout), (
                self.items
            )


class Memory:
    def __init__(self, trace):
        self.trace = trace

    def insert(self, key, value):
        self.trace.inserted[key] = value

    def raise_event(self, key, value):
        self.trace.add((key, value))


class Engine:
    """Scripted: each audio buffer gets the next reply; `start` records the phrases."""

    url = "http://asr:8080"

    def __init__(self, trace):
        self.trace = trace
        self.sessions: list[tuple] = []
        self.replies: list[dict] = []
        self.buffers: list[bytes] = []

    def start(self, language, phrases, spotting):
        self.sessions.append((language, list(phrases), spotting))
        return {"phrases": len(phrases), "dropped": []}

    def audio(self, pcm):
        self.buffers.append(pcm)
        return self.replies.pop(0) if self.replies else {"speech": False, "final": None}

    def stop(self):
        self.trace.add(("engine", "stop"))


class Feedback:
    def __init__(self, trace):
        self.trace = trace

    def begin_bip(self):
        self.trace.add(("bip", "begin"))

    def end_bip(self):
        self.trace.add(("bip", "end"))

    def listening(self):
        self.trace.add(("leds", "listening"))

    def heard(self, recognised):
        self.trace.add(("leds", "green" if recognised else "off"))

    def idle(self):
        self.trace.add(("leds", "idle"))

    def start_eyes(self):
        self.trace.add(("leds", "eyes on"))


class Dialog:
    """ALDialog's two callbacks; the second blocks while `answering` is set, as the real one
    returns once its answer has been said."""

    def __init__(self, trace):
        self.trace = trace
        self.answering = threading.Event()
        self.released = threading.Event()
        self.released.set()

    def wordsRecognizedCallback(self, value, words):
        self.trace.add(("dialog", "words", value, words))

    def endOfUtteranceCallback(self):
        self.answering.set()
        self.released.wait(5)
        self.answering.clear()
        self.trace.add(("dialog", "end"))
        return False


class Rig:
    def __init__(
        self, version, installed=("English", "French"), engine=True, sentences=None
    ):
        self.trace = Trace()
        self.engine = Engine(self.trace) if engine else None
        self.dialog = Dialog(self.trace)
        self.callback: Callable | None = None
        self.listened = threading.Event()
        self.rec = core.Recognition(
            version,
            Memory(self.trace),
            self.engine,
            self._listen,
            self._unlisten,
            Feedback(self.trace),
            lambda: self.dialog,
            sentences=sentences,
            installed=installed,
            log=lambda msg: None,
        )

    def _listen(self, callback):
        self.callback = callback
        self.listened.set()

    def _unlisten(self):
        self.callback = None
        self.listened.clear()

    def hear(self, *replies):
        """The engine answers these to the next buffers; a buffer is sent for each."""
        assert self.listened.wait(2) and self.engine is not None
        self.engine.replies.extend(replies)
        for _ in replies:
            assert self.callback is not None
            self.callback(1, 1365, [0, 0], b"\0\0" * 1365)

    def since(self, mark: int) -> list[tuple]:
        return self.trace.items[mark:]

    def mark(self) -> int:
        return len(self.trace.items)

    def close(self):
        self.dialog.released.set()
        self.rec.close()


@pytest.fixture(autouse=True)
def no_guard(monkeypatch):
    monkeypatch.setattr(core, "GUARD_S", 0.0)


@pytest.fixture
def rig():
    rigs: list[Rig] = []

    def make(version="2.1", **kw) -> Rig:
        r = Rig(version, **kw)
        rigs.append(r)
        return r

    yield make
    for r in rigs:
        r.close()


SPEECH = {"speech": True, "final": None}


def final(phrase, confidence=0.9):
    return {
        "speech": False,
        "final": {"phrase": phrase, "confidence": confidence, "text": phrase},
    }


def test_subscribe_returns_listening_after_the_begin_bip(rig):
    r = rig("2.1")
    assert r.trace.inserted["ALSpeechRecognition/Status"] == "Idle"
    r.rec.set_vocabulary(["yes", "no"], False)
    r.rec.subscribe("Test")  # returns once the statuses are raised, as the robot's
    assert r.trace.items == LISTEN_ON
    assert r.engine.sessions[-1] == ("English", ["yes", "no"], False)
    assert r.rec.subscribers_info() == [["Test", 30, 0.0]]


def test_a_recognition_raises_a_naos_sequence_then_listens_again(rig):
    r = rig("2.1")
    r.rec.set_vocabulary(["yes", "no"], False)
    r.rec.subscribe("Test")
    m = r.mark()
    r.hear(SPEECH, final("yes", 0.83))
    r.trace.wait(
        lambda items: items[-1] == ("leds", "listening") and len(items) > m + 10
    )
    assert r.since(m) == [
        ("SpeechDetected", 1),
        ("ALSpeechRecognition/Status", "SpeechDetected"),
        ("SpeechDetected", 0),
        ("ALSpeechRecognition/Status", "ListenOff"),
        ("bip", "end"),
        ("ALSpeechRecognition/ActiveListening", False),
        ("leds", "green"),
        ("WordRecognizedAndGrammar", ["yes", 0.83, "modifiable_grammar"]),
        ("WordRecognized", ["yes", 0.83]),
        ("LastWordRecognized", ["yes", 0.83]),
        ("RecoLatency", r.since(m)[10][1]),
        ("ALSpeechRecognition/Status", "EndOfProcess"),
        ("SpeechRecognition/endOfProcess", 1),
        ("bip", "begin"),
        ("ALSpeechRecognition/Status", "ListenOn"),
        ("ALSpeechRecognition/ActiveListening", True),  # IsRunning was already true
        ("leds", "listening"),
    ]
    assert len(r.engine.sessions) == 2  # a fresh session for the next utterance


def test_speech_that_is_no_phrase_raises_no_word(rig):
    r = rig("2.1")
    r.rec.set_vocabulary(["yes"], False)
    r.rec.subscribe("Test")
    m = r.mark()
    r.hear(SPEECH, final(""))
    r.trace.wait(
        lambda items: items[-1] == ("leds", "listening") and len(items) > m + 5
    )
    keys = [k for k, *_ in r.since(m)]
    assert "WordRecognized" not in keys and "WordRecognizedAndGrammar" not in keys
    assert ("ALSpeechRecognition/Status", "EndOfProcess") in r.since(m)
    assert ("leds", "off") in r.since(m)


def test_word_spotting_marks_both_sides_and_names_its_grammar(rig):
    r = rig("2.1")
    r.rec.set_vocabulary(["yes"], True)
    r.rec.subscribe("Test")
    assert r.engine.sessions[-1][2] is True
    m = r.mark()
    r.hear(final("yes", 0.5))
    r.trace.wait(lambda items: any(k == "WordRecognized" for k, *_ in items[m:]))
    assert (
        "WordRecognizedAndGrammar",
        ["<...> yes <...>", 0.5, "modifiable_grammar_wordspotting"],
    ) in r.since(m)


def test_unsubscribe_resets_the_words_and_stops_running(rig):
    r = rig("2.1")
    r.rec.subscribe("Test")
    m = r.mark()
    r.rec.unsubscribe("Test")
    assert r.since(m) == [
        ("SpeechDetected", 0),
        ("RecoLatency", 0),
        ("NoiseRecognized", 0),
        ("WordRecognized", ["", -3.0]),
        ("WordRecognizedAndGrammar", ["", -3.0, ""]),
        ("ALSpeechRecognition/Status", "Stop"),
        ("ALSpeechRecognition/Status", "ListenOff"),
        ("bip", "end"),
        ("ALSpeechRecognition/ActiveListening", False),
        ("ALSpeechRecognition/IsRunning", False),
        ("leds", "idle"),
        ("engine", "stop"),
    ]
    assert not r.listened.is_set()  # the microphones are let go


def test_pause_stops_and_resumes_listening_but_keeps_running(rig):
    r = rig("2.1")
    r.rec.subscribe("Test")
    m = r.mark()
    r.rec.pause(True)
    assert r.since(m) == [
        ("SpeechDetected", 0),
        ("ALSpeechRecognition/Status", "Stop"),
        ("ALSpeechRecognition/Status", "ListenOff"),
        ("bip", "end"),
        ("ALSpeechRecognition/ActiveListening", False),
        ("leds", "idle"),
        ("engine", "stop"),
    ]
    m = r.mark()
    r.rec.pause(False)
    assert r.since(m) == [
        x for x in LISTEN_ON if x[0] != "ALSpeechRecognition/IsRunning"
    ]


def test_the_vocabulary_cannot_change_while_listening_but_can_while_paused(rig):
    r = rig("2.1")
    r.rec.subscribe("Test")
    with pytest.raises(RuntimeError, match="You need to stop or pause the ASR engine"):
        r.rec.set_vocabulary(["yes"], False)
    r.rec.pause(True)
    r.rec.set_vocabulary(["yes"], False)
    r.rec.pause(False)
    assert r.engine.sessions[-1][1] == ["yes"]


def test_without_the_audio_expression_no_bip_is_played(rig):
    r = rig("2.1")
    r.rec.audio_expression = False
    r.rec.visual_expression = False
    r.rec.subscribe("Test")
    r.rec.unsubscribe("Test")
    assert not any(k in ("bip", "leds") for k, *_ in r.trace.items)


def test_languages_are_the_installed_ones_the_engine_has(rig):
    r = rig("2.1", installed=("German", "French"))
    assert r.rec.languages == ["French"] and r.rec.language == "French"
    with pytest.raises(
        RuntimeError, match="does not support the following language: German"
    ):
        r.rec.set_language("German")
    assert r.rec.language == "French"
    deaf = rig("2.1", installed=("Japanese",))
    deaf.rec.subscribe("Test")  # nothing to listen in: no listening
    assert deaf.trace.items == []


def test_parameters_are_the_robots(rig):
    r21, r28 = rig("2.1"), rig("2.8")
    assert r21.rec.get_parameter("Sensitivity") == 0.5
    r21.rec.set_parameter("Sensitivity", 0.7)
    assert r21.rec.get_parameter("Sensitivity") == 0.7
    with pytest.raises(
        RuntimeError, match="This engine does not support NbHypotheses setting"
    ):
        r21.rec.get_parameter("NbHypotheses")
    r28.rec.set_parameter("NbHypotheses", 1.0)  # the 2.8 dialog sets it
    with pytest.raises(RuntimeError, match="does not support Timeout setting"):
        r28.rec.set_parameter("Timeout", 3000)
    assert r21.rec.get_context_param("ctx", "AccuracyRatio") == 1.0


BNF = """#BNF+EMV1.1;
!grammar "BNFtestEnglish";
!start <start>;
!slot<robotname>;
!activatable<greet trig>;
!activatable<other trig>;
<start>:<greet trig>|<other trig>;
<greet trig>:<r1>;
<other trig>:<r2>;
<r1>:hello <robotname>;
<r2>:goodbye;
"""


def test_the_21_dialogs_grammar_is_compiled_and_its_active_rules_listened_for(
    rig, tmp_path: Path
):
    r = rig("2.1")
    bnf, lcf = tmp_path / "BNFtestEnglish.bnf", tmp_path / "BNFtestEnglish.lcf"
    bnf.write_text(BNF)
    # what the dialog calls, in its order (measured)
    r.rec.compile(str(bnf), str(lcf), "English")
    assert lcf.exists()  # the dialog finds the file it expects
    r.rec.remove_all_contexts()
    r.rec.add_context(str(lcf), "BNFtestEnglish")
    r.rec.deactivate_all_rules("BNFtestEnglish")
    r.rec.add_word_list_to_slot("BNFtestEnglish", "robotname", ["nao"])
    r.rec.activate_rule("BNFtestEnglish", "start")
    r.rec.activate_rule("BNFtestEnglish", "greet trig")
    r.rec.subscribe("ALDialogWordRecognized", 30, 0.0)
    assert r.engine.sessions[-1] == ("English", ["hello nao"], False)

    m = r.mark()
    r.dialog.released.clear()  # the dialog is saying its answer until released
    r.hear(SPEECH, final("hello nao", 0.7))
    assert r.dialog.answering.wait(2)
    # meanwhile the microphones hear the robot's answer: nothing of it is listened to
    heard_before = len(r.engine.buffers)
    if r.callback is not None:
        r.callback(1, 1365, [0, 0], b"\1\0" * 1365)
    r.dialog.released.set()
    r.trace.wait(
        lambda items: (
            items[-1] == ("leds", "listening") and ("dialog", "end") in items[m:]
        )
    )
    assert ("dialog", "words", ["hello nao", 0.7, "BNFtestEnglish"], 2) in r.since(m)
    assert (
        "WordRecognizedAndGrammar",
        ["hello nao", 0.7, "BNFtestEnglish"],
    ) in r.since(m)
    time.sleep(0.1)
    assert len(r.engine.buffers) == heard_before
    # listening again comes after the answer, never during it
    after = r.since(m)
    assert after.index(("dialog", "end")) < after.index(
        ("ALSpeechRecognition/Status", "ListenOn")
    )


def test_the_28_dialogs_topics_are_listened_for_through_their_sentences(rig):
    asked: list[tuple] = []

    def sentences(topic, language):
        asked.append((topic, language))
        return {"greet": ["hello robot", "my name is <...>"], "other": ["goodbye"]}.get(
            topic
        )

    r = rig("2.8", sentences=sentences)
    r.rec.create_context_set([], "SLM")
    r.rec.create_context(
        "/home/nao/.local/share/dialog/BNFwelcomeEnglish.lcf", "BNFwelcomeEnglish"
    )
    r.rec.deactivate_all_rules("BNFwelcomeEnglish")
    r.rec.activate_rule("BNFwelcomeEnglish", "start")
    r.rec.activate_rule("BNFwelcomeEnglish", "greet trig")
    r.rec.activate_rule(
        "BNFwelcomeEnglish", "lexicon_enu trig"
    )  # a word library: skipped
    r.rec.create_context_set(["BNFwelcomeEnglish"], "BNF")
    assert r.rec.get_context_sets() == ["BNF", "SLM"]
    r.rec.subscribe("ALDialogWordRecognized")
    # the sentences come from another thread: the session opens again once they are there
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and r.engine.sessions[-1][1] == []:
        time.sleep(0.02)
    assert r.engine.sessions[-1] == (
        "English",
        ["hello robot", "my name is <...>"],
        False,
    )
    assert asked == [("greet", "English")]
    # 2.8 plays and lights nothing by itself: a NAO 6's feedback application does
    assert not any(k in ("bip", "leds") for k, *_ in r.trace.items)

    m = r.mark()
    r.hear(final("hello robot", 1.0))
    r.trace.wait(lambda items: ("dialog", "end") in items[m:])
    assert ("dialog", "words", ["hello robot", 1.0, "BNFwelcomeEnglish"], 2) in r.since(
        m
    )


def test_without_an_engine_the_statuses_follow_and_the_microphones_stay_free(rig):
    r = rig("2.1", engine=False)
    r.rec.subscribe("Test")
    assert ("ALSpeechRecognition/Status", "ListenOn") in r.trace.items
    time.sleep(0.3)
    assert not r.listened.is_set()


# The methods the dialog calls (measured with a recording module, Nov 2026): a missing one stops
# the dialog without a word.
DIALOG_21 = [
    "pause",
    "getAudioExpression",
    "setAudioExpression",
    "getLanguage",
    "setLanguage",
    "getAvailableLanguages",
    "compile",
    "addContext",
    "removeContext",
    "removeAllContext",
    "pushContexts",
    "popContexts",
    "setContextParam",
    "activateRule",
    "deactivateRule",
    "deactivateAllRules",
    "addWordListToSlot",
    "_enableAudioLogging",
    "_enableFreeSpeechToText",
    "_disableFreeSpeechToText",
    "_isFreeSpeechToTextAvailable",
    "_remoteConsumptionOk",
    "_getVersion",
    "subscribe",
    "unsubscribe",
    "setVisualExpressionMode",
]
DIALOG_28 = [
    "pause",
    "getAudioExpression",
    "setAudioExpression",
    "getLanguage",
    "setLanguage",
    "getAvailableLanguages",
    "addContext",
    "removeContext",
    "removeAllContext",
    "setContextParam",
    "activateRule",
    "deactivateRule",
    "deactivateAllRules",
    "addWordListToSlot",
    "_enableAudioLogging",
    "_enableFreeSpeechToText",
    "_disableFreeSpeechToText",
    "_isFreeSpeechToTextAvailable",
    "_remoteConsumptionOk",
    "createContext",
    "deleteContext",
    "getContexts",
    "createContextSet",
    "addContextSet",
    "addContextToSet",
    "removeContextFromSet",
    "removeContextSet",
    "eraseContextSet",
    "deleteAllContextSets",
    "getContextSets",
    "activateAllRules",
    "setParameter",
    "setVisualExpression",
    "subscribe",
    "unsubscribe",
    "_connectRemote",
    "_disconnectRemote",
    "_enableBeamformer",
    "_disableBeamformer",
    "_playBipStart",
    "_playBipStop",
    "_startEyesRotation",
    "_stopEyesRotation",
    "_startEarsRotation",
    "_stopEarsRotation",
]


@pytest.mark.parametrize(
    ("version", "called"), [("2.1", DIALOG_21), ("2.8", DIALOG_28)]
)
def test_every_method_the_dialog_calls_is_answered(version, called):
    names = [name for name, *_ in core.methods(version)]
    assert sorted(set(called) - set(names)) == []
    assert len(names) == len(set(names))
    versions = {name: handler for name, _, _, handler in core.methods(version)}
    assert versions["_getVersion"](None) == core.VERSIONS[version]


def test_the_engine_client_reports_silence_when_unreachable():
    logged: list[str] = []
    engine = core.Engine("http://127.0.0.1:9", timeout=0.2, log=logged.append)
    assert engine.start("English", ["yes"], False) is None
    assert engine.audio(b"\0\0") is None
    assert len(logged) == 1  # once per run of failures
    assert core.Engine("", log=logged.append).audio(b"\0\0") is None


def test_the_bips_are_short_tones(tmp_path: Path):
    import wave

    path = core.write_bip(str(tmp_path / "bip.wav"), 900.0, 1500.0)
    with wave.open(path) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000
        assert abs(w.getnframes() / 16000 - core.BIP_S) < 0.001
