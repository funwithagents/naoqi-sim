# -*- coding: utf-8 -*-
"""The launchpad's people keys (Python 2.7, inside NAOqi; importable under Python 3 for the host's
fast tier): what a robot's launchpad plugins write for Autonomous Life about the people around it
(specs/services/launchpad-people.md). The desktop suites start no such plugin, so naoqi-sim writes
the keys from a module of its own, hidden, with no method for clients.

`LaunchpadPeople` follows `AutonomousLife/State`. While Life runs (2.1: `solitary`; 2.8: `solitary`
and `interactive`) it subscribes to the people perception and the engagement zones, and raises the
keys from their events and lists; when Life stops it raises every key empty.
"""
import threading
import time

NAME = "_NaoqiSimLaunchpadPeople"
STATUS_KEY = "NaoqiSim/Life/LaunchpadPeople"
PERIOD_MS = 200  # as a robot's plugin subscribes
L = "Launchpad/"
NUM = [L + "NumPeopleZone%d" % z for z in (1, 2, 3)]
NO_PEOPLE = L + "NoPeopleInZones"
NOT_SEEN = L + "PeopleNotSeen"
DURATION = L + "DurationPeopleNotSeen"
ZONE = L + "ZoneOfTrackedHuman"
DISTANCE = L + "DistanceOfTrackedHuman"
LOOKING = L + "TrackedHumanIsLookingAtRobot"
SAME = L + "SameTrackedHuman"
PERSON = "PeoplePerception/Person/%d/"

# What it follows: Life's state, and the people, zones, awareness and gaze events.
LIFE_STATE = "AutonomousLife/State"
ZONES_UPDATED = "EngagementZones/PeopleInZonesUpdated"
POPULATION = "PeoplePerception/PopulationUpdated"
TRACKED = "ALBasicAwareness/HumanTracked"
LOST = "ALBasicAwareness/HumanLost"
ENTERED = ["EngagementZones/PersonEnteredZone%d" % z for z in (1, 2, 3)]
STARTS_LOOKING = "GazeAnalysis/PersonStartsLookingAtRobot"
STOPS_LOOKING = "GazeAnalysis/PersonStopsLookingAtRobot"
EVENTS = [LIFE_STATE, ZONES_UPDATED, POPULATION, TRACKED, LOST] + ENTERED + [STARTS_LOOKING, STOPS_LOOKING]


def keys(version):
    """The keys this version's launchpad writes, in the order they are raised at start."""
    if version == "2.1":
        return NUM + [NO_PEOPLE, NOT_SEEN, DURATION, ZONE, LOOKING, SAME]
    return NUM + [NO_PEOPLE, NOT_SEEN, ZONE, DISTANCE, LOOKING, SAME]


def status(version):
    """The status key's value: the keys naoqi-sim writes in the launchpad's place, so a client
    tells them from a robot's plugins (specs/container/status-service.md)."""
    return ",".join(keys(version))


def running_states(version):
    """2.1's plugin stops in interactive (measured on a real NAO 2.1); 2.8's Life reads the tracked
    human's zone while interactive to go back to solitary."""
    return ("solitary",) if version == "2.1" else ("solitary", "interactive")


class LaunchpadPeople(object):
    """The keys, from the events. `people` and `zones` are the two modules' extractor state
    (subscribe/unsubscribe), `get_data` and `raise_event` ALMemory's."""

    def __init__(self, people, zones, get_data, raise_event, version="2.1", clock=None, log=None):
        self.people = people
        self.zones = zones
        self.get_data = get_data
        self.raise_event = raise_event
        self.version = version
        self.clock = clock or time.time
        self.log = log or (lambda **f: None)
        self.running = False
        self.values = {}  # key -> the last value raised
        self.tracked = -1  # the human awareness tracks, followed even while stopped
        self.last_visible = None  # when somebody was last visible
        self.lock = threading.Lock()
        self.queue = []
        self.wake = threading.Condition(self.lock)
        self.worker = None

    # -- the events, in order, off the callers' threads ------------------------------------
    def post(self, name, value):
        """Called from an ALMemory callback: queued, handled by the worker in order."""
        with self.lock:
            self.queue.append((name, value))
            self.wake.notify()

    def start_worker(self):
        self.worker = threading.Thread(target=self._work, name=NAME)
        self.worker.daemon = True
        self.worker.start()

    def _work(self):
        while True:
            with self.lock:
                while not self.queue:
                    self.wake.wait()
                name, value = self.queue.pop(0)
            try:
                self.handle(name, value)
            except Exception as e:  # noqa: BLE001  one bad event never stops the keys
                self.log(method="event-failed", name=name, error=repr(e))

    # -- the handlers ------------------------------------------------------------------------
    def handle(self, name, value):
        if name == LIFE_STATE:
            self.on_life_state(value)
        elif name == TRACKED:
            self.on_tracked(value)
        elif not self.running:
            return
        elif name == ZONES_UPDATED:
            self.read_zones()
        elif name == POPULATION:
            self.read_population()
        elif name == LOST:
            self.raise_key(SAME, 0)
            self.raise_key(ZONE, 0)
        elif name in ENTERED and value == self.tracked:
            self.raise_key(ZONE, ENTERED.index(name) + 1)
        elif name in (STARTS_LOOKING, STOPS_LOOKING) and value == self.tracked:
            self.raise_key(LOOKING, 1 if name == STARTS_LOOKING else 0)

    def on_life_state(self, state):
        if state in running_states(self.version):
            if not self.running:
                self.start()
        elif self.running:
            self.stop()

    def on_tracked(self, pid):
        pid = int(pid) if pid is not None else -1
        changed = pid != self.tracked
        self.tracked = pid
        if not self.running:
            return
        if pid < 0:
            self.raise_key(SAME, 0)
            self.raise_key(ZONE, 0)
            self.raise_key(LOOKING, 0)
            return
        if changed:  # a condition timing "the same human for n seconds" starts again
            self.raise_key(SAME, 0, force=True)
        self.raise_key(SAME, 1, force=changed)
        self.raise_key(ZONE, self.person(pid, "EngagementZone", 0))
        self.raise_key(LOOKING, 1 if self.person(pid, "IsLookingAtRobot", False) else 0)
        if self.version != "2.1":
            self.raise_key(DISTANCE, self.person(pid, "Distance", 0.0))

    # -- start and stop ----------------------------------------------------------------------
    def start(self):
        self.running = True
        self.people.subscribe(NAME, PERIOD_MS, 0.0)
        self.zones.subscribe(NAME, PERIOD_MS, 0.0)
        self.values = {}  # every value raised at start, changed or not
        self.last_visible = None
        self.read_zones()
        self.read_population()
        tracked = self.tracked
        self.tracked = -2  # so the tracked human counts as new
        self.on_tracked(tracked)
        self.log(method="start", values=dict(self.values))

    def stop(self):
        self.running = False
        for extractor in (self.zones, self.people):
            try:
                extractor.unsubscribe(NAME)
            except Exception as e:  # noqa: BLE001
                self.log(method="unsubscribe-failed", error=repr(e))
        for key in keys(self.version):
            self.raise_event(key, -1 if key == DURATION else None)
        self.values = {}
        self.log(method="stop")

    # -- the values ----------------------------------------------------------------------------
    def read_zones(self):
        counts = [len(self.data("EngagementZones/PeopleInZone%d" % z, [])) for z in (1, 2, 3)]
        for key, count in zip(NUM, counts):
            self.raise_key(key, count)
        self.raise_key(NO_PEOPLE, sum(counts) == 0)

    def read_population(self):
        now = self.clock()
        visible = self.data("PeoplePerception/VisiblePeopleList", [])
        if visible or self.last_visible is None:
            self.last_visible = now
        self.raise_key(NOT_SEEN, not visible)
        if self.version == "2.1":
            self.raise_key(DURATION, 0 if visible else int(now - self.last_visible))
        elif self.tracked >= 0:
            self.raise_key(DISTANCE, self.person(self.tracked, "Distance", 0.0))

    def raise_key(self, key, value, force=False):
        if not force and key in self.values and self.values[key] == value:
            return
        self.values[key] = value
        self.raise_event(key, value)

    def data(self, key, default):
        try:
            value = self.get_data(key)
        except Exception:  # noqa: BLE001  a key nobody wrote yet
            return default
        return default if value is None else value

    def person(self, pid, key, default):
        return self.data(PERSON % pid + key, default)
