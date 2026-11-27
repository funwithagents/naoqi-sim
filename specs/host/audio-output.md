---
code:
  - src/naoqi_sim/audio_output.py
  - src/naoqi_sim/sim.py
tests:
  - tests/test_audio_output.py
  - tests/test_sim.py
  - tests-e2e/test_speech_live.py
  - tests-e2e/test_audio_loopback_live.py
---

# Audio output

**Status:** Implemented

## Purpose

The robot's loudspeakers as a host device ([devices.md](devices.md)) the containers stream into. It plays PCM as it arrives, mixes the streams that play at once, and stops a stream on request. Its clients are the `tts` engine ([tts-engine.md](../container/tts-engine.md)) and the `ALAudioPlayer` replacement ([audio-player.md](../services/audio-player.md)).

On a NAO, the speech engine and the audio player are clients of the robot's sound server, which mixes every stream into the one stereo output of the ear loudspeakers; the microphones hear that mix. The audio output plays the sound server's part: one mixer, at the loudspeakers' format, and everything downstream (the device, a WAV file, memory, the fake microphone) gets what the loudspeakers would play.

It is named after its role, not after a loudspeaker: where the audio ends up is a seam, the audio sink, and a test's sink is memory.

## Decided

### Naming

- Module `src/naoqi_sim/audio_output.py`, class `AudioOutput`, config block `audio_output` ([config.md](../runtime/config.md)).
- It was first built as the "speaker" (class `Speaker`, command `naoqi-sim-speaker`), and before that the "sound card".
- The `tts` container's `NAOQI_SIM_SOUNDCARD` setting keeps its name: it is internal to the container recipes.

### Run by `NaoqiSim`

The audio output has no command of its own: a running `NaoqiSim` ([api.md](../runtime/api.md)) starts it in-process, listening on `0.0.0.0:9562`, before the containers, and stops it after them. The containers reach it at `host.docker.internal:9562`. Its events (`start`, `interrupted`, `end`, `stop-request`, per stream) go to the debug log.

### Protocol (TCP)

Each connection carries one command: a JSON header line, then a body. It stays its own protocol, off the host link ([devices.md](devices.md)): several streams are several connections.

- `{"cmd": "play", "stream": "speech", "rate": 22050, "channels": 1, "format": "s16le", "volume": 1.0, "pan": 0.0}`, then raw interleaved s16le PCM until the sender closes its side. `stream` defaults to `"default"`, `volume` (≥ 0.0) to 1.0, `pan` ([-1.0 left, 1.0 right]) to 0.0. The stream joins the mix with its first 100 ms of data; `play` returns when the data has played, the stream is stopped, or a newer stream of the same name starts.
- `{"cmd": "stop", "stream": "speech"}`, no body: stops that stream. Without `stream`, stops every stream.
- `{"cmd": "set", "stream": "player:3", "volume": 0.5, "pan": -1.0}`: changes a playing stream's volume or pan (either key may be left out), from its next tick.
- `{"cmd": "pause", "stream": ...}` and `{"cmd": "resume", "stream": ...}`: a paused stream stops being read and mixed, and goes on where it was.
- A command naming a stream that is not playing has no effect. An unparsable header closes the connection without effect.

### Streams

- **Named streams, the newest wins within a name.** Each `play` gets a generation number in its stream; an older play of the same name that is still receiving stops at its next tick and logs `interrupted`. The `tts` engine plays `speech`, so a new `say` still cuts the previous one as before; the audio player plays one `player:<id>` per task.
- **Different names play together**, mixed (below). Stopping one stream leaves the others playing.
- **Stop latency** is at most one tick plus the device buffer.

### Mixing

- **Output format: 48 kHz, stereo, s16le**, as a NAO's two ear loudspeakers.
- Each stream is converted to it as it is read: resampled to 48 kHz, mono spread to both channels, its volume applied, and its pan applied as a balance (pan p scales the left channel by min(1, 1 − p) and the right by min(1, 1 + p)).
- **One clock.** The mixer runs in ticks of 20 ms: at each tick it takes each playing stream's next 20 ms, sums them, clips to 16 bits and feeds the sum to the sink and the listeners. The output paces in real time whatever the sink ([devices.md](devices.md), "Real time").
- **The ticks keep their schedule.** Tick n is due at the run's start plus n × 20 ms, and is fed one tick ahead. A late wake-up (a loaded machine, a CI virtual machine: up to 30 ms measured on GitHub's macOS runner) is caught up by mixing the ticks already due back to back, so lateness never adds up in the playback: 0.5 s of audio plays in 0.5 s, its ticks reported 20 ms apart. Only when the mixer is more than 0.2 s behind (`RESYNC_S`) does the schedule restart from now, leaving a gap, as a device that ran dry would. Before this, each late wake-up restarted the schedule, and 0.5 s of speech took 0.87 s on that runner. Each tick's end is computed once, never earlier than now plus a tick (a tick fed while catching up plays no earlier than now): `playing_until` and the end of a stream finishing in that tick are that same time, so a play returns no earlier than the playing period it ends.
- **Active while something plays.** The mix starts when a stream joins after silence and ends when the last stream ends or is stopped; the sink and the listeners see nothing between two such runs.

### Audio sinks

Where the played audio goes is a seam, as tts-engine's `AudioSink` (its `specs/audio-sink.md`). The audio output owns the protocol, the streams, the mixer and the pacing; the sink receives the mix.

```python
class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """The mix starts: a stream joined after silence (always 48000, 2)."""

    def feed(self, chunk: bytes) -> None:
        """The mix, interleaved s16le, one tick."""

    def end(self, interrupted: bool) -> None:
        """The mix went quiet: the last stream ended, or a stop of every stream cut it."""
```

- **Call discipline:** for each run of the mix, `begin` once, `feed` any number of times, `end` exactly once, also when the output fails. All calls come from the mixer's thread, so they never overlap.
- **Streams as received.** A sink that also has `stream_begin(stream, rate, channels)`, `stream_feed(stream, chunk)` and `stream_end(stream, interrupted)` receives each stream's own PCM before conversion, from the same thread. The `MemorySink` does, so tests can assert on one stream while others play.
- **Shipped sinks:**

  | Sink | Does | Chosen by |
  | --- | --- | --- |
  | `DevicePlayer(device=None)` | Plays the mix on the output device (`sounddevice`, imported lazily at the first `begin`, so a host without PortAudio can use the other sinks), one device stream per run of the mix | `audio_output.mode = "play"`, the default |
  | `NullSink()` | Discards | `"silent"` |
  | `WavSink(path)` | Writes the mix as 48 kHz stereo 16-bit WAV, the runs one after the other; `close()` finishes the file (`NaoqiSim.stop()` calls it) | `"record"` |
  | `MemorySink()` | Keeps each stream as a `Playback(stream, rate, channels, pcm, started_at, ended_at, interrupted)` and each run of the mix as a `Playback` with `stream="mix"`; `playbacks` (the streams), `mixes`, `wait_for(predicate, timeout)` over the streams | Tests, passed as `NaoqiSim(config, sink=MemorySink())` |

- `AudioOutput(sink)` takes one sink. A `NaoqiSim` builds it from its `sink=` argument or the config's `audio_output` block ([api.md](../runtime/api.md), "Construction").
- The live tier runs its `NaoqiSim` with a `MemorySink` and asserts on the playbacks.

#### Muting the loudspeakers

The user mutes their loudspeakers (decided Nov 27, 2026): the device stops sounding, the robot does not notice. `DevicePlayer.muted`, set by `await sim.mute_output()` / `await sim.mute_output(False)` ([api.md](../runtime/api.md)) or the controls page's loudspeaker button ([controls.md](controls.md), "The page").

- **Zeros to the device.** While muted, `feed` writes silence of the chunk's length: the device stream opens, runs and closes as usual, so its timing and latency do not change and unmuting mid-sentence resumes the voice where it is.
- **Only the loudspeakers.** Everything before the sink goes on: the streams, the mix, `playing_until`, the speech engine's and the audio player's timing and events, and the listeners (a fake source still hears the robot). It is the user's volume knob, not the robot's: it changes neither `ALAudioDevice`'s output volume nor anything NAOqi reports.
- With the `mic` source, the microphone stops hearing the robot through the room, since the room is silent.
- Only a `DevicePlayer` has it (`audio_output.mode = "play"`, or one passed as `sink`): the other sinks make no sound. A `NaoqiSim` sets it back to unmuted when it starts.

### Playing state

Whether audio is playing belongs to the audio output, not the sink:

- `playing_until: float`, in `time.monotonic()` seconds: when the mix fed so far finishes playing (the last tick's pacing deadline). In the past when idle.
- It is updated at every tick and set to now when the mix goes quiet.
- Read from another thread without a lock: a float assignment is atomic in CPython.

### Listeners

What the robot plays can be heard by something else than the sink: the audio input's fake source, so the robot hears its own voice and its sounds ([audio-input.md](audio-input.md), "The robot hears itself").

- `AudioOutput.listeners`: callables `listener(chunk, rate, channels, at)`, called with each tick of the mix as it is fed to the sink (always 48000 Hz, 2 channels), `at` being when the tick is due to play (`time.monotonic()`, the start of its pacing slot); an empty chunk says a stop of every stream cut the mix at `at`. A `NaoqiSim` whose audio input is `fake` registers the fake source.
- Called on the mixer's thread, after the sink's `feed`; a listener that raises is logged and does not stop the mix.
- The device sink opens its stream at low latency (`latency="low"`), so the sound leaves the loudspeaker about when `at` says.

## Open questions

1. **Device selection and volume.** The audio output has no output device option, and the system volume (`ALAudioDevice.setOutputVolume`, [audio-device.md](../services/audio-device.md), and `ALTextToSpeech.setVolume` for the speech stream) is not applied to the mix. On a NAO, the system volume scales the whole output (measured on a real NAO 2.1, Oct 16, 2026: its own voice reaches its microphones at 0.28 times the RMS at volume 30 and 3.4 times at volume 80, relative to volume 50; [audio-device.md](../services/audio-device.md), open question 2); it would become a `set` without a stream once the services forward it.
2. **Tick length.** 20 ms is provisional: short enough for a stop and for a sound joining a sentence to land where a NAO's would, long enough for Python to keep up under emulation. To confirm when built.
