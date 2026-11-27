---
code:
  - src/naoqi_sim/audio_output.py
  - src/naoqi_sim/video_input.py
  - docker/compose.yaml
  - src/naoqi_sim/host_link.py
  - src/naoqi_sim/audio_input.py
  - src/naoqi_sim/touch_input.py
tests:
  - tests/test_audio_output.py
  - tests/test_video_input.py
  - tests/test_host_link.py
  - tests/test_audio_input.py
  - tests-e2e/test_audio_input_live.py
---

# Host devices

**Status:** Implemented

## Purpose

The simulated robot's inputs and outputs, on the host. A NAO has a loudspeaker, microphones, cameras and touch sensors; inside Docker, NAOqi has none of these, so naoqi-sim provides them on the host as **devices**: dumb, each doing one job, knowing nothing about NAOqi's tags, events or `say()` semantics. Every NAOqi-specific decision stays in the containers (the services of [services/](../services/)) or, for the devices that are ordinary qi clients, at the edge of the device.

Each device is named after its role on the robot, not after what implements it: the audio output may be a loudspeaker, a WAV file or memory, the video input a webcam or a render.

| Device | Spec | Direction | Talks to NAOqi through | State |
| --- | --- | --- | --- | --- |
| Audio output | [audio-output.md](audio-output.md) | The robot's voice and sounds, out | Its own TCP protocol, fed by the `tts` engine and later [`ALAudioPlayer`](../services/audio-player.md) | Built, with its audio sinks; mixing specified |
| Audio input | [audio-input.md](audio-input.md) | Microphone, or sounds played from code, in | The host link, into the [`ALAudioDevice`](../services/audio-device.md) replacement | Built, with the fake source and the host microphone |
| Video input | [video-input.md](video-input.md) | Head cameras (naoqi-viewer render or webcam), in | qi: `ALVideoDevice.putImage` | Built, with the render and the webcam sources |
| Touch input | [touch-input.md](touch-input.md) | Head, hand and foot sensors, in, from the API and the controls page ([controls.md](controls.md)) | qi: ALMemory (the sensors' value keys) | Built, always on |

This spec holds what every device shares: the contract below and the host link. The simulated world ([viewer.md](viewer.md)) is not a device, but it lives on the host too: the video input's render source comes from it. Neither are the controls ([controls.md](controls.md)): a page and an HTTP API that drive the devices, owning no signal of their own.

## Decided

### The device contract

- **Owned by `NaoqiSim`.** A running `NaoqiSim` ([api.md](../runtime/api.md)) starts each device the config asks for (step 2 for the audio output, step 6 for the inputs of "Lifecycle"), on its own threads, and stops them in reverse order. A device is never a user command: the only standalone entry point is a debugging one ([audio-output.md](audio-output.md), "Command").
- **Configured by its block** of [config.md](../runtime/config.md), named like the device: `audio_output`, `audio_input`, `video_input`. A device whose block says `none` is not started. The touch input has no block: it has no source to choose and captures nothing of the user, so it always runs ([touch-input.md](touch-input.md), "The device").
- **Pluggable at its edge.** Where the data goes or comes from is a seam, chosen by the config or passed in code: the audio output's `AudioSink`, the audio input's source (the fake source tests play into, or the host microphone), the video input's source (render or webcam). Tests plug in-memory ends.
- **Testable in CI first.** A runner has no loudspeaker, microphone or webcam, so each device is built with the end CI can use before the one that captures the user: memory and silent sinks for the audio output, the fake source for the audio input, the render source for the video input ([ci.md](../testing/ci.md)).
- **Publishes its source.** An input device with sources to choose from writes its `NaoqiSim/*/Source` key when it starts ([status-service.md](../container/status-service.md), "ALMemory keys"), as an ordinary qi client, and writes `none` back when it stops (best effort: NAOqi may be stopping too).
- **Real time.** A device paces its data in real time whatever its seam, so NAOqi's timing (a blocking `say()`, a microphone chunk cadence, a camera frame rate) is the same with a device, a file or memory.
- **Off unless asked** for the devices that capture the user: the webcam and the microphone run only when the config enables them, with an indicator in the sim window (or the terminal when headless) while live.
- **Over qi when qi suffices.** A device whose NAOqi side is a public API (`putImage`, ALMemory) calls it as an ordinary qi client, connecting in one attempt as any client does since libqi 3.1.8 (`stack.connect`). Only what qi cannot carry goes over the host link below.

### The host link

The containers and the host devices exchange what qi cannot carry over one TCP port. As designed, that is the audio input alone: the video and touch inputs are qi clients and the audio output keeps its own protocol ([audio-output.md](audio-output.md)).

- **The containers connect out** to the host at `host.docker.internal:9563` (`host-gateway` on Linux, as the `tts` container reaches the audio output on 9562), so only 9559 is published and the host never needs a container's address.
- **Module** `src/naoqi_sim/host_link.py`: the framing, the server and the dispatch of each connection to the device that serves its `hello`'s service. The compose services tell the container side where to connect (`NAOQI_SIM_HOST_LINK=host.docker.internal:9563`).
- **The host listens first.** `NaoqiSim.start()` opens the port at step 2, with the audio output, before the containers start, when a device uses it (an `audio_input` source other than `none`); step 1 then checks 9563 is free with the other ports. A container side retries every second while the host is absent (logging the first failure only), so a stack started by hand with `docker compose` connects whenever the host side comes up.
- **One connection per container-side service.** Each service that needs the host (today only `ALAudioDevice`) opens its own connection and sends a `hello` naming itself first; a second `hello` for the same service replaces the older connection.
- **Framing**, the toolkit's shared convention (naoqi-viewer's protocol): `u32 header_len | u32 payload_len | JSON header | raw payload`, big-endian. Every header has a `type`; the device spec owns its types (the audio input's in [audio-input.md](audio-input.md), "On the host link"). The container side's framing is Python 2.7 (in the audio device's core module), the host's Python 3; both are tested in the fast tier against each other's bytes.
- **No state survives a reconnect.** After a reconnect the container side sends its current state again (the audio input's subscription), so neither side needs to remember the other.
- **A connection before its handler is kept, with what it said.** The containers boot before step 6 of `NaoqiSim.start()` registers the audio input, so a service's `hello` and first `need` can arrive while nobody serves it. The link keeps the connection and the newest message of each type it sent, and hands both to the handler when it registers: `connected`, then the kept messages in arrival order. A `need` sent at boot is thus served, not lost (the cause of a rare timeout in the `ALAudioDevice` core's reconnect test).

## Open questions

1. ~~**The audio output on the link.**~~ Decided Oct 12, 2026 with [audio-player.md](../services/audio-player.md): the audio output keeps its own protocol. Mixing names each stream in its `play` header, so several streams are several connections ([audio-output.md](audio-output.md), "Streams").
2. **Ports.** 9559, 9562 and 9563 are fixed, so one naoqi-sim runs per machine. Configurable ports come with several instances ([config.md](../runtime/config.md), open questions).
3. **Link latency.** How long a chunk takes from the host to a subscriber's `processRemote`, under the amd64 emulation of Apple Silicon included, is to measure when the audio input is built.
