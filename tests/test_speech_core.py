import threading
import time

import naoqi_sim_speech_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

END = [
    ("ALTextToSpeech/CurrentSentence", ""),
    ("ALTextToSpeech/TextDone", 1),
    ("ALTextToSpeech/CurrentBookMark", 0),
    ("ALTextToSpeech/TextStarted", 0),
]


class FakeEngine(core.Speaker):
    """A Speaker whose engine replies with chosen timings after `synth_s`, or fails."""

    def __init__(self, duration=0.2, marks=None, synth_s=0.0, fail=False):
        self.events: list[tuple[float, str, object]] = []
        self.signals: list[tuple] = []
        self.engine_calls: list[dict] = []
        self.engine_stops: list[object] = []  # the ids /stop named
        self.engine_ids: list[object] = []  # the ids /say carried
        self.reply_stopped = (
            False  # the engine says it stopped the say before playing it
        )
        super().__init__(self._record, signal=lambda *a: self.signals.append(a))
        self.reply = {"duration": duration, "marks": marks or {}, "engine": "fake"}
        self.synth_s = synth_s
        self.fail = fail

    def _record(self, key, value):
        self.events.append((time.monotonic(), key, value))

    def _engine_say(self, items, rate, pitch, language, sid):
        self.engine_calls.append(
            {"items": items, "rate": rate, "pitch": pitch, "language": language}
        )
        self.engine_ids.append(sid)
        time.sleep(self.synth_s)
        if self.fail:
            raise OSError("engine unreachable")
        if self.reply_stopped:
            return {"duration": 0.0, "marks": {}, "engine": "fake", "stopped": True}
        return self.reply

    def _engine_stop(self, sid=None):
        self.engine_stops.append(sid)

    def sequence(self):
        return [(k, v) for _, k, v in self.events]

    def times(self, key):
        return [t for t, k, _ in self.events if k == key]


def say_in_thread(sp, text, sid=1):
    done: list[float] = []
    t0 = time.monotonic()
    th = threading.Thread(
        target=lambda: (sp.say(text, sid), done.append(time.monotonic() - t0))
    )
    th.start()
    return th, done


def spoken(sp):
    """The ids that reached the engine, in order, from their `started` status."""
    return [
        v[0]
        for _, k, v in sp.events
        if k == "ALTextToSpeech/Status" and v[1] == "started"
    ]


# -- parse -------------------------------------------------------------------


def test_parse_turns_tags_into_items():
    items, rate, pitch = core.parse(
        "\\pau=500\\ \\mrk=1\\  Hello there \\mrkpause=2\\ bye ", {}
    )

    assert items == [
        {"type": "pause", "ms": 500},
        {"type": "mark", "id": 1},
        {"type": "text", "text": "Hello there"},
        {"type": "mark", "id": 2},
        {"type": "text", "text": "bye"},
    ]
    assert (rate, pitch) == (100, 100)


def test_parse_drops_ignored_tags():
    items, _, _ = core.parse(
        "\\vol=50\\Loud \\emph=2\\word\\bound=W\\ \\readmode=char\\ \\tn=spell\\x", {}
    )

    assert items == [
        {"type": "text", "text": "Loud"},
        {"type": "text", "text": "word"},
        {"type": "text", "text": "x"},
    ]


def test_rate_and_pitch_apply_to_the_call_and_carry_over():
    state: dict = {}
    _, rate, pitch = core.parse("\\rspd=80\\slow \\vct=120\\high", state)
    assert (rate, pitch) == (80, 120)

    _, rate, pitch = core.parse("next call", state)
    assert (rate, pitch) == (80, 120)

    _, rate, pitch = core.parse("\\rspd=150\\ fast \\rst\\ back to normal", state)
    assert (rate, pitch) == (100, 100)


# -- say ---------------------------------------------------------------------


def test_say_raises_the_event_sequence_on_the_engine_clock():
    sp = FakeEngine(duration=0.3, marks={"2": 0.2, "1": 0.1})
    t0 = time.monotonic()
    sp.say("\\mrk=1\\ Hello \\mrk=2\\ world", 1)
    took = time.monotonic() - t0

    assert sp.sequence() == [
        ("ALTextToSpeech/Status", [1, "enqueued"]),
        ("ALTextToSpeech/TextStarted", 1),
        ("ALTextToSpeech/TextDone", 0),
        ("ALTextToSpeech/Status", [1, "started"]),
        ("ALTextToSpeech/CurrentSentence", "\\mrk=1\\ Hello \\mrk=2\\ world"),
        ("ALTextToSpeech/CurrentBookMark", 1),
        ("ALTextToSpeech/CurrentBookMark", 2),
        ("ALTextToSpeech/Status", [1, "done"]),
        *END,
    ]
    assert sp.signals == [("_started", "\\mrk=1\\ Hello \\mrk=2\\ world")]
    started = sp.times("ALTextToSpeech/CurrentSentence")[0]
    b1, b2, _ = sp.times("ALTextToSpeech/CurrentBookMark")
    assert b1 - started == pytest.approx(0.1, abs=0.03)
    assert b2 - started == pytest.approx(0.2, abs=0.03)
    assert took == pytest.approx(0.3, abs=0.05)
    assert sp.engine_stops == []


def test_say_sends_the_parsed_items_rate_and_language():
    sp = FakeEngine(duration=0.0)
    sp.set_language("French")
    sp.say("\\rspd=90\\Bonjour \\pau=200\\ toi")

    assert sp.engine_calls == [
        {
            "items": [
                {"type": "text", "text": "Bonjour"},
                {"type": "pause", "ms": 200},
                {"type": "text", "text": "toi"},
            ],
            "rate": 90,
            "pitch": 100,
            "language": "French",
        }
    ]
    assert ("languageTTS", "French") in sp.signals


def test_stop_all_mid_sentence():
    sp = FakeEngine(duration=1.0, marks={"1": 0.05, "2": 0.6})
    th, done = say_in_thread(sp, "\\mrk=1\\ one \\mrk=2\\ two")
    time.sleep(0.2)
    sp.stop_all()
    th.join(2)

    assert done[0] < 0.35
    marks = [v for _, k, v in sp.events if k == "ALTextToSpeech/CurrentBookMark"]
    assert marks == [1, 0]  # 2 was never reached; 0 is the end-of-sentence reset
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [1, "done"]), *END]
    assert len(sp.engine_stops) == 1


def test_stop_all_during_synthesis_returns_at_once_and_stops_that_say():
    """The engine takes 2 s to synthesize; the stop comes at 0.1 s: say() returns then, not
    after the reply (3 s for a long text on a GitHub runner), and the engine is told which say
    to abandon, so the reply's audio never plays."""
    sp = FakeEngine(duration=1.0, marks={"1": 0.3}, synth_s=2.0)
    th, done = say_in_thread(sp, "\\mrk=1\\ a sentence still being synthesized", sid=7)
    time.sleep(0.1)
    sp.stop_all()
    th.join(3)

    assert done[0] < 0.4  # at the stop, not after the engine's reply
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()
    assert ("ALTextToSpeech/CurrentBookMark", 1) not in sp.sequence()
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [7, "done"]), *END]
    assert sp.engine_stops == [7]  # once, with the say's id
    assert sp.engine_ids == [7]  # the id the engine knows the say by


def test_a_say_the_engine_stopped_first_is_interrupted_without_audio():
    """The stop reached the engine before the say did (or between its last item and the
    stream): the engine answers `stopped`, and the call ends interrupted at once."""
    sp = FakeEngine(duration=1.0)
    sp.reply_stopped = True
    t0 = time.monotonic()
    sp.say("hello", 3)

    assert time.monotonic() - t0 < 0.2  # not the 1 s of audio there would have been
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [3, "done"]), *END]
    assert sp.engine_stops == []  # the engine already stopped it


def test_a_stop_before_say_does_not_cut_the_next_sentence():
    sp = FakeEngine(duration=0.2)
    sp.stop_all()
    t0 = time.monotonic()
    sp.say("hello")

    assert time.monotonic() - t0 == pytest.approx(0.2, abs=0.05)
    assert ("ALTextToSpeech/TextInterrupted", 1) not in sp.sequence()


def test_fallback_clock_when_the_engine_is_unreachable(monkeypatch):
    monkeypatch.setattr(core, "FALLBACK_SECONDS_PER_TOKEN", 0.05)
    sp = FakeEngine(fail=True)
    t0 = time.monotonic()
    sp.say("one \\mrk=1\\ two three \\mrkpause=2\\", 1)
    took = time.monotonic() - t0

    # 5 whitespace tokens, tags included.
    assert took == pytest.approx(5 * 0.05, abs=0.04)
    started = sp.times("ALTextToSpeech/CurrentSentence")[0]
    b1, b2, _ = sp.times("ALTextToSpeech/CurrentBookMark")
    assert b1 - started == pytest.approx(0.05, abs=0.03)  # token 1
    assert b2 - started == pytest.approx(0.20, abs=0.03)  # token 4
    assert sp.last["engine"] == "fallback-clock"
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [1, "done"]), *END]


def test_parameters_round_trip_and_reach_the_engine():
    sp = FakeEngine(duration=0.0)
    sp.set_parameter("speed", 70)
    sp.set_parameter("pitchShift", 1.2)

    assert sp.get_parameter("speed") == 70.0
    assert sp.get_parameter("pitchShift") == pytest.approx(1.2)
    sp.say("hi")
    assert (sp.engine_calls[0]["rate"], sp.engine_calls[0]["pitch"]) == (
        70.0,
        pytest.approx(120.0),
    )


# -- calls by id (the C++ front's task ids) ----------------------------------


def test_a_call_without_an_id_gets_one_above_the_task_ids():
    sp = FakeEngine(duration=0.0)
    sp.say("a")
    sp.say("b")

    assert spoken(sp) == [core.FIRST_OWN_ID, core.FIRST_OWN_ID + 1]


def test_a_call_speaks_in_the_language_it_was_given_only():
    sp = FakeEngine(duration=0.0)
    sp.say("bonjour", 7, "French")
    sp.say("hello", 8)

    assert [c["language"] for c in sp.engine_calls] == ["French", "English"]
    assert sp.language == "English"


def test_the_installed_languages_come_from_the_environment_the_first_at_boot(
    monkeypatch,
):
    assert core.installed_languages("German, French ,English") == (
        "German",
        "French",
        "English",
    )
    assert core.installed_languages("") == ("English", "French")

    monkeypatch.setattr(core, "LANGUAGES", ("French", "German"))
    sp = FakeEngine(duration=0.0)
    assert sp.language == "French"
    sp.say("hallo", 1, "German")
    assert sp.engine_calls[-1]["language"] == "German"
    with pytest.raises(RuntimeError, match=r"'English'.*French, German"):
        sp.set_language("English")


def test_supported_languages_are_a_naos_whatever_is_installed():
    assert len(core.SUPPORTED_LANGUAGES) == 21
    assert set(core.LANGUAGES) < set(core.SUPPORTED_LANGUAGES)
    assert {"Japanese", "Korean", "Arabic", "Brazilian"} < set(core.SUPPORTED_LANGUAGES)
    assert set(core.LOCALES) == set(core.SUPPORTED_LANGUAGES)


def test_locale_follows_the_language():
    sp = FakeEngine(duration=0.0)
    assert sp.locale() == "en_US"
    sp.set_language("French")
    assert sp.locale() == "fr_FR"
    assert (
        core.LOCALES["Brazilian"] == "pt_BR" and core.LOCALES["Portuguese"] == "pt_PT"
    )


def test_set_language_refuses_a_language_that_is_not_installed():
    sp = FakeEngine(duration=0.0)
    sp.set_language("French")

    with pytest.raises(RuntimeError, match=r"'Klingon'.*English, French"):
        sp.set_language("Klingon")
    assert sp.language == "French"
    # No languageTTS for the refused one
    assert sp.signals == [("languageTTS", "French")]
    sp.say("bonjour", 1)
    assert sp.engine_calls[-1]["language"] == "French"


def test_a_call_in_a_language_that_is_not_installed_raises_unspoken():
    sp = FakeEngine(duration=0.0)

    with pytest.raises(RuntimeError, match="Klingon"):
        sp.say("nuqneH", 1, "Klingon")
    with pytest.raises(RuntimeError, match="Klingon"):
        sp.start(2, "nuqneH", "Klingon")  # to the front's caller, not on the say thread
    assert sp.wait_done(2, 0.0) is True
    assert sp.engine_calls == []
    assert sp.events == []
    assert sp.language == "English"


def test_stop_by_id_ends_the_speaking_call_and_the_next_one_speaks():
    sp = FakeEngine(duration=0.6)
    first, first_done = say_in_thread(sp, "first", 5)
    time.sleep(0.05)
    second, second_done = say_in_thread(sp, "second", 6)
    time.sleep(0.15)
    sp.stop_call(5)
    first.join(2)
    second.join(2)

    assert first_done[0] < 0.35
    assert spoken(sp) == [5, 6]
    assert sp.sequence().count(("ALTextToSpeech/TextInterrupted", 1)) == 1
    # The second call was not cut by the first one's stop: it played its whole duration.
    assert second_done[0] == pytest.approx(0.15 + 0.6, abs=0.15)
    assert len(sp.engine_stops) == 1


def test_stop_by_id_of_a_waiting_call_drops_it_unspoken():
    sp = FakeEngine(duration=0.4)
    first, first_done = say_in_thread(sp, "first", 5)
    time.sleep(0.05)
    second, second_done = say_in_thread(sp, "second", 6)
    time.sleep(0.05)
    sp.stop_call(6)
    second.join(2)

    assert second_done[0] < 0.1  # returned at once, not after the first call
    first.join(2)
    assert first_done[0] == pytest.approx(0.4, abs=0.1)  # untouched
    assert spoken(sp) == [5]
    assert [v for _, k, v in sp.events if k == "ALTextToSpeech/Status"] == [
        [5, "enqueued"],
        [5, "started"],
        [5, "done"],
    ]
    assert sp.engine_stops == []


def test_stop_by_an_unknown_or_finished_id_does_nothing():
    sp = FakeEngine(duration=0.0)
    sp.say("done already", 3)
    sp.stop_call(3)
    sp.stop_call(99)
    sp.say("next", 4)

    assert ("ALTextToSpeech/TextInterrupted", 1) not in sp.sequence()
    assert spoken(sp) == [3, 4]


def test_calls_speak_in_arrival_order():
    sp = FakeEngine(duration=0.1)
    threads = []
    for sid in (10, 11, 12):
        threads.append(say_in_thread(sp, f"call {sid}", sid)[0])
        time.sleep(0.02)
    for th in threads:
        th.join(2)

    assert spoken(sp) == [10, 11, 12]


def test_start_returns_at_once_and_wait_done_follows_the_call():
    sp = FakeEngine(duration=0.3)
    t0 = time.monotonic()
    sp.start(21, "background")

    assert time.monotonic() - t0 < 0.05
    assert sp.wait_done(21, 0.05) is False  # still speaking
    assert sp.wait_done(21, 1.0) is True
    assert time.monotonic() - t0 == pytest.approx(0.3, abs=0.1)
    assert spoken(sp) == [21]
    assert sp.wait_done(21, 0.0) is True  # finished, then unknown: done


def test_a_started_call_stopped_by_id_is_done_early():
    sp = FakeEngine(duration=1.0)
    sp.start(30, "long")
    time.sleep(0.1)
    sp.stop_call(30)

    assert sp.wait_done(30, 0.5) is True
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()


def test_status_events_carry_the_call_id():
    sp = FakeEngine(duration=0.0)
    sp.say("hi", 42)

    statuses = [v for _, k, v in sp.events if k == "ALTextToSpeech/Status"]
    assert statuses == [[42, "enqueued"], [42, "started"], [42, "done"]]
