"""ALSpeechRecognition on a running naoqi-sim stack (specs/services/speech-recognition.md): sentences
from tests-e2e/speech/ (a person's voice recorded on a NAO, committed) played into the fake room, recognised for a
script's vocabulary and for a dialog topic loaded by hand, on both versions; and a sim that boots in
German, a language whose voice and model are fetched on first use, heard and talked to in German."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from conftest import live_config
from support import recorded_sentences, say_to_the_robot

from naoqi_sim import NaoqiSim
from naoqi_sim.config import RobotSettings

SUBSCRIBER = "test_speech_recognition_live"
STATUS = "ALSpeechRecognition/Status"
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


@pytest.fixture(scope="session")
def sentences() -> dict[str, np.ndarray]:
    return recorded_sentences()


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
    }  # the default config installs these two; German has a model but is not installed
    with pytest.raises(RuntimeError, match="does not support the following language"):
        asr.setLanguage("German")
    asr.setLanguage("French")
    with listening(asr, ["je veux une pomme", "bonjour"]):
        mark = events.mark()
        say_to_the_robot(nao, sentences, "je veux une pomme")
        events.wait_word(mark)
        assert [p for p, _ in events.words(mark)] == ["je veux une pomme"]


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
    assert asr._getVersion() == "4.5"  # a NAO 2.1.4.13's answer
    assert asr.getParameter("Sensitivity") == pytest.approx(0.5)
    if nao.version.name == "2.8":
        assert nao.service("_AsrCompiler1").init() is True


def test_the_status_names_the_engine(nao):
    memory = nao.service("ALMemory")
    assert memory.getData("NaoqiSim/SpeechRecognition/Source") == "engine"
    status = nao.runner.run(nao.sim.status())
    assert status.speech_recognition_source == "engine"


GERMAN_TOPIC = """topic: ~naoqi_sim_test_reco_de()
language: ged
u:(hallo roboter) hallo mensch
u:(wie spät ist es) zeit zum testen
"""


def robot_said(nao, text: str) -> np.ndarray:
    """The robot's own speech of `text`, taken from the audio output and brought to 16 kHz mono:
    a sentence in a language the tier has no recording for. It is preceded by 0.6 s of silence,
    as a recording is: the module drops what it hears in the 0.35 s after it starts listening."""
    after = time.monotonic()
    nao.service("ALTextToSpeech").say(text)
    speech = nao.sink.wait_for(lambda p: p.started_at >= after and p.stream == "speech")
    samples = np.frombuffer(speech.pcm, dtype=np.int16).astype(np.float64)
    samples = samples.reshape(-1, speech.channels).mean(axis=1)
    n = int(len(samples) * 16000 / speech.rate)
    resampled = np.interp(
        np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples
    )
    return np.concatenate([np.zeros(9600), resampled]).astype(np.int16)


def test_a_sim_that_boots_in_german_speaks_hears_and_talks_german(nao, tmp_path: Path):
    """A language beyond the images' English and French (asr-engine.md, "Models"): its voice and
    its model fetched into the language packs volume on first use, the robot's language at boot,
    a script's vocabulary heard, a German topic answered, though the suites carry no German
    dialog data (speech-recognition.md, "Languages")."""
    default = nao.sim
    nao.stop()
    nao.sim = NaoqiSim(
        live_config(
            nao.version.name,
            robot=RobotSettings(
                available_languages=("German", "English"), language="German"
            ),
        ),
        sink=nao.sink,
    )
    try:
        nao.start()
        asr = nao.service("ALSpeechRecognition")
        assert nao.service("ALTextToSpeech").getLanguage() == "German"
        assert asr.getLanguage() == "German"
        assert set(asr.getAvailableLanguages()) == {"German", "English"}
        sentences = {
            t: robot_said(nao, t) for t in ("hallo roboter", "wie spät ist es")
        }
        events = Events(nao.service("ALMemory"))

        with listening(asr, ["hallo roboter", "wie spät ist es", "setz dich"]):
            for text in sentences:
                mark = events.mark()
                say_to_the_robot(nao, sentences, text)
                events.wait_word(mark)
                assert [p for p, _ in events.words(mark)] == [text]

        dialog = nao.service("ALDialog")
        topic_file = tmp_path / "naoqi_sim_test_reco_de.top"
        topic_file.write_text(GERMAN_TOPIC)
        nao.container.copy_in(topic_file, "/tmp/naoqi_sim_test_reco_de.top")
        dialog.setLanguage("German")
        topic = dialog.loadTopic("/tmp/naoqi_sim_test_reco_de.top")
        try:
            dialog.activateTopic(topic)
            dialog.subscribe(SUBSCRIBER)
            try:
                time.sleep(2.0)  # the dialog gives the recognition its phrases
                mark = events.mark()
                say_to_the_robot(nao, sentences, "hallo roboter")
                events.wait(
                    mark,
                    lambda items: any(
                        k == "Dialog/Answered" and v for _, k, v in items
                    ),
                    timeout=15,
                    what="the answer",
                )
                assert "hallo roboter" in events.since(mark, "Dialog/LastInput")
                assert events.since(mark, "Dialog/Answered")[-1] == "hallo mensch"
            finally:
                dialog.unsubscribe(SUBSCRIBER)
                dialog.deactivateTopic(topic)
        finally:
            dialog.unloadTopic(topic)
    finally:
        nao.stop()
        nao.sim = default  # the next test starts the default robot again
