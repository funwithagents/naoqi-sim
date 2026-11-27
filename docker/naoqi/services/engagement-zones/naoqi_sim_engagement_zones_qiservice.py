# -*- coding: utf-8 -*-
"""ALEngagementZones for NAOqi 2.8, a qi service in naoqi-service in place of the built-in (left out
with the people-perception library): the generated methods of the table in
naoqi_sim_engagement_zones_core (overloads as varargs), the three settings' signals, the zones
computed from the population of naoqi_sim_people_perception_qiservice."""
import os
import sys

import qi

import naoqi_sim_engagement_zones_core as core
import naoqi_sim_people_perception_qiservice as people
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/engagement_zones.jsonl", "naoqi_sim_engagement_zones_qiservice")


@qi.multiThreaded()
class ALEngagementZonesService(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self, session):
        memory = session.service("ALMemory")
        for name, signature in core.SIGNALS.items():
            setattr(self, name, qi.Signal(signature))
        self.module = core.Zones(people._service.module, memory.insertData, memory.removeData,
                                 memory.raiseEvent, signal=self._signal, version="2.8", log=LOG)

    def _signal(self, name, *args):
        try:
            getattr(self, name)(*args)
        except Exception as e:  # noqa: BLE001
            LOG(method="signal-failed", name=name, error=repr(e))

    def _call(self, method, args):
        return ext.call(self.module, self.HANDLERS, method, args, LOG)


ext.install(ALEngagementZonesService, core.METHODS, varargs=True)

_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = ALEngagementZonesService(_session)
_sid = _session.registerService(core.NAME, _service)
LOG(method="registered", name=core.NAME, id=_sid)
sys.stderr.write("[naoqi_sim_engagement_zones_qiservice] registered %s (id %s)\n" % (core.NAME, _sid))
