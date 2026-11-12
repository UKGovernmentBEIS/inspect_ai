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

@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [handle] = await enqueue_task(rollout_task())
        async with handle as rollouts:                    # closes on exit
            try:
                for _ in range(n_steps):
                    sample = await propose_next(state)
                    run = await rollouts.enqueue_sample(sample)   # its EvalSample
                    update(state, run)
            except Exception:
                rollouts.cancel()   # the search failed: stop the rollouts it sent
                raise
        return state

    return solve
```

`propose_next` is the searcher's own async function and may call a model.
The rollout task sets `fail_on_error=False`. With the default, the first
errored rollout is returned to its sender with its `error` set and then ends
the task; requests still unresolved receive `TaskEndedError`, and a task fed
through a handle is not retried. `fail_on_error=False` lets the task keep
accepting rollouts after a sample error. Closing never stops rollouts already sent; a creator
stops them with `cancel()`, in an `except Exception:` as above, or in a
`finally:` to stop them on every exit, including a time limit, which reaches
the block as a cancellation.

Handles build on the run queue of [task-dispatch.md](task-dispatch.md): an
added task is a `TaskRecord` in the run's `RunQueue`.

## Behaviour changes

All of these are new API; no existing eval waits on a handle or uses
`samples_from_handle()`.

- `enqueue_task()` is async and returns `list[TaskHandle]`
  ([task-dispatch.md](task-dispatch.md#behaviour-changes) has the migration).
- A task fed through a handle does not count toward `max_tasks`. A
  supervisor that sets `max_tasks` as a ceiling, such as a selection-mode
  worker's, sees one extra running task for each fed task that has been sent
  a sample and has not ended.
- A task fed through a handle runs once, under its creator's model, with
  one epoch, whatever models and epochs the run has.
- For a task fed through a handle, a sample limit or error-tolerance setting
  is its own value if it sets one, else the run's, else the default; for
  every other task the run's value replaces the task's, as today.
- A task fed through a handle is never retried automatically, and
  `eval_retry()` refuses its log. Its log is returned and listed with the
  run's other logs but does not decide `eval_set()`'s result or a
  selection-mode worker's: its creator's log does.
- The run's `--limit`, `--sample-id` and `--epochs` do not apply to a task
  fed through a handle.
- `TaskHandle.result()` waits only on a task fed through its handle; on the
  handle of any other added task it raises `RuntimeError`, and that task's
  log is read after the run.
- A run whose `max_sandboxes` leaves no room for the work a handle wait
  depends on can hang; the docs explain the headroom needed, and a warning
  names the `inspect ctl config --max-sandboxes` command that raises it
  while the run goes on.

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
- `_run_task` (`src/inspect_ai/_eval/run.py`) gives each attempt a
  `cancel_task` callback, through which the control channel stamps the
  attempt's `TaskCancel` for `abort`, `retry`, `drain`, `score` and `error`.
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
- `_resolve_enqueued_tasks` (`src/inspect_ai/_eval/eval.py`) resolves an
  added `Task` once per run model.
- `eval_retry()` recovers a crashed log before it resolves the log's task
  (`eval_retry_async`).
- `eval_set()` judges the result from every log `eval()` returns
  (`all_evals_succeeded`, also its retry predicate), added tasks' logs
  included; later rounds match logs only to requested tasks.
- A second `eval()` in the same process while one runs is refused ("Multiple
  concurrent calls to eval_async are not allowed"). A child `inspect eval`
  process starts its own control server by default and publishes a discovery
  entry keyed by its process id, so `inspect ctl` lists and cancels its tasks
  as a separate endpoint.

## Design

### The handle API

```python
async def enqueue_task(tasks: Tasks, *, run_id: str | None = None) -> list[TaskHandle]

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
resolution order: an ordinary `Task` gives one per run model, a task fed
through a handle gives one ("Tasks fed through a handle").

The *creator* of a task fed through a handle is the attempt that added it;
its end closes the task's channel. Docs and error messages say "fed through
its handle", not "creator".

- `close()` and `cancel()` are synchronous and idempotent; `close()` on a
  handle whose task is not fed through it does nothing. `cancel()` is
  `RunQueue.cancel` ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)).
- `async with` closes the handle on exit and never cancels the task
  (decision: Ransom, 2026-11-09): a creator that hits a time limit lets the
  rollouts it already sent finish. To stop them, the creator calls the
  synchronous `cancel()`: in an `except Exception:` to stop them when its
  own code fails, then re-raise, or in a `finally:` to stop them on every
  exit, including a time limit, which reaches the block as a cancellation.
  The handle docs and the overview example show this.
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

**Terminal outcomes.** Every record ends (task-dispatch.md, invariant 2),
including when dispatch ends, so no wait outlives its target:

| how the target ended | `result()` | an unresolved `enqueue_sample()` |
| --- | --- | --- |
| an attempt returned a log (success, error, setup failure, log-init failure, abort, a run-level cancellation of a running task), or it was cancelled before it started (its in-memory error log) | that log | `TaskEndedError(log=<that log>)` |
| no log (a fed task closed before any sample was sent, or dispatch ended first) | `None` | `TaskEndedError(log=None)` |

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
  the after-close error below.
- **`samples_from_handle()` tasks** are added only by `enqueue_task()` from
  code running inside an attempt that has not ended (`_attempt` set and
  `ended` false), which becomes the creator: a solver, scorer or tool, a
  task-level hook such as `on_task_start`, or a coroutine left over from a
  finished sample. Such a task closes with the attempt like any other.
  `enqueue_task()` checks this before `RunQueue.add` commits anything.
  Elsewhere:
  - outside any attempt, including `TaskSource.next_tasks()`, which the
    dispatcher calls: `RuntimeError` from `enqueue_task()`;
  - returned from a `TaskSource` callback (`task_complete`,
    `sample_complete`, `sample_abandoned`), whose returns are added with no
    creator: `RuntimeError` from `RunQueue.add`; a direct `enqueue_task()`
    call inside a callback that runs within an attempt is attempt code and
    allowed;
  - with `epochs` above 1: `ValueError` from `enqueue_task()` ("a task fed
    through its handle runs each sample once; send a sample again to repeat
    it");
  - passed to `eval()`, `eval_set()`, a selection worker or `eval_retry()`:
    `PrerequisiteError` from `eval_resolve_tasks` ("task '<task>' takes its
    samples through its handle (samples_from_handle()), so it cannot be run
    or retried on its own; run or retry the task that adds it");
  - as a `PreviousTask` or a `ResolvedTask` (with or without a prior sample
    source): `ValueError` ("tasks fed through a handle must start fresh;
    pass the Task");
  - put on a task a `@task` function returned with
    `task_with(task, dataset=samples_from_handle())`: `ValueError` from
    `task_with` ("samples_from_handle() must be the dataset the @task
    function '<name>' returns: eval_retry() rebuilds the task by calling that
    function, so a dataset set afterwards would be lost; return
    samples_from_handle() from a @task function of its own"). The log
    records only the factory's name and arguments, so a retry of such a
    task would rebuild the factory's own dataset (an empty ordinary
    `SampleSource`, say), pass the retry refusal below, and run without the
    sent samples. `task_with` raises when `dataset` resolves to a
    `HandleChannel` and the task carries registry info
    (`is_registry_object(task)`, set by the `@task` wrapper); a `Task`
    built directly with `samples_from_handle()`, inside a `@task` function
    or not, is unaffected.
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
  through it, or after `close()` or `result()`: `RuntimeError`; with a sample that has an
  `id`: `ValueError` (the channel assigns ids); after a drain, `score` or
  `error` cancel of the task: `SampleAbandonedError`; after the task ended:
  `TaskEndedError`.
- Off the run's loop: `RuntimeError` (see "The handle API").

### What the handles add to the run queue

```python
@dataclass(eq=False)
class TaskAttempt:                     # one per run_one attempt
    record: TaskRecord
    ended: bool = False                # set in the step run_one gives its slot back
    channels: list[HandleChannel] = field(default_factory=list)   # channels of tasks it added

_attempt: ContextVar[TaskAttempt | None]   # set by run_one around _run_task
```

`TaskRecord` gains `channel: HandleChannel | None = None`. `RunQueue.add`
takes `creator: TaskAttempt | None`, which `enqueue_task()` passes from
`_attempt`. The dispatcher gains one step after the ordinary picks, skipped
once it has latched a cancellation:

```
    for each queued record with a channel that holds a request, in queue order,
            if it is startable (task-dispatch.md "Start rule"):
        start run_one(record, counted=False)
```

An attempt started this way does not count toward `in_flight`, and the
ordinary picks skip every record that has a channel. `RunQueue.end` closes
the record's channel, settling every request still unsettled with
`TaskEndedError(log)`. `RunQueue.add` also records the task id of every
record with a channel in a process-level set, `fed_task_ids()`, cleared by
`reset_run_registries()` ("Logs and eval sets").

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
    stopped: bool                      # a drain, score or error cancel
    pushed: Wake

@dataclass(eq=False)
class PortRequest:
    sample: Sample                     # the channel's copy of the caller's sample, with its id
    future: Future[EvalSample]
```

- **One record, under the creator's model, one epoch.**
  `_resolve_enqueued_tasks` resolves a task whose dataset is
  `samples_from_handle()` once, for the model of the creator's attempt in
  place of the run's model list (a `Task` that sets its own `model` keeps
  it, as in any resolution). So `enqueue_task()` returns one handle for it,
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
  handle that is never used costs nothing. Its model controller is created
  when its attempt starts, as for any added task
  ([task-dispatch.md](task-dispatch.md#adding-tasks)); under its creator's
  model it usually exists already. It has no seed, so
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
  feeder drains the buffer, or `None` once the channel is closed or stopped,
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
  that applied:
  - The sample limits (`message_limit`, `token_limit` with its
    `token_limit_type`, `turn_limit`, `time_limit`, `working_limit`,
    `cost_limit`) and error tolerance (`fail_on_error`, `continue_on_fail`,
    `score_on_error`) are the fed task's own value if it sets one, else the
    run's, else the default. For every other task the run's value still
    replaces the task's.
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
  - `max_samples`: the run's value does not apply. A `Task` cannot set its
    own, so a fallback to the run's would always win; the fed task takes
    the default from its model's connection pool, and `inspect ctl config
    --max-samples` still retunes it while it runs.
  - `approval`, `review` and `sentinel`: the run's value still wins, as
    today; they are the operator's oversight controls for the whole run.
  - Tags stay merged; generate config and the run-wide limits (`max_tasks`,
    `max_sandboxes`, `max_connections`) are unchanged.

  The creator's own settings are not inherited: the searcher passes what it
  wants shared when it builds the rollout task. Other `SampleSource` tasks
  keep today's resolution and filtering.
- **Graceful cancels stop it.** `_run_task`'s `cancel_task` callback calls
  `channel.stop()` for `drain`, `score` and `error`: `next_samples()` returns
  `None` and later sends raise `SampleAbandonedError`. Samples already
  buffered or running follow the directive's existing rules and settle
  through `sample_complete` or `sample_abandoned`.
- **Closing.** The channel closes on `close()`, `result()`, `async with`
  exit, `cancel()`, the end of the creator's attempt (`run_one` sets
  `ended` and closes the attempt's channels in the step it gives its slot
  back) and `RunQueue.end`. Closing a channel whose record is still `queued`
  with no request ends the record with no log. A creator that forgets to
  close cannot keep a rollout task open past its own attempt.
- **Retries.** A task fed through a handle is never retried automatically
  (decision: Ransom, 2026-11-10). When its attempt fails for any reason, a
  sent sample's sandbox setup included, the task ends with its error log,
  its unresolved `enqueue_sample()` calls raise `TaskEndedError` with that
  log, and the calls already returned keep their runs. The creator holds
  the search state and every result returned, and decides whether to add a
  fresh task. `run_one` passes `can_retry=False` to `_run_task` for such a
  task and queues no retry for it, so no retry is pre-marked or reported
  (`will_retry` is false), and a retry the task requests itself through its
  `TaskCancel` is not honoured, as for a task with no retries left.
- **Logs and eval sets.** A fed task's log is an ordinary log with no
  marker. `eval()` returns it with the run's other logs, `eval_set()`
  returns it among its logs, and it is written to the log directory, where
  `inspect log list`, `list_eval_logs()` and the viewer list it. It does not
  decide the eval set's result: `all_evals_succeeded`, which is also
  `eval_set()`'s retry predicate and selection mode's result, skips the
  logs whose task id is in `fed_task_ids()`. So a creator that cancels its
  rollout task, a rollout task cancelled before it started, or one that
  failed and was replaced, does not fail the set; the creator's own log
  does, if the creator fails. `eval_retry()` of a fed task's log is refused
  when the log's task is resolved, because the reloaded task's dataset is
  `samples_from_handle()` ("What is refused"); that holds because a
  registered task can get that dataset only from its own `@task` function,
  never from `task_with` afterwards; a crashed log is recovered first, as
  for any log, which runs nothing.

### Waits and limits

A fed task takes no `max_tasks` slot, and `result()` waits only on fed
tasks, so no handle wait needs a slot. Two limits still apply to work that a
handle wait depends on, and neither is lent:

- **`max_sandboxes`.** A waiting sample keeps its `sandboxes/<provider>`
  permit. `max_sandboxes` is often a hard quota (a cloud account's sandbox
  limit, a cluster's capacity), a sandbox is a live resource rather than
  bookkeeping, and the limiter is a semaphore that cannot hand a permit to
  one specific sample, so permits are not lent. `max_sandboxes` for each
  provider both tasks use must exceed the number of samples that hold one
  while waiting. Inspect warns once per provider per run when a handle wait
  starts while every permit of a provider the target's task-level config
  names is in use (`sandbox_limiters()`, `in_use >= limit`): "task 'search'
  is waiting on task 'rollout', which uses 'docker' sandboxes, while all 1 of
  them (max_sandboxes) are in use; if their holders are waiting on
  'rollout', the run will not progress: raise it while the run goes on with
  `inspect ctl config --max-sandboxes N`".
- **`max_samples`** is per task, so a task's samples that wait on work its
  own other samples do need room for both.

The warning is advice: holders that finish release what they hold. The
`max_tasks`, `max_samples` and `max_sandboxes` docstrings,
`docs/parallelism.qmd` and the handle docs in `docs/task-source.qmd` state
the fed-task exception to `max_tasks` and the `max_sandboxes` and
`max_samples` headroom a waiting run needs.

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
- **Starting a fed task when it is added.** A handle never used would run an
  attempt and write an empty log; starting on the first sample needs no
  extra rule, because the dispatcher already rescans on `wake`.
- **One fed task per run model**, as for ordinary tasks. The creator would
  pick the handle for its own model and close the rest in every use.
- **Several epochs per sent sample**, with one result per epoch. It needs a
  future per epoch, a request that is partly abandoned, and an epoch on
  `SampleAbandonedError`. A creator that wants repeats sends the sample
  again and sees each result as it comes.
- **A fed task inheriting its creator's settings.** The creator's limits and
  error tolerance are chosen for the search, not for one rollout; the
  searcher passes what it wants shared when it builds the rollout task.
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
  result. It is a log schema change with a coordinated viewer update.
  `eval_retry()` is refused without it at task resolution, and the eval
  set's result skips fed tasks by the in-process `fed_task_ids()`. The
  identifier collision it guards needs a requested task with the same file,
  name and arguments as the fed task but another dataset, which is the
  exposure any edit of a task's dataset already has, since
  `task_identifier()` leaves the dataset out.
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
  limit would abort rollouts already running; a creator that wants that
  calls `cancel()` in a `finally:`.
- **Refusing waits that would never end** with a process-level wait-for graph
  over handle waits and sandbox and sample permits. It must be re-checked
  at every blocking event and limit change (a live retune can lower a limit
  below its use); documented headroom and the `max_sandboxes` warning cover
  the configurations the use case needs.

## Compatibility and migration

Public API: `enqueue_task()` is async and returns `list[TaskHandle]` (the
migration is in [task-dispatch.md](task-dispatch.md#compatibility-and-migration));
new `TaskHandle`, `TaskEndedError`, `SampleAbandonedError` and
`samples_from_handle`. Existing `SampleSource` tasks are unchanged: only a
`HandleChannel` gets `stop()`, and only a task fed through a handle ignores
the run's `--limit`, `--sample-id` and `--epochs` (with the run's epoch
reducer), resolves its settings before the run's, runs once under its
creator's model, is exempt from `max_tasks` and is left out of
`eval_set()`'s result.

No eval log schema, viewer type, control-channel or config file changes. A
fed task appears in `inspect ctl task list` as any task does.

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
    send, the `except` cancels the rollout task and the searcher's error
    propagates;
  - `result()` on the handle of an ordinary added task raises
    `RuntimeError` with the message above and leaves the task queued or
    running, while `cancel()` and `close()` on that handle work; `cancel()`
    of a fed task queued, in its attempt before `register_eval` and
    running; `close()` and `async with` leaving running rollouts to finish;
  - the terminal-outcome table row by row: a target whose sent sample's
    setup fails, whose log init fails, cancelled while queued (the
    cancelled-before-start error log), closed before any sample was sent (no
    attempt, no log; the display's task total drops by one, as for a queued
    cancel), and still queued at a latched cancellation (with the waiter in
    a sibling attempt's shielded cleanup);
  - in `next_tasks()`, a fed task's handle kept from its finished creator:
    `result()` returns the task's log at once and `enqueue_sample()` raises
    the after-close `RuntimeError`;
  - refusals: a `samples_from_handle()` task added from `next_tasks()`, returned from a `TaskSource` callback, added after
    its creator's attempt ended (by a coroutine the creator left running,
    while another task keeps the run open), with `epochs=2`, passed to
    `eval()` and `eval_set()`, as a `PreviousTask`, as a `ResolvedTask` with
    no prior sample source, and `eval_retry()` of its log (finished, and
    crashed: recovered, then refused), each raising and adding nothing;
    `task_with(dataset=samples_from_handle())` over a registered `@task`
    function whose own dataset is an empty ordinary `SampleSource` raises at
    the `task_with` call, so no such task runs and no log can be retried as
    an ordinary empty task, while the same `task_with` over an unregistered
    `Task` succeeds; off-loop calls raise, and through `anyio.from_thread`
    succeed;
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
    sandbox sends a sample to a fed task using the same provider; the
    warning naming `inspect ctl config --max-sandboxes` is logged once per
    provider when the send starts with every permit in use, and the run
    completes after that command raises the limit; a send with a free
    permit logs nothing.
- `tests/test_sample_source.py` (tasks fed through a handle):
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
    eval config records one epoch and no reducer from the run, and an
    ordinary task in the same run keeps the run's three epochs and reducer;
  - settings: under a run with `time_limit=10`, `message_limit=5`,
    `turn_limit=5` and `fail_on_error=True`, a fed task that sets
    `time_limit=60`, `turn_limit=100` and `fail_on_error=False` keeps them
    and takes `message_limit=5`, a fed task that sets none takes all four,
    and an ordinary task in the same run that sets `turn_limit=100` takes
    the run's values, `turn_limit=5` included; a run-level `max_samples=2` does not reach the
    fed task, whose limit comes from its model's pool; a run-level approval
    policy applies to a fed task that sets its own; each rollout log's eval
    config records the values that applied;
  - drain, `score` and `error`: an idle open channel ends the task, later
    sends raise `SampleAbandonedError`, a buffered or running sample settles
    under the directive's rule;
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

One PR, after step 3 of
[task-dispatch.md](task-dispatch.md#implementation-plan).

- `_eval/task/enqueue.py` (`TaskHandle`, the errors, `TaskAttempt` and
  `_attempt`, `fed_task_ids()`, `result()` refusing a handle whose task is
  not fed through it, the `max_sandboxes` warning naming its `inspect ctl
  config` command, `enqueue_task()` returning handles, passing its creator
  and refusing a fed task outside an attempt or with `epochs` above 1),
  `_eval/task/sample_source.py` (`HandleChannel`, `samples_from_handle()`,
  the free `enqueue_sample()` refusal), `_eval/task/run.py` (attach and
  detach the channel where the `SampleEnqueuer` is registered and cleared,
  and mark that enqueuer as the channel's), `_eval/run.py`
  (`configure_task()` resolving a fed task's settings, `turn_limit`
  included, and clearing its `epochs`, the run's epoch reducer, `limit` and
  `sample_id`; `_attempt` set in `run_one`; the
  uncounted start step; channels closed with the creator's attempt; no
  retry, and `can_retry=False`, for fed tasks; `channel.stop()` from the
  `cancel_task` callback), `_eval/task/task.py` (the `task_with` refusal),
  `_eval/eval.py` (`_resolve_enqueued_tasks` resolving a fed task for its
  creator's model; the `eval_resolve_tasks` refusal; `max_tasks`,
  `max_samples` and `max_sandboxes` docstrings), `_eval/evalset.py`
  (`all_evals_succeeded` skipping `fed_task_ids()`),
  `_control/eval_state.py` (`reset_run_registries()` clears the set),
  `__init__.py` (exports), `docs/task-source.qmd` (handles, stopping
  rollouts with `cancel()`, `fail_on_error=False` for rollout tasks),
  `docs/parallelism.qmd`, `docs/reference`. Tests: those above.

## Open questions

None. Decided: `enqueue_task()` returns `list[TaskHandle]` (Ransom,
2026-11-03), becomes async (2026-11-09), and the receiving task declares that
it is fed through its handle (2026-11-09); `async with` closes and never
cancels (2026-11-09); `result()` closes the handle before it waits
(2026-11-10); a fed task is never retried automatically (2026-11-10);
(2026-11-11) a fed task takes no `max_tasks` slot, with no slot lent to any
awaited task (replacing the 2026-11-03 decision to lend, made before a task
could declare that it is fed through a handle), is resolved once under its
creator's model (narrowing "one handle per task × model" to ordinary
tasks), and its sent samples get `send-<token>-<n>` ids with a per-task
token; and (2026-11-12) `samples_from_handle()` is the name, a fed task may
be added from any code inside a running attempt, runs one epoch per sent
sample, resolves its settings before the run's (except `max_samples` and
the oversight controls), does not decide `eval_set()`'s result, runs
in a `.json`-logged run as in any other (dropping the 2026-11-03 `.json`
refusal, whose premise was the per-delivery marker dropped on 2026-11-04),
and is the only task `result()` waits on (narrowing "wait for the task to
end" on any handle).

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()`.
- Recording the creator, or that a task was fed through a handle, in the
  eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Showing open handle waits in `inspect ctl task list`: a per-task count of
  waits in the control state, a `GET /tasks` field and a CLI column.
- Counting a fed task's token or cost usage against its creator's limits.
- Keeping an ordinary added task's failure in the result of an `eval_set()`
  whose later legacy round (`retry_immediate=False`) does not rerun it. It
  applies to every added task not fed through a handle, and belongs to the
  change that handles added tasks under `eval_set()`.
- Making the logs of tasks added under `eval_set()` pass its log-directory
  check without `log_dir_allow_dirty=True`; it applies to every added task.
- Detecting waits that cannot finish because sandbox or `max_samples`
  permits are held by their own waiters; see the wait-for graph under
  "Alternatives considered".
- Waiting in-run on an ordinary added task (one with its own dataset)
  through `result()`, a possible later addition. It needs a rule for the
  waiting task's `max_tasks` slot (a warning naming `inspect ctl config
  --max-tasks`, or a lent slot) and for waits inside
  `TaskSource.next_tasks()`.
