# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns one `TaskHandle` per task and model it added. A
handle waits for its task to start or end and cancels it. Called from a
sample's own code (its solver, scorers or tools) with `send_samples=True`,
for a task whose dataset is a `SampleSource`, it also sends that task
samples and returns each sample's logged result, keeping the task open
until the handle is closed or its creator's attempt ends. A handle is
awaited, and a sample port opened, only while a sample's own code runs
(the tasks it starts included); task-level callbacks and hooks can still
add tasks and cancel or close handles. A task that a running sample is
waiting on borrows a slot when every slot is taken, so a search that drives
a rollout task works at the default `max_tasks=1`:

```python
@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [rollouts] = enqueue_task(rollout_task(), send_samples=True)
        for _ in range(n_steps):
            sample = await propose_next(state)
            [result] = await rollouts.enqueue_sample(sample)
            update(state, result)
        rollouts.close()
        return state

    return solve
```

`propose_next` is the searcher's own async function and may call a model:
the searcher's model through `generate`, or another one through
`get_model(...)`.

The design relies on anonymous dynamic samples having unique ids (a
companion change), so samples sent through a handle shift no id a later
run would reuse. A task that can receive samples records that in its eval
spec: nothing is reused from its logs, `eval_retry()` refuses them and
`eval_set()` never counts them complete, and once it has received a sample
it is not retried; its creator sends the samples to a fresh task instead.
Loans lend
task slots, never sandboxes or sample slots, so `max_sandboxes` and
`max_samples` need headroom for samples that wait through handles.

Handles build on the run queue and dispatcher of
[task-dispatch.md](task-dispatch.md): an added task is a `TaskRecord` in the
run's `RunQueue`, and it starts as soon as a slot is free.

## Why

A long-running task that decides what to try next from earlier results (an
adversarial search for misalignment, run for hours as one Inspect task)
needs to start rollout tasks beside itself, send them samples and wait for
each sample's result, under `eval()`, under `eval_set()`, and in eval-set
selection-mode workers. With [task-dispatch.md](task-dispatch.md) an added
task starts while its creator runs, but the creator still cannot use it:

- `enqueue_task()` returns `None`, so the caller cannot wait for the task,
  send it samples or cancel it.
- `enqueue_sample()` reaches only the calling task's own `SampleSource`.
- At the default `max_tasks=1`, and in a selection-mode worker whose
  supervisor sets `max_tasks` to its selected batch size, the creator holds
  the only slot while it waits for its rollout task, which therefore never
  starts.

## Goals and non-goals

Goals:

- A handle from `enqueue_task()` that waits, cancels, closes, and sends
  samples to a `SampleSource` task and returns their results, with one
  terminal outcome per method for every way the task can end; no wait
  hangs on the target's lifecycle (a `result()` on a sample-sending
  handle also needs the port closed; see "Keeping the task open").
- Samples sent through a handle obey the receiving task's selection rules
  (`--limit`, `--sample-id`) and share its remaining sample budget, so they
  can take budget that would otherwise run a source sample; tasks without
  handles keep their selection behavior. A request the port refuses fails
  only its sender. An accepted explicit id reserves its runs
  as a source sample's does, so a later duplicate from the source fails the
  task and its unresolved requests, as a source duplicate does today. No
  later run reuses one sample's result for another: the
  log of a task that can receive samples through a handle says so, and
  nothing is reused from it.
- The search example works at the default `max_tasks=1`. `max_sandboxes`
  and `max_samples` are never exceeded; a run that waits through handles
  needs headroom in them, which the docs state and a warning points out.

Non-goals:

- Handles that reach a task in another process (another selection-mode
  worker). A handle is in-process only.
- Recording which task added a task, and choosing the creator's model for
  an added task under `eval_set()`; see "Interactions" in
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- The queue, dispatcher, control channel and sandbox setup, which
  [task-dispatch.md](task-dispatch.md) owns.

## Current behaviour

- `enqueue_task()` (`src/inspect_ai/_eval/task/enqueue.py:91`) resolves and
  buffers tasks and returns `None`.
- `enqueue_sample()` (`src/inspect_ai/_eval/task/sample_source.py:267`)
  finds the calling task's own `SampleEnqueuer` through a `ContextVar` and
  returns nothing.
- A `SampleSource` task's feeder (`feed_samples`,
  `src/inspect_ai/_eval/task/run.py:1832-1865`) admits buffered samples,
  waits while samples are in flight, and when fully idle awaits
  `next_samples()` inline (`:1854`). Nothing buffered starts while that call
  blocks, and the source may block indefinitely (`sample_source.py:63`).
  A sample enqueued while `next_samples()` blocks does not run until it
  returns. A control-channel rerun
  (`inspect ctl` requeue) is the one thing that does start during the pull:
  the feeder's hold keeps `SampleScheduler.open`
  (`src/inspect_ai/_eval/task/scheduler.py:209`) true, and the rerun starts
  at once (`tests/_control/test_requeue.py:1885`). A follow-up its
  `sample_complete` returns is buffered and admitted after the batch the pull
  returns, so at `limit=2` with one seed the pull's sample runs and the
  follow-up is dropped.
- The feeder is the only caller of `add_samples` (through `add_and_start`,
  `task/run.py:1779`), so nothing else allocates ids or reserves runs while
  it awaits.
- Admission (`add_samples`, `task/run.py:1745`) reserves `(str(id), epoch)`
  runs. The reservations start from the complete seed before `--limit` or
  `--sample-id` slices it (`:810`, `:1689-1693`), so a dynamic sample can
  reclaim neither an excluded seed id nor an int/str-equivalent one, while a
  seed id at an epoch above the configured `epochs` is a distinct run
  (`:1710-1731`). A duplicate raises `ValueError` inside the receiving task
  and fails it. `--limit` counts distinct ids against a budget recomputed at
  each attempt (`:1674-1678`); `--sample-id` drops non-matching samples.
- A dynamic sample admitted without an id gets the next integer after the
  seed's size that is not already taken (`reserve_runs`, `:1701`,
  `:1712-1717`), so its id depends on its admission order. The companion
  change this design builds on (see "Logs of tasks that can receive
  samples") replaces that rule.
- On a task retry, the prior attempt's completed samples are reused, and a
  reused sample's `sample_complete` fires again so a completion-driven
  source regenerates its follow-ups (`:1473`); a limited feed's later
  admissions are seeded from the prior log as they are re-admitted
  (`:952-965`).
- Every per-sample reuse of a prior log goes through `eval_log_sample_source()`
  (`task/run.py:3743`), which returns the id-and-epoch lookup, the seed
  source and `prior_checkpoints_dir` (checkpoint resume keys on id and epoch
  too, and its existing guards already withhold it when ids are unstable,
  `:3812`). It has two callers: the in-run retry (`src/inspect_ai/_eval/run.py:979`)
  and `resolve_previous_task()` (`src/inspect_ai/_eval/loader.py:363`), which
  every `PreviousTask` reaches: `eval_retry()`
  (`src/inspect_ai/_eval/eval.py:1973`), eval-set resume in ordinary and
  legacy retry rounds (`src/inspect_ai/_eval/evalset.py:1148`, `:1530`) and
  selection-worker resume (`evalset.py:1763`). `enqueue_task()` passes
  its `Tasks` argument to `_resolve_enqueued_tasks`
  (`src/inspect_ai/_eval/eval.py:1291`), which resolves it like any other
  `Tasks` value: a `ResolvedTask` is passed through with its
  `sample_source`, and a `PreviousTask` (alone, in a list, or mixed with
  `ResolvedTask`s) goes through `resolve_previous_tasks()`
  (`src/inspect_ai/_eval/loader.py:134-145`, `:287-326`), so an added task
  can start with a prior lookup, seed and checkpoint directory
  (`tests/test_enqueue_task.py:147` enqueues a `ResolvedTask`).
- Whole logs are reused without that function in two places. `eval_set()`
  classifies each task's latest log in `list_latest_eval_logs()`
  (`src/inspect_ai/_eval/evalset.py:1857-1872`), after recovering crashed
  logs first under a resolving `incomplete_action` (`:1832-1846`), and
  returns a log it counts complete as the task's result without running it
  (`:1169-1184`); a task with no selected samples counts as complete at
  `planned == 0` (`:1904`). Steward, which supervises selection-mode
  workers, makes the same judgement itself: it reads each header into a
  `LogAttempt` (`inspect_steward/_evalset/observe.py:648`, at
  `a2f40bf97d`), whose completeness predicate (`:608-627`) decides both
  whether a task needs running (`:507`) and whether a log in its reuse
  store can be imported (`_store/match.py:74`); attempts are cached in a
  file versioned by `CACHE_VERSION` (`_evalset/cache.py:25`).
- A sample's own code runs in its task inside `task_run_sample`: the
  solver plan at `task/run.py:2873` (with the tools and subtasks it runs)
  and the scorers at `:3101`. Scorers run only for a sample with no
  cancellation error, so the shield at `:3084`, which is raised only after
  one, never covers them. An abort of the task (a handle-level or
  `inspect ctl task cancel`, or a run-level cancellation) cancels the
  task's scope (`src/inspect_ai/_eval/run.py:620-639`), and with it every
  sample's task group. The solver runs in a task started in the sample's
  task group (`task/run.py:3003-3004`), which `background()` also uses
  (`src/inspect_ai/util/_background.py`); the group is cancelled when the
  solver returns (`:2976`) and exits before scoring. Every way of starting
  a task copies the starting task's context, so a `ContextVar` set around
  the solver is seen by every task the solver starts: AnyIO task groups,
  `asyncio.create_task()`, and through it `asyncio.gather()` of coroutines
  and `asyncio.TaskGroup`.
- Inspect calls into `Hooks` objects in four places: `_emit_to_all`
  (`src/inspect_ai/hooks/_hooks.py:1166`), through which every async hook
  is awaited, including the streamed `on_sample_event` (`:812`) and the
  model hooks that `Model.generate` awaits inside the caller's context
  (`src/inspect_ai/model/_model.py:1526`, `:1583`, `:1779`, `:2989`);
  the synchronous `override_api_key` dispatch (`hooks/_hooks.py:1092`),
  which `Model` construction calls (`model/_model.py:354-377`);
  `any_hook_needs_full_sample()` (`hooks/_hooks.py:1151`); and the
  `enabled()` scan in `Model.generate` (`model/_model.py:1471`). A hook a
  solver's or scorer's model call triggers runs in that solver's or
  scorer's context. The deprecated environment-variable hooks bypass all
  four: `send_telemetry_legacy()` awaits its subscriber directly
  (`hooks/_legacy.py:42`), and `Model.generate` awaits it after the usage
  hooks (`model/_model.py:1782`), as `task_run` does for the log
  (`task/run.py:2122`, `:2127`); `override_api_key_legacy()` calls its
  subscriber directly (`hooks/_legacy.py:63-66`) and is the fallback the
  `override_api_key` dispatch returns (`hooks/_hooks.py:1104`).
- The sites that report a sample to the source are `task/run.py:1480`,
  `:1619` and `:3372` (`sample_complete`, and `sample_abandoned` for a
  sample cancelled before it was logged); the `TaskSource` calls, at
  `:1623` and `:3376`, run inside the attempt's sample task group. The
  `:3372` call runs after the sample's scoring but still inside its
  `active_sample()` context, so `sample_active()`
  (`src/inspect_ai/log/_samples.py:599`) is set there; the other two run in
  the task's own code.
- Outside a sample, a task's code can run where the control channel no
  longer reaches it:
  - once its `EvalState` is terminal, a cancel or drain answers
    `changed: false, reason: "task already finished"`
    (`src/inspect_ai/_control/cancel.py:311-332`), although `run_one` has
    not returned and the task still holds its slot. A dynamic `EvalState`
    (a `SampleSource` dataset, or any task under a `TaskSource`,
    `task/run.py:1210`) is stamped by `finalize_eval()` (`:2105`), before
    `TaskSource.task_complete` (`:2137`); a fixed dataset at its last
    terminal sample report (`_maybe_mark_finished`,
    `src/inspect_ai/_control/eval_state.py:1069`), before the early-stopping
    callbacks (`task/run.py:1312`, `:1951`) and the `on_task_end` hooks
    (`:1995`); a task with no samples at registration
    (`eval_state.py:500`), before its `on_task_start` hooks
    (`task/run.py:1216`);
  - when an attempt that can be retried ends in error, `finish_task_log`
    marks the retry pending before the `on_task_end` hooks run
    (`task/run.py:894-901`, `:1995`), with `completed_at` still unset; a
    cancel or drain then only abandons the retry and never calls the
    attempt's cancel callback (`cancel.py:296-332`), and abandoning clears
    `retry_pending` (`eval_state.py:897-919`).
- The dispatcher awaits `TaskSource.next_tasks()` inline, only when nothing
  is queued or running (`src/inspect_ai/_eval/run.py:1103`), so a task
  enqueued inside it starts only after it returns.
- A sample's sandboxes are counted by a process-wide limiter per provider,
  `sandboxes/<provider>` (`max_sandboxes`, or the provider's
  `default_concurrency()`), which `sandboxenv_context` holds from before
  `sample_init` until after `sample_cleanup`, across the whole solver
  (`src/inspect_ai/_eval/task/sandbox.py:118-128`, `:51-80`); the registered
  limiters are listed by `sandbox_limiters()`
  (`src/inspect_ai/util/_concurrency.py:488`). The sample limiter
  (`max_samples`) is per task (`task/run.py:3898`), and model connection
  slots are held only during a `generate` call
  (`src/inspect_ai/model/_model.py:1066`).
- A second `eval()` in the same process while one runs is refused
  ("Multiple concurrent calls to eval_async are not allowed",
  `src/inspect_ai/_eval/eval.py:797`).

## Design

### The handle API

`enqueue_task(tasks, *, run_id=None, send_samples=False) -> list[TaskHandle]`:
still synchronous, one handle per task × model it added, in resolution
order (decision: Ransom, 2026-11-03). New exports from `inspect_ai`:
`TaskHandle`, `TaskEndedError`, `SampleAbandonedError`.

`send_samples` decides whether the handles can send samples, and only then
does a task wait for its handles (see "Keeping the task open") (decision:
Ransom, 2026-11-03). With the
default `False` the added tasks run and end exactly as today, so existing
callers, which ignore the `None` returned today, are unaffected: a parent
that ignores the return value and waits for its child to finish (for
example on its `TaskSource.task_complete` event) still sees it finish.
`send_samples=True` checks, at the call and for every task it resolves:

- that it is called from a sample's own code, whose attempt becomes the
  creator: otherwise `RuntimeError`, the error a call outside a running
  task attempt raises (its port would close at once), raised the same way
  in `TaskSource.next_tasks()` and in every task-level callback and hook
  (see "Creator and sample code");
- that the dataset is a `SampleSource`: otherwise `TypeError` naming the
  task;
- that the resolved task carries no prior state
  (`ResolvedTask.sample_source is None`): a `PreviousTask`, or a
  `ResolvedTask` with a `sample_source`, raises `ValueError` ("tasks that
  receive samples through a handle must start fresh; pass the Task"). A
  prior lookup keyed on id and epoch could hand a sample sent with an
  explicit id the prior result of another sample with that id (see "Logs
  of tasks that can receive samples"). Those inputs stay supported with
  `send_samples=False`;
- that the run logs in the `.eval` format (the log format `eval()` or
  `eval_set()` resolved for its loggers): with the deprecated `.json`
  format it raises `ValueError` ("send_samples=True needs the .eval log
  format; the .json format is deprecated") (decision: Ransom, 2026-11-03).
  No tool sends samples into a `.json` run, so the deprecated format is
  refused rather than supported; the `enqueue_task()` docstring and the
  handle docs in `docs/task-source.qmd` say the same.

Nothing is enqueued when a check fails.

```python
class TaskHandle:
    task_id: str
    task: str                       # task name
    model: str
    @property
    def state(self) -> Literal["queued", "running", "ended"]:
        """The record's phase, mapped as in task-dispatch.md "Task phases"."""
    async def started(self) -> None:
        """Wait until the task's first attempt starts.

        Returns once an attempt has started (registered with the control
        channel), including one that then fails (a setup failure starts an
        attempt that writes an error log). Raises TaskEndedError if the task
        ends before any attempt starts: its log is None, or the latest log
        of attempts that ended before starting (a failed log_start() flush,
        or run_samples=False).
        """
    async def result(self) -> EvalLog | None:
        """Wait until the task ends.

        Returns its latest attempt's log, or None if no attempt returned one
        (cancelled while queued, admission failed, or the run ended first).
        Never raises TaskEndedError. Does not close a sample port: on a
        handle created with send_samples=True, call close() first (or close
        it from elsewhere), since the task stays open while its port is.
        """
    def cancel(self) -> None:
        """Abort it, like `inspect ctl task cancel`.

        A task cancelled before any attempt has registered ends with the
        log an earlier attempt stored, or none (see task-dispatch.md
        "Task phases"); a task waiting for a retry keeps its latest
        attempt's log.
        """
    def close(self) -> None:
        """Send no more samples; the task ends once its source is done and its samples have run."""
    async def enqueue_sample(self, sample: Sample, *, epoch: int | None = None) -> list[EvalSample]:
        """Run `sample` in the task and return its logged runs, one per epoch, in epoch order.

        Raises ValueError if the (id, epoch) runs are already reserved in the
        task, SampleAbandonedError if the task drops or abandons the sample,
        and TaskEndedError if the task ends before every epoch has a result.
        """

class TaskEndedError(RuntimeError):
    log: EvalLog | None             # the task's final log, None if no attempt returned one
    error: BaseException | None     # the admission failure, if that is why it never started

class SampleAbandonedError(RuntimeError):
    sample: Sample
    epoch: int
```

`cancel()` and `close()` are synchronous requests and idempotent.
`started()`, `result()`, `enqueue_sample()`, `cancel()` and `close()` each
first check that they run on the run's event loop, as `enqueue_task()`
does ("Only the run's event loop changes the queue" in
[task-dispatch.md](task-dispatch.md#the-run-queue)), and raise
`RuntimeError` there before any other check and without changing a record,
loan, wake or port; `state` and the attributes are plain reads and work
anywhere. Each
record has at most one handle per `enqueue_task()` call; under a run with
two models, `enqueue_task(task)` returns two handles, each addressing one
task × model.

**Terminal outcomes, per method.** Every record ends (a run-level
cancellation ends every queued record with no log), so no wait outlives its
target. What each wait does when the target ends:

| how the target ended | `started()` | `result()` | an `enqueue_sample()` request still unresolved |
| --- | --- | --- | --- |
| one or more attempts ran (success, error, setup failure, abort, run-level cancellation of a running task), including a task cancelled, drained or left queued at run end while waiting for a retry | returned when the first attempt started | the latest attempt's log | `TaskEndedError(log=<latest log>)` |
| every attempt returned a log without starting (a startup error converted to an error log, with the retry budget spent, the retry abandoned, or a cancel pending; `run_samples=False`'s `started` log); see "Task phases" in [task-dispatch.md](task-dispatch.md#task-phases) | `TaskEndedError(log=<latest log>, error=None)` | the latest attempt's log | `TaskEndedError(log=<latest log>)` |
| cancelled or drained, or the run ended, before any attempt ran | `TaskEndedError(log=None, error=None)` | `None` | `TaskEndedError(log=None, error=None)` |
| admission failed (`ensure_model_controller` or `logger.init()` raised) | `TaskEndedError(log=None, error=exc)`, with `__cause__` set | `None` | `TaskEndedError(log=None, error=exc)` |

A retry waiting in the queue is not a never-started task: cancelling it
(through the handle or `inspect ctl task cancel`/`drain`), or the run ending
first, abandons the retry exactly as today's retry-abandon path does
(`src/inspect_ai/_eval/run.py:871`, `:1064`), discarding only the retry's
unstarted logger and keeping the error log the dispatcher stored before
queuing it (`run.py:1036`); see "End of run" in
[task-dispatch.md](task-dispatch.md#the-dispatcher).

A setup failure is an ordinary attempt in
[task-dispatch.md](task-dispatch.md#sandbox-setup-1): it registers, fires
`on_task_start` and writes an error log, so `started()` returns and
`result()` returns that log (after any retries). A request that already
has a result keeps it; one dropped or abandoned keeps its
`SampleAbandonedError`; one refused as a duplicate keeps its `ValueError`.
A cancelled caller's wait raises the cancellation; the sample it sent still
runs and its result is dropped.

### Run shapes and what is refused

Handles are returned to `enqueue_task()` callers in a solver, scorer, tool
or `TaskSource` callback, under `eval()`, `eval_set()` and selection mode;
they are awaited, and ports opened, only from a sample's own code (see
"Creator and sample code"). Everything else is refused with a clear error:

- `enqueue_task(..., send_samples=True)` outside a sample's own code (for
  example in `TaskSource.next_tasks()`, `sample_complete` or
  `task_complete`), for a task whose dataset is not a `SampleSource`, for a
  task with prior state, or in a run that logs in the `.json` format: the
  errors under "The handle API".
- `TaskHandle.enqueue_sample()` on a handle created with
  `send_samples=False`, or after `close()`: `RuntimeError`.
- `TaskHandle.enqueue_sample()` after a drain, or a `score` or `error`
  cancel, of its task: `SampleAbandonedError` (see "Keeping the task
  open").
- `TaskHandle.enqueue_sample()` after the task has ended: `TaskEndedError`
  as in the table.
- Awaiting `started()`, `result()` or `enqueue_sample()` inside
  `TaskSource.next_tasks()`: `RuntimeError` ("a task handle cannot be
  awaited inside TaskSource.next_tasks(): no task starts until
  next_tasks() returns; return the task, and wait for it from a running
  task"). The dispatcher awaits `next_tasks()` inline (see
  "Current behaviour"), so it could never start the awaited task. The
  dispatcher sets a `ContextVar` around that await, and the handle checks
  it before waiting. Calling `enqueue_task()` there, and `cancel()` or
  `close()` on its handles, stays allowed.
- Awaiting `started()`, `result()` or `enqueue_sample()` anywhere else
  outside a sample's own code (see "Creator and sample code"): in a
  `SampleSource`'s `next_samples()`, `sample_complete` or
  `sample_abandoned`; in `TaskSource.sample_complete`, `sample_abandoned`
  or `task_complete`; in early-stopping callbacks; in any hook
  (`on_task_start`, `on_task_end`, the sample hooks, and the model hooks,
  `override_api_key` and the legacy telemetry and API-key hooks even when a solver's or scorer's model call runs
  them); in a task started from a sample's code once that code has ended
  (a detached `asyncio.create_task()` still running after its sample); or
  in code the run did not start inside a sample: `RuntimeError` ("a task
  handle can be awaited only from a sample's solver, scorer or tools, or
  tasks they start, while the sample runs; wait for it there"). The check runs before the call blocks, so it never waits and
  never creates a loan; it applies to every handle, whether
  `enqueue_task()` returned it there or a sample kept it. Still allowed
  there, and everywhere in a running eval as today: `enqueue_task()`
  without `send_samples`, whose tasks run as today; the non-blocking calls
  on any handle, `cancel()`, `close()`, `state` and the `task_id`, `task`
  and `model` attributes; and the task's own `enqueue_sample()`
  (`sample_source.py:267`), which is not a handle call: it buffers a
  sample in the calling task's own source without waiting, and stays
  usable from `sample_complete` and the other source callbacks exactly as
  today.
- `eval_retry()` of a log whose task could receive samples through a
  handle: `PrerequisiteError` (see "Logs of tasks that can receive
  samples").
- `enqueue_task()` or any handle method other than `state` and the
  attributes, from a thread other than the run's event loop, including an
  `anyio.to_thread.run_sync()` worker whose copied context passes the
  sample-code check: `RuntimeError`, before that check and before any
  record, loan, wake or port changes. A worker calls them through
  `anyio.from_thread.run_sync()`, which runs the call on the loop with the
  worker's copied context, so the sample-code check then applies as for
  any task the sample started.

### What the handles add to the run queue

[task-dispatch.md](task-dispatch.md#the-run-queue) defines `TaskRecord`,
`RunQueue`, admission and the dispatch loop. This design adds to the record:

```python
    creator: TaskAttempt | None      # the attempt whose sample called enqueue_task(), if any
    port: SamplePort | None = None   # only when the dataset is a SampleSource
    loan: Loan | None = None         # see "Slot lending"
```

and to the dispatch loop one step after the ordinary picks, with the
ordinary count excluding attempts running on a loan:

```
    while not cancelled and ordinary_in_flight < effective_max_tasks(parallel):
        ... ordinary picks, unchanged ...
    for record whose loan is not running an attempt, in queue order,
            whose next entry is startable (the record itself in admitted,
            or its pending retry):
        if that entry is the record: move it to starting, as an ordinary pick does
        set loan.started; start run_one(entry, on_loan=True)
```

#### Creator and sample code

One fact decides where handle work may begin: **a sample of the calling
task is running its own code**: its solver, with the tools and subtasks the
solver runs, or its scorers, and the tasks they start while that code
runs, but not a hook either of them triggers. Only there may code call
`enqueue_task(..., send_samples=True)`, `TaskHandle.started()`, `result()`
and `enqueue_sample()`; the creator is the attempt the sample belongs to.
`enqueue_task()` called anywhere else has no creator.

```python
@dataclass(eq=False)
class SampleCode:
    attempt: TaskAttempt             # the attempt the sample belongs to
    live: bool = True                # cleared when the sample's own code has ended

_sample_code: ContextVar[SampleCode | None]   # in enqueue.py, default None
```

- **Setting it.** `_run_task` sets a `ContextVar` per attempt to its
  `TaskAttempt`. For each run of a sample (a sample-level retry is a new
  run), `task_run_sample` creates a `SampleCode` before the solver, and sets
  `_sample_code` to it around the solver plan (`task/run.py:2873`) and
  around the scorer loop (`:3101`), resetting it after each. A `finally`
  that ends the sample's own code (after the scorer loop, or when the run
  leaves by error or cancellation), before the source callbacks at
  `:3369`, sets `live = False`.
- **Hooks clear it.** Every call into a `Hooks` object, its `enabled()`
  and `needs_full_sample()` predicates included, runs under a
  `hook_call()` context manager (in `hooks/_hooks.py`) that sets
  `_sample_code` to `None` and resets it on return or on an exception. The
  calls are: `_emit_to_all` around each hook's `enabled()` check and
  `await callable(hook)` (`hooks/_hooks.py:1166`), which covers every async hook, including the
  model hooks a solver's or scorer's `generate` awaits (before-generate,
  usage, cache usage, retry) and the streamed `on_sample_event`; the
  synchronous `override_api_key` dispatch (`:1092`), which a model
  constructed inside a solver reaches; `any_hook_needs_full_sample()`
  (`:1151`); the `enabled()` scan in `Model.generate`
  (`src/inspect_ai/model/_model.py:1471`); and, inside each of the two
  legacy hook functions around its subscriber's call,
  `send_telemetry_legacy()` (`hooks/_legacy.py:42`, which `Model.generate`
  awaits after the usage hooks) and `override_api_key_legacy()`
  (`hooks/_legacy.py:63-66`, the `override_api_key` dispatch's fallback).
  These are all the places Inspect calls hook code, whether a `Hooks`
  object or a legacy subscriber (see "Current behaviour"). A hook
  can therefore add tasks and cancel or close handles, but cannot open a
  port or wait, wherever it is called from.
- **Tasks started from sample code.** The guard (`_eligible() ->
  SampleCode | None` in `enqueue.py`) reads `_sample_code` and allows the
  call only when the value is set and `live` is true. A task started from
  sample code inherits the value however it was started, because it copies
  its starter's context: in an AnyIO task group (the solver itself, started
  in the sample's group at `:3003-3004`; its subtasks through `tg_collect()`
  and `collect()`; agent and tool task groups; the scorers' own groups),
  with `background()`, under `asyncio.gather()` or `asyncio.TaskGroup`, with
  a raw `asyncio.create_task()`, or in a group another component owns. Each
  may open a port and wait while the sample's code is live, so a batch such
  as `await asyncio.gather(*(rollouts.enqueue_sample(s) for s in batch))`,
  the form `docs/parallelism.qmd` recommends for concurrent work in a
  solver, works as written. Once the sample's own code has ended, `live` is
  false for every copy, so a task that outlives it (a detached
  `asyncio.create_task()`) begins nothing new: each later
  `send_samples=True`, `started()`, `result()` or `enqueue_sample()` call is
  refused. A worker thread started from sample code
  (`anyio.to_thread.run_sync()`) copies the value too, but is not on the
  run's event loop; the loop check, which runs first, refuses it (see "Run
  shapes and what is refused").
- **Lifetime.** A wait begun in a task the sample joins ends with the
  sample: the solver's group is cancelled when the solver returns (`:2976`,
  which also ends `background()` work) and exits before scoring, each
  scorer's groups exit before it returns, and an awaited `asyncio.gather()`
  or `asyncio.TaskGroup` cancels its children when its caller is
  cancelled; an abort, through the handle, the control channel or a
  run-level cancellation, cancels the sample's group, and no shield covers
  the solver or the scorers (see "Current behaviour"). A wait that a
  detached task began while the sample's code was live is not cancelled
  when the sample ends, as nothing else a detached task does is today, and
  needs no cancel path of its own. What a wait holds is its share of its
  target's loan, which the attempt it ran in (`SampleCode.attempt`)
  justifies by holding a slot; that attempt belongs to the task, not the
  sample, so it keeps its slot while the task's other samples run, and when
  it ends its waits leave the loan (see "Slot lending", Lifetime). An
  attempt already started on the loan runs to its end, as for any wait
  that returned, so the bound on borrowed slots holds. The wait itself
  settles when its target ends, as every wait does ("Terminal outcomes"
  under "The handle API"). A port the attempt opened closes as "Keeping
  the task open" says, whichever task opened it.

Everything else is outside it and refused as "Run shapes and what is
refused" lists, including the source callbacks, which run after the
sample's scoring (`sample_complete` runs inside the sample's
`active_sample()` context, which is why the check reads `_sample_code`
rather than `sample_active()`). Outside a sample, the control channel can
stop reaching a task while its code still runs (a terminal `EvalState`,
or a retry-pending teardown whose cancel only abandons the retry; see
"Current behaviour"), and hooks such as `on_sample_scoring` can run under
a shield. Refusing there needs neither a list of those regions nor a
cancel path for them, and the use case never waits there: a search waits
on its rollouts from its solver. The guard reads `_sample_code` (and,
for its own message, the dispatcher's `next_tasks()` `ContextVar`) and
changes nothing in the control channel's registry: the existing timestamps and cancellation
behaviour stay as they are. `RunQueue.end` also clears `loan` and closes
the port, releasing its requests.

### Sending samples

A record added by `enqueue_task(..., send_samples=True)` has a
`SamplePort` (in `enqueue.py`), created when the record is configured;
no other record has one. It keeps a `PortRequest` for each
`enqueue_sample()` call until the call's outcome is settled:

```python
@dataclass(eq=False)
class PortRequest:
    sample: Sample                   # the port's own copy; an id assigned at delivery is set on it
    explicit_id: bool                # whether the caller's sample had an id when sent
    epoch: int | None
    state: Literal["sent", "admitted", "dropped", "refused", "done"]
    futures: dict[int, Future[EvalSample]]   # one per planned epoch

class SamplePort:
    pending: list[PortRequest]       # not yet settled, in send order
    runs: set[tuple[str, int]]       # (str(id), epoch) of every request that reserved runs
    closed: bool                     # close(), cancel(), creator attempt or run ended
    stopped: bool                    # a graceful directive: also ends the source
    delivered: bool                  # a request has passed step 1 of "Delivery"; never cleared
```

**Retention.** A request stays in `pending`, with its sample, until every
epoch's future has settled (a result, `SampleAbandonedError`,
`ValueError` or `TaskEndedError`). The port then drops it: the
`enqueue_sample()` call holds the futures and returns their values, and
neither the port nor the record keeps the sample, the futures or the
`EvalSample`s after that. Only the request's `(str(id), epoch)` runs stay,
in `runs`, for the duplicate check below; a refused request never adds
any. A pending request is kept until it is delivered and settled, or
settled without delivery, including across an in-run retry. So an
hours-long rollout task's port holds its pending requests and one small
tuple per run. This is about the port's own references: the runner and
the recorder keep theirs as they do for any injected sample. The runner
keeps an errored or cancelled sample so the control channel can requeue
it, and releases the others when they complete (`task/run.py:1018-1028`,
`:1040-1059`); the recorder keeps an `EvalSample` until its buffered write
is flushed (`src/inspect_ai/log/_recorders/eval.py:1152`, `:1277`;
`src/inspect_ai/_eval/task/log.py:778`). Neither changes.

**Ownership.** `enqueue_sample()` first takes its own copy of the caller's
sample, `sample.model_copy()`, and records `explicit_id = sample.id is not
None`. Every later step (the check at the call, the delivery check and
`add_samples`) uses that copy. The runner's allocator
assigns an automatic id by rebinding the top-level `id` field of the sample
it reserves (`reserve_runs`, `task/run.py:1710-1717`), and nothing else it
does changes the sample object, so a shallow copy is the depth needed: the
id lands on the copy, and the nested input, metadata and files stay shared
and read-only, as a source's own samples share them with its dataset
today. So the caller's object never gains an id, and one anonymous
`Sample` sent to two tasks, or to two task × model handles, gets an
automatic id in each target independently, and neither target sees the
other's id as an explicit one.

**Validation at the call.** `enqueue_sample()` validates `epoch` as the
task-side `enqueue_sample()` does. For a sample with an explicit id it computes the
planned runs with the runner's canonical rule (`(str(id), epoch)`, or
`(str(id), 1..epochs)` when `epoch` is `None`) and raises `ValueError` to
the caller, without reaching the task, when they intersect:

- the target's seed reservations: every seed id before `--limit` or
  `--sample-id` slicing, at epochs `1..epochs`, which the port computes
  from the configured task when the record is configured, exactly as the
  attempt does at start (`task/run.py:810`, `:1689-1693`). So an id equal
  to a seed id, an int/str-equivalent of one (`1` and `"1"`), or an
  excluded seed id is refused while the target is still queued; a seed id
  at an explicit epoch above `epochs` is accepted, as the runner accepts
  it;
- the runs of earlier requests on this port (`SamplePort.runs`);
- while an attempt runs, that attempt's own reservations.

A sample without an id is given one at delivery by the runner's rule for
anonymous dynamic samples, which under the companion change is unique (see
"Logs of tasks that can receive samples").

**Delivery.** While an attempt runs, the port is attached to that attempt's
feeder (after `log_start`, `task/run.py:1127`), which delivers requests as
they arrive, so a request starts as soon as `max_samples` allows; a request
sent while the task is queued is delivered when its first attempt starts.
The source's own additions can still reserve an id between the check at
the call and the delivery (the source returns or enqueues the same id
first). The feeder therefore delivers each request on its own, in two
steps:

1. It checks the request's planned runs against the attempt's reservations,
   the same check `reserve_runs` makes (`task/run.py:1710-1731`) without
   reserving anything. A clash makes the request **`refused`**: nothing is
   reserved, allocated or written, its futures fail with the same
   `ValueError`, and the receiving task continues. Only an explicit id can
   clash; an automatic id never does. A duplicate from the source's own
   samples still fails the task, as today.
2. It sets `SamplePort.delivered`, which ends the task's in-run retries
   (see "No in-run retry after a delivery" under "Logs of tasks that can
   receive samples"), and calls `add_samples` with the request alone,
   which reserves its runs and gives it an automatic id if it has none.
   The feeder is the task's only admitter (see "Current behaviour"), so
   nothing changes the reservations between the two steps. It then records
   one of:
   - **`dropped`**: `--sample-id` or `--limit` filtered it out after
     reservation (`task/run.py:1749-1755`), as for the source's own
     samples. Its futures fail with `SampleAbandonedError`, so a caller
     never waits for a sample that will not run.
   - **`admitted`**: `add_samples` accepted it, with the id it was given.

**Results.** At the sites that already report samples to the source (see
"Current behaviour"), before the source's own `sample_complete` the port
resolves the matching future with the `EvalSample` (an errored or
operator-cancelled sample is returned, with its `error`); before
`sample_abandoned` it fails the future with `SampleAbandonedError`.
`enqueue_sample()` returns when every epoch's future has resolved; the
request is then `done` and leaves the port (see "Retention").

### The feeder services the port while the source blocks

`SampleSource.next_samples()` may block indefinitely
(`sample_source.py:63`), and today the feeder awaits it inline
(`task/run.py:1854`), so nothing buffered starts until it returns: a
sample enqueued while `next_samples()` blocks does not run until it
returns. `feed_samples` changes so that a pull never
blocks the port, while everything the source adds keeps today's order:

```
async with task group tg:                  # owned by the feeder
    pull = None                            # the one outstanding next_samples() call
    while True:
        await checkpoint()
        if port.stopped and not source_done:   # drain or score/error (see "Keeping the task open")
            if pull is not None: cancel pull's scope and await its end; pull = None
            source_done = True; continue
        if pull is done:                   # checked first: a returned batch keeps priority
            more = pull.result(); pull = None
            if more: await add_and_start(more)
            held = await add_and_start(enqueuer.drain())   # the source's additions during the pull
            source_done = more is None and not held and not port_during_pull
            continue
        if requests := port.drain():       # handle samples, delivered one by one (see "Delivery")
            if await deliver(requests):
                if pull is not None: port_during_pull = True
                else: source_done = False
            continue
        if pull is None and (buffered := enqueuer.drain()):   # held while a pull is outstanding
            if await add_and_start(buffered): source_done = False
            continue
        if scheduler.outstanding > 0:
            await feeder_wake.wait(); continue   # rung by settle, enqueue, pull done, port send or close
        # no samples in flight or buffered
        if limit exhausted:                    # held additions: over the limit, as today, except
            if await add_and_start(enqueuer.drain()): continue   # more epochs of an admitted id
            break                              # nothing can start: an outstanding pull is cancelled below
        if pull is not None: await feeder_wake.wait(); continue
        if not source_done:
            port_during_pull = False
            pull = start next_samples() in tg, in its own cancel scope
            continue
        if not (port.closed or port.stopped): await feeder_wake.wait(); continue
        break
    cancel tg                              # an outstanding pull is cancelled, then joined
```

- A pull starts only when the task is fully idle, as today, and at most one
  is outstanding. It runs as a child of the feeder's task group, so it is
  joined before the feeder returns, its exception fails the task as an
  inline pull's does today, and a task cancel, a run cancel or the task
  ending cancels it with the feeder.
- **Only handle samples start while a pull blocks.** Everything the source
  adds while a pull is outstanding stays in the `SampleEnqueuer` buffer, in
  arrival order, and is admitted when the pull completes, after the batch it
  returns: what `next_samples()` itself enqueues, and the follow-ups that
  `sample_complete` returns for samples finishing meanwhile, whether those
  are control-channel reruns (which start during a pull today, see
  "Current behaviour") or samples sent through a handle. That is today's
  order exactly: the feeder awaits the pull inline, admits the returned
  batch, and drains the buffer on its next pass (`task/run.py:1854-1865`).
  So `--limit` and `--sample-id` select exactly the samples they select
  today, and ids are assigned in today's producer order: explicit ids as
  today, anonymous ones by the unique-id rule this design builds on (see
  "Logs of tasks that can receive samples"). Today, with an empty
  seed and `limit=1`, a `next_samples()` that enqueues A and returns `[B]`
  runs B; with one seed at `limit=2`, a rerun of the seed during a blocked
  pull whose `sample_complete` returns A, while the pull later returns B,
  runs B and drops A. The design keeps both.
- **Handle samples start at once.** While a pull is outstanding and still
  blocked, requests arriving through the port are delivered as they arrive,
  ahead of whatever the pull later returns, and their `sample_complete` and
  `sample_abandoned` may fire while `next_samples()` is still awaiting. The
  `SampleSource` docstrings say so. Under `--limit` they take the limit in
  arrival order. When the feeder observes a completed pull and port
  requests in the same pass, the pull's batch and the held additions go
  first and the requests follow.
- **A late addition always earns a repull.** When the pull returns `None`,
  the source is consulted again after the samples added during or at the
  end of that pull have run: `held` records the source's own additions and
  `port_during_pull` the requests delivered while the pull was outstanding,
  so the pull's `None` cannot erase them. That is today's rule for a late
  enqueue during a terminal call (`task/run.py:1855-1860`,
  `sample_source.py:69`): today a `next_samples()`
  that enqueues a sample and returns `None` is called again and its next
  batch runs.
- **An exhausted limit ends the task only when nothing more can start.**
  `--limit` counts distinct ids, and another epoch of an admitted id is
  still admitted at zero budget (`task/run.py:1734-1742`). So when the task
  is fully idle and the limit is exhausted, the feeder first admits the
  held additions; if any of them starts (an epoch 2 a callback returned for
  an admitted sample), it goes round the loop again, admitting each
  callback's further epochs in turn, and only when an idle pass starts
  nothing does it cancel an outstanding pull and end the task, since
  nothing the pull returned could run.
- A port closing does not end an outstanding pull: the source still decides
  when the task ends. An open port only keeps the task from ending after
  the source is done.

### Keeping the task open

A task with an open port does not end when its source is exhausted: the
feeder waits for the port (a new sample or a close) instead of finishing.
Only `send_samples=True` creates a port, so a caller that asks for one has
said it will send samples. The port closes on `close()`, on `cancel()`,
when the task attempt that created the handle finishes (`task_run` closes
the ports its attempt created beside its `finalize_eval()` call, before
`TaskSource.task_complete`; an attempt that ends without reaching
`finalize_eval()` closes them when `run_one` returns), and when the run
ends.
So a creator that forgets `close()` cannot keep a rollout task open past
its own attempt, and a task added without `send_samples` ends when its
source is done, as today.

`result()` does not close the port. A creator that awaits `result()` on a
sample-sending handle whose port is still open waits until something
closes it: its own `close()` before the wait, another closer it arranges
(a sibling sample, a `cancel()`, a drain), or the run ending. Lending
starts the target but cannot end it, so the creator's own attempt, still
waiting, never reaches its automatic close. The docs and the `result()`
docstring say to close first; nothing detects the cycle.

**Graceful directives stop the port.** A control-channel drain, or a task
cancel with `action="score"` or `action="error"`, stamps the attempt's
`TaskCancel` through its `cancel_task` callback
(`src/inspect_ai/_control/cancel.py:403-430`), which `_run_task` defines
(`src/inspect_ai/_eval/run.py:620-639`) and which cancels the task's scope
only for abort and retry. That callback is the one shared hook: for
`drain`, `score` and `error` it also calls `SamplePort.stop()` on the
attempt's port, if it has one. `stop()` is synchronous and idempotent:

- it sets `stopped`, so the port admits nothing more: a later
  `enqueue_sample()` raises `SampleAbandonedError` at once, and the feeder
  delivers no further request;
- it ends the source: on its next pass the feeder cancels an outstanding
  `next_samples()` call, which may block for ever by contract
  (`sample_source.py:63-70`; `tests/_control/test_requeue.py:1868` has
  one), through the pull's own cancel scope, awaits its end, and starts no
  further pull. The cancellation stays inside that scope, so it does not
  fail the task, and whatever the cancelled call had enqueued stays in the
  buffer and is admitted, then abandoned or resolved, under the
  directive's rules like any queued sample;
- it settles every `sent` request (accepted but not yet delivered) with
  `SampleAbandonedError`, as the directive abandons the task's queued
  samples;
- it leaves `admitted` requests to the directive's existing rules: under a
  drain an in-flight sample finishes naturally and resolves its future with
  its `EvalSample`, and a queued one is abandoned as it leaves the queue
  (`SampleAbandonedError`); under `score` or `error` an in-flight sample is
  interrupted and resolves with the scored or errored `EvalSample`, as
  under "Results";
- it rings `feeder_wake`, so a feeder parked on an open port or an
  outstanding pull sees it stopped. Once the samples already admitted have
  finished or been abandoned under the directive, the feeder ends and the
  task finishes.

A task without a port is untouched: its feeder handles a graceful
directive exactly as today.

An abort (including `TaskHandle.cancel()`) or a run cancellation tears the
attempt down and closes the port as above; a `retry` directive leaves the
port open, so its `sent` requests reach the retry.

### Logs of tasks that can receive samples

This design builds on a companion change in Inspect, **unique ids for
anonymous dynamic samples** (decision: Ransom, 2026-11-04). Every sample a
task admits without an id after its seed (from `next_samples()`, the task's
own `enqueue_sample()`, a callback follow-up, or a handle) gets an id no
other attempt or run gives a sample, such as a UUID string, instead of the
next free integer (see "Current behaviour"). Seed samples and explicit ids are unchanged. So an
anonymous dynamic sample's id never appears in another attempt: a lookup or
a checkpoint resume misses, and the sample runs fresh. Port deliveries
therefore shift no id that a rerun would reuse. With integer ids and an
empty seed, source sample A would get id 1, port request P id 2 and P's
callback follow-up B id 3, and a later run without P would give B id 2 and
hand it P's result; with unique ids each of the three has an id of its own
that no later run gives anything.

What the design records, and which restrictions stay, and why:

- **The record.** A new `EvalSpec` field, `send_samples: bool = False`,
  after `task_args_passed`: "the task was added by
  `enqueue_task(..., send_samples=True)` and could receive samples through
  a `TaskHandle`; no later run reuses its samples or checkpoints, and
  `eval_retry()` refuses it". `admit_task()` passes
  `send_samples=record.port is not None` to the `TaskLogger` it constructs
  (see [task-dispatch.md](task-dispatch.md#the-run-queue)), which sets it on
  the spec it builds (`src/inspect_ai/_eval/task/log.py:282`); `reinit()`
  copies that spec for a retry (`:425`). Being part of the spec, the field
  is in the log from its first write: `start.json` of an unfinished `.eval`
  log, the header of a finished one, the errored `EvalLog` that `_run_task`
  builds when a log write escapes the attempt (`eval=options.logger.eval`,
  `src/inspect_ai/_eval/run.py:682-687`), and every copy, since whole-log
  writes, conversion, streamed `inspect score` and crashed-log recovery all
  write the source's spec from their first write
  (`src/inspect_ai/log/_convert.py:158-159`,
  `src/inspect_ai/_cli/score.py:253-254`,
  `src/inspect_ai/log/_recover/_write.py:146-147`). No copy path changes
  and no write is added. It records the capability, not a delivery: a
  rollout task whose creator never sent it a sample carries it too
  (decision: Ransom, 2026-11-04), and loses reuse and `eval_retry()`
  (below), neither of which a task fed by its creator can use; it keeps its
  in-run retries ("No in-run retry after a delivery").
- **No reuse from such a log** (stays, for explicit ids). Anonymous port
  samples, and the anonymous samples admitted after them, are safe under
  the companion rule. A port sample sent with an explicit id is not: no
  rerun regenerates it, and a rerun's own source can produce the same id.
  In a log where request P with id `"x"` completed, a rerun whose source
  adds a sample `"x"` (which the first attempt could not do after P
  without a duplicate failure) would be handed P's result by the lookup by
  id and epoch (`task/run.py:3843`, `:3870`), and checkpoint resume would
  restore P's state into it. The same can happen inside the run: an in-run
  retry (which follows only an attempt without a delivery, below) whose
  failed attempt's source completed `"x"` can admit a request P with `"x"`
  before its source adds `"x"` again, and the lookup returns the source
  sample's result for P. The log does not say which samples came through
  the port, so `eval_log_sample_source()` returns the empty source (no
  lookup, no seed, no `prior_checkpoints_dir`) for a log whose
  `eval.send_samples` is set, with a warning naming it, before its other
  guards. That one check covers every path that reuses a prior log (see
  "Current behaviour"), for samples and checkpoints alike: the in-run retry,
  whose two branches (`src/inspect_ai/_eval/run.py:968-995`) either build
  the source from the failed attempt's log, which carries the field, or keep
  the source the failed attempt ran with, which for such a task is none (the
  first attempt starts clean, below) or the empty source; `eval_retry()`;
  eval-set resume in ordinary and legacy rounds; and selection-worker
  resume. Checkpoints and epochs need nothing more:
  checkpoint resume keys on `(id, epoch)` as the lookup does, so another
  attempt never finds an anonymous sample's checkpoints, and the empty
  source copies none; a request at an explicit epoch reserves that
  `(id, epoch)` like any run.
- **The first attempt starts clean** (stays, for the same reason):
  `send_samples=True` refuses a task with prior state ("The handle API"),
  whose lookup could hold an explicit id a request then takes.
- **Never counted complete** (stays; Ransom's decision, which does not
  depend on ids).
  `list_latest_eval_logs()` puts a log whose `eval.send_samples` is set
  among the incomplete logs whatever its status, checked with
  `invalidated` (`src/inspect_ai/_eval/evalset.py:1858-1861`) and so after
  any resolving recovery has finalized it, so `eval_set()` never returns
  such a log, which holds samples a creator sent, as an existing success;
  it reruns the task through a `PreviousTask`, which reuses nothing (above).
  The deprecated `retryable_eval_logs()` (`src/inspect_ai/log/_retry.py`)
  lists logs for `eval_retry()`, which refuses such a log.
- **Steward does the same** (a companion change in `inspect_steward`).
  `LogAttempt` gains `send_samples: bool`, read from the header's eval spec
  in `_attempt()`; `_incomplete_reason()` returns a new
  `IncompleteReason.SEND_SAMPLES` for such an attempt before its other
  checks, so the log is never counted complete and never imported from the
  reuse store (`_store/match.py` skips it and logs why); `CACHE_VERSION`
  goes up because `LogAttempt` changes shape, so attempts cached without
  the field are re-read. Steward then runs the task again, and if it
  resumes from that log, Inspect's own check reuses nothing. Steward's
  `inspect-ai` floor rises to the first release with
  `EvalSpec.send_samples`, since it reads the field.
- **No in-run retry after a delivery** (stays; it does not depend on ids).
  `SamplePort.delivered` is set when a request first passes step 1 of
  "Delivery" and is never cleared. Setting it also clears the attempt's
  `TaskCancel.can_retry` and the `will_retry` it registered with the control
  channel (`task/run.py:897`, `:1200`), and the dispatcher's retry decision
  (`src/inspect_ai/_eval/run.py:921-923`) reads it from the record, so
  neither a fallback log nor a failed final write turns the attempt back
  into a retry. A retry would rerun the task without the samples its
  creator sent, so it ends with its error log: every unresolved future
  fails with `TaskEndedError(log=<that log>)` (the table above), `result()`
  returns that log, and the creator, which holds the search state, decides
  what to do, typically enqueueing a fresh rollout task and sending the
  outstanding samples again. A task whose port delivered nothing (for
  example, its first attempt failed in sandbox setup before any request
  arrived, or its only request was refused) is retried, reusing nothing
  (above), and its `sent` requests are delivered into the retry as new
  arrivals, including requests accepted before `close()` and those whose
  caller was cancelled.
- **`eval_retry()` refuses such a log** (stays; Ransom's decision, which
  does not depend on ids) with `PrerequisiteError` ("<log> cannot be
  retried on its own: task '<task>' was added to receive samples through a
  task handle from the task that created it; retry that task instead"),
  checked when the logs are read (`src/inspect_ai/_eval/eval.py:1712`),
  before any recovery writes. With no creator, a rerun would lack the
  samples it was sent and could end `success` while missing them. After a
  restart, the creator's own task reruns and enqueues fresh rollout tasks.
- **Restarting under `eval_set()` needs `log_dir_allow_dirty=True`.** Every
  added task writes its own log into the eval set's log directory, under
  its own task identifier, which is not one of the tasks passed to
  `eval_set()`. `validate_eval_set_prerequisites()` rejects such a log
  before any classification unless `log_dir_allow_dirty` is set
  (`src/inspect_ai/_eval/evalset.py:1091`, `:2085-2095`; it defaults to
  false, `:999`), both in a later legacy retry round of the same call
  (`retry_immediate=False`) and in a later invocation over the same
  directory. This holds for any added task today, with or without handles.
  The supported configuration for an eval set whose tasks add tasks is
  `log_dir_allow_dirty=True`: the check then keeps only logs whose
  identifiers are requested tasks (`:2085-2086`), so the rollout logs are
  ignored, never reused, and the creator's task reruns and enqueues fresh
  rollout tasks. Without it, the existing prerequisite error names the
  option. The `enqueue_task()` docstring and the handle docs in
  `docs/task-source.qmd` state the requirement; making added tasks' logs
  pass the default check is listed under "Not this design".

### Slot lending

Decision: Ransom, 2026-11-03: lend, with loans specific to the awaited
task. Without it the use case deadlocks at the default `max_tasks=1`, and in
selection-mode workers whose supervisor sets `max_tasks` to the selected
batch size: the creator holds the only slot while it waits for its rollout.

```python
@dataclass(eq=False)
class Loan:
    target: TaskRecord              # the only record this loan can start
    waiters: dict[TaskAttempt, int] = field(default_factory=dict)
                                    # lending waits on the target blocked now, by the attempt each ran in
    started: bool = False           # an attempt of the target is running on this loan
```

- **Who lends.** Every wait the guard allows lends: it comes from a
  sample's own code (its solver, scorers or tools, in a task the dispatcher
  started, including a task that is itself running on a loan), whose
  attempt (`SampleCode.attempt`) holds a slot until it ends. It lends on a target record that
  has not ended, whatever its phase: `started()`, `result()` or
  `enqueue_sample()`. It counts in the target's loan, under its attempt,
  from the moment it blocks until it returns, is cancelled or its attempt
  ends. A wait anywhere else is refused
  before it blocks (see "Creator and sample code").
  Lending is held from the moment of the wait, not from admission:
  `RunQueue.add` returns the record in `waiting`, and its admission cannot
  run until the creator next awaits ("Sample selection waits for admission"
  in [task-dispatch.md](task-dispatch.md#the-run-queue)), so the usual
  `enqueue_task()` followed by an immediate `await handle.result()` begins
  its wait in `waiting` or `admitting`.
- **One loan per target.** The first such wait creates `target.loan` and,
  in the same synchronous step, rings the queue's `wake`, so a dispatcher
  already waiting rescans: the target may have been startable for a while
  (admitted with its setups settled, or a retry pending) with every
  admission and setup wake already consumed. A later wait that recreates a
  dropped loan rings it too. Later waits on the same target add to
  `waiters` and share it. A loan
  costs a slot only while an attempt of the target runs on it, so waits on
  a target whose attempt runs on an ordinary slot, such as repeated
  `enqueue_sample()` calls to a running rollout task, cost no more slots.
- **What it starts.** After the ordinary picks, the dispatcher starts a
  loan's target above the ordinary limit when the loan is not already
  running an attempt and the target's next entry is startable under the
  start rule in [task-dispatch.md](task-dispatch.md#the-dispatcher): the
  record itself in `admitted`, or its pending retry, with setups settled
  and no pause holding it. A loan held on a target still in `waiting` or
  `admitting` therefore starts nothing until admission moves the record to
  `admitted` (which rings the queue) and its setups settle. An earlier,
  unrelated queued task never starts on another task's loan: at
  `max_tasks=1`, with running parent P, an earlier queued task U and P's
  child C, P's wait starts C, and U waits for an ordinary slot. If an
  ordinary slot is free when the target becomes startable, the target takes
  it and the loan stays unused.
- **Lifetime.** The loan lives while `waiters` counts a wait or an
  attempt is running on it. A wait leaves `waiters` when it returns or is
  cancelled, and when the attempt it ran in ends: at the two places that
  close the ports an attempt created (beside `finalize_eval()`, and when
  `run_one` returns for an attempt that ended without reaching it), the
  attempt removes its entry from every loan in the queue. A wait still
  blocked then, which only a detached task can hold (see "Creator and
  sample code"), keeps waiting until its target ends but no longer lends;
  when it returns it finds no entry and changes nothing. When `waiters` is
  empty and no attempt runs on the loan, the loan is dropped, in whatever phase the target is; a later wait
  creates a new one. An attempt that started on the loan keeps its extra
  slot until it ends, whatever its waiters do; `started` is cleared then,
  and the loan is dropped if no waiter remains. A retry of the target is
  an ordinary pending entry: if waiters remain (for example a `result()`
  that began while the first attempt ran), the same loan can start it.
  `RunQueue.end` clears the loan when the target ends, including by an
  admission failure or a cancel before admission finished, and every wait
  then settles as the table under "The handle API" says. Loans nest: a
  target running on a loan that waits on its own child lends to that
  child. The number of attempts running on loans is bounded by the number
  of distinct targets whose borrowed attempt is still running, not by the
  waits now blocked: a parent that enqueues several sample-sending
  children and awaits each `started()` in turn has no wait left, while
  each child it started on a loan runs until its port closes. Each target
  has at most one loan, and a loan runs at most one attempt at a time, so
  the extra tasks never exceed the number of distinct targets that waits
  started, and each ends with its target's attempt.
- **Loans never lend sandboxes.** A loan lends a task slot only:
  `max_sandboxes` and `max_samples` are never exceeded; see "Sandbox and
  sample limits need headroom".
- **Waits on a target that cannot run.** A loan only starts a startable
  target. A target whose setup failed becomes startable, starts and ends
  with an error log; a target cancelled while queued, whose admission
  failed, or still queued when the run ends, ends without starting. Each
  wait then ends as the table under "The handle API" says, so a loan never
  leaves a waiter blocked.
- **Docs.** The `max_tasks` docstrings, `docs/parallelism.qmd` and the
  handle docs in `docs/task-source.qmd` state the exception: a task that a
  running task waited on through a handle may start beyond `max_tasks`,
  and keeps that extra slot until its attempt ends, even after the wait
  returned; the extra tasks are at most one per distinct task started that
  way and still running.

### Sandbox and sample limits need headroom

A sandboxed sample keeps its sandbox, and so its permit of
`sandboxes/<provider>`, from before `sample_init` to after
`sample_cleanup`, including while it waits through a handle; a running
sample likewise keeps its task's `max_samples` slot (see "Current
behaviour"). Loans lend task slots only, so `max_sandboxes` and
`max_samples` are never exceeded, and a run in which every permit is held
by samples waiting on a task whose own samples need that permit cannot
progress: it hangs until it is cancelled. For example, with
`max_sandboxes=1` for `docker`, a searcher whose docker sample awaits
`rollouts.enqueue_sample(...)` on a rollout task that also uses docker
waits for ever.

So a run that waits through handles needs headroom: `max_sandboxes` for
each provider both tasks use must exceed the number of samples that hold
one while waiting, and a task's `max_samples` must leave room for samples
that wait on work its own samples have to do. The `max_sandboxes` and
`max_samples` docstrings, `docs/parallelism.qmd` and the handle docs in
`docs/task-source.qmd` say so, with the example above.

Inspect warns once per provider per run when a handle wait (`started()`,
`result()` or `enqueue_sample()`) starts while every permit of a provider
the target uses is held: the providers named by the target's task-level and
seed-sample sandbox configs (the configs its setups come from in
[task-dispatch.md](task-dispatch.md#sandbox-setup-1)), each looked up in
`sandbox_limiters()`, warning when `in_use >= limit`. For example: "task
'search' is waiting on task 'rollout', which uses 'docker' sandboxes, while
all 1 of them (max_sandboxes) are in use; if their holders are waiting on
'rollout', the run will not progress: raise max_sandboxes". The warning is
advice, not a check: holders that finish on their own release their
permits, and a provider introduced later by the target's samples is not
seen.

Waits on targets that fail, are cancelled or never start still always
end: "Waits on a target that cannot run" under "Slot lending" and the table
under "The handle API" are unchanged.

## Alternatives considered

- **Running the rollout task in a separate Inspect process.** A nested
  `eval()` is refused in-process ("Multiple concurrent calls to eval_async
  are not allowed", `src/inspect_ai/_eval/eval.py:797`), so the route is a
  child `inspect eval` started through `subprocess()`, whose log the
  searcher reads.
  - Gains: no shared dispatcher, `max_tasks`, slot lending or sample port,
    so no interplay with `--limit`, retries or seed ids; no shared working
    directory or provider state; a rollout crash is isolated; it works today
    with no core change.
  - Costs: one child per step pays Inspect's import, model client start-up
    and the sandbox's `task_init` every time. Amortizing that needs a
    long-lived child: a rollout task whose `SampleSource.next_samples()`
    reads requests from a file or socket and whose `sample_complete` writes
    results back, a cross-process protocol each user builds (and handles
    that reach another process are a non-goal here). Per-process
    `max_connections`, rate-limit backoff, `max_sandboxes` and token limits
    are not shared. The child is invisible to `eval_set` retry and resume,
    to an external supervisor's fleet accounting (selection workers'
    `max_tasks`, the pool it allocates from) and to `inspect ctl`.
    Cancellation, Ctrl-C, the display (`display=none`) and the log location
    are the user's job.
  - Not chosen as this design's goal: the search must run under `eval_set()`
    and selection-mode workers with shared limits, one control channel and
    one retry story. Until in-process sample sending exists, the long-lived
    child is the way to run such a search.
- **The prototype's async `enqueue_task()` returning `list[TaskHandle]`.**
  Async was needed because the prototype resolves sandbox configs at the
  call. Here the call stays synchronous (resolution and configuration are
  synchronous today; sandbox key resolution runs in the background, see
  [task-dispatch.md](task-dispatch.md#sandbox-setup-1)), so the return value
  is additive and nobody migrates (decision: Ransom, 2026-11-03).
- **A separate `start_task(task, *, model=None) -> TaskHandle`** beside an
  unchanged `enqueue_task()`. Additive too, but two functions for one
  operation; not chosen (decision: Ransom, 2026-11-03).
- **Breaking `enqueue_sample()` out as a free function taking a task id.**
  A handle carries the record directly and has a clear owner, which the
  port lifetime rule needs.
- **Cancelling an outstanding `next_samples()` when a sample arrives
  through a handle,** then calling it again later. Simpler feeder, but it
  breaks a source that is part-way through producing samples (an awaited
  request is lost), and the source contract says it may block indefinitely.
- **Validating port requests only at delivery.** Simpler, but a sender
  could not learn of a seed-id clash until the target starts, and a
  rejection would then have to be told apart from a limit drop; checking
  the seed reservations at the call refuses the common case at once, and
  the delivery check covers the race.
- **Replaying port requests into an in-run retry** after a delivery,
  admitting the delivered requests again and rebinding their callers'
  futures. Unique ids keep an anonymous request from taking another
  sample's result, but each request would need its id, epochs, limit budget
  and outcome recorded and re-enforced, and a later run (`eval_retry()`, a
  resume) has no creator to send the requests at all. Ending the task with
  its error log is exact, and the creator can resubmit.
- **Refusing the first delivery into a retry that reuses prior state.**
  Also exact, but the creator's requests would fail for the whole of that
  attempt, and it would have to enqueue a fresh task anyway; rerunning the
  retry's own samples keeps the task usable.
- **A durable log record of the first delivery** instead of the spec
  field: a header field written, with fsync, before the first request is
  reserved, so that only logs that had received a sample were refused.
  Without unique ids for anonymous dynamic samples it was needed, because a
  delivery shifted the integer ids of every anonymous sample admitted after
  it. It costs a durable mid-run write, and every path that copies a log
  (conversion, streamed `inspect score`, crashed-log recovery, including a
  copy that writes over its own source) must write the record before it
  publishes a sample. With unique ids, nothing about reuse depends on when
  a sample arrived, and the spec field reaches every copy from its first
  write with no change to any copy path; a rollout task that was never
  sent a sample loses only reuse and `eval_retry()`, which a task fed by
  its creator cannot use.
- **Refusing explicit ids on samples sent through a handle.** Every port
  sample would then have a unique id, so a rerun could never be handed a
  port sample's result, and reuse from a rollout task's log could be
  allowed; the validation at the call and the `refused` outcome would go.
  Not chosen: explicit ids let a creator name the samples it sends in the
  log and the viewer, and the reuse it would allow is of
  little value, since a rollout task is not retried after a delivery and is
  not rerun without its creator.
- **Refusing waits that would never end** with a process-level wait-for
  graph: every blocking event (a handle wait, and a sample about to wait
  for a `sandboxes/<provider>` or `max_samples` permit) checked by a
  least-fixpoint liveness test, refusing the event that would close a cycle
  with an error. It keeps a run with too little headroom from hanging, but
  it has to be re-checked at every blocking event and on every limit
  change: `ResizableLimiter` allows `in_use > limit` after a live retune
  (`src/inspect_ai/util/_concurrency.py:170`,
  `src/inspect_ai/_control/limits.py:844`), so a lowered limit can turn
  waits that were live into a cycle, and the graph would then have to pick
  an existing wait to fail. Documented headroom and a warning cover the
  configurations the use case needs.
- **Handle work in task-level callbacks after the control channel stops
  reaching the task, with its own abort path.** There cancel and drain
  answer "task already finished", or only abandon a pending retry, so ports
  and lending waits would need a new cancellation route, ownership rules
  and a drain outcome for work no caller needs. Refusing the waits and
  ports there is simpler; a plain `enqueue_task()` there still works
  (decision: Ransom, 2026-11-05).
- **Allowing handle work in task-level code while the attempt is
  "running"**, with the boundary at `finalize_eval()`, at a list of named
  callbacks, or at the terminal `EvalState`. Each leaves task-level code
  the guard admits where cancel no longer reaches: a fixed dataset's
  `on_task_end` and early-stopping callbacks, a task with no samples'
  `on_task_start`, and the `on_task_end` hooks of a retry-pending teardown,
  whose cancel abandons the retry and clears `retry_pending` while
  `completed_at` stays unset (see "Current behaviour"). Letting handle
  work begin only while a sample's own code runs, which every abort
  reaches, needs no
  such list; it gives up waits in `sample_complete`, which the use case
  does not need, while the source's own `enqueue_sample()` keeps working
  there (decision: Ransom, 2026-11-06).
- **Refusing tasks the sample does not own**, by walking `parent_id`
  through `anyio.get_running_tasks()` to the task running the sample. It
  refuses awaited `asyncio.gather()` and `asyncio.TaskGroup` children,
  which have no AnyIO parent, although `docs/parallelism.qmd` recommends
  gather in solvers; a task that a foreign group's `TaskGroup.start()`
  takes over after readiness escapes it anyway; and it scans every running
  task on each call. What it guarded against, a detached wait outliving
  its sample, holds nothing once its attempt ends: its loan share leaves
  then, and the wait settles with its target (decision: Ransom,
  2026-11-06).
- **Cancelling a sample's blocked waits when its code ends**, through a
  register of waits on `SampleCode`. It would end detached waits with
  their sample, but adds bookkeeping for the user's own unjoined tasks,
  which Inspect does not cancel for anything else they do, and the loan's
  attempt-based lifetime already bounds what such a wait holds (decision:
  Ransom, 2026-11-06).
- **Slot lending counted globally** (raise the limit by the number of
  waits and pick as usual). An earlier unrelated queued task takes the
  borrowed slot and can hold it while the awaited task and its creator stay
  blocked. Loans name their target instead.
- **No lending, and a warning** when a handle waits on a queued task while
  every slot is held. The use case then needs `max_tasks >= 2`, which a
  selection-mode worker's supervisor may not allow. Not chosen (decision:
  Ransom, 2026-11-03).
- **Tasks added by a running task do not count toward `max_tasks`.** The
  simplest rule, but unbounded: a task that adds one task per sample runs
  them all at once.

## Compatibility and migration

No migration required.

Public API (additive):

- `enqueue_task()` returns `list[TaskHandle]` instead of `None` and gains
  the keyword-only `send_samples=False`; synchronous behaviour unchanged.
  Without `send_samples` an added task has no port and ends when its
  source is done, as today, whatever the caller does with the handles.
- New `inspect_ai.TaskHandle`, `TaskEndedError`, `SampleAbandonedError`.
- `SampleSource` docstrings: samples sent through a handle start while
  `next_samples()` is awaiting, and their callbacks may fire meanwhile;
  everything the source adds during a pull is admitted after the batch it
  returns, as today.
- The `TaskHandle` and `enqueue_task()` docstrings and the handle docs in
  `docs/task-source.qmd`: handles are awaited, and `send_samples=True`
  used, only from a sample's solver, scorers or tools and the tasks they
  start, while the sample runs (a detached task's later calls are
  refused); callbacks and hooks
  can add tasks and cancel or close handles, and the task's own
  `enqueue_sample()` works where it does today.
- `max_sandboxes` and `max_samples` docstrings: the headroom a run that
  waits through handles needs.

Behaviour changes:

- Slot lending lets a task that a running task is waiting on start beyond
  `max_tasks` (new API only; no existing eval waits on a handle). A
  supervisor that sets `max_tasks` as a ceiling, such as a selection-mode
  worker's, sees up to one extra running task per distinct task started on
  a loan, for as long as that task's attempt runs, including after the wait
  that started it has returned (decision: Ransom, 2026-11-03).
- The feeder's owned pull changes nothing for existing sources: only
  samples sent through a handle start while a pull blocks. What a pull
  enqueues, and the follow-ups of samples finishing during it (including
  control-channel reruns, which start during a pull today), are admitted
  after the pull's batch in arrival order, as today, so `--limit` and
  `--sample-id` select the same samples, and ids are assigned in the same
  order (anonymous ones by the unique-id rule this design builds on).
- A run whose sandbox or `max_samples` limits leave no headroom for samples
  waiting through handles can hang (new API only); the warning names the
  provider.

Eval logs:

- New `EvalSpec` field `send_samples` (default `False`), written with the
  rest of the spec. Logs without it read as `False`, so every existing log
  behaves as today. Producer: `TaskLogger`, from the record's port; every
  path that writes or copies a log writes it with the spec, unchanged.
  Consumers: `eval_log_sample_source()` (no reuse), `eval_retry()`
  (refusal), `list_latest_eval_logs()` (never complete) and Steward. It is
  part of `EvalSpec`, so the viewer's OpenAPI schema and generated
  TypeScript types change (a coordinated ts-mono update); the viewer does
  not display it.
- An Inspect version without the field ignores it (pydantic drops unknown
  keys), so an older `eval_retry()` or eval-set resume would reuse such a
  log, and an older `eval_set()` could count it complete: such a log must be
  retried or resumed with a version that has the field.
- Steward reads the field through the companion change (step 6 of the
  plan). A Steward release without it would count such a successful log
  complete and could import one from its reuse store, so runs that use
  `send_samples=True` under Steward need a Steward release with the change;
  its `inspect-ai` floor rises with it.
- `eval_retry()` of such a log raises `PrerequisiteError` instead of
  rerunning it.
- Sample ids of anonymous dynamic samples change in every task with the
  companion change this design builds on; that change owns the
  compatibility of its ids, and this design adds nothing to it.
- `enqueue_task(..., send_samples=True)` is refused in a run that logs in
  the deprecated `.json` format; `send_samples=False` works with either
  format.
- No control-channel or config file changes.

## Security

- **Samples sent through a handle** may carry model output (the search
  proposes them). They enter the receiving task through the same
  `SampleEnqueuer` path as `enqueue_sample()`: ids are checked for
  duplicates by `(str(id), epoch)` against the seed, earlier requests and
  the running attempt before they reach the task, and again at delivery,
  so a crafted id cannot reclaim a seed id (excluded ones included), and a
  request refused by those checks fails only its sender. An accepted
  explicit id reserves its runs as a source sample's does: if the source
  later adds the same `(str(id), epoch)`, `reserve_runs` raises
  (`src/inspect_ai/_eval/task/run.py:1720-1726`) and the task fails, with
  its unresolved requests ending in `TaskEndedError`, as a duplicate within
  a source fails its task today. A creator that sends model-proposed ids
  can avoid this by sending samples without ids, which get unique ids. Ids
  become log member names through the existing path; content is sample input, which the task treats as it
  treats any dataset sample.
- A handle is an in-process object; nothing new is exposed on the control
  channel.
- **`EvalSpec.send_samples` in a log** only restricts reuse. A log edited
  to clear it is reused as any log is today, which is the same trust the
  reuse paths already place in a log's sample ids; setting it only makes
  Inspect rerun samples instead of reusing them, and refuse `eval_retry()`.

## Testing

Unit and integration tests, asyncio and trio (`--runtrio` for every async
test touched), with mockllm models:

- `tests/test_enqueue_task.py`:
  - the overview's example as a test at `max_tasks=1`, under `eval()`,
    `eval_set()` and eval-set selection mode in-process;
  - `started()`, `result()`, `cancel()` queued and running, `close()`,
    `enqueue_sample()` results per epoch;
  - off the loop: from an `anyio.to_thread.run_sync()` worker in the
    parent's solver, `enqueue_task(..., send_samples=True)`, `started()`,
    `result()`, `enqueue_sample()`, `cancel()` (of a queued, an admitted
    and a running child) and `close()` each raise `RuntimeError` and leave
    the record's phase, loan, port and requests and the queue's wake as
    they were (the admitted child stays `admitted`, with no finalizer
    started); the same calls through `anyio.from_thread.run_sync()` from
    that worker succeed; on asyncio and trio;
  - the terminal-outcome table, row by row: a target whose setup fails
    (stub provider) — `started()` returns, `result()` returns the error
    log, an unresolved request raises `TaskEndedError(log=<that log>)`; a
    target cancelled while queued and one still queued when the run is
    cancelled — `started()` and the request raise `TaskEndedError(log=None)`
    and `result()` returns `None`; a target whose `logger.init()` raises —
    the same, with `error` set; none of these waits hangs (each bounded with
    `fail_after`);
  - refusals listed under "Run shapes", including awaiting `started()` or
    `result()` inside `TaskSource.next_tasks()` at `max_tasks=1` and `2`,
    while `enqueue_task()` there still works;
  - the port closing when the creator attempt ends;
  - slot lending (every `result()` wait below is on a child added without
    `send_samples`, or on a sample-sending child after `close()`, per
    "Keeping the task open"; a `result()` on an open port is tested
    separately: it completes once a sibling closes the port): an earlier
    unrelated queued task U ahead of the awaited
    child C at `max_tasks=1`, where C starts on the loan and U waits for an
    ordinary slot; several samples waiting on one queued task share one
    loan; repeated `enqueue_sample()` calls on a running task take no extra
    slot; the loan is returned when C ends; a nested loan; a parent that
    enqueues three sample-sending children and awaits each `started()` in
    turn at `max_tasks=1` has three attempts running on loans after every
    wait has returned, each until its port closes; at `max_tasks=1`,
    each of `started()`, `result()` and `enqueue_sample()` begun right after
    `enqueue_task()` (C in `waiting`) and while C's `logger.init()` is held
    on an event (C in `admitting`): C starts on the loan once admission
    finishes and its setups settle, and the wait completes (each bounded
    with `fail_after`); two waiters begun before admission share one loan
    and C starts once; every waiter cancelled before admission finishes
    drops the loan, and C then waits for an ordinary slot; C's admission
    failing, and C cancelled during admission, settle the waits with
    `TaskEndedError` and leave no loan; a `result()` begun while C's first
    attempt runs on an ordinary slot that then errors with a retry queued
    starts the retry on the loan; each of the three waits begun only after
    C is admitted with its setups settled and the dispatcher is already
    waiting on `wake` (held there by an event-controlled spy, with no other
    event afterwards), and likewise against a ready pending retry of C,
    starts C on the loan; a wait that recreates a dropped loan starts C the
    same way;
  - headroom: with `max_sandboxes=1` (stub sandbox provider), a parent
    sample holding the only sandbox awaits its child's `started()`, then
    finishes, and the child's sample then gets the sandbox and runs; a
    handle wait that starts while every permit of the target's provider is
    held logs the warning once per provider, and none when the target uses
    another provider or the provider has no limit.
- `tests/test_eval_retry.py` and `tests/test_eval_set.py` (logs of tasks
  that can receive samples, with the companion change in place):
  - a rollout task added with `send_samples=True` has `eval.send_samples`
    set in its log while unfinished, when finished, after
    `recover_eval_log`, after `convert_eval_logs` to `.json` and back,
    after streamed `inspect score` and after `write_eval_log`, including
    when it was never sent a sample; a task added without it, and every
    existing log, reads `False`;
  - a rollout task that has received a port request and then errors is not
    retried in-run even with `task_retry_attempts` set; its outstanding
    requests raise `TaskEndedError` with its error log; and the log holds
    each sample under the input it was sent with: with an empty seed,
    source sample A, port request P and P's callback follow-up B each have
    their own unique id;
  - the fallback log: after a delivery, a failing final log write (stub
    recorder) and a raising task-completion callback each end the task
    without a retry, and the log the dispatcher and `result()` return has
    `eval.send_samples` set;
  - `eval_retry()` of such a log, with and without deliveries, raises
    `PrerequisiteError` before any recovery writes; eval-set resume
    (ordinary and legacy `retry_immediate=False` rounds) and
    selection-worker resume of such a log with a requested task's
    identifier reuse no sample, copy no checkpoint and log the warning;
  - explicit ids: in a log of such a task in which request P with id `"x"`
    completed, a resume of it whose own source adds a sample `"x"` runs
    that sample fresh and does not return P's result or restore P's
    checkpoint;
  - under `eval_set(log_dir_allow_dirty=True)`, a parent that adds a
    rollout task, sends it a sample and then fails is retried in a legacy
    round (`retry_immediate=False`) and in a second invocation over the
    same directory: the rollout logs are ignored, the parent reruns and
    adds fresh rollout tasks, and nothing is reused from the rollout logs;
    without the flag, the existing prerequisite error is raised and names
    the option; `eval_set()` over a log directory holding such a successful
    log of a requested empty-seed task (so `planned == 0`), and over such a
    crashed log that recovery under `incomplete_action="error"` finalizes
    as `success`, reruns the task rather than returning the log as an
    existing success, and reuses none of its samples; an existing log
    without the field is reused as today;
  - a request refused at delivery (the source reserved its id first),
    followed by an otherwise retryable error: `SamplePort.delivered` is
    unset, the task is retried, and the retry reuses nothing;
  - a retry with an open port (the first attempt errors before any
    delivery): source sample A completes, A reruns in the retry and is not
    reused, with sample logging on and off and with checkpointing on (no
    checkpoint is copied into the retry); with a source that adds a sample
    with id `"x"` once per process, which completes before the failure, a
    request P with id `"x"`, sent after the failed attempt has ended and
    while a test hook holds the retry before it starts (while the attempt
    ran, its reservation of `"x"` refused P at the call), is accepted,
    delivered into the retry, and returns P's own result, not the source
    sample's, with no checkpoint of the source sample restored; the same
    with the port closed, and with P's caller cancelled, each after P is
    accepted and before the retry is released (an accepted request is still
    delivered); a task added without `send_samples` that fails the same way
    reuses A as today.
- `tests/test_enqueue_task.py` (existing callers and the new keyword):
  - a parent under a `TaskSource` at `max_tasks=2` enqueues a finite
    `SampleSource` child, ignores the return value and awaits the child's
    `task_complete` event: the child ends when its source is done and the
    parent completes (bounded with `fail_after`);
  - outside the parent's samples, at `max_tasks=1` and `2`, in each of:
    the parent `SampleSource`'s own `sample_complete` and
    `sample_abandoned`; `TaskSource.sample_complete`, `sample_abandoned`
    and `task_complete`; an `on_task_end` hook of a fixed-dataset parent run
    without a `TaskSource`; early-stopping `complete_task` of such a parent;
    an `on_task_start` hook of a parent with no samples; and an
    `on_task_end` hook of a `SampleSource` parent under `eval_set()` with
    retry budget left whose attempt fails its fractional `fail_on_error`
    threshold, checked both while the retry is pending and after a ctl
    cancel has abandoned it: `enqueue_task(..., send_samples=True)` raises
    `RuntimeError` and enqueues nothing; each of `started()`, `result()`
    and `enqueue_sample()`, on a handle `enqueue_task()` returned there and
    on one the parent's solver kept (where it has one), raises
    `RuntimeError` without blocking (bounded with `fail_after`) and leaves
    no loan; `cancel()`, `close()` and `state` work there; a plain
    `enqueue_task()` there returns handles whose tasks run to completion;
    control-channel timestamps and cancel answers are unchanged from a run
    without handles;
  - the parent `SampleSource`'s own `enqueue_sample()` called inside its
    `sample_complete` still admits that sample, which runs and is logged in
    the parent, as today;
  - hooks inside sample code: with a hook implementing
    `on_before_model_generate`, `on_model_usage`, `on_model_cache_usage`,
    `on_model_retry`, `on_sample_event` and `override_api_key`, a solver
    and a scorer that each call `generate` (and construct a model, for
    `override_api_key`; a cached call and a stub-provider retry for the
    cache and retry hooks): from each hook, `send_samples=True` (from the
    synchronous `override_api_key` as from the others), `started()`,
    `result()` and `enqueue_sample()` raise `RuntimeError` without blocking,
    and leave no loan; a hook that raises restores the caller's context, so
    the solver's own wait after the hook call (and after a hook that raised)
    is still allowed; the same from `enabled()` and `needs_full_sample()`;
    on asyncio and trio. A table in the test lists every public `Hooks`
    method with the dispatcher that calls it, and the test fails when
    `Hooks` gains a method the table lacks; the same four calls are
    refused from a legacy telemetry subscriber that a solver's `generate`
    reaches and from a legacy API-key subscriber that constructing a model
    in a solver reaches (each installed by setting the module's subscriber,
    as `init_legacy_hooks()` does), and the solver's own wait after each is
    still allowed;
  - tasks started from sample code: work started in the solver with
    `background()`, with `tg_collect()` and in a nested task group, and a
    scorer's own task group, can each open a port and wait; a batch of
    `enqueue_sample()` calls to one rollout handle under `asyncio.gather()`
    and under `asyncio.TaskGroup` in a solver (asyncio only) each succeed
    and return every sample's result; a raw `asyncio.create_task()` started
    in the solver (asyncio only) and still running after its sample's code
    has ended, with another task keeping the eval alive, is refused for
    `send_samples=True`, `started()`, `result()` and `enqueue_sample()`,
    without blocking and leaving no loan;
  - a detached wait: at `max_tasks=1`, a raw `asyncio.create_task()` in
    the parent's solver begins `result()` on a child added without
    `send_samples`, and the solver returns without awaiting it; the wait's
    loan starts the child; when the parent's attempt ends, its entry
    leaves the loan's `waiters` (with a second waiter from a sibling
    sample still blocked, `waiters` falls by one and the loan stays), the
    loan is dropped once the child's borrowed attempt ends and no waiter
    remains, and the detached `result()` returns the child's log when the
    child ends;
  - inside the parent's solver at `max_tasks=1`, and from a scorer, the
    same three waits lend, so the child starts and each wait completes
    (`started()` and `enqueue_sample()` on a sample-sending child with its
    port open, `result()` after `close()` on that handle, and `result()` on
    a child added without `send_samples`); an abort of the parent while a
    solver wait is blocked cancels that wait; a port the parent's solver
    opened closes when the parent's attempt finishes, before
    `task_complete` runs;
  - `send_samples=True` outside a sample's own code, for a non-`SampleSource`
    dataset, for a `PreviousTask`, a list of them, a mixed
    `PreviousTask`/`ResolvedTask` list, and a `ResolvedTask` with a
    `sample_source` each raise and enqueue nothing; the same inputs without
    `send_samples` still run as today (the existing `ResolvedTask` case at
    `tests/test_enqueue_task.py:147`), and `enqueue_sample()` on their
    handles raises `RuntimeError`;
  - with `send_samples=True` and a fresh task, P sent before the source's
    first pull gets its own id and result (initial admission);
  - `send_samples=True` in a run with `log_format="json"` raises
    `ValueError` naming the `.eval` requirement and enqueues nothing, while
    `send_samples=False` in the same run still adds the task;
  - graceful directives, for each of `inspect ctl` drain, `cancel
    action=score` and `cancel action=error`: with an idle open port and an
    exhausted source, the target finishes and `result()` returns its log;
    with an in-flight request, that request resolves under the directive's
    rule (its natural `EvalSample` under drain, the scored or errored one
    under score or error); with an accepted request still waiting for
    delivery (sent while a pull holds the feeder, or while `max_samples` is
    full), it fails with `SampleAbandonedError`, and a later
    `enqueue_sample()` fails at once the same way; and with a `next_samples()`
    that never returns (an `anyio.Event` nobody sets), with a pending and an
    in-flight request, the pull is cancelled without failing the task, the
    in-flight request resolves under the directive's rule, the pending one
    fails with `SampleAbandonedError`, and the target finishes (each bounded
    with `fail_after`);
  - retention: a rollout task that receives many requests (successful,
    errored, dropped and refused): after each call returns, the port holds
    no `PortRequest` for it and no reference to its sample copy, futures or
    `EvalSample` (checked on the port's own fields), while its `runs` still
    refuse a duplicate id; after the run's sample buffer is flushed and the
    runner has released the completed samples, weak references to the
    successful requests' inputs and results are dead, and an errored
    request's sample is still held by the runner for requeue, as today; a
    request still pending across an in-run retry is kept and delivered;
  - ownership: one anonymous `Sample` sent to task A (empty seed) and to
    task B (whose seed reserves id 1), and to two task × model handles of
    one task, each runs in every target with that target's own automatic
    id, and B does not fail; the caller's object still has `id is None`;
    sending one object with an explicit id that clashes is still refused
    with `ValueError`.
- `tests/test_sample_source.py`:
  - port validation: an id equal to a seed id, its int/str equivalent
    (`1` and `"1"`), and a seed id excluded by `--sample-id` or `--limit`
    are refused with `ValueError` while the target is queued and the target
    never sees them; a seed id at an explicit epoch above `epochs` is
    accepted; a duplicate of an earlier request is refused; a request that
    the source's own addition reserved first is refused at delivery, keeps
    no reservation, and the target task completes; an accepted request
    with explicit id `"y"` that the source then adds itself fails the task
    with the duplicate-id `ValueError`, and another request still pending
    ends with `TaskEndedError` carrying the task's error log;
  - abandoned and limit-dropped requests raise `SampleAbandonedError`;
  - a rollout task whose first attempt fails in setup before any request
    arrives is retried and receives its pending requests in the retry;
  - the feeder: a sample sent through a handle while `next_samples()` stays
    blocked runs at once; the blocked pull is cancelled when the task is
    cancelled, when the run is cancelled and when the sample limit is
    exhausted, and a pull's exception still fails the task; with an empty
    seed and `limit=1`, a `next_samples()` that enqueues A and returns `[B]`
    runs B and drops A; with one seed and `limit=2`, a control-channel
    rerun of the seed during a blocked pull whose `sample_complete` returns
    A, while the pull later returns B, runs B and drops A; in both, the
    samples that run have unique anonymous ids that no other attempt gives a
    sample, as the companion rule requires, rather than today's integers
    (the existing
    `tests/_control/test_requeue.py` case extended); a port sample's
    follow-up during a blocked pull is held until the pull returns; a handle
    sample arriving while the pull blocks is admitted first and takes the
    limit; port requests observed with a completed pull follow its batch
    and held additions; a pull that
    enqueues a sample and returns `None`, and a pull that returns `None`
    after a handle sample arrived during it, are each followed by another
    pull once those samples have run; with `limit=1` and a pull blocked, a
    port sample P whose `sample_complete` returns P at epoch 2, whose own
    callback returns P at epoch 3, runs all three epochs before the pull is
    cancelled and the task ends.

## Implementation plan

This design is step 5 of the plan in
[task-dispatch.md](task-dispatch.md#implementation-plan), one PR, after
step 3 (the run queue and dispatcher), step 4 (setup beside the dispatcher,
whose setup-failure attempt path the handle outcomes and loans rely on) and
the companion change that gives anonymous dynamic samples unique ids, plus a
companion change in Steward (step 6):

5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, `SamplePort`,
   `PortRequest`, the errors, `Loan`, `SampleCode`, the `next_tasks()` and
   outside-a-sample refusals with their shared `_eligible()` check (the
   `ContextVar` and `live`), `_require_run_loop()` in every handle method
   but `state`, the headroom
   warning; `enqueue_task()` returns handles and checks
   `send_samples=True`), `_eval/task/run.py`
   (port attach, the two delivery steps and `SamplePort.delivered`, the
   result sites, the feeder's owned pull and held buffer, the open port,
   the attempt `ContextVar`, the `SampleCode` per sample run, set around
   the solver plan and the scorer loop in `task_run_sample` and marked not
   `live` when the sample's own code ends, the close of the ports the attempt created beside
   `finalize_eval()` and the removal of its entries from loans there, the `send_samples` check in
   `eval_log_sample_source()`), `_eval/task/log.py` (the `send_samples`
   argument to `TaskLogger`, set on the spec), `log/_log.py`
   (`EvalSpec.send_samples`), `_eval/task/sample_source.py` (docstrings),
   `_eval/run.py` (the retry decision reads `SamplePort.delivered`, port
   close and loan-entry removal when an attempt ends without finishing, `SamplePort.stop()` from
   the `cancel_task` callback for drain, score and error, loans in the dispatcher, the
   `next_tasks()` scope, `admit_task()` passing `send_samples`),
   `_eval/eval.py` (the `eval_retry()` refusal, `max_tasks`, `max_samples`
   and `max_sandboxes` docstrings), `_eval/evalset.py` (such a log is
   incomplete in `list_latest_eval_logs()`; docstrings),
   `hooks/_hooks.py` (`hook_call()` around every call into a `Hooks`
   object), `hooks/_legacy.py` (`hook_call()` around each legacy
   subscriber's call), `model/_model.py` (the `enabled()` scan under `hook_call()`),
   `__init__.py` (exports), `docs/task-source.qmd`, `docs/parallelism.qmd`
   and `docs/reference`. No recorder or log-copy code changes. The new
   `EvalSpec` field changes the viewer's OpenAPI schema and generated
   TypeScript types, landed with the coordinated ts-mono update the repo's
   process requires. Tests: those above.
6. **Steward companion** (`inspect_steward`, after the Inspect release that
   adds `EvalSpec.send_samples`): `_evalset/observe.py`
   (`LogAttempt.send_samples`, read from the header's eval spec in
   `_attempt()`; `IncompleteReason.SEND_SAMPLES`, checked first in
   `_incomplete_reason()`), `_store/match.py` (the skipped candidate's log
   line), `_evalset/cache.py` (`CACHE_VERSION` raised), `pyproject.toml`
   (the `inspect-ai` floor). Tests in its suite: an observed successful log
   of an empty-seed manifest task with the field set is incomplete with
   that reason; such a log in the reuse store is not imported; a cache
   written by the previous version is discarded and the attempt re-read.

## Open questions

None. Ransom decided (2026-11-03) that `enqueue_task()` stays synchronous
and returns `list[TaskHandle]`, that sending samples is enabled by the
keyword-only `send_samples=False` and refused for `.json` logs ("The handle
API"), and that a task a running task waits on borrows a slot through a
loan specific to it ("Slot lending"). He decided (2026-11-04) that the
design builds on unique ids for anonymous dynamic samples and records the
capability to receive samples in the eval spec ("Logs of tasks that can
receive samples").

## Not this design

- Unique ids for anonymous dynamic samples, the companion change this
  design builds on.
- Ids of seed samples, which are positions when the dataset gives none: a
  rerun over an edited or reordered dataset of the same length can map a
  prior record onto a different sample. This holds for every task, with or
  without handles.

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()` (only
  `enqueue_task()` returns handles).
- Recording the creator in the eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Making the logs of tasks added under `eval_set()` pass its log-directory
  check without `log_dir_allow_dirty=True` (for example by recording which
  task added them); it applies to every added task, not only those with
  handles.
- Detecting waits that cannot finish because sandbox or `max_samples`
  permits are held by their own waiters; see the wait-for graph under
  "Alternatives considered".
