---
code:
  - docker/naoqi/services/engagement-zones/naoqi_sim_engagement_zones_core.py
  - docker/naoqi/services/engagement-zones/naoqi_sim_engagement_zones_almodule.py
  - docker/naoqi/services/engagement-zones/naoqi_sim_engagement_zones_qiservice.py
  - docker/naoqi/services/people-perception/naoqi_sim_people_perception_core.py
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
tests:
  - tests/test_engagement_zones_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_perception_live.py
---

# Engagement zones: ALEngagementZones replacement

**Status:** Implemented

Decided Nov 25, 2026: the module computes real zones, in place of the API-only stub of [perception-stubs.md](perception-stubs.md). The rule, the setters and the lists below were measured the same day on a real NAO 2.1 (trail in `spike/RESULTS.md`, "Launchpad plugins: why none starts on the sims; engagement zones measured on bobby"). Plan: [202611252200_engagement-zones-and-launchpad-people.md](../../plans/202611252200_engagement-zones-and-launchpad-people.md). Reviewed by the user Nov 25, 2026.

## Purpose

A NAO's `ALEngagementZones` sorts the people `ALPeoplePerception` sees into three zones around the robot: near and in front, farther or on the side, far. Autonomous Life decides from them when a person is close enough to talk to (the launchpad's people keys, [launchpad-people.md](launchpad-people.md)), and a program can react to a person entering a zone.

The desktop suites ship the module, but it works only with the built-in people perception, which naoqi-sim leaves out ([people-perception.md](people-perception.md), "The dependents"), so it has been an API-only stub: settings kept, zone 0 answered, no event. This spec makes it compute, from the population our people module publishes.

## Decided

### The zone of a point

For a point `(x, y, z)` in the robot frame, with the three settings `FirstLimitDistance` (default 1.5 m), `SecondLimitDistance` (2.5 m) and `LimitAngle` (90 degrees):

- `d = hypot(x, y)`: the height is ignored (a point 1.4 m ahead is in zone 1 at any height).
- `a = |atan(y / x)|` in degrees, 90 when `x` is 0. It is the angle to the robot's x axis, not to its forward direction: **a point behind the robot counts as in front** (with a limit of 60, a point at 121 degrees is in front, one at 120 on the side).
- The point is **in front** when `a < LimitAngle`, strictly. With the default 90, only a point exactly sideways is on the side.

| | In front | On the side |
|---|---|---|
| `d <= First` | 1 | 2 |
| `First < d <= Second` | 2 | 3 |
| `d > Second` | 3 | 3 |

Both limits are inclusive (1.5 m ahead is zone 1, 2.5 m zone 2). The origin is zone 1.

- `computeEngagementZone(x, y, z)` answers this for the point.
- `computeEngagementZone(xAngle, yAngle, distance, cameraPositionRobot)` answers it for the point at `distance` along the ray of the two image angles from the camera pose, placed in the robot frame as the people module places a head ([people-perception.md](people-perception.md), "The population from the faces").

### The settings

- `getFirstLimitDistance`, `getSecondLimitDistance`, `getLimitAngle` answer the current values.
- The setters **return nothing** (the documentation says a bool) and raise on a refused value, the value unchanged, with a NAO's texts:

| Setter | Accepted | Refused with |
|---|---|---|
| `setLimitAngle(deg)` | 0 to 180, both included | "The limit angle must be between 0 and 180 degrees" |
| `setFirstLimitDistance(m)` | 0 or more, and under the second distance | "The first distance must be positive and smaller than the second distance" |
| `setSecondLimitDistance(m)` | over the first distance | "The second distance must be positive and bigger than the first distance" |

- Each accepted call raises its event with the new value: `EngagementZones/LimitAngleUpdated` (in degrees, whatever the documentation says), `FirstLimitDistanceUpdated`, `SecondLimitDistanceUpdated`. On 2.8 the signals `limitAngleChanged`, `firstLimitChanged`, `secondLimitChanged` fire with them.
- The settings last until NAOqi restarts.

### People in zones

- **The module processes while it has a subscriber and is not paused**, as a NAO's does (the extractor API of [face-detection.md](face-detection.md)). Without a subscriber it writes nothing, and `computeEngagementZone` still answers.
- **It takes each population from the people module in-process**, after that module has written its keys and before it raises its events, as the people module takes the faces from the detector. So a person's zone is in ALMemory when `PeoplePerception/PopulationUpdated` and `JustArrived` reach their subscribers. A NAO raises `PeoplePerception/JustArrived` and `EngagementZones/PersonEnteredZone1` at the same moment (measured, a person standing in zone 1).
- **Each person's zone** is the zone of its `PositionInRobotFrame`, written to `PeoplePerception/Person/<id>/EngagementZone` (1, 2 or 3) at every population. The key is removed with the person.
- **Events per person**, each with the id:
  - a person sorted for the first time: `PersonEnteredZone1`, `PersonEnteredZone2` or `PersonEnteredZone3`, and nothing else;
  - a person whose zone changed: `PersonApproached` when the new zone is closer or `PersonMovedAway` when it is farther, then the `PersonEnteredZone` of the new zone.
- **Lists**: `EngagementZones/PeopleInZone1`, `PeopleInZone2`, `PeopleInZone3` hold the ids in each zone. They are rewritten, and `EngagementZones/PeopleInZonesUpdated` raised **with no value**, only:
  - at a population in which at least one of the events above was raised;
  - at the first population after the module starts processing;
  - once when the population becomes empty (the three lists emptied).
- So a person who disappears while others stay is still in its list until somebody changes zone. A consumer that needs the count at every moment reads the population. Whether a NAO's lists lag the same way is to confirm with open question 1.
- **A changed setting** applies from the next population.
- **The last subscriber leaving** empties the three people lists and the three movement lists, and raises `PeopleInZonesUpdated` and `MovementsInZonesUpdated`, both with no value.
- `isProcessing` is true while the module has a subscriber, is not paused and the people module processes.

### Movements

`EngagementZones/LastMovementsInZone1..3` stay empty and `MovementsInZonesUpdated` is never raised: naoqi-sim detects no movement. The names are declared, so a subscriber waits as on a robot in a still room.

### Mechanism

- A service of its own, `docker/naoqi/services/engagement-zones/`: a core tested on the host (the rule, the settings, the lists and events against a fake memory) under an `ALModule` shell on 2.1 and a qi service shell on 2.8 ([service-replacement.md](../container/service-replacement.md), "Object model per version").
- `ALEngagementZones` leaves the stubs' table and the `NaoqiSim/Perception/Stubs` list ([perception-stubs.md](perception-stubs.md), [status-service.md](../container/status-service.md)). The entrypoints keep leaving the built-in library out and keep checking the name answers.
- Loaded after the people module, before Autonomous Life.

### Tests

- **Fast tier**: the rule on the points measured on the robot (ahead at each limit, sideways, behind, at a height, with limits of 60 and 30 degrees); each setter's accepted and refused values and its event; a fake population moving between zones (the per-person key, the three lists, the entered, approached and moved-away events, no event when nothing changed); the lists emptied when the last subscriber leaves.
- **Live tier**, both versions: `computeEngagementZone` on a few points; a face prop at 2 m is in zone 2, moved to 1 m it enters zone 1 (`PersonEnteredZone1`, `PersonApproached`, `PeopleInZone1`), removed it leaves the lists.

## Specs this changes when it is built

[perception-stubs.md](perception-stubs.md) (the row and open question 1 go), [people-perception.md](people-perception.md) (a second in-process consumer), [status-service.md](../container/status-service.md) (the stubs list), [container.md](../container/container.md) (the loader's list), [naoqi-fidelity.md](../container/naoqi-fidelity.md).

## Open questions

1. **A walk between the zones in front of the real NAO 2.1**, to confirm the lists and events above with a person in view (the rule and the setters are measured; a person standing in zone 1 was seen to raise `PersonEnteredZone1` with `JustArrived`). A deferral: nothing here depends on it.
2. **A NAO 6** is unmeasured (none at hand): the 2.8 module follows the 2.1 measurements and the 2.8 documentation, which describes the same rule.
3. **Movements in zones** wait for a movement detection of our own.
