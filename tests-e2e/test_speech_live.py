"""Speech through a running naoqi-sim stack, on each NAOqi version: the ALTextToSpeech
replacement, the tts container and the host audio output together, driven over qi like any client."""

import re
import time

import pytest
from support import box

SENTENCE = "Hello, I am a simulated NAO speaking through the engine container."
LONG = (
    "This is a long sentence that will be interrupted by stop all before it finishes, "
    "and it goes on and on so that there is plenty of audio left to cut."
)
MARK = re.compile(r"\\mrk(?:pause)?=(\d+)\\")


def last(entries, method):
    return [e for e in entries if e.get("method") == method][-1]


def test_the_replacement_serves_alt_text_to_speech(nao):
    assert nao.version.implementation in nao.service("ALTextToSpeech").whoami()


def test_say_blocks_for_the_audio(nao):
    tts = nao.service("ALTextToSpeech")
    tts.setLanguage("English")
    mark = time.monotonic()
    tts.say(SENTENCE)
    returned = time.monotonic()
    playback = nao.sink.wait_for(lambda p: p.started_at >= mark)
    audio = playback.duration_s

    assert audio > 2.0  # real speech was played, not the fallback clock
    assert not playback.interrupted
    assert 0.8 * audio <= returned - mark <= audio + 1.5
    # Played in real time, and say() returns as the voice ends.
    assert playback.ended_at is not None
    assert playback.ended_at - playback.started_at == pytest.approx(audio, abs=0.3)
    assert abs(returned - playback.ended_at) < 1.0


def test_animated_speech_gets_every_bookmark(nao):
    memory = nao.service("ALMemory")
    raised: list[int] = []
    subscriber = memory.subscriber("ALTextToSpeech/CurrentBookMark")
    link = subscriber.signal.connect(raised.append)
    try:
        # The gesture comes from the robot's `animations` package, installed in the image.
        nao.service("ALAnimatedSpeech").say(
            "^start(animations/Stand/Gestures/Hey_1) Hello with gestures "
            "^wait(animations/Stand/Gestures/Hey_1) and a second part after the gesture."
        )
        time.sleep(0.5)  # events reach the host asynchronously
    finally:
        subscriber.signal.disconnect(link)

    received = last(nao.container.speech_log(), "say")["text"]
    expected = {int(m) for m in MARK.findall(received)}
    assert len(expected) >= 2, received
    assert expected <= set(raised)
    assert raised[-1] == 0


def test_stop_all_cuts_the_sentence(nao):
    tts = nao.service("ALTextToSpeech")
    mark = time.monotonic()
    future = tts.say(LONG, _async=True)
    time.sleep(1.5)  # well into the audio
    t_stop = time.time()
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t_stop
    # A moment of audio, cut; or none at all when the stop at 1.5 s still found the engine
    # synthesizing (about 1.5 s for this sentence on a GitHub runner, under a second on a Mac).
    played = nao.played_if_any(mark)

    done = last(nao.container.speech_log(), "say-done")
    assert done["interrupted"] is True
    assert returned < 0.5
    assert (
        played < 2.0
    )  # of a sentence of about 9 s (`duration` is 0 when nothing played)


def test_stop_all_during_synthesis(nao):
    tts = nao.service("ALTextToSpeech")
    mark = time.monotonic()
    t0 = time.time()
    future = tts.say(LONG + " " + LONG, _async=True)
    time.sleep(0.15)  # the engine is still synthesizing the long text
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t0

    done = last(nao.container.speech_log(), "say-done")
    assert done["interrupted"] is True
    # The stop at 0.15 s, not the synthesis (about 3 s for this text on a GitHub runner, which
    # say() no longer waits for) nor the ~15 s of audio.
    assert returned < 1.0
    # A moment of audio at most, or none when the stop came before the first of it.
    assert nao.played_if_any(mark) < 0.3


# -- the boxes' pattern: start, wait for and stop a sentence by task id -------------------------
#
# Run inside NAOqi as Choregraphe's boxes do: on 2.1 `ALProxy.post` / `wait(id, 0)` / `stop(id)`
# from a second proxy; on 2.8 `pCall` / `wait(id)` / `stop(id)` on qi service objects.


def done_entry(nao, call_id):
    return [
        e
        for e in nao.container.speech_log()
        if e.get("method") == "say-done" and e["id"] == call_id
    ]


def test_the_say_box_stops_its_sentence(nao):
    mark = time.monotonic()
    out = box(
        nao,
        f"""
def run():
    tts, stopper = proxies("ALTextToSpeech")
    t0 = time.time()
    tid = start(tts, "say", {LONG!r})
    stop_later(stopper, tid, 1.0)
    wait(tts, tid)
    return {{"id": tid, "waited": time.time() - t0, "status": memory().getData("ALTextToSpeech/Status")}}
""",
    )
    # The stop at 1 s lands during the audio (a Mac synthesizes the sentence in under a second:
    # a short, cut playback) or still during synthesis (about 1.5 s on a GitHub runner: the say
    # is abandoned and nothing plays). Either way, a moment of audio at most.
    played = nao.played_if_any(mark)

    assert out["id"] >= 0  # a task id, from post/pCall
    assert out["waited"] < 2.0  # the stop at 1 s, not the sentence's ~9 s
    assert out["status"] == [out["id"], "done"]  # the call's own id
    assert done_entry(nao, out["id"])[0]["interrupted"] is True
    assert played < 2.0


def test_stopping_a_waiting_sentence_skips_it(nao):
    mark = time.monotonic()
    out = box(
        nao,
        f"""
def run():
    tts, stopper = proxies("ALTextToSpeech")
    a = start(tts, "say", {SENTENCE!r})
    time.sleep(0.3)
    b = start(tts, "say", "This second sentence must never be heard.")
    time.sleep(0.3)
    stopper.stop(b)
    t0 = time.time()
    wait(tts, b)
    waited_b = time.time() - t0
    wait(tts, a)
    return {{"a": a, "b": b, "waited_b": waited_b}}
""",
    )
    log = nao.container.speech_log()

    assert (
        out["waited_b"] < 1.0
    )  # returned at once, while the first sentence still spoke
    assert done_entry(nao, out["a"])[0]["interrupted"] is False
    assert [e for e in log if e.get("method") == "say-dropped" and e["id"] == out["b"]]
    assert not [e for e in log if e.get("method") == "say" and e["id"] == out["b"]]
    playbacks = [p for p in nao.sink.playbacks if p.started_at >= mark]
    assert len(playbacks) == 1 and not playbacks[0].interrupted


def test_the_animated_say_box_stops_the_speech(nao):
    mode = (
        {"speakingMovementMode": "disabled"}
        if nao.version.name == "2.8"
        else {"bodyLanguageMode": "disabled"}
    )
    out = box(
        nao,
        f"""
def run():
    speech, stopper = proxies("ALAnimatedSpeech")
    t0 = time.time()
    tid = start(speech, "say", {LONG!r}, {mode!r})
    stop_later(stopper, tid, 1.5)
    wait(speech, tid)
    return {{"waited": time.time() - t0}}
""",
    )

    # ALAnimatedSpeech passed the stop on to the speech with stop(id) on its own call.
    assert last(nao.container.speech_log(), "say-done")["interrupted"] is True
    assert out["waited"] < 4.0  # not the ~9 s of the sentence


def test_set_language_emits_language_tts(nao):
    if nao.version.name != "2.8":
        pytest.skip("languageTTS is a 2.8 signal")
    tts = nao.service("ALTextToSpeech")
    got: list[str] = []
    link = tts.languageTTS.connect(got.append)
    try:
        tts.setLanguage("French")
        tts.setLanguage("English")
        time.sleep(0.5)
    finally:
        tts.languageTTS.disconnect(link)

    assert got == ["French", "English"]


def test_the_languages_are_a_naos(nao):
    """The config installs three languages; NAOqi's own list is what a NAO supports; locale
    follows the language."""
    tts = nao.service("ALTextToSpeech")
    assert tts.getAvailableLanguages() == ["English", "French", "German"]
    supported = tts.getSupportedLanguages()
    assert len(supported) == 21
    assert {"English", "French", "German", "Japanese", "Arabic", "Brazilian"} < set(
        supported
    )
    assert tts.getLanguage() == "English" and tts.locale() == "en_US"
    try:
        tts.setLanguage("German")
        assert tts.locale() == "de_DE"
    finally:
        tts.setLanguage("English")


def test_a_language_the_image_lacks_speaks_with_its_fetched_voice(nao):
    """German's voice is not in the tts image: the engine fetched it into the voice volume
    when the stack started, and it speaks like the baked ones."""
    tts = nao.service("ALTextToSpeech")
    mark = time.monotonic()
    tts.say("Hallo, ich heiße Nao und ich spreche Deutsch.", "German")
    playback = nao.sink.wait_for(lambda p: p.started_at >= mark)

    assert playback.duration_s > 1.5  # real speech, not the fallback clock
    assert not playback.interrupted
    assert tts.getLanguage() == "English"  # for that call only


def test_a_language_that_is_not_installed_is_refused(nao):
    tts = nao.service("ALTextToSpeech")
    tts.setLanguage("French")
    try:
        assert "Klingon" not in tts.getAvailableLanguages()
        with pytest.raises(RuntimeError, match="Klingon"):
            tts.setLanguage("Klingon")
        assert tts.getLanguage() == "French"
        with pytest.raises(RuntimeError, match="Klingon"):
            tts.say("nuqneH", "Klingon")
        assert tts.getLanguage() == "French"
    finally:
        tts.setLanguage("English")
