# inspect_core packaging and the sentinel dependency

Discussion notes. Two proposals that change what `design/workstreams.md` in [meridianlabs-ai/inspect_sentinel](https://github.com/meridianlabs-ai/inspect_sentinel) recorded on 2026-10-02 ("inspect_ai depends on sentinel directly"). Other `design/*.md` files cited below are in that repo too.

## Current state (draft PR #5664)

- Wire types live in `src/inspect_ai/core`: ChatMessage, Content, ToolCall, ToolInfo, ModelOutput, GenerateConfig, and the types they reference (citations, ToolParams, JSONSchema, CachePolicy, AdaptiveConcurrency).
- Original modules re-export every name that moved, private ones included. Names an original module only imported from elsewhere (for example `ToolCall` in `model/_chat_message.py`) are no longer there; nothing in `src`, `tests`, `docs`, `examples`, inspect_scout or inspect_swe uses them.
- Every re-export site has the same comment: `# Backward-compatible re-exports of names that moved to inspect_ai.core.`
- `tests/core/test_core_imports.py` checks every import in `inspect_ai.core`, including imports inside functions and under `TYPE_CHECKING`. Allowed: standard library, pydantic, typing_extensions, shortuuid, `inspect_ai.core`.
- Two exceptions remain, both imports inside functions:
  - `warn_once` in ChatMessage
  - `active_model` in `ModelOutput.from_message`
- Registry functions not moved yet.

## Proposal 1: sentinel stays optional, like inspect_scout

- Scout pattern: Scout requires inspect-ai. inspect_ai uses Scout only if installed, with a version check and a clear error otherwise. `inspect-scout` appears only in `requirements-dev.txt`.
- Sentinel would do the same. `feature/sentinel` already works this way.
- Reasons:
  - A required dependency makes inspect_ai and inspect_sentinel require each other. Only a separate inspect_core wheel removes that, and nothing else needs one yet.
  - No import cycle. Sentinel imports `inspect_ai.core`. inspect_ai loads its sentinel code only when a sentinel is configured.
  - Delayed imports can stay in the few places that check for a configured sentinel. Scout's are spread across about 40 call sites; sentinel's need not be.
- The `--no-deps` install in inspect_ai's CI is a separate issue:
  - Cause: sentinel depends on inspect_ai through a git branch, which conflicts with the editable install.
  - Goes away once sentinel is on PyPI with a version range, as Scout is.
- Watch item: `design/sentinel.md` plans to deprecate `@reviewer` in favor of `@protocol`. After that, review users need an optional package for the replacement. Same position as scanners with Scout. The deprecation is already deferred.

## Proposal 2: keep `inspect_ai.core` inside the inspect_ai wheel for now

- Evals: no extra cost. inspect_ai is already loaded.
- Sentinel: imports types from `inspect_ai.core`. No cycle.
- WASM in a proxy:
  - The bundler ships `inspect_ai/core` plus an empty `inspect_ai/__init__.py`.
  - Safe because the import test guarantees core needs nothing else.
  - The portability linter must reject monitor imports from inspect_ai other than `inspect_ai.core`.
- Cost: Python processes that don't run evals (proxy sidecar, small log reader):
  - must install all of inspect_ai
  - importing `inspect_ai.core` runs `inspect_ai/__init__.py`, measured in `design/inspect-core.md` at about 1.7s and 1,500 modules
- If a separate wheel becomes necessary:
  - Move the code to a new top-level `inspect_core` package and publish that. Don't build a wheel out of `inspect_ai/core`.
  - Hold the internal import rewrite (462 statements in 202 files) until this is decided, so it happens once.
  - Keep `inspect_ai.core` undocumented or marked experimental until then, to limit outside users.
  - `inspect-core` and `inspect_core` are both free on PyPI. Worth reserving?

## Recommendation: no separate package or wheel yet

- What a separate wheel buys:
  - Smaller installs for Python processes that don't run evals. The only benefit nothing else provides.
  - No circular requirement with sentinel. Gone anyway under the Scout pattern.
  - A clearer boundary. The allowlist test already enforces it.
  - An independent version for the wire contract. A schema version stamped in the payload and the bundle manifest does this without a separate wheel.
- What it costs, permanently: a second `pyproject.toml`, release automation, an exact version pin from inspect_ai, CI and editable installs for two packages, more for contributors to understand.
- WASM barely depends on the layout. The real risks are a wasm32-wasi build of `pydantic_core` and asyncio on WASI. Either one can stop the WASM path regardless of packaging. Copying `inspect_ai/core` with an empty `__init__.py` is a few lines in the bundler.
- The sidecar is the case to watch. `design/sentinel-deployment.md` names it as the first thing to ship, and it is a Python process that doesn't run evals.
  - Import time doesn't matter there: 1.7s once, at service startup.
  - Image size and dependency count do: all of inspect_ai's dependencies to install and patch.
- Plan:
  - Stay with `inspect_ai.core`.
  - Reserve `inspect-core` on PyPI.
  - Keep `inspect_ai.core` undocumented or experimental, and hold the internal import rewrite.
  - Revisit when a sidecar nears production. Measure its image size with and without inspect_ai's dependencies, and decide on that number.
- Deferring is cheap. Core is already self-contained and enforced, so a later move to a top-level `inspect_core` is a few days of mechanical work, not a redesign.

## Questions

1. Sentinel follows the Scout pattern instead of becoming a required dependency?
2. Keep `inspect_ai.core` in the inspect_ai wheel and defer a separate wheel until a Python process that doesn't run evals needs one?
3. Is a Python sidecar planned soon? That would justify a separate wheel now.
4. Reserve the `inspect-core` name on PyPI now?
