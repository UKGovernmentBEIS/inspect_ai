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
- **`next_tasks()` is async and may block indefinitely.** It is called only
  when no task is queued or running (so after the completion notifications of
  every task so far), can `await` external input or more results, and returns
  `None` to end the run.
  This is the blocking / explicit-pull path for an open-ended "keep producing
  until told to stop" loop.

`sample_complete` / `task_complete` fire as work completes (see below) and serve
double duty: they observe results *and* may **return follow-up tasks**. A
returned list is added to the run exactly as `enqueue_task` would (it is routed
through the same run enqueuer — see below), so the *simplest* sources never
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
  └─ eval_run(seed, added_tasks=enqueuer)   # once per run, one run_id,
        │                                     # one control/ACP server scope
        └─ run_task_retry_attempts (the run's one dispatcher), each cycle:
              add(ready())          # enqueuer.ready(): when_free additions
              dispatch up to max_tasks ─► task_run / task_run_sample
                                              │            │
                                              │            └─ sample_complete(sample, task) ─┐ (per sample)
                                              └─ task_complete(log) ──────────────────┤ (per task)
                                                       returned tasks ─► enqueuer ◄────┘
              if cancelled: break
              if nothing queued or running:
                  add(await when_idle())  # enqueuer.when_idle(): buffered additions
                                     # first, else resolve(await task_source.next_tasks());
                                     # None (closes the enqueuer) ends the run
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
  `task_source.task_complete(eval_log)` just before returning the log. Whatever
  a callback **returns** is passed to `_enqueue_source_tasks`, which pushes it
  onto the run enqueuer (`get_task_enqueuer().enqueue(...)`) with the run's
  default start policy — so returned tasks and default `enqueue_task` additions
  are handled the same way.
- **The batch boundary** — `TaskEnqueuer.when_idle()` in
  [task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py), behind the feed's
  `when_idle()`: the dispatcher calls it only when nothing is queued or running.
  It returns buffered additions first (`when_free` ones enqueued after the
  dispatcher's last `ready()`, then `after_batch` ones), and only if there are
  none calls `await task_source.next_tasks()`, resolving the result through the same
  resolve closure used by `enqueue_task`. A cancelled task ends the run.

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

so any path that resolves tasks without the run's dispatcher feed fails loudly
rather than silently running only the seed.

## Relationship to `enqueue_task`

There are three ways to add tasks to a run, in increasing directness, and they
all feed the run's one dispatcher:

- **`next_tasks()`** — the blocking / explicit-pull path: the dispatcher *pulls*
  the next batch from the source when nothing is queued or running.
- **Returning tasks from `sample_complete` / `task_complete`** — the *push from
  a result* path: the simplest sources react to each completion and return the
  follow-ups. The firing site routes the return value onto the run enqueuer, so
  it is just sugar for "call `enqueue_task` with what you'd return."
- **`enqueue_task()`**
  ([task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py)) — the *imperative*
  primitive for *arbitrary* code (a solver, a scorer, a tool), not just a
  `TaskSource`, to push tasks into the current run:

  ```python
  def enqueue_task(
      tasks: Tasks,
      *,
      run_id: str | None = None,
      start: Literal["when_free", "after_batch"] | None = None,
  ) -> None: ...
  ```

  `start="when_free"` starts the tasks as soon as there is free task capacity;
  `start="after_batch"` once no task is queued or running, including
  `when_free` tasks added later. `None` (the default) is the run's default:
  `when_free` in a `TaskSource` run, `after_batch` otherwise. An invalid
  `start` raises `ValueError` before the tasks are resolved. `enqueue_task`
  must be called from the eval's event loop: the dispatcher's wake callback is
  not thread-safe. The run's enqueuer is registered after `emit_run_start` and
  closed before `emit_run_end`, so a call from `on_run_start` or `on_run_end`
  raises; hooks called during a task can add tasks.

The last two share the same downstream machinery:

- A `TaskEnqueuer` holds the run's *resolve* closure (`_resolve_enqueued_tasks`,
  bound via `functools.partial` to the run's models / roles / config / sandbox /
  cost limit), the run's `TaskSource` (if any, which also sets the default start
  policy), and one buffer per start policy. `enqueue()` resolves immediately (so
  a bad task surfaces at the call site), buffers by start policy, and fires the
  wake callback the dispatcher registered with `set_wake()`. The dispatcher
  takes `ready()` (the `when_free` buffer) on every cycle and calls
  `when_idle()` only when idle.
- The batch boundary takes `after_batch` additions *before* consulting
  `next_tasks()`, so imperative additions and declarative generation compose in
  one loop.
- When `when_idle()` finds nothing more to run, it calls `close()` before
  returning `None` (and `eval_async` closes it once `eval_run` returns, for a
  cancelled run, or when the run fails). A later `enqueue()` raises `RuntimeError` instead of buffering a task
  that would never run.

Because `enqueue_task` is called from *arbitrary* code, it needs an ambient
handle to the active run — but a process global is too broad. It uses a
**`ContextVar`** (`_enqueuer`), set at the top of the run and reset via its
token in the `finally`. The ContextVar is scoped to the run's async context and
propagates to child tasks created after it's set, so samples/tools/scorers see
it; `enqueue_task` validates the optional `run_id` against the active enqueuer's
to reject a stray caller targeting a different run. A child context that copied
the ContextVar keeps a reference to the enqueuer after the run, which is why the
enqueuer itself refuses additions once closed.

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
  rl.py@my_source -T lr=0.1` and `eval("rl.py@my_source")` both drive the
  source.
- The `Tasks` type alias ([task/tasks.py](../src/inspect_ai/_eval/task/tasks.py))
  includes `| TaskSource | Callable[..., TaskSource]`, so both a source and a
  `@task_source` function type-check as `tasks`.
- `enqueue_task` is the imperative primitive (same module group).

`eval_set` / `eval_retry` / `score` still reject `TaskSource` **instances** with
a clear error; a source *spec* passed to `eval_set` currently fails later as a
task-not-found (not specially handled).

## Tests

- `tests/test_task_source.py` — multiple generations from `next_tasks()` under
  one `run_id`; single-batch when `next_tasks()` returns `None` immediately;
  `sample_complete` fires per sample *before* the task's `task_complete`;
  `task_complete` **returning** follow-up tasks chains generations (subclass and
  `from_tasks`); `TaskSource.from_tasks` seed + callbacks; `@task_source`
  decorator (instance, passed-as-function, load-by-registered-name, with task
  args, and `file.py@name`); live injection (below); sequence grouping at
  `max_tasks=1` for the seed and for callback-returned tasks; an explicit
  `after_batch` addition waiting for idle; rejection outside `eval()`.
- `tests/test_enqueue_task.py` — added task runs in the same run; additions
  chain across batches; calling outside a run raises; `when_free` starts during
  the batch under `eval()`, `eval_set()` (including selection mode) and a
  `TaskSource` run; a `when_free` child held at `max_tasks=1` until the limit is
  raised; the default `after_batch` waits for every seed task; sequence grouping
  of a multi-model `when_free` group; retries; a late enqueue raising; an
  invalid `start` raising before resolution; `when_idle()` returning buffered
  `when_free` additions first; cancellation while a `when_free` child is
  queued; cancellation while an added group is being prepared (both
  loggers discarded, the cancellation propagating); a real Ctrl-C while an
  added task is prepared or `next_tasks()` waits (in a subprocess, under both
  backends) raising `KeyboardInterrupt`; and which hooks can call
  `enqueue_task`. It also covers a throttled trailing call that enqueues after the run
  has finished dispatching (logged; the eval keeps its result) and a finished
  added task's dataset being freed before the run ends.
  `tests/test_task_source.py` also covers tasks enqueued by
  the final `next_tasks()` call (an `after_batch` one starting after the
  `when_free` ones enqueued with it) and a cancellation while `next_tasks()`
  blocks propagating, and
  `tests/util/sandbox/test_docker_cleanup.py` an added task sharing the run's
  sandbox scope.

## One dispatcher per run

Every run — `eval()`, `eval_set()`, or a `TaskSource` — has a single dispatcher
for its whole lifetime, and tasks added while it is in progress join that
dispatcher's queue. In a `TaskSource` run they start on free capacity by
default; elsewhere they start once the dispatcher is idle unless added with
`start="when_free"`. The batch boundary (no task queued or running) is the
moment the dispatcher becomes idle, so no separate batch loop is needed.

### How it works

`eval_async` ([eval.py](../src/inspect_ai/_eval/eval.py)) creates the run's
`TaskEnqueuer` with the run's `TaskSource` (if any) and calls `eval_run`
**once** with the seed and the enqueuer as `added_tasks`. `eval_run` takes it
through the `AddedTasks` protocol ([run.py](../src/inspect_ai/_eval/run.py)):

- `ready()` (non-blocking, every dispatch cycle): `when_free` additions, to
  start when free.
- `when_idle()` (called only when idle, may block): buffered `when_free`
  additions (enqueued during an await after the cycle's `ready()`), else
  `after_batch` additions, else `await task_source.next_tasks()` resolved to
  `ResolvedTask`s, else `None` (closing the enqueuer) to end the run. Since
  `next_tasks()` may block and enqueue meanwhile, the buffers are checked again
  before closing, `when_free` first (`after_batch` additions then wait for the
  next idle point); once `next_tasks()` has returned nothing it is not called
  again. Tasks enqueued while `next_tasks()` blocks start only after it
  returns, so `next_tasks()` must not wait for them; the dispatcher does not
  take `ready()` while it waits on `when_idle()`.
- `set_wake()`, so an enqueue wakes the dispatcher. An `after_batch` enqueue
  then costs one dispatch cycle in which `ready()` returns nothing.

`eval_run` wraps that with its own task preparation (`prepare_options`:
`ResolvedTask` → `TaskRunOptions`, with incremental sandbox startup via
`SandboxManager`) into a `PreparedFeed` with the same three operations, and
hands it to `run_task_retry_attempts(..., feed=...)`. `prepare_options` owns a
group's loggers until it returns them: if preparing a task fails or is
cancelled, it discards the loggers it already created (they are not yet in
`prepared_loggers`, so `eval_run`'s error handler would not reach them).
`prepared_loggers` keeps only the loggers, not the `TaskRunOptions`, so a
finished added task's `Task` and dataset are freed before the run ends. At
`parallel == 1` it puts the seed
and every added group in sequence-major order (`_dispatch_order`), so with the
dispatcher's queue-order tie-break all of task N's model fan-outs run before
task N+1's, as when the tasks are passed to `eval()` directly.

`run_task_retry_attempts` ([run.py](../src/inspect_ai/_eval/run.py)) serves both
fixed and open runs — a fixed set is just a run whose feed supplies nothing
(`when_idle()` returns `None` at the first idle point), so there is no separate
"dynamic" function. It also owns per-task retries (`task_retry_attempts`); a run without
retries is simply `task_retry_attempts==0`. Its dispatcher loop, per cycle:
drains buffered injections (growing the display via `update_task_count`),
dispatches up to the live `max_tasks` limit (model-balanced), and — when nothing
is pending, nothing is in flight, and nothing was buffered — calls the (blocking)
`feed.when_idle()`. It completes when the feed is exhausted *and* the queue has
drained. A re-armable `_Wake` (set on each task completion and each enqueue)
drives the loop; `feed.when_idle()` is only awaited when fully idle, so no
running task can enqueue while it blocks. A cancelled run stops before taking
further additions. Each task runs via the shared `_run_task`
helper (a per-task cancel scope around `task_run`); initial tasks keep their
input order in the results and injected tasks are appended in arrival order.
When dispatch stops on a cancelled run, tasks still queued never start, and
their log entries are discarded as for an abandoned retry.

A cancellation (Ctrl-C, or a cancelled scope around `eval_async`) that lands
while the dispatcher waits for running tasks is absorbed (`_run_task_screen`):
those tasks end with `cancelled` logs and the run returns them. One that lands
while the dispatcher takes tasks from the feed (preparing an added group, or
awaiting `next_tasks()`) propagates out of `eval_async`, so `eval()` raises
`KeyboardInterrupt` and the CLI exits 1: the tasks it interrupts have no log
yet, so a run that returned normally would look complete. Tasks running beside
the interrupted preparation are cancelled and write `cancelled` logs.

Consequences of one dispatcher per run: task-level sandbox environments
(`task_init`) started for any generation are cleaned up once, at the end of the
run; one task display grows as tasks are added; and `inspect ctl config` sees a
live dispatcher (with its real `pending` count) for the whole run.

### Components

- **`SandboxManager`** ([run.py](../src/inspect_ai/_eval/run.py)) — starts
  sandboxenvs incrementally (only ones not already started) and accumulates
  cleanups, so injected tasks get sandboxes and everything tears down once at
  the end.
- **`Display.update_task_count(n)`** ([display.py](../src/inspect_ai/_display/core/display.py))
  — bumps the "completed / total" denominator as tasks are injected (per-task
  progress views already grow on demand, the same path retries use). Implemented
  for the rich, plain, and textual displays; a no-op default for the log
  display. (Retries must *not* call this — they reuse a `task_id` and are deduped
  in the title; an injected task is a new `task_id`, so it does.)
- **`TaskEnqueuer.set_wake`** ([enqueue.py](../src/inspect_ai/_eval/task/enqueue.py))
  — registers the callback fired after buffering, used to wake the dispatcher.

### Tests

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
      onto the run enqueuer via `_enqueue_source_tasks`) — the simplest sources
      need no `next_tasks()`.
- [x] `TaskSource.from_tasks(...)` classmethod — build a source from a seed +
      callbacks without subclassing.
- [x] `@task_source` decorator (mirrors `@task`) + load-by-name: registered
      name, `@task_source` function, or `file.py@name` spec, with task-arg
      parameterization (`resolve_task_source`).
- [x] Threaded via `TaskRunOptions` (no global), per-sample and per-task firing.
- [x] `enqueue_task` imperative primitive backed by a `ContextVar`.
- [x] **One dispatcher per run**: a single `eval_run` and one
      `run_task_retry_attempts` dispatcher for every run (fixed = empty-feed;
      no separate dynamic path), incremental `SandboxManager`, growing display
      (rich / plain / textual), sequence-major order at `parallel == 1`.
- [x] **Start policy per addition.** `enqueue_task(start=...)`: `when_free`
      joins the running queue, `after_batch` waits for the dispatcher to be
      idle. The default is `when_free` in a `TaskSource` run (so
      callback-returned tasks start on free capacity at any `max_tasks`) and
      `after_batch` otherwise.
- [x] A late `enqueue_task()` (after the run has finished dispatching) raises.
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
   the enqueuer's `when_idle()` batch boundary up into eval_set. Real work, no
   new concepts.

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
