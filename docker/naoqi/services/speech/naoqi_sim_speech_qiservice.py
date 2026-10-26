# -*- coding: utf-8 -*-
"""The speech core for NAOqi 2.8, registered as the hidden qi service _NaoqiSimTextToSpeech (the
gateway relays it). ALTextToSpeech is the C++ front (docker/services/speech/naoqi_sim_speech_front.cpp), which forwards
every call here, carries the built-in's hidden signals (_started, synchroTTS, languageTTS) and
_sayWithLocale, which ALAnimatedSpeech 2.8 needs, and fires the signals when this core asks
(`_fire`). Speech itself is done by naoqi_sim_speech_core."""
import json
import os
import sys
import time

import qi

import naoqi_sim_speech_core as core

NAME = "_NaoqiSimTextToSpeech"
FRONT = "ALTextToSpeech"
LOG = "/home/nao/speech_qiservice.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


@qi.multiThreaded()
class NaoqiSimTextToSpeech(object):
    """multiThreaded: the front's waitDone blocks while stopCall and stopAll must get through."""

    def __init__(self, session):
        self.session = session
        self.memory = session.service("ALMemory")
        self._front = None
        self.speaker = core.Speaker(self.memory.raiseEvent, signal=self._signal, log=_log)

    def _signal(self, name, *args):
        # The front owns the signals; never connect to them from here (it crashed naoqi-service).
        try:
            if self._front is None:
                self._front = self.session.service(FRONT)
            self._front.call("_fire", name, *[str(a) for a in args])
        except Exception as e:  # noqa: BLE001
            self._front = None
            _log(method="fire-failed", name=name, error=repr(e))

    # -- what the front's long calls use ---------------------------------------
    def start(self, sid, text, lang):
        self.speaker.start(int(sid), text, lang or None)

    def waitDone(self, sid, timeoutMs):
        return self.speaker.wait_done(int(sid), timeoutMs / 1000.0)

    def stopCall(self, sid):
        self.speaker.stop_call(int(sid))

    def newId(self):
        return self.speaker.new_id()

    # -- forwarded as they are ---------------------------------------------------
    def sayToFile(self, text, path):
        _log(method="sayToFile", text=text, path=path)

    def stopAll(self):
        self.speaker.stop_all()

    def setLanguage(self, lang):
        self.speaker.set_language(lang)

    def getLanguage(self):
        return self.speaker.language

    def getAvailableLanguages(self):
        return list(core.LANGUAGES)

    def getSupportedLanguages(self):
        return list(core.SUPPORTED_LANGUAGES)

    def resetSpeed(self):
        self.speaker.state["rspd"] = 100

    def setParameter(self, name, value):
        self.speaker.set_parameter(name, value)

    def getParameter(self, name):
        return self.speaker.get_parameter(name)

    def setVoice(self, v):
        _log(method="setVoice", v=v)

    def getVoice(self):
        return "naoqisim"

    def getAvailableVoices(self):
        return ["naoqisim"]

    def setVolume(self, v):
        self.speaker.volume = float(v)

    def getVolume(self):
        return self.speaker.volume

    def locale(self):
        return self.speaker.locale()

    def loadVoicePreference(self, name):
        _log(method="loadVoicePreference", name=name)

    def setLanguageDefaultVoice(self, lang, voice):
        _log(method="setLanguageDefaultVoice", lang=lang, voice=voice)

    def enableNotifications(self):
        _log(method="enableNotifications")

    def disableNotifications(self):
        _log(method="disableNotifications")

    def pause(self):
        _log(method="_pause")

    def resume(self):
        _log(method="_resume")

    def reset(self):
        _log(method="reset")

    def whoami(self):
        return "naoqi-sim qi.Session replacement (2.8, engine %s)" % core.TTS_URL


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = NaoqiSimTextToSpeech(_session)
_sid = _session.registerService(NAME, _service)
_log(method="registered", name=NAME, id=_sid, url=_url, tts_url=core.TTS_URL)
sys.stderr.write("[naoqi_sim_speech_qiservice] registered %s (id %s), engine %s\n" % (NAME, _sid, core.TTS_URL))
