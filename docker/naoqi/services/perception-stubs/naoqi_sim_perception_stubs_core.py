# -*- coding: utf-8 -*-
"""The perception stubs' core, and the extractor machinery every perception module shares
(Python 2.7, inside NAOqi; importable under Python 3 so the host's fast tier tests it).

Replacing the built-in ALPeoplePerception leaves its library out of NAOqi's boot, and with it the
modules whose modularity processes chain to it; this module serves their names as API-only stubs
(specs/services/perception-stubs.md): the documented methods and events, the settings kept and
answered, the subscriptions listed, no detection, no event raised. It also holds what the face
and people modules build on: `Extractor`, the bookkeeping of a NAOqi extractor, and
`make_method`/`install`, which give a class the generated methods an ALModule needs (bound by
argspec, so with real argument lists) from a table of (name, arity, defaults, handler).
"""
import json
import sys
import threading
import time

DEFAULT_PERIOD_MS = 200  # a subscribe(name) with no period, for the stubs
UNSET = -1  # a period the subscriber did not give
UNSET_PRECISION = -1.0  # a precision the subscriber did not give


class Extractor(object):
    """A NAOqi extractor's bookkeeping: subscribers with their period and precision, pause,
    settings. The real modules subclass it; the stubs use it as it is."""

    def __init__(self, service, events=(), keys=(), settings=None, default_period=DEFAULT_PERIOD_MS, processes=True):
        self.service = service
        self.processes = processes  # False for a stub: it never processes, whoever subscribes
        self.events = list(events)
        self.keys = list(keys)
        self.settings = dict(settings or {})
        self.default_period = default_period
        self.subscribers = {}  # name -> [period ms, precision]
        self.paused = False
        self.log = None  # set by the shell: log(**fields)
        self.lock = threading.Lock()

    # -- the extractor generics ------------------------------------------------
    def subscribe(self, name, period=UNSET, precision=UNSET_PRECISION):
        if period is None or period == UNSET:
            period = self.default_period
        if precision is None or precision == UNSET_PRECISION:
            precision = 0.0
        with self.lock:
            self.subscribers[name] = [int(period), float(precision)]
        self.subscriptions_changed()

    def unsubscribe(self, name):
        with self.lock:
            self.subscribers.pop(name, None)
        self.subscriptions_changed()

    def updatePeriod(self, name, period):
        with self.lock:
            self.subscribers.setdefault(name, [self.default_period, 0.0])[0] = int(period)
        self.subscriptions_changed()

    def updatePrecision(self, name, precision):
        with self.lock:
            self.subscribers.setdefault(name, [self.default_period, 0.0])[1] = float(precision)

    def getCurrentPeriod(self):
        with self.lock:
            periods = [p for p, _ in self.subscribers.values() if p > 0]
        return min(periods) if periods else -1

    def getCurrentPrecision(self):
        with self.lock:
            precisions = [pr for _, pr in self.subscribers.values()]
        return max(precisions) if precisions else -1.0

    def getMyPeriod(self, name):
        return self.subscribers.get(name, [-1, -1.0])[0]

    def getMyPrecision(self, name):
        return self.subscribers.get(name, [-1, -1.0])[1]

    def getSubscribersInfo(self):
        with self.lock:
            return [[n, p, pr] for n, (p, pr) in sorted(self.subscribers.items())]

    def getOutputNames(self):
        return list(self.events)

    def getEventList(self):
        return list(self.events)

    def getMemoryKeyList(self):
        return list(self.keys)

    def isPaused(self):
        return self.paused

    def isProcessing(self):
        return self.processes and bool(self.subscribers) and not self.paused

    def pause(self, paused):
        self.paused = bool(paused)
        self.subscriptions_changed()

    def subscriptions_changed(self):
        """Hook for the real modules (the detector's schedule follows the subscribers)."""

    # -- settings ----------------------------------------------------------------
    def get(self, key):
        return self.settings[key]

    def set(self, key, value):
        self.settings[key] = value


# The handlers call the base implementations: a shell's generated method of the same name sits
# on the subclass, so `s.subscribe(...)` would call the generated method again.
GENERICS = [
    ("subscribe", 3, {1: str(UNSET), 2: str(UNSET_PRECISION)}, lambda s, n, p, pr: Extractor.subscribe(s, n, p, pr)),
    ("unsubscribe", 1, {}, lambda s, n: Extractor.unsubscribe(s, n)),
    ("updatePeriod", 2, {}, lambda s, n, p: Extractor.updatePeriod(s, n, p)),
    ("updatePrecision", 2, {}, lambda s, n, p: Extractor.updatePrecision(s, n, p)),
    ("getCurrentPeriod", 0, {}, lambda s: Extractor.getCurrentPeriod(s)),
    ("getCurrentPrecision", 0, {}, lambda s: Extractor.getCurrentPrecision(s)),
    ("getMyPeriod", 1, {}, lambda s, n: Extractor.getMyPeriod(s, n)),
    ("getMyPrecision", 1, {}, lambda s, n: Extractor.getMyPrecision(s, n)),
    ("getSubscribersInfo", 0, {}, lambda s: Extractor.getSubscribersInfo(s)),
    ("getOutputNames", 0, {}, lambda s: Extractor.getOutputNames(s)),
    ("getEventList", 0, {}, lambda s: Extractor.getEventList(s)),
    ("getMemoryKeyList", 0, {}, lambda s: Extractor.getMemoryKeyList(s)),
    ("isPaused", 0, {}, lambda s: Extractor.isPaused(s)),
    ("isProcessing", 0, {}, lambda s: Extractor.isProcessing(s)),
    ("pause", 1, {}, lambda s, b: Extractor.pause(s, b)),
]


def getter(key):
    return lambda s: s.get(key)


def setter(key):
    return lambda s, v: s.set(key, v)


def const(value):
    return lambda s, *a: value


# --- generated methods --------------------------------------------------------------------

def make_method(name, arity, defaults, varargs=False):
    """A method `name(self, a0, a1...)` with real arguments (an ALModule binds by argspec, and the
    defaults make the shorter overload work through BIND_PYTHON) calling self._call(name, [args]).
    With varargs (a 2.8 qi service registers one signature per name, so its overloads are one
    varargs method) `name(self, *args)`, the missing arguments completed with the defaults.
    Python 2.7: no generator expression with a free variable next to the exec."""
    doc = "naoqi-sim: " + name
    if varargs and defaults:
        tail = "[" + ", ".join([defaults[i] for i in sorted(defaults)]) + "]"
        src = "def %s(self, *args):\n    %r\n    return self._call(%r, list(args) + %s[len(args) - %d:])\n" % (
            name, doc, name, tail, arity - len(defaults))
    else:
        params = []
        for i in range(arity):
            p = "a%d" % i
            if i in defaults:
                p += "=" + defaults[i]
            params.append(p)
        src = "def %s(self%s):\n    %r\n    return self._call(%r, [%s])\n" % (
            name, (", " + ", ".join(params)) if params else "", doc, name,
            ", ".join(["a%d" % i for i in range(arity)]))
    ns = {}
    exec(src, ns)
    return ns[name]


def install(cls, methods, varargs=False):
    """Adds every method of the table to cls (which must define `_call(name, args)`) and records
    the handlers in cls.HANDLERS. A shell's `_call` is `call(...)` below."""
    cls.HANDLERS = {}
    for name, arity, defaults, handler in methods:
        setattr(cls, name, make_method(name, arity, defaults, varargs))
        cls.HANDLERS[name] = handler


def overloads(methods):
    """The (name, shorter arity) pairs an ALModule binds explicitly with BIND_PYTHON: the shortest
    overload of each method with defaults (NAOqi's extractors have two forms of subscribe)."""
    pairs = []
    for name, arity, defaults, _ in methods:
        if defaults:
            pairs.append((name, min(defaults)))
    return pairs


def call(state, handlers, name, args, log=None):
    """Runs a method's handler on the state and logs the call (the result, or the error)."""
    try:
        result = handlers[name](state, *args)
    except Exception as e:
        if log is not None:
            log(service=state.service, method=name, args=args, error=repr(e))
        raise
    if log is not None:
        log(service=state.service, method=name, args=args, result=result)
    return result


class JsonLog(object):
    """JSON lines to a file, with the time since the module loaded; stderr when the file cannot
    be written (a host test)."""

    def __init__(self, path, tag):
        self.path = path
        self.tag = tag
        self.t0 = time.time()
        self.lock = threading.Lock()

    def __call__(self, **fields):
        fields["t"] = round(time.time() - self.t0, 3)
        line = json.dumps(fields, default=repr)
        with self.lock:
            try:
                with open(self.path, "a") as fh:
                    fh.write(line + "\n")
            except IOError:
                sys.stderr.write("[%s] %s\n" % (self.tag, line))


# --- the stubs' tables -------------------------------------------------------------------

ENGAGEMENT_EVENTS = ["EngagementZones/" + e for e in (
    "FirstLimitDistanceUpdated", "LastMovementsInZone1", "LastMovementsInZone2", "LastMovementsInZone3",
    "LimitAngleUpdated", "MovementsInZonesUpdated", "PeopleInZone1", "PeopleInZone2", "PeopleInZone3",
    "PeopleInZonesUpdated", "PersonApproached", "PersonEnteredZone1", "PersonEnteredZone2",
    "PersonEnteredZone3", "PersonMovedAway", "SecondLimitDistanceUpdated")]
ENGAGEMENT_KEYS = ["EngagementZones/" + k for k in (
    "PeopleInZone1", "PeopleInZone2", "PeopleInZone3", "LastMovementsInZone1", "LastMovementsInZone2",
    "LastMovementsInZone3")]
ENGAGEMENT_SETTINGS = {"LimitAngle": 90.0, "FirstLimitDistance": 1.5, "SecondLimitDistance": 2.5}
ENGAGEMENT_METHODS = GENERICS + [
    ("setLimitAngle", 1, {}, setter("LimitAngle")), ("getLimitAngle", 0, {}, getter("LimitAngle")),
    ("setFirstLimitDistance", 1, {}, setter("FirstLimitDistance")),
    ("getFirstLimitDistance", 0, {}, getter("FirstLimitDistance")),
    ("setSecondLimitDistance", 1, {}, setter("SecondLimitDistance")),
    ("getSecondLimitDistance", 0, {}, getter("SecondLimitDistance")),
    ("computeEngagementZone", 4, {3: "None"}, const(0)),
]
GAZE_EVENTS = ["GazeAnalysis/PeopleLookingAtRobot", "GazeAnalysis/PersonStartsLookingAtRobot",
               "GazeAnalysis/PersonStopsLookingAtRobot"]
GAZE_SETTINGS = {"FaceAnalysisEnabled": False, "Tolerance": 0.2}
GAZE_METHODS = GENERICS + [
    ("setFaceAnalysisEnabled", 1, {}, setter("FaceAnalysisEnabled")),
    ("isFaceAnalysisEnabled", 0, {}, getter("FaceAnalysisEnabled")),
    ("setTolerance", 1, {}, setter("Tolerance")), ("getTolerance", 0, {}, getter("Tolerance")),
]
SITTING_EVENTS = ["SittingPeopleDetection/PersonSittingDown", "SittingPeopleDetection/PersonStandingUp"]
SITTING_SETTINGS = {"SittingThreshold": 1.0}
SITTING_METHODS = GENERICS + [
    ("setSittingThreshold", 1, {}, setter("SittingThreshold")),
    ("getSittingThreshold", 0, {}, getter("SittingThreshold")),
]
WAVING_EVENTS = ["WavingDetection/PersonWaving", "WavingDetection/PersonWavingCenter",
                 "WavingDetection/PersonWavingLeft", "WavingDetection/PersonWavingRight"]
WAVING_SETTINGS = {"MaxDistance": 3.0, "MinSize": 0.1}
WAVING_METHODS = GENERICS + [
    ("setMaxDistance", 1, {}, setter("MaxDistance")), ("getMaxDistance", 0, {}, getter("MaxDistance")),
    ("setMinSize", 1, {}, setter("MinSize")), ("getMinSize", 0, {}, getter("MinSize")),
]
TRACKING_SETTINGS = {"TrackingDistance": 1.0, "VerticalOffset": 0.0, "_DetectionMode": "",
                     "TrackingPosition": [0.0, 0.0, 0.0], "active": False}
_TRACKING = [
    ("setTrackingDistance", 1, {}, setter("TrackingDistance")),
    ("getTrackingDistance", 0, {}, getter("TrackingDistance")),
    ("setVerticalOffset", 1, {}, setter("VerticalOffset")), ("getVerticalOffset", 0, {}, getter("VerticalOffset")),
    ("setTrackingPosition", 3, {}, lambda s, x, y, z: s.set("TrackingPosition", [x, y, z])),
    ("getTrackingPosition", 0, {}, getter("TrackingPosition")),
    ("getDefaultPeriod", 0, {}, const(200)),
    ("_getDetectionMode", 0, {}, getter("_DetectionMode")), ("_setDetectionMode", 1, {}, setter("_DetectionMode")),
]
FASTPERSON_METHODS = GENERICS + _TRACKING + [
    ("startTracking", 1, {0: "None"}, lambda s, p: s.set("active", True)),
    ("stopTracking", 0, {}, lambda s: s.set("active", False)),
    ("isTracking", 0, {}, getter("active")),
]
FINDHEAD_METHODS = GENERICS + _TRACKING + [
    ("startSearching", 1, {0: "None"}, lambda s, p: s.set("active", True)),
    ("stopSearching", 0, {}, lambda s: s.set("active", False)),
    ("isSearching", 0, {}, getter("active")),
    ("startSearch", 0, {}, lambda s: s.set("active", True)),
    ("stopSearch", 0, {}, lambda s: s.set("active", False)),
]


class Stub(object):
    """One stub's description: its name per version (None where the version does not serve it),
    its table, events, keys, settings and 2.8 signals {name: qi signature}."""

    def __init__(self, name21, name28, methods, events=(), keys=(), settings=None, signals=None):
        self.name21 = name21
        self.name28 = name28
        self.methods = methods
        self.events = list(events)
        self.keys = list(keys)
        self.settings = dict(settings or {})
        self.signals = dict(signals or {})

    def name(self, version):
        return self.name21 if version == "2.1" else self.name28


STUBS = [
    Stub("ALEngagementZones", "ALEngagementZones", ENGAGEMENT_METHODS, ENGAGEMENT_EVENTS, ENGAGEMENT_KEYS,
         ENGAGEMENT_SETTINGS, {"limitAngleChanged": "(f)", "firstLimitChanged": "(f)", "secondLimitChanged": "(f)"}),
    Stub("ALGazeAnalysis", "ALGazeAnalysis", GAZE_METHODS, GAZE_EVENTS, [], GAZE_SETTINGS),
    Stub("ALSittingPeopleDetection", "ALSittingPeopleDetection", SITTING_METHODS, SITTING_EVENTS, [], SITTING_SETTINGS),
    # a real NAO 2.1 has no waving detection: dropped there with the library
    Stub(None, "ALWavingDetection", WAVING_METHODS, WAVING_EVENTS, [], WAVING_SETTINGS),
    # The fast person tracking and find person head libraries are not stubbed: they load on their
    # own on 2.1, and on 2.8 once the shared sources are loaded (naoqi_sim_perception_sources.cpp),
    # since ALBasicAwareness needs their modularity processes to track. Their tables stay for a
    # version that would need them.
]


def stubs(version):
    """The stubs this version serves, in load order."""
    return [s for s in STUBS if s.name(version) is not None]


def stub_names(version):
    return [s.name(version) for s in stubs(version)]


# --- _UserIdentification (2.8) ------------------------------------------------------------------

IDENT_NAME = "_UserIdentification"
IDENT_PROPERTIES = {  # name: (qi signature, default)
    "faceRecognitionThreshold": ("f", 0.5), "maxRetryRecognition": ("i", 3), "retryRecognitionDelay": ("L", 1000),
    "enableImageFiltering": ("b", True), "maximumHeadYawDegree": ("f", 30.0), "maximumHeadPitchDegree": ("f", 30.0),
    "maximumHeadRollDegree": ("f", 30.0), "filterNonFrontalFaces": ("b", True), "minimumHeadSizePixel": ("i", 40),
    "minimumFacialPartsAvgConfidence": ("f", 0.5), "filterCameraMovements": ("b", True),
}
# the manager converts match's reply to this struct (status, matches), a match being (uid, confidence, storage)
RECOGNITION_RESULT = "(i[(Lfi)<RecognitionMatch,value,confidence,storage>])<RecognitionResult,status,matches>"
STATUS_OK = 1
STORE_OK = 0  # store's reply: a status, 0 for success (an id there made the manager store the person again)
STORAGE_TEMPORARY = 0
STORAGE_PERMANENT = 1


class UserStore(object):
    """The face-recognition user database behind ALUserSession, in memory: which user a tracked
    person (a people-perception id) was stored as. `match` never recognizes a face: a person
    never stored is unknown (status OK, no match), so the session manager stores a new user and
    opens a session; a person stored keeps their user."""

    def __init__(self):
        self.service = IDENT_NAME
        self.users = {}  # ppid -> uid
        self.permanent = set()
        self.lock = threading.Lock()

    def match(self, ppid):
        with self.lock:
            uid = self.users.get(ppid)
            if uid is None:
                return (STATUS_OK, [])
            storage = STORAGE_PERMANENT if uid in self.permanent else STORAGE_TEMPORARY
            return (STATUS_OK, [(uid, 1.0, storage)])

    def store(self, ppid, uid):
        with self.lock:
            self.users[ppid] = uid
        return STORE_OK

    def remove(self, uid):
        with self.lock:
            before = len(self.users)
            self.users = dict([(p, u) for p, u in self.users.items() if u != uid])
            self.permanent.discard(uid)
            return len(self.users) != before

    def clear(self):
        with self.lock:
            self.users.clear()
            self.permanent.clear()
        return True

    def makePermanent(self, uid):
        with self.lock:
            if uid not in self.users.values():
                return False
            self.permanent.add(uid)
            return True

    def makeTemporary(self, uid):
        with self.lock:
            if uid not in self.users.values():
                return False
            self.permanent.discard(uid)
            return True

    def isPermanent(self, uid):
        return uid in self.permanent

    def isTemporary(self, uid):
        return uid in self.users.values() and uid not in self.permanent

    def getStoredUsers(self):
        with self.lock:
            return sorted(set(self.users.values()))

    def checkPhotoForIdentification(self, path):
        return 0


IDENT_METHODS = [  # match is declared by the 2.8 shell itself, with its struct
    ("store", 2, {}, lambda s, ppid, uid: UserStore.store(s, ppid, uid)),
    ("remove", 1, {}, lambda s, uid: UserStore.remove(s, uid)),
    ("clear", 0, {}, lambda s: UserStore.clear(s)),
    ("makePermanent", 1, {}, lambda s, uid: UserStore.makePermanent(s, uid)),
    ("makeTemporary", 1, {}, lambda s, uid: UserStore.makeTemporary(s, uid)),
    ("isPermanent", 1, {}, lambda s, uid: UserStore.isPermanent(s, uid)),
    ("isTemporary", 1, {}, lambda s, uid: UserStore.isTemporary(s, uid)),
    ("getStoredUsers", 0, {}, lambda s: UserStore.getStoredUsers(s)),
    ("checkPhotoForIdentification", 1, {}, lambda s, p: UserStore.checkPhotoForIdentification(s, p)),
]

STUBS_KEY = "NaoqiSim/Perception/Stubs"


def write_stubs_key(insert, version):
    """The NaoqiSim status key listing the stubs loaded, so a client tells a stub from a module
    that detects (specs/container/status-service.md)."""
    names = stub_names(version)
    if version != "2.1":
        names = names + [IDENT_NAME]
    insert(STUBS_KEY, ",".join(names))
    return names
