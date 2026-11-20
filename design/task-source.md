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
    async def sample_complete(self, sample: EvalSample, task: Task) -> list[Task] | None: ...  # observe + add
    async def sample_abandoned(self, sample: Sample, epoch: int, task: Task) -> list[Task] | None: ...  # never-logged cancel
    async def task_complete(self, log: EvalLog) -> list[Task] | None: ...          # observe + add
```

The two halves of the *production* contract are deliberately asymmetric:

- **`initial_tasks()` is synchronous and must return immediately.** It is the
  seed the run sets up and starts from. The run resolves and validates it
  up front (concurrency, sample-id assignment, sandbox startup) exactly like
  any other task list — so it cannot block / await.
- **`next_tasks()` is async and may block indefinitely.** It is called when no
  task is queued or running (and after the finished tasks' completion
  notifications), can `await` external input or more results, and returns
  `None` to end the run.
  This is the blocking / explicit-pull path for an open-ended "keep producing
  until told to stop" loop.

`sample_complete` / `task_complete` fire as work completes (see below) and serve
double duty: they observe results *and* may **return follow-up tasks**. A
returned list is added to the run as `enqueue_task` adds tasks outside a running
task (it is routed through the same run queue — see below), so the *simplest* sources never
implement `next_tasks()` at all: they just react to each result and return the
next tasks. The run then ends naturally when the callbacks return nothing
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
  ├─ eval_resolve_tasks(task_source.initial_tasks() ...)   # seed
  │
  └─ eval_run (one, under one run_id and one control/ACP server scope):
        queue.add(seed)
        dispatch_tasks(queue):       ─► task_run / task_run_sample
            start queued tasks while a max_tasks slot is free      │
                                       sample_complete(sample, task) ─┐ (per sample)
                                       task_complete(log) ────────────┤ (per attempt)
                                       returned tasks ─► queue ◄──────┘
            if nothing is queued or running:
                queue.add(resolve(await task_source.next_tasks()))   # blocking pull
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
  `task_source.sample_complete(eval_sample, task)` right after `emit_sample_end` (so
  it fires **per sample**, not batched at task end; it runs after the shielded
  completion block, and is skipped for a sample cancelled by the task's own
  unwind — see [sample-source.md](sample-source.md)); `run_sample` calls
  `task_source.sample_abandoned(sample, epoch, task)` for a run that ends
  `DISCARDED` — cancelled without ever being logged (queued-sample cancel,
  graceful task-cancel abandon at queue exit, pre-retry drain-window abandon;
  same delivery rule, see [sample-source.md](sample-source.md) and
  [sample-lifecycle.md](sample-lifecycle.md)) — and, because that hook runs
  after the run's terminal count, a `TaskSource`-driven eval registers as
  `dynamic` in the control-channel state so `ctl task cancel` still works
  while a callback is suspended; and `task_run` calls
  `_run_task` (in [run.py](../src/inspect_ai/_eval/run.py)) calls
  `task_source.task_complete(eval_log)` once for each attempt, with the log it
  ended with. Whatever a callback **returns** is passed to
  `_enqueue_source_tasks`, which adds it to the run queue
  (`get_run_queue().enqueue(...)`) — so returned tasks and `enqueue_task`
  additions go through one queue.
- **The dispatcher** — `dispatch_tasks` in
  [run.py](../src/inspect_ai/_eval/run.py): starts queued tasks as slots free
  and, only when nothing is queued or running, awaits
  `task_source.next_tasks()`, resolving the result through the same
  `resolve_added_tasks` closure used by `enqueue_task`. See
  [task-dispatch.md](task-dispatch.md).

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

so any path that resolves tasks without the dispatcher fails loudly rather than
silently running only the seed.

## Relationship to `enqueue_task`

There are three ways to add tasks to a run, in increasing directness, and they
all feed one queue:

- **`next_tasks()`** — the blocking / explicit-pull path: the dispatcher
  *pulls* the next batch from the source when nothing is queued or running.
- **Returning tasks from `sample_complete` / `task_complete`** — the *push from
  a result* path: the simplest sources react to each completion and return the
  follow-ups. The firing site routes the return value onto the run queue, so
  it is just sugar for "call `enqueue_task` with what you'd return" from outside
  a running task.
- **`enqueue_task()`**
  ([task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py)) — the *imperative*
  primitive for *arbitrary* code (a solver, a scorer, a tool), not just a
  `TaskSource`, to push tasks into the current run:

  ```python
  def enqueue_task(tasks: Tasks, *, run_id: str | None = None) -> None: ...
  ```

The last two share the same downstream machinery:

- The run's `RunQueue` holds the *resolve* closure (`_resolve_enqueued_tasks`,
  bound via `functools.partial` to the run's models / roles / config / sandbox /
  cost limit). Once the run has opened its queue, `enqueue()` resolves and
  configures immediately (so a bad task surfaces at the call site) and queues
  the task, which starts when a slot is free. From an `on_run_start` hook,
  before the queue opens, it resolves immediately but configures after the
  hooks return, when the queue opens: the tasks start after the seed, and a
  failing configuration or selection check ends the run before any seed task
  starts ([task-dispatch.md](task-dispatch.md#adding-tasks)).
- Resolution depends on where the tasks are added. Inside a running task
  attempt (its samples, solvers, tools, scorers and other code the attempt
  runs), they resolve once, under the attempt's model, in place of the run's
  models. Anywhere else, they resolve once per run model. TaskSource callbacks
  (`initial_tasks`, `next_tasks`, `sample_complete`, `sample_abandoned`,
  `task_complete`) count as outside an attempt, both for the tasks they return
  and for `enqueue_task()` calls made inside them, and so does a background
  coroutine still running after its attempt ended. A private `ContextVar` in
  `task/enqueue.py` (`_creator`) carries the attempt's model in a cell the
  attempt marks ended: `_run_task` (`_eval/run.py`) sets it around
  `task_run`, and each callback site clears it.
  [task-handles.md](task-handles.md)'s `_attempt` ContextVar replaces it. A
  task that sets its own `model` keeps it either way, and model roles and
  generate config come from the run.
- The dispatcher consults `next_tasks()` only when nothing is queued or
  running, so imperative additions and declarative generation compose in one
  loop.

Because `enqueue_task` is called from *arbitrary* code, it needs an ambient
handle to the active run — but a process global is too broad. It uses a
**`ContextVar`** (`_run_queue`), set at the top of the run and reset via its
token in the `finally`. The ContextVar is scoped to the run's async context and
propagates to child tasks created after it's set, so samples/tools/scorers see
it; `enqueue_task` validates the optional `run_id` against the active queue's
to reject a stray/late caller targeting a torn-down or different run.

(`TaskSource` itself does *not* need the ContextVar — it is threaded explicitly
via `TaskRunOptions`. Only `enqueue_task`, called from unknown call sites, needs
the ambient lookup.)

## Public surface

- `TaskSource` is exported from `inspect_ai` (`__init__.py` `__all__`).
- `@task_source` decorator ([registry.py](../src/inspect_ai/_eval/registry.py),
  exported from `inspect_ai`) — **mirrors `@task`**. Decorates a function
  returning a `TaskSource`, registering it (registry type `"task_source"`) so it
  can be referenced and **loaded by name** and parameterized, and tagging the
  produced instance with registry info + file / run-dir attrs. `task_source_register`
  / `task_source_create` parallel `task_register` / `task_create` (the latter
  calls the registered wrapper directly — `registry_create` only auto-invokes
  factories whose return-type name matches the registry type, which
  `"task_source"` / `TaskSource` does not, the same as `score_reducer`).
- `TaskSource.from_tasks(initial_tasks, *, next_tasks=None, sample_complete=None,
  task_complete=None)` — classmethod that builds a `TaskSource` from a seed plus
  optional callbacks, for the common case where subclassing is more than you
  need. Returns a `_CallableTaskSource` delegating to the callables (which
  typically close over shared state). Omitting `next_tasks` (and returning
  nothing from callbacks) stops after the seed — equivalent to passing the list
  directly.
- **Load-by-name** — `resolve_task_source(tasks, task_args)`
  ([loader.py](../src/inspect_ai/_eval/loader.py)), called by `eval_async`,
  resolves a `TaskSource` from any form `eval()` accepts: an instance, a
  `@task_source`-decorated function, a registered name, or a `file.py@name`
  spec. The file case reuses `load_file_tasks` (the same module loader the task
  path uses) after a cheap text check that the file defines a `@task_source` (so
  a task-only file isn't loaded here and then again as tasks); the shared load
  gate (`code_has_task_or_source`) now also makes source-only files discoverable
  during directory enumeration, removing the task/source asymmetry. The CLI
  passes specs as a one-element list, which it unwraps. Returns `None` for
  anything else, so normal task resolution proceeds. So `inspect eval
  rl.py@my_source -T lr=0.1` and `eval("rl.py@my_source")` both drive the live
  path.
- The `Tasks` type alias ([task/tasks.py](../src/inspect_ai/_eval/task/tasks.py))
  includes `| TaskSource | Callable[..., TaskSource]`, so both a source and a
  `@task_source` function type-check as `tasks`.
- `enqueue_task` is the imperative primitive (same module group).

`eval_set` / `eval_retry` / `score` still reject `TaskSource` **instances** with
a clear error; a source *spec* passed to `eval_set` currently fails later as a
task-not-found (not specially handled).

## Tests

- `tests/test_task_source.py` — multiple generations under one `run_id`;
  single-batch when `next_tasks()` returns `None` immediately;
  `sample_complete` fires per sample *before* the task's `task_complete`;
  `task_complete` **returning** follow-up tasks chains generations (subclass and
  `from_tasks`); `TaskSource.from_tasks` seed + callbacks; `@task_source`
  decorator (instance, passed-as-function, load-by-registered-name, with task
  args, and `file.py@name`); live injection (below); rejection outside `eval()`.
- `tests/test_enqueue_task.py` — added task runs in the same run, and starts
  while its creator runs; additions chain; calling outside a run raises.

## Live injection

Every run is **live**: a task added while the run is in progress starts on
free capacity immediately, rather than waiting for a batch boundary, with or
without a `TaskSource`. One queue and one dispatcher serve every run; see
[task-dispatch.md](task-dispatch.md).

`tests/test_task_source.py::test_live_injection_runs_concurrently_with_in_flight_task`
discriminates live injection from batch-at-a-time: a "blocker" task parks until
an injected task releases it, and the injected task is only enqueued mid-run. It
can only complete if the injected task runs *while the blocker is still in
flight* — under batch-at-a-time it would deadlock (the `fail_after` turns a
regression into a fast failure rather than a hang).

## Status

Implemented and tested in `eval()` / `eval_async()`:

- [x] `TaskSource` base class + `initial_tasks` / `next_tasks` /
      `sample_complete` / `task_complete`.
- [x] `sample_complete` / `task_complete` may **return** follow-up tasks (routed
      onto the run queue via `_enqueue_source_tasks`) — the simplest sources
      need no `next_tasks()`.
- [x] `TaskSource.from_tasks(...)` classmethod — build a source from a seed +
      callbacks without subclassing.
- [x] `@task_source` decorator (mirrors `@task`) + load-by-name: registered
      name, `@task_source` function, or `file.py@name` spec, with task-arg
      parameterization (`resolve_task_source`).
- [x] Threaded via `TaskRunOptions` (no global), per-sample and per-task firing.
- [x] `enqueue_task` imperative primitive backed by a `ContextVar`.
- [x] **Live injection** for every run: one `eval_run`, one queue and one
      dispatcher ([task-dispatch.md](task-dispatch.md)), incremental
      `SandboxManager`, growing display (rich / plain / textual).
- [x] Rejected (with a clear error) on non-`eval()` paths.

## Next steps / future work

- **`eval_set`** — see below; live injection does not change the eval_set story.

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
   eval_async's dispatcher loop up into eval_set. Real work, no new concepts.

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
  the inner `eval()`, whose dispatcher drives `next_tasks()`. The generated
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
