# -*- coding: utf-8 -*-
"""The engagement zones core (Python 2.7, inside NAOqi; importable under Python 3 for the host's
fast tier): the ALEngagementZones replacement, sorting the people of our population into a NAO's
three zones (specs/services/engagement-zones.md).

`Zones` is an extractor and a consumer of the people module's populations
(naoqi_sim_people_perception_core.Population.add_consumer): it gets each population after the
people module has written its keys and before it raises its events, writes each person's zone,
and raises the zone events and lists a NAO raises.
"""
import math
import threading

import naoqi_sim_perception_stubs_core as ext

NAME = "ALEngagementZones"
PREFIX = "EngagementZones/"
PERSON = "PeoplePerception/Person/"
DEFAULT_PERIOD_MS = 200
EVENTS = [PREFIX + e for e in (
    "FirstLimitDistanceUpdated", "LastMovementsInZone1", "LastMovementsInZone2", "LastMovementsInZone3",
    "LimitAngleUpdated", "MovementsInZonesUpdated", "PeopleInZone1", "PeopleInZone2", "PeopleInZone3",
    "PeopleInZonesUpdated", "PersonApproached", "PersonEnteredZone1", "PersonEnteredZone2",
    "PersonEnteredZone3", "PersonMovedAway", "SecondLimitDistanceUpdated")]
PEOPLE_LISTS = [PREFIX + "PeopleInZone%d" % z for z in (1, 2, 3)]
MOVEMENT_LISTS = [PREFIX + "LastMovementsInZone%d" % z for z in (1, 2, 3)]
KEYS = PEOPLE_LISTS + MOVEMENT_LISTS
SETTINGS = {"LimitAngle": 90.0, "FirstLimitDistance": 1.5, "SecondLimitDistance": 2.5}
SIGNALS = {"limitAngleChanged": "(f)", "firstLimitChanged": "(f)", "secondLimitChanged": "(f)"}

ANGLE_ERROR = "The limit angle must be between 0 and 180 degrees"
FIRST_ERROR = "The first distance must be positive and smaller than the second distance"
SECOND_ERROR = "The second distance must be positive and bigger than the first distance"


def zone_of(x, y, first, second, limit_angle):
    """The zone (1, 2 or 3) of a point of the robot frame, its height ignored: the planar
    distance against the two limits (both inclusive), and in front when |atan(y / x)| is strictly
    under the limit angle (degrees). That angle is to the x axis, so a point behind the robot
    counts as in front, as on a NAO."""
    d = math.hypot(x, y)
    if x == 0:
        angle = 0.0 if y == 0 else 90.0  # the origin is in front; a point exactly sideways is not
    else:
        angle = math.degrees(abs(math.atan(y / x)))
    front = angle < limit_angle
    if d <= first:
        return 1 if front else 2
    if d <= second:
        return 2 if front else 3
    return 3


def rotation(wx, wy, wz):
    """The 3x3 rotation of a NAOqi Position6D's angles: Rz(wz) Ry(wy) Rx(wx)."""
    cx, sx = math.cos(wx), math.sin(wx)
    cy, sy = math.cos(wy), math.sin(wy)
    cz, sz = math.cos(wz), math.sin(wz)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def point_from_camera(x_angle, y_angle, distance, camera):
    """The point at `distance` along the ray of two image angles (NAOqi's: x to the left, y down),
    from the camera's Position6D in the robot frame, as the people module places a head."""
    ray = [distance * math.cos(y_angle) * math.cos(x_angle),
           distance * math.cos(y_angle) * math.sin(x_angle),
           -distance * math.sin(y_angle)]
    r = rotation(camera[3], camera[4], camera[5])
    return [camera[i] + sum(r[i][j] * ray[j] for j in range(3)) for i in range(3)]


class Zones(ext.Extractor):
    """ALEngagementZones' logic: the rule, the settings, and the zones of the population."""

    def __init__(self, people, insert, remove, raise_event, signal=None, version="2.1", log=None):
        ext.Extractor.__init__(self, NAME, EVENTS, KEYS, SETTINGS, DEFAULT_PERIOD_MS)
        self.people = people
        self.insert = insert
        self.remove = remove
        self.raise_event = raise_event
        self.signal = signal or (lambda name, *args: None)
        self.version = version
        self.log = log or (lambda **f: None)
        self.zones = {}  # person id -> the zone last written
        self.fresh = True  # the next population is the first since the module started processing
        self.zones_lock = threading.Lock()
        for key in KEYS:
            self.insert(key, [])
        people.add_consumer(self)

    # -- the rule --------------------------------------------------------------------------
    def zone(self, x, y):
        return zone_of(x, y, self.get("FirstLimitDistance"), self.get("SecondLimitDistance"),
                       self.get("LimitAngle"))

    def compute(self, a0, a1, a2, a3=None):
        """computeEngagementZone(x, y, z), or (xAngle, yAngle, distance, cameraPositionRobot)."""
        if a3 is None:
            return self.zone(float(a0), float(a1))
        x, y, _ = point_from_camera(float(a0), float(a1), float(a2), [float(v) for v in a3])
        return self.zone(x, y)

    # -- the settings ----------------------------------------------------------------------
    def set_limit_angle(self, value):
        value = float(value)
        if not 0.0 <= value <= 180.0:
            raise RuntimeError(ANGLE_ERROR)
        self._changed("LimitAngle", value, "LimitAngleUpdated", "limitAngleChanged")

    def set_first_limit(self, value):
        value = float(value)
        if value < 0.0 or value >= self.get("SecondLimitDistance"):
            raise RuntimeError(FIRST_ERROR)
        self._changed("FirstLimitDistance", value, "FirstLimitDistanceUpdated", "firstLimitChanged")

    def set_second_limit(self, value):
        value = float(value)
        if value < 0.0 or value <= self.get("FirstLimitDistance"):
            raise RuntimeError(SECOND_ERROR)
        self._changed("SecondLimitDistance", value, "SecondLimitDistanceUpdated", "secondLimitChanged")

    def _changed(self, key, value, event, signal):
        self.set(key, value)
        self.raise_event(PREFIX + event, value)
        self.signal(signal, value)
        self.log(method="setting", key=key, value=value)

    # -- the extractor ---------------------------------------------------------------------
    def processing(self):
        return bool(self.subscribers) and not self.paused

    def is_processing(self):
        return self.processing() and self.people.isProcessing()

    def subscriptions_changed(self):
        # The last subscriber gone, the lists are emptied and both updated events raised.
        had = getattr(self, "_had_subscribers", False)
        self._had_subscribers = bool(self.subscribers)
        if had and not self.subscribers:
            with self.zones_lock:
                self.zones = {}
                self.fresh = True
            for key in KEYS:
                self.insert(key, [])
            self.raise_event(PREFIX + "PeopleInZonesUpdated", None)
            self.raise_event(PREFIX + "MovementsInZonesUpdated", None)
            self.log(method="stopped")

    # -- the people module's consumer -------------------------------------------------------
    def on_population(self, people):
        """Each person's zone, the events of the people who entered or changed zone, the lists
        when something changed, at the first population, and when the population empties."""
        if not self.processing():
            return
        events = []
        with self.zones_lock:
            current = {}
            for pid, position in people:
                zone = self.zone(position[0], position[1])
                current[pid] = zone
                self.insert(PERSON + "%d/EngagementZone" % pid, zone)
                before = self.zones.get(pid)
                if before is None:
                    events.append(("PersonEnteredZone%d" % zone, pid))
                elif before != zone:
                    events.append(("PersonApproached" if zone < before else "PersonMovedAway", pid))
                    events.append(("PersonEnteredZone%d" % zone, pid))
            emptied = bool(self.zones) and not current
            update = bool(events) or self.fresh or emptied
            self.zones = current
            self.fresh = False
            if update:
                for z, key in zip((1, 2, 3), PEOPLE_LISTS):
                    self.insert(key, sorted(pid for pid, zone in current.items() if zone == z))
        for name, pid in events:
            self.raise_event(PREFIX + name, pid)
        if update:
            self.raise_event(PREFIX + "PeopleInZonesUpdated", None)
            self.log(method="zones", zones=dict((str(k), v) for k, v in current.items()))

    def whoami(self):
        return "naoqi-sim ALEngagementZones (%s)" % self.version


METHODS = [m for m in ext.GENERICS if m[0] != "isProcessing"] + [
    ("isProcessing", 0, {}, lambda s: s.is_processing()),
    ("setLimitAngle", 1, {}, lambda s, v: s.set_limit_angle(v)),
    ("getLimitAngle", 0, {}, ext.getter("LimitAngle")),
    ("setFirstLimitDistance", 1, {}, lambda s, v: s.set_first_limit(v)),
    ("getFirstLimitDistance", 0, {}, ext.getter("FirstLimitDistance")),
    ("setSecondLimitDistance", 1, {}, lambda s, v: s.set_second_limit(v)),
    ("getSecondLimitDistance", 0, {}, ext.getter("SecondLimitDistance")),
    ("computeEngagementZone", 4, {3: "None"}, lambda s, a, b, c, d: s.compute(a, b, c, d)),
]
