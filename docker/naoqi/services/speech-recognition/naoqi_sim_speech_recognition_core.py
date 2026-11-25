# -*- coding: utf-8 -*-
"""ALSpeechRecognition's logic (Python 2.7, inside NAOqi; importable under Python 3 so the host's
fast tier tests it), shared by naoqi_sim_speech_recognition_almodule (2.1) and
naoqi_sim_speech_recognition_qiservice (2.8). See specs/services/speech-recognition.md.

`Recognition` keeps what a caller set (the vocabulary, the dialog's contexts and rules, the
subscribers, pause, language, the switches) and runs one worker thread that owns the listening:
it opens a session on the engine with the current phrases, hands it the front microphone's
audio (an in-process listener on our ALAudioDevice), and turns what the engine hears into a
NAO's statuses and events, and into the dialog's two callbacks. The worker is the only thread
that raises the listening events, so they come in a NAO's order.
"""
import io
import json
import math
import os
import struct
import sys
import threading
import time
import wave

try:
    import Queue as queue
    import urllib2
except ImportError:  # Python 3, for the host-side tests
    import queue
    import urllib.request as urllib2

import naoqi_sim_speech_recognition_grammar as grammar

NAME = "ALSpeechRecognition"
COMPILER = "_AsrCompiler1"  # 2.8: the dialog waits for it and calls its init()
ENGINE_URL = os.environ.get("NAOQI_SIM_ASR_URL", "")
ENGINE_TIMEOUT_S = 2.0
SOURCE_KEY = "NaoqiSim/SpeechRecognition/Source"
LANGUAGES = ("English", "French")  # the engine's models
DEFAULT_PERIOD = 30  # a subscriber's period, as the robot lists it
WAIT_S = 2.0  # how long subscribe, unsubscribe and pause wait for the statuses
GUARD_S = 0.35  # audio dropped after (re)starting to listen: the bip, the robot's last words
VOCABULARY_GRAMMAR = "modifiable_grammar"
RESET = ["", -3.0]  # WordRecognized when listening stops

STATUS = NAME + "/Status"
EVENTS = [
    "WordRecognizedAndGrammar", "WordRecognized", "SpeechDetected", "RecoLatency",
    "NoiseRecognized", "LastWordRecognized", NAME + "/IsConnected", NAME + "/IsRunning",
    STATUS, NAME + "/SignalTooLow", NAME + "/QueryError", NAME + "/ActiveListening",
]
END_OF_PROCESS = "SpeechRecognition/endOfProcess"

NOT_PAUSED = ("You need to stop or pause the ASR engine to be able to make this call.")


def native(text):
    """A string as NAOqi 2.1's Python takes it: a unicode string reaches ALMemory as null."""
    if not isinstance(text, str):
        try:
            return text.encode("utf-8")
        except AttributeError:
            return text
    return text


def _stderr(msg):
    sys.stderr.write("[naoqi_sim_speech_recognition] %s\n" % msg)


# --- the engine ----------------------------------------------------------------------------

class Engine(object):
    """The speech recognition engine's HTTP API (specs/container/asr-engine.md). Every call
    answers None when the engine cannot be reached, logged once per run of failures."""

    def __init__(self, url=ENGINE_URL, timeout=ENGINE_TIMEOUT_S, log=_stderr):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._log = log
        self._failing = False

    def _post(self, path, body, content_type):
        if not self.url:
            return None
        try:
            req = urllib2.Request(self.url + path, body, {"Content-Type": content_type})
            reply = json.loads(urllib2.urlopen(req, timeout=self.timeout).read().decode("utf-8"))
        except Exception as e:  # unreachable, a 4xx/5xx: silence, logged once
            if not self._failing:
                self._log("the engine at %s fails (%s): hearing nothing" % (self.url, e))
                self._failing = True
            return None
        if self._failing:
            self._log("the engine at %s answers again" % self.url)
            self._failing = False
        return reply

    def start(self, language, phrases, word_spotting):
        body = json.dumps({"language": language, "phrases": list(phrases),
                           "word_spotting": bool(word_spotting)}).encode("utf-8")
        return self._post("/start", body, "application/json")

    def audio(self, pcm):
        return self._post("/audio", pcm, "application/octet-stream")

    def stop(self):
        return self._post("/stop", b"", "application/octet-stream")


# --- bips and LEDs -------------------------------------------------------------------------

BIP_S = 0.11
BIP_RATE = 16000


def write_bip(path, f0, f1, duration=BIP_S, rate=BIP_RATE, amplitude=0.3):
    """A short tone sliding from f0 to f1 Hz, faded in and out, as a 16-bit mono WAV."""
    n = int(duration * rate)
    fade = int(0.01 * rate)
    phase = 0.0
    frames = []
    for i in range(n):
        f = f0 + (f1 - f0) * i / float(n)
        phase += 2 * math.pi * f / rate
        gain = min(1.0, i / float(fade), (n - 1 - i) / float(fade))
        frames.append(struct.pack("<h", int(32767 * amplitude * gain * math.sin(phase))))
    w = wave.open(path, "wb")
    try:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
    finally:
        w.close()
    return path


class Feedback(object):
    """The bips and the LED animation of the default behaviour: the eyes blue and turning and
    the ears turning while listening, the eyes green on a recognition, white eyes and lit ears
    when listening stops. `player()` and `leds()` give ALAudioPlayer and ALLeds."""

    EYES = "FaceLeds"
    EARS = "EarLeds"

    def __init__(self, player, leds, folder="/tmp", log=_stderr):
        self._player = player
        self._leds = leds
        self._log = log
        self.begin = os.path.join(folder, "naoqi_sim_asr_begin.wav")
        self.end = os.path.join(folder, "naoqi_sim_asr_end.wav")
        write_bip(self.begin, 900.0, 1500.0)
        write_bip(self.end, 1500.0, 900.0)
        self._eyes = threading.Event()
        self._ears = threading.Event()
        self._lock = threading.Lock()

    def _safely(self, what, call):
        try:
            call()
        except Exception as e:
            self._log("%s failed: %s" % (what, e))

    def begin_bip(self):
        self._safely("the begin bip", lambda: self._player().playFile(self.begin))

    def end_bip(self):
        self._safely("the end bip", lambda: self._player().playFile(self.end))

    def start_eyes(self):
        with self._lock:
            if self._eyes.is_set():
                return
            self._eyes.set()
        self._safely("the eyes", lambda: self._leds().fadeRGB(self.EYES, 0x0000FF, 0.05))
        threading.Thread(target=self._turn_eyes, name="ALSpeechRecognition-eyes").start()

    def _turn_eyes(self):
        while self._eyes.is_set():
            try:
                self._leds().rotateEyes(0x0055FF, 0.8, 0.8)
            except Exception as e:
                self._log("the eyes failed: %s" % e)
                time.sleep(0.8)

    def stop_eyes(self, color=0xFFFFFF):
        self._eyes.clear()
        if color is not None:
            self._safely("the eyes", lambda: self._leds().fadeRGB(self.EYES, color, 0.05))

    def start_ears(self):
        with self._lock:
            if self._ears.is_set():
                return
            self._ears.set()
        threading.Thread(target=self._turn_ears, name="ALSpeechRecognition-ears").start()

    def _turn_ears(self):
        angle = 0
        while self._ears.is_set():
            try:
                self._leds().earLedsSetAngle(angle, 0.1, False)
            except Exception as e:
                self._log("the ears failed: %s" % e)
                time.sleep(0.5)
            angle = (angle + 36) % 360

    def stop_ears(self, on=True):
        self._ears.clear()
        self._safely("the ears", lambda: self._leds().fade(self.EARS, 1.0 if on else 0.0, 0.05))

    # the default behaviour, around a listening
    def listening(self):
        self.start_eyes()
        self.start_ears()

    def heard(self, recognised):
        """Listening stopped at the end of an utterance: the animation pauses, green on a word."""
        self.stop_eyes(0x00FF00 if recognised else 0x000000)
        self.stop_ears(on=False)

    def idle(self):
        self.stop_eyes()
        self.stop_ears()


# --- the recognition -------------------------------------------------------------------------

class _Context(object):
    def __init__(self, grammar_=None):
        self.grammar = grammar_  # the grammar the dialog compiled for it, or None
        self.active = set()  # the activated rules
        self.slots = {}  # 2.1: slot -> word list
        self.params = {}


class Recognition(object):
    """ALSpeechRecognition's state and its listening worker.

    memory: insert(key, value) and raise_event(key, value) on ALMemory.
    engine: an `Engine` (or a fake).
    listen(callback) / unlisten(): the in-process listener on ALAudioDevice's front microphone at
    16 kHz; callback(nbOfChannels, nbOfSamples, timeStamp, buffer).
    feedback: a `Feedback`; it plays and lights by itself on 2.1 only (on 2.8 a NAO's
    signs-and-feedback application calls the hidden methods that drive it).
    dialog(): ALDialog's proxy, None while it is not registered.
    installed: the installed speech languages, in NAOqi's names."""

    def __init__(self, version, memory, engine, listen, unlisten, feedback, dialog,
                 installed=LANGUAGES, log=_stderr, start=True):
        self.version = version
        self.memory = memory
        self.engine = engine
        self._listen = listen
        self._unlisten = unlisten
        self.feedback = feedback
        self._dialog = dialog
        self._log = log
        self.languages = [l for l in installed if l in LANGUAGES]
        self.language = self.languages[0] if self.languages else ""
        self.own_feedback = version == "2.1"

        self._lock = threading.RLock()
        self.subscribers = {}  # name -> [period, precision]
        self.paused = False
        self.audio_expression = True
        self.visual_expression = True
        self.parameters = {"Sensitivity": 0.5}
        if version == "2.8":
            self.parameters["NbHypotheses"] = 1.0
        self.vocabulary = []
        self.word_spotting = False
        self.source = "vocabulary"  # whichever caller set the phrases last: or "dialog"
        self.contexts = {}  # name -> _Context
        self.compiled = {}  # 2.1: lcf path -> Grammar
        self.context_sets = {}  # 2.8: name -> [contexts]
        self._dirty = True

        # the worker's own state
        self.phase = "idle"  # idle, listen, speech, process
        self.running = False  # IsRunning: subscribed
        self.in_callback = False
        self._epoch = 0  # audio of an earlier listening is dropped
        self._accept_after = 0.0
        self._accepting = False
        self._session = (VOCABULARY_GRAMMAR, False, False)
        self._queue = queue.Queue()
        self._applied = threading.Condition(threading.Lock())
        self._requested = 0
        self._done = 0
        self._closed = False

        memory.insert(STATUS, "Idle")
        memory.insert(NAME + "/IsRunning", False)
        memory.insert(NAME + "/ActiveListening", False)
        memory.insert(NAME + "/IsConnected", 0)
        memory.insert("SpeechDetected", 0)
        memory.insert("WordRecognized", RESET)
        self._thread = threading.Thread(target=self._run, name="ALSpeechRecognition")
        self._thread.daemon = True
        if start:
            self._thread.start()

    # --- what callers set --------------------------------------------------------------------

    def _changed(self, wait=False):
        """The listening may have to change: the worker applies it; with `wait`, the caller
        returns once it did (as the robot's subscribe returns after ListenOn), unless the worker
        is inside the dialog's callback (the dialog may be the caller)."""
        with self._applied:
            self._requested += 1
            token = self._requested
        self._queue.put(("update", None, None))
        if not wait or self.in_callback or threading.current_thread() is self._thread:
            return
        end = time.time() + WAIT_S
        with self._applied:
            while self._done < token and not self._closed:
                left = end - time.time()
                if left <= 0:
                    return
                self._applied.wait(min(left, 0.1))

    def _listening_wanted(self):
        return bool(self.subscribers) and not self.paused and bool(self.language)

    def subscribe(self, name, period=DEFAULT_PERIOD, precision=0.0):
        if period is None or period < 0:
            period = DEFAULT_PERIOD
        if precision is None or precision < 0:
            precision = 0.0
        with self._lock:
            self.subscribers[name] = [int(period), float(precision)]
        self._changed(wait=True)

    def unsubscribe(self, name):
        with self._lock:
            self.subscribers.pop(name, None)
        self._changed(wait=True)

    def update_period(self, name, period):
        with self._lock:
            if name in self.subscribers:
                self.subscribers[name][0] = int(period)

    def update_precision(self, name, precision):
        with self._lock:
            if name in self.subscribers:
                self.subscribers[name][1] = float(precision)

    def subscribers_info(self):
        with self._lock:
            return [[n, p, pr] for n, (p, pr) in sorted(self.subscribers.items())]

    def current_period(self):
        with self._lock:
            periods = [p for p, _ in self.subscribers.values()]
        return min(periods) if periods else -1

    def current_precision(self):
        with self._lock:
            precisions = [pr for _, pr in self.subscribers.values()]
        return max(precisions) if precisions else -1.0

    def my_period(self, name):
        return self.subscribers.get(name, [-1, -1.0])[0]

    def my_precision(self, name):
        return self.subscribers.get(name, [-1, -1.0])[1]

    def pause(self, paused):
        with self._lock:
            self.paused = bool(paused)
        self._changed(wait=True)

    def _refuse_while_listening(self):
        if self._listening_wanted():
            raise RuntimeError("ALSpeechRecognition: " + NOT_PAUSED)

    def set_vocabulary(self, phrases, word_spotting=False):
        with self._lock:
            self._refuse_while_listening()
            self.vocabulary = [p for p in phrases if p]
            self.word_spotting = bool(word_spotting)
            self.source = "vocabulary"
            self._dirty = True
        self._changed()

    def set_language(self, language):
        if language not in self.languages:
            raise RuntimeError("ALSpeechRecognition::setLanguage\n\tThis engine does not support "
                               "the following language: %s" % language)
        with self._lock:
            if language != self.language:
                self.language = language
                self._dirty = True
        self._changed()

    def get_parameter(self, name):
        if name not in self.parameters:
            raise RuntimeError("ALSpeechRecognition::getParameter\n\tThis engine does not support "
                               "%s setting." % name)
        return float(self.parameters[name])

    def set_parameter(self, name, value):
        if name not in self.parameters:
            raise RuntimeError("ALSpeechRecognition::setParameter\n\tThis engine does not support "
                               "%s setting." % name)
        self.parameters[name] = float(value)

    def set_visual_expression(self, on):
        self.visual_expression = bool(on)

    def set_visual_expression_mode(self, mode):
        self.visual_expression = int(mode) != 0

    # --- the dialog's contexts -----------------------------------------------------------------

    def _dialog_changed(self):
        with self._lock:
            self.source = "dialog"
            self._dirty = True
        self._changed()

    def compile(self, bnf, lcf, language):
        """The dialog wrote its grammar at `bnf`; it will add it as a context by `lcf`."""
        try:
            parsed = grammar.Grammar(grammar.read_text(bnf))
        except (IOError, OSError, grammar.GrammarError) as e:
            self._log("compile(%r): %s" % (bnf, e))
            parsed = None
        with self._lock:
            self.compiled[lcf] = parsed
        try:  # the dialog expects the compiled file to exist
            folder = os.path.dirname(lcf)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            io.open(lcf, "ab").close()
        except (IOError, OSError) as e:
            self._log("compile(%r): could not write %r: %s" % (bnf, lcf, e))

    def add_context(self, lcf, name):
        """The dialog adds the grammar it had compiled to `lcf` as the context `name`
        (`addContext` on 2.1, `createContext` on 2.8)."""
        with self._lock:
            parsed = self.compiled.get(lcf)
            if parsed is None and lcf.endswith(".lcf"):
                try:  # a context compiled before this module loaded
                    parsed = grammar.Grammar(grammar.read_text(lcf[:-4] + ".bnf"))
                except (IOError, OSError, grammar.GrammarError):
                    parsed = None
            if parsed is None:
                self._log("the context %r has no grammar (%r): nothing to listen for in it" % (name, lcf))
            self.contexts[name] = _Context(parsed)
        self._dialog_changed()

    def remove_context(self, name):
        with self._lock:
            self.contexts.pop(name, None)
            for members in self.context_sets.values():
                if name in members:
                    members.remove(name)
            self._dirty = True
        self._changed()

    def remove_all_contexts(self):
        with self._lock:
            self.contexts.clear()
            self._dirty = True
        self._changed()

    def _context(self, name):
        with self._lock:
            if name not in self.contexts:
                self.contexts[name] = _Context()
            return self.contexts[name]

    def activate_rule(self, context, rule):
        self._context(context).active.add(rule)
        self._dialog_changed()

    def deactivate_rule(self, context, rule):
        self._context(context).active.discard(rule)
        self._dialog_changed()

    def activate_all_rules(self, context):
        ctx = self._context(context)
        if ctx.grammar is not None:
            ctx.active.update(ctx.grammar.activatable | set([ctx.grammar.start]))
        self._dialog_changed()

    def deactivate_all_rules(self, context):
        self._context(context).active.clear()
        self._dialog_changed()

    def add_word_list_to_slot(self, context, slot, words):
        self._context(context).slots[slot] = [w for w in words]
        self._dialog_changed()

    def remove_word_list_from_slot(self, context, slot):
        self._context(context).slots.pop(slot, None)
        self._dialog_changed()

    def set_context_param(self, context, name, value):
        self._context(context).params[name] = float(value)

    def get_context_param(self, context, name):
        return float(self._context(context).params.get(name, 1.0 if name == "AccuracyRatio" else 0.0))

    def get_rules(self, context, kind=""):
        with self._lock:
            ctx = self.contexts.get(context)
            if ctx is None or ctx.grammar is None:
                return []
            return sorted(ctx.grammar.activatable)

    # 2.8
    create_context = add_context

    def get_contexts(self):
        with self._lock:
            return sorted(self.contexts)

    def create_context_set(self, contexts, name):
        with self._lock:
            self.context_sets[name] = list(contexts or [])

    def add_context_to_set(self, set_name, context):
        with self._lock:
            members = self.context_sets.setdefault(set_name, [])
            if context not in members:
                members.append(context)

    def remove_context_from_set(self, set_name, context):
        with self._lock:
            members = self.context_sets.get(set_name, [])
            if context in members:
                members.remove(context)

    def remove_context_set(self, name):
        with self._lock:
            self.context_sets.pop(name, None)

    def delete_all_context_sets(self):
        with self._lock:
            self.context_sets.clear()

    def get_context_sets(self):
        with self._lock:
            return sorted(self.context_sets)

    # --- the phrases ---------------------------------------------------------------------------

    def _phrases(self):
        """(phrases, word spotting, grammar name, for the dialog) of the current source."""
        with self._lock:
            if self.source == "vocabulary":
                name = VOCABULARY_GRAMMAR + ("_wordspotting" if self.word_spotting else "")
                return list(self.vocabulary), self.word_spotting, name, False
            contexts = sorted(self.contexts.items())
            language = self.language
        name = contexts[0][0] if contexts else ""
        found = []
        seen = set()
        for _, ctx in contexts:
            if ctx.grammar is not None:
                for p in ctx.grammar.phrases(ctx.active, ctx.slots):
                    if p not in seen:
                        seen.add(p)
                        found.append(p)
        return found, False, name, True

    # --- the worker ----------------------------------------------------------------------------

    def _on_audio(self, channels, samples, stamp, buffer):
        """The audio device's listener: queued for the worker while it listens."""
        if self._accepting:
            self._queue.put(("audio", self._epoch, bytes(buffer)))

    def _raise(self, key, value):
        try:
            self.memory.raise_event(key, value)
        except Exception as e:
            self._log("raising %s failed: %s" % (key, e))

    def _run(self):
        listening_audio = False
        while not self._closed:
            try:
                kind, epoch, payload = self._queue.get(timeout=0.25)
            except queue.Empty:
                kind = "tick"
            try:
                if kind == "audio":
                    if epoch == self._epoch:
                        self._audio(payload)
                else:
                    self._apply()
                    with self._applied:
                        self._done = self._requested
                        self._applied.notify_all()
                wanted_audio = self.phase != "idle" and self.engine is not None
                if wanted_audio != listening_audio:
                    if wanted_audio:
                        self._listen(self._on_audio)
                    else:
                        self._unlisten()
                    listening_audio = wanted_audio
            except Exception as e:  # the worker must outlive anything
                self._log("the worker failed: %r" % e)

    def _apply(self):
        want = self._listening_wanted()
        if want and self.phase == "idle":
            self._start_listening()
        elif not want and self.phase != "idle":
            self._stop_listening()
        elif want and self.phase == "listen" and self._dirty:
            self._open_session()

    def _open_session(self):
        with self._lock:
            self._dirty = False  # before: a change while the phrases are computed marks it again
        phrases, spotting, name, dialog = self._phrases()
        with self._lock:
            self._session = (name, dialog, spotting)
        if self.engine is not None:
            reply = self.engine.start(self.language, phrases, spotting)
            if reply is not None and reply.get("dropped"):
                self._log("%d phrases the engine cannot hear, for example %r" % (
                    len(reply["dropped"]), reply["dropped"][:3]))
        self._log("listening for %d phrases (%s)" % (len(phrases), name or "no grammar"))

    def _start_listening(self):
        self._open_session()
        bip = self.own_feedback and self.audio_expression
        if bip:
            self.feedback.begin_bip()
        self._epoch += 1
        self._accept_after = time.time() + GUARD_S
        self._accepting = True
        self.phase = "listen"
        self._raise(STATUS, "ListenOn")
        if not self.running:
            self.running = True
            self._raise(NAME + "/IsRunning", True)
        self._raise(NAME + "/ActiveListening", True)
        if self.own_feedback and self.visual_expression:
            self.feedback.listening()

    def _stop_listening(self):
        unsubscribed = not self.subscribers
        self._accepting = False
        self._epoch += 1
        self.phase = "idle"
        self._raise("SpeechDetected", 0)
        if unsubscribed:
            self._raise("RecoLatency", 0)
            self._raise("NoiseRecognized", 0)
            self._raise("WordRecognized", list(RESET))
            self._raise("WordRecognizedAndGrammar", list(RESET) + [""])
        self._raise(STATUS, "Stop")
        self._raise(STATUS, "ListenOff")
        if self.own_feedback and self.audio_expression:
            self.feedback.end_bip()
        self._raise(NAME + "/ActiveListening", False)
        if unsubscribed and self.running:
            self.running = False
            self._raise(NAME + "/IsRunning", False)
        if self.own_feedback and self.visual_expression:
            self.feedback.idle()
        if self.engine is not None:
            self.engine.stop()

    def _audio(self, pcm):
        if self.phase not in ("listen", "speech") or time.time() < self._accept_after:
            return
        reply = self.engine.audio(pcm) if self.engine is not None else None
        if reply is None:
            return
        if (reply.get("speech") or reply.get("final")) and self.phase == "listen":
            self.phase = "speech"
            self._raise("SpeechDetected", 1)
            self._raise(STATUS, "SpeechDetected")
        if reply.get("final"):
            self._end_utterance(reply["final"])

    def _end_utterance(self, final):
        self._accepting = False
        self._epoch += 1
        self.phase = "process"
        ended = time.time()
        self._raise("SpeechDetected", 0)
        self._raise(STATUS, "ListenOff")
        if self.own_feedback and self.audio_expression:
            self.feedback.end_bip()
        self._raise(NAME + "/ActiveListening", False)
        name, dialog, spotting = self._session
        phrase = final.get("phrase") or ""
        if self.own_feedback and self.visual_expression:
            self.feedback.heard(bool(phrase))
        latency = round((time.time() - ended) * 1000.0)
        if phrase:
            confidence = float(final.get("confidence", 0.0))
            words = phrase.replace(grammar.GARBAGE, " ").split()
            text = native(" ".join(words))
            name = native(name)
            value = "<...> %s <...>" % text if spotting and not dialog else text
            self._raise("WordRecognizedAndGrammar", [value, confidence, name])
            self._raise("WordRecognized", [value, confidence])
            self._raise("LastWordRecognized", [value, confidence])
            self._raise("RecoLatency", latency)
            self._raise(STATUS, "EndOfProcess")
            self._raise(END_OF_PROCESS, 1)
            if dialog:
                self._to_dialog(text, confidence, name, len(words))
        else:
            self._raise("RecoLatency", latency)
            self._raise(STATUS, "EndOfProcess")
            self._raise(END_OF_PROCESS, 1)
        if self._listening_wanted():
            self.phase = "idle"
            self._start_listening()
        else:
            self._stop_listening()

    def _to_dialog(self, text, confidence, name, words):
        """The result to the dialog: its callback returns once its answer has been said, so
        the robot's voice is not listened to (specs/services/speech-recognition.md)."""
        dialog = self._dialog()
        if dialog is None:
            return
        self.in_callback = True
        try:
            dialog.wordsRecognizedCallback([text, confidence, name], words)
            dialog.endOfUtteranceCallback()
        except Exception as e:
            self._log("the dialog's callbacks failed: %s" % e)
        finally:
            self.in_callback = False

    def close(self):
        self._closed = True
        self._queue.put(("close", None, None))
        with self._applied:
            self._applied.notify_all()


# --- the methods each version answers --------------------------------------------------------

def _const(value):
    return lambda s, *a: value


def _none(s, *a):
    return None


# (name, arity, defaults, handler(recognition, *args)), the public ones first; `defaults` makes
# the shorter overloads (subscribe(name)) for 2.1's BIND_PYTHON.
COMMON = [
    ("subscribe", 3, {1: str(DEFAULT_PERIOD), 2: "0.0"}, lambda s, n, p, pr: s.subscribe(n, p, pr)),
    ("unsubscribe", 1, {}, lambda s, n: s.unsubscribe(n)),
    ("updatePeriod", 2, {}, lambda s, n, p: s.update_period(n, p)),
    ("updatePrecision", 2, {}, lambda s, n, p: s.update_precision(n, p)),
    ("getCurrentPeriod", 0, {}, lambda s: s.current_period()),
    ("getCurrentPrecision", 0, {}, lambda s: s.current_precision()),
    ("getMyPeriod", 1, {}, lambda s, n: s.my_period(n)),
    ("getMyPrecision", 1, {}, lambda s, n: s.my_precision(n)),
    ("getSubscribersInfo", 0, {}, lambda s: s.subscribers_info()),
    ("getOutputNames", 0, {}, lambda s: list(EVENTS)),
    ("getEventList", 0, {}, lambda s: list(EVENTS)),
    ("getMemoryKeyList", 0, {}, _const([])),
    ("pause", 1, {}, lambda s, b: s.pause(b)),
    ("setVocabulary", 2, {}, lambda s, v, w: s.set_vocabulary(v, w)),
    ("setWordListAsVocabulary", 1, {}, lambda s, v: s.set_vocabulary(v, False)),
    ("loadVocabulary", 1, {}, _none),
    ("getLanguage", 0, {}, lambda s: s.language),
    ("setLanguage", 1, {}, lambda s, l: s.set_language(l)),
    ("getAvailableLanguages", 0, {}, lambda s: list(s.languages)),
    ("getParameter", 1, {}, lambda s, n: s.get_parameter(n)),
    ("setParameter", 2, {}, lambda s, n, v: s.set_parameter(n, v)),
    ("getAudioExpression", 0, {}, lambda s: s.audio_expression),
    ("setAudioExpression", 1, {}, lambda s, b: setattr(s, "audio_expression", bool(b))),
    ("setVisualExpression", 1, {}, lambda s, b: s.set_visual_expression(b)),
    ("setVisualExpressionMode", 1, {}, lambda s, m: s.set_visual_expression_mode(m)),
    ("addContext", 2, {}, lambda s, lcf, n: s.add_context(lcf, n)),
    ("removeContext", 1, {}, lambda s, n: s.remove_context(n)),
    ("removeAllContext", 0, {}, lambda s: s.remove_all_contexts()),
    ("pushContexts", 0, {}, _none),
    ("popContexts", 0, {}, _none),
    ("activateRule", 2, {}, lambda s, c, r: s.activate_rule(c, r)),
    ("deactivateRule", 2, {}, lambda s, c, r: s.deactivate_rule(c, r)),
    ("activateAllRules", 1, {}, lambda s, c: s.activate_all_rules(c)),
    ("deactivateAllRules", 1, {}, lambda s, c: s.deactivate_all_rules(c)),
    ("addWordListToSlot", 3, {}, lambda s, c, slot, w: s.add_word_list_to_slot(c, slot, w)),
    ("removeWordListFromSlot", 2, {}, lambda s, c, slot: s.remove_word_list_from_slot(c, slot)),
    ("setContextParam", 3, {}, lambda s, c, n, v: s.set_context_param(c, n, v)),
    ("getContextParam", 2, {}, lambda s, c, n: s.get_context_param(c, n)),
    ("getRules", 2, {}, lambda s, c, k: s.get_rules(c, k)),
    ("saveContextSet", 1, {}, _const(True)),
    ("loadContextSet", 1, {}, _none),
    ("eraseContextSet", 1, {}, lambda s, n: s.remove_context_set(n)),
    ("compile", 3, {}, lambda s, bnf, lcf, l: s.compile(bnf, lcf, l)),
    # hidden: kept and answered, a missing one stops the dialog without a word
    ("_enableAudioLogging", 1, {}, _none),
    ("_enableFreeSpeechToText", 0, {}, _none),
    ("_disableFreeSpeechToText", 0, {}, _none),
    ("_isFreeSpeechToTextAvailable", 0, {}, _const(False)),
    ("_remoteConsumptionOk", 0, {}, _const(0)),
    ("_getVersion", 0, {}, None),  # set below
    ("_silentNextBipOn", 0, {}, _none),
    ("_silentNextBipOff", 0, {}, _none),
    ("_setDefaultLanguage", 1, {}, _none),
    ("_enableRealTimeThread", 1, {}, _none),
    ("_naoStoreApplicationInstalled", 3, {}, _none),
    ("_naoStoreApplicationUninstalled", 3, {}, _none),
]

ONLY_28 = [
    ("createContext", 2, {}, lambda s, lcf, n: s.create_context(lcf, n)),
    ("deleteContext", 1, {}, lambda s, n: s.remove_context(n)),
    ("getContexts", 0, {}, lambda s: s.get_contexts()),
    ("createContextSet", 2, {}, lambda s, cs, n: s.create_context_set(cs, n)),
    ("addContextSet", 1, {}, _none),
    ("addContextToSet", 2, {}, lambda s, n, c: s.add_context_to_set(n, c)),
    ("removeContextFromSet", 2, {}, lambda s, n, c: s.remove_context_from_set(n, c)),
    ("removeContextSet", 1, {}, lambda s, n: s.remove_context_set(n)),
    ("deleteContextSet", 1, {}, lambda s, n: s.remove_context_set(n)),
    ("deleteAllContextSets", 0, {}, lambda s: s.delete_all_context_sets()),
    ("getContextSets", 0, {}, lambda s: s.get_context_sets()),
    ("_connectRemote", 0, {}, _none),
    ("_disconnectRemote", 0, {}, _none),
    ("_enableBeamformer", 0, {}, _none),
    ("_disableBeamformer", 0, {}, _none),
    ("_beamformerEnabled", 0, {}, _const(False)),
    ("_playBipStart", 0, {}, lambda s: s.feedback.begin_bip()),
    ("_playBipStop", 0, {}, lambda s: s.feedback.end_bip()),
    ("_startEyesRotation", 0, {}, lambda s: s.feedback.start_eyes()),
    ("_stopEyesRotation", 0, {}, lambda s: s.feedback.stop_eyes()),
    ("_startEarsRotation", 0, {}, lambda s: s.feedback.start_ears()),
    ("_stopEarsRotation", 0, {}, lambda s: s.feedback.stop_ears()),
]

# What a NAO 2.1.4.13 answers (measured, not NAOqi's version); no 2.8 robot was measured, so 2.8
# answers the same.
VERSIONS = {"2.1": "4.5", "2.8": "4.5"}


def methods(version):
    """The method table a version's shell installs: the robot's module's whole list."""
    table = []
    for name, arity, defaults, handler in COMMON:
        if name == "_getVersion":
            handler = _const(VERSIONS[version])
        table.append((name, arity, defaults, handler))
    if version == "2.8":
        table += ONLY_28
    return table


def _compile(s, bnf, lcf, language):
    s.compile(bnf, lcf, language)
    return True


# 2.8: the service the dialog gives its grammar to; it shares the recognition's state
COMPILER_METHODS = [
    ("init", 0, {}, _const(True)),
    ("compile", 3, {}, _compile),
    ("destroy", 0, {}, _const(True)),
]


def write_source_key(insert, url=ENGINE_URL):
    insert(SOURCE_KEY, "engine" if url else "none")
