# Nightly image data check

**Status:** Done

Implements [ci.md](../specs/testing/ci.md) ("The nightly image data check"): a scheduled workflow that asks each pinned image data URL, with a HEAD request, whether it still serves its file, and opens an issue when one does not. It leaves the engines' models and the meshes out, and downloads nothing: the full hashes stay the cold build's.

## Scope

- `src/naoqi_sim/suite.py` — `PinnedFile.size`, pinned for the six downloads; `download_problem` (one HEAD request: status, `Content-Length`, a SHA-256 `ETag`) and `check_image_data` (every pinned file, three tries)
- `tests/test_suite.py` — the check against a local server that answers HEAD only: all served, a 404, a passing fault, another size, another hash, an ETag that is not a hash, no answer; every real pin has its size
- `.github/workflows/image-data-check.yml` — the nightly schedule, the check, the issue on failure
- `specs/testing/ci.md`, `specs/container/container.md`, `specs/_index.md`, `AGENTS.md`, this plan and `plans/_index.md`

## Steps

1. Measure what the six URLs answer to HEAD (sizes, ETags), and pin the sizes.
2. `download_problem` and `check_image_data`, then their tests.
3. The workflow.
4. The specs and the project map.

## Verification

- `uv run ruff check .`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest`.
- The check run against the real URLs: six available, exit 0 (Nov 27, 2026).
- The workflow itself runs only once it is on `main`: start it by hand there (`gh workflow run image-data-check.yml`) to see it green. The issue step has not run.
