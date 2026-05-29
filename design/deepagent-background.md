# Background Subagent Dispatch for `deepagent()`

## Context

Inspect's `deepagent()` today dispatches subagents **synchronously**: when the model calls the `agent` tool (the multiplexer in `src/inspect_ai/agent/_deepagent/agent_tool.py`), the parent blocks until the child returns its final assistant message. This is a real limitation for evals where the parent has independent work it could be doing while a long-running subagent grinds — research-style agents launching multiple independent investigations, coding agents that want to kick off a verification subtask while continuing to draft, and so on. The design RFC (`design/deepagents.md`) explicitly defers this as "out of scope for v1."

Survey of five comparable scaffolds (Claude Code, Codex CLI, OpenCode, LangChain `deepagents`, Pydantic AI `deepagents`) shows background dispatch is now table stakes — all five ship some form, with handle/poll/wait/cancel lifecycle tools and either pull-based polling or completion-notification injection. Codex CLI has the most complete surface (`spawn_agent`, `wait_agent`, `list_agents`, `close_agent`, `send_message`, `followup_task`); Pydantic ships the cleanest semantic split (`task` / `check_task` / `wait_tasks` / `soft_cancel_task` / `hard_cancel_task`).

This plan adds background dispatch to Inspect's `deepagent()` with the **minimum useful surface**, leveraging Inspect's existing primitives — particularly `inspect_ai.util._background.background()` for sample-scoped concurrency, anyio `Event` and `CancelScope` for synchronisation, and the existing span/timeline infrastructure (which already supports concurrent open spans via `_current_span_id` ContextVar at `src/inspect_ai/util/_span.py:86`).

## Design overview

**Parent tool gains a parameter.** The existing `agent` tool grows a `background: bool = False`. When `True`, the call returns *immediately* with a friendly handle like `AGENT-1` and the child runs concurrently on the sample's task group.

**Four new lifecycle tools** added to the deepagent's top-level tool list:
- `agent_status(agent_id)` — instant, returns status + (for completed) full result, (for running) soft peek (message count, tool-call count, elapsed seconds, last assistant message truncated to ~2000 bytes).
- `agent_wait(agent_ids, mode="any"|"all", timeout=None)` — blocks; returns same shape per id.
- `agent_cancel(agent_id)` — fires cancel scope, returns current status; idempotent on terminal agents.
- `agent_list(status_filter=None)` — enumerates all agents in the registry (matching `status_filter` if given, one of `"running"`, `"completed"`, `"errored"`, `"cancelled"`). Returns a list of the same status dicts as `agent_status`. Three of five surveyed scaffolds ship enumeration (Codex `list_agents`, LangChain `list_async_tasks`, Pydantic `list_active_tasks`); Claude Code's "model holds IDs in conversation" stance breaks down under compaction (see Phase 4).

**Lifetime semantics: abandon on parent exit.** Background children spawn via `background()` onto `sample.tg`. When the parent's `react()` loop returns, in-flight children continue under the sample until they complete or the sample itself ends (at which point anyio cancels them). The parent does *not* drain.

**Top-level switch + cap, unified.** New `background: bool | int = True` parameter on `deepagent()`:
- `True` (default): enabled with default cap of 8.
- `False`: disabled — the `agent` tool's parameter schema does not include `background`, and the four lifecycle tools (`agent_status`, `agent_wait`, `agent_cancel`, `agent_list`) are absent from the top-level tool list. Returns deepagent to today's synchronous-only surface.
- Positive `int` (e.g. `background=4`): enabled with that as the cap.
- `0` or negative: `ValueError` — for "disabled" pass `False` explicitly.

Resolves internally to `(background_enabled: bool, max_background: int)` — the registry continues to store `max_background: int`. Validation order matters: `is True` / `is False` must be checked before `isinstance(..., int)` because Python's `bool` is a subclass of `int`.

When at cap, `agent(background=True)` raises `ToolError("Max N background agents reached; call agent_wait or agent_cancel to free a slot.")`. Reject — do not block.

**Handle naming.** Per-deepagent monotonic `AGENT-N` counter. Friendly to the model; the existing `agent_span_id` shortuuid stays for log-viewer correlation. Counter never reuses — `AGENT-1` finishing does not free the name `AGENT-1`. Completed/errored/cancelled futures remain in the registry for the sample's lifetime so the model can re-check them; only *running* futures count toward the cap.

**Registry isolation.** A per-deepagent `BackgroundRegistry` is held in a module-level `ContextVar`, set/reset in `deepagent.execute()` using the established `token = var.set(...); try/finally: var.reset(token)` idiom from `src/inspect_ai/util/_span.py:86,109`. Nested deepagents get isolated `AGENT-N` namespaces automatically because ContextVars carry per-task semantics.

**Limits.** `background()` uses `sample.tg.start_soon`, which copies the current ContextVar context per PEP 567. Sample-level token/cost/message/time limits propagate via the shared `_LimitNode` references in `src/inspect_ai/util/_limit.py` (counters live on shared limit objects; GIL serialises increments — small overshoot is bounded and acceptable). Per-subagent `sa.limits` continue to be deepcopied per dispatch.

**`fork=True` works with `background=True`** — return value is the final assistant message, so the "parent evolved while child was forked" concern doesn't bite.

## Critical files

| File | Change |
|---|---|
| `src/inspect_ai/agent/_deepagent/agent_tool.py` | Add `AgentFuture` + `BackgroundRegistry` types, ContextVar plumbing, `background` param on `agent()`, `_dispatch_background` + `_run_background`, four lifecycle-tool factories. Expose `active_background_agents()` reader (consumed by the Phase 4 `on_continue` reminder). |
| `src/inspect_ai/agent/_deepagent/deepagent.py` | New `background: bool \| int` param (resolves internally to `background_enabled` + `max_background`). When enabled: ContextVar setup in `execute()`, append four lifecycle tools to `all_tools` after `agent`, and wrap `on_continue` with the Phase 4 reminder composer. When disabled: pass `background_enabled=False` through to `agent_tool()` so the `background` parameter is omitted from the schema; skip ContextVar setup, lifecycle tools, and the `on_continue` wrapper. |
| `src/inspect_ai/agent/_deepagent/prompt.py` | Append background-dispatch discipline paragraph in `build_subagent_dispatch()` (line 85). |
| `src/inspect_ai/agent/_deepagent/__init__.py` | Optional: export the four lifecycle tool factories for power users. |
| `src/inspect_ai/agent/_deepagent/lifecycle_tools.py` (or new `background_reminder.py`) | Phase 4: `background_reminder_message(futures)` passive formatter, `REMINDER_INTERVAL` constant, `_used_background_tool(state)` helper. |
| `tests/agent/deepagent/test_agent_tool.py` (or new `test_background.py`) | All new lifecycle/dispatch/reminder tests. |
| `tests/agent/deepagent/test_prompt.py` | Add prompt-content assertions for the new paragraph. |
| `design/deepagents.md` | Update the "Async / background subagents" section (~line 285) to reflect that this shipped. |
| `docs/deep-agents.qmd` | Add a background-dispatch section once Phase 10 doc work lands. |

**Files explicitly NOT changed:**
- `src/inspect_ai/agent/_run.py` — we replicate its ~15-line body inline in `_run_background` (see below); no new public hook.
- `src/inspect_ai/util/_background.py` — its existing API is sufficient.
- `src/inspect_ai/util/_limit.py` — propagation works via PEP 567 contextvar copy; no changes needed.
- `src/inspect_ai/agent/_deepagent/subagent.py` — `Subagent` config is orthogonal to dispatch mode.

## Key implementation details

### `AgentFuture` and `BackgroundRegistry` (in `agent_tool.py`)

```python
@dataclass
class AgentFuture:
    agent_id: str                                    # "AGENT-1"
    span_id: str                                     # existing shortuuid
    subagent_name: str                               # e.g. "research"
    status: Literal["running", "completed", "errored", "cancelled"]
    result: str | None = None
    error: str | None = None
    done: anyio.Event = field(default_factory=anyio.Event)
    cancel_scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    started_at: float = field(default_factory=anyio.current_time)
    child_state: AgentState | None = None            # populated as child runs

@dataclass
class BackgroundRegistry:
    max_background: int
    counter: int = 0
    futures: dict[str, AgentFuture] = field(default_factory=dict)

    def next_id(self) -> str:
        self.counter += 1
        return f"AGENT-{self.counter}"

    def running_count(self) -> int:
        return sum(1 for f in self.futures.values() if f.status == "running")

_background_registry: ContextVar[BackgroundRegistry | None] = ContextVar(
    "_background_registry", default=None
)
```

### `_run_background` — inline replication of `run()`

`src/inspect_ai/agent/_run.py:36-104` constructs the `AgentState` internally and never exposes a live reference, so we can't wrap `run()`. Replicate inline (~15 lines mirroring `_run.py:69-104`):

```python
async def _run_background(
    future: AgentFuture,
    child_agent: Agent,
    sa: Subagent,
    input: str | list[ChatMessage],
    span_id: str,
    forked: bool,
    from_message: str | None,
) -> None:
    from copy import copy, deepcopy
    from inspect_ai.util._limit import apply_limits
    from inspect_ai.util._span import AGENT_SPAN_TYPE, span
    from inspect_ai.event._timeline import timeline_branch

    try:
        with future.cancel_scope:
            input_messages = _coerce_to_messages(copy(input))
            state = AgentState(messages=input_messages)
            future.child_state = state              # live reference for peek
            limits = deepcopy(sa.limits) if sa.limits else []
            with apply_limits(limits, catch_errors=True) as limit_scope:
                async with span(name=sa.name, type=AGENT_SPAN_TYPE, id=span_id):
                    if forked:
                        async with timeline_branch(name=sa.name, from_anchor=from_message):
                            state = await child_agent(state)
                    else:
                        state = await child_agent(state)
            if limit_scope.limit_error is not None:
                future.result = f"Subagent '{sa.name}' stopped: {limit_scope.limit_error.message}"
            else:
                future.result = _extract_result(state)
            future.status = "completed"
    except anyio.get_cancelled_exc_class():
        future.status = "cancelled"
        raise                                       # re-raise so the scope sees it
    except Exception as ex:
        future.status = "errored"
        future.error = f"{type(ex).__name__}: {ex}"
        raise                                       # let background() log it
    finally:
        future.done.set()
```

Note that `anyio.get_cancelled_exc_class()` derives from `BaseException`, not `Exception`, so the cancellation path will not trip `_background.py:62-65`'s "Background worker error" log message.

### Spawn path in `agent()`'s `execute()`

The `agent_tool()` factory takes a new `background_enabled: bool = True` keyword. When True, the inner `execute()` signature accepts `background: bool = False` alongside the existing parameters; when False, the parameter is omitted from the function signature (use two near-identical function definitions, factory selects one — cleaner than dynamic decorator manipulation). Same goes for the tool description text.

When `background=True` is passed (only possible when `background_enabled=True`): validate registry exists, validate cap (`registry.running_count() < max_background`), allocate handle (`registry.next_id()`), construct `AgentFuture`, register it, then kick off `background(_run_background, future, child_agent, sa, input, span_id, forked, from_message)`. Return the handle string:

```python
return f"Dispatched {agent_id}. Use agent_status({agent_id!r}) or agent_wait([...]) to follow up."
```

The cap check + register is synchronous (no `await` between read and write), so the cooperative scheduler guarantees no race between sibling spawns in parallel-tool-call mode.

### Lifecycle tools

Four plain `@tool` factories in `agent_tool.py`, each reading the registry via `_background_registry.get()`:

- `agent_status_tool()` — `parallel=True`. Looks up future by id; returns `_format_future_status(future)`.
- `agent_wait_tool()` — `parallel=False` (serialise to avoid stacked waits). Validates non-empty `agent_ids`; for `mode="any"` uses an anyio task group with a shared `done_event` that cancels the group on first child completion; for `mode="all"` uses `anyio.move_on_after(timeout)` wrapping a sequential `await f.done.wait()` loop (each already-set event returns instantly). On timeout, returns *honest* status for still-running entries (`status: "running"` with peek).
- `agent_cancel_tool()` — `parallel=True`. Calls `future.cancel_scope.cancel()` (safe from any task per anyio docs); returns the current status dict. No-op on terminal-state futures.
- `agent_list_tool()` — `parallel=True`. Optional `status_filter: Literal["running","completed","errored","cancelled"] | None = None`. Iterates the registry's `futures.values()` (insertion order, which is `AGENT-1`, `AGENT-2`, ...), applies the filter, returns `[_format_future_status(f) for f in matching]`. Returns `[]` (not an error) when the registry is empty. Cheap — ~20 lines including the filter parameter.

All four return `ToolError("agent_status is only available inside deepagent().")` (etc.) when the ContextVar is unset, and `ToolError(f"Unknown agent id {id!r}.")` when an id doesn't exist (only applies to `agent_status`, `agent_wait`, `agent_cancel` — `agent_list` doesn't take ids).

### `_format_future_status` and `_peek_messages`

Use `truncate_string_to_bytes` from `src/inspect_ai/_util/text.py:52` (the raw byte-safe truncator) — **not** `truncate_tool_output` from `src/inspect_ai/model/_call_tools.py:1131`, which appends a model-facing "your output was too long" wrapper we don't want.

Defensive snapshot in `_peek_messages`: `messages = list(future.child_state.messages)` before iteration (the child may mutate the list while we read).

Returns:
- `running`: `{agent_id, status, messages_count, tool_calls_count, elapsed_seconds, last_message}` (last_message is the most recent **assistant** message text, truncated to 2000 bytes).
- `completed`: `{agent_id, status, result}`.
- `errored`: `{agent_id, status, error}`.
- `cancelled`: `{agent_id, status}`.

### Prompt addition (in `prompt.py:build_subagent_dispatch`)

Append at the end of the subagent dispatch section:

> You can dispatch a subagent in the background with `background=True` on the `agent` tool — the call returns an `AGENT-N` handle immediately while the subagent runs in parallel with your work. While waiting, do useful independent work in the parent context. Use `agent_status(id)` for a quick non-blocking peek. Use `agent_wait([ids], mode="any"|"all", timeout=...)` when you actually need a result before continuing — prefer one `agent_wait` over a polling loop of `agent_status` calls. Use `agent_cancel(id)` when a background agent is no longer useful. If you may have lost track of background agents — for example after a long stretch of work or after context compaction — call `agent_list()` to recover their state.

## Working through the phases

Follow the convention established in `design/deepagents.md`:

1. **One phase at a time.** Each phase gets its own focused implementation pass. Do not proceed to the next phase without explicit user approval.
2. **Pause for discussion before starting each phase** — confirm the scope and any open design points carry-over from the previous phase.
3. **Run the full test suite at each step.** Every phase ships implementation + tests together.
4. **Pause for code review before committing.** After tests pass, review the diff together. Do not auto-commit.
5. **Update this plan after each completed phase** — replace the phase block with a summary of what was actually built and tested (files created/modified, key implementation decisions, test coverage), matching the format used in `design/deepagents.md` phase summaries.
6. **Then commit** with the user's approval.

## Implementation phases

**Phase 1 — Registry + background spawn (no lifecycle tools yet)**
- Add `BackgroundRegistry`, `AgentFuture`, ContextVar + helpers in `agent_tool.py`.
- `background: bool | int = True` param on `deepagent()`. Resolve to `(background_enabled, max_background)` at the top of `execute()` — check `is True` / `is False` before `isinstance(..., int)`; `0` or negative ints raise `ValueError`. When disabled, skip ContextVar setup entirely and pass `background_enabled=False` through to `agent_tool()`.
- `background_enabled: bool = True` param on `agent_tool()` factory — selects between two near-identical `execute()` function definitions, one with `background: bool` parameter and one without (cleaner than dynamic decorator manipulation; gives the model a parameter schema that accurately reflects what's available).
- ContextVar setup in `execute()` with `try/finally: reset(token)` (only when enabled).
- `background: bool` param on the `agent` tool's `execute()` (background-enabled variant only); cap check → `ToolError` on overflow.
- `_dispatch_background` + `_run_background` (inline replication of `run()`'s body).
- Tests: basic spawn, cap rejection (`background=2` then spawn 3 → third rejects), sample-level limit propagation across two concurrent children, per-subagent `sa.limits` isolation, abandon-on-sample-end, registry isolation across nested deepagents, counter monotonicity, `deepagent(background=False)` produces an `agent` tool whose schema has no `background` parameter and no lifecycle tools surfaced, `deepagent(background=0)` raises ValueError, `deepagent(background=4)` cap matches 4.

**Phase 2 — Lifecycle tools** (refined at implementation planning)

*Implementation notes / corrections to the original sketch:*
- **Return type is a markdown string, not a dict.** `ToolResult` (`src/inspect_ai/tool/_tool.py:35-46`) permits only `str`/scalar/Content — not `dict`. Each lifecycle tool returns a readable **markdown** string. The model reads it directly; the web viewer renders tool-result content as markdown so it displays nicely there too. (Original sketch said "return a dict" / JSON — superseded.)
- **Custom `ToolCallViewer`s** give each *call* line a clean title (e.g. `agent_status: AGENT-1`, `agent_wait: AGENT-1, AGENT-2 (all)`, `agent_cancel: AGENT-1`, `agent_list` / `agent_list: running`). This mirrors the existing `_agent_viewer` (`agent_tool.py`). Note the `ToolCallViewer` contract is `Callable[[ToolCall], ToolCallView]` (`_tool_call.py:93`) — it only sees the **call** (args), not the result. So the viewer governs the call line; the markdown return value governs the result body (rendered by each viewer's normal tool-result path).
- **New file `src/inspect_ai/agent/_deepagent/lifecycle_tools.py`** holds the four `@tool` factories + their viewers + `_format_future_status` + `_peek_messages`. It imports the registry primitives (`current_background_registry`, `AgentFuture`, `BackgroundStatus`) from `agent_tool.py`. Keeps `agent_tool.py` focused on dispatch; no circular import (lifecycle imports from agent_tool, not vice versa).

*Tools (all return markdown `str`):*
- `agent_status(agent_id)` — `parallel=True`. Markdown block for one agent. `ToolError` on unknown id / no registry. Viewer title `agent_status: {agent_id}`.
- `agent_wait(agent_ids, mode="any"|"all"=", timeout=None)` — `parallel=False`. Validates non-empty ids + each exists + valid mode. `any`: anyio task group, first `done` cancels the group. `all`: `anyio.move_on_after(timeout)` over sequential `await f.done.wait()`. On timeout returns honest per-agent markdown (running entries include the live peek). Joins per-agent blocks. Viewer title `agent_wait: {ids} ({mode})`.
- `agent_cancel(agent_id)` — `parallel=True`. Fires `future.cancel_scope.cancel()` (safe cross-task per anyio); idempotent no-op on terminal futures. Returns the post-cancel markdown block. Viewer title `agent_cancel: {agent_id}`.
- `agent_list(status_filter=None)` — `parallel=True`. Markdown list of agents in `AGENT-N` insertion order. `"No background agents."` (not an error) when empty. Viewer title `agent_list` / `agent_list: {filter}`.

*Status markdown (`_format_future_status(future) -> str`), one block per agent:*
- running: header `**AGENT-1** (research) — running`, then bullet lines: elapsed seconds, message count, tool-call count, and `latest:` = the most recent **assistant** message text, truncated to 2000 bytes via `truncate_string_to_bytes` (`_util/text.py:52`). Defensive `list(future.child_state.messages)` snapshot; handle `child_state is None` (init window) → zero counts / empty latest.
- completed: header + the result text below.
- errored: header + the error text.
- cancelled: header only.

`agent_wait` / `agent_list` join multiple blocks with a blank line + `---` separator.

*Wiring:* append the four tools to `all_tools` in `deepagent.execute()` immediately after the `agent` tool, **only when `background_enabled`** (consistent with the `background=False` switch hiding the whole surface — corrects the original "always present" note). This also makes the Phase 1 cap-error message (which names `agent_wait`/`agent_cancel`) accurate, since those tools exist exactly when background dispatch is reachable.

*Tests* (`tests/agent/deepagent/test_background.py`, reuse Phase 1's per-subagent mockllm + `_block_helper` pattern):
- `agent_status` running (peek content) + completed (result) paths
- `agent_wait` `any` returns on first, `all` waits for both, timeout returns honest partial
- `agent_cancel` terminates a running child; idempotent on already-terminal
- `agent_list` empty / populated / status_filter
- invalid id → ToolError; empty `agent_ids` → ToolError; tools when `background=False`/no registry → ToolError
- soft-peek `latest` truncated to ≤2000 bytes
- viewer titles render expected strings from call args
- Phase 1's deferred `_wait_test_helper` e2e re-expressed against real `agent_wait`/`agent_status`.

---

**Phase 2 — SHIPPED.** Files: new `src/inspect_ai/agent/_deepagent/lifecycle_tools.py` (four `@tool` factories + viewers + `_format_future_status`/`_peek_messages`/`_format_many`/`_require_registry`/`_require_future`); `deepagent.py` appends the four tools to `all_tools` only when `background_enabled`; `agent_tool.py` gained a module `logger`. 24 new tests in `test_background.py` (168 deepagent tests pass total; ruff + mypy clean).

Two correctness fixes surfaced by Phase 2 tests — both real bugs in Phase 1's `_run_background`:
1. **Background errors must not kill the sample.** A subagent raising an `Exception` re-raised through `background()` → `sample.tg` → failed the whole sample. Fixed: `_run_background` now *swallows* non-cancellation exceptions after recording `status="errored"` + `error` on the future (surfaced via `agent_status`/`agent_wait`) and `logger.warning`s. Only `CancelledError` re-raises (structured concurrency).
2. **`agent_cancel` reported stale `running`.** An anyio `CancelScope` *absorbs* its own cancellation at the `with` boundary, so the `except CancelledError` never fired for an `agent_cancel`-initiated cancel — status stayed `running`. Fixed: detect via `future.cancel_scope.cancelled_caught` *after* the `with` block and set `status="cancelled"`. The separate `except CancelledError` now handles only *outer* (sample-teardown) cancellation, which propagates through the inner scope. `agent_cancel` also now `await`s `future.done` after firing the cancel so its returned block reflects the settled state.

**Phase 3 — Prompt, docs, and design doc update**
- Append background-dispatch paragraph in `build_subagent_dispatch` (`prompt.py:85`).
- Update `_build_agent_description` in `agent_tool.py:172` to mention the `background` parameter.
- Update `design/deepagents.md` "Async / background subagents" section (~line 285) to summarise what shipped.
- Defer `docs/deep-agents.qmd` background section to the broader Phase 10 doc work in the main RFC.
- Tests: prompt-content assertions in `tests/agent/deepagent/test_prompt.py`.

**Phase 4 — Periodic background-agent reminder (via `on_continue`)**

**Goal.** Keep the parent model aware of its running background agents — both after context compaction drops the `AGENT-N` handles from its view *and* in the ordinary course of a long trajectory where it simply forgets it dispatched something. Solve both with one mechanism that is fully decoupled from compaction.

**Why not the compaction route (superseded).** The original Phase 4 plan hooked the compaction loop (`_compaction.py:263-273`, mirroring the memory warning) and read the registry via a `model._compaction → agent._deepagent` import. Two problems killed it: (1) it only covers the compaction-induced loss, not plain forgetting; (2) reaching the registry from compaction is awkward — a direct inverted import is benign but layering-reversing, and the "pluggable hook" alternative is actually *worse* (a global registry of ContextVar-readers duplicates/cross-contaminates across concurrent deepagent samples; to be correct it must hold the provider in a ContextVar, at which point it collapses back into the direct read). Research confirms no surveyed scaffold (Claude Code, Codex CLI, OpenCode, LangChain, Pydantic) does *any* automatic injection — they all rely on an on-demand list tool, and Claude Code users are filing the post-compaction-recovery gap as a bug (issues #34663, #29751). So proactive injection is novel, and `on_continue` is the cleaner home for it.

**Design: a forgetting *backstop*, not a periodic nag.** `react()` invokes `on_continue` on every loop iteration with `state` in hand (`_react.py:326-327`), so deepagent can do everything locally — the registry ContextVar is natively in scope, no cross-package dependency, no `_compaction.py` change at all. Cadence is interaction-gated:

- Maintain a per-sample turn counter (closure var in `deepagent.execute()`).
- Each `on_continue` turn: if the latest assistant turn used a background tool (`agent_status` / `agent_wait` / `agent_cancel` / `agent_list`, or an `agent` call with `background=True`), **reset the counter to 0** — an engaged model is never nagged. Otherwise increment.
- When the counter reaches `REMINDER_INTERVAL` (default **5**) *and* `active_background_agents()` is non-empty, append a passive reminder `ChatMessageUser` and reset the counter.

This fires only after N turns of *ignoring* background agents, which is exactly (and only) the failure mode — forgetting. It covers compaction for free: post-compaction the model can't interact (handles gone from view), so the counter climbs and the reminder fires within N turns.

**Over-prompting mitigations** (the reminder must read as ambient awareness, not a call to action — otherwise the model over-polls and defeats the point of backgrounding):
- **Passive framing**, e.g.: *"[Automatic reminder — no action needed.] Background agents still running: AGENT-1 (research, 52s). Keep working; use `agent_wait` only when you actually need a result."*
- **Terse content** — one line per agent (`id (name, status, elapsed)`), **not** the full peek (last message / counts stay in `agent_status` for when the model deliberately asks).
- **Completed agents get a light, appropriate nudge** — "AGENT-2 (general): completed — collect via `agent_status('AGENT-2')`" — since uncollected results are wasted work. Running agents are explicitly "no action needed."
- The interaction-gated counter is itself the primary mitigation: a model already managing its agents never sees the reminder.

**Files:**
| File | Change |
|---|---|
| `src/inspect_ai/agent/_deepagent/deepagent.py` | When `background_enabled`, wrap the `on_continue` passed to `react()` in a reminder-injecting composer (per-sample counter in the `execute()` closure). When disabled, pass `on_continue` through unchanged. |
| `src/inspect_ai/agent/_deepagent/lifecycle_tools.py` (or new `background_reminder.py`) | `background_reminder_message(futures: list[AgentFuture]) -> ChatMessageUser` (terse, passive formatter) + `REMINDER_INTERVAL` constant + a `_used_background_tool(state) -> bool` helper that scans the latest assistant turn's `tool_calls`. |

Reuse `active_background_agents()` (`agent_tool.py:151`, returns `list[AgentFuture]`, `[]` when no registry) — no new reader needed. **No changes to `model/_compaction/` and no `CompactionStrategy` property.**

**`on_continue` composition (preserve existing semantics).** The wrapper must replicate `react()`'s handling of the three `on_continue` forms so behavior is unchanged when no agents are active:
- `None` → behave as default (`return True`).
- `str` → return the string **only when the latest turn had no tool calls** (matches `_react.py:354-359`, which injects a str-continue only on a stop); otherwise `return True`. Returning a str unconditionally would change behavior (`_react.py:338` appends it even after tool calls).
- callable → `await` it and pass through its result.
- Inject the reminder into the *result's* `AgentState` when the callable returns one (it replaces `state.messages` at `_react.py:347-349`); otherwise into `state.messages`. Then apply the counter/return logic.

**Tests** (`tests/agent/deepagent/test_background.py`, reuse per-subagent mockllm + `_block_helper`):
- Reminder fires after `REMINDER_INTERVAL` turns of no interaction when an agent is running; message content includes the running agent's id/name and a "no action needed" framing.
- Counter resets on a lifecycle-tool call (`agent_status`/etc.) and on `agent(background=True)` — reminder does *not* fire while the model is actively managing agents.
- No reminder when the registry is empty / `background=False` (zero injection in the common case).
- Completed agent surfaces the "collect via `agent_status`" line; running agent does not.
- Composition: a user-supplied `str` `on_continue` still injects only on a stop turn; a callable `on_continue` returning `True`/`str`/`AgentState` is honored and the reminder rides along.
- Unit test `_used_background_tool` and `background_reminder_message` directly.

Each phase lands as its own commit with passing tests. Phase 4 is independent of compaction and can ship in the same PR series.

## Verification

End-to-end verification after Phase 2:
1. `pytest tests/agent/deepagent/ -v` — full deepagent test suite passes.
2. Targeted: `pytest tests/agent/deepagent/test_agent_tool.py::TestBackgroundDispatch tests/agent/deepagent/test_agent_tool.py::TestLifecycleTools -v`.
3. Manual eval: a small `deepagent()` task with mockllm that exercises spawn → other work in parent → wait → result.
4. `mypy --exclude tests/test_package src tests` clean.
5. `ruff format` + `ruff check --fix` clean.
6. After implementation, verify in the log viewer that an in-flight background agent renders as an open span/swimlane alongside the parent's continuing activity (the existing infrastructure supports this; verify nothing breaks visually).

## Risks and open items

1. **Cap-check race.** Two parallel `agent(background=True)` calls could both observe the count below cap. The check + registry insert is purely synchronous (no `await` between them), so cooperative scheduling guarantees atomicity. Document this clearly in code.
2. **`future.child_state` initialisation window.** Brief gap between `background()` kickoff and `_run_background` setting `child_state`. `_peek_messages` handles `None` by returning zero counts / empty `last_message`.
3. **Log viewer rendering.** Concurrent in-flight spans are infrastructurally supported (`_current_span_id` is a ContextVar; `_tree.py:43-91` buckets by `parent_id`, no ordering constraint). Verify visually after implementation; no code changes anticipated.
4. **Per-sample contextvar lifetime.** `BackgroundRegistry` is held by the ContextVar in `deepagent.execute()`. If a nested deepagent is run as a subagent of another deepagent, the inner gets its own registry — correct. If the outer deepagent's `execute()` returns while inner background children are still running on the *outer's* registry... they're already disconnected (each `execute()` has its own scope). Verify in test #9.
5. **Phase 4 is decoupled from compaction (revised approach).** The reminder lives entirely in deepagent via `on_continue` — no `model._compaction` change, no cross-package import. This supersedes the earlier compaction-hook design, which (a) covered only compaction-induced loss, not plain forgetting, and (b) had a messy registry-access story (a direct inverted import reverses layering; a "pluggable hook" of ContextVar-readers duplicates across concurrent samples and collapses back into the direct read once made correct).
6. **Over-prompting.** A periodic status injection risks making the model over-poll/wait on background agents and abandon its main work. Mitigated by (a) the interaction-gated counter (an engaged model that touches any `agent_*` tool resets the counter and never sees a reminder), (b) passive "no action needed" framing, and (c) terse content (no peek). Validate the framing doesn't induce premature `agent_wait` in tests.
7. **Reminder staleness / cadence.** `REMINDER_INTERVAL=5` is a fixed constant for v1 (not user-configurable). Elapsed times in a reminder are a point-in-time snapshot; the model gets fresh data from `agent_status` on demand. Revisit exposing the interval if real evals show 5 is too sparse/frequent.
8. **`on_continue` composition.** Wrapping a user-supplied `on_continue` must preserve `react()`'s str/None/callable/AgentState semantics (see Phase 4 "composition" note); the wrapper injects the reminder as a side effect on the correct target state. Covered by composition tests.

---

## Phase 5 — Comprehensive Test Coverage Hardening

### Context

Phases 1–4 shipped with 49 tests, but a full audit (implementation surface vs. test inventory, verified against the file) found gaps in exactly the async/concurrency and safety-critical areas that matter most before field use. Two are acute: (a) **limit propagation into background subagents is unverified** — this was an explicit Phase 1 requirement ("limits should still be checked inside `background()` — verify that"); the test file only ever sets `message_limit` on the parent Task. (b) **The Phase 2 bug fix — a background exception must not kill the sample — has no regression test.** Other gaps cover untested branches (`fork=True`+background, `agent_wait` partial timeouts, errored/cancelled formatting, `on_continue` returning `AgentState`/`False`). Goal: close every verified gap that can be tested deterministically; document the rest. All tests go in `tests/agent/deepagent/test_deepagent_background.py` reusing its per-subagent-mockllm + `_eval_deepagent` + `_block_helper` patterns.

### New test helpers (top of the test file)

- `_build_erroring_subagent(name)` — subagent whose own mockllm `custom_outputs` is a callable that raises `RuntimeError` during generate (so the failure originates inside the background child's `react`). `RuntimeError` is an `Exception` (not `BaseException`), so it exercises the swallow-and-record path in `_run_background` (`agent_tool.py:623-632`), not the cancellation path.
- `_build_limited_subagent(name, limits)` — subagent with `limits=[...]` (e.g. `token_limit(1)`) plus a normal submit output, to trigger the `apply_limits(catch_errors=True)` → `"Subagent '…' stopped: …"` result path (`agent_tool.py:604-607`).
- Reuse `check_limit_event` / `find_limit_event` from `tests/test_helpers/limits.py`, `token_limit`/`time_limit` from `inspect_ai.util`, and existing `_build_blocking_subagent` / `_build_submit_subagent` / `_wait_test_helper`.

### Tier 1 — correctness-critical (new classes)

- **`TestBackgroundLimits`**
  - *sa.limits enforced inside background* — dispatch `_build_limited_subagent("capped", [token_limit(1)])` in background; wait; assert its result/status reflects `"stopped"` (limit checked inside the background child). Directly verifies the Phase 1 limits requirement.
  - *usage/contextvar propagation* — dispatch a background child that records model usage; after eval, assert the child's usage appears in `log.stats.model_usage` (proves the child ran under the sample's accounting context that limits share — the PEP 567 contextvar copy works). Deterministic; avoids racy overshoot-timing assertions.
- **`TestBackgroundErrors`**
  - *error does not kill the sample* — dispatch `_build_erroring_subagent`; parent waits then submits; assert `log.status == "success"`, the future is `errored`, and the error text is surfaced via `agent_status`/`_wait_test_helper`. Regression test for the Phase 2 fix.
- **`TestForkedBackground`**
  - *fork=True + background=True* — a `fork=True` subagent dispatched in background (parent has conversation history via `get_messages`); assert it completes with its result. Exercises the untested `timeline_branch` forked branch in `_run_background` (`agent_tool.py:596-602`).
- **`TestAbandonOnExit`**
  - *parent exits while child running* — spawn a blocking child, parent submits immediately without waiting; assert `log.status == "success"` and the parent did not block on the child (last action is submit; test completes well under the child's 60s sleep — a hang would trip the 300s test timeout). Note the primitive-level teardown/cancellation is already covered by `tests/util/test_background.py::test_background_termination`; this asserts the deepagent-level integration.

### Tier 2 — async edge branches (extend existing classes / small new ones)

- **`agent_wait` partial timeouts** (extend `TestAgentWait`): `mode="all"` with one completed + one blocking at `timeout=0.2` → both blocks returned honestly (one completed, one running); `mode="any"` with two blocking at `timeout=0.2` → returns after timeout with both shown running (exercises the task-group + `move_on_after` partial paths, `lifecycle_tools.py:240-253`). Short timeout vs 60s blockers → low flake risk.
- **Formatter branches** (extend `TestFormatStatusUnit`): `_format_future_status` on an **errored** future (shows error text) and a **cancelled** future (header only) — `lifecycle_tools.py:99-103`.
- **`on_continue` composition** (extend `TestReminderE2E`): a callable `on_continue` returning a fresh **`AgentState`** → reminder appended to that state's messages (`lifecycle_tools.py:461-462`); a callable returning `True`×4 then **`False`** at the interval turn → reminder suppressed and loop ends (`lifecycle_tools.py:448-449`).
- **Errored/cancelled display e2e** (extend `TestAgentStatus`/`TestAgentList`): `agent_status` and `agent_list` show an **errored** agent (reuse `_build_erroring_subagent`) and a **cancelled** agent (spawn blocking → `agent_cancel` → list).

### Tier 3 — document / verify (no fragile tests)

- **Cap-check race**: keep as a documented invariant (already Risk #1) — add a one-line code comment at the cap-check/insert site in `_dispatch_background` noting the no-`await`-between-read-and-write atomicity and that v1 tool execution is sequential. No test.
- **Trio backend**: run the async *unit* tests under `--runtrio` (`pytest tests/agent/deepagent/test_deepagent_background.py --runtrio`); if any rely on asyncio-specifics, annotate with `@skip_if_trio` (from `test_helpers.utils`). Confirms the anyio primitives (`Event`, `CancelScope`, `move_on_after`) behave under both backends.

### Verification

1. `pytest tests/agent/deepagent/test_deepagent_background.py -v` — all (existing + new) pass under asyncio.
2. `pytest tests/agent/deepagent/test_deepagent_background.py --runtrio` — async unit tests pass under trio (or are explicitly skipped).
3. `pytest tests/agent/deepagent/ -q` — full deepagent suite green.
4. `ruff format` + `ruff check --fix` + `mypy --exclude tests/test_package src tests` clean (the last confirms no new duplicate-module / typing regressions).
5. Sanity: each new Tier-1 test, when its production guard is reverted locally, should fail (i.e. the tests actually exercise the safety property) — spot-check the errored-doesn't-kill-sample and sa.limits tests.

