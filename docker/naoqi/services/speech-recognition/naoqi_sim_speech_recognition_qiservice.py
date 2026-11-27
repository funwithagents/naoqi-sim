# -*- coding: utf-8 -*-
"""ALSpeechRecognition for NAOqi 2.8, a qi service in naoqi-service (the gateway relays it), and
_AsrCompiler1, which the 2.8 dialog gives its grammar to: the methods of the robot's module (the table in
naoqi_sim_speech_recognition_core), each taking any arguments, since a missing signature stops
the dialog without a word; the listening in the core, the audio taken in-process from our
ALAudioDevice (specs/services/speech-recognition.md)."""
import os
import sys

import qi

import naoqi_sim_audio_device_qiservice as audio_device
import naoqi_sim_perception_stubs_core as ext
import naoqi_sim_speech_recognition_core as core

LOG = ext.JsonLog("/home/nao/speech_recognition.jsonl", "naoqi_sim_speech_recognition_qiservice")
METHODS = core.methods("2.8")

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)


def _log(message):
    LOG(message=message)


class _Memory(object):
    def __init__(self, proxy):
        self.insert = proxy.insertData
        self.raise_event = proxy.raiseEvent


class _Lazy(object):
    """A service asked for at its first use: ALDialog registers after this module."""

    def __init__(self, name):
        self.name = name
        self.proxy = None

    def __call__(self):
        if self.proxy is None:
            try:
                self.proxy = _session.service(self.name)
            except RuntimeError:
                return None
        return self.proxy


_dialog = _Lazy("ALDialog")


def _audio_device():
    return audio_device._service.device


def _method(name, arity, defaults):
    """Any arguments: those missing completed with the table's defaults (or None), the extra ones
    dropped; a count the table did not expect is logged."""
    def method(self, *args):
        args = list(args)
        if len(args) != arity and not (defaults and len(args) >= min(defaults)):
            LOG(method=name, args=args, note="called with %d arguments, %d expected" % (len(args), arity))
        for i in range(len(args), arity):
            args.append(eval(defaults[i]) if i in defaults else None)
        return self._call(name, args[:arity])
    method.__name__ = name
    return method


@qi.multiThreaded()
class ALSpeechRecognitionService(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self):
        memory = _session.service("ALMemory")
        # Declared with this module as their extractor, as on 2.1: ALMemory then calls
        # subscribe("ALDialogWordRecognized") when the dialog starts listening.
        for event in core.EVENTS:
            try:
                memory.declareEvent(event, core.NAME)
            except RuntimeError:
                pass
        installed = [l for l in os.environ.get("NAOQI_SIM_LANGUAGES", "English,French").split(",") if l]
        self.state = core.Recognition(
            "2.8",
            _Memory(memory),
            core.Engine(log=_log) if core.ENGINE_URL else None,
            lambda callback: _audio_device().listen(core.NAME, 16000, 3, callback),
            lambda: _audio_device().unlisten(core.NAME),
            core.Feedback(_Lazy("ALAudioPlayer"), _Lazy("ALLeds"), log=_log),
            _dialog,
            installed=installed,
            log=_log,
        )
        self.state.service = core.NAME
        core.write_source_key(memory.insertData)

    def _call(self, method, args):
        return ext.call(self.state, self.HANDLERS, method, args, LOG)


ALSpeechRecognitionService.HANDLERS = {}
for _name, _arity, _defaults, _handler in METHODS:
    setattr(ALSpeechRecognitionService, _name, _method(_name, _arity, _defaults))
    ALSpeechRecognitionService.HANDLERS[_name] = _handler


@qi.multiThreaded()
class AsrCompilerService(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self):
        self.service = core.COMPILER

    def _call(self, method, args):
        return ext.call(self, self.HANDLERS, method, args, LOG)


AsrCompilerService.HANDLERS = {}
for _name, _arity, _defaults, _handler in core.COMPILER_METHODS:
    setattr(AsrCompilerService, _name, _method(_name, _arity, _defaults))
    AsrCompilerService.HANDLERS[_name] = _handler

_service = ALSpeechRecognitionService()
# The dialog gives its grammar to the compiler service; the recognition reads it and listens for it.
AsrCompilerService.HANDLERS["compile"] = lambda _self, bnf, lcf, language: core._compile(_service.state, bnf, lcf, language)
_sid = _session.registerService(core.NAME, _service)
_cid = _session.registerService(core.COMPILER, AsrCompilerService())
LOG(method="registered", name=core.NAME, id=_sid, compiler=_cid, engine=core.ENGINE_URL)
sys.stderr.write("[naoqi_sim_speech_recognition_qiservice] registered %s (id %s) and %s (id %s), engine %r\n" % (
    core.NAME, _sid, core.COMPILER, _cid, core.ENGINE_URL))
