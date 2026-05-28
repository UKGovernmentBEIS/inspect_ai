# Background Subagent Dispatch for `deepagent()`

## Context

Inspect's `deepagent()` today dispatches subagents **synchronously**: when the model calls the `agent` tool (the multiplexer in `src/inspect_ai/agent/_deepagent/agent_tool.py`), the parent blocks until the child returns its final assistant message. This is a real limitation for evals where the parent has independent work it could be doing while a long-running subagent grinds — research-style agents launching multiple independent investigations, coding agents that want to kick off a verification subtask while continuing to draft, and so on. The design RFC (`design/deepagents.md`) explicitly defers this as "out of scope for v1."

Survey of five comparable scaffolds (Claude Code, Codex CLI, OpenCode, LangChain `deepagents`, Pydantic AI `deepagents`) shows background dispatch is now table stakes — all five ship some form, with handle/poll/wait/cancel lifecycle tools and either pull-based polling or completion-notification injection. Codex CLI has the most complete surface (`spawn_agent`, `wait_agent`, `list_agents`, `close_agent`, `send_message`, `followup_task`); Pydantic ships the cleanest semantic split (`task` / `check_task` / `wait_tasks` / `soft_cancel_task` / `hard_cancel_task`).

This plan adds background dispatch to Inspect's `deepagent()` with the **minimum useful surface**, leveraging Inspect's existing primitives — particularly `inspect_ai.util._background.background()` for sample-scoped concurrency, anyio `Event` and `CancelScope` for synchronisation, and the existing span/timeline infrastructure (which already supports concurrent open spans via `_current_span_id` ContextVar at `src/inspect_ai/util/_span.py:86`).

## Design overview

**Parent tool gains a parameter.** The existing `agent` tool grows a `background: bool = False`. When `True`, the call returns *immediately* with a friendly handle like `AGENT-1` and the child runs concurrently on the sample's task group.

**Three new lifecycle tools** added to the deepagent's top-level tool list:
- `agent_status(agent_id)` — instant, returns status + (for completed) full result, (for running) soft peek (message count, tool-call count, elapsed seconds, last assistant message truncated to ~2000 bytes).
- `agent_wait(agent_ids, mode="any"|"all", timeout=None)` — blocks; returns same shape per id.
- `agent_cancel(agent_id)` — fires cancel scope, returns current status; idempotent on terminal agents.

**No `agent_list` enumeration tool** — matching Claude Code's explicit stance that the model should hold IDs in conversation.

**Lifetime semantics: abandon on parent exit.** Background children spawn via `background()` onto `sample.tg`. When the parent's `react()` loop returns, in-flight children continue under the sample until they complete or the sample itself ends (at which point anyio cancels them). The parent does *not* drain.

**Concurrency cap.** New `max_background: int = 8` parameter on `deepagent()`. When at cap, `agent(background=True)` raises `ToolError("Max 8 background agents reached; call agent_wait or agent_cancel to free a slot.")`. Reject — do not block.

**Handle naming.** Per-deepagent monotonic `AGENT-N` counter. Friendly to the model; the existing `agent_span_id` shortuuid stays for log-viewer correlation. Counter never reuses — `AGENT-1` finishing does not free the name `AGENT-1`. Completed/errored/cancelled futures remain in the registry for the sample's lifetime so the model can re-check them; only *running* futures count toward the cap.

**Registry isolation.** A per-deepagent `BackgroundRegistry` is held in a module-level `ContextVar`, set/reset in `deepagent.execute()` using the established `token = var.set(...); try/finally: var.reset(token)` idiom from `src/inspect_ai/util/_span.py:86,109`. Nested deepagents get isolated `AGENT-N` namespaces automatically because ContextVars carry per-task semantics.

**Limits.** `background()` uses `sample.tg.start_soon`, which copies the current ContextVar context per PEP 567. Sample-level token/cost/message/time limits propagate via the shared `_LimitNode` references in `src/inspect_ai/util/_limit.py` (counters live on shared limit objects; GIL serialises increments — small overshoot is bounded and acceptable). Per-subagent `sa.limits` continue to be deepcopied per dispatch.

**`fork=True` works with `background=True`** — return value is the final assistant message, so the "parent evolved while child was forked" concern doesn't bite.

## Critical files

| File | Change |
|---|---|
| `src/inspect_ai/agent/_deepagent/agent_tool.py` | Add `AgentFuture` + `BackgroundRegistry` types, ContextVar plumbing, `background` param on `agent()`, `_dispatch_background` + `_run_background`, three lifecycle-tool factories. |
| `src/inspect_ai/agent/_deepagent/deepagent.py` | New `max_background: int = 8` param. ContextVar setup in `execute()` (line 93 area). Append three lifecycle tools to `all_tools` after `agent` (line 162). |
| `src/inspect_ai/agent/_deepagent/prompt.py` | Append background-dispatch discipline paragraph in `build_subagent_dispatch()` (line 85). |
| `src/inspect_ai/agent/_deepagent/__init__.py` | Optional: export the three lifecycle tool factories for power users. |
| `tests/agent/deepagent/test_agent_tool.py` (or new `test_background.py`) | All new tests (see below). |
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

Synchronously: validate registry exists, validate cap (`registry.running_count() < max_background`), allocate handle (`registry.next_id()`), construct `AgentFuture`, register it, then kick off `background(_run_background, future, child_agent, sa, input, span_id, forked, from_message)`. Return the handle string:

```python
return f"Dispatched {agent_id}. Use agent_status({agent_id!r}) or agent_wait([...]) to follow up."
```

The cap check + register is synchronous (no `await` between read and write), so the cooperative scheduler guarantees no race between sibling spawns in parallel-tool-call mode.

### Lifecycle tools

Three plain `@tool` factories in `agent_tool.py`, each reading the registry via `_background_registry.get()`:

- `agent_status_tool()` — `parallel=True`. Looks up future by id; returns `_format_future_status(future)`.
- `agent_wait_tool()` — `parallel=False` (serialise to avoid stacked waits). Validates non-empty `agent_ids`; for `mode="any"` uses an anyio task group with a shared `done_event` that cancels the group on first child completion; for `mode="all"` uses `anyio.move_on_after(timeout)` wrapping a sequential `await f.done.wait()` loop (each already-set event returns instantly). On timeout, returns *honest* status for still-running entries (`status: "running"` with peek).
- `agent_cancel_tool()` — `parallel=True`. Calls `future.cancel_scope.cancel()` (safe from any task per anyio docs); returns the current status dict. No-op on terminal-state futures.

All three return `ToolError("agent_status is only available inside deepagent().")` (etc.) when the ContextVar is unset, and `ToolError(f"Unknown agent id {id!r}.")` when the id doesn't exist.

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

> You can dispatch a subagent in the background with `background=True` on the `agent` tool — the call returns an `AGENT-N` handle immediately while the subagent runs in parallel with your work. While waiting, do useful independent work in the parent context. Use `agent_status(id)` for a quick non-blocking peek. Use `agent_wait([ids], mode="any"|"all", timeout=...)` when you actually need a result before continuing — prefer one `agent_wait` over a polling loop of `agent_status` calls. Use `agent_cancel(id)` when a background agent is no longer useful.

## Implementation phases

**Phase 1 — Registry + background spawn (no lifecycle tools yet)**
- Add `BackgroundRegistry`, `AgentFuture`, ContextVar + helpers in `agent_tool.py`.
- `max_background` param on `deepagent()`; ContextVar setup in `execute()` with `try/finally: reset(token)`.
- `background: bool` param on the `agent` tool's `execute()`; cap check → `ToolError` on overflow.
- `_dispatch_background` + `_run_background` (inline replication of `run()`'s body).
- Tests: basic spawn, cap rejection, sample-level limit propagation across two concurrent children, per-subagent `sa.limits` isolation, abandon-on-sample-end, registry isolation across nested deepagents, counter monotonicity.

**Phase 2 — Lifecycle tools**
- Implement `agent_status_tool`, `agent_wait_tool`, `agent_cancel_tool` in `agent_tool.py`.
- Append them to `all_tools` in `deepagent.execute()` after the `agent` tool (line 162) — always present regardless of `max_background`.
- Add `_format_future_status`, `_peek_messages`, integrate `truncate_string_to_bytes`.
- Tests: `agent_status` running + completed paths, `agent_wait` `any` and `all` modes, `agent_wait` with timeout returns partial honestly, `agent_cancel` terminates a running child, idempotent cancel on terminal state, invalid id ToolError, empty `agent_ids` ToolError, lifecycle tools outside deepagent ToolError, soft peek shape and 2000-byte truncation.

**Phase 3 — Prompt, docs, and design doc update**
- Append background-dispatch paragraph in `build_subagent_dispatch` (`prompt.py:85`).
- Update `_build_agent_description` in `agent_tool.py:172` to mention the `background` parameter.
- Update `design/deepagents.md` "Async / background subagents" section (~line 285) to summarise what shipped.
- Defer `docs/deep-agents.qmd` background section to the broader Phase 10 doc work in the main RFC.
- Tests: prompt-content assertions in `tests/agent/deepagent/test_prompt.py`.

Each phase lands as its own commit with passing tests.

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

