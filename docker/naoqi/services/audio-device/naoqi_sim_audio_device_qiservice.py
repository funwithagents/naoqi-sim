# -*- coding: utf-8 -*-
"""ALAudioDevice replacement for NAOqi 2.8, registered as a qi service (the gateway relays it).
The desktop suite has no ALAudioDevice, so the name is registered directly. The logic lives in
naoqi_sim_audio_device_core; buffers reach a subscriber through the native relay (_NaoqiSimAudioRelay),
which this module calls through its own session."""
import os
import sys
import time

import qi

import naoqi_sim_audio_device_core as core

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)


def _deliver(name, channels, samples, stamp, buffer):
    _session.service(core.RELAY).deliver(name, channels, samples, stamp, buffer)


def _forget(name):
    _session.service(core.RELAY).forget(name)


def _exists(name, wait_s=10.0):
    # Asked directly, and again for a while: a service a host client registers through the
    # gateway reaches this session a moment later (a client subscribes right after registering),
    # and services() does not list it at all.
    deadline = time.time() + wait_s
    while True:
        try:
            _session.service(name)
            return True
        except RuntimeError:
            if time.time() >= deadline:
                return False
            time.sleep(0.1)


@qi.multiThreaded()
class ALAudioDevice(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self):
        self.device = core.AudioDevice(_deliver, _exists, _forget)

    def setClientPreferences(self, name, sampleRate, channels, deinterleaved):
        try:
            self.device.set_preferences(name, sampleRate, channels, deinterleaved)
        except ValueError as e:
            raise RuntimeError("ALAudioDevice.setClientPreferences: %s" % e)

    def subscribe(self, name):
        self.device.subscribe(name)

    def unsubscribe(self, name):
        self.device.unsubscribe(name)

    def enableEnergyComputation(self):
        self.device.enable_energy()

    def disableEnergyComputation(self):
        self.device.disable_energy()

    def getFrontMicEnergy(self):
        return self.device.energy("front")

    def getRearMicEnergy(self):
        return self.device.energy("rear")

    def getLeftMicEnergy(self):
        return self.device.energy("left")

    def getRightMicEnergy(self):
        return self.device.energy("right")

    def openAudioInputs(self):
        pass

    def closeAudioInputs(self):
        pass

    def isInputMuted(self):
        return False

    def getOutputVolume(self):
        return self.device.output_volume

    def setOutputVolume(self, volume):
        self.device.output_volume = int(volume)


_service = ALAudioDevice()
_sid = _session.registerService(core.SERVICE, _service)
sys.stderr.write("[naoqi_sim_audio_device_qiservice] registered %s (id %s)\n" % (core.SERVICE, _sid))
