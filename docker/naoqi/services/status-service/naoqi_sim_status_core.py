# -*- coding: utf-8 -*-
"""Shared logic of the NaoqiSim status service (Python 2.7, inside NAOqi).

The identity of a naoqi-sim target: the naoqi-sim and NAOqi versions, which host devices are
attached, and whether boot is complete, published as ALMemory keys under `NaoqiSim/`.

Used by naoqi_sim_status_almodule (2.1, ALModule) and naoqi_sim_status_qiservice (2.8, qi service).
Kept importable under Python 3 so the host's fast tests cover it.
"""
import os

SERVICE = "NaoqiSim"
PREFIX = "NaoqiSim/"
NONE = "none"  # no host device attached to that service
# "Camera" summarizes the two cameras' keys (specs/host/video-input.md)
DEVICES = ("Camera", "Camera/Top", "Camera/Bottom", "Audio")
DEFAULT_VERSION = "dev"
UNKNOWN = "unknown"


def versions(env=None):
    """(naoqi-sim version, NAOqi version) from the image's environment."""
    if env is None:
        env = os.environ
    return (
        env.get("NAOQI_SIM_VERSION") or DEFAULT_VERSION,
        env.get("NAOQI_SIM_NAOQI_VERSION") or UNKNOWN,
    )


class Status(object):
    """Writes the NaoqiSim/ keys at creation and flips NaoqiSim/Ready on set_ready().

    insert(key, value) writes an ALMemory key; raise_event(key, value) also notifies the
    subscribers of that key (ALMemory.insertData / ALMemory.raiseEvent on the real thing)."""

    def __init__(self, insert, raise_event, env=None):
        self.version, self.naoqi_version = versions(env)
        self.ready = False
        self._raise_event = raise_event
        insert(PREFIX + "Version", self.version)
        insert(PREFIX + "NaoqiVersion", self.naoqi_version)
        for device in DEVICES:
            insert(PREFIX + device + "/Source", NONE)
        insert(PREFIX + "Audio/Channels", NONE)  # the audio input's mono policy
        # the perception modules overwrite these at their load (specs/services/face-detection.md,
        # perception-stubs.md): `none` and no stub until then
        insert(PREFIX + "Perception/Source", NONE)
        insert(PREFIX + "Perception/Stubs", "")
        raise_event(PREFIX + "Ready", 0)

    def set_ready(self):
        self.ready = True
        self._raise_event(PREFIX + "Ready", 1)
