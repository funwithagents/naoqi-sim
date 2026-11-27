# Contributing

Thanks for your interest in naoqi-sim. This page says how the project is run, so you know what to expect before you spend time on it.

## Feedback: yes, please

Issues are the way in, at [github.com/funwithagents/naoqi-sim/issues](https://github.com/funwithagents/naoqi-sim/issues):

- **Bug reports.** Say what you ran (the command or the config, the NAOqi version, your OS and Docker), what you expected, what happened, and the output of `naoqi-sim status` and `naoqi-sim logs --tail 200`. A small script that reproduces it is the best possible report.
- **Differences from a real robot.** naoqi-sim's job is to behave like a NAO in its API. If a call answers differently on your robot than on the sim, that is exactly what the project wants to know: the call, the two answers, the robot and its NAOqi version.
- **Questions.** If the README or a page under [docs/](docs/index.md) left you guessing, that is a documentation bug worth an issue too.

## Pull requests

The project is developed by one person, as a spec-driven project, and is not taking external pull requests for now: a change is designed in a spec before it is coded, and reviewing code written outside that loop costs more than redoing it. If you have a change in mind, open an issue describing it first. The code is Apache-2.0: forking it and building on it is welcome.

## How it is developed

- **Specs first.** Each concept has one spec under [specs/](specs/_index.md), the design with its reasons, its measurements and its open questions; [specs/_overview.md](specs/_overview.md) is the architecture. Each spec names the code and tests it governs, and a test keeps that map and the statuses honest.
- **Plans.** A settled spec becomes an implementation plan under [plans/](plans/_index.md), then code.
- **Two test tiers.** `tests/` is fast and deterministic, with no Docker: the host code, and the code that runs inside the containers against fakes. `tests-e2e/` starts the real containers, once per NAOqi version, and checks the simulated robot over qi as any client would.
- **CI on every change**: lint, format and types, the fast tier, and the live tier on both NAOqi versions ([specs/testing/ci.md](specs/testing/ci.md)).
- **[AGENTS.md](AGENTS.md) is the operating manual** for anyone, or any coding agent, working in the repository: the project map, the verification gate, how specs and plans are kept in step with the code.

## Working in a checkout

```bash
uv sync --dev                              # everything, extras included
uv run naoqi-sim fetch-and-build-images --naoqi 2.1 2.8   # the images; again after changing docker/
uv run naoqi-sim run --naoqi 2.8 --viewer --mic --controls

uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest                              # the fast tier
uv run pytest tests-e2e                    # the live tier: stop any running naoqi-sim first
```

A checkout keeps the downloaded image data in `docker/image-data/` (gitignored). **Never commit Aldebaran's software**: the NAOqi suites, robot images and packages, meshes or textures, or anything derived from them. The images built from the suites stay on your machine and are never pushed.
