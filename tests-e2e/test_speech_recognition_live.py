"""ALSpeechRecognition on a running naoqi-sim stack (specs/services/speech-recognition.md): sentences
from tests-e2e/speech/ (synthesised once, committed) played into the fake room, recognised for a
script's vocabulary and for a dialog topic loaded by hand, on both versions."""

import threading
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

SUBSCRIBER = "test_speech_recognition_live"
STATUS = "ALSpeechRecognition/Status"
SPEECH = Path(__file__).parent / "speech"
# The methods a dialog calls on the module, hidden ones included (measured with a recording
# module): a missing one stops the dialog without a word, so each must be there.
DIALOG_CALLS = {
    "2.1": [
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
        "setVisualExpressionMode",
        "subscribe",
        "unsubscribe",
        "_enableAudioLogging",
        "_enableFreeSpeechToText",
        "_disableFreeSpeechToText",
        "_isFreeSpeechToTextAvailable",
        "_remoteConsumptionOk",
        "_getVersion",
    ],
    "2.8": [
        "pause",
        "getAudioExpression",
        "setAudioExpression",
        "getLanguage",
        "setLanguage",
        "getAvailableLanguages",
        "removeAllContext",
        "setContextParam",
        "activateRule",
        "deactivateRule",
        "deactivateAllRules",
        "addWordListToSlot",
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
        "_enableAudioLogging",
        "_enableFreeSpeechToText",
        "_disableFreeSpeechToText",
        "_isFreeSpeechToTextAvailable",
        "_remoteConsumptionOk",
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
    ],
}
TOPIC = """topic: ~naoqi_sim_test_reco()
language: enu
u:(hello robot) hello human
u:(what time is it) it is time to test
"""


class Events:
    """Every value of the module's events and the dialog's, in order, with their times."""

    KEYS = (
        "WordRecognized",
        "WordRecognizedAndGrammar",
        "SpeechDetected",
        STATUS,
        "ALSpeechRecognition/IsRunning",
        "Dialog/LastInput",
        "Dialog/Answered",
    )

    def __init__(self, memory):
        self.items: list[tuple[float, str, object]] = []
        self.changed = threading.Condition()
        self._subs = []
        for key in self.KEYS:
            sub = memory.subscriber(key)
            sub.signal.connect(lambda value, key=key: self._add(key, value))
            self._subs.append(sub)

    def _add(self, key, value):
        with self.changed:
            self.items.append((time.monotonic(), key, value))
            self.changed.notify_all()

    def mark(self) -> int:
        with self.changed:
            return len(self.items)

    def since(self, mark: int, key: str | None = None) -> list:
        with self.changed:
            return [v for _, k, v in self.items[mark:] if key is None or k == key]

    def wait(self, mark: int, check: Callable[[list], bool], timeout=10.0, what=""):
        with self.changed:
            ok = self.changed.wait_for(lambda: check(self.items[mark:]), timeout)
        assert ok, f"{what}: {self.items[mark:]}"

    def wait_word(self, mark: int, timeout=10.0) -> None:
        """Until a word came, in both events (two events raised an instant apart may reach a
        subscriber in either order)."""

        def both(items):
            keys = {k for _, k, v in items if k.startswith("WordRecognized") and v[0]}
            return keys == {"WordRecognized", "WordRecognizedAndGrammar"}

        self.wait(mark, both, timeout, what="a word")

    def words(self, mark: int) -> list:
        """The words recognised since `mark`, not the resets."""
        return [v for v in self.since(mark, "WordRecognized") if v[0]]


def _read(path: Path) -> np.ndarray:
    """A sentence's 16 kHz mono WAV, with 0.3 s of silence on each side."""
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (
            16000,
            1,
            2,
        ), path
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    silence = np.zeros(4800, np.int16)
    return np.concatenate([silence, pcm, silence])


@pytest.fixture(scope="session")
def sentences() -> dict[str, np.ndarray]:
    """The test sentences, by text: `english-hello_robot.wav` is "hello robot"."""
    return {
        p.stem.split("-", 1)[1].replace("_", " "): _read(p)
        for p in sorted(SPEECH.glob("*.wav"))
    }


@pytest.fixture
def asr(nao):
    service = nao.service("ALSpeechRecognition")
    yield service
    service.unsubscribe(SUBSCRIBER)
    service.pause(False)
    service.setAudioExpression(True)
    service.setLanguage("English")


@pytest.fixture
def events(nao) -> Events:
    return Events(nao.service("ALMemory"))


def say_to_the_robot(nao, sentences, text: str) -> None:
    """Plays a sentence into the fake room and waits for its end."""
    nao.audio.play(sentences[text], 16000)
    time.sleep(len(sentences[text]) / 16000)


@contextmanager
def listening(asr, phrases, spotting=False) -> Iterator[None]:
    """A script's listening: the vocabulary set while paused (on 2.8 the dialog keeps the module
    subscribed, and a NAO refuses a vocabulary change while it listens), then a subscription."""
    asr.pause(True)
    asr.setVocabulary(phrases, spotting)
    asr.pause(False)
    asr.subscribe(SUBSCRIBER)
    try:
        yield
    finally:
        asr.unsubscribe(SUBSCRIBER)


def in_order(values: list, expected: list) -> bool:
    """`expected` appear in `values` in this order. Only for statuses far enough apart: a qi
    subscriber may receive two events raised within a few milliseconds the other way round (the
    module's own order is the fast tier's to check)."""
    it = iter(values)
    return all(any(v == e for v in it) for e in expected)


def test_a_spoken_phrase_is_recognised_with_a_naos_events(nao, asr, events, sentences):
    with listening(asr, ["hello robot", "what time is it"]):
        mark = events.mark()
        say_to_the_robot(nao, sentences, "what time is it")
        events.wait(
            mark,
            lambda items: any(k == STATUS and v == "ListenOn" for _, k, v in items[3:]),
            what="listening again",
        )
        events.wait_word(mark)
        [(phrase, confidence)] = events.words(mark)
        assert phrase == "what time is it" and 0.0 < confidence <= 1.0
        [grammar] = [v for v in events.since(mark, "WordRecognizedAndGrammar") if v[0]]
        assert grammar == ["what time is it", confidence, "modifiable_grammar"]
        statuses = events.since(mark, STATUS)
        assert in_order(statuses, ["SpeechDetected", "ListenOff"])
        assert {"EndOfProcess", "ListenOn"} <= set(
            statuses[statuses.index("ListenOff") :]
        )
        assert in_order(events.since(mark, "SpeechDetected"), [1, 0])
        assert (
            nao.service("ALMemory").getData("LastWordRecognized")[0]
            == "what time is it"
        )


def test_a_sentence_outside_the_vocabulary_gives_no_word(nao, asr, events, sentences):
    with listening(asr, ["hello robot", "what time is it"]):
        mark = events.mark()
        say_to_the_robot(nao, sentences, "the weather is nice today")
        events.wait(
            mark,
            lambda items: any(v == "EndOfProcess" for _, _, v in items),
            what="the end of the utterance",
        )
        time.sleep(1.0)
        assert events.words(mark) == []
        assert "SpeechDetected" in events.since(mark, STATUS)


def test_word_spotting_finds_a_phrase_inside_a_sentence(nao, asr, events, sentences):
    with listening(asr, ["what time is it"], spotting=True):
        mark = events.mark()
        say_to_the_robot(nao, sentences, "tell me what time is it please")
        events.wait_word(mark)
        [(phrase, _)] = events.words(mark)
        assert phrase == "<...> what time is it <...>"
        [grammar] = [v for v in events.since(mark, "WordRecognizedAndGrammar") if v[0]]
        assert grammar[2] == "modifiable_grammar_wordspotting"


def test_french_is_recognised_in_french(nao, asr, events, sentences):
    assert set(asr.getAvailableLanguages()) == {
        "English",
        "French",
    }  # German has no model
    with pytest.raises(RuntimeError, match="does not support the following language"):
        asr.setLanguage("German")
    asr.setLanguage("French")
    with listening(asr, ["bonjour je voudrais une pomme rouge", "bonjour"]):
        mark = events.mark()
        say_to_the_robot(nao, sentences, "bonjour je voudrais une pomme rouge")
        events.wait_word(mark)
        assert [p for p, _ in events.words(mark)] == [
            "bonjour je voudrais une pomme rouge"
        ]


def test_the_vocabulary_cannot_change_while_listening(nao, asr):
    with (
        listening(asr, ["hello robot"]),
        pytest.raises(RuntimeError, match="stop or pause the ASR engine"),
    ):
        asr.setVocabulary(["what time is it"], False)


def test_pause_stops_the_listening_and_its_end_resumes_it(nao, asr, events, sentences):
    with listening(asr, ["hello robot"]):
        mark = events.mark()
        asr.pause(True)
        assert {"Stop", "ListenOff"} <= set(events.since(mark, STATUS))
        assert nao.service("ALMemory").getData(STATUS) == "ListenOff"
        say_to_the_robot(nao, sentences, "hello robot")
        time.sleep(1.0)
        assert events.words(mark) == []  # paused: deaf
        mark = events.mark()
        asr.pause(False)
        assert events.since(mark, STATUS)[:1] == ["ListenOn"]
        say_to_the_robot(nao, sentences, "hello robot")
        events.wait_word(mark)


def test_unsubscribe_resets_the_words_unless_the_dialog_still_listens(nao, asr, events):
    with listening(asr, ["hello robot"]):
        pass  # unsubscribed on the way out
    others = asr.getSubscribersInfo()
    mark = events.mark()
    asr.subscribe(SUBSCRIBER)
    asr.unsubscribe(SUBSCRIBER)
    if not others:
        # nobody else listens: listening stops, the words are reset, the module stops running
        assert ["", -3.0] in events.since(mark, "WordRecognized")
        assert {"Stop", "ListenOff"} <= set(events.since(mark, STATUS))
        assert nao.service("ALMemory").getData(STATUS) == "ListenOff"
        assert events.since(mark, "ALSpeechRecognition/IsRunning")[-1] is False
    else:
        # 2.8's dialog subscribes the module from boot, as ALDialogWordRecognized (until a
        # dialog's stop unsubscribes it): it goes on listening
        assert [name for name, _, _ in others] == ["ALDialogWordRecognized"]
        assert "Stop" not in events.since(mark, STATUS)
    if nao.version.name == "2.1":
        assert (
            others == []
        )  # the 2.1 dialog subscribes only while a script subscribes it


def test_the_bips_are_played_on_2_1_unless_the_audio_expression_is_off(nao, asr):
    if nao.version.name != "2.1":
        pytest.skip(
            "on 2.8 a NAO's feedback application plays them, through hidden methods"
        )
    after = time.monotonic()
    asr.subscribe(SUBSCRIBER)
    asr.unsubscribe(SUBSCRIBER)
    time.sleep(0.5)
    bips = [
        p for p in nao.sink.playbacks if p.started_at >= after and p.stream != "speech"
    ]
    assert len(bips) == 2 and all(0.08 < p.duration_s < 0.2 for p in bips)
    asr.setAudioExpression(False)
    after = time.monotonic()
    asr.subscribe(SUBSCRIBER)
    asr.unsubscribe(SUBSCRIBER)
    time.sleep(0.5)
    assert [
        p for p in nao.sink.playbacks if p.started_at >= after and p.stream != "speech"
    ] == []


def test_a_hand_loaded_dialog_topic_answers_a_spoken_sentence(
    nao, asr, events, sentences, tmp_path: Path
):
    """The Dialog box's path: a topic loaded, activated, the dialog subscribed; the recognition
    hands the dialog what it heard, and listens again once the answer has been said."""
    dialog = nao.service("ALDialog")
    topic_file = tmp_path / "naoqi_sim_test_reco.top"
    topic_file.write_text(TOPIC)
    nao.container.copy_in(topic_file, "/tmp/naoqi_sim_test_reco.top")
    dialog.setLanguage("English")
    topic = dialog.loadTopic("/tmp/naoqi_sim_test_reco.top")
    try:
        dialog.activateTopic(topic)
        dialog.subscribe(SUBSCRIBER)
        try:
            time.sleep(2.0)  # the dialog gives the recognition its phrases
            mark = events.mark()
            say_to_the_robot(nao, sentences, "hello robot")
            events.wait(
                mark,
                lambda items: any(k == "Dialog/Answered" and v for _, k, v in items),
                timeout=15,
                what="the answer",
            )
            assert "hello robot" in events.since(mark, "Dialog/LastInput")
            assert events.since(mark, "Dialog/Answered")[-1] == "hello human"
            # the robot's own answer was not listened to: listening again after it, one word
            answered = next(
                i
                for i, (_, k, v) in enumerate(events.items)
                if i >= mark and k == "Dialog/Answered" and v
            )
            events.wait(
                answered,
                lambda items: (STATUS, "ListenOn") in [(k, v) for _, k, v in items],
                what="listening again",
            )
            assert [p for p, _ in events.words(mark)] == ["hello robot"]
        finally:
            dialog.unsubscribe(SUBSCRIBER)
            dialog.deactivateTopic(topic)
    finally:
        dialog.unloadTopic(topic)


def test_every_method_the_dialog_calls_is_there(nao, asr):
    for name in DIALOG_CALLS[nao.version.name]:
        assert hasattr(asr, name), name
    assert asr._isFreeSpeechToTextAvailable() is False
    assert asr._remoteConsumptionOk() == 0
    assert asr._getVersion() == {"2.1": "2.1.4.13", "2.8": "2.8.7.4"}[nao.version.name]
    assert asr.getParameter("Sensitivity") == pytest.approx(0.5)
    if nao.version.name == "2.8":
        assert nao.service("_AsrCompiler1").init() is True


def test_the_status_names_the_engine(nao):
    memory = nao.service("ALMemory")
    assert memory.getData("NaoqiSim/SpeechRecognition/Source") == "engine"
    status = nao.runner.run(nao.sim.status())
    assert status.speech_recognition_source == "engine"
