"""The audio input: the fake source, the formats it produces, pacing, the robot hearing itself,
the microphone.

The device runs as on a running `NaoqiSim`, served a `need` by a fake host link connection that
records what it sends, with a fake qi session for its ALMemory keys."""

import io
import sys
import threading
import time
import types
import wave

import numpy as np
import pytest

from naoqi_sim import audio_input
from naoqi_sim.audio_input import (
    BASE_RATE,
    CHUNK,
    AudioInput,
    Decimator,
    FakeAudioSource,
    MicSource,
    _Stream,
    check_mic,
    load_sound,
    upsample,
)
from naoqi_sim.audio_output import AudioOutput, MemorySink
from naoqi_sim.errors import DeviceUnavailableError

FRONT = {"rate": 16000, "channel": "front", "deinterleaved": False}
ALL = {"rate": 48000, "channel": "all", "deinterleaved": False}
ALL_SPLIT = {"rate": 48000, "channel": "all", "deinterleaved": True}


def tone(freq: float, seconds: float, rate: int, amplitude: float = 8000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def peak_hz(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(spectrum)])


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


# --- Resampling ------------------------------------------------------------------------------


def test_a_48k_tone_brought_to_16k_keeps_its_pitch_and_level_without_seams():
    x = tone(1000, 1.0, BASE_RATE).astype(np.float64)[:, None].repeat(4, axis=1)
    whole = Decimator()(x)
    blocks = Decimator()
    pieces = np.vstack([blocks(x[i : i + 480]) for i in range(0, len(x), 480)])
    assert np.allclose(whole, pieces)  # block by block is the same signal: no seams
    assert len(pieces) == 16000
    steady = pieces[200:-200, 0]
    assert peak_hz(steady, 16000) == pytest.approx(1000, abs=3)
    assert rms(steady) == pytest.approx(8000 / np.sqrt(2), rel=0.02)


def test_up_then_down_gives_back_a_16k_signal():
    x = tone(440, 0.5, 16000).astype(np.float64)[:, None]
    back = Decimator(1)(upsample(x))
    delay = (len(audio_input.LOWPASS) - 1) // 2 // 3  # the decimator's, at 16 kHz
    error = back[delay + 50 : -50, 0] - x[50 : -50 - delay, 0]
    assert np.max(np.abs(error)) < 0.02 * 8000


def test_a_tone_above_8k_does_not_fold_into_16k():
    x = tone(12000, 0.5, BASE_RATE).astype(np.float64)[:, None]
    assert rms(Decimator(1)(x)[100:]) < 0.01 * rms(x)


# --- The fake source -------------------------------------------------------------------------


def test_load_sound_reads_wav_files_and_arrays(tmp_path):
    path = tmp_path / "four.wav"
    data = np.arange(40, dtype=np.int16).reshape(10, 4)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(4)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(data.tobytes())
    samples, rate = load_sound(path)
    assert rate == 48000 and np.array_equal(samples, data)
    samples, rate = load_sound(np.zeros(5, dtype=np.int16), 16000)
    assert samples.shape == (5, 1) and rate == 16000


def write_wav(path, rate=16000, channels=1, width=2, frames=10):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\0" * frames * channels * width)
    return path


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda p: write_wav(p / "a.wav", width=1), "8-bit"),
        (lambda p: write_wav(p / "a.wav", channels=2), "2 channels"),
        (lambda p: write_wav(p / "a.wav", rate=44100), "44100 Hz"),
        (lambda p: p / "missing.wav", "cannot read"),
        (lambda p: np.zeros(10, dtype=np.float32), "float32"),
        (lambda p: np.zeros((10, 2), dtype=np.int16), "2 channels"),
    ],
)
def test_the_fake_source_refuses_other_sounds(tmp_path, make, problem):
    with pytest.raises(ValueError, match=problem):
        FakeAudioSource().play(make(tmp_path), 16000)


def test_a_mono_sound_is_spread_by_the_mono_policy():
    sound = np.full(4800, 1000, dtype=np.int16)
    dup = FakeAudioSource("duplicate")
    dup.play(sound, 48000)
    assert np.all(dup.read(time.monotonic(), 480)[:, :] > 900)
    front_only = FakeAudioSource("silence")
    take = front_only.play(sound, 48000)
    block = front_only.read(take.started_at, 480)
    assert np.all(block[:, 2] == 1000) and not block[:, [0, 1, 3]].any()


def test_a_four_channel_sound_keeps_nao_order():
    sound = np.tile(np.array([[1, 2, 3, 4]], dtype=np.int16), (480, 1))
    source = FakeAudioSource("silence")  # the policy does not touch a 4-channel sound
    take = source.play(sound, 48000)
    assert np.array_equal(source.read(take.started_at, 480), sound)


def test_overlapping_sounds_mix_and_clip():
    source = FakeAudioSource()
    a = source.play(np.full(4800, 20000, dtype=np.int16), 48000)
    source.play(np.full(4800, 20000, dtype=np.int16), 48000)
    block = audio_input._clip16(source.read(a.started_at + 0.01, 480))
    assert np.all(block == 32767)


def test_a_sound_plays_on_the_wall_clock():
    source = FakeAudioSource()
    sound = np.arange(4800, dtype=np.int16)  # 0.1 s at 48 kHz
    take = source.play(sound, 48000)
    before = source.read(take.started_at - 480 / BASE_RATE, 960)  # straddles its start
    assert not before[:480].any() and np.array_equal(before[480:, 0], sound[:480])
    later = source.read(take.started_at + 0.05, 4800)  # the second half, then silence
    assert np.array_equal(later[:2400, 0], sound[2400:]) and not later[2400:].any()
    assert take.ended_at == pytest.approx(take.started_at + 0.1)


def test_wait_returns_when_a_take_ends_and_stop_cuts_every_take():
    source = FakeAudioSource()
    short = source.play(np.zeros(4800, dtype=np.int16), 48000)  # 0.1 s
    assert short.wait(2) and short.done
    assert time.monotonic() >= short.ended_at

    long = source.play(np.ones(48000 * 10, dtype=np.int16), 48000)
    assert not long.wait(0.05)
    threading.Timer(0.1, source.stop).start()
    assert long.wait(2)
    assert long.ended_at - long.started_at < 1
    assert not source.read(time.monotonic(), 480).any()


def test_deinterleaved_chunks_lay_each_channel_after_the_other():
    stream = _Stream((48000, "all", True))
    chunk = np.tile(np.array([[1, 2, 3, 4]]), (3, 1))
    header, data = stream.message(chunk)
    assert header["channels"] == 4 and header["samples"] == 3
    assert np.frombuffer(data, "<i2").tolist() == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]


# --- The device ------------------------------------------------------------------------------


class Conn:
    """The host link connection: records every message sent, with its time."""

    def __init__(self):
        self.sent: list[tuple[float, dict, bytes]] = []
        self.lock = threading.Lock()

    def send(self, header, payload=b""):
        with self.lock:
            self.sent.append((time.monotonic(), header, payload))
        return True

    def pcm(self, fmt: dict) -> list[tuple[float, dict, np.ndarray]]:
        with self.lock:
            return [
                (t, h, np.frombuffer(p, "<i2").reshape(h["samples"], h["channels"]))
                for t, h, p in self.sent
                if h["type"] == "pcm" and h["format"] == fmt
            ]

    def energies(self) -> list[dict]:
        with self.lock:
            return [h for _, h, _ in self.sent if h["type"] == "energy"]


class Memory:
    def __init__(self):
        self.writes: list[tuple[str, str]] = []

    def insertData(self, key, value):
        self.writes.append((key, value))


class Session:
    def __init__(self):
        self.memory = Memory()
        self.closed = False

    def service(self, name):
        assert name == "ALMemory"
        return self.memory

    def close(self):
        self.closed = True


@pytest.fixture
def device():
    made = []

    def make(source=None):
        session, conn = Session(), Conn()
        dev = AudioInput(
            source or FakeAudioSource(), "duplicate", connect=lambda: session
        )
        dev.connected(conn)
        made.append(dev)
        return dev, conn, session

    yield make
    for dev in made:
        dev.stop()


def need(*formats, energy=False):
    return {"type": "need", "formats": list(formats), "energy": energy}


def test_silence_comes_in_chunks_at_the_nao_cadence(device):
    dev, conn, session = device()
    dev.start()
    dev.message(conn, need(FRONT), b"")
    time.sleep(1.0)
    chunks = conn.pcm(FRONT)
    assert 10 <= len(chunks) <= 13  # 1365 samples at 16 kHz: one every 85 ms
    assert all(c.shape == (CHUNK[16000], 1) and not c.any() for _, _, c in chunks)
    gaps = np.diff([t for t, _, _ in chunks])
    assert np.all(gaps > 0.05)  # paced, never a burst
    assert session.memory.writes == [
        ("NaoqiSim/Audio/Source", "fake"),
        ("NaoqiSim/Audio/Channels", "duplicate"),
    ]


def test_a_played_tone_reaches_each_format_with_its_pitch(device):
    dev, conn, _ = device()
    dev.start()
    dev.message(conn, need(FRONT, ALL), b"")
    take = dev.source.play(tone(440, 0.6, 16000), 16000)  # type: ignore[attr-defined]
    take.wait(2)
    time.sleep(0.3)
    low = np.concatenate([c[:, 0] for _, _, c in conn.pcm(FRONT)])
    high = np.concatenate([c for _, _, c in conn.pcm(ALL)])
    loud = low[np.abs(low) > 1000]
    assert peak_hz(low[: len(low) // 1365 * 1365], 16000) == pytest.approx(440, abs=12)
    assert len(loud) > 0.4 * 16000
    assert np.max(np.abs(low)) == pytest.approx(8000, rel=0.05)
    assert high.shape[1] == 4 and np.array_equal(high[:, 0], high[:, 3])  # duplicated
    assert peak_hz(high[:, 0], 48000) == pytest.approx(440, abs=12)


def test_a_need_before_start_is_served_after_it_and_stop_resets_the_keys(device):
    dev, conn, session = device()
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.2)
    assert conn.pcm(FRONT) == []  # NaoqiSim step 6 has not started the device yet
    dev.start()
    time.sleep(0.3)
    assert conn.pcm(FRONT)
    dev.stop()
    sent = len(conn.sent)
    time.sleep(0.2)
    assert len(conn.sent) == sent
    assert session.memory.writes[-2:] == [
        ("NaoqiSim/Audio/Source", "none"),
        ("NaoqiSim/Audio/Channels", "none"),
    ]
    assert session.closed


class BlockingSource:
    """A silent source whose `read` blocks while `gate` is clear, the way a microphone's
    could on a stalled machine; `reading` is set once a read has blocked."""

    name = "fake"

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.reading = threading.Event()

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def skip(self) -> None:
        pass

    def read(self, start: float, frames: int) -> np.ndarray:
        if not self.gate.is_set():
            self.reading.set()
            self.gate.wait()
        return np.zeros((frames, 4), np.int16)


def test_nothing_is_sent_after_stop_returns_even_with_a_block_in_flight(
    device, monkeypatch
):
    """A stop while the producer is mid-block: the stop waits for it (up to the join timeout)
    and the block is dropped, never sent after `stop()` returned. The failure this pins was
    seen once on a loaded CI runner: a chunk after `stop()`, when the producer was waiting on
    the device's lock that the stop held while joining it."""
    monkeypatch.setattr(audio_input, "JOIN_TIMEOUT_S", 0.3)
    source = BlockingSource()
    dev, conn, _ = device(source)
    dev.start()
    dev.message(conn, need(FRONT), b"")
    deadline = time.monotonic() + 2
    while not conn.pcm(FRONT):
        assert time.monotonic() < deadline, "no chunk"
        time.sleep(0.01)
    source.gate.clear()
    assert source.reading.wait(1.0)  # the producer is now inside read()

    started = time.monotonic()
    dev.stop()
    took = time.monotonic() - started
    sent = len(conn.sent)
    source.gate.set()  # the read returns now, into a halted producer
    time.sleep(0.3)

    assert 0.25 <= took < 1.0  # waited for the join timeout, no longer
    assert len(conn.sent) == sent  # the block in flight was dropped


def test_an_empty_need_stops_production_and_a_new_one_resumes(device):
    dev, conn, _ = device()
    dev.start()
    dev.message(conn, need(ALL_SPLIT), b"")
    time.sleep(0.3)
    dev.message(conn, need(), b"")
    time.sleep(0.05)
    count = len(conn.sent)
    time.sleep(0.3)
    assert len(conn.sent) == count
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.3)
    assert conn.pcm(FRONT)
    header = conn.pcm(ALL_SPLIT)[0][1]
    assert (header["channels"], header["samples"]) == (4, CHUNK[48000])


def test_energy_follows_the_sound(device):
    dev, conn, _ = device()
    dev.start()
    dev.message(conn, need(energy=True), b"")
    dev.source.play(tone(1000, 0.5, 48000, 10000), 48000)  # type: ignore[attr-defined]
    time.sleep(1.0)
    values = [e["front"] for e in conn.energies()]
    assert len(values) >= 9  # one per 4096 samples
    assert max(values) == pytest.approx(10000 / np.sqrt(2), rel=0.05)
    assert values[-1] < 1
    assert conn.pcm(FRONT) == []  # energy alone sends no audio


def test_the_fake_room_hears_what_the_robot_plays():
    source = FakeAudioSource()
    at = time.monotonic() + 1.0
    voice = tone(1000, 0.2, 22050)  # the speech engine's rate
    source.hear(voice[:2205].tobytes(), 22050, 1, at)  # two 100 ms chunks, back to back
    source.hear(voice[2205:].tobytes(), 22050, 1, at + 0.1)
    assert not source.read(at - 0.01, 480).any()  # not before it is due
    heard = source.read(at, 9600)  # 0.2 s at 48 kHz
    assert np.array_equal(heard[:, 0], heard[:, 3])  # on every microphone
    assert peak_hz(heard[:, 0], BASE_RATE) == pytest.approx(1000, abs=10)
    assert np.abs(heard[100:-100]).max() == pytest.approx(
        audio_input.ROBOT_VOICE_GAIN * 8000, rel=0.05
    )
    seam = heard[4790:4810, 0]  # where the two chunks meet: no gap
    assert np.abs(seam).max() > 1000
    assert not source.read(at + 0.2, 480).any()


def test_a_cut_stops_the_robots_voice_in_the_room():
    source = FakeAudioSource()
    at = time.monotonic() + 1.0
    source.hear(tone(1000, 0.1, 22050).tobytes(), 22050, 1, at)
    source.hear(tone(1000, 0.1, 22050).tobytes(), 22050, 1, at + 0.1)
    source.hear(b"", 22050, 1, at + 0.05)  # stopped half way through the first chunk
    assert np.abs(source.read(at, 2400)).max() > 1000  # 0 to 50 ms: heard
    assert not source.read(at + 0.05, 9600).any()  # nothing after the cut


def test_the_robot_is_heard_through_the_audio_output(device):
    """What the audio output plays reaches a subscriber, as on a NAO: nothing mutes it."""
    dev, conn, _ = device()
    output = AudioOutput(MemorySink())
    output.listeners.append(dev.source.hear)  # type: ignore[attr-defined]
    dev.start()
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.3)
    header = {"cmd": "play", "rate": 22050, "channels": 1, "format": "s16le"}
    speech = tone(500, 0.6, 22050).tobytes()
    started = time.monotonic()
    output.play_stream(io.BytesIO(speech), header)
    time.sleep(0.4)
    received = [(t, c[:, 0]) for t, _, c in conn.pcm(FRONT)]
    loud = [t - (len(c) - np.arange(len(c))) / 16000 for t, c in received]
    times = np.concatenate(loud)
    values = np.concatenate([c for _, c in received])
    during = (times > started + 0.1) & (times < started + 0.5)
    assert peak_hz(values[during], 16000) == pytest.approx(500, abs=12)
    assert np.abs(values[during]).max() == pytest.approx(
        audio_input.ROBOT_VOICE_GAIN * 8000, rel=0.1
    )
    assert np.abs(values[times < started - 0.05]).max() == 0  # silence before
    assert np.abs(values[times > started + 0.75]).max() == 0  # and after


# --- The microphone --------------------------------------------------------------------------


class FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.paused = threading.Event()  # set: the room is silent, nothing captured

    def start(self):
        self.calls.append("start")
        block = np.full(self.kwargs["blocksize"], 3000, dtype="<i2").tobytes()

        def feed():
            while "stop" not in self.calls:
                if not self.paused.is_set():
                    self.kwargs["callback"](block, self.kwargs["blocksize"], None, None)
                time.sleep(0.01)

        threading.Thread(target=feed, daemon=True).start()

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def fake_sounddevice(monkeypatch):
    streams: list[FakeInputStream] = []
    module = types.ModuleType("sounddevice")

    def raw_input_stream(**kwargs):
        streams.append(FakeInputStream(**kwargs))
        return streams[-1]

    module.RawInputStream = raw_input_stream  # type: ignore[attr-defined]
    module.query_devices = lambda kind=None: {"name": "fake mic"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return streams, module


def test_the_microphone_is_open_for_the_whole_run_whatever_naoqi_needs(
    device, fake_sounddevice
):
    """A NAO's microphones are always on: the stream opens at start and closes at stop, not
    with each subscription (speech recognition subscribes around each listening); audio
    captured while nothing was needed is not sent when a need comes back."""
    streams, _ = fake_sounddevice
    dev, conn, session = device(source=MicSource())
    dev.start()
    assert len(streams) == 1 and streams[0].calls == ["start"]  # open before any need
    kwargs = streams[0].kwargs
    assert (kwargs["samplerate"], kwargs["channels"], kwargs["dtype"]) == (
        48000,
        1,
        "int16",
    )
    assert kwargs["latency"] == "low"  # little capture delay, as a NAO's
    for _ in range(3):  # listening on, off, on...
        dev.message(conn, need(FRONT), b"")
        time.sleep(0.3)
        dev.message(conn, need(), b"")
    assert len(streams) == 1 and streams[0].calls == [
        "start"
    ]  # never reopened, still on
    chunks = [c for _, _, c in conn.pcm(FRONT)]
    assert chunks and np.abs(chunks[-1]).max() > 2500  # what it captured
    dev.stop()
    assert streams[0].calls == ["start", "stop", "close"]
    assert ("NaoqiSim/Audio/Source", "mic") in session.memory.writes


def test_a_need_coming_back_gets_live_audio_not_the_backlog(fake_sounddevice):
    streams, _ = fake_sounddevice
    """What the open microphone captured while nothing read it is dropped when reading
    resumes: the first block is the room now, not up to 200 ms ago."""
    mic = MicSource()
    mic.open()
    try:
        time.sleep(0.1)  # blocks pile up, nobody reads
        assert np.abs(mic.read(0.0, 480)).max() > 2500  # the backlog, as it was
        time.sleep(0.1)
        streams[0].paused.set()
        time.sleep(0.05)  # a block in flight has landed
        mic.skip()
        assert np.abs(mic.read(0.0, 480)).max() == 0  # dropped: nothing captured since
    finally:
        mic.close()


def test_check_mic_needs_an_input_device(fake_sounddevice):
    _, module = fake_sounddevice
    check_mic()

    def none(kind=None):
        raise ValueError("No input device matching")

    module.query_devices = none
    with pytest.raises(DeviceUnavailableError, match="no default input device"):
        check_mic()
