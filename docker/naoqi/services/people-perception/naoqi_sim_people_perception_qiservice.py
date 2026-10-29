# -*- coding: utf-8 -*-
"""ALPeoplePerception for NAOqi 2.8, a qi service in naoqi-service in place of the built-in: the
generated methods of the table in naoqi_sim_people_perception_core (overloads as varargs), the
built-in's four signals, the population built on the face detector of
naoqi_sim_face_detection_qiservice."""
import os
import sys

import qi

import naoqi_sim_face_detection_qiservice as face
import naoqi_sim_people_perception_core as core
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/people_perception.jsonl", "naoqi_sim_people_perception_qiservice")


@qi.multiThreaded()
class ALPeoplePerceptionService(object):
    def __init__(self, session):
        memory = session.service("ALMemory")
        self.justArrived = qi.Signal("(i)")
        self.justLeft = qi.Signal("(i)")
        self.populationReset = qi.Signal("()")
        self.maximumDetectionRangeChanged = qi.Signal("(f)")
        self.module = core.Population(face._service.detector, memory.insertData, memory.removeData,
                                      memory.raiseEvent, signal=self._signal, version="2.8", log=LOG)

    def _signal(self, name, *args):
        try:
            getattr(self, name)(*args)
        except Exception as e:  # noqa: BLE001
            LOG(method="signal-failed", name=name, error=repr(e))

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALPeoplePerceptionService, core.METHODS, varargs=True)

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = ALPeoplePerceptionService(_session)
_sid = _session.registerService(core.NAME, _service)
LOG(method="registered", name=core.NAME, id=_sid)
sys.stderr.write("[naoqi_sim_people_perception_qiservice] registered %s (id %s)\n" % (core.NAME, _sid))
