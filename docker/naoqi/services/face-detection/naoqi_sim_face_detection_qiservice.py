# -*- coding: utf-8 -*-
"""ALFaceDetection for NAOqi 2.8, a qi service in naoqi-service (the gateway relays it): the
generated methods of the table in naoqi_sim_face_detection_core (overloads as varargs), the
camera, the engine and FaceDetected in its core."""
import os
import sys

import qi

import naoqi_sim_face_detection_core as core
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/face_detection.jsonl", "naoqi_sim_face_detection_qiservice")


@qi.multiThreaded()
class ALFaceDetectionService(object):
    def __init__(self, session):
        memory = session.service("ALMemory")
        self.detector = core.Detector(lambda: session.service("ALVideoDevice"), lambda: session.service("ALMotion"), core.Engine(), log=LOG)
        self.module = core.FaceModule(self.detector, memory.insertData, memory.raiseEvent, "2.8", LOG)
        core.write_source_key(memory.insertData)
        self.detector.start()

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALFaceDetectionService, core.METHODS, varargs=True)

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = ALFaceDetectionService(_session)
_sid = _session.registerService(core.NAME, _service)
LOG(method="registered", name=core.NAME, id=_sid, engine=core.ENGINE_URL)
sys.stderr.write("[naoqi_sim_face_detection_qiservice] registered %s (id %s), engine %r\n" % (core.NAME, _sid, core.ENGINE_URL))
