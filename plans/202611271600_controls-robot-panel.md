# The controls' Robot panel

**Status:** Done

Implements `specs/host/controls.md` ("The robot", the Robot line of "The page", the `/api/robot/*` rows of "The HTTP API"): the page shows the robot's motors, stiffness, posture and Autonomous Life as NAOqi reports them, with buttons the server relays to NAOqi, one action at a time. No Python API on `NaoqiSim`: a program calls NAOqi itself.

## Scope

- `src/naoqi_sim/controls.py` — `Robot` (its own qi session: `state()`, one action at a time), the `/api/robot/*` routes, `robot` in the state
- `src/naoqi_sim/controls.html` — the Robot panel: four lines, state beside its buttons, the running action, NAOqi's refusals on the panel's message line
- `src/naoqi_sim/sim.py` — the controls get a `Robot` on a session of their own
- `tests/test_controls.py` — the routes and the state against fake NAOqi services: each action's call, busy (409), `goToPosture` False (409), NAOqi failing (500, and `robot.error` in the state)
- `tests-e2e/test_controls_robot_live.py` — through HTTP on both versions: rest, a posture with the stiffness off, wake up, stiffness off and on, Life on and off

## Steps

1. `Robot(connect)` in `controls.py`: `start()` opens the session, `stop()` closes it; `state()` reads `robotIsWakeUp`, `getStiffnesses("Body")` (min, max), `getPosture`, Life's `getState` and `focusedActivity`, plus `running`; a failure gives `{"error": ...}`. `do(name, call)` takes a non-blocking lock (409 naming the running action otherwise) and runs the call.
2. The routes: `motors` (`wake_up`, `rest`), `stiffness` (`on`), `posture` (`Stand`, `StandInit`, `Sit`, `Crouch`; `False` is a 409), `life` (`on`: `solitary` or `disabled`); bad bodies 400.
3. `Controls` takes the `Robot` (optional, for the tests that need none) and starts and stops it with the server; `state()` adds `robot`.
4. `NaoqiSim._start_controls` gives the controls `Robot(stack.connect)`.
5. The page's Robot panel, first in the side column; buttons disabled while `running` is set or the state has an error.
6. The tests, the spec back to `Implemented`.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; `uv run pytest tests-e2e/test_controls_robot_live.py` on both versions, on an idle machine.
