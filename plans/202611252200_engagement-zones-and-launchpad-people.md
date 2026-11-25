# Engagement zones and the launchpad's people keys

**Status:** In progress

Implements [engagement-zones.md](../specs/services/engagement-zones.md) and [launchpad-people.md](../specs/services/launchpad-people.md): `ALEngagementZones` computes real zones from our population in place of its stub, and a hidden module of ours writes the launchpad's people keys while Life runs, so Life goes to a person by itself on both sims. Two PRs, stacked on the robot state's (#29): the zones first, then the keys. Leaves out the movement keys (no movement detection), 2.1's other launchpad plugins, and the full-scenario live test with our own packages ([autonomous-life.md](../specs/container/autonomous-life.md), "Tests"), which comes after.

## Scope

- `docker/naoqi/services/engagement-zones/naoqi_sim_engagement_zones_core.py` — the zone rule, the settings and their checks, the per-person key, the lists and events, `computeEngagementZone`'s two forms
- `docker/naoqi/services/engagement-zones/naoqi_sim_engagement_zones_almodule.py`, `..._qiservice.py` — the 2.1 and 2.8 shells (2.8: the three signals)
- `docker/naoqi/services/people-perception/naoqi_sim_people_perception_core.py` — population consumers, called after the keys are written and before the events; the zone key removed with the person
- `docker/naoqi/services/perception-stubs/naoqi_sim_perception_stubs_core.py` — `ALEngagementZones` leaves the stubs' table and status key
- `docker/naoqi/services/launchpad-people/naoqi_sim_launchpad_people_core.py` and its two shells — the keys, following `AutonomousLife/State`, subscribing to people and zones while running
- `docker/naoqi/entrypoint-2.1.sh`, `entrypoint-2.8.sh` — the modules' load order (zones after people; launchpad people after zones), the hidden name checked
- `tests/test_engagement_zones_core.py`, `tests/test_launchpad_people_core.py`, `tests/test_perception_stubs_core.py`, `tests/test_people_perception_core.py`, `tests/test_entrypoint.py` — fast tier
- `tests-e2e/test_perception_live.py`, `tests-e2e/test_life_live.py` — live tier
- Specs: the two above to `Implemented`, and the specs they name under "Specs this changes when it is built"; `AGENTS.md` project map

## Steps

1. People module: a list of population consumers (`add_consumer`), each called with the population (id and robot-frame position of every person) after the keys are written and before `JustArrived`, `JustLeft` and `PopulationUpdated`; also on an idle update and on a reset (empty population). `EngagementZone` joins the per-person keys removed with a person.
2. Zones core: an `Extractor` subclass. The rule (planar distance, inclusive limits, `|atan(y/x)|` strictly under the angle), the setters' checks and texts, their events and signals; `computeEngagementZone(x, y, z)` and the camera-angles form (the ray placed with the 6D camera pose). As a consumer: processes only while subscribed and not paused; the per-person key at every population, the entered/approached/moved-away events, the lists and `PeopleInZonesUpdated` (with no value) when an event was raised, at the first population and once when the population empties; the last subscriber leaving empties the six lists and raises both updated events.
3. Shells and load order: `ALEngagementZones` served by the new module on both versions, loaded right after the people module; dropped from the stubs and `NaoqiSim/Perception/Stubs`.
4. Fast and live tests for the zones (spec's "Tests"). PR.
5. Launchpad people core: follows `AutonomousLife/State` (2.1: runs in `solitary`; 2.8: `solitary` and `interactive`), subscribes to people and zones at 200 ms while running, writes the keys from the events and lists, raises every key empty (`DurationPeopleNotSeen` -1) when it stops; a clock for the duration.
6. Its shells (hidden `_NaoqiSimLaunchpadPeople`), load order after the zones, the status service's list.
7. Fast tests; live tests: a face prop at 2 m then 1 m gives `NumPeopleZone2`, then `NumPeopleZone1` and `ZoneOfTrackedHuman` 1; on 2.8 Life goes `interactive` by itself. PR.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`, and the live tier on both versions after `fetch-and-build-images`. Mark `Done` (here and in [_index.md](_index.md)) once both PRs' checks pass, and the two specs `Implemented`.
