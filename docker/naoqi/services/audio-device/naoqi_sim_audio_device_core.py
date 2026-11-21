# -*- coding: utf-8 -*-
"""Shared logic of the ALAudioDevice replacement (Python 2.7, inside NAOqi).

NAOqi's desktop suites have no ALAudioDevice; this one serves the host's audio input
(specs/services/audio-device.md). It keeps the subscribers and their formats, tells the host
which formats are needed over the host link (specs/host/devices.md, "The host link"), and routes
each buffer the host sends to the subscribers of its format, unchanged: the host does every
conversion, this side does no signal processing. Each subscriber has its own delivery thread, so a
slow one costs only itself. The buffer reaches the subscriber's processRemote through the native
relay, which sends it as a binary, as a NAO's C++ ALAudioDevice does (Python 2.7 cannot).

Used by naoqi_sim_audio_device_almodule (2.1, ALModule) and naoqi_sim_audio_device_qiservice (2.8, qi
service). Kept importable under Python 3 so the host's fast tests cover it.
"""
import json
import os
import socket
import struct
import sys
import threading
import time

try:
    import Queue as queue
except ImportError:  # Python 3, for the host-side tests
    import queue

SERVICE = "ALAudioDevice"
RELAY = "_NaoqiSimAudioRelay"
HOST_LINK = os.environ.get("NAOQI_SIM_HOST_LINK", "host.docker.internal:9563")

# setClientPreferences' channel constants (ALLCHANNELS, LEFTCHANNEL, ...) and NAO's mic order
CHANNELS = {0: "all", 1: "left", 2: "right", 3: "front", 4: "rear"}
MICS = ("left", "right", "front", "rear")
DEFAULT_FORMAT = (48000, "all", False)  # without setClientPreferences
QUEUE_SIZE = 4  # buffers waiting for one subscriber; the oldest is dropped beyond
FAILURES = 3  # consecutive failed deliveries that unsubscribe a subscriber...
FAILING_S = 2.0  # ...once they span this long (a new subscriber may not be reachable at once)
RETRY_S = 1.0  # between attempts to reach the host
# How long subscribe() waits for a service just registered to become visible: on 2.1 a qi
# service registered an instant before is not yet reachable through the broker's ALProxy.
EXISTS_WAIT_S = 1.0
EXISTS_POLL_S = 0.05

_LENGTHS = struct.Struct(">II")


def _stderr(msg):
    sys.stderr.write("[naoqi_sim_audio_device] %s\n" % msg)


def parse_preferences(sample_rate, channels, deinterleaved):
    """setClientPreferences' arguments -> a format (rate, channel, deinterleaved), as NAOqi's
    documentation lists them: 48 kHz all channels (interleaved or not), 16 kHz one channel."""
    rate, constant = int(sample_rate), int(channels)
    if constant not in CHANNELS:
        raise ValueError("channels must be one of %s, not %r" % (sorted(CHANNELS), channels))
    channel = CHANNELS[constant]
    if rate == 48000 and channel == "all":
        return (48000, "all", bool(deinterleaved))
    if rate == 16000 and channel != "all":
        return (16000, channel, False)
    raise ValueError(
        "unsupported format: %s Hz with channels %s (48000 Hz takes all channels, 16000 Hz one)"
        % (sample_rate, channels))


def format_header(fmt):
    return {"rate": fmt[0], "channel": fmt[1], "deinterleaved": fmt[2]}


def format_of(header):
    return (int(header["rate"]), str(header["channel"]), bool(header["deinterleaved"]))


def encode(header, payload=b""):
    """One message in the host link's framing: u32 | u32 | JSON header | payload, big-endian."""
    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return _LENGTHS.pack(len(head), len(payload)) + head + payload


def _read_exactly(rfile, n):
    data = rfile.read(n) if n else b""
    if len(data) != n:
        raise EOFError("connection closed")
    return data


def read_message(rfile):
    """The next (header, payload) from a buffered stream; EOFError when it ends."""
    header_len, payload_len = _LENGTHS.unpack(_read_exactly(rfile, _LENGTHS.size))
    header = json.loads(_read_exactly(rfile, header_len).decode("utf-8"))
    return header, _read_exactly(rfile, payload_len)


class Subscriber(object):
    """One subscriber's delivery thread: buffers are delivered in order, the oldest dropped when
    the subscriber falls QUEUE_SIZE behind, and `failed(name)` called after FAILURES consecutive
    failures over at least FAILING_S."""

    def __init__(self, name, fmt, deliver, failed, log):
        self.name = name
        self.format = fmt
        self._deliver = deliver
        self._failed = failed
        self._log = log
        self._queue = queue.Queue(QUEUE_SIZE)
        self._dropping = False
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name="ALAudioDevice-" + name)
        self._thread.daemon = True
        self._thread.start()

    def put(self, item):
        dropped = False
        while True:
            try:
                self._queue.put_nowait(item)
                break
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    dropped = True
                except queue.Empty:
                    pass
        if dropped and not self._dropping:
            self._log("%s falls behind: dropping its oldest buffers" % self.name)
        self._dropping = dropped

    def stop(self):
        self._stopped = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _run(self):
        failures, first_failure = 0, 0.0
        while not self._stopped:
            item = self._queue.get()
            if item is None or self._stopped:
                return
            try:
                self._deliver(self.name, *item)
                failures = 0
            except Exception as e:  # the subscriber is gone, or its processRemote raised
                failures += 1
                if failures == 1:
                    first_failure = time.time()
                if failures >= FAILURES and time.time() - first_failure >= FAILING_S:
                    self._log("%s: %d deliveries failed (%s): unsubscribed" % (self.name, failures, e))
                    self._failed(self.name)
                    return


class AudioDevice(object):
    """ALAudioDevice's state and logic; the version's shell exposes the methods.

    deliver(name, nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer): the relay's call.
    exists(name): whether a service by that name is registered.
    forget(name): tells the relay to drop its proxy to a subscriber, so the next delivery to that
    name reaches the service holding it then (called on unsubscribe, subscribe and failure)."""

    def __init__(self, deliver, exists, forget=None, address=HOST_LINK, log=_stderr, start=True):
        self._deliver = deliver
        self._exists = exists
        self._forget = forget
        self._log = log
        self._lock = threading.RLock()
        self._preferences = {}
        self._subscribers = {}
        self._listeners = {}  # in-process listeners (another module of ours), by name
        self._energy_on = False
        self._energy = dict((mic, 0.0) for mic in MICS)
        self.output_volume = 50
        self.link = Link(address, self._message, self.need, log)
        if start:
            self.link.start()

    # --- Preferences and subscriptions -------------------------------------------------------

    def set_preferences(self, name, sample_rate, channels, deinterleaved):
        fmt = parse_preferences(sample_rate, channels, deinterleaved)  # raises, keeping the old
        with self._lock:
            self._preferences[name] = fmt  # taken into account at the next subscribe

    def _wait_exists(self, name):
        """Whether a service `name` is registered, giving one registered an instant before
        (a client subscribing right after registering) EXISTS_WAIT_S to become visible."""
        end = time.time() + EXISTS_WAIT_S
        while not self._exists(name):
            if time.time() >= end:
                return False
            time.sleep(EXISTS_POLL_S)
        return True

    def subscribe(self, name):
        with self._lock:
            subscribed = name in self._subscribers
        if not subscribed and not self._wait_exists(name):
            raise RuntimeError("ALAudioDevice.subscribe: no module or service named %r" % name)
        # Whoever holds the name now gets the buffers: a client may have registered it again
        # (after an unsubscribe, or after dying without one), and the relay's proxy would still
        # reach the service it replaced.
        self._forget_proxy(name)
        with self._lock:
            if name in self._subscribers:
                return
            fmt = self._preferences.get(name, DEFAULT_FORMAT)
            self._subscribers[name] = Subscriber(name, fmt, self._deliver, self._failed, self._log)
        self.link.send_need()

    def unsubscribe(self, name):
        with self._lock:
            sub = self._subscribers.pop(name, None)
        if sub is not None:
            sub.stop()
            self.link.send_need()
            self._forget_proxy(name)

    def subscribers(self):
        with self._lock:
            return dict((name, sub.format) for name, sub in self._subscribers.items())

    def _failed(self, name):
        with self._lock:
            sub = self._subscribers.get(name)
            if sub is not None and not sub._stopped:
                del self._subscribers[name]
                sub._stopped = True
        self.link.send_need()
        self._forget_proxy(name)

    def _forget_proxy(self, name):
        if self._forget is not None:
            try:
                self._forget(name)
            except Exception as e:  # the relay keeps a stale proxy: the next subscribe retries
                self._log("%s: the relay could not forget its proxy (%s)" % (name, e))

    # --- In-process listeners ------------------------------------------------------------------

    def listen(self, name, sample_rate, channels, deliver):
        """Hands another module of ours, in this process, the buffers of a format (as
        setClientPreferences takes it) with no qi call: deliver(nbOfChannels,
        nbOfSamplesByChannel, timeStamp, buffer) on a thread of its own, the oldest buffer
        dropped when it falls behind. Listening again under a name replaces the previous one."""
        fmt = parse_preferences(sample_rate, channels, False)
        log = self._log

        def call(_name, *item):
            try:
                deliver(*item)
            except Exception as e:  # a listener's error is its own: keep delivering
                log("%s: listener raised %r" % (name, e))

        with self._lock:
            old = self._listeners.pop(name, None)
            self._listeners[name] = Subscriber(name, fmt, call, lambda n: None, log)
        if old is not None:
            old.stop()
        self.link.send_need()

    def unlisten(self, name):
        with self._lock:
            sub = self._listeners.pop(name, None)
        if sub is not None:
            sub.stop()
            self.link.send_need()

    # --- Energy -------------------------------------------------------------------------------

    def enable_energy(self):
        with self._lock:
            self._energy_on = True
        self.link.send_need()

    def disable_energy(self):
        with self._lock:
            self._energy_on = False
            self._energy = dict((mic, 0.0) for mic in MICS)
        self.link.send_need()

    def energy(self, mic):
        with self._lock:
            return float(self._energy[mic]) if self._energy_on else 0.0

    # --- The host link ------------------------------------------------------------------------

    def need(self):
        """The need message: the distinct formats the subscribers need, and the energy flag."""
        with self._lock:
            subs = list(self._subscribers.values()) + list(self._listeners.values())
            formats = sorted(set(sub.format for sub in subs))
            return {
                "type": "need",
                "formats": [format_header(f) for f in formats],
                "energy": self._energy_on,
            }

    def _message(self, header, payload):
        kind = header.get("type")
        if kind == "pcm":
            now = time.time()
            stamp = [int(now), int((now - int(now)) * 1000000)]
            fmt = format_of(header["format"])
            item = (int(header["channels"]), int(header["samples"]), stamp, payload)
            with self._lock:
                subs = list(self._subscribers.values()) + list(self._listeners.values())
                targets = [s for s in subs if s.format == fmt]
            for sub in targets:
                sub.put(item)
        elif kind == "energy":
            with self._lock:
                if self._energy_on:
                    for mic in MICS:
                        self._energy[mic] = float(header.get(mic, 0.0))

    def close(self):
        self.link.close()
        with self._lock:
            subs = list(self._subscribers.values()) + list(self._listeners.values())
            self._subscribers.clear()
            self._listeners.clear()
        for sub in subs:
            sub.stop()


class Link(object):
    """The container side of the host link: connects out, retrying every RETRY_S, says hello and
    the current need on every connection, and hands each message to `on_message`."""

    def __init__(self, address, on_message, need, log):
        host, port = address.rsplit(":", 1)
        self._address = (host, int(port))
        self._on_message = on_message
        self._need = need
        self._log = log
        self._send_lock = threading.Lock()
        self._sock = None
        self._stopped = threading.Event()
        self.connected = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ALAudioDevice-link")
        self._thread.daemon = True

    def start(self):
        self._thread.start()

    def send_need(self):
        self._send(self._need())

    def _send(self, header, payload=b""):
        with self._send_lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall(encode(header, payload))
                return True
            except (OSError, socket.error):
                return False

    def _run(self):
        failing = False
        while not self._stopped.is_set():
            try:
                sock = socket.create_connection(self._address, timeout=2.0)
                sock.settimeout(None)
            except (OSError, socket.error) as e:
                if not failing:
                    self._log("host link %s:%d unreachable (%s): retrying every %gs"
                              % (self._address[0], self._address[1], e, RETRY_S))
                    failing = True
                self._stopped.wait(RETRY_S)
                continue
            failing = False
            rfile = sock.makefile("rb")
            with self._send_lock:
                self._sock = sock
                try:
                    sock.sendall(encode({"type": "hello", "service": SERVICE}))
                    sock.sendall(encode(self._need()))
                except (OSError, socket.error):
                    pass
            self.connected.set()
            self._log("host link connected")
            try:
                while not self._stopped.is_set():
                    header, payload = read_message(rfile)
                    self._on_message(header, payload)
            except (EOFError, ValueError, OSError, socket.error, struct.error) as e:
                if not self._stopped.is_set():
                    self._log("host link lost (%s): reconnecting" % (e or "closed"))
            finally:
                self.connected.clear()
                with self._send_lock:
                    self._sock = None
                try:
                    rfile.close()
                    sock.close()
                except (OSError, socket.error):
                    pass
            self._stopped.wait(RETRY_S)

    def close(self):
        self._stopped.set()
        with self._send_lock:
            sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error):
                pass
        if self._thread.is_alive():
            self._thread.join(5)
