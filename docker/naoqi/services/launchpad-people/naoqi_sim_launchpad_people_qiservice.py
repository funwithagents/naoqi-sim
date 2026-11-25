# -*- coding: utf-8 -*-
"""The launchpad's people keys on NAOqi 2.8: a hidden qi service in naoqi-service, with no method for
clients, writing the keys of naoqi_sim_launchpad_people_core while Life runs. It subscribes to the
people module and the engagement zones in-process, and to their ALMemory events."""
import os
import sys

import qi

import naoqi_sim_engagement_zones_qiservice as zones
import naoqi_sim_launchpad_people_core as core
import naoqi_sim_people_perception_qiservice as people
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/launchpad_people.jsonl", "naoqi_sim_launchpad_people_qiservice")
VERSION = "2.8"


@qi.multiThreaded()
class LaunchpadPeopleService(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self, session):
        memory = session.service("ALMemory")
        self.core = core.LaunchpadPeople(people._service.module, zones._service.module, memory.getData,
                                         memory.raiseEvent, version=VERSION, log=LOG)
        self.core.start_worker()
        self.subscribers = []  # kept: a subscriber dropped stops its signal
        for event in core.EVENTS:
            subscriber = memory.subscriber(event)
            subscriber.signal.connect(lambda value, event=event: self.core.post(event, value))
            self.subscribers.append(subscriber)
        try:
            state = memory.getData(core.LIFE_STATE)
        except RuntimeError:  # Life never raised its state yet
            state = "disabled"
        self.core.post(core.LIFE_STATE, state)
        memory.insertData(core.STATUS_KEY, core.status(VERSION))
        LOG(method="started", life=state)


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = LaunchpadPeopleService(_session)
_sid = _session.registerService(core.NAME, _service)
LOG(method="registered", name=core.NAME, id=_sid)
sys.stderr.write("[naoqi_sim_launchpad_people_qiservice] registered %s (id %s)\n" % (core.NAME, _sid))
