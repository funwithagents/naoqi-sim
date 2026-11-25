# -*- coding: utf-8 -*-
"""ALSpeechRecognition for NAOqi 2.1, an ALModule on naoqi-bin's broker: the methods of the robot's
module (the table in naoqi_sim_speech_recognition_core), the listening in its core, the audio
taken in-process from our ALAudioDevice (specs/services/speech-recognition.md)."""
import os
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_audio_device_almodule as audio_device
import naoqi_sim_perception_stubs_core as ext
import naoqi_sim_speech_recognition_core as core

LOG = ext.JsonLog("/home/nao/speech_recognition.jsonl", "naoqi_sim_speech_recognition_almodule")
METHODS = core.methods("2.1")


class _Memory(object):
    def __init__(self, proxy):
        self.insert = proxy.insertData
        self.raise_event = proxy.raiseEvent


class _Lazy(object):
    """A proxy made at its first use: ALDialog registers after this module."""

    def __init__(self, name):
        self.name = name
        self.proxy = None

    def __call__(self):
        if self.proxy is None:
            try:
                self.proxy = ALProxy(self.name)
            except RuntimeError:
                return None
        return self.proxy


def _audio_device():
    return audio_device.ALAudioDevice.device


class ALSpeechRecognitionModule(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        # Declared with this module as their extractor: ALMemory then calls subscribe(<subscriber
        # module><event>, period, precision) when a module subscribes to one of them, which is
        # how the 2.1 dialog starts the listening (it calls no subscribe itself).
        for event in core.EVENTS:
            try:
                memory.declareEvent(event, name)
            except RuntimeError:
                pass
        installed = [l for l in os.environ.get("NAOQI_SIM_LANGUAGES", "English,French").split(",") if l]
        self.state = core.Recognition(
            "2.1",
            _Memory(memory),
            core.Engine(log=self._log) if core.ENGINE_URL else None,
            lambda callback: _audio_device().listen(core.NAME, 16000, 3, callback),
            lambda: _audio_device().unlisten(core.NAME),
            core.Feedback(_Lazy("ALAudioPlayer"), _Lazy("ALLeds"), log=self._log),
            _Lazy("ALDialog"),
            installed=installed,
            log=self._log,
        )
        self.state.service = core.NAME
        # The ALModule binds no method whose name starts with "_", and subscribe's one-argument
        # form needs its own binding: both by hand.
        for method, arity, defaults, _ in METHODS:
            arities = [min(defaults)] if defaults else []
            if method.startswith("_"):
                arities.append(arity)
            for n in arities:
                self.functionName(method, name, "")
                for i in range(n):
                    self.addParam("a%d" % i)
                self._bindWithParam(name, method, n)
        core.write_source_key(memory.insertData)

    def _log(self, message):
        LOG(message=message)

    def _call(self, method, args):
        return ext.call(self.state, self.HANDLERS, method, args, LOG)


ext.install(ALSpeechRecognitionModule, METHODS)

# The instance must be a global named like the module: the broker finds it by that name.
ALSpeechRecognition = ALSpeechRecognitionModule(core.NAME)
LOG(method="registered", name=core.NAME, engine=core.ENGINE_URL)
sys.stderr.write("[naoqi_sim_speech_recognition_almodule] registered %s through the broker, engine %r\n" % (core.NAME, core.ENGINE_URL))
