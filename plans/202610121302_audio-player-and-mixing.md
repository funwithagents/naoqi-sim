# ALAudioPlayer replacement, with mixing in the audio output

**Status:** Done

After [202610121149_speech-cpp-front.md](202610121149_speech-cpp-front.md), which builds the first C++ front, `load_native` and the front's build in the native stage; this plan adds the second front on that pattern.

Implements:
- [audio-player.md](../specs/services/audio-player.md), whole: the `ALAudioPlayer` replacement on 2.1 and 2.8, a C++ front over a Python core, decoding WAV/OGG/FLAC with the suite's libsndfile, one audio output stream per task.
- [audio-output.md](../specs/host/audio-output.md), "Protocol", "Streams", "Mixing", "Audio sinks", "Playing state" and "Listeners": named streams, the `set`/`pause`/`resume` commands, the mixer at 48 kHz stereo, sinks receiving the mix, `MemorySink` keeping each stream.
- [tts-engine.md](../specs/container/tts-engine.md): speech as the `speech` stream, `/stop` stopping it alone.

Left out: the open questions of those specs (the system volume, the tick length measured on a robot, loaded-file ids, web streams).

The design was measured before writing this plan (Oct 12, 2026). A C++ `ALModule` built in each image's native stage sees `stop(id)` through `isStopRequired(getMethodID())` on both versions; Python modules cannot.

## Scope

**Host: the audio output**
- `src/nao_sim/audio_output.py`: named streams with a generation each, the `stop`/`set`/`pause`/`resume` commands, the mixer thread (20 ms ticks, 48 kHz stereo, resample, spread, volume, balance, sum, clip), the `AudioSink` protocol receiving the mix, the optional `stream_begin`/`stream_feed`/`stream_end`, `WavSink` at 48 kHz stereo, `MemorySink.playbacks` per stream (with `stream`) and `MemorySink.mixes`, `playing_until` and the listeners on the mix.
- `tests/test_audio_output.py`: rewritten for the above.

**Speech engine**
- `docker/tts-engine/server.py`: `"stream": "speech"` in the `play` header and in `/stop`'s stop.
- `tests/test_tts_engine.py`: the headers it sends.

**Container: the player**
- `docker/naoqi/services/audio-player/nao_sim_audio_player_front.cpp` (new): `ALAudioPlayer`, the C++ front.
- `docker/naoqi/services/audio-player/nao_sim_audio_player_core.py` (new): the core.
- `docker/naoqi/services/audio-player/nao_sim_audio_player_almodule.py`, `docker/naoqi/services/audio-player/nao_sim_audio_player_qiservice.py` (new): `_NaoSimAudioPlayer`, per version.
- `docker/naoqi/Dockerfile.naoqi-2.1`, `docker/naoqi/Dockerfile.naoqi-2.8`: the front built in the `native` stage next to the relay, `-lboost_date_time` if needed, copied into the final stage.
- `docker/naoqi/entrypoint-2.1.sh`, `docker/naoqi/entrypoint-2.8.sh`, `docker/naoqi/entrypoint-lib.sh`: `ALAudioPlayer` in `REPLACED`; the core in `MODULES`; the front loaded with `load_native` after the modules; `_NaoSimAudioPlayer` and `ALAudioPlayer` checked; dependents found in step 6 added to `DEPENDENTS`.
- `docker/compose.yaml`: `NAO_SIM_SOUNDCARD=host.docker.internal:9562` for the NAOqi services.
- `tests/test_audioplayer_core.py` (new), `tests/test_entrypoint.py`.

**Live tier**
- `tests-e2e/test_audio_player_live.py` (new); `tests-e2e/test_speech_live.py` and `tests-e2e/test_audio_input_live.py` adjusted to the per-stream `MemorySink`.

**Specs and maps**
- Frontmatter of `audio-player.md`, `audio-output.md`, `tts-engine.md` (the new files), and `service-replacement.md`'s `code:` (the new `.cpp`); statuses; `AGENTS.md`'s project map if a module is added under `src/nao_sim/` (none planned).

## Steps

1. **Audio output streams and mixer.** Keep one connection thread per command. A `play` registers a `_Stream` (name, generation, rate, channels, volume, pan, a bounded queue of decoded chunks, paused flag) and feeds it from the socket; the newer generation of a name cuts the older one. A mixer thread wakes every 20 ms on the monotonic clock while any stream is active, pulls 20 ms from each unpaused stream (resampled to 48 kHz by linear interpolation, carrying the fractional position across ticks; mono spread to two channels; volume; balance `min(1, 1 − p)`, `min(1, 1 + p)`), sums in float, clips to int16, then calls the sink's `feed` and the listeners with the tick's due time. `begin(48000, 2)` when the first stream joins after silence, `end` when the last leaves; `end(interrupted=True)` and an empty listener chunk when a stop of every stream cut it. A `play` returns when its stream has been fully mixed, stopped or replaced. Back-pressure: a stream's queue holds at most 200 ms, so the socket read paces the sender as today.
2. **Sinks.** `DevicePlayer` opens one `RawOutputStream` at 48 kHz stereo per run of the mix. `WavSink` writes 48 kHz stereo. `MemorySink` implements `stream_begin`/`stream_feed`/`stream_end` to keep `playbacks` per stream (`Playback` gains `stream`; `started_at`/`ended_at` from the mixer's clock) and records each run of the mix in `mixes`; `wait_for` stays over `playbacks`.
3. **Fast tier for the audio output.** Two streams of different names play together and the mix holds both (sum of two sines at different frequencies, checked by FFT bins); a newer play of the same name cuts the older; `stop` with a name leaves the others; `stop` without a name stops all and tells the listeners; `set` changes volume and pan from the next tick (left/right RMS); `pause`/`resume` shift a stream's end by the pause length; a 22050 Hz mono stream comes out 48 kHz stereo with the same duration; `playing_until` and the listeners follow the mix; pacing stays real time.
4. **Speech engine.** `server.py` sends `"stream": "speech"` in its `play` header and `{"cmd": "stop", "stream": "speech"}`; its tests check both.
5. **The C++ front.** `nao_sim_audio_player_front.cpp`, on the pattern of `nao_sim_speech_front.cpp`: an `ALModule` named `ALAudioPlayer` binding every method of audio-player.md's contract with its overloads. Play methods (`playFile*`, `play`, `playInLoop`, `playSoundSetFile`, `playSine`): `id = getMethodID()`, or `core.newTaskId()` when `-1`; `core.start(id, kind, args)`; loop every 20 ms on `core.isPlaying(id)`, calling `core.stop(id)` once when `isStopRequired(id)`. `loadFile` returns the core's id. Every other method forwards to the core through an `ALProxy(getParentBroker(), "_NaoSimAudioPlayer")` and returns its answer; a core exception becomes an `ALError` with the core's message. Build it in each Dockerfile's `native` stage with the relay's flags, check `ldd -r`, copy the `.so` next to the relay's.
6. **Dependents.** With the recording proxy of speech.md's survey, list which in-process modules hold an `ALAudioPlayer` proxy at start on each version (step 1 of "Replacing a built-in"), and add them to each entrypoint's `DEPENDENTS`; write the result into audio-player.md's open question 1 (closing it) or note that none does.
7. **The core.** `nao_sim_audio_player_core.py` (Python 2.7, importable under Python 3): a `Player` holding the tasks (id → path, rate, channels, position, volume, pan, loop, state) and the loaded files; decoding by running the suite's `sndfile-convert -pcm16 <in> <tmp>.wav` (MP3 and unknown formats raise with libsndfile's message) and reading the WAV with `wave`; `playSine` generated in the core; one TCP connection per task to `NAO_SIM_SOUNDCARD` with `stream = "player:<id>"`, the file's rate and channels, `volume = task × master`, `pan`; `setVolume`/`setMasterVolume`/`setPanorama` send `set`; `pause`/`play` of a loaded file send `pause`/`resume`; `goTo` restarts the task's stream from the position; positions from the bytes sent minus the audio output's lead, corrected by pauses; `stop(id)` and `stopAll` send `stop` for their streams. Sound sets from the package store's `apps/` folders (open question 2). The shells register it as `_NaoSimAudioPlayer`: `ALModule` on 2.1, `@qi.multiThreaded()` qi service on 2.8. The audio output being unreachable logs and plays nothing, with blocking calls still lasting the file's duration, as the speech path does.
8. **Fast tier for the core.** Against a fake audio output on a local port: the headers each call sends (stream name, rate, channels, volume × master, pan), WAV decoded without the suite (a `sndfile-convert` stub on `PATH` for the OGG path), `stopAll` stops every task stream and never `speech`, loaded-file ids, `goTo`, `getCurrentPosition`, `getFileLength`, sound set lookup in a temporary package store, `playSine` samples.
9. **Entrypoints and compose.** `REPLACED` gains `ALAudioPlayer`, `MODULES` the core shell, the front loaded with `ALLauncher.launchLocal` after the Python modules (`load_native`), the readiness check covers `_NaoSimAudioPlayer` and `ALAudioPlayer`; `compose.yaml` gives the NAOqi services `NAO_SIM_SOUNDCARD`. `tests/test_entrypoint.py` checks the order and the fail-loudly paths.
10. **Live tier** (`test_audio_player_live.py`, both versions, `MemorySink`; the test files are written into the container by the test: a generated sine WAV, and `hey6.ogg` from the installed `animations` package):
    - `playFile` blocks for the file's duration and its PCM reaches the `MemorySink` as `player:<id>`, for WAV and OGG; an `.mp3` raises.
    - Volume 0.5 halves the RMS; pan −1 silences the right channel; `setVolume` and `setMasterVolume` during playback change the mix.
    - `playFileInLoop` keeps playing until `stop(id)`; `stopAll` stops it and a `say()` playing at the same time goes on.
    - `loadFile`, `play`, `pause` then `play`, `goTo`, `getCurrentPosition`, `getFileLength`.
    - A sound during `say()`: both streams in `playbacks`, overlapping in time, neither interrupted, and the mix holds both.
    - The Play Sound box's pattern from NAOqi's Python: `post.playFileFromPosition`, `wait(id, 0)` returning when `ALProxy('ALAudioPlayer', True).stop(id)` stops it; of two posted sounds, only the stopped one ends.
    - `playSine`; the sound set calls when a `soundsetaldebaran` package is present (skips otherwise).
    - The existing speech and audio input live tests pass with the per-stream `MemorySink`.
11. **Specs.** Frontmatter `code:`/`tests:` of the four specs with the new files; audio-player.md, audio-output.md and tts-engine.md to `Implemented`; their rows in `specs/_index.md`; the overview's milestone 2 and 4 lines; this plan `Done` here and in [_index.md](_index.md).

## Verification

- `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (fast tier, including the new core and audio output tests and `test_project_map.py`).
- `uv run pytest tests-e2e` on 2.1 and 2.8 (images rebuilt: the recipes changed), including `test_modules_live.py`'s Python 2.7 compile check over the new modules.
- CI green on both versions.
- Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
