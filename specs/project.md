---
code:
  - pyproject.toml
  - .gitattributes
  - src/naoqi_sim/files.py
  - src/naoqi_sim/docker_images.py
tests:
  - tests/test_project_map.py
  - tests/test_files.py
  - tests-e2e/test_install_live.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the naoqi-sim project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, development tooling, and how naoqi-sim is distributed.

## Decided

- **Python version:** 3.12 or 3.13 for host code (`requires-python = ">=3.12,<3.14"`, as naoqi-viewer): the versions tested. The libqi wheels go from cp310 to cp315, so the bound is ours, not libqi's. Code that runs inside NAOqi (the Python in `docker/naoqi/services/`) is Python 2.7, imposed by the suites' embedded interpreter. `.python-version` pins 3.12 for the dev venv.
- **libqi:** `qi>=3.1.8,<4` is a runtime dependency: naoqi-sim's host side talks to NAOqi over qi (camera injection, viewer, probe, live tests), so it does not run without it. The wheels come from the package index of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork on GitHub Pages (`https://funwithagents.github.io/libqi-python/simple/`), declared as in naoqi-viewer: a named index (`[[tool.uv.index]] name = "libqi"`, `explicit = true`, so only what is pinned to it comes from it) and `qi = { index = "libqi" }` in `[tool.uv.sources]`. This also keeps uv from picking Aldebaran's older `qi` 3.1.5 on PyPI. `uv.lock` holds the exact version; the range lets naoqi-sim and the packages installed next to it (naoqi-viewer, clients) each move to a new libqi release on its own (`uv lock --upgrade-package qi`), and a 4.0 is adopted on purpose. 3.1.8 is the floor because it fixed the failed connects 3.1.6 needed retries for: every qi connect makes one attempt ([testing.md](testing/testing.md)).
- **Platforms:** those the fork ships wheels for: **macOS 11+ on arm64, Linux x86_64 (glibc 2.28+), Windows x64**; `[tool.uv] environments` limits naoqi-sim's own lock to them. Elsewhere (Intel macOS, Linux arm64) installation fails instead of producing a naoqi-sim that cannot reach NAOqi. The containers need Docker: Docker Desktop on macOS and Windows ([container.md](container/container.md), "Platforms"). For Windows:
  - `.gitattributes` checks every text file out with LF, so a Windows checkout, and the wheel a git install builds from it, carries the entrypoints and scripts under `docker/` as the containers run them (a CRLF entrypoint does not start);
  - files naoqi-sim reads or writes (configs, the image records) are opened as UTF-8, and docker's output is read as UTF-8 (Windows' default is a legacy code page);
  - `naoqi-sim run` hears Ctrl-C without the event loop's signal handlers, which Windows lacks ([cli.md](runtime/cli.md)).
  - `docker` is run as `shutil.which` finds it, following `PATHEXT` as a shell does, where `subprocess` looks for `docker.exe` only (`docker_images.resolve`; the fast tier's fake is a `docker.cmd` there).
- **Package layout:** `src/` layout — `src/naoqi_sim/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`. Build backend: `hatchling` (wheel packages `src/naoqi_sim`).
- **Linting/formatting:** `ruff`, excluding `docker/naoqi/services/` (Python 2.7) and the untracked local investigation scripts.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that builds and runs the naoqi-sim containers. Full strategy is specced in [testing.md](testing/testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`. `docker/` is not itself in pyright's `include` (its code runs in container images whose dependencies are not in the host venv), but `extraPaths` lists each `docker/naoqi/services/<service>/` and `docker/tts-engine`, so the tests that import that code type-check.
- **Repo shape:**
  - `src/naoqi_sim/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept, in one folder per architecture layer (`runtime/`, `container/`, `services/`, `host/`, `testing/`); this spec, the overview, the index and the template stay at the root.
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `tests/` at repo root, one test file per module under test.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.
  - `docker/` — container recipes, one folder per container: `naoqi/` (the NAOqi image: Dockerfiles, entrypoints, healthcheck, and `services/<service>/`, the Python 2.7 and C++ code that runs inside NAOqi) and `tts-engine/` (the speech engine container), `compose.yaml` running both, and the gitignored `image-data/` for the user-supplied suite tarballs.
  - `docs/` — the user documentation the README links to; `CONTRIBUTING.md` — how the project is run and how to work in a checkout.
  - `examples/configs/` — config files to read and to copy: one per NAOqi version, each the `naoqi-sim config` command's output with everything turned on, and `ci.json` for a CI job or a server ([config.md](runtime/config.md), "Example files").
  - `.github/workflows/` — CI ([ci.md](testing/ci.md)), once built.
- **No Aldebaran assets in git** (see [_overview.md](_overview.md), "Licensing"): `.gitignore` covers suite tarballs, `docker/image-data/`, meshes and textures. An automated asset guard is not built yet.

### Distribution

naoqi-sim is distributed through its GitHub repository, not PyPI: another project depends on it as a **uv git dependency** pinned to a commit or tag. pip is not supported for naoqi-sim itself (see "Dependencies of a git install").

- **In a project**: the project's `pyproject.toml` declares

  ```toml
  [project]
  requires-python = ">=3.12,<3.14"            # naoqi-sim's range
  dependencies = ["naoqi-sim[viewer]"]          # or "naoqi-sim" for no window and no render camera

  [tool.uv.sources]
  naoqi-sim = { git = "https://github.com/funwithagents/naoqi-sim", rev = "<commit or tag>" }
  ```

  then, once per machine, `uv run naoqi-sim fetch-and-build-images --naoqi <version>` (the images) and, for Aldebaran's look in the window, `uv run naoqi-sim fetch-meshes` (its typed license acceptance); `uv run naoqi-sim run --config ...` or a `NaoqiSim` in the project's code then runs the simulated NAO. Docker, the suite download, the images and the meshes are never uv's job.
- **Dependencies of a git install.** uv applies naoqi-sim's own `[tool.uv.sources]` to a git dependency, the index source included (measured with uv 0.11.29): `qi` resolves to 3.1.8 from the libqi index and naoqi-viewer to its pinned commit, with nothing for the depending project to repeat. It needs no `environments` either: a registry dependency locks without a wheel for every platform (measured: a scratch project with none locked), so a machine the wheels don't cover fails at `uv sync`, for want of a wheel, rather than at `uv lock`. A project that would rather have its lock refuse those platforms adds naoqi-sim's three `environments`. It must not pin naoqi-viewer itself at another commit: naoqi-sim's pin is the one tested with it. pip ignores `[tool.uv.sources]`: it would find `qi` with `--extra-index-url https://funwithagents.github.io/libqi-python/simple/`, but naoqi-viewer's git pin would still be uv's alone.
- **The wheel** a git install builds holds `naoqi_sim` and, as its package data, the container recipes under `naoqi_sim/docker/`: everything under `docker/` but `image-data/` and Python caches (compose; `naoqi/`: the Dockerfiles and their ignore files, entrypoints, healthcheck and `services/`, the Python 2.7 and C++ sources of our NAOqi modules; `tts-engine/`), none of it an Aldebaran file. Hatch maps `src/naoqi_sim` and `docker` into the package (`only-include` and `sources`) and excludes `docker/image-data`, so even a wheel built from a checkout holding the suites carries none; `dev-mode-dirs = ["src"]` keeps the editable install of a checkout working, since hatch cannot make an editable install from a remapped path. The sdist is the repository's tracked files, which never include the image data either.
- **Where the files are** ([api.md](runtime/api.md), "Files on disk"): an installed naoqi-sim reads its recipes from the package and keeps the image data in the user data directory; a checkout uses `docker/` and `docker/image-data/` as today. Both build the images the same way, and compute the same `io.naoqi-sim.recipes` digest from the same recipes.
- **naoqi-viewer behind the extra** needs nothing more: its model and scenes are its package data, its meshes live in its own user data directory (`platformdirs.user_data_dir("naoqi-viewer")/meshes`), so one `fetch-meshes` serves every project and checkout on the machine, and its `naoqi-viewer` command and MuJoCo's `mjpython` (the macOS window) are installed in the depending project's environment with it.
- **Runtime dependencies**: `numpy`, `qi`, `sounddevice`, `platformdirs`; the `viewer` extra adds naoqi-viewer, the `webcam` extra `opencv-python-headless` ([video-input.md](host/video-input.md), "The webcam source"). The `dev` group takes both extras, so the fast tier tests the webcam's frame conversion with the real OpenCV.
- **Versions**: a depending project pins a commit or tag in its `[tool.uv.sources]` and moves it on purpose. The package version is baked into the images (`io.naoqi-sim.version`, `NaoqiSim/Version`) next to the recipes digest, which is what tells a commit's images from another's: moving to a commit that changed `docker/` makes `start()` ask for a rebuild, and one that did not reuses the images. The version is bumped by hand, with a tag, when a change is worth naming; the README carries the compatibility of naoqi-sim, naoqi-viewer and the NAOqi versions.
- **As a command of its own**: `uv tool install "naoqi-sim[viewer,webcam] @ git+https://github.com/funwithagents/naoqi-sim"`, which the README leads with for a person who runs the sim from a terminal. uv resolves `qi` and naoqi-viewer from naoqi-sim's own sources there as for a dependency (checked Nov 27, 2026 with `uv tool run --from` on a checkout's path: `qi` 3.1.8, naoqi-viewer and OpenCV installed, the recipes read from the package). A tool install exposes only naoqi-sim's command, hence `naoqi-sim fetch-meshes` ([cli.md](runtime/cli.md)). Not in the live tier yet.
- **Tested** by the live tier (`tests-e2e/test_install_live.py`): a scratch project, declaring only `requires-python`, the dependency and its source, installs this checkout as the wheel a git dependency builds, and runs `naoqi-sim run` from it on each version.

## Open questions

1. **pip.** `qi` is now on an index pip can use (`--extra-index-url`); naoqi-viewer, a git dependency without a package on an index, is what still keeps pip out. Deferred until someone needs pip.
