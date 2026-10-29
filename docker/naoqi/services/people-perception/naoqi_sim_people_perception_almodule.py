# -*- coding: utf-8 -*-
"""ALPeoplePerception for NAOqi 2.1, an ALModule on naoqi-bin's broker in place of the built-in:
the generated methods of the table in naoqi_sim_people_perception_core, the population built on
the face detector of naoqi_sim_face_detection_almodule."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_face_detection_almodule as face
import naoqi_sim_people_perception_core as core
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/people_perception.jsonl", "naoqi_sim_people_perception_almodule")


class ALPeoplePerceptionModule(ALModule):
    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        self.module = core.Population(face.ALFaceDetection.detector, memory.insertData, memory.removeData,
                                      memory.raiseEvent, version="2.1", log=LOG)
        for method, arity in ext.overloads(core.METHODS):  # subscribe(name)
            self.BIND_PYTHON(name, method, arity)

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALPeoplePerceptionModule, core.METHODS)

# The instance must be a global named like the module: the broker finds it by that name.
ALPeoplePerception = ALPeoplePerceptionModule(core.NAME)
LOG(method="registered", name=core.NAME)
sys.stderr.write("[naoqi_sim_people_perception_almodule] registered %s through the broker\n" % core.NAME)
