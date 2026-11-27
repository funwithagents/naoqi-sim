"""The audio input: the robot's microphones, fed into the `ALAudioDevice` replacement
(specs/host/audio-input.md).

A device served on the host link (`host_link.py`): the container side says which formats its
subscribers need, and this side produces each of them in real time from its source, cut in chunks,
so the Python 2.7 side only routes buffers. The source is either the host's microphone or the fake
source, a quiet room in which code plays sounds (`FakeAudioSource`, the input side's counterpart of
the audio output's `MemorySink`). The robot hears itself, as a NAO does: the microphone hears the
host's loudspeaker, and the fake room hears what the audio output plays (`FakeAudioSource.hear`).

Everything is made from one base signal, 48 kHz with four channels in NAO order (left, right,
front, rear), advanced in 10 ms blocks on the wall clock.
"""

import logging
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from naoqi_sim import stack
from naoqi_sim.errors import DeviceUnavailableError

log = logging.getLogger(__name__)

SERVICE = "ALAudioDevice"  # the container-side service on the host link
SOURCE_KEY = "NaoqiSim/Audio/Source"
CHANNELS_KEY = "NaoqiSim/Audio/Channels"

BASE_RATE = 48000
MICS = ("left", "right", "front", "rear")  # NAO order, the base signal's columns
BLOCK = 480  # 10 ms at 48 kHz: the producer's step
BLOCK_S = BLOCK / BASE_RATE
# Samples per channel in each chunk, per rate: about 85 ms, the values clients report from NAO
# robots (the 2.1 docs say 170 ms). Provisional: specs/host/audio-input.md, open question 1.
CHUNK = {48000: 4096, 16000: 1365}
ENERGY_BLOCK = 4096  # base samples per energy value
# The robot's own voice in the fake room, relative to what it plays: a placeholder until a NAO's
# coupling is measured (specs/host/audio-input.md, open question 3).
ROBOT_VOICE_GAIN = 0.5
MAX_LATE_S = 0.5  # a producer further behind than this skips ahead instead of bursting
MIC_BACKLOG = 20  # captured blocks kept at most (200 ms) before the oldest are dropped
JOIN_TIMEOUT_S = 1.0

Format = tuple[
    int, str, bool
]  # (rate, channel, deinterleaved), as audio-device.md defines it


def _lowpass(taps: int = 97, cutoff: float = 7200.0) -> np.ndarray:
    """The windowed-sinc filter for a factor of 3 between 16 and 48 kHz (unity gain)."""
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / BASE_RATE * n) * np.blackman(taps)
    return h / h.sum()


LOWPASS = _lowpass()


def upsample(x: np.ndarray) -> np.ndarray:
    """16 kHz to 48 kHz, (n, ch) to (3n, ch): zeros stuffed between samples, then filtered."""
    stuffed = np.zeros((len(x) * 3, x.shape[1]))
    stuffed[::3] = x
    delay = (len(LOWPASS) - 1) // 2
    out = np.empty_like(stuffed)
    for c in range(x.shape[1]):
        out[:, c] = np.convolve(stuffed[:, c], LOWPASS * 3)[
            delay : delay + len(stuffed)
        ]
    return out


class Decimator:
    """48 kHz to 16 kHz, continuous across calls (no seam at block boundaries)."""

    def __init__(self, channels: int = 4):
        self._history = np.zeros((len(LOWPASS) - 1, channels))
        self._phase = 0

    def __call__(self, block: np.ndarray) -> np.ndarray:
        buf = np.vstack([self._history, block])
        windows = np.lib.stride_tricks.sliding_window_view(buf, len(LOWPASS), axis=0)
        picked = windows[self._phase : len(block) : 3]  # (m, channels, taps)
        self._history = buf[len(block) :]
        self._phase = (self._phase - len(block)) % 3
        return picked @ LOWPASS[::-1]


def _spread(mono: np.ndarray, policy: str) -> np.ndarray:
    """A mono signal as four channels: copied to all (`duplicate`), or on front only (`silence`)."""
    if policy == "duplicate":
        return np.repeat(mono[:, None], 4, axis=1)
    out = np.zeros((len(mono), 4))
    out[:, MICS.index("front")] = mono
    return out


def _clip16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(x), -32768, 32767).astype(np.int16)


# --- Sources ---------------------------------------------------------------------------------


class AudioSource(Protocol):
    """Where the audio comes from; `name` is what `NaoqiSim/Audio/Source` says."""

    name: str

    def open(self) -> None:
        """The device starts: open for the whole run (a NAO's microphones are always on)."""

    def close(self) -> None:
        """The device stops."""

    def skip(self) -> None:
        """The container side needs audio again: drop what came while nothing was read."""

    def read(self, start: float, frames: int) -> np.ndarray:
        """`frames` base samples, (frames, 4) float, starting at `start` (time.monotonic())."""
        ...


class Take:
    """One sound played on the fake source: when it started and ends, on time.monotonic()."""

    def __init__(self, samples: np.ndarray, started_at: float):
        self.samples = samples  # (n, 4) float, 48 kHz
        self.started_at = started_at
        self.ended_at = started_at + len(samples) / BASE_RATE
        self._cut = threading.Event()

    @property
    def duration_s(self) -> float:
        return len(self.samples) / BASE_RATE

    @property
    def done(self) -> bool:
        return self._cut.is_set() or time.monotonic() >= self.ended_at

    def wait(self, timeout: float | None = None) -> bool:
        """Until the sound has played (or was stopped); False if `timeout` came first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.done:
            left = self.ended_at - time.monotonic()
            if deadline is not None:
                left = min(left, deadline - time.monotonic())
                if left <= 0:
                    return self.done
            self._cut.wait(max(0.0, left))
        return True

    def _stop(self, now: float) -> None:
        self.ended_at = min(self.ended_at, now)
        self._cut.set()


def load_sound(
    sound: str | Path | np.ndarray, rate: int | None = None
) -> tuple[np.ndarray, int]:
    """A WAV file or an int16 array as ((n, channels) int16, rate); ValueError for anything the
    fake source does not take (specs/host/audio-input.md, "The fake source")."""
    if isinstance(sound, (str, Path)):
        try:
            with wave.open(str(sound), "rb") as w:
                width, channels, rate = (
                    w.getsampwidth(),
                    w.getnchannels(),
                    w.getframerate(),
                )
                data = w.readframes(w.getnframes())
        except (OSError, EOFError, wave.Error) as e:
            raise ValueError(f"{sound}: cannot read it as a WAV file ({e})") from None
        if width != 2:
            raise ValueError(
                f"{sound}: {8 * width}-bit samples; the fake source takes 16-bit"
            )
        samples = np.frombuffer(data, dtype="<i2").reshape(-1, channels)
        where = str(sound)
    else:
        samples = np.asarray(sound)
        if samples.dtype != np.int16:
            raise ValueError(
                f"an array of {samples.dtype}; the fake source takes int16"
            )
        if samples.ndim == 1:
            samples = samples[:, None]
        if samples.ndim != 2:
            raise ValueError(
                f"an array of shape {samples.shape}; expected (n,) or (n, 4)"
            )
        if rate is None:
            raise ValueError("an array needs its rate (16000 or 48000)")
        where = "the array"
    if samples.shape[1] not in (1, 4):
        raise ValueError(f"{where}: {samples.shape[1]} channels; expected 1 or 4")
    if rate not in (16000, 48000):
        raise ValueError(f"{where}: {rate} Hz; expected 16000 or 48000")
    return samples, rate


class FakeAudioSource:
    """A quiet room in which code plays sounds: silence, plus every take playing now, mixed.

    `play` is thread-safe and works at any time: a sound plays from the moment it is called on
    the wall clock, heard by whoever subscribes while it plays."""

    name = "fake"

    def __init__(self, mono: str = "duplicate"):
        self._mono = mono
        self._takes: list[Take] = []
        self._voice: list[Take] = []  # what the robot plays, as the room hears it
        self._lock = threading.Lock()

    def play(self, sound: str | Path | np.ndarray, rate: int | None = None) -> Take:
        """Start `sound` now: a WAV path (16-bit, mono or 4 channels, 16 or 48 kHz) or an int16
        array, (n,) mono or (n, 4) in NAO order, with its `rate`."""
        samples, rate = load_sound(sound, rate)
        signal = samples.astype(np.float64)
        if rate == 16000:
            signal = upsample(signal)
        if signal.shape[1] == 1:
            signal = _spread(signal[:, 0], self._mono)
        take = Take(signal, time.monotonic())
        with self._lock:
            self._takes.append(take)
        return take

    def stop(self) -> None:
        """End every sound playing now."""
        now = time.monotonic()
        with self._lock:
            takes, self._takes = self._takes, []
            self._voice = []
        for take in takes:
            take._stop(now)

    def hear(self, chunk: bytes, rate: int, channels: int, at: float) -> None:
        """What the robot plays, due at `at`: added to the room, on every microphone, at
        ROBOT_VOICE_GAIN. An empty chunk: the robot's audio was cut at `at`. Registered as a
        listener of the audio output (specs/host/audio-output.md, "Listeners")."""
        if not chunk:
            with self._lock:
                kept = []
                for take in self._voice:
                    if take.started_at < at:
                        keep = round((at - take.started_at) * BASE_RATE)
                        take.samples = take.samples[:keep]
                        take.ended_at = min(take.ended_at, at)
                        kept.append(take)
                self._voice = kept
            return
        pcm = np.frombuffer(chunk, dtype="<i2").astype(np.float64)
        mono = pcm.reshape(-1, channels).mean(axis=1)
        n_out = round(len(mono) * BASE_RATE / rate)
        times = np.arange(n_out) * rate / BASE_RATE
        resampled = np.interp(times, np.arange(len(mono)), mono)
        voice = Take(_spread(resampled * ROBOT_VOICE_GAIN, "duplicate"), at)
        with self._lock:
            self._voice = [t for t in self._voice if t.ended_at > at - 1.0] + [voice]

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def skip(self) -> None:
        pass  # takes play on the clock, not from a backlog

    def read(self, start: float, frames: int) -> np.ndarray:
        out = np.zeros((frames, 4))
        end = start + frames / BASE_RATE
        with self._lock:
            self._takes = [
                t
                for t in self._takes
                if t.ended_at > start - 1.0 and not t._cut.is_set()
            ]
            takes = self._takes + self._voice
        for take in takes:
            if take.ended_at <= start or take.started_at >= end:
                continue
            first = round((start - take.started_at) * BASE_RATE)
            lo, hi = (
                max(first, 0),
                min(first + frames, round(take.duration_s * BASE_RATE)),
            )
            if hi > lo:
                out[lo - first : hi - first] += take.samples[lo:hi]
        return out


def check_mic() -> None:
    """The host microphone can open: PortAudio is there and there is a default input device."""
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        raise DeviceUnavailableError(
            f"audio_input.source 'mic': sounddevice cannot load PortAudio ({e})"
        ) from None
    try:
        sd.query_devices(kind="input")
    except Exception as e:  # noqa: BLE001 (PortAudio's errors are not typed)
        raise DeviceUnavailableError(
            f"audio_input.source 'mic': no default input device ({e})"
        ) from None


class MicSource:
    """The host's default input device: 48 kHz mono int16, captured in 10 ms blocks while open."""

    name = "mic"

    def __init__(self, mono: str = "duplicate"):
        self._mono = mono
        self._stream: Any = None
        self._blocks: deque[bytes] = deque(maxlen=MIC_BACKLOG)
        self._pending = b""
        self._lock = threading.Lock()
        self.captured = 0  # blocks captured since created, for diagnostics
        self.peak = 0  # the loudest sample captured

    def open(self) -> None:
        import sounddevice as sd

        def captured(indata, frames, time_info, status) -> None:
            data = bytes(indata)
            with self._lock:
                self._blocks.append(data)
                self.captured += 1
                if data:
                    self.peak = max(
                        self.peak, int(np.abs(np.frombuffer(data, "<i2")).max())
                    )

        self._stream = sd.RawInputStream(
            samplerate=BASE_RATE,
            channels=1,
            dtype="int16",
            blocksize=BLOCK,
            latency="low",
            callback=captured,
        )
        self._stream.start()
        log.info("audio input: the microphone is live")

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
            log.info("audio input: the microphone is off")
        self.skip()

    def skip(self) -> None:
        with self._lock:
            self._blocks.clear()
            self._pending = b""

    def read(self, start: float, frames: int) -> np.ndarray:
        need = frames * 2
        with self._lock:
            data = self._pending
            while len(data) < need and self._blocks:
                data += self._blocks.popleft()
            self._pending = data[need:]
        data = data[:need].ljust(need, b"\0")  # not captured yet: silence
        return _spread(np.frombuffer(data, dtype="<i2").astype(np.float64), self._mono)


# --- The device ------------------------------------------------------------------------------


class _Stream:
    """One needed format: the samples waiting to make its next chunk."""

    def __init__(self, fmt: Format):
        self.format = fmt
        self.pending = np.zeros((0, 4 if fmt[1] == "all" else 1))

    def add(self, block: np.ndarray) -> list[np.ndarray]:
        self.pending = np.vstack([self.pending, block])
        size = CHUNK[self.format[0]]
        chunks = []
        while len(self.pending) >= size:
            chunks.append(self.pending[:size])
            self.pending = self.pending[size:]
        return chunks

    def message(self, chunk: np.ndarray) -> tuple[dict, bytes]:
        rate, channel, deinterleaved = self.format
        samples = _clip16(chunk)
        data = (samples.T if deinterleaved else samples).tobytes()
        return (
            {
                "type": "pcm",
                "format": {
                    "rate": rate,
                    "channel": channel,
                    "deinterleaved": deinterleaved,
                },
                "channels": samples.shape[1],
                "samples": len(samples),
            },
            data,
        )


def parse_need(header: dict) -> tuple[set[Format], bool]:
    formats = {
        (int(f["rate"]), str(f["channel"]), bool(f["deinterleaved"]))
        for f in header.get("formats", [])
    }
    return formats, bool(header.get("energy", False))


class AudioInput:
    """The host link's handler for `ALAudioDevice`: produces the formats it needs from `source`,
    from `start()` to `stop()`."""

    service = SERVICE  # the container-side service it serves on the host link

    def __init__(
        self,
        source: AudioSource,
        mono: str,
        connect: Callable[[], Any] | None = None,
    ):
        self.source = source
        self._mono = mono
        self._connect = connect or (lambda: stack.connect())
        self._lock = threading.RLock()
        self._conn: Any = None
        self._formats: set[Format] = set()
        self._energy = False
        # What the producer reads, as one reference assigned under the lock: the producer never
        # takes the lock, so a stop that joins it under the lock cannot wait on it (and leak a
        # chunk after it returns, as it did once on a loaded CI runner).
        self._need: tuple[Any, frozenset[Format], bool] = (None, frozenset(), False)
        self._started = False
        self._producer: threading.Thread | None = None
        self._halt = threading.Event()
        self._session: Any = None
        self._memory: Any = None

    # --- Lifecycle (NaoqiSim step 6) --------------------------------------------------------

    def start(self) -> None:
        self._session = self._connect()
        self._memory = self._session.service("ALMemory")
        self._publish(self.source.name, self._mono)
        # Open for the whole run, as a NAO's microphones are, whatever NAOqi asks for: the
        # producer follows the need, the source does not (specs/host/audio-input.md).
        self.source.open()
        with self._lock:
            self._started = True
            self._update()

    def stop(self) -> None:
        """Stop producing, close the source, write `none` back. Idempotent."""
        with self._lock:
            self._started = False
            self._update()
        self.source.close()
        if isinstance(self.source, FakeAudioSource):
            self.source.stop()
        if self._session is not None:
            self._publish("none", "none")
            self._session.close()
            self._session = None

    # --- The host link's handler ----------------------------------------------------------

    def connected(self, conn: Any) -> None:
        with self._lock:
            self._conn = conn
            self._update()

    def message(self, conn: Any, header: dict, payload: bytes) -> None:
        if header.get("type") != "need":
            return
        with self._lock:
            self._formats, self._energy = parse_need(header)
            self._update()

    def disconnected(self, conn: Any) -> None:
        with self._lock:
            if self._conn is conn:
                self._conn = None
                self._formats, self._energy = (
                    set(),
                    False,
                )  # sent again after a reconnect
                self._update()

    # --- Production -----------------------------------------------------------------------

    def _needed(self) -> bool:
        return (
            self._started
            and self._conn is not None
            and (bool(self._formats) or self._energy)
        )

    def _update(self) -> None:
        """Start or stop the producer to match the need (under the lock), which it reads as one
        snapshot."""
        self._need = (self._conn, frozenset(self._formats), self._energy)
        running = self._producer is not None
        if self._needed() and not running:
            self._halt = threading.Event()
            self.source.skip()  # what was captured while nobody listened is not sent
            self._producer = threading.Thread(
                target=self._produce,
                args=(self._halt,),
                name="naoqi-sim-audio-input",
                daemon=True,
            )
            self._producer.start()
        elif not self._needed() and running:
            self._halt.set()
            producer, self._producer = self._producer, None
            if producer is not None and producer is not threading.current_thread():
                producer.join(timeout=JOIN_TIMEOUT_S)

    def _produce(self, halt: threading.Event) -> None:
        streams: dict[Format, _Stream] = {}
        decimator: Decimator | None = None
        energy = np.zeros((0, 4))
        t0 = time.monotonic()
        k = 0
        while not halt.is_set():
            block_start = t0 + k * BLOCK_S
            due = block_start + BLOCK_S  # a block is made once its last sample is due
            now = time.monotonic()
            if due > now:
                if halt.wait(due - now):
                    return
            elif now - due > MAX_LATE_S:  # far behind (a stalled machine): skip ahead
                k += int((now - due) / BLOCK_S)
                continue
            k += 1
            conn, formats, want_energy = self._need  # one reference: no lock needed
            if conn is None:
                continue
            block = self.source.read(block_start, BLOCK)
            if halt.is_set():  # halted during the read: the block is dropped, not sent
                return
            for fmt in formats - streams.keys():
                streams[fmt] = _Stream(fmt)
            for fmt in streams.keys() - formats:
                del streams[fmt]
            low = None
            if any(f[0] == 16000 for f in streams):
                decimator = decimator or Decimator()
                low = decimator(block)
            else:
                decimator = None
            for fmt, stream in streams.items():
                rate, channel, _ = fmt
                part = block if rate == BASE_RATE else low
                assert part is not None
                if channel != "all":
                    part = part[:, MICS.index(channel)][:, None]
                for chunk in stream.add(part):
                    conn.send(*stream.message(chunk))
            if want_energy:
                energy = np.vstack([energy, block])
                if len(energy) >= ENERGY_BLOCK:
                    rms = np.sqrt(np.mean(energy[:ENERGY_BLOCK] ** 2, axis=0))
                    energy = energy[ENERGY_BLOCK:]
                    conn.send(
                        {
                            "type": "energy",
                            **dict(zip(MICS, map(float, rms), strict=True)),
                        }
                    )
            else:
                energy = np.zeros((0, 4))

    def _publish(self, source: str, channels: str) -> None:
        for key, value in ((SOURCE_KEY, source), (CHANNELS_KEY, channels)):
            try:
                self._memory.insertData(key, value)
            except Exception as e:  # noqa: BLE001 (best effort: NAOqi may be stopping too)
                log.debug("audio input: could not write %s = %s: %s", key, value, e)
