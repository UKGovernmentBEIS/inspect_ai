# TaskSource: driving a running eval from code

This document describes `TaskSource` — an abstraction that lets a run produce
its tasks dynamically (a seed plus result-driven follow-ups) instead of from a
fixed list. It covers the design, the implementation as it stands today, the
related `enqueue_task` primitive it shares machinery with, and the open
questions / options for future work (notably `eval_set` / `eval_retry`).

## Motivation

The original `tasks` argument to `eval()` is static: you hand it a `Task` (or
list of tasks, or things that resolve to tasks) and the run executes exactly
those. RL-style and other interactive workflows need the opposite — the *next*
tasks to run depend on the *results* of the ones that just ran (e.g. generate
follow-up tasks from the scores of a batch, or keep producing until told to
stop).

Two earlier approaches were rejected:

- **Global hooks.** A globally-enabled hook that observes sample/task
  completion and pushes new work. Rejected (JJ): "globally enabled… a very
  indirect and not very intuitive interface… we should do something more
  direct." The objection is that an ambient, process-wide switch is the wrong
  shape for what is really a per-run input.
- **A bare imperative push API as the *only* surface.** `enqueue_task()` (see
  below) exists and is useful, but on its own it doesn't answer "where do the
  *initial* tasks come from?" or "how does the run know when it's done?" — it's
  a primitive, not the user-facing contract.

The chosen design is an **explicit task argument**: `TaskSource` is just another
type the existing `tasks` parameter accepts. This mirrors `EarlyStopping`
(`util/_early_stopping.py`) — a per-run object, threaded through `Task` /
`TaskRunOptions`, that fires notification callbacks from inside the run. No
global state, no new top-level parameter.

## The `TaskSource` contract

`src/inspect_ai/_eval/task/task_source.py` defines a subclassable base class
with no-op defaults:

```python
class TaskSource:
    def initial_tasks(self) -> list[Task]: ...                          # sync seed (immediate)
    async def next_tasks(self) -> list[Task] | None: ...                # async; None ends run
    async def sample_complete(self, sample: EvalSample) -> list[Task] | None: ...  # observe + add
    async def task_complete(self, log: EvalLog) -> list[Task] | None: ...          # observe + add
```

The two halves of the *production* contract are deliberately asymmetric:

- **`initial_tasks()` is synchronous and must return immediately.** It is the
  seed the run sets up and starts from. The run resolves and validates it
  up front (concurrency, sample-id assignment, sandbox startup) exactly like
  any other task list — so it cannot block / await.
- **`next_tasks()` is async and may block indefinitely.** It is called *after*
  each batch finishes (and after that batch's completion notifications), can
  `await` external input or more results, and returns `None` to end the run.
  This is the blocking / explicit-pull path for an open-ended "keep producing
  until told to stop" loop.

`sample_complete` / `task_complete` fire as work completes (see below) and serve
double duty: they observe results *and* may **return follow-up tasks**. A
returned list is added to the run exactly as `enqueue_task` would (it is routed
through the same run enqueuer — see below), so the *simplest* sources never
implement `next_tasks()` at all: they just react to each result and return the
next tasks. The run then ends naturally when a batch's callbacks return nothing
and `next_tasks()` (default `None`) yields no more. `next_tasks()` is reserved
for the blocking case (wait for external input) that a per-result callback can't
express.

A `TaskSource` is passed as the `tasks` argument and runs under a **single
`run_id`** — every generation shares the run, with each task getting its own
`eval_id` / `task_id` and log file.

## Where it plugs in

```
eval() / eval_async()              tasks=<TaskSource>
  │
  ├─ task_source = tasks if isinstance(tasks, TaskSource) else None   # eval.py
  │
  ├─ eval_resolve_tasks(task_source.initial_tasks() ...)   # seed = first batch
  │
  └─ batch loop (under one run_id, one control/ACP server scope):
        while pending is not None:
            run_batch(pending)            ─► eval_run ─► task_run / task_run_sample
                                                 │            │
                                                 │            └─ sample_complete(sample) ─┐ (per sample)
                                                 └─ task_complete(log) ──────────────────┤ (per task)
                                                          returned tasks ─► enqueuer ◄────┘
            if cancelled: break
            pending = enqueuer.drain() or None         # enqueue_task + returned tasks first
            if pending is None and task_source is not None:
                pending = resolve(await task_source.next_tasks())   # else blocking pull
```

Key locations:

- **Interception** — `eval_async` ([eval.py](../src/inspect_ai/_eval/eval.py),
  ~line 753): `task_source = tasks if isinstance(tasks, TaskSource) else None`,
  then `eval_resolve_tasks(task_source.initial_tasks() if task_source else tasks, …)`.
  After this point the seed is an ordinary resolved-task list.
- **Threading the source to the run** — it is *not* a global. It travels down
  via `eval_run(task_source=…)` → `TaskRunOptions.task_source` → `task_run`
  (`task_complete`) and `task_run_sample(task_source=…)` (`sample_complete`).
  This mirrors how `EarlyStopping` is carried on `Task` and fired from
  `task_run`.
- **Notification firing** — in
  [task/run.py](../src/inspect_ai/_eval/task/run.py): `task_run_sample` calls
  `task_source.sample_complete(eval_sample)` right after `emit_sample_end` (so
  it fires **per sample**, not batched at task end), and `task_run` calls
  `task_source.task_complete(eval_log)` just before returning the log. Whatever
  a callback **returns** is passed to `_enqueue_source_tasks`, which pushes it
  onto the run enqueuer (`get_task_enqueuer().enqueue(...)`) — so returned tasks
  and `enqueue_task` additions share one buffer and the loop drains both.
- **The batch loop** — [eval.py](../src/inspect_ai/_eval/eval.py) (~line 999):
  drains imperatively-enqueued tasks first (`enqueuer.drain()`), and only if
  none calls `await task_source.next_tasks()`, resolving the result through the
  same `resolve_added_tasks` closure used by `enqueue_task`. A cancelled batch
  ends the run.

### Rejected elsewhere

`TaskSource` is only meaningful to `eval()` / `eval_async()`. `resolve_tasks`
([loader.py](../src/inspect_ai/_eval/loader.py), ~line 86) guards against it:

```python
if isinstance(tasks, TaskSource):
    raise ValueError(
        "A TaskSource can only be passed to eval(); it isn't supported here "
        "(e.g. eval_set / eval_retry / score)."
    )
```

so any path that resolves tasks without the batch loop fails loudly rather than
silently running only the seed.

## Relationship to `enqueue_task`

There are three ways to add tasks to a run, in increasing directness, and they
all feed one buffer:

- **`next_tasks()`** — the blocking / explicit-pull path: the loop *pulls* the
  next batch from the source between batches.
- **Returning tasks from `sample_complete` / `task_complete`** — the *push from
  a result* path: the simplest sources react to each completion and return the
  follow-ups. The firing site routes the return value onto the run enqueuer, so
  it is just sugar for "call `enqueue_task` with what you'd return."
- **`enqueue_task()`**
  ([task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py)) — the *imperative*
  primitive for *arbitrary* code (a solver, a scorer, a tool), not just a
  `TaskSource`, to push tasks into the current run:

  ```python
  def enqueue_task(tasks: Tasks, *, run_id: str | None = None) -> None: ...
  ```

The last two share the same downstream machinery:

- A `TaskEnqueuer` holds the run's *resolve* closure (`_resolve_enqueued_tasks`,
  bound via `functools.partial` to the run's models / roles / config / sandbox /
  cost limit) plus a buffer. `enqueue()` resolves immediately (so a bad task
  surfaces at the call site) and buffers; `drain()` is the non-blocking pull the
  loop does after each batch.
- The batch loop drains the enqueuer *before* consulting `next_tasks()`, so
  imperative additions and declarative generation compose in one loop.

Because `enqueue_task` is called from *arbitrary* code, it needs an ambient
handle to the active run — but a process global is too broad. It uses a
**`ContextVar`** (`_enqueuer`), set at the top of the run and reset via its
token in the `finally`. The ContextVar is scoped to the run's async context and
propagates to child tasks created after it's set, so samples/tools/scorers see
it; `enqueue_task` validates the optional `run_id` against the active enqueuer's
to reject a stray/late caller targeting a torn-down or different run.

(`TaskSource` itself does *not* need the ContextVar — it is threaded explicitly
via `TaskRunOptions`. Only `enqueue_task`, called from unknown call sites, needs
the ambient lookup.)

## Public surface

- `TaskSource` is exported from `inspect_ai` (`__init__.py` `__all__`).
- `task_source(initial_tasks, *, next_tasks=None, sample_complete=None,
  task_complete=None)` — a factory that builds a `TaskSource` from a seed plus
  optional callbacks, for the common case where subclassing is more than you
  need. Returns a `_CallableTaskSource` that delegates to the provided callables
  (which typically close over shared state to decide what to run next). Omitting
  `next_tasks` stops after the seed — equivalent to passing the list directly.
  Also exported from `inspect_ai`.
- The `Tasks` type alias ([task/tasks.py](../src/inspect_ai/_eval/task/tasks.py))
  includes `| TaskSource`, so `eval(tasks=…)` accepts it and the type checker is
  happy.
- `enqueue_task` is the imperative primitive (same module group).

## Tests

- `tests/test_task_source.py` — batch-at-a-time over multiple generations under
  one `run_id`; single-batch when `next_tasks()` returns `None` immediately;
  `sample_complete` fires per sample *before* the task's `task_complete`;
  `task_complete` **returning** follow-up tasks chains generations (subclass and
  factory); `task_source()` factory seed + callbacks; rejection outside `eval()`.
- `tests/test_enqueue_task.py` — added task runs in the same run; additions
  chain across batches; calling outside a run raises.

## Status

Implemented and tested for **batch-at-a-time** generation in
`eval()` / `eval_async()`:

- [x] `TaskSource` base class + `initial_tasks` / `next_tasks` /
      `sample_complete` / `task_complete`.
- [x] `sample_complete` / `task_complete` may **return** follow-up tasks (routed
      onto the run enqueuer via `_enqueue_source_tasks`) — the simplest sources
      need no `next_tasks()`.
- [x] `task_source(...)` factory — build a source from a seed + callbacks without
      subclassing.
- [x] Threaded via `TaskRunOptions` (no global), per-sample and per-task firing.
- [x] Batch loop driving `next_tasks()`, composing with `enqueue_task`.
- [x] `enqueue_task` imperative primitive backed by a `ContextVar`.
- [x] Rejected (with a clear error) on non-`eval()` paths.

## Next steps / future work

### Live injection (no API change expected)

The current loop is strictly batch-at-a-time: `next_tasks()` is only consulted
*between* batches, so a slow batch can't be augmented mid-flight. The same
`TaskSource` contract is intended to also support **live injection** — a
concurrent producer feeding `run_multiple`'s queue while a batch is in flight,
with a dynamic completion condition rather than a fixed batch boundary. This is
expected to be an internal change to the eval loop (a concurrent producer task +
a completion predicate) with **no change to the user-facing `TaskSource` API**:
`initial_tasks()` still seeds, `next_tasks()` still produces, the notifications
still fire per sample/task. Designing this is the main remaining piece.

### `eval_set` support — feasible, but only pays off for deterministic sources

eval_set's value is *idempotent retry-to-completion over an identity-tracked
task set, resumable across process restarts*. `try_eval()`
([evalset.py](../src/inspect_ai/_eval/evalset.py)) resolves the task list,
hashes each task to a stable `task_identifier`, then diffs against the log files
in `log_dir` to find succeeded / failed / never-run, and re-runs the incomplete
ones up to `retries` times — re-running `try_eval()` from scratch on each
attempt and on crash-resume.

**Identity is not the obstacle.** `task_identifier`
([evalset.py](../src/inspect_ai/_eval/evalset.py), `def task_identifier`) is
*purely content-derived*:

```
[task_file@]task_name#task_args_hash/model/additional_hash
```

`additional_hash` folds in the plan, generate config, model roles, version, and
limits. Nothing in it encodes *when* or *how* a task was produced — no
generation index, no ordinal, no run_id. So a task emitted by a `TaskSource`'s
third `next_tasks()` call hashes to the same identifier as the identical task in
a static list. eval_set's existing diff (`task_identifier(task) in
log_task_identifiers`) would work on generated tasks **with no change to
`TaskSource` or to `task_identifier`.** (An earlier draft claimed generated
tasks "have no stable identity to rematch" — that was wrong; it conflated
*identity*, which is content-derived and free, with *deterministic
regeneration*, which is the actual constraint below.)

The real work, in order:

1. **eval_set must own the generation loop (structural, mechanical).** Today
   `try_eval()` resolves a fixed list once. For a source it must instead drive
   `initial_tasks()` → run → `next_tasks()` → run, diffing *each generation's*
   batch against the logs before running it. This is essentially lifting
   eval_async's `run_batches` loop up into eval_set. Real work, no new concepts.

2. **Resume requires replaying results into the source (new machinery + a
   determinism contract).** This is the crux, and it is narrower than it first
   appears. The *only* reason to put dynamic generation in eval_set rather than
   `eval()` is cross-process crash-resume — within one process, `eval()`'s loop
   already runs a `TaskSource`. On resume, eval_set reconstructs a *fresh*
   source object that has not observed the prior run's results. To regenerate
   gen-N so its identifiers match the existing logs, eval_set must **replay the
   completed logs back through the source's `sample_complete` / `task_complete`**
   before calling `next_tasks()`. That is feasible (eval_set has the logs) but
   it is new code, and it only reproduces the same tasks if **the source's
   generation is deterministic given that replayed history.** A deterministic
   curriculum (branch on pass/fail) resumes perfectly; a stochastic RL loop
   (RNG, model sampling, wall-clock, external state) regenerates *different*
   tasks → different identifiers → they look new and get re-run, with the old
   logs orphaned. No data loss, but the resume payoff evaporates for exactly the
   headline use case.

3. **eval_set assumes identifier *uniqueness* — sources may violate it.**
   `validate_eval_set_prerequisites`
   ([evalset.py](../src/inspect_ai/_eval/evalset.py)) hard-errors if two tasks
   share an identifier. A source that re-emits an identical-content task in two
   generations (e.g. re-evaluating the same prompt) collides — it would trip
   this check or get silently deduped to one log. This mode would need that
   check relaxed/scoped plus a defined story for intentional duplicates.

Bottom line: identity is free; the cost is loop-ownership in eval_set + result
replay, and the feature only delivers its resume guarantee for
deterministic/replayable sources. Options, in increasing cost / value:

- **A. Leave rejected (current).** The loader guard names eval_set explicitly.
  Recommended until there's a concrete need for *crash-resumable dynamic runs* —
  which is the only thing eval_set adds over `eval(tasks=<TaskSource>)`, and only
  for deterministic sources.
- **B. Cheap pass-through (~hours).** Special-case `isinstance(tasks,
  TaskSource)` in eval_set to skip resolution / diff and forward the source to
  the inner `eval()`, whose batch loop drives `next_tasks()`. The generated
  tasks run and land in `log_dir`, but eval_set's retry-to-completion and
  crash-resume guarantees do not cover them (only the seed is visible to that
  machinery). Adds little over calling `eval()` directly — not recommended.
- **C. Real support.** eval_set owns the generation loop (item 1) and replays
  completed logs into the source before each `next_tasks()` (item 2), with the
  uniqueness check scoped (item 3). Documented as **deterministic-/replayable-
  sources-only**: a resumed run reuses prior logs iff the source regenerates the
  same tasks from the replayed completion history. Defer until a concrete
  crash-resumable-dynamic-run requirement exists; when it does, this is the
  shape — not a redesign of the identity model.

### `eval_retry` — not applicable

`eval_retry(tasks: str | EvalLogInfo | EvalLog | list[...])`
([eval.py](../src/inspect_ai/_eval/eval.py)) reconstructs a `Task` /
`PreviousTask` *from a prior eval log* and re-runs it. A `TaskSource` produces
tasks from code, not from logs — there is nothing to retry, and the signature
doesn't even accept the `Tasks` union. No work is planned here beyond the
existing clear rejection.
