---
code:
  - src/naoqi_sim/config.py
  - src/naoqi_sim/sim.py
  - src/naoqi_sim/audio_input.py
  - src/naoqi_sim/host_link.py
tests:
  - tests/test_config.py
  - tests/test_audio_input.py
  - tests/test_sim.py
  - tests-e2e/test_audio_input_live.py
  - tests-e2e/test_audio_loopback_live.py
---

# Audio input

**Status:** Implemented

## Purpose

The robot's microphones as a host device ([devices.md](devices.md)). It feeds the `ALAudioDevice` replacement ([audio-device.md](../services/audio-device.md)) with PCM over the host link, so a client that subscribes to `ALAudioDevice` gets microphone audio through `processRemote` as on a NAO. Speech recognition and sound processing run in the clients on that stream, never in naoqi-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

**The robot hears itself**, as a NAO does: its microphones pick up its own loudspeaker. With the host microphone that is the room's acoustics; with the fake source, the robot's voice is mixed into the fake room ("The robot hears itself"). Clients deal with it as on a NAO, where NAOqi's own speech recognition stops listening while the robot speaks.

## Decided

### Module

`src/naoqi_sim/audio_input.py`, class `AudioInput`, run in-process by a `NaoqiSim` ([api.md](../runtime/api.md)); config block `audio_input` ([config.md](../runtime/config.md)). The host link it is served on is `src/naoqi_sim/host_link.py` ([devices.md](devices.md), "The host link").

### Sources

The `audio_input` block picks one:

| `source` | Audio |
| --- | --- |
| `none` (default) | Nothing: the host link is not opened, `ALAudioDevice` accepts subscriptions and delivers nothing, `NaoqiSim/Audio/Source` stays `none` |
| `fake` | A quiet room in which code plays sounds: silence, plus what a test (or any program that runs the sim) plays through `NaoqiSim.fake_audio`. The source CI tests on every run |
| `mic` | The host's default input device |

#### The fake source

`FakeAudioSource`, reached as `sim.fake_audio` on a running `NaoqiSim` whose source is `fake` (any other source raises `NaoqiSimError`). It is the input side's counterpart of the audio output's `MemorySink`: the test decides what the robot hears and when.

```python
take = sim.fake_audio.play("hello.wav")  # or play(samples, rate=16000)
take.wait(timeout=5)  # take.started_at, take.ended_at
sim.fake_audio.stop()  # every sound playing now
```

- **Silence until told otherwise.** Subscribers get zero chunks at the normal cadence, as from a quiet room.
- **`play(sound, rate=None)`** starts the sound at once and returns a `Take` (`started_at`, `ended_at`, both `time.monotonic()`; `done`; `wait(timeout)`). `sound` is a WAV path (16-bit PCM, mono or 4-channel, 16 or 48 kHz) or a `numpy` int16 array (`(n,)` mono or `(n, 4)` in NAO order: left, right, front, rear) with its `rate` (16000 or 48000). Any other format raises `ValueError` at the call, naming the problem.
- **Sounds overlap and mix**, as in a room: samples are summed and clipped to int16.
- **Wall-clock time.** A sound plays from the moment `play` is called, whether or not anybody subscribes: a subscriber that arrives mid-sound hears the rest, and one played while nobody listens goes unheard. `ended_at` is when its last sample is due.
- **Split files.** A test plays one part, has the robot act, then plays the next: the timing is the test's.
- **The robot's own voice is in the room**, mixed with the sounds played ("The robot hears itself").
- `play` is thread-safe and may be called from any thread or before a subscription; `stop()` ends every sound playing (their `ended_at` becomes now).

#### The host microphone

Captured with `sounddevice` (`RawInputStream`, int16, mono, 48 kHz, blocks of 10 ms) from the default input device, opened when the input starts and closed when it stops, for the whole run whatever the container side needs (unless the user mutes it, below), as a NAO's microphones are always on (decided Nov 27, 2026: opened only while audio was needed, it followed speech recognition, which subscribes around each listening, and the microphone went on and off with every turn of a dialog). What it captures while nothing is needed is dropped, and when a need comes back the first block sent is the room now, not the up to 200 ms captured before. `NaoqiSim.start()` checks at step 1 that `sounddevice` imports (PortAudio is present) and that a default input device exists, failing with `DeviceUnavailableError` otherwise. The input logs at info level that the microphone is live when it opens and off when it closes, once a run (and at each mute and unmute): the terminal indicator of [devices.md](devices.md) ("Off unless asked"). An indicator in the sim window waits for naoqi-viewer to offer one.

#### Muting the microphone

The user mutes their microphone (decided Nov 27, 2026): the robot then hears nothing from it until it is unmuted. `MicSource.mute(muted)`, reached as `await sim.mute_input()` / `await sim.mute_input(False)` ([api.md](../runtime/api.md)) or the controls page's microphone button ([controls.md](controls.md), "The page").

- **The device is closed while muted**, so the operating system's microphone indicator goes off: muting is the user's privacy, not a gain set to zero. Unmuting reopens it while the input runs; the first block sent is the room after the reopening.
- **The robot hears silence**, at the normal cadence: the producer keeps sending zero chunks while audio is needed, as from a quiet room, so `ALAudioDevice`'s subscribers, the energies and speech recognition carry on as on a NAO in a silent room. `NaoqiSim/Audio/Source` stays `mic`.
- A mute before the input starts holds: `open()` leaves the device closed. A stopped input forgets it: the next run starts unmuted.
- The microphone being off, the robot no longer hears its own voice through the room either.
- The input logs the muting and the unmuting at info level, with the device's "off" and "live" lines.
- Only the `mic` source has it: the fake source is silent unless code plays into it.

### Formats, channels and the mono policy

- **The host produces every format the container side asks for**, and the Python 2.7 side does no signal processing: the need message lists formats (rate, channel, deinterleaved), as [audio-device.md](../services/audio-device.md) ("Preferences, as NAOqi's device") defines them, and the host sends one `pcm` stream per format.
- **Resampling** between 16 and 48 kHz is by a factor of 3, with a windowed-sinc low-pass filter (`numpy`), applied continuously across chunks so a stream has no seams.
- **Channels.** The source becomes four channels (left, right, front, rear); a format with one channel takes that microphone's channel; a deinterleaved format lays the four channels one after the other.
- **Mono policy** (`audio_input.mono`) for mono audio (the `mic`, a mono sound played on the fake source): `duplicate` (default) copies it to every channel, `silence` puts it on the front channel and zeros on the others. A 4-channel sound keeps its channels.
- The device publishes its source as `NaoqiSim/Audio/Source` (`fake`, `mic`) and the mono policy as `NaoqiSim/Audio/Channels` (`duplicate`, `silence`) when it starts, and `none` for both when it stops ([status-service.md](../container/status-service.md), "ALMemory keys").

### Chunks

- Each format's stream is cut in chunks of a fixed number of samples per channel: **4096 at 48 kHz, 1365 at 16 kHz** (about 85 ms), the values clients report from NAO robots; provisional (open question 1), one constant per rate in `audio_input.py`.
- **Real time.** Each stream is paced on its own sample clock: chunk `k` is sent when its last sample is due, `t0 + (k + 1) × samples / rate` after the stream starts, never in bursts; a late slot is sent at once and the schedule kept, not reset.
- **Energy.** When the need asks for it, the host computes each microphone's energy, the RMS of the 48 kHz four-channel signal over the last 4096 samples, in [0, 32768], and sends it on that cadence.

### The robot hears itself

A NAO's microphones hear its loudspeaker, so naoqi-sim's do too; nothing is muted while the robot speaks.

- **The host microphone** hears the host's loudspeaker through the room, as it is. The `DevicePlayer` and the microphone open their streams at low latency (`latency="low"`), so the robot's voice comes back about when a NAO's would.
- **The fake source** hears the audio output: every chunk the audio output plays ([audio-output.md](audio-output.md), "Listeners"), the mix of speech and sounds, is added to the fake room from the moment it is due to play, resampled to 48 kHz, on all four microphones, at **half its level** (provisional, open question 3). A stopped or cut stream stops being heard with it, up to the chunk already handed over (one tick of the mix at most).
- So a client tested against naoqi-sim has to cope with hearing the robot, exactly as on a NAO (for example by not listening between `ALTextToSpeech`'s `TextStarted` and `TextDone`). naoqi-sim keeps nothing from the client that a NAO would give it.
- A **microphone gate** (zeros while the robot plays, plus a tail) was designed and built, then removed on October 11, 2026, because it made naoqi-sim differ from a NAO: open question 4.

### On the host link

The audio input's messages on the host link ([devices.md](devices.md), "The host link"), from the `ALAudioDevice` service (`hello {"service": "ALAudioDevice"}`):

| Type | Direction | Header | Payload |
| --- | --- | --- | --- |
| `need` | container → host | `formats`: a list of `{"rate": 16000 \| 48000, "channel": "all" \| "left" \| "right" \| "front" \| "rear", "deinterleaved": bool}`; `energy`: bool | — |
| `pcm` | host → container | `format` (as in `need`), `channels` (1 or 4), `samples` (per channel) | s16le, interleaved or deinterleaved as the format says |
| `energy` | host → container | `left`, `right`, `front`, `rear` (floats) | — |

- `need` is sent whenever the set of formats or the energy flag changes, and again after every reconnect; `{"formats": [], "energy": false}` means nothing is needed. The host opens the microphone only while something is needed; the fake source's sounds run on the wall clock either way.
- A `need` that arrives before the device has started (step 6 of `NaoqiSim.start()`) is kept and served once it starts.
- The container stamps each chunk with its own clock on arrival ([audio-device.md](../services/audio-device.md), "Delivery").
- **Nothing is sent after the need ends.** An empty `need`, a disconnect or the device's `stop()` halts the producer and waits for it (up to a second), and a block being read when the halt comes is dropped, not sent: once `stop()` has returned, no `pcm` or `energy` message follows. The producer reads the connection and the need as one snapshot the handlers publish, never taking the device's lock, so the stop that joins it under that lock cannot wait on it (a chunk after `stop()`, seen once on a loaded CI runner).

### In the live tier and CI

- **Every live run uses the fake source.** The live tier's config has `audio_input = {source: "fake"}`, so `ALAudioDevice` is exercised on every run of both versions: a test subscribes as a client does, plays tones through `sim.fake_audio` and checks what it receives against them, and checks it hears the robot speak.
- **The loopback tests** use a real device: the `mic` source, the robot's speech played by a `DevicePlayer` and coming back into the microphone, and the `DevicePlayer` itself. They run only when the default output and input devices form a loopback, which `NAOQI_SIM_E2E_AUDIO=loopback` declares; without it they skip, since playing into a user's loudspeakers and recording their microphone is not acceptable by default. CI's live entries provide the loopback (a PulseAudio null sink as the default sink, its monitor as the default source) and set the variable, so there they cannot skip ([ci.md](../testing/ci.md)).

## Open questions

1. ~~**Chunk size and cadence.**~~ Closed, measured on a real NAO 2.1 (2.1.4.13) on Oct 16, 2026: a NAO delivers 4096 samples per channel at 48 kHz and 1365 at 16 kHz, one chunk every 85.3 ms (standard deviation about 1 ms, in the host's arrival times and in the robot's own timestamps alike), with all four channels or one, as a `bytearray` of little-endian 16-bit samples interleaved in the order left, right, front, rear (matched against the energy getters), stamped `[seconds, microseconds]` of the robot's clock. Exactly what the device sends. `getFrontMicEnergy` and the others answer each microphone's RMS over the last chunk (300 to 400 in a quiet room), as the device computes them.
2. **Microphone selection.** No option picks an input device other than the default; decided with the audio output's device selection ([audio-output.md](audio-output.md), open question 1).
3. **The level of the robot's voice in the fake room.** Half the played level is a placeholder; the reference, measured on a real NAO 2.1 (2.1.4.13) on Oct 16, 2026, at rest in a quiet room: the microphones' floor is an RMS of 200 to 400 (16-bit scale) per channel; while the robot speaks at output volume 50 the RMS over a sentence is 2300 to 6400 per channel (left loudest, rear quietest), with peaks at full scale on loud syllables; at volume 30 about 0.28 of that, at volume 80 about 3.4 times, clipping. The microphones hear the voice 0.2 to 0.5 s after `TextStarted` (the engine's latency before sound, longer for a longer sentence, plus one chunk). So a NAO hears itself at 10 to 20 times its room floor, near full scale at mid volume. What 'the played level' corresponds to on a NAO, and whether the gain becomes per microphone, is still to decide.
4. **Not hearing itself.** Whether naoqi-sim should ever keep the robot from hearing itself: a gate (zeros while the audio output plays, plus a tail, built and removed as unfaithful) or echo cancellation, which the host could do because it has the played and the captured audio on one clock. Only if a NAO does it too (NAO V6's audio front end is to check), or as a client-side tool rather than in naoqi-sim.
5. **Output device latency.** The robot's voice comes back as late as the output device plays it. Measured on CI: a PulseAudio null sink with no low-latency client renders about 1.5 s late, whatever PortAudio asks for, so CI keeps one ([ci.md](../testing/ci.md)).
6. **Replaying a file from the config.** `naoqi-sim run` has no way to feed a recording (the fake source is driven from code); a CLI option or a `fake` setting that plays a file at the first subscription waits for a user who needs it.
