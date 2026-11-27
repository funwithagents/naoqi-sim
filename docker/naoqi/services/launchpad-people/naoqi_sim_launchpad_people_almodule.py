# -*- coding: utf-8 -*-
"""The launchpad's people keys on NAOqi 2.1: a hidden ALModule on naoqi-bin's broker, with no method
for clients, writing the keys of naoqi_sim_launchpad_people_core while Life runs. It subscribes to
the people module and the engagement zones in-process, and to their ALMemory events."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_engagement_zones_almodule as zones
import naoqi_sim_launchpad_people_core as core
import naoqi_sim_people_perception_almodule as people
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/launchpad_people.jsonl", "naoqi_sim_launchpad_people_almodule")
VERSION = "2.1"


class LaunchpadPeopleModule(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        self.core = core.LaunchpadPeople(people.ALPeoplePerception.module, zones.ALEngagementZones.module,
                                         memory.getData, memory.raiseEvent, version=VERSION, log=LOG)
        self.core.start_worker()

    def onEvent(self, key, value, message):
        """naoqi-sim: an ALMemory event the launchpad's people keys follow."""
        self.core.post(key, value)


# The instance must be a global named like the module: the broker finds it by that name, and a
# hidden name is only exported through __all__.
_NaoqiSimLaunchpadPeople = LaunchpadPeopleModule(core.NAME)
__all__ = [core.NAME]
_memory = ALProxy("ALMemory")
for _event in core.EVENTS:
    _memory.subscribeToEvent(_event, core.NAME, "onEvent")
try:
    _state = _memory.getData(core.LIFE_STATE)
except RuntimeError:  # Life never raised its state yet
    _state = "disabled"
_NaoqiSimLaunchpadPeople.core.post(core.LIFE_STATE, _state)
_memory.insertData(core.STATUS_KEY, core.status(VERSION))
LOG(method="registered", name=core.NAME, life=_state)
sys.stderr.write("[naoqi_sim_launchpad_people_almodule] registered %s through the broker\n" % core.NAME)
