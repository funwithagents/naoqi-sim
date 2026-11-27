# -*- coding: utf-8 -*-
"""_ALBrightnessStatistics on NAOqi 2.8: a hidden qi service in naoqi-service with the two methods
Autonomous Life calls, _start() and _stop(); the camera and the keys in its core
(specs/services/brightness-statistics.md). 2.8 only: a NAO 2.1 has no such module."""
import os
import sys

import qi

import naoqi_sim_brightness_statistics_core as core
import naoqi_sim_perception_stubs_core as ext

LOG = ext.JsonLog("/home/nao/brightness_statistics.jsonl", "naoqi_sim_brightness_statistics_qiservice")


@qi.multiThreaded()
class BrightnessStatisticsService(object):
    def version(self):
        # NAOqi's own answer, asked of a built-in: a qi service has no version() of its own
        return _session.service("ALMemory").version()

    def __init__(self, session):
        memory = session.service("ALMemory")
        self.core = core.BrightnessStatistics(lambda: session.service("ALVideoDevice"), memory.raiseEvent, log=LOG)

    def _start(self):
        self.core.start()

    def _stop(self):
        self.core.stop()


_url = "tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559")
_session = qi.Session()
_session.connect(_url)
_service = BrightnessStatisticsService(_session)
_sid = _session.registerService(core.NAME, _service)
LOG(method="registered", name=core.NAME, id=_sid)
sys.stderr.write("[naoqi_sim_brightness_statistics_qiservice] registered %s (id %s)\n" % (core.NAME, _sid))
