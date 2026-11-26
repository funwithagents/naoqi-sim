# Rename to naoqi-sim

**Status:** Done

Implements the toolkit rename decided on Oct 12, 2026 (in local notes, not committed: what changes, what stays, the order across the four repositories, the local migration). This plan renames nao-sim to naoqi-sim everywhere a name comes from the package: repository, distribution, import package, CLI, the `NaoSim*` classes and config, the `NaoSim` service and `NaoSim/*` ALMemory keys (the cross-package contract, [status-service.md](../specs/container/status-service.md)), the NAOqi-side modules and files, Docker names and labels, `NAO_SIM_*` variables, the user data directory, specs and docs; and follows naoqi-viewer's rename. It changes no behavior and adds no compatibility alias.

**Kept** (robot or upstream names): "a NAO in a box" and prose about the robot, Aldebaran's file names (`nao-x86-…` suites, `.opn` images), `nao_meshes` (upstream, one mention), the NAOqi module names nao-sim replaces (`ALTextToSpeech`, `ALAudioDevice`, `ALAudioPlayer`). `Done` plans and the older local notes are historical records and stay as written.

## Scope

Names, in replacement order (exact tokens, never a bare `nao`):

| Old | New | Where |
| --- | --- | --- |
| `NaoSim` | `NaoqiSim` | `NaoSim`, `NaoSimConfig`, `NaoSimError`…, the service, `NaoSim/*` keys, `NaoSimTextToSpeech`, `NaoSimAudioPlayer`, `NaoSimAudioRelay`, `NaoSimStatus` |
| `nao_sim` | `naoqi_sim` | the import package, `nao_sim_*` container modules and their files, `nao_sim_front_core.h`, `nao_sim_version()` |
| `nao-sim` | `naoqi-sim` | distribution, CLI, compose project, images `naoqi-sim/naoqi:<version>` and `naoqi-sim/tts:dev`, containers `naoqi-sim-naoqi21`…, volumes, label `io.naoqi-sim.version`/`.recipes`, target id, data directory, prose |
| `NAO_SIM` | `NAOQI_SIM` | every `NAO_SIM_*` variable (`IMAGE_DATA`, `VERSION`, `RECIPES`, `TTS_ENGINE`, `TTS_URL`, `HOST_LINK`, `INTERNAL_PORT`, `E2E_VERSION`, `E2E_AUDIO`, `SOUNDCARD`…), `NAO_SIM_FRONT_CORE_H` |
| `NaoViewer` | `NaoqiViewer` | `NaoViewer`, `NaoViewerConfig`, `FakeNaoViewer` |
| `nao_viewer` | `naoqi_viewer` | imports |
| `nao-viewer` | `naoqi-viewer` | the extra's dependency, the git source, prose |
| `nao-bridge`, `NaoBridge` | `naoqi-bridge`, `NaoqiBridge` | prose, the `sim` backend's description |

Files:

- `src/nao_sim/` → `src/naoqi_sim/` (`git mv`, all 14 modules)
- `docker/naoqi/services/**/nao_sim_*` → `naoqi_sim_*` (16 files: the Python cores and shells, the C++ fronts and relay, `nao_sim_front_core.h`), and every reference to them: the Dockerfiles' build and copy lines, `entrypoint-lib.sh`/`entrypoint-2.*.sh` (module loading, `autoload.ini`, the 2.1 `__all__` names), `healthcheck.sh`, the C++ `#include`s and library names, `tests/conftest.py`'s `sys.path`, `pyproject.toml`'s pyright `extraPaths` if a path changes
- `docker/compose.yaml` — `name: naoqi-sim`, images, `container_name`s, labels, `NAOQI_SIM_*`
- `docker/tts-engine/` — variable names, image name
- `src/naoqi_sim/docker_images.py` — `LABEL = "io.naoqi-sim.version"`, image names, `naoqi_sim_version()`
- `src/naoqi_sim/files.py` — `platformdirs.user_data_dir("naoqi-sim", …)`, `NAOQI_SIM_IMAGE_DATA`
- `src/naoqi_sim/stack.py` — the compose project and container filters
- `src/naoqi_sim/viewer.py` — `import naoqi_viewer`, `NaoqiViewer`, `NaoqiViewerConfig`
- `pyproject.toml` — `name = "naoqi-sim"`, version `0.1.0`, `naoqi-sim = "naoqi_sim.cli:main"`, `viewer = ["naoqi-viewer"]`, dev `naoqi-sim[viewer]`, hatch `only-include`/`sources` (`"src/naoqi_sim" = "naoqi_sim"`, `"docker" = "naoqi_sim/docker"`), `[tool.uv.sources] naoqi-viewer = { git = "https://github.com/funwithagents/naoqi-viewer", rev = <naoqi-viewer commit A> }`
- `uv.lock` — regenerated
- `tests/` — imports, `fake_docker.py` (names, labels), every test naming an image, label, variable or key
- `tests-e2e/` — `test_naosim_live.py` → `test_naoqisim_live.py`, the keys and service in `test_status_live.py`, `support.py`, `conftest.py` (`NAOQI_SIM_E2E_*`)
- `.github/workflows/ci.yml` — cache key and stamp (`naoqi_sim_version()`), `naoqi-sim fetch-and-build-images`, image names in `docker save`, the `naoqi-sim-` container filter
- `examples/configs/*.json` — names in comments or keys, if any
- `specs/` — all 21 specs: names, contract, the `code:`/`tests:` frontmatter paths (`src/naoqi_sim/…`, `docker/naoqi/services/**/naoqi_sim_*`); `_overview.md`; `status-service.md` (the contract table: service, methods, keys, target id); `container.md` (images, label, compose project, volumes); `project.md` (distribution, data directory, the `viewer` extra); `runtime/*.md` (`NaoqiSimConfig`, `NaoqiSim`, the `naoqi-sim` command); `host/viewer.md` (naoqi-viewer's API); `testing/*.md` (variables, CI)
- `specs/_index.md`, `plans/_index.md` — names in prose and this plan's row
- `AGENTS.md` — the project map (module rows `src/naoqi_sim/*`, which `tests/test_project_map.py` checks; the `docker/` row's file names), the e2e and linting sections; `README.md`
- The toolkit's cross-package notes (local, untracked): title "NAOqi toolkit (naoqi-bridge, naoqi-sim, naoqi-viewer)", every name and the contract, the open question "Repository names" closed by this rename

Spec statuses: the spec edits land in the same change as the code, so every `Implemented` spec stays `Implemented`. If the spec edits are committed ahead of the code, set the touched specs to `Updated` until this plan is `Done`.

## Steps

1. **Local migration** (once for the four repositories, from a plain terminal, no Claude session open in any of them; analysis, "Local migration"):
   - `uv run nao-sim cleanup`, all four repositories clean and pushed;
   - `cp -a ~/.claude/projects ~/claude-projects-backup-20261012`;
   - `gh repo rename naoqi-sim`; `mv nao-sim naoqi-sim`; `git remote set-url origin git@github.com:funwithagents/naoqi-sim.git`;
   - `mv ~/.claude/projects/-Users-thibault-code-funwithagents-nao-sim ~/.claude/projects/-Users-thibault-code-funwithagents-naoqi-sim` and the perl pass on its transcripts and memory paths;
   - `rm -rf .venv .pytest_cache .ruff_cache && uv sync --dev`;
   - reopen VS Code and `claude` in `naoqi-sim/`, check `/resume` lists the earlier conversations and the memory index loads.
2. Wait for naoqi-viewer's commit A (its plan, step 8), then branch `rename-naoqi`.
3. `git mv src/nao_sim src/naoqi_sim`, `git mv` each `nao_sim_*` container file and `tests-e2e/test_naosim_live.py`.
4. Replace the tokens in the table, in that order, across tracked files except `plans/2*.md` (`git ls-files -z | xargs -0 perl -pi -e '…'`, one exact substitution per row). Review `git diff` for kept names (the robot prose, `nao_meshes`, Aldebaran's file names).
5. Check by hand what a replacement cannot: the 2.1 ALModule globals and `__all__` (the module instance must still be named after its module), the C++ module names registered with the broker and their `.so` names in the entrypoints, the healthcheck's key, `check_images`' label comparison.
6. `pyproject.toml`: the git pin to naoqi-viewer's commit A; `uv lock && rm -rf .venv && uv sync --dev`; `uv cache clean nao-viewer`.
7. Lint, type check, fast tests (Verification).
8. **Docker**: `docker rmi nao-sim/naoqi:2.1.4.13 nao-sim/naoqi:2.8.7.4 nao-sim/tts:dev`, `docker volume rm nao-sim_packages-2.1 nao-sim_packages-2.8`; `uv run naoqi-sim fetch-and-build-images` (both versions, from `docker/image-data/`, nothing downloaded); `uv run pytest tests-e2e` on both versions.
9. Update the toolkit's cross-package notes (local).
10. Commit, push, CI green on both tiers and both versions; merge. Hand the merge commit to naoqi-viewer's plan (step 9, `NAOQI_SIM_REF`). If naoqi-viewer's branch is squash-merged, re-pin naoqi-viewer to its merge commit in a follow-up commit.
11. **Claude memory** in `~/.claude/projects/-Users-thibault-code-funwithagents-naoqi-sim/memory/`, once the code matches: new names in every memory that has old ones (`libqi3-connect-flaky-retry`, `naming-by-role-spec-matches-code`, `nao-opn-images-contents`, `naoqi-cpp-front-gotchas`, `py2-cannot-send-binary-native-relay`, `toolkit-cross-spec-decisions`); `nao-sim-spike-results.md` → `naoqi-sim-spike-results.md` with its `name:`, its `MEMORY.md` line and the `[[links]]` to it; `toolkit-rename-to-naoqi.md` rewritten as done: what was renamed, the product-versus-robot rule, the robot names kept for Pepper work. Remove `~/claude-projects-backup-20261012` once all four repositories are verified.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` all clean (`tests/test_project_map.py` included: map, frontmatter paths).
- `git grep -n -E 'NaoSim|nao_sim|nao-sim|NAO_SIM|NaoViewer|nao_viewer|nao-viewer|NaoBridge|nao-bridge' -- ':!plans/2*' ':!analysis'` returns nothing.
- `uv run python -c "import naoqi_sim, naoqi_viewer"` works; `uv pip list` shows no `nao-*` package.
- `uv build`: the wheel holds `naoqi_sim/` and `naoqi_sim/docker/`, no `image-data`.
- `uv run pytest tests-e2e` passes on 2.1 and 2.8: the `NaoqiSim` service answers, `NaoqiSim/NaoqiVersion` and `NaoqiSim/Ready` are set, `docker inspect` shows `io.naoqi-sim.version` = `0.1.0`, `qicli info` lists the renamed fronts.
- `uv run naoqi-sim run --config examples/configs/default.json` opens the window; `naoqi-sim status` and `naoqi-sim cleanup` find the stack.
- CI green on both tiers and both versions.

Mark this plan `Done` here and in [_index.md](_index.md) once merged with CI green and the memories updated.

## Outcome

Done Oct 12, 2026. The four GitHub repositories are renamed. naoqi-sim `8ca438d` pins naoqi-viewer `917a782`; naoqi-viewer's CI builds naoqi-sim at `8ca438d`, and both CI runs are green (one 2.1 live run failed on a timing race in `test_a_sound_and_a_sentence_play_together`, sentence ending 60 ms before the beep; it passed on rerun). Deviations:

- Step 1's moves of the working folders and Claude project folders could not run from a Claude session inside them: they are in `../naoqi-migrate.sh`, run once every session is closed. The GitHub rename and the remote URL ran first, as planned.
- Branches merged fast-forward, so every pinned commit is on `main`.
- Also renamed, outside the table: the C++ macro `NAOSIM_NAOQI_28` → `NAOQISIM_NAOQI_28` and the speech engine name `"naosim"` → `"naoqisim"`.
- naoqi-meshes' release `r1` was deleted and republished, not `r2`; its repository keeps no `plans/`.
