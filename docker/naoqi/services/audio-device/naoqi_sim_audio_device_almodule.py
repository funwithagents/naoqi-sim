# -*- coding: utf-8 -*-
"""ALAudioDevice replacement for NAOqi 2.1, registered through naoqi-bin's broker (ALModule).
The desktop suite has no ALAudioDevice, so the name is registered directly. The logic lives in
naoqi_sim_audio_device_core; buffers reach a subscriber through the native relay (_NaoqiSimAudioRelay),
which this module calls through the broker."""
import sys
import threading

from naoqi import ALModule, ALProxy

import naoqi_sim_audio_device_core as core

_local = threading.local()  # one relay proxy per delivery thread


def _relay():
    proxy = getattr(_local, "relay", None)
    if proxy is None:
        proxy = _local.relay = ALProxy(core.RELAY)
    return proxy


def _deliver(name, channels, samples, stamp, buffer):
    _relay().deliver(name, channels, samples, stamp, buffer)


def _forget(name):
    _relay().forget(name)


def _exists(name):
    try:
        ALProxy(name)
        return True
    except RuntimeError:
        return False


class ALAudioDevice(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        self.device = core.AudioDevice(_deliver, _exists, _forget)

    def setClientPreferences(self, name, sampleRate, channels, deinterleaved):
        """Sets the format a subscriber gets from its next subscribe: 48000 Hz with all channels
        (0), interleaved or deinterleaved, or 16000 Hz with one channel (1 left, 2 right, 3 front,
        4 rear)."""
        try:
            self.device.set_preferences(name, sampleRate, channels, deinterleaved)
        except ValueError as e:
            raise RuntimeError("ALAudioDevice.setClientPreferences: %s" % e)

    def subscribe(self, name):
        """Starts calling name.processRemote with the microphones' buffers."""
        self.device.subscribe(name)

    def unsubscribe(self, name):
        """Stops calling name.processRemote."""
        self.device.unsubscribe(name)

    def enableEnergyComputation(self):
        """Computes the microphones' energy, with or without subscribers."""
        self.device.enable_energy()

    def disableEnergyComputation(self):
        """Stops computing the microphones' energy."""
        self.device.disable_energy()

    def getFrontMicEnergy(self):
        """The front microphone's energy over the last buffer, in [0, 32768]."""
        return self.device.energy("front")

    def getRearMicEnergy(self):
        """The rear microphone's energy over the last buffer, in [0, 32768]."""
        return self.device.energy("rear")

    def getLeftMicEnergy(self):
        """The left microphone's energy over the last buffer, in [0, 32768]."""
        return self.device.energy("left")

    def getRightMicEnergy(self):
        """The right microphone's energy over the last buffer, in [0, 32768]."""
        return self.device.energy("right")

    def openAudioInputs(self):
        """No-op: capture follows the subscribers."""

    def closeAudioInputs(self):
        """No-op: capture follows the subscribers."""

    def isInputMuted(self):
        """Always False: nothing mutes the microphones, the robot hears itself as a NAO does."""
        return False

    def getOutputVolume(self):
        """The output volume last set, 0 to 100."""
        return self.device.output_volume

    def setOutputVolume(self, volume):
        """Keeps the output volume, 0 to 100 (not applied to the audio output yet)."""
        self.device.output_volume = int(volume)


# The instance must be a global named like the module: the broker finds it by that name.
ALAudioDevice = ALAudioDevice(core.SERVICE)
sys.stderr.write("[naoqi_sim_audio_device_almodule] registered %s through the broker\n" % core.SERVICE)
