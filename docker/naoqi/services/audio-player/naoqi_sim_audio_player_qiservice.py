# -*- coding: utf-8 -*-
"""The audio player core for NAOqi 2.8, registered as the hidden qi service _NaoqiSimAudioPlayer (the
gateway relays it). ALAudioPlayer is the C++ front (naoqi_sim_audio_player_front.cpp), which forwards
every call here; the logic is naoqi_sim_audio_player_core (specs/services/audio-player.md)."""
import json
import os
import sys
import time

import qi

import naoqi_sim_audio_player_core as core

NAME = "_NaoqiSimAudioPlayer"
KIND = "qi.Session player core"
LOG = "/home/nao/audio_player_qiservice.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


@qi.multiThreaded()
class NaoqiSimAudioPlayer(object):
    """multiThreaded: the front's waitDone blocks while stopCall and stopAll must get through."""

    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self):
        self.player = core.Player(log=_log)

    def start(self, tid, kind, params):
        try:
            self.player.start(int(tid), kind, params)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def waitDone(self, tid, timeoutMs):
        try:
            return self.player.wait_done(int(tid), timeoutMs / 1000.0)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def stopCall(self, tid):
        try:
            self.player.stop_call(int(tid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def newId(self):
        try:
            return self.player.new_id()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def stopAll(self):
        try:
            self.player.stop_all()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def pause(self, tid):
        try:
            self.player.pause(int(tid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def goTo(self, tid, position):
        try:
            self.player.go_to(int(tid), float(position))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getCurrentPosition(self, tid):
        try:
            return float(self.player.get_current_position(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getFileLength(self, tid):
        try:
            return float(self.player.get_file_length(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setVolume(self, tid, volume):
        try:
            self.player.set_volume(int(tid), float(volume))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getVolume(self, tid):
        try:
            return float(self.player.get_volume(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setMasterVolume(self, volume):
        try:
            self.player.set_master_volume(float(volume))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getMasterVolume(self):
        try:
            return float(self.player.get_master_volume())
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setPanorama(self, pan):
        try:
            self.player.set_panorama(float(pan))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def loadFile(self, path):
        try:
            return self.player.load_file(path)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadFile(self, fid):
        try:
            self.player.unload_file(int(fid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadAllFiles(self):
        try:
            self.player.unload_all_files()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedFilesIds(self):
        try:
            return self.player.get_loaded_files_ids()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedFilesNames(self):
        try:
            return self.player.get_loaded_files_names()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getInstalledSoundSetsList(self):
        try:
            return self.player.get_installed_sound_sets_list()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedSoundSetsList(self):
        try:
            return self.player.get_loaded_sound_sets_list()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getSoundSetFileNames(self, name):
        try:
            return self.player.get_sound_set_file_names(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetInstalled(self, name):
        try:
            return self.player.is_sound_set_installed(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetLoaded(self, name):
        try:
            return self.player.is_sound_set_loaded(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetFileInstalled(self, name, fileName):
        try:
            return self.player.is_sound_set_file_installed(name, fileName)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def loadSoundSet(self, name):
        try:
            self.player.load_sound_set(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadSoundSet(self, name):
        try:
            self.player.unload_sound_set(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def whoami(self):
        try:
            return "naoqi-sim %s (audio output %s)" % (KIND, core.SOUNDCARD)
        except core.PlayerError as e:
            raise RuntimeError(str(e))


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = NaoqiSimAudioPlayer()
_sid = _session.registerService(NAME, _service)
_log(method="registered", name=NAME, id=_sid, url=_url, soundcard=core.SOUNDCARD)
sys.stderr.write("[naoqi_sim_audio_player_qiservice] registered %s (id %s)\n" % (NAME, _sid))
