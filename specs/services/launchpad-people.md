---
code:
  - docker/naoqi/services/launchpad-people/naoqi_sim_launchpad_people_core.py
  - docker/naoqi/services/launchpad-people/naoqi_sim_launchpad_people_almodule.py
  - docker/naoqi/services/launchpad-people/naoqi_sim_launchpad_people_qiservice.py
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_launchpad_people_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_life_live.py
---

# Launchpad people keys

**Status:** Implemented

Decided Nov 25, 2026, after finding why the desktop launchpad writes no people key (trail in `spike/RESULTS.md`, "Launchpad plugins: why none starts on the sims"). What a NAO 2.1 writes was measured on a real one on Nov 21, 2026. Plan: [202611252200_engagement-zones-and-launchpad-people.md](../../plans/202611252200_engagement-zones-and-launchpad-people.md). Reviewed by the user Nov 25, 2026; built Nov 25, 2026.

## Purpose

Autonomous Life decides when to talk to somebody from a few ALMemory keys under `Launchpad/`: how many people stand in each engagement zone, and the zone of the person the robot is tracking. On a robot, launchpad plugins inside Life write them. The conditions that read them:

- **2.1**: the launch condition of the activity that runs the main dialog, `('Launchpad/ZoneOfTrackedHuman' == 1) && ('UserSession/FocusedUser' >= 0)`, and any activity's own condition.
- **2.8**: Life's rules for a NAO ([autonomous-life.md](../container/autonomous-life.md)): into `interactive` when `'Launchpad/NumPeopleZone1' > 0` for 0.25 s, back to `solitary` when the tracked human is gone, or `'Launchpad/ZoneOfTrackedHuman' > 2`, for 20 s.

**The desktop suites do not run these plugins**, and we found no setting that starts them: the 2.1 suite's launchpad starts none of a robot's seven, the 2.8 suite's starts six of a NAO 6's eight, without the two that watch people. So on the sims nobody writes the people keys, and Life never goes to a person by itself. naoqi-sim writes them from a module of its own.

## Decided

### The keys

Each is raised as an event, so its last value is also readable, as a robot's are.

| Key | Value | 2.1 | 2.8 |
|---|---|---|---|
| `Launchpad/NumPeopleZone1`, `2`, `3` | The number of people in each engagement zone | yes | yes |
| `Launchpad/NoPeopleInZones` | True when the three are 0 | yes | yes |
| `Launchpad/PeopleNotSeen` | True when `PeoplePerception/VisiblePeopleList` is empty | yes | yes |
| `Launchpad/DurationPeopleNotSeen` | Whole seconds since somebody was last visible (0 while somebody is), raised when the number changes; -1 when the module is not running | yes | no |
| `Launchpad/ZoneOfTrackedHuman` | The engagement zone of the person basic awareness tracks; 0 with nobody tracked | yes | yes |
| `Launchpad/DistanceOfTrackedHuman` | That person's `Distance`; unmeasured on a robot | no | yes |
| `Launchpad/TrackedHumanIsLookingAtRobot` | 0: the gaze analysis is a stub ([perception-stubs.md](perception-stubs.md)) | yes | yes |
| `Launchpad/SameTrackedHuman` | 1 while a human is tracked, 0 with nobody; raised 0 then 1 when the tracked human changes, so a condition timing "the same human for n seconds" starts again | yes | yes |

- The movement keys (`NumMotionZone1..3`, `NoMotionInZones`) and `WavingDetection` are not written: a real NAO 2.1 leaves them unset in a still room, and naoqi-sim detects no movement.
- With nobody in view a NAO 2.1 in `solitary` shows `NumPeopleZone1..3` 0, `NoPeopleInZones` true, `PeopleNotSeen` true, `DurationPeopleNotSeen` counting, `ZoneOfTrackedHuman` 0, `TrackedHumanIsLookingAtRobot` 0, `SameTrackedHuman` 0 (measured). The module writes these when it starts.

### When it runs

- **It follows `AutonomousLife/State`.**
  - **2.1**: it runs in `solitary` only. A NAO stops its people plugin when Life enters `interactive` and the keys go back to unset, `DurationPeopleNotSeen` to -1 (measured): they are what gets Life into `interactive`, not what keeps it there.
  - **2.8**: it runs in `solitary` and `interactive`, since the rule back to `solitary` reads `ZoneOfTrackedHuman` while `interactive`. Which of a NAO 6's two plugins runs in which state is not measured.
- When it stops (Life `disabled`, `safeguard`, or `interactive` on 2.1) it raises every key with an empty value, and `DurationPeopleNotSeen` with -1.
- **While it runs it subscribes to `ALPeoplePerception` and `ALEngagementZones` at 200 ms**, as a robot's plugin does ([naoqi-fidelity.md](../container/naoqi-fidelity.md), "Measured against a real NAO 2.1"), so the zones are computed without any client subscribing.

### Where the values come from

The module follows the events and keys the people perception, the engagement zones and basic awareness publish:

| On | It does |
|---|---|
| Its start | Everything below once, from the current keys, each value raised whether it changed or not; the tracked human from the last `ALBasicAwareness/HumanTracked` |
| `EngagementZones/PeopleInZonesUpdated` | Reads the three lists `EngagementZones/PeopleInZone1..3` ([engagement-zones.md](engagement-zones.md)); raises each `NumPeopleZoneN` whose length changed, and `NoPeopleInZones` when it changed. The event's value is not used |
| `PeoplePerception/PopulationUpdated` | Reads `PeoplePerception/VisiblePeopleList`; raises `PeopleNotSeen` when it changed, and `DurationPeopleNotSeen` when its number of seconds changed. On 2.8, `DistanceOfTrackedHuman` from the tracked person's `Distance` |
| `ALBasicAwareness/HumanTracked` with an id | A human other than the last one: `SameTrackedHuman` 0 then 1. Then `ZoneOfTrackedHuman` from `PeoplePerception/Person/<id>/EngagementZone` and `TrackedHumanIsLookingAtRobot` from `.../IsLookingAtRobot` (0 when the key is missing) |
| `ALBasicAwareness/HumanTracked` with -1 | `SameTrackedHuman` 0, `ZoneOfTrackedHuman` 0, `TrackedHumanIsLookingAtRobot` 0 |
| `ALBasicAwareness/HumanLost` | `SameTrackedHuman` 0, `ZoneOfTrackedHuman` 0 |
| `EngagementZones/PersonEnteredZone1`, `2`, `3` with the tracked human's id | `ZoneOfTrackedHuman` 1, 2 or 3 |
| `GazeAnalysis/PersonStartsLookingAtRobot`, `PersonStopsLookingAtRobot` with the tracked human's id | `TrackedHumanIsLookingAtRobot` 1 or 0 (never raised today: the gaze analysis is a stub) |

So the zone counts follow the zones module's lists, with their rule: a person who disappears while others stay is counted until somebody changes zone or the population empties.

### What it does not do

- It is not a launchpad plugin: `ALAutonomousLife.getEnabledLaunchpadPlugins()` does not list it, and `setLaunchpadPluginEnabled` does not reach it.
- **2.1's other six plugins stay missing** (Activities, Battery, HardwareInfo, Posture, Temperature, Timing): `Launchpad/State`, `Launchpad/Posture`, the battery, temperature and time keys are not written, so an activity whose launch condition reads one of them is not launched autonomously on the 2.1 sim. 2.8 runs its own six. Recorded as a limitation in [naoqi-fidelity.md](../container/naoqi-fidelity.md); to add here if a client's activity needs one.

### Mechanism

- A service folder of its own, `docker/naoqi/services/launchpad-people/`: a core tested on the host with a fake memory and a fake clock, under an `ALModule` shell on 2.1 and a qi service shell on 2.8, hidden name `_NaoqiSimLaunchpadPeople`, no method for clients.
- Loaded after the engagement zones module. It subscribes to `AutonomousLife/State` once Life answers, and reads the current state then.
- Listed in the status service next to the stubs, so a client tells naoqi-sim's keys from a robot's plugins: `NaoqiSim/Life/LaunchpadPeople` names the keys it writes ([status-service.md](../container/status-service.md)).
- **It follows the events on a thread of its own**: an ALMemory callback queues the event and returns, and the module handles them in order (subscribing and unsubscribing the two modules from a callback would wait on NAOqi from NAOqi's own thread). It subscribes to `AutonomousLife/State` at load, whether Life answers yet or not, and reads the current state (`disabled` when Life never raised one).

### Tests

- **Fast tier**: the keys at start; a fake population entering zone 2 then zone 1, tracked, lost; the keys unset when the state leaves `solitary` (2.1) or reaches `disabled` (2.8); the duration counting on a fake clock.
- **Live tier**: with the full scenario of [autonomous-life.md](../container/autonomous-life.md): a face prop at 2 m gives `NumPeopleZone2` 1, at 1 m `NumPeopleZone1` 1 and `ZoneOfTrackedHuman` 1.

## Open questions

1. **A person in zone 2 in front of the real NAO 2.1, Life in `solitary`**, to confirm the values above (those with nobody in view are measured). A deferral.
2. **A NAO 6** is unmeasured: which plugin runs in which state, `DistanceOfTrackedHuman`'s value. The 2.8 choices above follow its Life configuration.
3. **The other 2.1 plugins' keys**, if an activity needs them.
