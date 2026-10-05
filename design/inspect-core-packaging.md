# inspect_core packaging and the sentinel dependency

Discussion notes. Two proposals that change what sentinel's `workstreams.md` recorded on 2026-10-02 ("inspect_ai depends on sentinel directly").

## Current state (draft PR #5664)

- Wire types live in `src/inspect_ai/core`: ChatMessage, Content, ToolCall, ToolInfo, ModelOutput, GenerateConfig, and the types they reference (citations, ToolParams, JSONSchema, CachePolicy, AdaptiveConcurrency).
- Original modules re-export everything that moved. Existing imports keep working, private ones included.
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
- Watch item: `sentinel.md` plans to deprecate `@reviewer` in favor of `@protocol`. After that, review users need an optional package for the replacement. Same position as scanners with Scout. The deprecation is already deferred.

## Proposal 2: keep `inspect_ai.core` inside the inspect_ai wheel for now

- Evals: no extra cost. inspect_ai is already loaded.
- Sentinel: imports types from `inspect_ai.core`. No cycle.
- WASM in a proxy:
  - The bundler ships `inspect_ai/core` plus an empty `inspect_ai/__init__.py`.
  - Safe because the import test guarantees core needs nothing else.
  - The portability linter must reject monitor imports from inspect_ai other than `inspect_ai.core`.
- Cost: Python processes that don't run evals (proxy sidecar, small log reader):
  - must install all of inspect_ai
  - importing `inspect_ai.core` runs `inspect_ai/__init__.py`, measured in `inspect-core.md` at about 1.7s and 1,500 modules
- If a separate wheel becomes necessary:
  - Move the code to a new top-level `inspect_core` package and publish that. Don't build a wheel out of `inspect_ai/core`.
  - Hold the internal import rewrite (462 statements in 202 files) until this is decided, so it happens once.
  - Keep `inspect_ai.core` undocumented or marked experimental until then, to limit outside users.
  - `inspect-core` and `inspect_core` are both free on PyPI. Worth reserving?

## Questions

1. Sentinel follows the Scout pattern instead of becoming a required dependency?
2. Keep `inspect_ai.core` in the inspect_ai wheel and defer a separate wheel until a Python process that doesn't run evals needs one?
3. Is a Python sidecar planned soon? That would justify a separate wheel now.
4. Reserve the `inspect-core` name on PyPI now?
