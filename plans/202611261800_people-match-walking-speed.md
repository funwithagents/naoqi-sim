# People perception: the match follows a walking person

**Status:** Done

Implements the updated matching rule in [people-perception.md](../specs/services/people-perception.md) ("A face is a person"): the radius within which a face is a known person grows with the time since that person was last seen, at walking speed, so a person walking toward the robot keeps their id when detections are sparse. The CI's live tier gave a new id to a face moved from 2 m to 1 m in 1 s (`test_a_face_walking_in_is_sorted_into_the_zones`, `test_the_launchpad_keys_follow_a_person_walking_in`, failing since the engagement zones). Crowds and crossing faces stay open question 1.

## Scope

- `docker/naoqi/services/people-perception/naoqi_sim_people_perception_core.py` — `WALKING_SPEED`, `MAX_UNSEEN_FOR_MATCH`; `_match` takes the time and widens each person's radius by the time since they were last seen
- `tests/test_people_perception_core.py` — a face moved 1 m with one detection a second keeps its person; a face farther than a walk allows is a new person; the existing "two faces are two people" check made in one detection
- `specs/services/people-perception.md`, `specs/_index.md`, `plans/_index.md` — statuses

## Steps

1. `MATCH_DISTANCE` stays 0.35 m; add `WALKING_SPEED = 1.5` (m/s) and `MAX_UNSEEN_FOR_MATCH = 1.0` (s).
2. `_match(world, taken, now)`: for each person not taken, the radius is `MATCH_DISTANCE + WALKING_SPEED * min(now - person.last_seen, MAX_UNSEEN_FOR_MATCH)`; the nearest person within their own radius wins.
3. Tests as in the scope; the fast tier, lint, format, pyright.
4. The live tier's perception and Life tests on both versions (CI), then spec `Implemented`, plan `Done`.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`; the live tier on CI (the two tests that failed). Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
