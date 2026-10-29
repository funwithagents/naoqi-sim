---
code:
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/services/speech/naoqi_sim_speech_almodule.py
  - docker/naoqi/services/speech/naoqi_sim_speech_qiservice.py
  - docker/naoqi/Dockerfile.naoqi-2.1
  - docker/naoqi/Dockerfile.naoqi-2.8
  - docker/naoqi/services/audio-device/naoqi_sim_audio_device_relay.cpp
  - docker/naoqi/services/speech/naoqi_sim_speech_front.cpp
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_front.cpp
  - docker/naoqi/services/naoqi_sim_front_core.h
  - docker/naoqi/services/service-replacement/naoqi_sim_loader.cpp
tests:
  - tests-e2e/test_speech_live.py
  - tests/test_entrypoint.py
---

# Service replacement

**Status:** Implemented

## Purpose

naoqi-sim makes the container look like a real NAO by replacing or adding NAOqi services *inside* NAOqi, so any qi client on the host reaches them on 9559 exactly like built-ins and in-process modules (`ALAnimatedSpeech`, `ALDialog`...) call them instead of the originals. This spec is the reusable mechanism: how an override module is loaded, which object model it uses on each version, how it takes a built-in's place in NAOqi's boot, how an override reaches services that live on the host, and the two native pieces for what Python 2.7 cannot do: the relay to send a binary, and a C++ front for `post`/`wait`/`stop(id)`. The `ALTextToSpeech` replacement ([speech.md](../services/speech.md)) is its first user; the `ALAudioDevice` replacement ([audio-device.md](../services/audio-device.md)) and the planned `ALAudioPlayer` replacement reuse it.

## Decided

### Loading a module

- Override modules are Python 2.7 files, kept with their service in `docker/naoqi/services/<service>/` and copied flat to `/opt/naoqi/modules/`, importable by name (hence their unique `naoqi_sim_<service>_` names).
- The desktop loaders ignore the `[python]` section of `autoload.ini`, silently (main file, user file, with or without `--writable-path`; on both versions, measured). A `sitecustomize.py` on the path runs when `pythonbridge` starts its interpreter, but too early: an `ALModule` cannot be created there ("no current broker in Python's world", 2.1).
- So our C++ loader ("Replacing a built-in") calls `ALLauncher.launchPythonModule(<module>)`, which runs `from <module> import *` in `ALPythonBridge`'s embedded interpreter. On 2.1 that is the `naoqi-bin` process itself (same pid, verified); on 2.8 it is `naoqi-service`.
- A module registers its service at import time, at module level.
- `launchPythonModule` does not report an import failure, so the entrypoint checks once NAOqi has booted that every replaced name (`REPLACED` in each version's script) and every added name (`ADDED`: `ALAudioDevice`, `_NaoqiSimAudioRelay`, the cores) answers, and exits non-zero otherwise rather than printing "ready" with a service missing ([container.md](container.md), "Entrypoint"). The `NaoqiSim` module is checked too, since the entrypoint's last step calls it.

### Object model per version

| | 2.1 | 2.8 |
| --- | --- | --- |
| Registration | `naoqi.ALModule(name)` subclass, instantiated at module level | `qi.Session` connected to `tcp://127.0.0.1:$NAOQI_SIM_INTERNAL_PORT`, `registerService(name, obj)` |
| Why | Registers to the main broker: served on 9559 with the built-ins' endpoints and listed in the broker's local module table, which in-process callers use. A module's own `qi.Session` would serve on a separate port advertised with the container IP, unreachable from the host on Docker Desktop | The gateway relays every service, so a plain qi service is reachable. Required when callers need signals: a legacy `ALModule` cannot declare `qi.Signal`s |
| Concurrency | Measured OK: `stopAll` gets through while `say` blocks | Decorate the class with `@qi.multiThreaded()`; qi objects are single-threaded by default, so a blocking method would queue every other call |
| `ALProxy.post` | A task id; `wait`/`isRunning` served by the generics | Runs the call synchronously and returns `-1`; `wait`, `stop`, `isRunning` are "Can't find method" (measured on both versions for a qi service) |

`ALModule` rules (2.1):

- It auto-binds every method that has a docstring, with the arity from `inspect.getargspec`; defaults count toward that arity. An overload with fewer arguments needs an explicit `self.BIND_PYTHON(name, "<method>", <arity>)`, for example `say(text)` next to `say(text, language)`.
- Method names that collide with the `ALModule` generics (`ping`, `version`, `exit`, `stop`, `wait`, ...) must be avoided. A Python `stop` is never called, even bound explicitly with `BIND_PYTHON`: the generic wins (measured Oct 12, 2026).
- The generics `pCall` (what `ALProxy.post` calls), `isRunning(id)` and `wait(id, timeout)` work on a Python `ALModule`, on 2.1 and in 2.8's `naoqi-service`; the generic `stop(id)` does nothing to it ("Task ids, `wait` and `stop(id)`").

### Replacing a built-in

A replacement takes the built-in's place in NAOqi's own boot. The entrypoint starts NAOqi from a copy of the suite's `autoload.ini` in which the built-in's library is commented out (`#replaced <entry>`) and ours are listed right after `pythonbridge`. The built-in never loads, so no module ever holds a proxy to it, and every module NAOqi loads after ours finds the replacement registered under the built-in's name, in-process callers included (they resolve names through the broker's local module table, where our modules are).

| | 2.1 | 2.8 |
| --- | --- | --- |
| Left out of the autoload copy | `audioout`, which provides both `ALTextToSpeech` and `ALAudioPlayer`; `peopleperception` and the four libraries whose modularity processes chain to it ([people-perception.md](../services/people-perception.md), [perception-stubs.md](../services/perception-stubs.md)) | `audioplayer`, `ttsinterface`; `peopleperception` and the same four; `naoqi_sim_perception_sources` inserted after `modularityperception` |
| Loads the autoload | `naoqi-bin`, in order, in-process | `naoqi-service` (the `system.Naoqi` package service `naoqi-bin`'s `ALServiceManager` starts), same |
| Loaded after ours | The rest of the autoload: `behaviormanager` (its preloaded behaviors' boxes make their proxies as they load), `animatedspeech`, `dialog`, and the added built-ins ([naoqi-fidelity.md](naoqi-fidelity.md), "Matching a real NAOqi robot's modules") | The rest of the autoload, and the package services (`dialog`, `expressivity`, `life`...), which `ALServiceManager` starts beside `naoqi-service` |

Our entries, in order:

1. `naoqi_sim_audio_device_relay`, the native relay ("Binary arguments: the native relay").
2. `naoqi_sim_loader`, which loads our Python modules (below).
3. `naoqi_sim_speech_front`, `naoqi_sim_audio_player_front`: the C++ fronts ("Task ids, `wait` and `stop(id)`: a C++ front"), which take the replaced names over their cores, loaded just before.

An entry `foo` is `/opt/naoqi/lib/naoqi/libfoo.so`, the suite's module folder, where the images install ours ([container.md](container.md), "The native build").

**The loader** (`docker/naoqi/services/service-replacement/naoqi_sim_loader.cpp`) is a C++ `ALModule`, `_NaoqiSimLoader`, built as the other native modules. In its `init()`, at its place in the autoload, it adds `NAOQI_SIM_MODULES_DIR` to the embedded interpreter's `sys.path` (`ALPythonBridge.eval`; 2.8's `naoqi-service` does not inherit `PYTHONPATH`), then calls `ALLauncher.launchPythonModule` for each module of `NAOQI_SIM_PYTHON_MODULES`, in order. The calls are synchronous, so our services are registered before the next autoload entry loads. The entrypoint exports both variables before starting `naoqi-bin`; on 2.8 `naoqi-service` inherits them. It logs each module to stderr (2.8: `naoqi-service`'s log, `~/.local/share/PackageManager/logs/system.Naoqi_error.log`).

- **2.8's package services start beside `naoqi-service`, not after it.** `ALServiceManager` launches every autorun package service about 0.25 s before `naoqi-service`; they registered after our modules and bound to them in 6 boots out of 6 (measured Oct 14, 2026). A NAO 6 is in the same position: its `ttsinterface` sits in `naoqi-service`'s autoload as ours do, and its package services call it.
- **Before Oct 14, 2026** the entrypoint let the built-ins load, called their `exit()`, loaded ours over `ALLauncher`, and relaunched (2.1) or restarted (2.8, `ALServiceManager`) every module holding a proxy to them. Each module missed showed as "module destroyed" (2.1's preloaded behaviors, then 2.8's `ALDialog`), and exiting a built-in during a slow 2.8 boot killed `naoqi-service`.
- A name that no built-in holds (`ALAudioDevice`, `ALFaceDetection` on both versions) is registered the same way, with nothing left out.
- **A library may register more than its name.** 2.8's `peopleperception` also registers the hidden `_UserIdentification`, which another package waits for silently; leaving a library out means serving every name it registered (measured Oct 29, 2026, by diffing the service list of a boot with the library left out against a normal boot's: the method that finds such names).
- **A library may need another library's modularity process**, which no replacement can provide: the four vision modules chained to `PeoplePerception_process` fail to load without the built-in library, so they are left out and stubbed with it ([perception-stubs.md](../services/perception-stubs.md)). A library may also lose shared settings another loads: 2.8's tracking processes read `peopleperception_sources.mds`, which naoqi-sim loads itself from an autoload entry placed after `modularityperception` (the same file, "The tracking processes").
- A replacement must carry whatever its callers connect to at start, not only the documented methods. On 2.8, `ALAnimatedSpeech` connects to `ALTextToSpeech`'s hidden signal `_started` and the process dies without it. The recording proxy and caller survey in [speech.md](../services/speech.md) are the method for finding these.

### Overloads, structs and properties on a 2.8 qi service

Measured Oct 29, 2026, on the perception survey stubs:

- **Overloads are one varargs method.** A qi service registers one signature per method name, from the Python function's argument list; a method with defaults is registered at its full arity, so `subscribe(name)` from `ALBasicAwareness` failed against `subscribe(name, period=30, precision=0.0)` ("Arguments types did not match") and the awareness process died. `def subscribe(self, *args)` serves both calls. On 2.1 an `ALModule` keeps the explicit second binding (`BIND_PYTHON`).
- **A struct reply needs its type declared.** A caller converting the reply to a qi struct (`_UserSessionManager` to its `RecognitionResult`) fails on a plain list; `qi.bind(returnType="(i[(Lfi)<RecognitionMatch,value,confidence,storage>])<RecognitionResult,status,matches>", paramsType=["i"])` on the method makes a tuple convert. The caller's expected signature appears in its error log ("will not be able to convert return type from ... to ...").
- **Properties** are `qi.Property(signature)` instances set on the object before `registerService`; **signals** `qi.Signal(signature)` likewise. The methods are read at `registerService`: anything set on the class afterwards is not served.
- A Python 2.7 function that `exec`s generated code may hold no generator expression with a free variable (the compiler refuses the `exec`); a list comprehension is fine.

### Calling services registered on the host

Some overrides must call a service that a host client registered: for example, `ALAudioDevice` calls a subscriber's `processRemote`.

- Go through the broker with `naoqi.ALProxy(<name>)`. NAOqi calls the host back over the socket the host already opened (libqi 2.1 `ClientServerSocket` capability), the mechanism NAOqi uses for any service a connected client registers.
- Never go through a module's own `qi.Session`. That opens a new connection to the host's advertised endpoints, and fails for two reasons: the host auto-listens on loopback only ("No endpoint available"), and the libqi 3 fork's server binds objects only after a service-0 capability message that 2.1 clients never send.
- On 2.8, a module's own `qi.Session` (on `NAOQI_SIM_INTERNAL_PORT`) reaches a host-registered service through the gateway, as `naoqi.ALProxy` does.
- Measured on 2.1 (C++ `ALMemory.subscribeToEvent` callback and an in-process `ALProxy`: pass; own `qi.Session` and `qicli` from the container: fail) and, on Oct 10, 2026, on both versions with a host `processRemote` (2.1 through the broker, 2.8 through a module's own session: pass).

### Binary arguments: the native relay

Python 2.7 inside NAOqi cannot send a binary value to another service, on either version (measured Oct 10, 2026): py2 `qi` sends `str` and `bytearray` as a qi string, `naoqi.ALProxy` turns a `bytearray` into `None`, and `buffer`/`memoryview` are refused. A libqi 3 client then receives a `str` (mangled when the bytes are not UTF-8) where a NAO's C++ module sends an `ALValue` binary, which it receives as a `bytearray`. Where the bytes matter (a subscriber's `processRemote`), an override goes through a native relay:

- **A small C++ NAOqi module**, an `ALModule` built from one source for both versions (`docker/naoqi/services/audio-device/naoqi_sim_audio_device_relay.cpp`), named with a leading underscore so it stays out of NAOqi's service listings as NAO's own internal modules do (`_NaoqiSimAudioRelay`). Its methods take the bytes as a string, which Python 2.7 sends intact, and make the call with an `ALValue` binary through an `ALProxy`, exactly as the C++ module of a NAO does. It holds no logic: the Python 2.7 module decides what is sent, to whom and when.
- **Loaded** from the autoload copy, before the loader, into the process that hosts our Python modules (`naoqi-bin` on 2.1, `naoqi-service` on 2.8) ("Replacing a built-in"); the entrypoint checks that `_NaoqiSimAudioRelay` answers.
- **Built in the image**, in a builder stage of each version's Dockerfile, never on the host and never committed ([container.md](container.md), "The native build"). One recipe for both versions: the headers of the version's own C++ SDK (the same release as its suite), linked against the suite's own libraries, with the suite's compiler and C++ ABI.
- Each call costs under 1.5 ms (measured with 64 KB buffers).

### Task ids, `wait` and `stop(id)`: a C++ front

Choregraphe's boxes start a call with `id = proxy.post.<method>(...)`, wait with `proxy.wait(id, 0)`, and stop it with `ALProxy(name, True).stop(id)` from a second proxy (the Play Sound and Say boxes). `wait` and `stop` are `ALModule` generics; a C++ module honours `stop(id)` by checking `isStopRequired(getMethodID())` while it runs. Python cannot (measured Oct 12, 2026):

| | Python `ALModule` | Python qi service | C++ `ALModule` |
| --- | --- | --- | --- |
| `post` | Task id | Synchronous, `-1` | Task id |
| `wait(id, 0)` | Blocks until the call ends | "Can't find method" | Blocks until the call ends, or until stopped |
| `stop(id)` | Accepted, no effect | "Can't find method" | `isStopRequired(id)` turns true in that call only |
| `getMethodID()` in the call | `-1` (not given to Python; through `ctypes`, `-1`) | — | The id `post` returned; `-1` for a blocking call |

Same on 2.1 and 2.8. So a replacement whose callers stop by task id has a **C++ front**:

- **The service is a C++ `ALModule`** registered under the built-in's name, built and loaded as the relay is (one source for both versions, compiled in the native build stage, listed in the autoload copy after the loader, "Replacing a built-in").
- **It holds no logic.** The logic lives in a Python 2.7 core module, a hidden service named with a leading underscore (`_NaoqiSim<Name>`, `ALModule` on 2.1, qi service on 2.8 as above), so the fast tier tests it on the host as the other cores.
- **A long call** (one that plays, speaks or waits) takes its id with `getMethodID()` (or asks the core for one when it is `-1`, a blocking call), starts the work in the core with that id, and polls every 20 ms: `isStopRequired(id)` makes it call the core's stop for that id; the core reporting the work done makes it return. A core-side stop (`stopAll`) ends the polls.
- **Every other method** forwards to the core and returns its answer.
- **The front reaches its core through `ALProxy` on 2.1 and a `qi::AnyObject` on 2.8**, each version's own API (`getParentBroker()->session()->service(core)` on 2.8), with typed calls. They are safe because each image compiles against its suite's own SDK ([container.md](container.md), "Build files: the C++ SDK"): built against mismatched libqi headers, typed calls sent "Invalid" values and crashed `naoqi-service`.
- **The qi box pattern works on it too.** 2.8's boxes call `pCall(method, ...)`, `wait(id)` and `stop(id)` as qi methods on a service object, rather than `ALProxy.post`; a C++ `ALModule` serves them (measured on 2.8). A Python qi service could define those methods itself, but `ALProxy.post` (2.1-style scripts, 2.8's deprecated boxes, `ALAnimatedSpeech`'s C++ proxy) would still run synchronously against it, so the front stays the one mechanism on both versions.
- **On 2.8** the C++ front is an `ALModule` in `naoqi-service` like the relay; the gateway relays it like any service.
- **Stopped by a cancel.** A qi caller may stop a call by cancelling its future instead of `stop(id)`: `ALAnimatedSpeech` 2.8 does so with `ALTextToSpeech._sayWithLocale` (`qicli trace` shows no other call on the service when it is stopped). A long call such a caller makes answers with a `qi::Future` from a `qi::Promise` whose cancel callback stops the work in the core, completed by a thread that follows it (cancelled or done).
- **Signals** a front's callers need are the front's: advertised in its constructor with `getBuilder().advertiseSignal(name, &member)` (an `ALModuleCore` is a `qi::DynamicObject`), fired as member signals when the core asks through a hidden method; a string signal reaches clients in other processes (measured on 2.8). While the build used mismatched headers, firing through `asObject().post(...)` and connecting from NAOqi's embedded Python crashed `naoqi-service` and a `qi::uint64_t` signal delivered nothing; not measured again since. A front fires only the signals its callers need, as members.
- **Users:** the `ALTextToSpeech` replacement ([speech.md](../services/speech.md), "Architecture"), then the `ALAudioPlayer` replacement ([audio-player.md](../services/audio-player.md)).

## Open questions

1. **Restarting a replacement** (re-running the procedure without restarting the container, e.g. while developing a module) is not supported.
