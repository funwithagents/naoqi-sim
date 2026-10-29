# -*- coding: utf-8 -*-
"""The perception stubs for NAOqi 2.1: one ALModule per stub of naoqi_sim_perception_stubs_core's
table, on naoqi-bin's broker, in place of the modules the people-perception library took with it."""
import sys

from naoqi import ALModule, ALProxy

import naoqi_sim_perception_stubs_core as core

VERSION = "2.1"
LOG = core.JsonLog("/home/nao/perception_stubs.jsonl", "naoqi_sim_perception_stubs_almodule")


class StubModule(ALModule):
    STUB = None

    def __init__(self, name):
        ALModule.__init__(self, name)
        stub = self.STUB
        self.state = core.Extractor(name, stub.events, stub.keys, stub.settings, processes=False)
        for method, arity in core.overloads(stub.methods):
            self.BIND_PYTHON(name, method, arity)

    def _call(self, method, args):
        return core.call(self.state, self.HANDLERS, method, args, LOG)


# The instances must be globals named like the modules: the broker finds them by that name.
for _stub in core.stubs(VERSION):
    _name = _stub.name(VERSION)
    _cls = type(_name + "Module", (StubModule,), {"STUB": _stub})
    core.install(_cls, _stub.methods)
    globals()[_name] = _cls(_name)
__all__ = core.stub_names(VERSION)
core.write_stubs_key(ALProxy("ALMemory").insertData, VERSION)
LOG(method="registered", names=__all__)
sys.stderr.write("[naoqi_sim_perception_stubs_almodule] registered %s through the broker\n" % ", ".join(__all__))
