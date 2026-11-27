# -*- coding: utf-8 -*-
"""Autonomous Life off at boot, on NAOqi 2.8: a NAO's Life-at-boot switch is a preference, which
Life reads when it starts. This module is loaded before the package services start, and sets the
switch off, so the sim boots with Life `disabled`, as a NAO whose user turned the switch off; a
client switches Life on with `ALAutonomousLife.setState` (specs/container/autonomous-life.md,
"The sim boots with Life off, at rest")."""
import os
import sys

import qi

DOMAIN, SETTING = "com.aldebaran.debug", "DisableLifeAndDialog"

_session = qi.Session()
_session.connect("tcp://127.0.0.1:%s" % os.environ.get("NAOQI_SIM_INTERNAL_PORT", "9559"))
_session.service("ALPreferenceManager").setValue(DOMAIN, SETTING, "1")
sys.stderr.write("[naoqi_sim_life_qiservice] %s / %s set to 1: Autonomous Life stays disabled at boot\n" % (DOMAIN, SETTING))
