"""The audio output: the simulated robot's loudspeakers on the host, a dumb PCM player and mixer
the containers stream into, as a NAO's sound server (specs/host/audio-output.md).

Protocol (TCP, one command per connection): a JSON header line, then a body.
  {"cmd": "play", "stream": "speech", "rate": 22050, "channels": 1, "format": "s16le",
   "volume": 1.0, "pan": 0.0}, then raw PCM until the sender closes; the connection is closed
   when the stream has played, was stopped, or a newer play of the same name started.
  {"cmd": "stop", "stream": "speech"} stops that stream; without "stream", every stream.
  {"cmd": "set", "stream": ..., "volume": ..., "pan": ...} changes a playing stream.
  {"cmd": "pause" | "resume", "stream": ...} holds a stream, or lets it go on.
Streams of different names play together: a mixer sums them at the loudspeakers' format (48 kHz
stereo) in 20 ms ticks, paced in real time, and feeds the mix to an `AudioSink` (the output
device, nothing, a WAV file or memory) and to the listeners. A running `NaoqiSim` owns it; there is
no command to start it on its own.
"""

import dataclasses
import io
import json
import logging
import socketserver
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

RATE = 48000  # the mix: a NAO's two ear loudspeakers
CHANNELS = 2
TICK_S = 0.02  # the mixer's unit of mixing, feeding, pacing and stop latency
TICK_FRAMES = int(RATE * TICK_S)
JOIN_S = (
    0.1  # a stream joins the mix once this much of it has arrived (or it has ended)
)
QUEUE_S = 0.2  # what a stream may buffer ahead of the mix: the socket paces the sender
RESYNC_S = 0.2  # how far behind its schedule the mixer still catches up
DEFAULT_STREAM = "default"


class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """The mix starts: a stream joined after silence (always 48000, 2)."""

    def feed(self, chunk: bytes) -> None:
        """The mix, interleaved s16le, one tick."""

    def end(self, interrupted: bool) -> None:
        """The mix went quiet: the last stream ended, or a stop of every stream cut it."""


class NullSink:
    """Discards the audio (the audio output still paces it)."""

    def begin(self, rate: int, channels: int) -> None:
        pass

    def feed(self, chunk: bytes) -> None:
        pass

    def end(self, interrupted: bool) -> None:
        pass


class DevicePlayer:
    """Plays the mix on an output device; `sounddevice` is imported at the first run.

    `muted`, the user's: while set, the device plays silence of the same length, so its timing
    does not change and nothing before the sink notices (specs/host/audio-output.md, "Muting
    the loudspeakers")."""

    def __init__(self, device: int | str | None = None):
        self.device = device
        self.muted = False
        self._stream: Any = None

    def begin(self, rate: int, channels: int) -> None:
        import sounddevice as sd

        self._stream = sd.RawOutputStream(
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=0,
            device=self.device,
            # The device's own buffer as short as it allows, so the robot's voice leaves the
            # loudspeaker about when it is due (PulseAudio buffered seconds at sounddevice's
            # default "high" latency, measured on CI).
            latency="low",
        )
        self._stream.start()

    def feed(self, chunk: bytes) -> None:
        if self._stream is not None:
            self._stream.write(bytes(len(chunk)) if self.muted else chunk)

    def end(self, interrupted: bool) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            # A cut mix stops at once; a finished one plays out what is queued.
            if interrupted:
                stream.abort()
            else:
                stream.stop()
        finally:
            stream.close()


class WavSink:
    """Writes the mix as 48 kHz stereo 16-bit WAV, the runs one after the other."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._wav: wave.Wave_write | None = None

    def begin(self, rate: int, channels: int) -> None:
        if self._wav is None:
            self._wav = wave.open(str(self.path), "wb")  # noqa: SIM115 (spans runs, closed by close())
            self._wav.setnchannels(channels)
            self._wav.setsampwidth(2)
            self._wav.setframerate(rate)

    def feed(self, chunk: bytes) -> None:
        if self._wav is not None:
            self._wav.writeframes(chunk)  # patches the header: readable between runs

    def end(self, interrupted: bool) -> None:
        pass

    def close(self) -> None:
        """Finish the file."""
        if self._wav is not None:
            self._wav.close()
            self._wav = None


@dataclass
class Playback:
    """One stream (or one run of the mix, `stream == "mix"`) as a `MemorySink` received it;
    `pcm` is the stream's own audio, before mixing; times are `time.monotonic()` seconds."""

    stream: str
    rate: int
    channels: int
    pcm: bytes = b""
    started_at: float = 0.0
    ended_at: float | None = None
    interrupted: bool = False

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / (2.0 * self.channels * self.rate)


class MemorySink:
    """Keeps every stream and every run of the mix, for tests to assert on what was played."""

    def __init__(self) -> None:
        self._playbacks: list[Playback] = []
        self._open: dict[str, Playback] = {}
        self._mixes: list[Playback] = []
        self._changed = threading.Condition()

    @property
    def playbacks(self) -> list[Playback]:
        """The streams, in the order they joined the mix."""
        with self._changed:
            return [dataclasses.replace(p) for p in self._playbacks]

    @property
    def mixes(self) -> list[Playback]:
        """The runs of the mix (48 kHz stereo), in order."""
        with self._changed:
            return [dataclasses.replace(p) for p in self._mixes]

    def wait_for(
        self, predicate: Callable[[Playback], bool], timeout: float = 5.0
    ) -> Playback:
        """The first ended stream the predicate accepts."""
        end = time.monotonic() + timeout
        with self._changed:
            while True:
                for p in self._playbacks:
                    if p.ended_at is not None and predicate(p):
                        return dataclasses.replace(p)
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no matching playback in {timeout} s")
                self._changed.wait(left)

    # The mix
    def begin(self, rate: int, channels: int) -> None:
        with self._changed:
            self._mixes.append(
                Playback("mix", rate, channels, started_at=time.monotonic())
            )

    def feed(self, chunk: bytes) -> None:
        with self._changed:
            self._mixes[-1].pcm += chunk

    def end(self, interrupted: bool) -> None:
        with self._changed:
            self._mixes[-1].ended_at = time.monotonic()
            self._mixes[-1].interrupted = interrupted

    # Each stream, as received
    def stream_begin(self, stream: str, rate: int, channels: int) -> None:
        with self._changed:
            playback = Playback(stream, rate, channels, started_at=time.monotonic())
            self._playbacks.append(playback)
            self._open[stream] = playback
            self._changed.notify_all()

    def stream_feed(self, stream: str, chunk: bytes) -> None:
        with self._changed:
            self._open[stream].pcm += chunk

    def stream_end(self, stream: str, interrupted: bool) -> None:
        with self._changed:
            playback = self._open.pop(stream)
            playback.ended_at = time.monotonic()
            playback.interrupted = interrupted
            self._changed.notify_all()


# listener(chunk, rate, channels, at): a tick of the mix fed to the sink, due to play at `at`
# (time.monotonic()); an empty chunk says a stop of every stream cut the mix at `at`.
Listener = Callable[[bytes, int, int, float], None]


class _Stream:
    """One play: what its connection has received and the mixer not yet mixed."""

    def __init__(self, name: str, header: dict):
        self.name = name
        self.rate = int(header.get("rate", 22050))
        self.channels = max(1, int(header.get("channels", 1)))
        self.volume = float(header.get("volume", 1.0))
        self.pan = float(header.get("pan", 0.0))
        self.paused = False
        self.pending = np.zeros(
            (0, self.channels), dtype=np.int16
        )  # frames not yet mixed
        self.phase = (
            0.0  # where the next output frame falls in `pending`, in input frames
        )
        self.eof = False  # the sender closed: no more frames will come
        self.cut = False  # stopped, or replaced by a newer play of the same name
        self.joined = False
        self.done = threading.Event()  # mixed to its end, or cut
        self.ended_at = 0.0  # when its last frame plays

    def ready(self) -> bool:
        return self.eof or len(self.pending) >= self.rate * JOIN_S

    def take(self) -> tuple[np.ndarray, np.ndarray, bool]:
        """The next tick: (its 48 kHz stereo float frames, the input frames it used, finished)."""
        step = self.rate / RATE
        positions = self.phase + step * np.arange(TICK_FRAMES)
        lower = np.floor(positions).astype(np.int64)
        usable = lower + 1 < len(self.pending)
        if self.eof and len(self.pending) > 0:
            usable |= lower == len(self.pending) - 1  # the very last frame
        n = int(np.count_nonzero(usable))
        out = np.zeros((TICK_FRAMES, CHANNELS), dtype=np.float32)
        if n:
            src = self.pending.astype(np.float32)
            nxt = np.minimum(lower[:n] + 1, len(src) - 1)
            frac = (positions[:n] - lower[:n])[:, None]
            frames = src[lower[:n]] * (1 - frac) + src[nxt] * frac
            if self.channels == 1:
                frames = np.repeat(frames, 2, axis=1)
            elif self.channels > 2:
                frames = frames[:, :2]
            left = min(1.0, 1.0 - self.pan) * self.volume
            right = min(1.0, 1.0 + self.pan) * self.volume
            out[:n] = frames * np.array([left, right], dtype=np.float32)
        consumed = min(len(self.pending), int(np.floor(self.phase + step * n)))
        used = self.pending[:consumed]
        self.pending = self.pending[consumed:]
        self.phase = self.phase + step * n - consumed
        finished = self.eof and len(self.pending) == 0
        return out, used, finished


class AudioOutput:
    """Mixes the streams it receives into its sink, the newest play of a name replacing the
    older one. Its listeners hear the mix (the fake audio source: the robot hears itself)."""

    def __init__(
        self,
        sink: AudioSink,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.sink = sink
        self._on_event = on_event or (lambda e: log.debug("audio output: %s", e))
        self._streams: list[_Stream] = []
        self._changed = (
            threading.Condition()
        )  # guards _streams and every _Stream's fields
        self._mixer: threading.Thread | None = None
        # When the mix fed so far finishes playing (time.monotonic()); may be read from other
        # threads, a float assignment being atomic.
        self.playing_until = 0.0
        self.listeners: list[Listener] = []

    # -- the connections' side -------------------------------------------------------------
    def play_stream(self, rfile: io.BufferedIOBase, header: dict) -> None:
        """Receives one play until its sender closes, and returns once it has played (or was
        stopped, or replaced)."""
        name = str(header.get("stream") or DEFAULT_STREAM)
        stream = _Stream(name, header)
        frame_bytes = 2 * stream.channels
        chunk_bytes = max(frame_bytes, int(stream.rate * TICK_S) * frame_bytes)
        with self._changed:
            for older in self._streams:
                if older.name == name and not older.cut:
                    older.cut = True
            self._streams.append(stream)
            self._ensure_mixer()
            self._changed.notify_all()
        rest = b""
        while True:
            data = rfile.read(chunk_bytes)
            with self._changed:
                if stream.cut:
                    break
                if not data:
                    stream.eof = True
                    self._changed.notify_all()
                    break
                data = rest + data
                whole = len(data) - len(data) % frame_bytes
                rest = data[whole:]
                frames = np.frombuffer(data[:whole], dtype="<i2").reshape(
                    -1, stream.channels
                )
                stream.pending = np.concatenate([stream.pending, frames])
                self._changed.notify_all()
                # Back-pressure: the socket waits while the stream is far enough ahead.
                while not stream.cut and len(stream.pending) > stream.rate * QUEUE_S:
                    self._changed.wait(0.5)
                if stream.cut:
                    break
        stream.done.wait()
        _sleep_until(stream.ended_at)

    def stop(self, stream: str | None = None) -> None:
        """Stops that stream, or every stream."""
        with self._changed:
            for s in self._streams:
                if stream is None or s.name == stream:
                    s.cut = True
            self._changed.notify_all()
        self._on_event({"event": "stop-request", "stream": stream})

    def set(
        self, stream: str, volume: float | None = None, pan: float | None = None
    ) -> None:
        """Changes a playing stream's volume or pan, from its next tick."""
        with self._changed:
            for s in self._streams:
                if s.name == stream and not s.cut:
                    if volume is not None:
                        s.volume = float(volume)
                    if pan is not None:
                        s.pan = float(pan)

    def pause(self, stream: str, paused: bool = True) -> None:
        """Holds a stream (it stops being read and mixed), or lets it go on."""
        with self._changed:
            for s in self._streams:
                if s.name == stream and not s.cut:
                    s.paused = paused
            self._changed.notify_all()

    # -- the mixer ---------------------------------------------------------------------------
    def _ensure_mixer(self) -> None:
        if self._mixer is None or not self._mixer.is_alive():
            self._mixer = threading.Thread(
                target=self._mix, name="audio-mixer", daemon=True
            )
            self._mixer.start()

    def _mix(self) -> None:
        running = False  # inside a run of the mix: the sink has begun
        slot = 0.0  # when the next tick is due to play
        while True:
            with self._changed:
                for s in [s for s in self._streams if s.cut]:
                    self._finish(s, interrupted=True)
                if not self._streams and not running:
                    self._mixer = None  # a new play starts another mixer
                    return
                quiet = not self._streams  # the last stream has left
                active = [s for s in self._streams if s.ready() and not s.paused]
                if not running and not active:
                    self._changed.wait(TICK_S)  # nothing has enough audio yet
                    continue
                cut = self._last_cut
            if quiet:
                self._end_run(interrupted=cut)
                running = False
                continue
            if not running:
                running = True
                slot = time.monotonic()
                if not self._sink_call(self.sink.begin, RATE, CHANNELS):
                    continue
            # The ticks keep their schedule: a late wake-up is caught up by mixing the ticks
            # that are due back to back, so lateness never accumulates into the playback. Only
            # beyond RESYNC_S behind does the schedule restart from now, leaving a gap, as a
            # device that ran dry would.
            now = time.monotonic()
            if now - slot > RESYNC_S:
                slot = now
            at = slot
            # When this tick finishes playing: a tick fed while catching up plays no earlier than
            # now. A stream ending in it ends then, and so does the playing period.
            ends = max(at, now) + TICK_S
            mix = np.zeros((TICK_FRAMES, CHANNELS), dtype=np.float32)
            with self._changed:
                for s in active:
                    if s.cut or s not in self._streams:
                        continue
                    if not s.joined:
                        s.joined = True
                        self._record("stream_begin", s.name, s.rate, s.channels)
                        self._on_event(
                            {"event": "start", "stream": s.name, "rate": s.rate}
                        )
                    frames, used, finished = s.take()
                    mix += frames
                    if len(used):
                        self._record("stream_feed", s.name, used.tobytes())
                    if finished:
                        s.ended_at = ends
                        self._finish(s, interrupted=False)
                self._changed.notify_all()  # room in the streams' buffers
            chunk = np.clip(np.rint(mix), -32768, 32767).astype("<i2").tobytes()
            if not self._sink_call(self.sink.feed, chunk):
                continue
            self.playing_until = ends
            self._tell(chunk, at)
            slot = at + TICK_S
            _sleep_until(
                self.playing_until - TICK_S
            )  # one tick ahead: a device never runs dry

    _last_cut = False  # the last stream to leave was cut by a stop (set under _changed)

    def _finish(self, s: _Stream, interrupted: bool) -> None:
        """Takes a stream out of the mix (under _changed)."""
        if s in self._streams:
            self._streams.remove(s)
        if s.joined:
            self._record("stream_end", s.name, interrupted)
            self._on_event(
                {
                    "event": "interrupted" if interrupted else "end",
                    "stream": s.name,
                }
            )
        if interrupted:
            s.ended_at = time.monotonic()
        self._last_cut = interrupted
        s.done.set()

    def _end_run(self, interrupted: bool) -> None:
        if interrupted:
            self.playing_until = time.monotonic()
            self._tell(b"", self.playing_until)
        else:
            _sleep_until(self.playing_until)
        try:
            self.sink.end(interrupted=interrupted)
        except Exception as e:  # noqa: BLE001 (a sink must not stop the mixer)
            log.warning("audio output: the sink failed to end: %s", e)

    def _sink_call(self, fn: Callable[..., None], *args: Any) -> bool:
        """Calls the sink; if it fails, the streams of this run are cut (their plays return)
        and the run ends at the next tick, with `end(interrupted=True)`."""
        try:
            fn(*args)
            return True
        except Exception as e:  # noqa: BLE001 (a sink must not stop the mixer)
            log.warning("audio output: the sink failed: %s", e)
            with self._changed:
                for s in self._streams:
                    s.cut = True
                self._changed.notify_all()
            return False

    def _record(self, method: str, *args: Any) -> None:
        """A sink that keeps each stream (`MemorySink`) gets it as received."""
        fn = getattr(self.sink, method, None)
        if fn is not None:
            fn(*args)

    def _tell(self, chunk: bytes, at: float) -> None:
        for listener in list(self.listeners):
            try:
                listener(chunk, RATE, CHANNELS, at)
            except Exception as e:  # noqa: BLE001 (a listener must not stop the mix)
                log.warning("audio output: a listener failed: %s", e)


def _sleep_until(deadline: float) -> None:
    """Returns once `deadline` has passed: a sleep may end a hair early (Windows' timer
    granularity), and what follows (a play returning, `playing_until` in the past) relies on it."""
    while (left := deadline - time.monotonic()) > 0:
        time.sleep(left)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        try:
            header = json.loads(line.decode() or "{}")
        except ValueError:
            return
        assert isinstance(self.server, Server)
        output = self.server.audio_output
        cmd, stream = header.get("cmd"), header.get("stream")
        if cmd == "play":
            output.play_stream(self.rfile, header)
        elif cmd == "stop":
            output.stop(stream)
        elif cmd == "set" and stream:
            output.set(stream, header.get("volume"), header.get("pan"))
        elif cmd in ("pause", "resume") and stream:
            output.pause(stream, paused=cmd == "pause")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, audio_output: AudioOutput):
        super().__init__(addr, Handler)
        self.audio_output = audio_output
