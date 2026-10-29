# -*- coding: utf-8 -*-
"""The perception stubs for NAOqi 2.8: one qi service per stub of naoqi_sim_perception_stubs_core's
table (overloads as varargs, the signals declared), plus _UserIdentification, the face-recognition
user database life's usersession waits for, with its typed `match`."""
import os
import sys

import qi

import naoqi_sim_perception_stubs_core as core

VERSION = "2.8"
LOG = core.JsonLog("/home/nao/perception_stubs.jsonl", "naoqi_sim_perception_stubs_qiservice")


class StubService(object):
    STUB = None

    def __init__(self, name):
        stub = self.STUB
        self.state = core.Extractor(name, stub.events, stub.keys, stub.settings, processes=False)
        for signal, signature in stub.signals.items():
            setattr(self, signal, qi.Signal(signature))

    def _call(self, method, args):
        return core.call(self.state, self.HANDLERS, method, args, LOG)


@qi.multiThreaded()
class UserIdentification(core.UserStore):
    def __init__(self):
        core.UserStore.__init__(self)
        for prop, (signature, value) in core.IDENT_PROPERTIES.items():
            p = qi.Property(signature)
            p.setValue(value)
            setattr(self, prop, p)

    # the session manager converts the reply to its struct: declared, a plain list fails
    @qi.bind(returnType=core.RECOGNITION_RESULT, paramsType=["i"])
    def match(self, ppid):
        return core.call(self, {"match": lambda s, p: core.UserStore.match(s, p)}, "match", [ppid], LOG)

    def _call(self, method, args):
        return core.call(self, self.HANDLERS, method, args, LOG)


core.install(UserIdentification, core.IDENT_METHODS, varargs=True)

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_registered = []
for _stub in core.stubs(VERSION):
    _name = _stub.name(VERSION)
    _cls = qi.multiThreaded()(type(_name + "Service", (StubService,), {"STUB": _stub}))
    core.install(_cls, _stub.methods, varargs=True)
    _registered.append((_name, _session.registerService(_name, _cls(_name))))
_registered.append((core.IDENT_NAME, _session.registerService(core.IDENT_NAME, UserIdentification())))
_names = core.write_stubs_key(_session.service("ALMemory").insertData, VERSION)
LOG(method="registered", names=_names, ids=[i for _, i in _registered])
sys.stderr.write("[naoqi_sim_perception_stubs_qiservice] registered %s\n" % ", ".join(_names))
