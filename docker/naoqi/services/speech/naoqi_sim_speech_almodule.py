# -*- coding: utf-8 -*-
"""The speech core for NAOqi 2.1, registered through naoqi-bin's broker (ALModule) as the hidden
_NaoqiSimTextToSpeech. ALTextToSpeech is the C++ front (docker/services/speech/naoqi_sim_speech_front.cpp), which forwards
every call here; speech itself is done by naoqi_sim_speech_core (tts container + host audio output)."""
import json
import sys
import time

from naoqi import ALModule, ALProxy

import naoqi_sim_speech_core as core

NAME = "_NaoqiSimTextToSpeech"
LOG = "/home/nao/speech_almodule.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


class NaoqiSimTextToSpeech(ALModule):
    def __init__(self, name):
        ALModule.__init__(self, name)
        self.memory = ALProxy("ALMemory")
        self.speaker = core.Speaker(self.memory.raiseEvent, log=_log)

    # -- what the front's long calls use ---------------------------------------
    def start(self, sid, text, lang):
        """Starts speaking text as call sid (in lang if not empty), returns at once."""
        self.speaker.start(int(sid), text, lang or None)

    def waitDone(self, sid, timeoutMs):
        """True once call sid is over, waiting at most timeoutMs."""
        return self.speaker.wait_done(int(sid), timeoutMs / 1000.0)

    def stopCall(self, sid):
        """Stops call sid: the speaking one ends, a waiting one is dropped."""
        self.speaker.stop_call(int(sid))

    def newId(self):
        """An id for a blocking call, which has no task id."""
        return self.speaker.new_id()

    # -- forwarded as they are ---------------------------------------------------
    def sayToFile(self, text, path):
        """Not supported on naoqi-sim."""
        _log(method="sayToFile", text=text, path=path)

    def stopAll(self):
        """Stops all current speech."""
        self.speaker.stop_all()

    def setLanguage(self, lang):
        """Sets the language."""
        self.speaker.set_language(lang)

    def getLanguage(self):
        """Returns the current language."""
        return self.speaker.language

    def getAvailableLanguages(self):
        """Returns the installed languages."""
        return list(core.LANGUAGES)

    def getSupportedLanguages(self):
        """Returns the supported languages."""
        return list(core.SUPPORTED_LANGUAGES)

    def setParameter(self, name, value):
        """Sets a parameter (speed, pitchShift...)."""
        self.speaker.set_parameter(name, value)

    def getParameter(self, name):
        """Gets a parameter."""
        return self.speaker.get_parameter(name)

    def resetSpeed(self):
        """Resets the speed."""
        self.speaker.state["rspd"] = 100

    def setVolume(self, v):
        """Sets the volume."""
        self.speaker.volume = float(v)

    def getVolume(self):
        """Returns the volume."""
        return self.speaker.volume

    def setVoice(self, v):
        """Sets the voice (ignored)."""
        _log(method="setVoice", v=v)

    def getVoice(self):
        """Returns the voice."""
        return "naoqisim"

    def getAvailableVoices(self):
        """Returns the voices."""
        return ["naoqisim"]

    def locale(self):
        """Returns the locale."""
        return self.speaker.locale()

    def loadVoicePreference(self, name):
        """Loads a voice preference (ignored)."""
        _log(method="loadVoicePreference", name=name)

    def setLanguageDefaultVoice(self, lang, voice):
        """Sets the default voice of a language (ignored)."""
        _log(method="setLanguageDefaultVoice", lang=lang, voice=voice)

    def enableNotifications(self):
        """Deprecated no-op."""
        _log(method="enableNotifications")

    def disableNotifications(self):
        """Deprecated no-op."""
        _log(method="disableNotifications")

    def whoami(self):
        """Identifies this implementation."""
        return "naoqi-sim ALModule replacement (engine %s)" % core.TTS_URL


# The instance must be a global named like the module: the broker finds it by that name, in the
# namespace launchPythonModule's `from <module> import *` fills, which skips underscore names
# unless __all__ lists them.
__all__ = [NAME]
_NaoqiSimTextToSpeech = NaoqiSimTextToSpeech(NAME)
_log(method="registered", name=NAME, tts_url=core.TTS_URL)
sys.stderr.write("[naoqi_sim_speech_almodule] registered %s through the broker, engine %s\n" % (NAME, core.TTS_URL))
