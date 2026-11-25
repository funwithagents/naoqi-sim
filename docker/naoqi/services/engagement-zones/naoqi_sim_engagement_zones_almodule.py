# -*- coding: utf-8 -*-
"""ALEngagementZones for NAOqi 2.1, an ALModule on naoqi-bin's broker in place of the built-in (left
out with the people-perception library): the generated methods of the table in
naoqi_sim_engagement_zones_core, the zones computed from the population of
naoqi_sim_people_perception_almodule."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_engagement_zones_core as core
import naoqi_sim_people_perception_almodule as people
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/engagement_zones.jsonl", "naoqi_sim_engagement_zones_almodule")


class ALEngagementZonesModule(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        self.module = core.Zones(people.ALPeoplePerception.module, memory.insertData, memory.removeData,
                                 memory.raiseEvent, version="2.1", log=LOG)
        for method, arity in ext.overloads(core.METHODS):  # subscribe(name), computeEngagementZone(x, y, z)
            self.BIND_PYTHON(name, method, arity)

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALEngagementZonesModule, core.METHODS)

# The instance must be a global named like the module: the broker finds it by that name.
ALEngagementZones = ALEngagementZonesModule(core.NAME)
LOG(method="registered", name=core.NAME)
sys.stderr.write("[naoqi_sim_engagement_zones_almodule] registered %s through the broker\n" % core.NAME)
