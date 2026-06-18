# Checkpoint: back up + hydrate assistant-internal state


## Context

Providers "smuggle" wire-level content that doesn't round-trip through `ChatMessage` — Anthropic thinking blocks / server-tool spans, OpenAI Responses tool-call params — in per-provider `ContextVar[_AssistantInternal]` dataclasses. Message replay consults these caches to reconstruct full-fidelity requests. The checkpoint host backup currently captures events/store/agent_state but NOT this state, so a resumed sample replays prior assistant messages with missing thinking blocks / tool params. Fix: serialize it into the host context at each fire, restore at hydrate. `init_sample_assistant_internal()` gains an optional `JsonValue` param used by the hydrate path.

## Key facts / constraints

- OpenAI `_AssistantInternal` (`src/inspect_ai/model/_openai_responses.py:614`): `tool_calls`, `server_tool_uses` — values are SDK **TypedDicts** (plain dicts at runtime) → JSON-dump directly, restore via `cast`.
- Anthropic `_AssistantInternal` (`src/inspect_ai/model/_providers/anthropic.py:2651`): `thinking_blocks` (TypedDicts), `tool_call_internal_names` (`dict[str, str | None]`), `server_mcp_tool_uses` (`dict[str, tuple[TypedDict, TypedDict]]` — JSON turns tuple→list; restore `tuple(...)`), `server_tool_spans` / `server_tool_span_index` (share `_ServerToolSpan` **object identity**; `anthropic.py:2681-2706`). `_ServerToolSpan` (`anthropic.py:2572`) is a dataclass with `blocks: list[TypedDict]`, `content_ids: list[str]`, `open_use_ids: set[str]` (set → sorted list on dump, set() on load).
- **Restore must mutate in place, not `ContextVar.set()`**: providers populate the instance set at `run.py:1091` (sample task) by in-place dict mutation, which is why scorers (sibling task, post-solver) see it. Restore runs in `_CheckpointerSetup.__aenter__` (solver task); a `.set()` there would be invisible to the scoring task (matters for `resume_for_scoring`). So: `init_sample_*_assistant_internal(value)` with `value is None` → `.set(fresh)` (today's behavior); with value → populate the *current* instance in place. Docstring must state this rationale.
- Layering OK: `util/_checkpoint` already imports `inspect_ai.model._chat_message` (`host_context.py`, `hydrate.py`); it must never import `_eval` → aggregator moves out of `run.py`.
- `_hydrate_host` runs as a tg_collect child task → do NOT restore in `_push_host_state`; carry value on the result and restore after `hydrate()` returns. (In-place mutation would technically work from the child task too, but keep restore at `__aenter__` — single obvious point, runs once thanks to the `_cached` re-entry guard at `checkpointer_impl.py:118-120`.)

## Changes

### 1. New `src/inspect_ai/model/_assistant_internal.py`
Move from `run.py:2041-2068` (delete there; update import at `run.py:1091`; keep the `_HAS_OPENAI`/`_HAS_ANTHROPIC` find_spec caching + its perf comment):
- `init_sample_assistant_internal(value: JsonValue | None = None) -> None` — forwards `value["openai"]` / `value["anthropic"]` (when present) to provider inits.
- `dump_sample_assistant_internal() -> JsonValue | None` — `{"openai": ..., "anthropic": ...}`, omit empty providers, `None` when nothing to save (signals skip-file).
- Move/retarget the find_spec-cache test `tests/_eval/test_init_sample_assistant_internal.py`.

### 2. Providers
`_openai_responses.py`:
- `init_sample_openai_assistant_internal(value: JsonValue | None = None)` — None → `.set(_AssistantInternal())`; else populate current instance (`tool_calls.update(cast(...))`, same for `server_tool_uses`).
- `dump_openai_assistant_internal() -> JsonValue | None` — shallow dict copies; `None` if both empty.

`anthropic.py`: same pair (`init_sample_anthropic_assistant_internal(value=None)`, `dump_anthropic_assistant_internal()`). Format:
```json
{
  "thinking_blocks": {...},
  "tool_call_internal_names": {...},
  "server_mcp_tool_uses": {"id": [use, result]},
  "spans": [{"blocks": [...], "content_ids": [...], "open_use_ids": [...]}],
  "server_tool_spans": {"msg_id": [span_index, ...]},
  "server_tool_span_index": {"content_id": span_index}
}
```
`spans` is an `id()`-deduped table; the two maps hold integer indices → object identity (shared spans, index-only spans from `index_server_tool_spans`) survives the round-trip. No runtime validation on load — values are opaque provider wire dicts, `cast` only (corrupt data surfaces at request time, same as today's in-memory path).

### 3. Checkpoint layout (`util/_checkpoint/_layout/host_context.py`)
- Constant `ASSISTANT_INTERNAL = "assistant_internal.json"`.
- `HostContext.assistant_internal: JsonValue | None = None` (absent file → None — same convention as `agent_state`; old checkpoints keep working).
- Extend `read()` + module docstring.

### 4. Write path (`util/_checkpoint/checkpointer_impl.py` `_write_host_context`, ~541)
- `value = dump_sample_assistant_internal()`; if not None, write atomically alongside `store.json` (reuse existing atomic-write/json helpers in that function). ContextVar read is correct from fire tasks (children inherit context).

### 5. Hydrate (`util/_checkpoint/hydrate.py`)
- `_HostHydrationResult.assistant_internal: JsonValue | None = None`; populate in `_load_host_state` from `HostContext`. No change to `_push_host_state`.

### 6. Restore (`checkpointer_impl.py` `_CheckpointerSetup.__aenter__`, after `hydrate()` returns, ~line 128)
- `if result.host.assistant_internal is not None: init_sample_assistant_internal(result.host.assistant_internal)`.
- Fresh runs / old checkpoints: value None → no-op (run.py already init'd). `resume_for_scoring`: restores like any resume.

## Tests (`tests/checkpoint/`, plus provider tests)

- Per-provider serde round-trip units: dump → json.dumps/loads → init(value) → assert equality incl. anthropic tuple restoration and span identity (`spans map entry is index entry`). Guard with existing skip-if-no-provider markers.
- Aggregate: empty → None; round-trip both providers.
- Fire writes `assistant_internal.json` when populated / skips when empty — follow `_patch_sample_runtime` + `_CountingCheckpointer` patterns in `test_checkpointer.py`.
- `host_context.read()` picks up the file; absent → None.
- Scorer-visibility regression: init fresh in outer context, restore-with-value inside a child task scope, assert outer `assistant_internal()` sees restored data (pins the mutate-in-place semantics).

## Verification

1. `pytest tests/checkpoint tests/_eval/test_init_sample_assistant_internal.py` (moved), plus new provider serde tests.
2. `mypy --exclude tests/test_package src tests`; `ruff format && ruff check --fix`.
3. E2E (docker, manual): run `examples/checkpoint_ctf.py` with an Anthropic model + thinking past a checkpoint, kill, resume — confirm `assistant_internal.json` in `context/`, and resumed generate requests include replayed `thinking` blocks (trace logs).

## Resolved decisions

- Skip file when state empty (dump → None).
- Serialize `open_use_ids` (spans can be indexed while open; cheap).
- Shallow copies at dump — recorded params are write-once.
- No load validation (opaque wire payloads; SDK version skew tolerated as with any wire dict).
