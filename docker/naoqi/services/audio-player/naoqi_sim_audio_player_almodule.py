# -*- coding: utf-8 -*-
"""The audio player core for NAOqi 2.1, registered through naoqi-bin's broker (ALModule) as the
hidden _NaoqiSimAudioPlayer. ALAudioPlayer is the C++ front (naoqi_sim_audio_player_front.cpp), which
forwards every call here; the logic is naoqi_sim_audio_player_core (specs/services/audio-player.md)."""
import json
import sys
import time

from naoqi import ALModule, ALProxy

import naoqi_sim_audio_player_core as core

NAME = "_NaoqiSimAudioPlayer"
KIND = "ALModule player core"
LOG = "/home/nao/audio_player_almodule.jsonl"
_t0 = time.time()


def _log(**f):
    f["t"] = round(time.time() - _t0, 3)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(f, default=repr) + "\n")


class NaoqiSimAudioPlayer(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        self.player = core.Player(log=_log)

    def start(self, tid, kind, params):
        """Starts play call tid (kind, JSON params); returns at once."""
        try:
            self.player.start(int(tid), kind, params)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def waitDone(self, tid, timeoutMs):
        """True once call tid is over, waiting at most timeoutMs."""
        try:
            return self.player.wait_done(int(tid), timeoutMs / 1000.0)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def stopCall(self, tid):
        """Stops call tid (a task id or a loaded file id)."""
        try:
            self.player.stop_call(int(tid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def newId(self):
        """An id for a blocking call."""
        try:
            return self.player.new_id()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def stopAll(self):
        """Stops every sound."""
        try:
            self.player.stop_all()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def pause(self, tid):
        """Pauses a sound."""
        try:
            self.player.pause(int(tid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def goTo(self, tid, position):
        """Jumps to a position (seconds)."""
        try:
            self.player.go_to(int(tid), float(position))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getCurrentPosition(self, tid):
        """The position (seconds)."""
        try:
            return float(self.player.get_current_position(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getFileLength(self, tid):
        """The length (seconds)."""
        try:
            return float(self.player.get_file_length(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setVolume(self, tid, volume):
        """A sound's own volume."""
        try:
            self.player.set_volume(int(tid), float(volume))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getVolume(self, tid):
        """A sound's own volume."""
        try:
            return float(self.player.get_volume(int(tid)))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setMasterVolume(self, volume):
        """The player's volume."""
        try:
            self.player.set_master_volume(float(volume))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getMasterVolume(self):
        """The player's volume."""
        try:
            return float(self.player.get_master_volume())
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def setPanorama(self, pan):
        """The pan of every sound."""
        try:
            self.player.set_panorama(float(pan))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def loadFile(self, path):
        """Loads a file; returns its id."""
        try:
            return self.player.load_file(path)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadFile(self, fid):
        """Unloads a file."""
        try:
            self.player.unload_file(int(fid))
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadAllFiles(self):
        """Unloads every file."""
        try:
            self.player.unload_all_files()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedFilesIds(self):
        """The loaded files' ids."""
        try:
            return self.player.get_loaded_files_ids()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedFilesNames(self):
        """The loaded files' paths."""
        try:
            return self.player.get_loaded_files_names()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getInstalledSoundSetsList(self):
        """The installed sound sets."""
        try:
            return self.player.get_installed_sound_sets_list()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getLoadedSoundSetsList(self):
        """The loaded sound sets."""
        try:
            return self.player.get_loaded_sound_sets_list()
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def getSoundSetFileNames(self, name):
        """The sounds of a set."""
        try:
            return self.player.get_sound_set_file_names(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetInstalled(self, name):
        """Whether a set is installed."""
        try:
            return self.player.is_sound_set_installed(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetLoaded(self, name):
        """Whether a set is loaded."""
        try:
            return self.player.is_sound_set_loaded(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def isSoundSetFileInstalled(self, name, fileName):
        """Whether a set has a sound."""
        try:
            return self.player.is_sound_set_file_installed(name, fileName)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def loadSoundSet(self, name):
        """Loads a sound set."""
        try:
            self.player.load_sound_set(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def unloadSoundSet(self, name):
        """Unloads a sound set."""
        try:
            self.player.unload_sound_set(name)
        except core.PlayerError as e:
            raise RuntimeError(str(e))

    def whoami(self):
        """Identifies this implementation."""
        try:
            return "naoqi-sim %s (audio output %s)" % (KIND, core.SOUNDCARD)
        except core.PlayerError as e:
            raise RuntimeError(str(e))


# The instance must be a global named like the module: the broker finds it by that name, in the
# namespace launchPythonModule's `from <module> import *` fills, which skips underscore names
# unless __all__ lists them.
__all__ = [NAME]
_NaoqiSimAudioPlayer = NaoqiSimAudioPlayer(NAME)
_log(method="registered", name=NAME, soundcard=core.SOUNDCARD)
sys.stderr.write("[naoqi_sim_audio_player_almodule] registered %s through the broker\n" % NAME)
