# -*- coding: utf-8 -*-
"""ALFaceDetection for NAOqi 2.1, an ALModule on naoqi-bin's broker: the generated methods of the
table in naoqi_sim_face_detection_core, the camera, the engine and FaceDetected in its core."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_face_detection_core as core
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/face_detection.jsonl", "naoqi_sim_face_detection_almodule")


class ALFaceDetectionModule(ALModule):
    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        self.detector = core.Detector(lambda: ALProxy("ALVideoDevice"), lambda: ALProxy("ALMotion"), core.Engine(), log=LOG)
        self.module = core.FaceModule(self.detector, memory.insertData, memory.raiseEvent, "2.1", LOG)
        for method, arity in ext.overloads(core.METHODS):  # subscribe(name)
            self.BIND_PYTHON(name, method, arity)
        core.write_source_key(memory.insertData)
        self.detector.start()

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALFaceDetectionModule, core.METHODS)

# The instance must be a global named like the module: the broker finds it by that name.
ALFaceDetection = ALFaceDetectionModule(core.NAME)
LOG(method="registered", name=core.NAME, engine=core.ENGINE_URL)
sys.stderr.write("[naoqi_sim_face_detection_almodule] registered %s through the broker, engine %r\n" % (core.NAME, core.ENGINE_URL))
