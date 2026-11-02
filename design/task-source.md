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
returned list is added to the run exactly as `enqueue_task` would (the callback
site calls it — see below), so the *simplest* sources never
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
  └─ eval_run(seed)               # once per run, one run_id,
        │                           # one control/ACP server scope
        └─ TaskDispatcher (the run's one scheduling loop):
              while True:
                  prepare_front_of_queue(): request the next tasks' setups
                  start_prepared_tasks() ───────────► task_run / task_run_sample
                                              │            │
                                              │            └─ sample_complete(sample, task) ─┐ (per sample)
                                              └─ task_complete(log) ──────────────────┤ (per task)
                                                 returned tasks ─► enqueue_task() ◄───┘
                  if any started: go round again
                  elif anything is queued or running: wait_for_change()
                  else add_tasks_from_source(): add await next_tasks()'s batch;
                       nothing left: close the run's tasks and end the run
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
  `task_source.task_complete(eval_log)` once the attempt's cancel scope has
  exited. Whatever a callback **returns** is passed to
  `_enqueue_source_tasks`, which calls `enqueue_task` with it — so returned
  tasks and `enqueue_task` additions are the same thing.
- **The batch boundary** — `TaskDispatcher.add_tasks_from_source()` in
  [run.py](../src/inspect_ai/_eval/run.py): the loop calls it only when nothing
  is queued or running. It awaits the source's `next_tasks()` (the dispatcher
  holds only that hook, not the source) and adds the batch with
  `RunTasks.add_ahead`, which resolves tasks as `RunTasks.add` (the function
  `enqueue_task` uses) does but queues them ahead of any added while
  `next_tasks()` ran. A cancelled task ends the run.

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

so any path that resolves tasks without the run's dispatcher fails loudly
rather than silently running only the seed.

## Relationship to `enqueue_task`

There are three ways to add tasks to a run, in increasing directness, and they
all feed the run's one dispatcher:

- **`next_tasks()`** — the blocking / explicit-pull path: the dispatcher *pulls*
  the next batch from the source when nothing is queued or running.
- **Returning tasks from `sample_complete` / `task_complete`** — the *push from
  a result* path: the simplest sources react to each completion and return the
  follow-ups. The firing site calls `enqueue_task` with the return value, so
  it is just sugar for "call `enqueue_task` with what you'd return."
- **`enqueue_task()`**
  ([task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py)) — the *imperative*
  primitive for *arbitrary* code (a solver, a scorer, a tool), not just a
  `TaskSource`, to push tasks into the current run:

  ```python
  async def enqueue_task(
      tasks: Tasks, *, run_id: str | None = None
  ) -> list[TaskHandle]: ...
  ```

  It is a coroutine: it resolves the tasks against the run's models and
  config, configures them and works out the sandbox configs their selected
  samples use, then queues them, so an invalid task or sandbox config raises
  to the caller and none of the call's tasks is queued. An added task starts
  when a slot is free, after the tasks queued before it. `enqueue_task` must
  be called from the eval's event loop: the run's tasks have no lock and
  their wake is not thread-safe. The run's tasks are registered after
  `emit_run_start` and closed before `emit_run_end`, so a call from
  `on_run_start` or `on_run_end` raises; hooks called during a task can add
  tasks.

All three share the same downstream machinery:

- The run's `RunTasks` ([task/enqueue.py](../src/inspect_ai/_eval/task/enqueue.py))
  holds the run's *resolve* function (`_resolve_enqueued_tasks`, bound via
  `functools.partial` to the run's models / roles / config / sandbox / cost
  limit), and every record: `queued`, `running`, and all in the order queued.
  `add()` resolves, configures and prepares the tasks, then queues them and
  sets the wake the loop waits on. A `next_tasks()` batch is added when the
  call returns, ahead of any task added while it ran (in the queue and in the
  results).
- When the dispatcher finds nothing more to run it closes the run's tasks
  before returning (and on a cancelled or failed run; `eval_run` closes them
  when the run fails before dispatch). A later `add()` raises `RuntimeError`
  instead of queuing a task that would never run.

Because `enqueue_task` is called from *arbitrary* code, it needs an ambient
handle to the active run — but a process global is too broad. It uses a
**`ContextVar`** (`_run_tasks`), set at the top of the run and reset via its
token in the `finally`. The ContextVar is scoped to the run's async context and
propagates to child tasks created after it's set, so samples/tools/scorers see
it; `enqueue_task` validates the optional `run_id` against the active run's
to reject a stray caller targeting a different run. A child context that copied
the ContextVar keeps a reference to the run's tasks after the run, which is
why `RunTasks` itself refuses additions once closed.

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
  `max_tasks=1` for the seed and for callback-returned tasks; rejection
  outside `eval()`.
- `tests/test_enqueue_task.py` — added task runs in the same run; additions
  chain across batches; calling outside a run raises; an added task starts
  while others run under `eval()`, `eval_set()` (including selection mode) and
  a `TaskSource` run; a child held at `max_tasks=1` until the limit is raised;
  sequence grouping of a multi-model group; retries; a late enqueue raising;
  cancellation while a child is queued; a real Ctrl-C while an added task is
  set up or `next_tasks()` waits (in a subprocess, under both backends:
  asyncio returns the logs so far, trio raises `KeyboardInterrupt`); which
  hooks can call `enqueue_task`; and a finished added task's dataset being
  freed before the run ends. `tests/test_task_source.py` also covers tasks
  enqueued by the final `next_tasks()` call and a cancellation while
  `next_tasks()` blocks returning the logs so far, and
  `tests/util/sandbox/test_docker_cleanup.py` an added task sharing the run's
  sandbox scope. `tests/test_task_dispatch.py` covers the records, the idle
  rule, the scheduling loop with scripted tasks and setups (the look-ahead
  window, in-place retries, setup failures, cancels of waiting tasks), and
  `tests/test_setup_cache.py` the shared setup jobs, and
  `tests/util/sandbox/test_sandbox_provider_context.py` where a sandbox
  provider's `task_init` ContextVar state is visible.

## One dispatcher per run

Every run — `eval()`, `eval_set()`, or a `TaskSource` — has a single dispatcher
for its whole lifetime, and tasks added while it is in progress join that
dispatcher's queue and start on free capacity. The batch boundary (no task queued or running) is the
moment the dispatcher becomes idle, so no separate batch loop is needed.

### How it works

`eval_async` ([eval.py](../src/inspect_ai/_eval/eval.py)) calls `eval_run`
**once** with the seed and the function that resolves added tasks. `eval_run`
([run.py](../src/inspect_ai/_eval/run.py)) creates the run's `RunTasks`,
makes it the active one for `enqueue_task`, starts up the seed and runs the
`TaskDispatcher`:

- **Records.** Every task has a `TaskRecord` from the moment it is queued
  until it ends: created by `RunTasks.add` (inside `enqueue_task`, which a
  `TaskSource` callback's returned tasks also go through, and for each
  `next_tasks()` batch) and for the seed. Creating a record configures the
  task (`TaskStartup.configure`), creates its model's connection controller
  (so `ctl config` can retune `max_connections` during a long setup) and
  resolves the sandbox configs its selected samples use, in sample order
  (`TaskStartup.prepare`); an invalid task or config raises to whoever added
  it. At `parallel == 1` the tasks of one addition are sorted sequence-major,
  so with the dispatcher's queue-order tie-break all of task N's model
  fan-outs run before task N+1's, as when the tasks are passed to `eval()`
  directly. A record is queued, then running (from its first attempt's start
  through its last attempt, retries included), then ended; every way it ends
  goes through `RunTasks.end`, which keeps its final log, if any. `RunTasks.find`
  looks a record up by task id. `enqueue_task` is a plain coroutine that
  returns a `TaskHandle` per record, in start order; entering a handle with
  `async with` cancels its task on exit. A handle's `state` is read from where the record is,
  `cancel()` calls the ctl's `cancel_task` with the record's id (so the handle
  and `inspect ctl` act on the same record), and `wait()` waits for the
  record's end event and returns its final log.
- **Setups.** As tasks start, the loop requests the setups of the records in
  front of the queue (`prepare_front_of_queue`: the first `max_tasks`
  unpaused queued records, read live, so a queued task's sandboxes are not
  created long before a slot can be free for it; a record behind the front
  whose configs all have a job already holds them at once — that is how a
  task with no sandbox never waits) from the run's `SetupCache`
  ([setup_cache.py](../src/inspect_ai/_eval/task/setup_cache.py)), which keeps
  one shared job per config and runs the jobs one at a time, in the order
  they were requested, except that a config someone needs now (a retry, a
  running task's `SampleSource`, the seed) goes ahead of queued tasks'
  setups. A record whose setup fails starts and ends with an error log (its
  retries apply); the failure is forgotten, so the retry sets up again.
- **The seed** is set up before the task display opens: every seed setup runs
  (output streamed, the first failure raises before any log exists), then
  each seed logger is created; it is initialised as the task starts.
- **The loop** (`TaskDispatcher.loop`) recomputes two stages from the run's
  tasks on each pass: `prepare_front_of_queue` requests the setups of the
  front of the queue, then `start_prepared_tasks` starts tasks while a slot
  is free under the live `max_tasks` limit, each the
  `earliest_of_least_busy_model` among the unpaused queued records whose
  setups are done or failed (a record whose setup is still running does not
  hold back a later prepared one). If any started, the front of the queue
  moved, so the pass repeats. Otherwise, while anything is queued or running
  it waits (`RunTasks.wait_for_change`) for a completion, an addition, a
  setup or a control change. Once nothing is, `add_tasks_from_source()` asks
  `next_tasks()` (until it first returns nothing) and queues its batch with
  `RunTasks.add_ahead`, ahead of any tasks added while it ran: those start
  only after it returns, behind its batch, so `next_tasks()` must not wait
  for them.
  With nothing left, the loop closes the run's tasks and ends.
- **Attempts** run in their slots (`run_one`: the task's logger is created or
  taken from the seed and initialised here, then the shared `_run_task`
  helper, a per-task cancel scope around `task_run`). The dispatcher also
  owns per-task retries (`task_retry_attempts`): a failed attempt is retried
  in the same slot — after any pause on the task lifts and whatever setup
  failed is set up again, ahead of queued tasks' setups — and the retry
  reinitialises the failed attempt's logger for a fresh log entry. Results
  are in the order the tasks were queued: the seed's input order, then added
  tasks in the order added, except that a `next_tasks()` batch comes ahead
  of the tasks added while it ran.

A cancellation (Ctrl-C, or a cancelled scope around `eval_async`) that lands
once the task display is open is absorbed (`_run_task_screen`) wherever the
dispatcher is: running tasks are cancelled and write `cancelled` logs, tasks
that have not started end without a log, and the run returns the logs written
so far, including the `cancelled` ones. On trio, `eval()` then raises
`KeyboardInterrupt`, as after every Ctrl-C (`run_main`). A cancellation while
the seed is set up, before the display opens, propagates.

`inspect ctl task cancel` or `drain` of a task none of whose attempts has
registered (given its full task id) ends it without running: one waiting to
start is ended by the directive itself (`RunTasks.cancel_waiting`); for one
starting, the directive abandons its next attempt (the process-wide set a
cancel between attempts uses), which bails in `task_run` before it registers.

Sandbox setup does not change the process's working directory or environment
variables (every running task shares them): providers read the task directory
from `sandbox_setup()`, and `inspect_ai.util.subprocess()` applies it and the
setup's environment variables to the child processes it starts.

Consequences of one dispatcher per run: task-level sandbox environments
(`task_init`) started for any generation are cleaned up once, at the end of the
run; one task display grows as tasks are added; and `inspect ctl config` sees a
live dispatcher (with its real `pending` count) for the whole run.

### Components

- **`SandboxManager`** ([run.py](../src/inspect_ai/_eval/run.py)) — sets up
  sandbox configs through the run's `SetupCache` (each once, whoever needs it)
  and accumulates cleanups, so injected tasks get sandboxes and everything
  tears down once at the end. The ContextVars each `task_init` sets are added
  to the run's provider state, which the loop sets in its own context before
  it starts each task, and each `task_cleanup` runs with the state its own
  `task_init` left, so a provider that keeps state in a ContextVar sees that
  state in its cleanup even after a later `task_init` of the same provider set
  it again.
- **`Display.update_task_count(n)`** ([display.py](../src/inspect_ai/_display/core/display.py))
  — bumps the "completed / total" denominator as tasks are injected (per-task
  progress views already grow on demand, the same path retries use). Implemented
  for the rich, plain, and textual displays; a no-op default for the log
  display. (Retries must *not* call this — they reuse a `task_id` and are deduped
  in the title; an injected task is a new `task_id`, so it does.)
- **`RunTasks.changed`** ([enqueue.py](../src/inspect_ai/_eval/task/enqueue.py))
  — set as tasks are queued, as a task ends, by each setup that ends, by a
  cancel of a waiting task, and (as a dispatch waker) by control changes,
  including a `max_tasks` change, which resizes the look-ahead window; the
  loop waits on it.

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
- [x] `sample_complete` / `task_complete` may **return** follow-up tasks (added
      with `enqueue_task` via `_enqueue_source_tasks`) — the simplest sources
      need no `next_tasks()`.
- [x] `TaskSource.from_tasks(...)` classmethod — build a source from a seed +
      callbacks without subclassing.
- [x] `@task_source` decorator (mirrors `@task`) + load-by-name: registered
      name, `@task_source` function, or `file.py@name` spec, with task-arg
      parameterization (`resolve_task_source`).
- [x] Threaded via `TaskRunOptions` (no global), per-sample and per-task firing.
- [x] `enqueue_task` imperative primitive backed by a `ContextVar`.
- [x] **One dispatcher per run**: a single `eval_run` and one
      `TaskDispatcher` for every run (a fixed run adds nothing; no separate
      dynamic path), incremental `SandboxManager`, growing display
      (rich / plain / textual), sequence-major order at `parallel == 1`.
- [x] Added tasks start on free capacity at any `max_tasks`, in the order
      added.
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
   the dispatcher's idle step (`add_when_idle`) up into eval_set. Real work, no
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
