---
code:
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_almodule.py
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_qiservice.py
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_relay.cpp
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/compose.yaml
tests:
  - tests/test_audio_device_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_audio_input_live.py
---

# ALAudioDevice replacement

**Status:** Implemented

## Purpose

The desktop NAOqi has no audio input: neither version registers `ALAudioDevice`. An override module ([service-replacement.md](../container/service-replacement.md)) registers one, so clients subscribe to the microphones as on a NAO and receive audio through `processRemote`, from the audio input on the host ([audio-input.md](../host/audio-input.md)). The name is free on both versions, so it is registered directly, with no built-in to remove.

The module routes audio; it does no signal processing. The host produces every format the subscribers ask for, and a small native relay hands each buffer to a subscriber as a binary, as the C++ `ALAudioDevice` of a NAO does ("Delivery").

## Decided

### Modules

- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py`: the subscribers, their preferences, the formats they need, the host link client and the delivery threads. Python 2.7, importable under Python 3 so the fast tier tests it on the host, as the speech and status cores are.
- `naoqi_sim_audio_device_almodule.py` (2.1, an `ALModule` named `ALAudioDevice`) and `naoqi_sim_audio_device_qiservice.py` (2.8, a qi service, `@qi.multiThreaded()`): thin shells per object model.
- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_relay.cpp`: the native relay, one C++ source for both versions ([service-replacement.md](../container/service-replacement.md), "Binary arguments: the native relay").
- Each entrypoint loads the relay, then the module with the other modules, and its readiness check covers both names ([container.md](../container/container.md), "Entrypoint").

### Methods

| Method | Behavior |
| --- | --- |
| `setClientPreferences(name, sampleRate, channels, deinterleaved)` | Stores the format for `name`, taken into account at its next `subscribe` (as NAOqi's documentation says). Without a call, a subscriber gets the default: 48 kHz, all channels, interleaved |
| `subscribe(name)` | Starts delivering to the service `name` (a module or a service a client registered). `name` must exist: a name no service holds raises, once it has been given 5 s to appear (on 2.8 after waiting up to 10 s for it, see "As measured"). The second covers a client that registers its service and subscribes at once: NAOqi 2.1's broker reaches a qi service registered an instant before only a moment later, so an immediate check refused it (a live-tier failure on CI). Subscribing a name already subscribed keeps its subscription and format, and its buffers now reach whichever service holds the name ("A name registered again") |
| `unsubscribe(name)` | Stops delivering to it, and the relay forgets its proxy; an unknown name is a no-op |
| `enableEnergyComputation()`, `disableEnergyComputation()` | Energy is computed only while enabled, with or without subscribers |
| `getFrontMicEnergy()`, `getRearMicEnergy()`, `getLeftMicEnergy()`, `getRightMicEnergy()` | The last energy the host computed for that microphone, in [0, 32768]; `0.0` while disabled |
| `openAudioInputs()`, `closeAudioInputs()` | No-ops: capture follows the subscribers |
| `isInputMuted()` | Always `false`: nothing mutes the microphones, the robot hears itself as a NAO does ([audio-input.md](../host/audio-input.md), "The robot hears itself") |
| `getOutputVolume()`, `setOutputVolume(volume)` | The value (0 to 100, initially 50) is kept and returned (open question 2) |

### Preferences, as NAOqi's device

The formats are those of NAOqi's documentation (the 2.1 suite's offline docs, `alaudiodevice.txt` and `alaudiodevice-api.txt`):

- `sampleRate` is 16000 or 48000. `channels` is NAOqi's channel constant, not a count: `0` all channels (`ALLCHANNELS`), `1` left, `2` right, `3` front, `4` rear.
- 48 kHz takes all channels, interleaved or deinterleaved (`deinterleaved` = 1: the buffer holds each channel's samples one channel after the other, in the order left, right, front, rear).
- 16 kHz takes one channel, any of the four.
- Any other combination raises, and the stored preferences stay as they were.
- A subscriber's format is a triple (rate, channel, deinterleaved), with channel one of `all`, `left`, `right`, `front`, `rear`. The module asks the host for the set of distinct formats its subscribers need ([audio-input.md](../host/audio-input.md), "On the host link"), and routes each `pcm` message to the subscribers of that format, unchanged.

### Delivery

- The module holds the host link connection ([devices.md](../host/devices.md), "The host link"), at the address the compose service gives it (`NAOQI_SIM_HOST_LINK`, `host.docker.internal:9563`). It retries every second while the host is absent, logging only the first failure, and sends its current need again after each reconnect.
- **Each subscriber has its own delivery thread** with a queue of 4 buffers: the link thread never waits on a subscriber, and a slow subscriber costs only itself. When the queue is full the oldest buffer is dropped, logged once per run of drops.
- **Through the native relay.** The delivery thread calls `_NaoqiSimAudioRelay.deliver(name, nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` with the PCM as a Python string; the relay calls the subscriber's `processRemote(nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` with the buffer as a binary, so a libqi 3 client receives a `bytearray` as from a NAO. 2.1 reaches the relay with `naoqi.ALProxy`, 2.8 through the module's own `qi.Session` (both measured, see "As measured").
- **Timestamps.** Each buffer is stamped on arrival in the container, `[seconds, microseconds]` of the container's clock, since `processRemote`'s `timeStamp` is the robot's time, comparable to NAOqi's other timestamps.
- **A subscriber that goes away.** Three consecutive failed deliveries to a name spanning at least 2 s (a client disconnected without unsubscribing) unsubscribe it, logged, and the relay is told to forget its proxy. The 2 s keep a new subscriber that the relay cannot reach yet (2.8, "As measured") from being dropped.
- **A name registered again.** The relay keeps a proxy per subscriber name, which reaches the service that held the name when it was made: if a client registers a new service under the same name, the old proxy reaches a destroyed module. So the relay is told to forget a name's proxy on every `unsubscribe` and every `subscribe` (also of a name still subscribed, for a client that died without unsubscribing and registered again), and the next delivery reaches the service holding the name then. Both versions deliver through the relay; the module's own `qi.Session` only finds the relay and checks that a name exists, asking for the service each time, so it keeps no handle to a subscriber. (Found by a client's live tests: before this, every other session of a client reusing its name was deaf.)
- **No host source.** With no host link, or while the host has no source (`NaoqiSim/Audio/Source` is `none`), subscriptions are accepted and nothing is delivered.

### In-process listeners

Another module of ours in the same process (the speech recognition, [speech-recognition.md](speech-recognition.md)) takes the microphones without a qi call per buffer: `listen(name, sampleRate, channels, deliver)` on the core, a format as `setClientPreferences` takes it, gives `deliver(nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` each buffer of that format on a thread of its own, with the same queue and dropping as a subscriber; `unlisten(name)` stops it. A listener counts in the formats asked of the host, is not a qi subscriber, and an error it raises is logged and costs it nothing. It is not part of `ALAudioDevice`'s API.

### Chunks

The host cuts the buffers ([audio-input.md](../host/audio-input.md), "Chunks"); the module passes them on as they come. Provisionally 4096 samples per channel at 48 kHz and 1365 at 16 kHz (about 85 ms), the values clients report from NAO robots; the 2.1 docs say 170 ms (open question 1).

## As measured

Oct 10, 2026, both versions, a libqi 3 host client registering a service with `processRemote`:

- **Callbacks reach the host on both versions**: 2.1 through the broker, 2.8 through the gateway from the module's own session. A call costs 0.4 to 1.3 ms per chunk.
- **Python 2.7 cannot send a binary** on either version: `str` and `bytearray` travel as a qi string (the host gets a `str`, mangled when not UTF-8, so `bytes(inputBuffer)` fails), and `ALProxy` turns a `bytearray` into `None`. A C++ `ALValue` binary arrives as a `bytearray`. Hence the relay.
- **Through the relay**, both versions: the host receives a `bytearray` with the exact bytes and the timestamp sent, from `ALProxy` (2.1) and a qi session (2.8). A 48 kHz four-channel chunk (8192 samples) costs 0.74 ms on 2.1 and 1.28 ms on 2.8.
- **2.8: a client's service reaches the container a moment late.** A client registers its service and subscribes at once; through the gateway, the module's session may not find the name yet (`session.service` fails for a moment), and `session.services()` never lists it. So on 2.8, `subscribe` asks for the service directly, retrying for up to 10 s (measured with the live tier: intermittent failures without the retry, none with it at first; then one failure after 3 s on a loaded CI runner, the first listener after the stack came up). The wait only delays the error for a name that does not exist. 2.1, through the broker, finds it at once.

## Open questions

1. ~~**Chunk size and cadence.**~~ Closed: a real NAO 2.1 delivers 4096 samples per channel at 48 kHz and 1365 at 16 kHz every 85.3 ms, interleaved left, right, front, rear, which is what the device sends ([audio-input.md](../host/audio-input.md), open question 1, measured Oct 16, 2026).
2. **Output volume and output buffers.** Whether `setOutputVolume` drives the audio output's volume ([audio-output.md](../host/audio-output.md), open question 1), and whether `sendRemoteBufferToOutput` (a client playing its own PCM through the robot) is served, by streaming to the audio output. The reference, measured on a real NAO 2.1 (2.1.4.13) on Oct 16, 2026: `setOutputVolume` scales the loudspeakers (the robot's own voice reaches its microphones at 0.28 times the RMS at volume 30 and 3.4 times at volume 80, relative to volume 50); `sendRemoteBufferToOutput(nbOfFrames, buffer)` takes 48 kHz interleaved stereo 16-bit little-endian, returns true after 23 ms for 0.4 s of audio (buffered, not blocking), and `playSine(frequency, gain, pan, duration)` returns at once too.
3. **Other methods and formats.** The rest of the NAO's `ALAudioDevice` (`setParameter`, `muteAudioOut`, `flushAudioOutputs`, `setFileAsInput`, recording, `startMicrophonesRecording`/`stopMicrophonesRecording`, which the Record Sound box calls, and `ALAudioRecorder`), and four channels at 16 kHz, are out of v1 unless a client needs them. A real NAO 2.1 does accept all four channels at 16 kHz (`setClientPreferences(name, 16000, 0, 0)` gives chunks of 1365 samples by 4 channels, measured Oct 16, 2026), so that format is a gap of ours, not a later version's. The robot's `ALAudioDevice` has 15 public methods ours lacks and a `speakersPlaying` signal ([naoqi-fidelity.md](../container/naoqi-fidelity.md), "Measured against a real NAO 2.1").
