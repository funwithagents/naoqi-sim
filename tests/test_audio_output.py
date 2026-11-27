import json
import socket
import sys
import threading
import time
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from naoqi_sim import audio_output
from naoqi_sim.audio_output import (
    RATE as MIX_RATE,
)
from naoqi_sim.audio_output import (
    TICK_S,
    AudioOutput,
    AudioSink,
    DevicePlayer,
    MemorySink,
    NullSink,
    Server,
    WavSink,
)

RATE = 8000  # small streams; the mixer resamples every rate the same way


class RunningOutput:
    """An in-process audio output on a free port, feeding `sink`."""

    def __init__(self, sink: AudioSink):
        self.sink = sink
        self.output = AudioOutput(sink)
        self.server = Server(("127.0.0.1", 0), self.output)
        host, port = self.server.server_address[:2]
        self.addr = (str(host), int(port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def send(self, header: bytes | dict, pcm: bytes = b"") -> float:
        """One connection: header line, body, then wait for the output to close it. Returns
        how long that took."""
        line = (
            header if isinstance(header, bytes) else json.dumps(header).encode() + b"\n"
        )
        t0 = time.monotonic()
        with socket.create_connection(self.addr) as s:
            s.sendall(line + pcm)
            s.shutdown(socket.SHUT_WR)
            try:
                while s.recv(4096):
                    pass
            # The output may stop reading with data still buffered, which resets the connection.
            except ConnectionResetError:
                pass
        return time.monotonic() - t0

    def play(
        self,
        seconds: float = 0.0,
        rate: int = RATE,
        channels: int = 1,
        pcm: bytes | None = None,
        **header,
    ) -> float:
        return self.send(
            {
                "cmd": "play",
                "rate": rate,
                "channels": channels,
                "format": "s16le",
                **header,
            },
            tone(seconds, rate, channels) if pcm is None else pcm,
        )

    def play_async(self, *args, **kwargs) -> list[float]:
        out: list[float] = []
        threading.Thread(
            target=lambda: out.append(self.play(*args, **kwargs)), daemon=True
        ).start()
        return out

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()


def tone(seconds: float, rate: int = RATE, channels: int = 1, level: int = 16) -> bytes:
    return np.full(int(seconds * rate) * channels, level, dtype="<i2").tobytes()


def sine(freq: float, seconds: float, rate: int = 16000, level: float = 8000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * freq * t)).astype("<i2").tobytes()


def frames(pcm: bytes, channels: int = 2) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").reshape(-1, channels).astype(np.float64)


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


@pytest.fixture
def memory():
    c = RunningOutput(MemorySink())
    yield c
    c.shutdown()


def playbacks(c: RunningOutput):
    assert isinstance(c.sink, MemorySink)
    return c.sink.playbacks


def mixes(c: RunningOutput):
    assert isinstance(c.sink, MemorySink)
    return c.sink.mixes


# --- One stream: the protocol, pacing, stop -------------------------------------------


def test_late_wake_ups_do_not_drift_the_mix(memory, monkeypatch, lateness):
    # Every sleep of the mixer wakes 30 ms late, longer than a tick, as a loaded machine's (or
    # a CI virtual machine's) timers can: the ticks keep their schedule, and the play its length.
    sleep_until = audio_output._sleep_until

    def late(deadline: float) -> None:
        if deadline > time.monotonic():  # a sleep there is wakes 30 ms late
            sleep_until(deadline + 0.03)

    monkeypatch.setattr(audio_output, "_sleep_until", late)
    dues: list[float] = []
    memory.output.listeners.append(lambda chunk, rate, channels, at: dues.append(at))

    took = memory.play(0.5, stream="speech")

    assert np.diff(dues) == pytest.approx(TICK_S)  # one tick apart, every one
    assert dues[-1] + TICK_S - dues[0] == pytest.approx(0.5, abs=TICK_S)
    # The late wake-ups don't add up (they would add 30 ms a tick); the play may still end one of
    # this machine's own late wake-ups late, on top of the injected 30 ms.
    assert took == pytest.approx(0.5, abs=0.15 + lateness())


def test_play_records_the_stream_as_received_paced_in_real_time(memory):
    took = memory.play(0.5, stream="speech")

    [p] = playbacks(memory)
    assert (p.stream, p.rate, p.channels, p.interrupted) == ("speech", RATE, 1, False)
    assert p.pcm == tone(0.5)
    assert 0.45 <= took <= 0.8
    assert p.ended_at is not None and p.ended_at - p.started_at >= 0.4


def test_a_play_without_a_stream_name_is_the_default_stream(memory):
    memory.play(0.1)
    assert playbacks(memory)[0].stream == "default"


def test_the_mix_is_48k_stereo_with_the_stream_s_duration(memory):
    memory.play(0.5, rate=22050)

    [mix] = mixes(memory)
    assert (mix.rate, mix.channels, mix.interrupted) == (MIX_RATE, 2, False)
    assert mix.duration_s == pytest.approx(0.5, abs=TICK_S)
    left, right = frames(mix.pcm)[len(frames(mix.pcm)) // 2]
    assert left == right == 16  # mono spread to both loudspeakers, at its level


def test_null_sink_is_paced_too():
    c = RunningOutput(NullSink())
    try:
        assert 0.45 <= c.play(0.5) <= 0.8
    finally:
        c.shutdown()


def test_stop_ends_a_stream_within_a_tick(memory):
    done = memory.play_async(2.0, stream="speech")
    time.sleep(0.5)
    t_stop = time.monotonic()
    memory.send({"cmd": "stop", "stream": "speech"})
    wait_for(lambda: done)

    assert time.monotonic() - t_stop < 0.15
    [p] = playbacks(memory)
    assert p.interrupted
    assert 0.3 < p.duration_s < 0.8


def test_the_newest_play_of_a_name_replaces_the_older(memory):
    first = memory.play_async(2.0, stream="speech")
    time.sleep(0.3)
    second_took = memory.play(0.5, stream="speech")
    wait_for(lambda: first)

    cut, full = playbacks(memory)
    assert cut.interrupted and cut.duration_s < 0.6
    assert not full.interrupted and full.duration_s == pytest.approx(0.5)
    assert first[0] < 1.0 and second_took >= 0.45


def test_bad_header_is_ignored(memory):
    memory.send(b"not json\n", tone(0.2))
    memory.play(0.2)

    [p] = playbacks(memory)
    assert p.pcm == tone(0.2)


def test_a_stop_does_not_cut_the_next_stream(memory):
    memory.send({"cmd": "stop"})
    memory.play(0.2)

    [p] = playbacks(memory)
    assert not p.interrupted and p.pcm == tone(0.2)


# --- Several streams: mixing --------------------------------------------------------------


def test_two_streams_play_together_and_the_mix_holds_both(memory):
    a = memory.play_async(rate=16000, pcm=sine(440, 0.6), stream="speech")
    b = memory.play_async(rate=16000, pcm=sine(1000, 0.6), stream="player:1")
    wait_for(lambda: a and b)

    speech, player = sorted(playbacks(memory), key=lambda p: p.stream != "speech")
    assert not speech.interrupted and not player.interrupted
    assert speech.ended_at is not None and player.ended_at is not None
    assert speech.started_at < player.ended_at and player.started_at < speech.ended_at
    [mix] = mixes(memory)
    left = frames(mix.pcm)[:, 0]
    middle = left[int(0.15 * MIX_RATE) : int(0.45 * MIX_RATE)]
    spectrum = np.abs(np.fft.rfft(middle))
    freqs = np.fft.rfftfreq(len(middle), 1 / MIX_RATE)

    def peak(f):
        return spectrum[np.argmin(np.abs(freqs - f))]

    noise = np.median(spectrum)
    assert peak(440) > 100 * noise and peak(1000) > 100 * noise


def test_stopping_one_stream_leaves_the_others(memory):
    a = memory.play_async(1.0, stream="speech")
    b = memory.play_async(1.0, stream="player:1")
    time.sleep(0.3)
    memory.send({"cmd": "stop", "stream": "player:1"})
    wait_for(lambda: a and b)

    by_name = {p.stream: p for p in playbacks(memory)}
    assert by_name["player:1"].interrupted
    assert not by_name["speech"].interrupted
    assert by_name["speech"].duration_s == pytest.approx(1.0)
    assert not mixes(memory)[-1].interrupted  # the speech went on to its end


def test_a_stop_without_a_name_stops_every_stream_and_tells_the_listeners(memory):
    heard: list[tuple[int, float]] = []
    memory.output.listeners.append(
        lambda chunk, rate, channels, at: heard.append((len(chunk), at))
    )
    a = memory.play_async(2.0, stream="speech")
    b = memory.play_async(2.0, stream="player:1")
    time.sleep(0.4)
    t_stop = time.monotonic()
    memory.send({"cmd": "stop"})
    wait_for(lambda: a and b)

    assert all(p.interrupted for p in playbacks(memory))
    assert mixes(memory)[-1].interrupted
    wait_for(lambda: heard and heard[-1][0] == 0)
    assert heard[-1][1] == pytest.approx(t_stop, abs=0.1)  # silent from the stop


def test_set_changes_volume_and_pan_from_the_next_tick(memory):
    done = memory.play_async(pcm=tone(1.0, level=1000), stream="player:1")
    time.sleep(0.3)
    memory.send({"cmd": "set", "stream": "player:1", "volume": 0.5, "pan": -1.0})
    wait_for(lambda: done)

    mix = frames(mixes(memory)[-1].pcm)
    before, after = mix[int(0.1 * MIX_RATE)], mix[-int(0.1 * MIX_RATE)]
    assert before.tolist() == [1000, 1000]
    assert after.tolist() == [500, 0]  # half as loud, all on the left


def test_volume_and_pan_from_the_play_header(memory):
    memory.play(pcm=tone(0.3, level=1000), volume=0.25, pan=0.5)

    left, right = frames(mixes(memory)[-1].pcm)[int(0.15 * MIX_RATE)]
    assert (left, right) == (125, 250)  # balance: the left at 1 - pan, the right whole


def test_pause_holds_a_stream_and_resume_lets_it_go_on(memory, lateness):
    t0 = time.monotonic()
    done = memory.play_async(0.5, stream="player:2")
    time.sleep(0.15)
    memory.send({"cmd": "pause", "stream": "player:2"})
    time.sleep(0.4)
    memory.send({"cmd": "resume", "stream": "player:2"})
    wait_for(lambda: done)

    [p] = playbacks(memory)
    assert not p.interrupted and p.pcm == tone(0.5)  # nothing lost
    # Two late wake-ups can lengthen the run: this test's 0.4 s pause, and the mixer's resume.
    assert time.monotonic() - t0 == pytest.approx(0.5 + 0.4, abs=0.2 + 2 * lateness())


def test_streams_mix_into_one_run_and_quiet_ends_it(memory, lateness):
    a = memory.play_async(0.4, stream="speech")
    time.sleep(0.2)
    memory.play(0.4, stream="player:1")  # joins the running mix
    wait_for(lambda: a)
    time.sleep(0.1)
    memory.play(0.2, stream="speech")  # after silence: a new run

    first, second = mixes(memory)
    # player:1 joins after this test's 0.2 s sleep, which a slow machine wakes late.
    assert first.duration_s == pytest.approx(0.6, abs=0.1 + lateness())
    assert second.duration_s == pytest.approx(0.2, abs=TICK_S)


# --- The sink's call discipline -------------------------------------------------------------


class CallLog:
    """A sink that records its calls, and fails if two runs overlap."""

    def __init__(self):
        self.calls: list[str] = []
        self._open = False

    def begin(self, rate, channels):
        assert not self._open, "begin while a run is open"
        assert (rate, channels) == (MIX_RATE, 2)
        self._open = True
        self.calls.append("begin")

    def feed(self, chunk):
        assert self._open
        if self.calls[-1] != "feed":
            self.calls.append("feed")

    def end(self, interrupted):
        assert self._open
        self._open = False
        self.calls.append(f"end({interrupted})")


def test_overlapping_streams_make_one_run_of_sink_calls():
    sink = CallLog()
    c = RunningOutput(sink)
    try:
        first = c.play_async(0.6, stream="speech")
        time.sleep(0.2)
        c.play(0.2, stream="player:1")
        wait_for(lambda: first)
    finally:
        c.shutdown()

    assert sink.calls == ["begin", "feed", "end(False)"]


def test_a_failing_sink_still_gets_its_end_and_the_plays_return():
    class Failing(CallLog):
        def feed(self, chunk):
            raise OSError("device gone")

    sink = Failing()
    c = RunningOutput(sink)
    try:
        assert c.play(0.3) < 1.0
        assert c.play(0.3) < 1.0
    finally:
        c.shutdown()

    assert sink.calls == ["begin", "end(True)", "begin", "end(True)"]


# --- Playing state and listeners --------------------------------------------------------------


def test_playing_until_follows_the_mix(memory, lateness):
    output = memory.output
    assert output.playing_until < time.monotonic()  # idle

    t0 = time.monotonic()
    done = memory.play_async(1.0)
    time.sleep(0.4)
    # The mix is fed a tick ahead: it covers now, unless this machine woke the mixer late.
    assert output.playing_until > time.monotonic() - lateness()
    # A tick ahead of now, and now is t0 + 0.4 plus this test's own late wake-up.
    assert output.playing_until == pytest.approx(t0 + 0.4, abs=0.15 + lateness())
    wait_for(lambda: done)
    assert output.playing_until == pytest.approx(t0 + 1.0, abs=0.15)
    assert output.playing_until <= time.monotonic()


def test_a_stop_ends_the_playing_period_at_once(memory):
    done = memory.play_async(2.0)
    time.sleep(0.4)
    t_stop = time.monotonic()
    memory.send({"cmd": "stop"})
    wait_for(lambda: done)

    assert memory.output.playing_until <= time.monotonic()
    assert memory.output.playing_until == pytest.approx(t_stop, abs=0.1)


def test_listeners_hear_every_tick_of_the_mix_when_it_is_due(memory):
    heard: list[tuple[int, int, int, float]] = []
    memory.output.listeners.append(
        lambda chunk, rate, channels, at: heard.append((len(chunk), rate, channels, at))
    )
    t0 = time.monotonic()
    memory.play(0.35)
    assert sum(n for n, *_ in heard) == len(mixes(memory)[-1].pcm)  # all of the mix
    assert {(rate, channels) for _, rate, channels, _ in heard} == {(MIX_RATE, 2)}
    dues = [at for *_, at in heard]
    assert dues[0] == pytest.approx(t0, abs=0.15)
    # Back to back: each tick is due when the one before has played.
    for (n, *_, at), next_at in zip(heard, dues[1:], strict=False):
        assert next_at == pytest.approx(at + n / (4 * MIX_RATE), abs=0.005)


def test_a_failing_listener_does_not_stop_the_mix(memory):
    def broken(chunk, rate, channels, at):
        raise RuntimeError("deaf")

    memory.output.listeners.append(broken)
    memory.play(0.3)
    assert playbacks(memory)[-1].duration_s == pytest.approx(0.3, abs=0.01)
    assert not playbacks(memory)[-1].interrupted


# --- Sinks --------------------------------------------------------------------------


def wav_contents(path: Path) -> tuple[int, int, int, bytes]:
    with wave.open(str(path)) as w:
        return w.getnchannels(), w.getframerate(), w.getnframes(), w.readframes(-1)


def test_wav_sink_writes_the_runs_one_after_the_other(tmp_path):
    path = tmp_path / "played.wav"
    sink = WavSink(path)
    for seconds in (0.1, 0.2):
        sink.begin(MIX_RATE, 2)
        sink.feed(tone(seconds, MIX_RATE, 2))
        sink.end(False)
        # Readable between runs.
    assert wav_contents(path)[:3] == (2, MIX_RATE, int(0.3 * MIX_RATE))
    sink.close()


def test_wav_sink_records_what_the_output_mixes(tmp_path):
    path = tmp_path / "played.wav"
    c = RunningOutput(WavSink(path))
    try:
        c.play(0.3, rate=22050)
    finally:
        c.shutdown()
    assert isinstance(c.sink, WavSink)
    c.sink.close()

    channels, rate, nframes, _ = wav_contents(path)
    assert (channels, rate) == (2, MIX_RATE)
    assert nframes / MIX_RATE == pytest.approx(0.3, abs=TICK_S)


def test_memory_sink_wait_for_returns_an_ended_stream():
    sink = MemorySink()
    sink.stream_begin("speech", RATE, 1)
    sink.stream_feed("speech", tone(0.1))

    def finish():
        time.sleep(0.1)
        sink.stream_end("speech", False)

    threading.Thread(target=finish).start()
    p = sink.wait_for(lambda p: p.stream == "speech", timeout=2)
    assert p.ended_at is not None and p.pcm == tone(0.1)
    with pytest.raises(TimeoutError):
        sink.wait_for(lambda p: p.stream == "player:1", timeout=0.1)


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.written = b""

    def start(self):
        self.calls.append("start")

    def write(self, data):
        self.written += data

    def stop(self):
        self.calls.append("stop")

    def abort(self):
        self.calls.append("abort")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def fake_sounddevice(monkeypatch):
    streams: list[FakeStream] = []

    def raw_output_stream(**kwargs):
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    module = types.ModuleType("sounddevice")
    module.RawOutputStream = raw_output_stream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return streams


def test_device_player_plays_each_run_and_cuts_on_interruption(fake_sounddevice):
    player = DevicePlayer(device=3)
    assert fake_sounddevice == []  # nothing opened before a run

    player.begin(MIX_RATE, 2)
    player.feed(b"ab")
    player.feed(b"cd")
    player.end(False)
    player.begin(MIX_RATE, 2)
    player.end(True)

    finished, cut = fake_sounddevice
    assert (
        finished.kwargs["samplerate"] == MIX_RATE and finished.kwargs["channels"] == 2
    )
    assert finished.kwargs["device"] == 3 and finished.kwargs["dtype"] == "int16"
    assert (
        finished.kwargs["latency"] == "low"
    )  # heard about when it is due, as on a NAO
    assert finished.written == b"abcd"
    assert finished.calls == ["start", "stop", "close"]  # drained
    assert cut.calls == ["start", "abort", "close"]  # cut at once


def test_a_muted_device_player_plays_silence_of_the_same_length(fake_sounddevice):
    """The loudspeakers muted: the device stream runs as usual, fed zeros in place of the mix,
    so its timing does not change; unmuted, the mix is heard again from the next tick."""
    player = DevicePlayer()
    player.begin(MIX_RATE, 2)
    player.feed(b"ab")
    player.muted = True
    player.feed(b"cdef")
    player.muted = False
    player.feed(b"gh")
    player.end(False)
    (stream,) = fake_sounddevice
    assert stream.written == b"ab" + bytes(4) + b"gh"
    assert stream.calls == ["start", "stop", "close"]


def test_muting_the_loudspeakers_leaves_the_listeners_hearing_the_robot(
    fake_sounddevice,
):
    """Only the device is silent: what listens to the mix (the fake room) still gets it."""
    player = DevicePlayer()
    player.muted = True
    output = AudioOutput(player)
    heard: list[bytes] = []
    output.listeners.append(lambda chunk, rate, channels, at: heard.append(chunk))
    server = Server(("127.0.0.1", 0), output)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        header = {"cmd": "play", "rate": MIX_RATE, "channels": 2, "format": "s16le"}
        with socket.create_connection(("127.0.0.1", port)) as s:
            s.sendall(json.dumps(header).encode() + b"\n" + b"\x10\x00" * 2 * 4800)
            s.shutdown(socket.SHUT_WR)
            while s.recv(4096):
                pass
    finally:
        server.shutdown()
        server.server_close()
    (stream,) = fake_sounddevice
    assert stream.written and not any(stream.written)  # the device: silence
    assert any(b"\x10\x00" in chunk for chunk in heard)  # the fake room: the robot
