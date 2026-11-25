# -*- coding: utf-8 -*-
"""NaoqiSim status service for NAOqi 2.1, registered through naoqi-bin's broker (ALModule).
The keys and the ready flag live in naoqi_sim_status_core."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_status_core as core


class NaoqiSim(ALModule):
    def version(self):
        """Returns the version of the module."""
        # NAOqi's own answer (a Python ALModule's is 'PythonModule'), asked of a built-in
        return ALProxy("ALMemory").version()

    def __init__(self, name):
        ALModule.__init__(self, name)
        memory = ALProxy("ALMemory")
        self.status = core.Status(memory.insertData, memory.raiseEvent)

    def getVersion(self):
        """Returns the naoqi-sim version this image was built with."""
        return self.status.version

    def getNaoqiVersion(self):
        """Returns the full NAOqi version of the suite running in this container."""
        return self.status.naoqi_version

    def isReady(self):
        """Returns whether naoqi-sim finished booting: overrides loaded and replaced services answering."""
        return self.status.ready

    def setReady(self):
        """Marks boot complete; called by the entrypoint as its last step."""
        self.status.set_ready()


# The instance must be a global named like the module: the broker finds it by that name.
NaoqiSim = NaoqiSim(core.SERVICE)
sys.stderr.write("[naoqi_sim_status_almodule] registered %s through the broker (naoqi-sim %s, NAOqi %s)\n"
                 % (core.SERVICE, NaoqiSim.status.version, NaoqiSim.status.naoqi_version))
