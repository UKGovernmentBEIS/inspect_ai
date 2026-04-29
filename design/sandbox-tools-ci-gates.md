# Sandbox Tools CI Gates

Design for the CI jobs that protect the sandbox-tools injection pipeline on pull requests. See issue #3704 for background.

## Problem

The sandbox-tools binary (`inspect-sandbox-tools`) is injected into user containers at runtime. There are two artifact flavors:

- **Published `-v{N}`**: built by maintainers and uploaded to S3. The PyPI publish flow downloads the S3 artifact and bundles it into the wheel (under `src/inspect_ai/binaries/`), so PyPI users resolve it via the local-file path with no runtime S3 access. Editable installs whose sandbox-tools source matches `main` fall through to an S3 download at first use and cache the result locally.
- **`-v{N}-dev`**: built locally via Docker. Used by contributors iterating on the injectable source; never published to S3.

Selection happens in `sandbox.py::_get_install_state()`, which classifies an editable install as `clean` or `edited` by diffing `src/inspect_sandbox_tools/` and `sandbox_tools_version.txt` against `main`. `edited` forces the `-dev` name; `clean` uses the published name. PyPI installs are classified `pypi` and always use the bundled non-dev binary.

The CI gates exist to prevent two failure modes:

1. **Regression in sandbox-related tool behavior.** The end-to-end tests under `tests/tools/` that exercise real sandboxes are too slow to run in the normal test gate, so they're excluded there and run in a dedicated slow-test gate instead. That gate only triggers when a PR touches code that could plausibly regress them — the host-side tool code, the injectable, or the tests themselves. PRs touching those paths pay the cost of the slower tests; PRs that don't, don't.
2. **Merging injectable source changes that haven't been published.** If `src/inspect_sandbox_tools/` changes but `sandbox_tools_version.txt` isn't bumped (and the new `v{N}` isn't uploaded to S3), the next PyPI wheel build will either fail or bundle the wrong binary, and editable installs on `main` will S3-download a binary that doesn't match the source tree. The gates force the bump and verify the S3 upload before the PR can land.

## Gates

Three jobs run in sequence on PRs:

```
check-tool-paths ──► check-version-bump ──► slow-tool-tests-dev ──► slow-tool-tests-release
```

- **`check-tool-paths`** — detects whether the PR touches tool-related paths relative to the PR base branch. Emits `tools_changed` and `injectable_src_changed`.
- **`check-version-bump`** — fast, cheap. Reads `sandbox_tools_version.txt` on the PR and on the base branch. Enforces the invariant "injectable source and version move together": fails when the injectable source changed without a correct `N+1` bump, and also when the version was bumped without an injectable change.
- **`slow-tool-tests-dev`** — runs `pytest --runslow -m slow tests/tools/`. Green = "your code works from a developer perspective." Conditionally builds a `-dev` binary in CI when the PR changed the injected code; otherwise uses the published `v{N}` via the runtime's normal S3 download path.
- **`slow-tool-tests-release`** — runs only when a version bump is present. Prechecks S3 for the new `v{N+1}`; on 404 fails fast with a message telling the maintainer to run `upload_to_s3.py`. On success, downloads the published artifact and re-runs the slow tests against it. Maintainer reruns this job manually from the Actions UI after publishing.

## Behavior matrix

When `check-tool-paths` returns false, none of the downstream gates execute. The table describes the four possibilities when `check-tool-paths` returns true. `N` = version on the PR base branch.

| Scenario | injectable src | `...version.txt` | check-version-bump | slow-tool-tests-dev | slow-tool-tests-release |
|---|---|---|---|---|---|
| Tool changes unrelated&nbsp;to&nbsp;the&nbsp;injectable | unchanged | unchanged | pass | **run** — no build; pytest resolves `v{N}` via normal S3 download path | skip |
| Same as above with mistaken&nbsp;version.txt&nbsp;change | unchanged | any change | **fail** — "unexpected version bump" | skip | skip |
| Injectable change with&nbsp;correct&nbsp;bump | changed | bumped to N+1 | pass | **run** — conditional build; pytest uses freshly-built `-dev v{N+1}` | **run** — precheck `v{N+1}`; download; pytest with `INSTALL_STATE = clean` |
| Injectable change, bump&nbsp;missing&nbsp;or&nbsp;wrong | changed | unchanged OR changed to anything ≠ N+1 | **fail** — "missing or incorrect version bump" | skip | skip |

## Gate conditions

- `check-version-bump`: `needs: check-tool-paths`; `if: tools_changed == 'true'`. Enforces that injectable source and version move together — passes when both changed (injectable edit + N→N+1 bump) or neither changed; fails otherwise. Emits `version_correctly_bumped` for downstream jobs.
- `slow-tool-tests-dev`: `needs: [check-tool-paths, check-version-bump]`; `if: tools_changed == 'true'`; build step conditional on `injectable_src_changed || version_correctly_bumped`.
- `slow-tool-tests-release`: `needs: [check-tool-paths, check-version-bump, slow-tool-tests-dev]`; `if: tools_changed == 'true' && version_correctly_bumped == 'true'`.

## `INSPECT_SANDBOX_TOOLS_INSTALL_STATE` escape hatch

`slow-tool-tests-release` tests against the downloaded non-dev `v{N+1}`, but the runtime's install-state check would return `edited` on a release PR (because `sandbox_tools_version.txt` differs from main) and resolve the `-dev` name. To avoid duplicating the divergence logic, the release gate sets `INSPECT_SANDBOX_TOOLS_INSTALL_STATE=clean`, forcing the non-dev resolution. The dev gate does not set it — the host-side-change case relies on the natural `clean` classification to exercise the real S3 download path.
