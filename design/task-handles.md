# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns a `TaskHandle` for each task it added, through
which the adding task can cancel it. A task whose dataset is
`samples_from_handle()` takes its samples through its handle: the task that
added it sends each one with `TaskHandle.enqueue_sample()` and gets back the
sample's logged `EvalSample`, and `result()` waits for the task's final log.
Such a task runs under the adding task's
model, starts when its first sample is sent, and does not take a
`max_tasks` slot, so a search that drives a rollout task works at any
`max_tasks`. It stays open until its handle is closed or the attempt that
added it ends, and `async with` closes the handle on exit:

```python
@task
def rollout_task() -> Task:
    return Task(
        dataset=samples_from_handle(),
        solver=rollout(),
        scorer=judge(),
        fail_on_error=False,  # an errored rollout comes back with its `error` set
    )

@task
def search() -> Task:
    return Task(
        dataset=[Sample(input="Find a misaligned behaviour.")],
        solver=searcher(n_steps=50),
    )

@solver
def searcher(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [handle] = enqueue_task(rollout_task())
        async with handle as rollouts:                    # closes on exit
            try:
                for _ in range(n_steps):
                    sample = await propose_next(state)
                    run = await rollouts.enqueue_sample(sample)   # its EvalSample
                    update(state, run)
            except BaseException:
                rollouts.cancel()   # the search stopped early: stop the rollouts it sent
                raise
        return state

    return solve
```

With both tasks in `search.py`, run the searcher by name: `inspect eval
search.py@search`, or `eval_set("search.py@search", ...)`, which can be
resumed over a directory holding the rollout task's logs. Loading the
whole file (`inspect eval search.py`) also loads `rollout_task`, and a task
fed through a handle cannot run on its own, so that run is refused ("What
is refused").

`propose_next` is the searcher's own async function and may call a model.
The rollout task sets `fail_on_error=False`. With the default, the first
errored rollout is returned to its sender with its `error` set and then ends
the task; requests still unresolved receive `TaskEndedError`, and a task fed
through a handle is not retried. `fail_on_error=False` lets the task keep
accepting rollouts after a sample error. A task fed through a handle keeps
its own limits, error tolerance and `max_samples`, falling back to the
run's values when unset.

Closing never stops rollouts already sent; a creator stops them with
`cancel()` in an `except BaseException:` that re-raises, as above. It runs
when the search raises, hits a sample limit, or is cancelled (a time limit
and a working limit both reach the block as a cancellation, as does an
operator abort), and not when the search returns normally. A `finally:`
would also run on a normal exit, where `cancel()` aborts the rollout task
and leaves it a "Task cancelled by user (abort)" error log.

Handles build on the run queue of [task-dispatch.md](task-dispatch.md): an
added task is a `TaskRecord` in the run's `RunQueue`.

## Behaviour changes

All of these are new API; no existing eval waits on a handle or uses
`samples_from_handle()`.

- `enqueue_task()` returns `list[TaskHandle]` and stays synchronous; a
  call on the run's event loop that ignores the result is unchanged (an
  async version would turn every such call, none of which awaits today,
  into one that adds nothing). A call
  from a worker thread that copied the run's context, which today buffers
  the task, raises `RuntimeError`; the worker calls
  `anyio.from_thread.run_sync(lambda: enqueue_task(...))` instead
  ([task-dispatch.md](task-dispatch.md#run-shapes-and-what-is-refused)).
- A task fed through a handle does not count toward `max_tasks`. A
  supervisor that sets `max_tasks` as a ceiling, such as a selection-mode
  worker's, sees one extra running task for each fed task that has been sent
  a sample and has not ended.
- A task fed through a handle runs once, under its creator's model, with
  one epoch, whatever models and epochs the run has.
- For a task fed through a handle, a sample limit, error-tolerance setting
  or `max_samples` is its own value if it sets one, else the run's, else the
  default. For every other task, an ordinary task added from inside a
  running task included, the run's value replaces the task's, as today.
- A task fed through a handle that is cancelled before it starts ends at
  once with no log, as one whose handle is closed before any sample is
  sent: no abort attempt runs, the run's `TaskSource` hears nothing, and
  `eval()` returns no log for it.
- A task fed through a handle is never retried automatically, and
  `eval_retry()` refuses its log. Its log is returned and listed with the
  run's other logs but does not decide `eval_set()`'s result or a
  selection-mode worker's: its creator's log does. Its log's
  `task_identifier()` is built from its task id, so no ordinary task's
  identifier matches it, whatever the two tasks are named.
  The eval set's log-directory check skips fed logs, so resuming an eval
  set whose directory holds them, or its later `retry_immediate=False`
  rounds, needs no `log_dir_allow_dirty=True`; an ordinary added task's log
  still does, as today.
- A fed task's log records the dataset name `samples_from_handle`, which is
  refused for any other dataset.
- The run's `--limit`, `--sample-id` and `--epochs` do not apply to a task
  fed through a handle.
- `TaskHandle.result()` waits only on a task fed through its handle; on the
  handle of any other added task it raises `RuntimeError`, and that task's
  log is read after the run.
- A run whose `max_sandboxes`, `max_samples` or `max_connections` leaves no
  room for the work a handle wait depends on can hang, with no warning; the
  docs explain the headroom needed and the `inspect ctl config
  --max-sandboxes` command that raises the sandbox limit while the run goes
  on.

## Why

With [task-dispatch.md](task-dispatch.md) an added task starts while its
creator runs, but the creator still cannot use it:

- `enqueue_task()` returns `None`, so the caller cannot wait for the task or
  cancel it.
- `enqueue_sample()` reaches only the calling task's own `SampleSource`.
- A running task holds one of the `max_tasks` slots for its whole life,
  including while it waits, so a searcher waiting on a rollout task it added
  holds a slot the queued rollout needs. Any fixed limit deadlocks once N
  waiting tasks hold N slots: one searcher at `max_tasks=1`, two searchers at
  `max_tasks=2`, or a selection-mode worker whose `max_tasks` equals its
  batch size. Requiring a larger `max_tasks` does not fix it (`eval_set()`
  already defaults to at least 10); the rollout task has to start whatever
  the limit is.

## Goals and non-goals

Goals:

- A handle that cancels its task and, for a task fed through it, sends it
  samples, returns each sample's run and waits for the task's final log,
  with one terminal outcome for every way the task can end.
- The search example works at any `max_tasks`, under `eval()`, `eval_set()`
  and selection mode, without exceeding `max_sandboxes` or `max_samples`.

Non-goals:

- Handles that reach a task in another process (another selection-mode
  worker).
- Handles for tasks a `TaskSource` returns.
- The queue, dispatcher, control channel and sandbox setup, which
  [task-dispatch.md](task-dispatch.md) owns.

## Current behaviour

- `enqueue_task()` (`src/inspect_ai/_eval/task/enqueue.py`) returns `None`.
  `enqueue_sample()` (`src/inspect_ai/_eval/task/sample_source.py`) buffers
  into the calling task's own `SampleEnqueuer`, found through a `ContextVar`
  that `task_run` sets (`register_sample_enqueuer`) for a task whose dataset
  is a `SampleSource`.
- A `SampleSource` task's feeder (`feed_samples` inside `task_run`,
  `src/inspect_ai/_eval/task/run.py`) admits buffered samples first, waits
  while samples are in flight, and only when idle awaits
  `next_samples()`; a `None` return ends the task, `[]` makes it loop. The
  enqueuer's `on_enqueue` wakes the feeder.
- `add_samples` (inside `task_run`) reserves `(str(id), epoch)` runs through
  `reserve_runs` and drops samples outside `--sample-id` (silently) or
  beyond `--limit` (with a warning); the source is not told. `reserve_runs`
  gives a sample without an id a generated `dyn-<token>-<counter>` id, whose
  per-attempt token keeps a task retry or checkpoint resume (both keyed on
  `(id, epoch)`) from matching it to another sample's record.
- The source hears each logged sample through `sample_complete(EvalSample)`
  and each sample cancelled before it was logged through
  `sample_abandoned(sample, epoch)`, including samples a graceful task cancel
  (`drain`, `score`, `error`) abandons from the queue. A graceful cancel does
  not end the source: the feeder keeps calling `next_samples()`.
- `_run_task` (`src/inspect_ai/_eval/run.py`) creates each attempt's
  `TaskCancel`, whose `apply` closure wakes paused samples and cancels the
  attempt's scope for `abort` and `retry`. `task_run` passes it to
  `register_eval`, and the control channel's `cancel_task` and `drain_task`
  (`_control/cancel.py`) find it through
  `latest_eval_for_task(...).task_cancel` and call `request()` with
  `abort`, `drain`, `score` or `error`; `retry` is requested only by task
  code.
  A `TaskSource`'s `task_complete` runs inside `_run_task`, after `task_run`
  returns; `sample_complete` and `sample_abandoned` run inside `task_run`;
  `next_tasks()` runs in the dispatcher, outside any attempt.
- Eval-level settings replace a task's own in `prepare_options`: for
  `epochs`, `message_limit`, `token_limit`, `turn_limit`, `time_limit`,
  `working_limit`, `cost_limit`, `fail_on_error`, `continue_on_fail` and
  `score_on_error`, a value passed to `eval()` (or by `eval_set()`)
  overwrites the task's, and the task's value is used only when the run
  passes none. `approval`, `review` and `sentinel` work the same way; tags
  are merged. Every one of these `Task` arguments defaults to `None`.
- The run's epoch reducer (`eval(epochs=Epochs(3, "at_least_2"))`) travels
  apart from the epoch count: `eval_async` passes the resolved reducers to
  `eval_run` as their own argument and records their names in
  `EvalConfig.epochs_reducer` (`src/inspect_ai/_eval/eval.py`).
  `prepare_options` sets that argument on every task, then validates each
  reducer against the task's epoch count (`validate_reducer`), so an
  `at_least_k`, `pass_at_k` or `pass_k_k` reducer raises `PrerequisiteError`
  for a task with fewer than k epochs.
- A sample's sandboxes hold a permit of the process-wide
  `sandboxes/<provider>` limiter from before `sample_init` to after
  `sample_cleanup` (`sandboxenv_context`, `src/inspect_ai/_eval/task/sandbox.py`);
  `max_samples` is per task, and a task with none takes its default from
  its model's connection pool (`create_sample_semaphore`); model connection
  slots are held only during a `generate` call.
- `_resolve_enqueued_tasks` (`src/inspect_ai/_eval/eval.py`) resolves a
  task added inside a running attempt once, under that attempt's model, and
  a task added elsewhere (including from a `TaskSource` callback) once per
  run model. A private `ContextVar` (`_creator`,
  `src/inspect_ai/_eval/task/enqueue.py`) carries the attempt's model in a
  cell the attempt marks ended on exit, so a background coroutine that
  outlives its attempt counts as outside it: `_run_task`
  (`src/inspect_ai/_eval/run.py`) sets it around `task_run`, and each place
  Inspect calls a `TaskSource` callback sets it to `None` for the call.
- Every log records its task's dataset name (`EvalDataset.name`, which
  `TaskLogger` takes from `task.dataset`, `src/inspect_ai/_eval/task/log.py`).
  For a `SampleSource` task the dataset is the unnamed `MemoryDataset` of its
  `initial_samples()` that `resolve_dataset_or_source`
  (`src/inspect_ai/_eval/task/task.py`) builds, at `Task` construction and in
  `task_with`.
- `eval_retry()` recovers every crashed log in its list before it resolves
  any log's task (`eval_retry_async`).
- `eval_set()` judges the result from every log `eval()` returns
  (`all_evals_succeeded`, also its retry predicate), added tasks' logs
  included; later rounds and a selection worker's `resume` match logs to
  requested tasks by `task_identifier()` (`src/inspect_ai/_eval/evalset.py`,
  `{task_file}@{task_name}#{args_hash}/{model}/{additional_hash}`), which
  includes the task name but not the dataset or the task id. The same
  identifier is computed from a `ResolvedTask` and from a log header; it is
  versioned by `TASK_IDENTIFIER_VERSION`, which eval-set capture manifests
  record and inspect_steward checks, refusing a manifest computed under
  another version (`_schedule/reconcile.py`). inspect_flow's Delta store
  (`_runner/run.py`) and inspect_steward's log observation and directory
  store (`_evalset/observe.py`, `_store/`) key logs on this identifier,
  computed from the log header. `eval_set()` passes the names of every task
  in the set to each round and selection worker as `eval_set_tasks`.
- A second `eval()` in the same process while one runs is refused ("Multiple
  concurrent calls to eval_async are not allowed"). A child `inspect eval`
  process starts its own control server by default and publishes a discovery
  entry keyed by its process id, so `inspect ctl` lists and cancels its tasks
  as a separate endpoint.

## Design

### The handle API

```python
def enqueue_task(tasks: Tasks, *, run_id: str | None = None) -> list[TaskHandle]

class TaskHandle:
    task_id: str
    task: str                         # task name
    model: str
    async def enqueue_sample(self, sample: Sample) -> EvalSample:
        """Run `sample` in the task (one epoch) and return its logged run."""
    async def result(self) -> EvalLog | None:
        """Close the handle, then wait until the fed task ends; its final log, or None."""
    def close(self) -> None:
        """Send no more samples; the task ends once the samples sent have run."""
    def cancel(self) -> None:
        """Abort the task, like `inspect ctl task cancel`."""
    async def __aenter__(self) -> "TaskHandle": ...
    async def __aexit__(self, *exc: object) -> None:   # close(), never cancel()

class TaskEndedError(RuntimeError):
    log: EvalLog | None               # the task's final log, None if it ended with none

class SampleAbandonedError(RuntimeError):
    sample: Sample
```

New exports from `inspect_ai`: `TaskHandle`, `TaskEndedError`,
`SampleAbandonedError`, `samples_from_handle`. One handle per record, in
resolution order: a task added inside an attempt, including one fed
through a handle, gives one ("Tasks fed through a handle"); a task added
elsewhere gives one per run model.

The *creator* of a task fed through a handle is the attempt that added it;
its end closes the task's channel. Docs and error messages say "fed through
its handle", not "creator".

- `close()` and `cancel()` are synchronous and idempotent; `close()` on a
  handle whose task is not fed through it does nothing. `cancel()` is
  `RunQueue.cancel` ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)).
- `async with` closes the handle on exit and never cancels the task
  (decision: Ransom, 2026-11-09): a creator that hits a time limit lets the
  rollouts it already sent finish. To stop them when it stops early, the
  creator calls the synchronous `cancel()` in an `except BaseException:`
  and re-raises (decision: Ransom, 2026-11-18). That block runs on an
  error, on a sample limit (`LimitExceededError`), and on every
  cancellation: a time limit and a working limit, which both reach the
  sample's code as a cancellation, and an operator abort. `except
  Exception:` misses the cancellations. `cancel()` awaits nothing, so it
  runs inside a cancelled scope. The block does not run on a normal exit;
  a `finally:` would, and there `cancel()` aborts the rollout task, which
  is still running (it ends only once its channel is closed and its sent
  samples have run, and closing does not wait for that), leaving a search
  that succeeded with a rollout log that says "Task cancelled by user
  (abort)" and has status `error`. The handle docs and the overview example show
  `except BaseException:`.
- `result()` waits only on a task fed through its handle (decision: Ransom,
  2026-11-12). On the handle of any other task it raises `RuntimeError`
  ("result() waits only on a task fed through its handle
  (samples_from_handle()): wait on a task fed through its handle, or read
  its log after the run"). An ordinary added task needs a `max_tasks` slot
  of its own while the waiting task keeps its slot, so a run whose every
  running task waited on a queued one would not progress; the use case
  never waits on one, and allowing it later breaks nobody. `cancel()`,
  `close()` and the attributes work on every handle.
- `result()` closes the handle first (decision: Ransom, 2026-11-10).
  Without that, a creator that awaits `result()` on a task it feeds would
  wait for an end that its own open handle prevents; the cost is that another
  holder of the same handle can no longer send.
- Every method checks first that it runs on the run's event loop
  (`_require_run_loop`), as `enqueue_task()` does.
- `enqueue_task()` stays synchronous (decision: Ransom, 2026-11-16, with
  the reasons restated 2026-11-18) for two reasons. Adding a task awaits
  nothing: resolution, `configure_task()` and `RunQueue.add` are
  synchronous, and the log, sandbox setup and model controller come with
  the attempt. And an async version would silently break every existing
  call that does not await it: the call would return a coroutine that never
  runs, so the task would never be added, with no error. Returning a handle
  is not a reason either way; every wait is on the handle. Backpressure on
  adds, if ever needed, would be a new async method or an await on the
  handle, not a change to this call.

**Terminal outcomes.** Every record ends (task-dispatch.md, invariant 2),
including when dispatch ends, so no wait outlives its target:

| how the target ended | `result()` | an unresolved `enqueue_sample()` |
| --- | --- | --- |
| an attempt returned a log (success, error, setup failure, log-init failure, abort, a run-level cancellation of a running task) | that log | `TaskEndedError(log=<that log>)` |
| no log (a fed task closed before any sample was sent, cancelled before it started, or still queued when dispatch ended) | `None` | `TaskEndedError(log=None)` |

A request that already has its run keeps it; one abandoned raises
`SampleAbandonedError`. A cancelled caller's wait raises the cancellation;
the sample it sent still runs and its result is dropped.

### What is refused

- **`result()` on a handle whose task is not fed through it**:
  `RuntimeError` ("The handle API"), before the handle is closed or anything
  waits.
- Handle waits inside `TaskSource.next_tasks()` need no rule of their own.
  The dispatcher calls it only when no attempt is running
  ([task-dispatch.md](task-dispatch.md#the-dispatcher)), so every fed
  task's creator has ended and closed its channel, and every fed task has
  ended: `result()` returns its log at once and `enqueue_sample()` raises
  `TaskEndedError` with that log (the order below).
- **`samples_from_handle()` tasks** are added only by `enqueue_task()` from
  code running inside an attempt that has not ended (`_attempt` set and
  `ended` false), which becomes the creator: a solver, scorer or tool, a
  task-level hook such as `on_task_start`, or a coroutine left over from a
  finished sample. Such a task closes with the attempt like any other.
  `enqueue_task()` checks this before `RunQueue.add` commits anything.
  Elsewhere:
  - outside any attempt: `RuntimeError` from `enqueue_task()`;
  - in any `TaskSource` callback (`next_tasks()`, `task_complete`,
    `sample_complete`, `sample_abandoned`), whether called directly or
    returned, though `task_complete` and the sample callbacks run inside an
    attempt and `task_complete` can run after its task's `EvalState` is
    terminal: `RuntimeError`. Each place Inspect calls a source callback
    (`notify_task_source` for `task_complete`, `task_run` for
    `sample_complete` and `sample_abandoned`, the dispatcher for
    `next_tasks()`) sets `_attempt` to `None` for the call and resets it
    after (a `ContextVar` token), so the existing check refuses a direct
    `enqueue_task()` of a fed task with no new condition, and a coroutine
    the callback starts inherits `None`. Tasks a callback returns are added
    with no creator, and `RunQueue.add` refuses a fed one. An ordinary
    `enqueue_task()` from a callback needs no attempt and works as today
    (decision: Ransom, 2026-11-17, confirming the callback refusal of
    2026-11-12, whose premise that callbacks run outside attempts was
    false for `task_complete`);
  - with `epochs` above 1: `ValueError` from `enqueue_task()` ("a task fed
    through its handle runs each sample once; send a sample again to repeat
    it");
  - passed to `eval()`, `eval_set()` or a selection worker:
    `PrerequisiteError` from `eval_resolve_tasks` ("task '<task>' takes its
    samples through its handle (samples_from_handle()), so it cannot be run
    or retried on its own; run or retry the task that adds it"). This
    includes a whole-file spec: `create_file_tasks()` loads every decorated
    task in a file given without a task name, so `inspect eval search.py`
    with the rollout task beside its creator is refused, and the creator is
    selected by name (`search.py@search`), as the overview shows;
  - its log passed to `eval_retry()`: `PrerequisiteError` from
    `eval_retry_async`, by the log's dataset name, before any task is
    resolved ("Logs and eval sets");
  - as a `PreviousTask` or a `ResolvedTask` (with or without a prior sample
    source): `ValueError` ("tasks fed through a handle must start fresh;
    pass the Task");
- **A fed task named like a requested or seed task is not refused.** Its
  identifier, `…#samples_from_handle/{model}/{task_id}`, already keeps its
  log apart from every requested task's ("A fed log's identifier"), and
  every eval-set matching path compares identifiers, not names. The cost:
  a fed task and a requested task can share a name in the display,
  `inspect ctl task list` and the viewer, and a control-channel selector by
  name and model then matches both, so the CLI reports its existing
  ambiguity error and asks for the task id, as it already does when a
  creator adds several rollouts from one factory.
- **A user dataset named `samples_from_handle`**: `ValueError` from
  `resolve_dataset_or_source` ("the dataset name 'samples_from_handle' is
  reserved for tasks fed through a handle"), at `Task` construction or in
  `task_with`, so no other task's log can carry it.
- **The free `enqueue_sample()` function** (exported from `inspect_ai`,
  which adds samples to the calling task's own `SampleSource`) inside a task fed
  through a handle: `RuntimeError` ("enqueue_sample() cannot add samples to
  a task fed through its handle; only the handle that added it sends
  samples"), before anything is buffered. `task_run` registers the attempt's
  `SampleEnqueuer` as for any source, and marks it as a handle channel's
  when the task's source is a `HandleChannel`; the free function checks the
  mark. The channel puts its own requests in that buffer directly, so
  delivery is unchanged, and every other `SampleSource` task keeps today's
  behaviour. Without the refusal a rollout solver could add work its handle
  never sent, including after `close()`, which the feeder admits before it
  asks whether the source has ended.
- **`TaskHandle.enqueue_sample()`** on a handle whose task is not fed
  through it: `RuntimeError`; with a sample that has an `id`: `ValueError`
  (the channel assigns ids). Otherwise a send to a channel that no longer
  accepts samples raises by one order, checked against the record and the
  channel's own state, first match wins:
  1. the task has ended (the record is `ended`): `TaskEndedError` with its
     final log, or `None`;
  2. the channel is closed, by any cause (`close()`, `result()`, `async
     with` exit, `cancel()` before the task ends, the end of the creator's
     attempt, or an operator `abort`, `drain`, `score` or `error` cancel,
     while sent samples still run or the attempt's abort unwinds):
     `RuntimeError` ("the handle is closed, by its holder or an
     operator drain or cancel: send no more samples").

  So a handle kept from a finished creator, or one whose task an operator
  drained, raises `RuntimeError` while its task's last samples run and
  `TaskEndedError` once the task has ended, and a send after a drain of an
  idle channel, which ends the task, raises `TaskEndedError`.
  `TaskEndedError` is a `RuntimeError` subclass, so tests assert the exact
  type.
- Off the run's loop: `RuntimeError` (see "The handle API").

### What the handles add to the run queue

```python
@dataclass(eq=False)
class TaskAttempt:                     # one per run_one attempt
    record: TaskRecord
    ended: bool = False                # set where run_one publishes a retry or ends the record, counted or not
    channels: list[HandleChannel] = field(default_factory=list)   # channels of tasks it added

_attempt: ContextVar[TaskAttempt | None]   # set by run_one around _run_task
```

`TaskRecord` gains `channel: HandleChannel | None = None`.
`RunQueue.add` takes `creator: TaskAttempt | None`, which `enqueue_task()` passes from
`_attempt`. The dispatcher's uncounted start, which task-dispatch.md
already uses for a record with `abort_requested`, also starts each queued
record with a channel that holds a request, in queue order, if it is
startable (task-dispatch.md "Start rule"); it is skipped once the
dispatcher has latched a cancellation:

```
    for each pending entry with abort_requested, or with a channel that
            holds a request and is startable, in queue order:
        start_attempt(entry, counted=False)
```

An attempt started this way does not count toward `in_flight`. The
ordinary picks skip every record that has a channel or `abort_requested`,
and both passes start an entry through task-dispatch.md's `start_attempt`,
which takes it out of the same pending list and moves the record into
`attempt` in one synchronous step, so no record is started twice. `RunQueue.end` closes
the record's channel, settling every request still unsettled with
`TaskEndedError(log)`.

### Tasks fed through a handle

`samples_from_handle()` returns a `HandleChannel`, a `SampleSource` with no
seed. `RunQueue.add` gives each record whose task has one a fresh
`HandleChannel` on the record's configured copy of the task, and records it
in the creator's `TaskAttempt.channels`.

```python
class HandleChannel(SampleSource):
    enqueuer: SampleEnqueuer | None    # the attempt's buffer, while it runs
    token: str                         # the first 8 characters of the record's task id
    requests: dict[str, PortRequest]   # every unsettled request, by sample id, in send order
    sent: int                          # samples accepted so far; the next id's counter
    closed: bool
    pushed: Wake

@dataclass(eq=False)
class PortRequest:
    sample: Sample                     # the channel's copy of the caller's sample, with its id
    future: Future[EvalSample]
```

- **Its dataset name.** `resolve_dataset_or_source` gives a
  `HandleChannel`'s `MemoryDataset` the reserved name `samples_from_handle`,
  so every log of a fed task records `eval.dataset.name ==
  "samples_from_handle"`. The record's fresh channel keeps the task's
  dataset, and the name lives in the eval spec, so every copy of the log
  (conversion, recovery) carries it. It is what `eval_retry()` and the eval
  set's result read ("Logs and eval sets").
- **One record, under the creator's model, one epoch.**
  `_resolve_enqueued_tasks` resolves a task whose dataset is
  `samples_from_handle()` once, for the model of the creator's attempt in
  place of the run's model list, as it does any task added inside an
  attempt (a `Task` that sets its own `model` keeps it, as in any
  resolution). So `enqueue_task()` returns one handle for it,
  and a creator in a multi-model run feeds a rollout task under its own
  model. Each sent sample runs once: a creator that wants repeats sends the
  sample again.
- **It starts on its first sample and takes no slot.** The record waits in
  `queued`, listed and cancellable like any queued task, until its channel
  holds a request; the dispatcher then starts it at once, whatever
  `max_tasks` is, and its attempt is not counted against the limit. A fed
  task does nothing its creator did not send: its samples are bounded by
  `max_samples`, `max_sandboxes` and the model's connection limit like any
  task's, and its creator's own slot is counted. A record whose channel
  closes before any sample was sent ends with no log and no attempt, so a
  handle that is never used costs nothing, and so does a record cancelled
  while queued ("Closing"). Its model controller is created
  lazily on its first `generate`, as for any added task
  ([task-dispatch.md](task-dispatch.md#adding-tasks)); under its creator's
  model it usually exists already. When it does not (the rollout task sets
  its own `model`, or its creator is an added task that has not generated
  yet), an `inspect ctl config --max-connections` retune made before it is
  created misses it, as for any added task, until the follow-up that
  remembers retunes and applies them when a controller is created
  ([task-dispatch.md](task-dispatch.md#not-this-design)); the controller is
  still created lazily then. It has no seed, so
  its attempt sets up no sandbox before its first sample, and the
  dispatcher, which never waits on a setup, starts it as soon as a sample is
  sent.
- **Sending.** `enqueue_sample(sample)` takes its own copy of the sample
  (`model_copy()`, so the caller's object is unchanged) with the id
  `send-<token>-<n>`: the channel's token and its `sent` counter,
  zero-padded to four digits as generated ids are. It creates a
  `PortRequest` with one future, records it in `requests` under that id,
  puts the copy in the running attempt's buffer (`enqueuer.enqueue`), which
  wakes the feeder, or leaves it for delivery if the attempt has not
  started, rings `pushed` and the queue's `wake`, and waits for the future.
- **Ids.** The channel's ids are explicit ids to `reserve_runs`, which
  admits them as given. Within the task they cannot collide: it has no
  seed, a caller-set id is refused, and the counter never repeats. The
  token makes them unique across tasks too. It is the first 8 characters of
  the record's task id, which resolution generates afresh for every
  `enqueue_task()` call (a fed task is accepted only as a `Task`, so no
  already-resolved task id can be added again in another run), so a fresh
  rollout task a creator adds after a failure, and the one a retried
  creator adds again, each get their own token, as do the rollout tasks of
  two creators. So a sent id never names two samples: logs of the same
  rollout task can be grouped by sample id, and nothing that reuses a
  record by `(id, epoch)` can match one sent sample to another, whichever
  route reaches it. The token is the task's rather than the attempt's
  `eval.created` second (the token of today's generated ids) because a
  sample can be sent before the attempt starts. Ids sort in send order
  within a log, up to 9,999 samples.
- **Delivery.** `task_run`, where it registers the attempt's `SampleEnqueuer`,
  attaches it to the channel and puts every request's sample in it, in send
  order; where it clears the enqueuer, it detaches it. The feeder admits the
  buffer as it admits any enqueued sample, so a sample starts as soon as
  `max_samples` allows. A sent sample can need a sandbox setup; the feeder
  runs it through `startup_sandboxes` before scheduling the batch, as for
  any `SampleSource` addition, and its failure fails this task only.
- **`next_samples()`** waits on `pushed` and returns `[]` after a send, so the
  feeder drains the buffer, or `None` once the channel is closed,
  which ends the task when nothing is in flight or buffered (samples sent
  while that `None` is returned still run, as for any source).
- **Results.** `sample_complete` resolves the future of the request holding
  that id (an errored or operator-cancelled sample is returned with its
  `error`), and `sample_abandoned` fails it with `SampleAbandonedError`; both
  return `None`. A future already resolved keeps its first value (a sample
  the operator requeues reports again). A request leaves `requests` when its
  future settles, so the channel holds no sample or result after its call
  returns. A caller whose wait is cancelled leaves its request in place: the
  sample still runs, and the request is removed when it settles or the task
  ends, with its result dropped.
- **Settings.** `configure_task()` resolves a fed task's settings before it
  builds the task's logger, so the log's eval config records the values
  that applied. Only fed tasks take this rule: every other task, an
  ordinary task added from inside a running task included, keeps today's
  resolution, where the run's value replaces the task's (decision: Ransom,
  2026-11-19):
  - The sample limits (`message_limit`, `token_limit` with its
    `token_limit_type`, `turn_limit`, `time_limit`, `working_limit`,
    `cost_limit`), error tolerance (`fail_on_error`, `continue_on_fail`,
    `score_on_error`) and `max_samples` are the fed task's own value if it
    sets one, else the run's, else the default (for `max_samples`, the
    default from its model's connection pool). So a rollout task that sets
    no `max_samples` runs at most the run's `max_samples` samples at once
    when the run sets one; its author sets the task's own value to size it
    apart from the run. `inspect ctl config --max-samples` retunes it while
    it runs, as for any task.
  - `epochs`, the epoch reducer, `limit` and `sample_id` are cleared: one
    epoch, no reducer from the run, no limit, no selection, whatever the run
    passes. For the reducer, `configure_task()` does not apply the run's
    reducer argument to a fed task and clears `epochs_reducer` from its eval
    config along with `epochs`, before resolving the task's own one-epoch
    configuration; the task's own reducer, if it sets one, is validated and
    recorded as today. Otherwise a run with `epochs=Epochs(3, "at_least_2")`
    (or a `pass_at_2` or `pass_k_2` reducer) would refuse every fed task,
    since such a reducer needs two epochs. `--limit` and `--sample-id` choose
    among the requested tasks' samples; a fed task's samples are chosen by
    its creator, whose own selection already limits what it sends, and a
    run-wide value would silently drop requests (a `--sample-id 3` filters
    every sent id, and a `--limit 2` ends the task after two). A `task:id`
    selector naming the fed task's name selects nothing there, and the "No
    sample_id selector names task" warning is not logged for it.
  - `approval`, `review` and `sentinel`: the run's value still wins, as
    today; they are the operator's oversight controls for the whole run.
  - Tags stay merged; generate config and the run-wide limits (`max_tasks`,
    `max_sandboxes`, `max_connections`) are unchanged.

  The creator's own settings are not inherited: the searcher passes what it
  wants shared when it builds the rollout task. Other `SampleSource` tasks
  keep today's resolution and filtering.
- **Closing.** `channel.close()` sets `closed` and rings `pushed` in one
  synchronous step, so a feeder parked in `next_samples()` wakes and returns
  `None`; a second call does nothing. Every cause uses it: `close()`,
  `result()`, `async with` exit, `cancel()`, an `abort`, `drain`, `score`
  or `error` cancel (the attempt's `TaskCancel.apply`, which
  `start_attempt` creates with the attempt's cancel scope, calls
  `channel.close()` for every action, `abort` included, before it cancels
  the scope; [task-dispatch.md](task-dispatch.md#phases-and-cancelling)),
  the end of the creator's attempt (`run_one` sets
  `ended` and closes the attempt's channels in the synchronous step in which
  it publishes a retry or ends the record, its exception exit included, for
  a counted and an uncounted attempt alike, so a fed task that is itself a
  creator closes its channels when it ends) and `RunQueue.end`. Closing a
  channel whose record is still `queued` with no request ends the record
  with no log. A creator that forgets to close cannot keep a rollout task
  open past its own attempt.
- **Cancelling.** A fed record is never retried, so while it is `queued` it
  has never started. `RunQueue.cancel` of such a record ends it at once with
  no log, `RunQueue.end(record, None)`, whether or not a request was sent:
  that closes its channel and settles every request with
  `TaskEndedError(log=None)`, as for a handle closed before any sample was
  sent or a record still queued when dispatch ends (decision: Ransom,
  2026-11-19). No abort attempt runs, the run's `TaskSource` hears nothing,
  and the record never gets `abort_requested`, so every way a fed task can
  end before it starts has one outcome. The abort log and report an
  ordinary queued task ends with exist for `eval_set()`'s result and for a
  source waiting on reports; a fed log does not decide the result ("Logs
  and eval sets"), and a fed handle never used already ends unreported.
  In `attempt`,
  `RunQueue.cancel` routes the cancel as for any record
  ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)) and then
  closes the record's channel itself, in the same synchronous call, so a
  handle's `cancel()` does not depend on the directive being accepted.
  That covers a fed attempt that has already ended on its own (its
  `EvalState` terminal, its enqueuer detached) while its `task_complete`
  still runs: `cancel_task` then answers "task already finished" without
  calling `apply`, and the record is still in `attempt`. So a send between
  a fed task's `cancel()` and the record's end raises `RuntimeError` at
  once rather than waiting through the abort's log write, or the natural
  end's `task_complete`, for `TaskEndedError`. Samples already buffered or
  running when a drain, `score` or `error` cancel closes the channel follow
  the directive's existing rules and settle through `sample_complete` or
  `sample_abandoned`; an abort cancels them with the attempt, as today.
- **Retries.** A task fed through a handle is never retried automatically
  (decision: Ransom, 2026-11-10). When its attempt fails for any reason, a
  sent sample's sandbox setup included, the task ends with its error log,
  its unresolved `enqueue_sample()` calls raise `TaskEndedError` with that
  log, and the calls already returned keep their runs. The creator holds
  the search state and every result returned, and decides whether to add a
  fresh task. `start_attempt` (task-dispatch.md "Starting an attempt")
  creates such a task's `TaskCancel` with `can_retry=False`, whatever the
  run's retry budget, and `run_one` queues no retry for it, so no retry is pre-marked or reported
  (`will_retry` is false), and a retry the task requests itself through its
  `TaskCancel` is not honoured, as for a task with no retries left.
- **Logs and eval sets.** A fed task's log is an ordinary log whose
  dataset name is `samples_from_handle`. `eval()` returns it with the run's
  other logs, `eval_set()` returns it among its logs, and it is written to the log directory, where
  `inspect log list`, `list_eval_logs()` and the viewer list it. It does not
  decide the eval set's result: `all_evals_succeeded`, which is also
  `eval_set()`'s retry predicate and selection mode's result, skips the
  logs with that dataset name. So a creator that cancels its running
  rollout task, or whose rollout task failed and was replaced, does not
  fail the set (a rollout task cancelled while queued has no log at all);
  the creator's own log does, if the creator fails.
  `eval_retry()` refuses a fed task's log: after it recovers its crashed
  logs, as for any log (recovery runs nothing), and before it resolves any
  task, `eval_retry_async` checks every log's `eval.dataset.name` and raises
  `PrerequisiteError` ("task '<task>' took its samples through its handle
  (samples_from_handle()), so it cannot be retried on its own; retry the
  task that added it"), so a list holding such a log retries nothing. The
  check reads the log, so it holds however the task was built, including
  `task_with(registered_task(), dataset=samples_from_handle())` after the
  `@task` function returned, whose log names that factory and whose
  rebuilt task would have the factory's own dataset.
- **A fed log's identifier.** A fed task can have the name, arguments and
  model of a task an eval set requests, in the same run or a later one, for
  example the factory a creator adapted with `task_with`. So a fed task's identifier is built from its
  task id: when the dataset name is `samples_from_handle`
  (`task.task.dataset.name` for a `ResolvedTask`, `eval.dataset.name` for a
  log), `task_identifier()` returns
  `{task_file}@{task_name}#samples_from_handle/{model}/{task_id}` (without
  the `{task_file}@` prefix for a task with no source file, as today),
  where `task_id` is `ResolvedTask.id` or the log's `eval.task_id`. It
  computes neither the args hash nor the additional hash for a fed task.
  The existing `EvalSpec.task_id` meets every requirement, so no field is
  added:
  - it is stored in every log's eval spec, so the identifier recomputed
    from a log header on every read is the one computed at run time;
  - it is unique to the fed task: a fed task is always a fresh `Task`
    (refused as a `ResolvedTask` or `PreviousTask`, which keep an id), and
    each addition resolves to a new id;
  - it is the same on every attempt of the record, since `run_one`'s
    retries keep the logger's eval spec and its task id (a fed task is
    never retried today, so its one attempt is all there is, but anything
    that groups attempts by identifier still sees one task), unlike
    `eval_id`, which is new per attempt;
  - `ResolvedTask.id` is the task id the logger writes, so a `ResolvedTask`
    and its log give the same identifier.

  The settings are left out because the task id alone makes the
  identifier unique and stable, nothing matches a fed log by its settings,
  and the settings are the only inputs on which the `ResolvedTask` branch
  and the log-header branch can disagree. A fed task's settings are one
  such disagreement: they resolve task-first ("Tasks fed through a
  handle"), so the resolved branch, which applies the run's limits over the
  task's, would hash the run's `message_limit` where the log records the
  task's own. With no settings in the identifier, no precedence rule is
  needed in `task_identifier()`.

  No ordinary task can produce this form: an ordinary identifier's part
  after `#` is the args hash. Ordinary identifiers are unchanged, so
  `TASK_IDENTIFIER_VERSION` is not bumped: inspect_steward refuses a
  manifest computed under another version (`_schedule/reconcile.py`),
  inspect_flow's Delta store names its column
  `task_identifier_{TASK_IDENTIFIER_VERSION}` (`_store/deltalake.py`), and
  no ordinary identifier, nor any manifest or store, changes. Only a log whose user
  dataset was named `samples_from_handle` before the name was reserved
  would get a new identifier. The consumers treat an identifier as an
  opaque string: inspect_ai's eval-set code, inspect_flow's runner and Delta
  store (`_runner/run.py`, `_runner/logs.py`, `_store/deltalake.py`) and
  inspect_steward's manifest,
  reconcile, observation and stores (`_evalset/manifest.py`,
  `_schedule/reconcile.py`, `_evalset/observe.py`, `_store/`) compare it
  whole, use it as a key, or hash it whole (Steward's score class keys take
  `digest8(identifier)`); none splits it into its parts. The splitting on
  `@` in Steward's `_tend/items.py` and `_evalset/classify.py` is of
  anomaly class keys built from exception types, not of task
  identifiers.

  A fed log in an eval-set directory is then a log of an identifier the set
  does not request, like any added task's: matching never takes it for a
  requested task, and a selection worker given it as `resume` refuses it
  with its existing identifier check (`_resumed_task`).
- **The log-directory check skips fed logs** (decision: Ransom,
  2026-11-18). `validate_eval_set_prerequisites`
  (`src/inspect_ai/_eval/evalset.py`), which a resumed `eval_set()` and
  every later `retry_immediate=False` round run over the directory's logs,
  raises `PrerequisiteError` for a log whose identifier the set does not
  request unless `log_dir_allow_dirty=True`, and with that flag drops such
  logs from the list it returns. It now skips every log whose
  `header.eval.dataset.name` is `samples_from_handle` in both branches: no
  error, and left out of the returned list as the dirty branch leaves out
  every unrequested log, so `write_eval_set_info` and log matching see what
  they see today with the flag set. So a search's eval set resumes over its
  own rollout logs without `log_dir_allow_dirty=True`, which would turn the
  check off for every stray log. The name is reserved ("What is refused"),
  so no other log is skipped. An ordinary added task's log still fails the
  check without the flag, as today: it carries no mark that it was added
  ("Not this design").

### Waits and limits

A fed task takes no `max_tasks` slot, and `result()` waits only on fed
tasks, so no handle wait needs a slot. Three limits still apply to work
that a handle wait depends on, and none is lent:

- **`max_sandboxes`.** A waiting sample keeps its `sandboxes/<provider>`
  permit. `max_sandboxes` is often a hard quota (a cloud account's sandbox
  limit, a cluster's capacity), a sandbox is a live resource rather than
  bookkeeping, and the limiter is a semaphore that cannot hand a permit to
  one specific sample, so permits are not lent. `max_sandboxes` for each
  provider both tasks use must exceed the number of samples that hold one
  while waiting.
- **`max_samples`** is per task, so a task's samples that wait on work its
  own other samples do need room for both.
- **`max_connections`.** A model connection permit is held for the whole
  of a `generate` call (`Model._generate_prepared` enters
  `_connection_concurrency` before `_generate`), and `_generate` awaits the
  public `on_before_model_generate` hook inside it. That hook runs in the
  attempt, where handle calls are allowed, so a hook that awaits a sent
  sample on the creator's model holds a permit that sample needs: with
  `max_connections=1` it waits forever, whatever the sample and sandbox
  headroom. A run that waits from such a hook needs a connection limit
  above the number of such waits.

No warning covers any of the three (decision: Ransom, 2026-11-19): a
warning when a wait starts with every permit in use would also fire when
the holders are about to finish, and for sandboxes it would need each
sent sample's provider resolved and tracked until it settles
("Alternatives considered"). The `max_tasks`, `max_samples`,
`max_sandboxes` and `max_connections` docstrings, `docs/parallelism.qmd`
and the handle docs in `docs/task-source.qmd` state the fed-task exception
to `max_tasks` (beside the exception for a task cancelled while queued that
task-dispatch.md documents), the `max_sandboxes`, `max_samples` and
`max_connections` headroom a waiting run needs, and that `inspect ctl
config --max-sandboxes N` raises the sandbox limit while the run goes on.

## Alternatives considered

- **Running the rollout task in a separate Inspect process.** A nested
  `eval()` is refused in-process, so the route is a child `inspect eval`
  through `subprocess()`, whose log the searcher reads. It shares no
  dispatcher, `max_tasks`, working directory or provider state, isolates a
  crash, and works today. But each child pays Inspect's import, model client
  start-up and the sandbox's `task_init`; amortizing that needs a long-lived
  child whose source reads requests from a file or socket, a protocol each
  user builds. Per-process `max_connections`, rate-limit backoff,
  `max_sandboxes` and token limits are not shared, and the child is outside
  `eval_set()` retry and resume and an external supervisor's fleet
  accounting. Until in-process sample sending exists, the long-lived child is
  the way to run such a search.
- **Lending a slot to the task a running task waits on.** It makes a wait on
  any added task safe at every `max_tasks`, but needs a loan per target with
  its waiters, a second start step, slot bookkeeping for every wait, waits
  refused outside a slot-holding attempt, and rules for a wait that outlives
  its attempt and for nested loans. The use case waits only on fed tasks,
  which need no slot at all.
- **`result()` on any handle, with a warning for `max_tasks`.** A wait on an
  ordinary added task keeps the waiter's slot while the awaited task needs
  one, so a run whose every running task waits on a queued one stops until
  an operator runs `inspect ctl config --max-tasks N`; Inspect would warn
  when such a wait begins with no slot free, and would refuse waits inside
  `TaskSource.next_tasks()`, where nothing starts until the call returns.
  The use case never waits on an ordinary task, and refusing the wait now
  leaves room to allow it later without breaking anyone.
- **No added task counts toward `max_tasks`.** Unbounded: a task that adds
  one fixed-dataset task per sample runs them all at once. A fed task runs
  only what its creator sends, so exempting those alone stays bounded by the
  sample limits.
- **Starting a fed task when it is added.** It would remove the start
  condition and the rule that closing an empty channel ends a queued record
  with no log ("Closing"). But a handle never used would run an attempt,
  write an empty log and fire the task hooks. Starting on the first sample
  costs that close rule; the start itself needs nothing new, because the
  dispatcher already rescans on `wake` (decision: Ransom, 2026-11-17,
  kept 2026-11-18).
- **A fed task cancelled while queued ending through an abort attempt**, as
  an ordinary queued task does
  ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)), with the
  abort log and one report to the source. That serves an ordinary task
  because `eval_set()` counts its abort log as a failure and a source may
  wait on its report. A fed log counts toward neither the eval set's result
  nor its log-directory check, and a fed task ending with no log is already
  an outcome (a handle never used). Taking the abort path would need an
  exception to the empty-channel close rule, so that a cancel which closes
  the channel leaves the record queued for its abort attempt, and an order
  inside `RunQueue.cancel` (set `abort_requested`, then close the channel)
  (decision: Ransom, 2026-11-19, replacing the 2026-11-17 queued-cancel
  rule for fed records only).
- **One fed task per run model**, as for tasks added outside an attempt. The creator would
  pick the handle for its own model and close the rest in every use.
- **Several epochs per sent sample**, with one result per epoch. It needs a
  future per epoch, a request that is partly abandoned, and an epoch on
  `SampleAbandonedError`. A creator that wants repeats sends the sample
  again and sees each result as it comes.
- **A fed task inheriting its creator's settings.** The creator's limits and
  error tolerance are chosen for the search, not for one rollout; the
  searcher passes what it wants shared when it builds the rollout task.
- **Task-first settings for every task added from inside a running task**,
  fed or not, so a creator has one rule for every task it adds. It changes
  an existing feature, ordinary added tasks, and brings compatibility work
  with it: `task_identifier()` pairing for a `ResolvedTask` added that way,
  `eval_retry()` replaying a recorded epoch pair (and the run's fallback for
  tasks added during the retry), and migration text for existing evals.
  Fed tasks are new and need none of it, so only they resolve task-first
  (decision: Ransom, 2026-11-19, narrowing the 2026-11-18 one-rule
  decision); it can be revisited if a real need appears.
- **A fed task's `max_samples` skipping the run's value**, going from its
  own straight to its model's pool default. It was chosen while a `Task`
  could not set its own `max_samples`, when a fallback to the run's value
  would always have won. Now the rollout task sets its own when it wants a
  size apart from the run's, and its `max_samples` resolves like its other
  settings, with no branch of its own (decision: Ransom, 2026-11-19).
- **`max_samples` and similar settings as keyword arguments on
  `enqueue_task()`.** They would cover only `enqueue_task()`, with a second
  precedence rule beside the task's own settings; `max_samples` on `Task`
  works however the task enters the run.
- **A `send_samples=True` keyword on `enqueue_task()`** with a port attached
  to any `SampleSource` task, serviced by a feeder that pulls the source
  concurrently. It lets handle samples share a sample budget with the task's
  own source, but needs a rewritten feeder (a concurrent pull, a held buffer,
  repulls after late additions, cancelling the pull) and delivery checks
  against the source's ids. Declaring the feeding on the receiving task uses
  the existing buffer and callbacks.
- **Generated `dyn-` ids for sent samples.** The attempt assigns them at
  admission, so the channel would have to find each request by the identity
  of its buffered sample and be told the id afterwards. Assigning the id at
  send keys the request from the start.
- **A plain counter (`send-<n>`) with no token.** Safe only while every
  route that reuses a record by `(id, epoch)` stays closed to fed tasks (no
  retry, no `eval_retry()`, a checkpoints directory per log), and every
  rollout log of a task would hold a `send-0001` naming a different sample.
  Integer ids assigned in admission order had this failure before generated
  ids replaced them; the token costs nothing.
- **Caller-chosen ids on sent samples.** They need duplicate checks against
  the task's other ids.
- **An `EvalSpec.send_samples` field** marking a fed task's log, read by
  `eval_retry()`, `task_identifier()`, selection resume and `eval_set()`'s
  result. It is a log schema change with a coordinated viewer update; the
  reserved dataset name marks the log with a field every log already has.
- **Refusing `eval_retry()` when the rebuilt task's dataset is
  `samples_from_handle()`**, with an in-process set of fed task ids for the
  eval set's result. A task adapted with `task_with` after its `@task`
  function returned has a log naming that function, whose rebuilt dataset
  is the factory's own, so the retry would run without the sent samples.
  Closing that needs a marker `task_with` sets, the `@task` wrapper clears
  and `enqueue_task()` refuses; the dataset name is read from the log and
  needs none of it.
- **Counting a fed task's log in the eval set's result**, as for other
  added tasks. A creator that recovers from a failed rollout task, or
  cancels one it no longer needs, would fail the set although the search
  succeeded.
- **Retrying a fed task after a failure.** The retry would have to bring the
  requests already settled into its results without running them again,
  which the existing reuse path does only for records it can read back from
  the log, and hand the unsettled requests to the retry. The creator already
  holds every result returned and can add a fresh task, so the task ends with
  its error log instead (decision: Ransom, 2026-11-10).
- **Applying the run's `--limit` and `--sample-id` to fed tasks**, telling
  the creator about each dropped request. The options select among requested
  tasks' samples and say nothing useful about samples a creator chooses; a
  run limited for debugging would drop most rollouts.
- **A `started()` wait and a `state` property.** Nothing in the use case waits
  for a start or polls a state; `result()` and `enqueue_sample()` cover it.
- **`async with` cancelling the task on exit.** A creator that hits a time
  limit would abort rollouts already running, and a creator that returns
  normally would abort the rollout task before it finished its samples; a
  creator that wants to stop them when it stops early calls `cancel()` in
  an `except BaseException:` that re-raises.
- **A warning when a handle wait starts while every `max_sandboxes` permit
  of a provider it depends on is in use**, naming `inspect ctl config
  --max-sandboxes`. For `enqueue_sample()` it needs each sent sample's
  effective provider resolved (an `await resolve_sandbox(...)` per send);
  for `result()`, the providers of every sent sample not yet settled
  tracked per request; and once-per-provider state for the run. It is only
  advice, since holders that finish release their permits, so it can fire
  when nothing is stuck. A version for `enqueue_sample()` alone drops the
  per-request tracking but keeps the per-send resolution. The docs state
  the headroom instead (decision: Ransom, 2026-11-19).
- **Refusing waits that would never end** with a process-level wait-for graph
  over handle waits and sandbox and sample permits. It must be re-checked
  at every blocking event and limit change (a live retune can lower a limit
  below its use); documented headroom covers the configurations the use
  case needs.

## Compatibility and migration

Public API: `enqueue_task()` returns `list[TaskHandle]` and stays
synchronous, so existing calls on the run's event loop are unchanged; a
call from a worker thread that copied the run's context, which today
buffers the task, now raises `RuntimeError`, and the worker calls
`anyio.from_thread.run_sync(lambda: enqueue_task(...))` instead
([task-dispatch.md](task-dispatch.md#compatibility-and-migration)). New
`TaskHandle`,
`TaskEndedError`, `SampleAbandonedError` and `samples_from_handle`. Existing `SampleSource` tasks, and every ordinary task added with `enqueue_task()`, keep their settings resolution and filtering: only a task fed through a handle ignores
the run's `--limit`, `--sample-id` and `--epochs` (with the run's epoch
reducer), resolves its settings, `max_samples` included, before the
run's, is exempt from `max_tasks` and is left out of
`eval_set()`'s result and the eval set's log-directory check.

inspect_flow's Delta store and inspect_steward's log observation and
directory store key logs on `task_identifier()` from the log header, so a
fed log can be observed, published and copied like any log, but its
identifier never matches another task's, in this project or another, and
it is never reused for one. Neither needs a change to read fed logs. Two
limitations remain, both documented rather than changed, and Steward
selection workers have one prerequisite (below):

- neither knows a fed log's role: they treat it as the log of a task the
  set does not request, as they treat an ordinary added task's log today
  (Flow's `_print_result` reports "Log returned that does not match any
  task" for each);
- Flow's `_print_result` prints "Some logs failed even though the eval set
  succeeded" when the creator succeeds and a fed task fails, because the
  eval set's result ignores fed failures ("Logs and eval sets").

**Prerequisite for Steward selection workers.** Steward marks a log whose
identifier is not in its manifest as orphaned and archives it (moves the
file) unless that identifier is in its running set
(`_schedule/reconcile.py`, `_archiving`). A worker's running set holds the
creator's identifiers, not those of the fed tasks the creator adds, so
Steward can move a fed task's log while the run is still writing it, and
the recorder's next flush writes the original path again. Before handles
are used in Steward selection workers, Steward must not archive a log
while the worker that wrote it is running (for example, by treating logs
in the worker's log directory as in flight until it exits). This is a
Steward change; the Inspect design is unchanged.

No eval log schema, viewer type, control-channel or config file changes. A
fed task's log records the reserved dataset name `samples_from_handle`,
which the viewer shows as its dataset name; a user dataset of that name is
refused at construction. A fed task appears in `inspect ctl task list` as
any task does.

## Security

- **Sent samples** may carry model output (the search proposes them). They
  enter the receiving task through its existing `SampleEnqueuer` with ids
  the channel assigns, so model output never chooses a sample id or log
  member name; their content is sample input, treated as any dataset sample
  is.
- A handle is an in-process object; nothing new is exposed on the control
  channel.
- **The `max_tasks` exemption** is reached only through
  `samples_from_handle()`, which the eval author writes; the number of fed
  tasks a creator adds is the author's code's choice, and their samples stay
  under `max_samples`, `max_sandboxes` and the connection limits.
- **Oversight controls**: a run-level `approval`, `review` or `sentinel`
  policy applies to a fed task even when the task sets its own, so a
  rollout task cannot opt out of the operator's policy.

## Testing

Unit and integration tests on asyncio and trio (`--runtrio` for every async
test touched), with mockllm models; every test that waits is bounded with
`fail_after`.

- `tests/test_enqueue_task.py`:
  - the overview's example as a test at `max_tasks=1`, under `eval()`,
    `eval_set()` and selection mode in-process, and in a two-model run (each
    creator gets one handle, for its own model); with a rollout solver that
    raises for one sample, the run returns that `EvalSample` with its
    `error` set and the search continues; with the searcher raising after a
    send, the `except BaseException:` cancels the rollout task and the
    searcher's error propagates, and the same when the searcher's sample
    hits its `time_limit`, and separately its `working_limit`, while a sent
    sample runs (the rollout task ends with the abort log and the creator's
    sample with its limit); a search that returns normally calls no
    `cancel()`, and its rollout log has status `success` with every sent
    sample;
  - a faceted selection worker, with pruning enabled, whose selected creator
    constructs the unselected `rollout_task()` in its solver, adds it and
    gets a sent sample's `EvalSample` back: the factory body runs, the task
    is fed through its handle, and the worker's own task list is still
    pruned at resolution (the existing definition-time pruning tests
    pass);
  - `result()` on the handle of an ordinary added task raises
    `RuntimeError` with the message above and leaves the task queued or
    running, while `cancel()` and `close()` on that handle work; `cancel()`
    of a fed task queued, in its attempt before `register_eval` and
    running; `close()` and `async with` leaving running rollouts to finish;
  - the terminal-outcome table row by row: a target whose sent sample's
    setup fails, whose log init fails, closed before any sample was sent,
    cancelled while queued with no sample sent, and cancelled while queued
    holding a sent request (sent under a process pause, which keeps the
    record from starting while the creator's sample runs), each of the last
    three ending at once with no attempt and no log: `result()` returns
    `None`, the pending `enqueue_sample()` raises `TaskEndedError` with
    `log=None`, a `TaskSource` hears no report, the record never has
    `abort_requested`, `eval()` returns no log for it and the display's task
    total drops by one, as for an added task ended unstarted; and still
    queued at a latched cancellation (with the waiter in a sibling attempt's
    shielded cleanup);
  - in `next_tasks()`, a fed task's handle kept from its finished creator:
    `result()` returns the task's log at once and `enqueue_sample()` raises
    `TaskEndedError` (not its base `RuntimeError`) carrying that log;
  - the send error order, each asserting the exact type: after `close()`
    while a sent sample still runs, `RuntimeError` that is neither
    subclass; after the creator's attempt ends while a sent sample still
    runs, the same; after a drain while a sample is still running, the
    same, and after that sample settles and the task ends,
    `TaskEndedError`; between `cancel()` of a running fed task and its end,
    `RuntimeError` that is neither subclass, from an `enqueue_sample()`
    called right after `cancel()` with no await between (so the abort
    cannot have ended the task, which the test asserts by the record not
    being `ended`), both for a registered attempt whose sent sample is
    running (the solver sets an `anyio.Event` the test awaits first) and
    for one picked but not yet registered, and once the task has ended,
    `TaskEndedError`; for a fed task that failed on its own, with its
    `task_complete` held on an `anyio.Event` (its `EvalState` terminal, the
    record still in `attempt`), `handle.cancel()` followed by a send raises
    plain `RuntimeError` and buffers nothing, and after the test releases
    the callback and the record ends, a send raises `TaskEndedError`; after `cancel()` once the task has ended,
    `TaskEndedError`;
  - a fed task built as
    `task_with(registered_task(), dataset=samples_from_handle())` from a
    factory the eval set requests, under `eval()`, `eval_set()` and a
    selection worker, is added and runs beside the requested task of the
    same name, with a different identifier;
  - in a `TaskSource` run, a `task_complete` called after its task's
    `EvalState` is terminal that calls `enqueue_task()` with a
    `samples_from_handle()` task gets the `RuntimeError` and adds nothing,
    and an ordinary `enqueue_task()` from the same callback adds its task,
    which runs; the same refusal from `sample_complete`;
  - refusals: a `samples_from_handle()` task added from `next_tasks()`, returned from a `TaskSource` callback, added after
    its creator's attempt ended (by a coroutine the creator left running,
    while another task keeps the run open), with `epochs=2`, passed to
    `eval()` and `eval_set()`, as a `PreviousTask`, and as a `ResolvedTask`
    with no prior sample source, each raising and adding nothing;
    a fed task built in a solver as
    `task_with(registered_task(), dataset=samples_from_handle())`, whose
    factory's own dataset is an empty ordinary `SampleSource`, is added and
    runs, and `eval_retry()` of its log raises the `PrerequisiteError` above
    before any task is resolved (the factory is not called) and writes no
    log; off-loop calls raise, including one from `anyio.to_thread.run_sync`
    (which buffers the task today), and through `anyio.from_thread` succeed;
  - discovery: with `search` and `rollout_task` in one file, a whole-file
    load (`eval("search.py")`, `eval_set("search.py")`) raises the
    `PrerequisiteError` above naming `rollout_task` before any task runs,
    and `eval("search.py@search")` and `eval_set("search.py@search", ...)`
    run the searcher and its rollouts;
  - creation from attempt code outside a sample: an `on_task_start` hook
    adds a fed task and a sample of the same attempt sends to it through the
    handle the hook stored; the channel closes when the attempt ends; a fed
    task added in a `.json`-logged run runs as in an `.eval` one;
  - no slot: at `max_tasks=1` with an ordinary task U queued ahead, a fed
    task C starts on its first sample while its creator runs, and U still
    waits for the slot; two fed tasks of one creator run at once; a fed
    task with requests is not started after a latched cancellation; a fed
    task's first sample sent while another task's `task_init` is held
    starts the task at once;
  - headroom: with `max_sandboxes=1`, a creator sample holding the only
    sandbox sends a sample to a fed task using the same provider; the send
    waits, and the run completes after `inspect ctl config --max-sandboxes
    2` raises the limit, as the docs say.
- `tests/test_eval_set.py`: with a rollout task the set does not request,
  a resumed `eval_set()`, and a second `retry_immediate=False` round, pass
  the log-directory check without `log_dir_allow_dirty=True`, take only the
  requested task's log, and leave the fed log out of the eval-set info;
  with an ordinary task added by the creator instead, the resume still
  fails the check without the flag and passes with it, as today. The
  two-run case: run A requests only the creator, which adds
  `task_with(rollout(), dataset=samples_from_handle())` (allowed, since A
  does not request `rollout`); run B, an `eval_set()` requesting the
  ordinary `rollout` factory with the same arguments and model in the same
  directory with `log_dir_allow_dirty=True`, runs `rollout` rather than
  taking A's fed log, and a selection worker given A's fed log as `resume`
  refuses it as another task's log.
- `tests/test_eval_set.py` (identifiers): a fed task whose own
  `message_limit` and `time_limit` differ from the run's has the same
  `task_identifier()` from its `ResolvedTask` as from its log, in the form
  `…#samples_from_handle/<model>/<task_id>`; an ordinary task with the same
  name, arguments and model as a fed task has a different identifier from
  the fed log; two fed logs that share a `task_id` and differ in
  `eval_id`, as attempts of one record would, give one identifier; an
  ordinary task's identifier is the same as before the change for a stored
  log.
- `tests/test_sample_source.py` (tasks fed through a handle):
  - a fed task's log records `eval.dataset.name == "samples_from_handle"`;
    a `Task` whose dataset is a `MemoryDataset` named `samples_from_handle`,
    and `task_with` given one, raise `ValueError`;
  - each sent sample runs under the id `send-<token>-<n>` in send order,
    with the token the first 8 characters of the task's id, and its one run
    comes back; the caller's object keeps `id is None`; a sample with an
    `id` is refused; two rollout tasks added by one creator, and the rollout
    tasks a creator adds in its first attempt and in its retry, share no
    sample id;
  - a sample sent before the task has started is delivered when it starts;
    one sent while `next_samples()` blocks starts at once; samples sent from
    several solver tasks at once (`tg_collect`) all return; two requests
    whose samples are equal in value each get their own id and run;
  - in a run with `--sample-id 3` (and separately `--limit 2`, and
    `--epochs 3`), the creator runs only its selected samples, every one of
    four requests it sends to its rollout task runs once and returns, the
    rollout log's eval config records no limit or sample id and one epoch,
    and an ordinary `SampleSource` task in the same run is still filtered
    as today; under `eval()` and in a selection-mode worker;
  - under a run with `epochs=Epochs(3, "at_least_2")`, and separately with
    `pass_at_2` and `pass_k_2`, sending to a fed task succeeds, its log's
    eval config records one epoch and no reducer from the run, and a seed
    task in the same run keeps the run's three epochs and reducer;
  - settings: under a run with `time_limit=10`, `message_limit=5`,
    `turn_limit=5` and `fail_on_error=True`, a fed task that sets
    `time_limit=60`, `turn_limit=100` and `fail_on_error=False` keeps them
    and takes `message_limit=5`, a fed task that sets none takes all four,
    and an ordinary task with its own dataset that a solver in the same run
    adds with `turn_limit=100` takes the run's values, `turn_limit=5`
    included, as today; under a run-level `max_samples=2` a fed task that
    sets `max_samples=3` runs with 3 and one that sets none runs with 2,
    while with no run-level value one that sets none takes its model's pool
    default; under a run with `epochs=3` an ordinary added
    task that sets `epochs=1` runs three epochs, as today; a run-level
    approval policy applies to a fed task that sets its own; each log's
    eval config records the values that applied;
  - drain, `score` and `error`: an idle open channel ends the task and a
    later send raises `TaskEndedError`; with a sample running, a send
    raises `RuntimeError` (neither subclass) until the task ends and
    `TaskEndedError` after, and the running sample settles under the
    directive's rule;
  - a fed task whose request A completes and whose request B then needs a
    sandbox setup that fails (stub provider): the task ends with its error
    log and is not retried, A's call has already returned its run, and B's
    call raises `TaskEndedError` carrying that log;
  - a fed task failing for another reason after a sample ran is not retried,
    and its unresolved requests raise `TaskEndedError` with its error log; a
    retry the task requests itself is not honoured;
  - under `eval_set()` (immediate retries) and in a selection-mode worker, a
    creator whose rollout task fails, which handles the `TaskEndedError`, adds
    a fresh rollout task and then succeeds: the failed rollout's error log is
    among the returned logs and in the log directory, and the eval set's
    (and worker's) result is success; a creator that cancels its rollout
    task, and one whose rollout task is cancelled before it starts, also
    leave the result success; a creator that fails makes it failure;
  - the creator's attempt ending closes its channels: a started rollout task
    ends once its samples have run, and one never sent a sample ends with no
    log;
  - retention: after many requests, the channel holds no request, sample or
    result once each call has returned;
  - the free `enqueue_sample()` called from a rollout's solver raises
    `RuntimeError` and adds nothing, both while the handle is open and after
    `close()` while an earlier rollout is still running (the task then ends
    with only the sent samples run); the same call in an ordinary
    `SampleSource` task in the same run adds its sample as today;
  - with the default `fail_on_error`, the first errored rollout's
    `enqueue_sample()` returns its `EvalSample` with `error` set, and a
    request still unresolved when the task then ends raises
    `TaskEndedError`;
  - request ownership, each bounded: with the feeder held in another sent
    sample's sandbox setup (stub provider), a request sent meanwhile sits in
    the buffer unadmitted; cancelling the task, and failing that setup, each
    end the task with the request's call raising `TaskEndedError`, and the
    channel holds nothing afterwards.

## Implementation plan

One PR, after step 3a of
[task-dispatch.md](task-dispatch.md#implementation-plan) (the queue, the
dispatcher and logs that start with their attempt); it does not need step
3b, the control channel's queued tasks. It requires the task-level
`max_samples` setting (a `max_samples` parameter on `Task` and
`task_with()`), which the fed-task rule and its tests read. Its selection-mode
support relies on runtime pruning leaving tasks constructed by attempt code
unpruned
([task-dispatch.md](task-dispatch.md#interactions-with-related-changes));
the selection-mode tests below run with pruning enabled. Running it under Steward also needs Steward's protection of
a running worker's fed logs from archival ("Compatibility and migration").

- `_eval/task/enqueue.py` (`TaskHandle`, the errors, `TaskAttempt` and
  `_attempt`, which replaces `_creator`, `result()` refusing a handle whose task is
  not fed through it, `RunQueue.cancel` ending a queued fed record at once
  with no log and closing a fed record's channel itself in `attempt`,
  `enqueue_task()` returning handles, passing its creator
  and refusing a fed task outside an attempt or with `epochs` above 1),
  `_eval/task/sample_source.py` (`HandleChannel`, `samples_from_handle()`,
  the free `enqueue_sample()` refusal), `_eval/task/run.py` (attach and
  detach the channel where the `SampleEnqueuer` is registered and cleared,
  and mark that enqueuer as the channel's), `_eval/run.py`
  (`configure_task()` resolving a fed task's settings task-first,
  `turn_limit` and `max_samples` included, and clearing its `epochs`, the
  run's epoch reducer, `limit` and `sample_id`; `_attempt` set in `run_one`; the
  uncounted start step; channels closed with the creator's attempt; no
  retry, and `can_retry=False` on the `TaskCancel` that `start_attempt`
  creates, for fed tasks; `channel.close()` from the
  attempt's `TaskCancel.apply` that `start_attempt` creates, for every
  action, `abort` included), `_eval/task/task.py` (`resolve_dataset_or_source`
  naming a `HandleChannel`'s dataset and refusing the reserved name for any
  other; the `max_samples` parameter docs of `Task` and `task_with`, which
  say a run's value overrides the task's, adding that it does not for a
  task fed through its handle), `_eval/eval.py` (`_resolve_enqueued_tasks` reading the creator's
  model from `_attempt`; the `eval_resolve_tasks` refusal;
  `eval_retry_async` refusing a log by its dataset name; `max_tasks`,
  `max_samples` and `max_sandboxes` docstrings), `_eval/evalset.py`
  (`all_evals_succeeded` and `validate_eval_set_prerequisites` skipping
  logs with the reserved dataset name; `task_identifier` building a fed
  task's identifier from its task id),
  `__init__.py` (exports), `docs/task-source.qmd` (handles; stopping
  rollouts with `cancel()` in an `except BaseException:` that re-raises,
  which runs on errors, limits and every cancellation, a time limit and a
  working limit included, and why a `finally:` would abort the rollout task
  on a normal exit; `fail_on_error=False` for rollout tasks; a fed task's
  settings, resolved before the run's; and running the creator
  by name, `inspect eval search.py@search` and
  `eval_set("search.py@search", ...)`, when the rollout task shares its
  file), `docs/parallelism.qmd` (a fed task's own `max_samples` wins over
  the run's; the headroom a waiting run needs), `docs/reference`, and `_attempt` set to `None`
  around each `TaskSource` callback call (`_eval/task/run.py`,
  `_eval/run.py`), where `_creator` is cleared today. Tests: those above.

## Open questions

None. Decided: `enqueue_task()` returns `list[TaskHandle]` (Ransom,
2026-11-03) and stays synchronous (2026-11-16, reversing the 2026-11-09
decision to make it async; its reasons restated 2026-11-18: adding a task
awaits nothing, and an async version would silently break every existing
call that does not await it, while returning a handle is no reason either
way), and the receiving task declares that it is fed
through its handle (2026-11-09); `async with` closes and never
cancels (2026-11-09); `result()` closes the handle before it waits
(2026-11-10); a fed task is never retried automatically (2026-11-10);
(2026-11-11) a fed task takes no `max_tasks` slot, with no slot lent to any
awaited task (replacing the 2026-11-03 decision to lend, made before a task
could declare that it is fed through a handle), is resolved once under its
creator's model (as is any task added inside an attempt), and its sent samples get `send-<token>-<n>` ids with a per-task
token; and (2026-11-12) `samples_from_handle()` is the name, a fed task may
be added from any code inside a running attempt, runs one epoch per sent
sample, resolves its settings before the run's (except the oversight
controls), does not decide
`eval_set()`'s result, runs
in a `.json`-logged run as in any other (dropping the 2026-11-03 `.json`
refusal, whose premise was the per-delivery marker dropped on 2026-11-04),
and is the only task `result()` waits on (narrowing "wait for the task to
end" on any handle); and (2026-11-16) a fed task's log is marked by the
reserved dataset name `samples_from_handle`, which `eval_retry()` and the
eval set's result read (the 2026-11-04 decision's refusal and counting
from the log, without the schema field dropped then), and every cancel
through the attempt's `TaskCancel` (`abort`, `drain`, `score` or `error`)
closes the channel in its `apply` (`abort` added 2026-11-17, so `cancel()`
of a running fed task closes it at once, and `RunQueue.cancel` closes it
too, whether or not the directive applies), with no separate stopped
state (narrowing the 2026-11-12 send error order to ended, then closed);
and
(2026-11-17) a fed task's
`task_identifier()` is built from its task id
(`…#samples_from_handle/{model}/{task_id}`, with no settings hashed;
2026-11-17), so no ordinary task can produce
it, with no change to inspect_flow or inspect_steward (replacing the
2026-11-16 refusal of a fed log under a requested identifier and, with it,
the 2026-11-16 refusal of a fed task named like a requested or seed task),
and fed-task creation is refused in every `TaskSource` callback, by
clearing `_attempt` for the call; and (2026-11-17) protecting a running
worker's fed logs from Steward's archival is a Steward prerequisite for
selection workers, not an Inspect change; and (2026-11-18) the eval set's
log-directory check skips fed logs, so
resuming needs no `log_dir_allow_dirty=True` for them (replacing the
earlier rule that it does, as for any added task's log); a creator
stops its rollouts with `cancel()` in an `except BaseException:` that
re-raises, not in a `finally:`, which aborts the rollout task on a normal
exit (replacing the `finally:` advice given with the 2026-11-09 decision);
a fed task still starts on its
first sample, at the cost of the empty-channel close rule (the 2026-11-17
decision kept); and an added task's model controller is still created lazily,
with `--max-connections` retunes remembered and applied when a controller
is created as a follow-up, rather than created when the task is added; and
(2026-11-19) an ordinary task added from inside a running task keeps
today's rules, where the run's values win (limits, error tolerance,
`max_samples`, `epochs` and the epoch reducer), and only a task fed through
a handle takes its own limits, error tolerance and `max_samples` first,
with `epochs`, `limit` and `sample_id` cleared. This narrows the
2026-11-18 decision that every task added from inside a running task
follows one task-first rule, and replaces the 2026-11-19 answer that such
an ordinary task keeps its own `epochs` and reducer as a pair: applying the
task-first rule to ordinary added tasks changed an existing feature and
brought compatibility work (`task_identifier()` pairing for a
`ResolvedTask` added that way, `eval_retry()` replaying a recorded epoch
pair and the run's fallback for tasks added during a retry, migration text
for existing evals), while fed tasks are new and carry none of it. It can
be revisited if a real need appears. Also (2026-11-19): a fed task's
`max_samples` falls back to the run's value like its other settings
(replacing the 2026-11-12 rule that the run's value does not apply, made
while a `Task` could not set its own); a fed task cancelled while queued
ends at once with no log, like a handle never used, with no abort attempt
(replacing the 2026-11-17 queued-cancel rule for fed records only, and with
it the empty-channel close rule's `abort_requested` exception); and handle
waits get no `max_sandboxes` warning, the docs stating the headroom
instead.

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()`.
- Recording the creator in the eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Showing open handle waits in `inspect ctl task list`: a per-task count of
  waits in the control state, a `GET /tasks` field and a CLI column.
- Counting a fed task's token or cost usage against its creator's limits.
- Keeping an ordinary added task's failure in the result of an `eval_set()`
  whose later legacy round (`retry_immediate=False`) does not rerun it. It
  applies to every added task not fed through a handle, and belongs to the
  change that handles added tasks under `eval_set()`.
- Making the logs of ordinary added tasks (not fed through a handle) pass
  the eval set's log-directory check without `log_dir_allow_dirty=True`.
  Fed logs pass it by their reserved dataset name; an ordinary added task's
  log needs a mark of its own first, such as a record of the task that
  added it.
- A sent sample's failed sandbox setup failing only that sample (returned
  to its sender with its `error` set) rather than ending the fed task and
  cancelling its running samples. It belongs in the shared `SampleSource`
  feeder, for every task whose source adds samples, not in a path for fed
  tasks only.
- Detecting waits that cannot finish because sandbox or `max_samples`
  permits are held by their own waiters; see the wait-for graph under
  "Alternatives considered".
- Waiting in-run on an ordinary added task (one with its own dataset)
  through `result()`, a possible later addition. It needs a rule for the
  waiting task's `max_tasks` slot (a warning naming `inspect ctl config
  --max-tasks`, or a lent slot) and for waits inside
  `TaskSource.next_tasks()`.
