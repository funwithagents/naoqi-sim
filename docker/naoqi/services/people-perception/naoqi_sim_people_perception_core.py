# -*- coding: utf-8 -*-
"""The people perception core (Python 2.7, inside NAOqi; importable under Python 3 for the host's
fast tier): the ALPeoplePerception replacement, a population built from the faces the face
detector finds (specs/services/people-perception.md).

`Population` consumes the face detector's detections (naoqi_sim_face_detection_core.Detector):
each face is matched to a known person by angular distance or becomes a new one, its head is
placed at the distance the face's angular height gives, in the torso, robot and world frames
through the camera's transforms, and the people-perception contract is written to ALMemory, the
keys first, then the events the built-in awareness, tracker and user session react to.
"""
import math
import threading
import time

import naoqi_sim_perception_stubs_core as ext

NAME = "ALPeoplePerception"
PREFIX = "PeoplePerception/"
PERSON = PREFIX + "Person/"
HEAD_HEIGHT = 0.20  # m, the real height of what the detector boxes (brow to chin and a little more)
HEAD_TOP = 0.12  # m above the head's centre, for RealHeight
MATCH_DISTANCE = 0.35  # m: a face whose head is this close to a known person's last position is that person
# (in the world frame, so a head turning between two frames does not make a new person)
DEFAULT_PERIOD_MS = 200
FRAME_TORSO, FRAME_WORLD, FRAME_ROBOT = 0, 1, 2
EVENTS = [PREFIX + e for e in ("JustArrived", "JustLeft", "MaximumDetectionRangeUpdated", "NonVisiblePeopleList",
                                "PeopleDetected", "PeopleList", "PopulationReset", "PopulationUpdated",
                                "RemovedPersonFromMemory", "VisiblePeopleList")]
KEYS = [PREFIX + "PeopleList", PREFIX + "VisiblePeopleList", PREFIX + "NonVisiblePeopleList"]
PERSON_KEYS = ("PositionInTorsoFrame", "PositionInRobotFrame", "PositionInWorldFrame", "Distance", "AnglesYawPitch",
               "IsVisible", "IsFaceDetected", "NotSeenSince", "PresentSince", "RealHeight")
# The built-in's defaults, from the suite's peopleperception_sources.mds (NearPopulation_MaximumDetectionRange,
# Tracker_TimeBeforeVisiblePersonDisappears, Tracker_TimeBeforeNonVisiblePersonDisappears)
SETTINGS = {
    "MaximumDetectionRange": 3.5, "TimeBeforePersonDisappears": 10.0, "TimeBeforeVisiblePersonDisappears": 2.0,
    "FastModeEnabled": False, "GraphicalDisplayEnabled": False, "MovementDetectionEnabled": True,
    "FaceDetectionEnabled": True, "MinimumBodyHeight": 1.0, "MaximumBodyHeight": 2.0,
    "_DetectionMode": "", "_FaceRecognitionThreshold": 0.4, "_MaximumColorDistance": 0.0, "_TimeBeforeMTMPruning": 0.0,
}


def transform_point(matrix, point):
    """A 4x4 row-major transform (ALMotion.getTransform's 16 floats) applied to [x, y, z]."""
    x, y, z = point
    return [matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
            matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
            matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11]]


def head_in_camera_frame(alpha, beta, size_y):
    """The head's position in the camera's frame (x forward, y left, z up): at the distance the
    face's angular height gives, along the ray of its angles (NAOqi's: yaw left, pitch down)."""
    distance = HEAD_HEIGHT / (2.0 * math.tan(max(size_y, 1e-4) / 2.0))
    return [distance * math.cos(beta) * math.cos(alpha),
            distance * math.cos(beta) * math.sin(alpha),
            -distance * math.sin(beta)]


class Person(object):
    def __init__(self, pid, now):
        self.id = pid
        self.first_seen = now
        self.last_seen = now
        self.alpha = 0.0
        self.beta = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.distance = 0.0
        self.torso = [0.0, 0.0, 0.0]
        self.robot = [0.0, 0.0, 0.0]
        self.world = [0.0, 0.0, 0.0]
        self.visible = True


class Population(ext.Extractor):
    """ALPeoplePerception's logic: a consumer of the face detector's detections."""

    def __init__(self, detector, insert, remove, raise_event, signal=None, version="2.1", log=None, clock=None):
        ext.Extractor.__init__(self, NAME, EVENTS, KEYS, SETTINGS, DEFAULT_PERIOD_MS)
        self.detector = detector
        self.insert = insert
        self.remove = remove
        self.raise_event = raise_event
        self.signal = signal or (lambda name, *args: None)
        self.version = version
        self.log = log or (lambda **f: None)
        self.clock = clock
        self.people = {}  # id -> Person
        self.next_id = 1
        self.state_lock = threading.Lock()
        self.last_counts = None
        self.insert(PREFIX + "PeopleList", [])
        self.insert(PREFIX + "VisiblePeopleList", [])
        self.insert(PREFIX + "NonVisiblePeopleList", [])
        detector.add_consumer(self)

    def now(self):
        """The module's own clock, for the timers (a detection's stamp is NAOqi's, for the payloads)."""
        if self.clock is not None:
            return self.clock()
        return time.time()

    # -- the detector's consumer ------------------------------------------------
    def wants(self):
        if self.paused or not self.subscribers:
            return None
        return self.getCurrentPeriod()

    def subscriptions_changed(self):
        # The last subscriber gone, a NAO clears its population at once and raises PopulationReset
        # (bobby, Oct 29, 2026, twice, even with nobody in it; no JustLeft).
        had = getattr(self, "_had_subscribers", False)
        self._had_subscribers = bool(self.subscribers)
        if had and not self.subscribers:
            self.reset_population()
        self.detector.poke()

    def on_detection(self, detection):
        now = self.now()
        with self.state_lock:
            arrived = []
            seen = set()
            faces = detection.faces if self.get("FaceDetectionEnabled") else []
            for face in faces:
                head = head_in_camera_frame(face.alpha, face.beta, face.size_y)
                robot = transform_point(detection.transforms[FRAME_ROBOT], head)
                # from the camera, as a NAO measures it (bobby, Oct 29, 2026: Distance is the
                # camera-to-head distance; AnglesYawPitch the head's angles from the camera's axis)
                distance = math.sqrt(head[0] ** 2 + head[1] ** 2 + head[2] ** 2)
                if distance > self.get("MaximumDetectionRange"):
                    continue
                world = transform_point(detection.transforms[FRAME_WORLD], head)
                person = self._match(world, seen)
                if person is None:
                    person = Person(self.next_id, now)
                    self.next_id += 1
                    self.people[person.id] = person
                    arrived.append(person.id)
                seen.add(person.id)
                person.last_seen = now
                person.visible = True
                person.alpha, person.beta = face.alpha, face.beta
                person.distance = distance
                person.torso = transform_point(detection.transforms[FRAME_TORSO], head)
                person.robot = robot
                person.world = world
                person.yaw, person.pitch = face.alpha, face.beta
            left = self._age(now)
            self._write_keys(now)
            visible = [p.id for p in self._sorted() if p.visible]
        for pid in arrived:
            self.raise_event(PREFIX + "JustArrived", pid)
            self.signal("justArrived", pid)
        for pid in left:
            self.raise_event(PREFIX + "JustLeft", pid)
            self.signal("justLeft", pid)
        payload = [detection.stamp, [[p.id, p.distance, p.pitch, p.yaw] for p in self._sorted() if p.visible],
                   detection.pose_torso, detection.pose_robot, detection.camera]
        self.raise_event(PREFIX + "PopulationUpdated", payload)
        self.raise_event(PREFIX + "PeopleDetected", payload)
        counts = (len(visible), len(self.people))
        if counts != self.last_counts:
            self.last_counts = counts
            self.log(method="population", visible=visible, people=sorted(self.people))

    def on_idle(self):
        """Paused, no detection comes but the timers still run: a person turns invisible, then
        leaves, as when the camera stops seeing them (what a paused NAO does is not measured).
        Writes and raises only when something changed. With nobody subscribed the population was
        cleared when the last subscriber left (subscriptions_changed): nothing is left to age."""
        now = self.now()
        with self.state_lock:
            visible_before = set(p.id for p in self.people.values() if p.visible)
            left = self._age(now)
            visible_after = set(p.id for p in self.people.values() if p.visible)
            changed = bool(left) or visible_before != visible_after
            if changed:
                self._write_keys(now)
        if not changed:
            return
        for pid in left:
            self.raise_event(PREFIX + "JustLeft", pid)
            self.signal("justLeft", pid)
        stamp = [int(now), int((now % 1) * 1e6)]
        people = [[p.id, p.distance, p.pitch, p.yaw] for p in self._sorted() if p.visible]  # camera-relative
        self.raise_event(PREFIX + "PopulationUpdated", [stamp, people, [0.0] * 6, [0.0] * 6, 0])
        self.log(method="population", visible=sorted(visible_after), people=sorted(self.people), idle=True)

    def _match(self, world, taken):
        best, best_d = None, MATCH_DISTANCE
        for person in self.people.values():
            if person.id in taken:
                continue
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(person.world, world)))
            if d < best_d:
                best, best_d = person, d
        return best

    def _age(self, now):
        """Visibility and disappearance from the time since each person was seen; the ids that left."""
        left = []
        for pid, person in list(self.people.items()):
            unseen = now - person.last_seen
            if unseen > self.get("TimeBeforePersonDisappears"):
                del self.people[pid]
                self._remove_person(pid)
                left.append(pid)
            elif unseen > self.get("TimeBeforeVisiblePersonDisappears"):
                person.visible = False
        return left

    def _sorted(self):
        return [self.people[k] for k in sorted(self.people)]

    def _write_keys(self, now):
        people = self._sorted()
        for p in people:
            prefix = PERSON + "%d/" % p.id
            self.insert(prefix + "PositionInTorsoFrame", list(p.torso))
            self.insert(prefix + "PositionInRobotFrame", list(p.robot))
            self.insert(prefix + "PositionInWorldFrame", list(p.world))
            self.insert(prefix + "Distance", p.distance)
            self.insert(prefix + "AnglesYawPitch", [p.yaw, p.pitch])
            self.insert(prefix + "IsVisible", p.visible)
            self.insert(prefix + "IsFaceDetected", p.visible)
            self.insert(prefix + "NotSeenSince", 0.0 if p.visible else now - p.last_seen)
            self.insert(prefix + "PresentSince", now - p.first_seen)
            self.insert(prefix + "RealHeight", p.robot[2] + HEAD_TOP)
        self.insert(PREFIX + "PeopleList", [p.id for p in people])
        self.insert(PREFIX + "VisiblePeopleList", [p.id for p in people if p.visible])
        self.insert(PREFIX + "NonVisiblePeopleList", [p.id for p in people if not p.visible])

    def _remove_person(self, pid):
        for key in PERSON_KEYS:
            try:
                self.remove(PERSON + "%d/%s" % (pid, key))
            except Exception:  # noqa: BLE001  a key already gone
                pass

    # -- the module's own methods -----------------------------------------------------
    def reset_population(self):
        with self.state_lock:
            ids = sorted(self.people)
            for pid in ids:
                del self.people[pid]
                self._remove_person(pid)
            self._write_keys(self.now())
        self.raise_event(PREFIX + "PopulationReset", None)
        self.signal("populationReset")
        self.log(method="resetPopulation", removed=ids)

    def set_maximum_detection_range(self, value):
        self.set("MaximumDetectionRange", float(value))
        self.raise_event(PREFIX + "MaximumDetectionRangeUpdated", float(value))
        self.signal("maximumDetectionRangeChanged", float(value))

    def whoami(self):
        return "naoqi-sim ALPeoplePerception (%s)" % self.version


def _pair(key, cast=float):
    return [("get" + key, 0, {}, ext.getter(key)), ("set" + key, 1, {}, lambda s, v: s.set(key, cast(v)))]


def _flag(key):
    return [("is" + key, 0, {}, ext.getter(key)), ("set" + key, 1, {}, lambda s, v: s.set(key, bool(v)))]


METHODS = ext.GENERICS + [
    ("getMaximumDetectionRange", 0, {}, ext.getter("MaximumDetectionRange")),
    ("setMaximumDetectionRange", 1, {}, lambda s, v: s.set_maximum_detection_range(v)),
] + _pair("TimeBeforePersonDisappears") + _pair("TimeBeforeVisiblePersonDisappears") + _flag("FastModeEnabled") + _flag(
    "GraphicalDisplayEnabled") + _flag("MovementDetectionEnabled") + _flag("FaceDetectionEnabled") + _pair(
    "MinimumBodyHeight") + _pair("MaximumBodyHeight") + [
    ("resetPopulation", 0, {}, lambda s: s.reset_population()),
    ("_getDetectionMode", 0, {}, ext.getter("_DetectionMode")),
    ("_setDetectionMode", 1, {}, ext.setter("_DetectionMode")),
    ("_getFaceRecognitionThreshold", 0, {}, ext.getter("_FaceRecognitionThreshold")),
    ("_setFaceRecognitionThreshold", 1, {}, ext.setter("_FaceRecognitionThreshold")),
    ("_getMaximumColorDistance", 0, {}, ext.getter("_MaximumColorDistance")),
    ("_setMaximumColorDistance", 1, {}, ext.setter("_MaximumColorDistance")),
    ("_getTimeBeforeMTMPruning", 0, {}, ext.getter("_TimeBeforeMTMPruning")),
    ("_setTimeBeforeMTMPruning", 1, {}, ext.setter("_TimeBeforeMTMPruning")),
    ("_getLTMContent", 0, {}, ext.const([])),
    ("_matchInDatabase", 1, {}, ext.const(-1)),
    ("_matchInDatabaseNoCreate", 1, {}, ext.const(-1)),
    ("_matchInLTM", 1, {}, ext.const(-1)),
    ("_storeInLTM", 1, {}, ext.const(True)),
    ("_removeFromLTM", 1, {}, ext.const(True)),
    ("_removeAllFromLTM", 0, {}, ext.const(True)),
    ("whoami", 0, {}, lambda s: s.whoami()),
]
