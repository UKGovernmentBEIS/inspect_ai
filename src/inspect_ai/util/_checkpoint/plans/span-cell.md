# Checkpoint spans across task boundaries (`_SpanCell`)

## Problem

The checkpointer wraps the agent's work-between-fires window in a `checkpoint N`
transcript span and rotates it at each fire. Under a normal in-process agent
(react) this works. Under `sandbox_agent_bridge` it produces, per fire:

```
WARNING sample=1 Exiting span created in another context: __aexit__() [contextlib.py:221]
```

and — worse, silently — wrong span parentage and wrong event→span attribution
(details below).

Requirements:

1. Events emitted between fires MUST nest under the current `checkpoint N` span.
2. Checkpoint spans must be siblings (parented under the span current at
   `span_session()` entry), not nested under `checkpoint 1`.
3. One mechanism for all agents. Agent writers use `checkpointer()` as today;
   nothing extra to wire.

## Mechanics

Three facts combine to cause the failure:

1. `span()` (`src/inspect_ai/util/_span.py`) is an `@asynccontextmanager`. Its
   body runs in the `Context` of whichever task awaits `__aenter__`/`__aexit__`.
   `_current_span_id.set()` mutates the *calling task's* context and returns a
   token bound to that specific `Context` object.
2. anyio `tg.start_soon()` snapshots `copy_context()` at spawn. Later `set()`s
   in the parent are invisible to the child; `set()`s in the child never
   propagate up or sideways.
3. `ContextVar.reset(token)` from a different `Context` than the one that
   created the token raises `ValueError` — caught at `_span.py:110`, producing
   the warning (the logged caller is contextlib's `__aexit__`, hence the
   cryptic text).

Every event stamps `span_id = current_span_id()` at construction
(`BaseEvent.model_post_init`, `src/inspect_ai/event/_base.py:48`) — from the
*emitting task's* context.

The checkpointer holds the span cm in instance state
(`_EnteredCheckpointer._current_span_cm`) and drives enter/exit from whichever
task calls `tick()`.

## Task/context hierarchy — normal case (react), works

One task does everything; every set/reset pair lands in the same `Context`:

```
sample task T0 (one Context for the whole agent phase)
└─ react agent coroutine stack — all plain awaits, no task hops
   ├─ checkpointer() __aenter__ → span_session() → span("checkpoint 1").__aenter__
   │     set(ckpt1) in T0's Context, token bound to it
   ├─ loop: generate / execute_tools / await cp.tick()        (_react.py:238)
   │     trigger fires → _fire_once:
   │       _close_current_span → __aexit__ resumes generator IN T0 → reset ✓
   │       _open_next_span → span("checkpoint 2") — parent read from T0 ctx ✓
   └─ span_session() exit → __aexit__ in T0 ✓
```

Tool subtasks inherit `_current_span_id = ckpt-N` at spawn, so their events
stamp the right checkpoint.

## Task/context hierarchy — sandbox bridge, fails

`claude_code()` enters `checkpointer()` *before* `sandbox_agent_bridge()`
(inspect_swe claude_code.py), so the bridge's tasks copy a context where
`ckpt1` is current — and that copy is frozen forever:

```
sample task T0: solver
├─ checkpointer() entered in T0 → "checkpoint 1" opened in T0's Context
└─ sandbox_agent_bridge() in T0:
   └─ anyio task group
      ├─ T1 = run_model_service → sandbox_service poll loop
      │      Context = copy of T0 at spawn → _current_span_id = ckpt1, frozen
      │      └─ per poll batch: tg.start_soon(_handle_request) per request
      │           T2a, T2b, …  Context = copy of T1 → ckpt1, frozen
      ├─ T_monitor = _monitor_proxy
      └─ T0: parks at `yield bridge` (sandbox/bridge.py:190); the
             caller (claude_code) execs the CLI agent in the container

container agent proc → HTTP proxy → file RPC → T1 poll → T2x handler
   └─ inspect_*_api_request → bridge_generate → _track_state → await cp.tick()
```

When the trigger fires inside T2a:

1. `_close_current_span()` resumes the `checkpoint 1` generator in T2a's
   Context. `SpanEndEvent` emits fine, but `reset(token-from-T0)` →
   `ValueError` → the warning. Once more at `span_session()` exit in T0
   (closing a cm opened in some T2x).
2. `_open_next_span()` in T2a reads inherited `ckpt1` as parent →
   **`checkpoint 2` recorded as a child of `checkpoint 1`** (and every later
   checkpoint likewise — each fresh T2x inherits ckpt1 from T1's snapshot).
3. The `set(ckpt2)` lands only in T2a's Context, which dies with the task.
4. Every later event (model events etc. in T2b, T2c, …) stamps
   `span_id = ckpt1` forever. **Rotation never takes effect for attribution.**

This is structural, not a drive-it-from-the-right-task bug: even a dedicated
rotation task can't make its `set()` visible to already-running siblings.
ContextVar *values* can't propagate sideways — but ContextVar *references*
can: every task spawned after `span_session()` entry inherits a reference to
the same object.

## Design: checkpoint span as a shared mutable cell on the span chain

- `_current_span_id` becomes `ContextVar[str | _SpanCell | None]` where
  `_SpanCell` is a private mutable holder with an `id: str` field.
- `current_span_id()` and `span()`'s parent capture unwrap the cell. `span()`
  is otherwise untouched — normal spans still `set()` a plain str in their own
  task, shadowing the cell within their subtree; token discipline unchanged.
- `span_session()` entry (T0): emit `SpanBeginEvent(ckpt-N, parent=resolved
  current)`, then `var.set(_SpanCell(ckpt-N))` — token bound to T0.
- Fire/rotation (any task): emit `SpanEndEvent(cell.id)`, emit
  `SpanBeginEvent(next, parent=session-parent captured at entry)`, mutate
  `cell.id = next`. **No ContextVar set/reset at fire time** — nothing
  straddles contexts; warning gone by construction.
- `span_session()` exit (T0): emit `SpanEndEvent(cell.id)`, `var.reset(token)`
  — same context, valid.

Why it satisfies the requirements: T2x tasks hold a *reference* to the cell
(copied at spawn), so `cell.id` mutation is instantly visible — events stamp
the live checkpoint id (req 1). Parent is explicit per begin event (req 2).
React and bridge use the identical path; agents change nothing (req 3).

Concurrency: the sample runs on one event loop; `cell.id = next` is a single
attribute assignment between awaits — no races beyond today's ordering.

## Phases

### Phase 1 — `_span.py`: cell type + rotating scope primitive

- Add private `_SpanCell` (mutable, `id: str`).
- Widen `_current_span_id` to `ContextVar[str | _SpanCell | None]`; unwrap in
  `current_span_id()` and in `span()`'s parent capture. Keep the union type
  private to the module (public API still returns `str | None`).
- Add a private rotating-scope primitive (e.g. `_span_scope(name_for, type)` or
  a small class) owning: session parent capture, begin/end event emission,
  cell set/reset (entry/exit task only), `rotate(name)`, and `close()`
  (idempotent, for the `final=True` fire). All ContextVar mechanics stay in
  `_span.py`.
- The scope must replicate two things `span()` did:
  - **`_span_id_provider` consultation** for each span id (replay-deterministic
    ids) — `await provider(name, parent_id, requested_id)` per open/rotate.
  - **`track_store_changes()` semantics**: snapshot `store_jsonable(store())`
    at each span open; at rotate/close, diff and emit `StoreEvent` *before*
    the `SpanEndEvent` and before mutating the cell (so the `StoreEvent`
    stamps the closing checkpoint's id, matching `span()`'s ordering today).
- Leave the `except ValueError` warning guard in `span()` untouched — still a
  valid misuse guard for other callers.

### Phase 2 — `checkpointer_impl.py`: use the scope

- Replace `_current_span_cm` / `_open_next_span` / `_close_current_span`
  manual cm driving with the Phase 1 scope.
- `span_session()`: open scope with name `checkpoint {next_id}` (id still
  scanned from disk via `_scan_next_checkpoint_id`), type `"checkpoint"`.
- `_fire_once`: `scope.rotate(f"checkpoint {next_id}")` placed where
  close/open happen today (close before `_write_host_context` so the
  `SpanEndEvent` lands in this checkpoint's `events.json`; reopen in the
  `finally`, skipped when `final=True` → `scope.close()`).
- Per-checkpoint `events.json` export (transcript subscription) is
  ordering-based and unaffected.

### Phase 3 — inspect_swe: lazy outer-span resolution

Both consumers freeze `outer_span_id=current_span_id()` at construction,
*before* `checkpointer()` entry, and explicitly stamp model events with it —
bypassing emission-time resolution:

- `_claude_code/_events/live_consumer.py` (`LiveConsumer`, claude_code.py:169)
- `_codex_cli/_events/consumer.py` (`CodexConsumer`, codex_cli.py:169)

Change: resolve the outer span lazily — call `current_span_id()` at
attribution/emission time instead of storing a frozen id (constructor arg
becomes unnecessary or becomes a fallback). With the cell in place, sink
callbacks run in T2x whose chain bottoms out at the cell, so main-agent model
events stamp the live checkpoint id, and sub-agent spans parent correctly off
the attributed event's span_id.

### Phase 4 — tests

- Cross-task rotation: enter `span_session()` in task A; spawn task B (after
  entry) that triggers a fire; spawn task C that emits an event after the
  fire. Assert: no `Exiting span created in another context` warning (caplog —
  attach `caplog.handler` to the `inspect_ai.util._span` logger, module has
  `propagate=False`); checkpoint spans are siblings with the session parent;
  C's event stamps checkpoint 2.
- React-path regression: existing `tests/checkpoint/test_checkpointer.py`
  flow still produces correctly nested spans/events.
- `StoreEvent` parity: store mutation between fires yields a `StoreEvent`
  stamped with the closing checkpoint span, emitted before its `SpanEndEvent`.
- Span-id provider: rotation consults `_span_id_provider` when set.

## Edges / non-changes

- A sub-span (e.g. tool span) still open across a fire keeps its original
  parent; its events stay under the old checkpoint. Spans can't reparent;
  fires happen at turn boundaries, acceptable.
- `hydrate.py` (`current_span_id()` at :326, synthesized-event stamping,
  `_wrap_prior_run`) reads resolved values — unaffected.
- Viewer: still plain `SpanBeginEvent`/`SpanEndEvent` with explicit
  `parent_id` — no viewer changes.
- ACP `AGENT_SPAN_TYPE` depth counting keys on type `"agent"`; checkpoint
  spans are type `"checkpoint"` — no interference.

## Unresolved questions

1. Scope primitive shape: free functions vs small class in `_span.py`? (lean:
   class, instance held by `_EnteredCheckpointer`)
2. inspect_swe consumers: keep `outer_span_id` ctor arg as fallback for
   no-checkpointer runs, or drop entirely and always resolve lazily? (lean:
   always lazy; `current_span_id()` at construction time was already just the
   agent span)
3. Should rotation `StoreEvent` diffing reuse `track_store_changes` via
   re-snapshot, or inline the diff? (lean: inline; the cm shape doesn't fit
   rotation)
