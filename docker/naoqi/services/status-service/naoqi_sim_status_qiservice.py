# -*- coding: utf-8 -*-
"""NaoqiSim status service for NAOqi 2.8, registered as a qi service (the gateway relays it).
The keys and the ready flag live in naoqi_sim_status_core."""
import os
import sys

import qi

import naoqi_sim_status_core as core


class NaoqiSim(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self, session):
        memory = session.service("ALMemory")
        self.status = core.Status(memory.insertData, memory.raiseEvent)

    def getVersion(self):
        return self.status.version

    def getNaoqiVersion(self):
        return self.status.naoqi_version

    def isReady(self):
        return self.status.ready

    def setReady(self):
        self.status.set_ready()


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = NaoqiSim(_session)
_sid = _session.registerService(core.SERVICE, _service)
sys.stderr.write("[naoqi_sim_status_qiservice] registered %s (id %s; naoqi-sim %s, NAOqi %s)\n"
                 % (core.SERVICE, _sid, _service.status.version, _service.status.naoqi_version))
