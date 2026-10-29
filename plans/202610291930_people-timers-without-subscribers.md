# People perception: the timers run with nobody subscribed

**Status:** Done

Implements the settled behavior in [people-perception.md](../specs/services/people-perception.md) ("The timers run with nobody subscribed"): when the last subscriber leaves, the population keeps aging (invisible after 2 s, gone after 10 s) instead of freezing as last written. The people display's own subscription is naoqi-viewer's (its people display subscribes to `ALPeoplePerception`, as its camera display subscribes to `ALVideoDevice`: funwithagents/naoqi-viewer#7, merged as `bd3b71f`), taken here with the pin. Nothing else changes.

## Scope

- `docker/naoqi/services/face-detection/naoqi_sim_face_detection_core.py` — the detector gives each consumer that wants no detections an `on_idle` tick every 0.5 s.
- `docker/naoqi/services/people-perception/naoqi_sim_people_perception_core.py` — `on_idle` ages the people and writes and raises on a change; the timers on the module's own clock.
- `tests/test_people_perception_core.py`, `tests/test_face_detection_core.py` — the timers with nobody subscribed; the tick.
- `pyproject.toml`, `uv.lock`, [viewer.md](../specs/host/viewer.md) — naoqi-viewer's pin, `bd3b71f`, and the people display's subscription described.

## Steps

1. The tick and `on_idle`, their fast tests.
2. Rebuild, and the live tier's perception file on both versions.

## Verification

Lint, type check, the fast tier; `uv run pytest tests-e2e/test_perception_live.py` on both versions. Mark this plan `Done` (here and in [_index.md](_index.md)) and the spec `Implemented` once they pass.

## As built

Done Oct 29, 2026: lint, type check, the fast tier (427 passed) and `tests-e2e/test_perception_live.py` on both versions (13 passed, 1 expected failure: life on 2.1) pass. The hand check with the webcam (the marker leaving about 10 s after the last subscriber) is the user's, with naoqi-viewer#7's people display, pinned since at `bd3b71f`; naoqi-viewer's own people live tests pass against this naoqi-sim (and, in its CI, against the built-in people perception).

## Amended Oct 29, 2026: what a real NAO does

Measured on bobby (a real NAO 2.1) the same day, two things changed this plan:

- **Leaving**: a NAO clears its population at once when the last subscriber leaves, with `PopulationReset` and no `JustLeft`. That replaces the timers with nobody subscribed; the timers stay for a paused module.
- **Frames**: `Distance` is the camera-to-head distance and `AnglesYawPitch` the head's angles from the camera's axis, and so are the `PeopleDetected`/`PopulationUpdated` entries. Ours were measured from the floor origin, which put a visitor's face, above the camera, out of the head's reach: with a webcam, awareness never moved the head.

Scope added: the people core (camera-relative values, clearing on the last unsubscribe), its tests, `tests-e2e/test_perception_live.py` (the angles in the keys, a face above the camera raising the head, the population cleared on the last unsubscribe), [people-perception.md](../specs/services/people-perception.md) back to `Updated` until this is verified.

Verified after the amendment: the fast tier (428 passed) and `tests-e2e/test_perception_live.py` on both versions (16 passed and 1 expected failure, then the face-above test, moved fully into the camera's view, passing on both: 0.35 m above the camera at 1 m left the face cut by the top of 2.1's view, where the detector does not find it).
