# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns a `TaskHandle` for each task it added. A handle
waits for its task's result and cancels it. A task whose dataset is
`samples_from_creator()` takes its samples from the task that added it: the
creator sends each one with `TaskHandle.enqueue_sample()` and gets back the
sample's logged runs. Such a task runs under its creator's model, starts
when its first sample is sent, and does not take a `max_tasks` slot, so a
search that drives a rollout task works at any `max_tasks`. It stays open
until its handle is closed or its creator's attempt ends, and `async with`
closes the handle on exit:

```python
@task
def rollout_task() -> Task:
    return Task(dataset=samples_from_creator(), solver=rollout(), scorer=judge())

@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [handle] = await enqueue_task(rollout_task())
        async with handle as rollouts:                # closes on exit
            for _ in range(n_steps):
                sample = await propose_next(state)
                runs = await rollouts.enqueue_sample(sample)  # one EvalSample per epoch
                update(state, runs)
        return state

    return solve
```

`propose_next` is the searcher's own async function and may call a model.

Handles build on the run queue of [task-dispatch.md](task-dispatch.md): an
added task is a `TaskRecord` in the run's `RunQueue`.

## Behaviour changes

All of these are new API; no existing eval waits on a handle or uses
`samples_from_creator()`.

- `enqueue_task()` is async and returns `list[TaskHandle]`
  ([task-dispatch.md](task-dispatch.md#behaviour-changes) has the migration).
- A task fed by its creator does not count toward `max_tasks`. A supervisor
  that sets `max_tasks` as a ceiling, such as a selection-mode worker's, sees
  one extra running task for each fed task that has been sent a sample and
  has not ended.
- A task fed by its creator runs once, under its creator's model, whatever
  models the run has.
- A run whose `max_tasks`, `max_sandboxes` or `max_samples` leaves no room
  for the work that handle waits depend on can hang; the docs say so and a
  warning names the limit.
- A task fed by its creator is never retried automatically, and
  `eval_retry()` refuses its log. Its error log stays one of the run's logs,
  so the eval set's or selection worker's result is failure even if the
  creator recovers, as for any added task that fails.
- The run's `--limit` and `--sample-id` do not apply to a task fed by its
  creator.

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

- A handle that waits for its task's result, cancels it, and, for a task fed
  by its creator, sends it samples and returns each sample's runs, with one
  terminal outcome for every way the task can end.
- The search example works at any `max_tasks`, under `eval()`, `eval_set()`
  and selection mode, without exceeding `max_sandboxes` or `max_samples`.

Non-goals:

- Handles that reach a task in another process (another selection-mode
  worker).
- Handles for tasks a `TaskSource` returns.
- Making a wait on an ordinary added task (one with its own dataset) safe at
  every `max_tasks`: such a wait holds its slot, and the docs and a warning
  say so ("Waits and limits").
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
- A sample's sandboxes hold a permit of the process-wide
  `sandboxes/<provider>` limiter from before `sample_init` to after
  `sample_cleanup` (`sandboxenv_context`, `src/inspect_ai/_eval/task/sandbox.py`);
  `max_samples` is per task; model connection slots are held only during a
  `generate` call.
- `_resolve_enqueued_tasks` (`src/inspect_ai/_eval/eval.py`) resolves an
  added `Task` once per run model.
- `eval_retry()` recovers a crashed log before it resolves the log's task
  (`eval_retry_async`).
- `eval_set()` has no handling for the logs of added tasks: they are among
  the logs each `eval()` returns, and later rounds match logs only to
  requested tasks.
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
    async def enqueue_sample(self, sample: Sample) -> list[EvalSample]:
        """Run `sample` in the task and return its logged runs, one per epoch, in epoch order."""
    async def result(self) -> EvalLog | None:
        """Close the handle, then wait until the task ends; its final log, or None."""
    def close(self) -> None:
        """Send no more samples; the task ends once the samples sent have run."""
    def cancel(self) -> None:
        """Abort the task, like `inspect ctl task cancel`."""
    async def __aenter__(self) -> "TaskHandle": ...
    async def __aexit__(self, *exc: object) -> None:   # close(), never cancel()

class TaskEndedError(RuntimeError):
    log: EvalLog | None               # the task's final log, None if no attempt returned one

class SampleAbandonedError(RuntimeError):
    sample: Sample
    epoch: int
```

New exports from `inspect_ai`: `TaskHandle`, `TaskEndedError`,
`SampleAbandonedError`, `samples_from_creator`. One handle per record, in
resolution order: an ordinary `Task` gives one per run model, a task fed by
its creator gives one ("Tasks fed by their creator").

- `close()` and `cancel()` are synchronous and idempotent; `close()` on a
  handle whose task is not fed by its creator does nothing. `cancel()` is
  `RunQueue.cancel` ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)).
- `async with` closes the handle on exit and never cancels the task: a
  creator that hits a time limit lets the rollouts it already sent finish.
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
| an attempt returned a log (success, error, setup failure, log-init failure, abort, a run-level cancellation of a running task, a pending retry abandoned) | that log | `TaskEndedError(log=<that log>)` |
| no attempt returned a log (cancelled while queued, a fed task closed before any sample was sent, or dispatch ended first) | `None` | `TaskEndedError(log=None)` |

A request that already has its runs keeps them; one abandoned raises
`SampleAbandonedError`. A cancelled caller's wait raises the cancellation;
the sample it sent still runs and its result is dropped.

### What is refused

- **Waits inside `TaskSource.next_tasks()`.** The dispatcher starts nothing
  while that call blocks
  ([task-dispatch.md](task-dispatch.md#the-dispatcher)), so a wait there on
  a task that has not ended would never return. `result()` and
  `enqueue_sample()` raise `RuntimeError` there: "a task handle cannot be
  awaited inside TaskSource.next_tasks(): no task starts until it returns;
  return the task, and wait for it from a running task" (they read the
  `ContextVar` the dispatcher sets around the call). Waits are allowed
  everywhere else on the run's loop; `close()`, `cancel()` and the
  attributes work anywhere.
- **`samples_from_creator()` tasks** are added only by `enqueue_task()` from a
  running sample (`sample_active()` set) whose attempt has not ended
  (`_attempt` set and `ended` false); that attempt becomes the creator.
  `enqueue_task()` checks both before `RunQueue.add` commits anything, so a
  detached task that kept a finished sample's context adds nothing and opens
  no channel. Elsewhere:
  - anywhere else, including a `TaskSource`'s `next_tasks()` or callback
    returns: `RuntimeError` from `enqueue_task()` or `RunQueue.add`;
  - passed to `eval()`, `eval_set()`, a selection worker or `eval_retry()`:
    `PrerequisiteError` from `eval_resolve_tasks` ("task '<task>' takes its
    samples from the task that adds it (samples_from_creator()), so it
    cannot be run or retried on its own; run or retry the task that adds
    it");
  - as a `PreviousTask`, or a `ResolvedTask` carrying a prior sample source:
    `ValueError` ("tasks fed by their creator must start fresh; pass the
    Task");
  - in a run that logs in the deprecated `.json` format: `ValueError`
    (decision: Ransom, 2026-11-03).
- **`enqueue_sample()`** on a handle whose task is not fed by its creator, or
  after `close()` or `result()`: `RuntimeError`; with a sample that has an
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
    channels: list[CreatorChannel]     # channels of tasks its samples added

_attempt: ContextVar[TaskAttempt | None]   # set by run_one around _run_task
```

`TaskRecord` gains `channel: CreatorChannel | None`. `RunQueue.add` takes
`creator: TaskAttempt | None`, which `enqueue_task()` passes from `_attempt`.
The dispatcher gains one step after the ordinary picks, skipped once it has
latched a cancellation:

```
    for each queued record with a channel that holds a request, in queue order,
            if it is startable (task-dispatch.md "Start rule"):
        start run_one(record, counted=False)
```

An attempt started this way does not count toward `in_flight`, and the
ordinary picks skip every record that has a channel. `RunQueue.end` closes
the record's channel, settling every request still unsettled with
`TaskEndedError(log)`.

### Tasks fed by their creator

`samples_from_creator()` returns a `CreatorChannel`, a `SampleSource` with no
seed. `RunQueue.add` gives each record whose task has one a fresh
`CreatorChannel` on the record's configured copy of the task, and records it
in the creator's `TaskAttempt.channels`.

```python
class CreatorChannel(SampleSource):
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
    futures: dict[int, Future[EvalSample]]   # one per epoch
```

- **One record, under the creator's model.** `_resolve_enqueued_tasks`
  resolves a task whose dataset is `samples_from_creator()` once, for the
  model of the creator's attempt in place of the run's model list (a `Task`
  that sets its own `model` keeps it, as in any resolution). So
  `enqueue_task()` returns one handle for it, and a creator in a multi-model
  run feeds a rollout task under its own model.
- **It starts on its first sample and takes no slot.** The record waits in
  `queued`, listed and cancellable like any queued task, until its channel
  holds a request; the dispatcher then starts it at once, whatever
  `max_tasks` is, and its attempt is not counted against the limit. A fed
  task does nothing its creator did not send: its samples are bounded by
  `max_samples`, `max_sandboxes` and the model's connection limit like any
  task's, and its creator's own slot is counted. A record whose channel
  closes before any sample was sent ends with no log and no attempt, so a
  handle that is never used costs nothing. Preparing the record
  ([task-dispatch.md](task-dispatch.md#the-dispatcher)) ensures its model
  controller; it has no seed, so no sandbox is set up before it starts.
  Until [task-dispatch-setup.md](task-dispatch-setup.md) lands, a first
  sample sent while the dispatcher is setting up another task's sandboxes
  starts its task when that setup returns.
- **Sending.** `enqueue_sample(sample)` takes its own copy of the sample
  (`model_copy()`, so the caller's object is unchanged) with the id
  `send-<token>-<n>`: the channel's token and its `sent` counter,
  zero-padded to four digits as generated ids are. It creates a `PortRequest` with one future
  per configured epoch, records it in `requests` under that id, puts the
  copy in the running attempt's buffer (`enqueuer.enqueue`), which wakes the
  feeder, or leaves it for delivery if the attempt has not started, rings
  `pushed` and the queue's `wake`, and waits for every future.
- **Ids.** The channel's ids are explicit ids to `reserve_runs`, which
  admits them as given. Within the task they cannot collide: it has no
  seed, a caller-set id is refused, and the counter never repeats. The
  token makes them unique across tasks too. It is the first 8 characters of
  the record's task id, which resolution generates afresh for every
  `enqueue_task()` call, so a fresh rollout task a creator adds after a
  failure, and the one a retried creator adds again, each get their own
  token, as do the rollout tasks of two creators. So a sent id never names
  two samples: logs of the same rollout task can be grouped by sample id,
  and nothing that reuses a record by `(id, epoch)` can match one sent
  sample to another, whichever route reaches it. The token is the task's
  rather than the attempt's `eval.created` second (the token of today's
  generated ids) because a sample can be sent before the attempt starts.
  Ids sort in send order within a log, up to 9,999 samples.
- **Delivery.** `task_run`, where it registers the attempt's `SampleEnqueuer`,
  attaches it to the channel and puts every request's sample in it, in send
  order; where it clears the enqueuer, it detaches it. The feeder admits the
  buffer as it admits any enqueued sample, so a sample starts as soon as
  `max_samples` allows. A sent sample can need a sandbox setup; the feeder
  runs it through today's `startup_sandboxes` before scheduling the batch,
  as for any `SampleSource` addition, and its failure fails this task only.
- **`next_samples()`** waits on `pushed` and returns `[]` after a send, so the
  feeder drains the buffer, or `None` once the channel is closed or stopped,
  which ends the task when nothing is in flight or buffered (samples sent
  while that `None` is returned still run, as for any source).
- **Results.** `sample_complete` resolves the future of the request holding
  that id for the sample's epoch (an errored or operator-cancelled sample is
  returned with its `error`), and `sample_abandoned` fails it with
  `SampleAbandonedError`; both return `None`. A future already resolved
  keeps its first value. A request leaves `requests` once every epoch has
  settled, so the channel holds no sample or result after its call returns.
  A caller whose wait is cancelled leaves its request in place: the sample
  still runs, and the request is removed when it settles or the task ends,
  with its result dropped.
- **Run-wide selection does not apply.** `--limit` and `--sample-id` choose
  among the requested tasks' samples; a fed task's samples are chosen by its
  creator, whose own selection already limits what it sends, and a run-wide
  value would silently drop requests (a `--sample-id 3` filters every sent
  id, and a `--limit 2` ends the task after two). So `configure_task()`
  gives a task whose dataset is `samples_from_creator()` `limit=None` and
  `sample_id=None` whatever the run passes, before it builds the task's
  logger, so the log's eval config records them cleared; a `task:id`
  selector naming the fed task's name selects nothing there, and the "No
  sample_id selector names task" warning is not logged for it. `epochs` and
  every other eval-level override apply as to any task. Other `SampleSource`
  tasks keep today's filtering.
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
- **Retries.** A task fed by its creator is never retried automatically
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
  marker, and `eval_set()` treats it as it treats every added task's log
  today. Its error log is among the run's logs, so under immediate retries
  (the default) and in a selection worker the result is failure even when
  the creator recovers with a fresh task. `eval_retry()` of the log is
  refused when the log's task is resolved, because the reloaded task's
  dataset is `samples_from_creator()` ("What is refused"); a crashed log is
  recovered first, as for any log, which runs nothing.

### Waits and limits

A fed task takes no `max_tasks` slot, so the search example never waits on a
slot. Three limits still apply to work that a handle wait depends on, and
none is lent:

- **`max_tasks`, for an ordinary added task.** A task that awaits `result()`
  on a task with its own dataset keeps its slot while it waits, and the
  awaited task needs one. If every slot is held by a task waiting on a
  queued task, the run does not progress. Inspect warns once per run when a
  `result()` wait begins inside an attempt on a queued record with no
  channel while no slot is free: "task 'search' is waiting on task 'probe',
  which is queued behind max_tasks=1; if every running task is waiting on a
  queued task, the run will not progress: raise max_tasks, or take the
  result after this task's samples finish".
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
  'rollout', the run will not progress: raise max_sandboxes".
- **`max_samples`** is per task, so a task's samples that wait on work its
  own other samples do need room for both.

Both warnings are advice: holders that finish release what they hold. The
`max_tasks`, `max_samples` and `max_sandboxes` docstrings,
`docs/parallelism.qmd` and the handle docs in `docs/task-source.qmd` state
the fed-task exception and the headroom a waiting run needs.

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
- **No added task counts toward `max_tasks`.** Unbounded: a task that adds
  one fixed-dataset task per sample runs them all at once. A fed task runs
  only what its creator sends, so exempting those alone stays bounded by the
  sample limits.
- **Starting a fed task when it is added.** A handle never used would run an
  attempt and write an empty log; starting on the first sample needs no
  extra rule, because the dispatcher already rescans on `wake`.
- **One fed task per run model**, as for ordinary tasks. The creator would
  pick the handle for its own model and close the rest in every use.
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
  `eval_retry()`, `task_identifier()` and selection resume. It is a log
  schema change with a coordinated viewer update. `eval_retry()` is refused
  without it at task resolution. The identifier collision it guards needs a
  requested task with the same file, name and arguments as the fed task but
  another dataset, which is the exposure any edit of a task's dataset
  already has, since `task_identifier()` leaves the dataset out.
- **Remembering failed fed tasks across legacy `eval_set()` rounds.** A
  record kept for one invocation reports failure, and a second invocation on
  the same log directory then reports success with nothing run. Every added
  task's failed log has the same gap across legacy rounds today ("Not this
  design").
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
  limit would abort rollouts already running.
- **Refusing waits that would never end** with a process-level wait-for graph
  over handle waits and task, sandbox and sample permits. It must be
  re-checked at every blocking event and limit change (a live retune can
  lower a limit below its use); documented headroom and the warnings cover
  the configurations the use case needs.

## Compatibility and migration

Public API: `enqueue_task()` is async and returns `list[TaskHandle]` (the
migration is in [task-dispatch.md](task-dispatch.md#compatibility-and-migration));
new `TaskHandle`, `TaskEndedError`, `SampleAbandonedError` and
`samples_from_creator`. Existing `SampleSource` tasks are unchanged: only a
`CreatorChannel` gets `stop()`, and only a task fed by its creator ignores
the run's `--limit` and `--sample-id`, runs once under its creator's model
and is exempt from `max_tasks`.

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
  `samples_from_creator()`, which the eval author writes; the number of fed
  tasks a creator adds is the author's code's choice, and their samples stay
  under `max_samples`, `max_sandboxes` and the connection limits.

## Testing

Unit and integration tests on asyncio and trio (`--runtrio` for every async
test touched), with mockllm models; every test that waits is bounded with
`fail_after`.

- `tests/test_enqueue_task.py`:
  - the overview's example as a test at `max_tasks=1`, under `eval()`,
    `eval_set()` and selection mode in-process, and in a two-model run (each
    creator gets one handle, for its own model);
  - `result()` of a child added without a channel, queued and running;
    `cancel()` queued, starting and running; `close()` and `async with`
    leaving running rollouts to finish;
  - the terminal-outcome table row by row: a target whose sent sample's
    setup fails, whose log init fails, cancelled while queued, closed before
    any sample was sent (no attempt, no log), and still queued at a latched
    cancellation (with the waiter in a sibling attempt's shielded cleanup);
  - refusals: a wait in `next_tasks()`; a `samples_from_creator()` task
    added outside a sample, returned from a `TaskSource`, passed to `eval()`
    and `eval_set()`, as a `PreviousTask`, in a `.json` run, and
    `eval_retry()` of its log (finished, and crashed: recovered, then
    refused), each raising and adding nothing; off-loop calls raise, and
    through `anyio.from_thread` succeed;
  - no slot: at `max_tasks=1` with an ordinary task U queued ahead, a fed
    task C starts on its first sample while its creator runs, and U still
    waits for the slot; two fed tasks of one creator run at once; a fed
    task with requests is not started after a latched cancellation; a fed
    task's first sample sent while another record's setup is held starts
    the task when that setup returns;
  - the `max_tasks` warning: a parent at `max_tasks=1` awaiting `result()`
    of an ordinary child logs it once; a wait on a fed task, and a wait
    with a free slot, log nothing;
  - headroom: with `max_sandboxes=1`, a parent holding the only sandbox awaits
    its child's `result()` after its own sample finished, and the warning is
    logged once per provider when a wait starts with every permit in use.
- `tests/test_sample_source.py` (tasks fed by their creator):
  - each sent sample runs under the id `send-<token>-<n>` in send order,
    with the token the first 8 characters of the task's id, and its runs
    come back in epoch order; the caller's object keeps `id is None`; a
    sample with an `id` is refused; two rollout tasks added by one creator,
    and the rollout tasks a creator adds in its first attempt and in its
    retry, share no sample id;
  - a sample sent before the task has started is delivered when it starts;
    one sent while `next_samples()` blocks starts at once; samples sent from
    several solver tasks at once (`tg_collect`) all return; two requests
    whose samples are equal in value each get their own id and runs;
  - in a run with `--sample-id 3` (and separately `--limit 2`), the creator
    runs only its selected samples, every one of four requests it sends to
    its rollout task runs and returns, the rollout log's eval config records
    no limit or sample id, and an ordinary `SampleSource` task in the same
    run is still filtered as today; under `eval()` and in a selection-mode
    worker;
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
    among the run's logs and the eval set's (and worker's) result is failure;
  - a detached task started in a creator's solver, released after the
    creator's attempt has ended while another task keeps the run open, calls
    `enqueue_task()` with a `samples_from_creator()` task: it raises
    `RuntimeError`, adds no record and opens no channel;
  - the creator's attempt ending closes its channels: a started rollout task
    ends once its samples have run, and one never sent a sample ends with no
    log;
  - retention: after many requests, the channel holds no request, sample or
    result once each call has returned;
  - request ownership, each bounded: with the feeder held in another sent
    sample's sandbox setup (stub provider), a request sent meanwhile sits in
    the buffer unadmitted; cancelling the task, and failing that setup, each
    end the task with the request's call raising `TaskEndedError`, and the
    channel holds nothing afterwards.

## Implementation plan

One PR, after step 3 of
[task-dispatch.md](task-dispatch.md#implementation-plan). It does not need
[task-dispatch-setup.md](task-dispatch-setup.md).

- `_eval/task/enqueue.py` (`TaskHandle`, the errors, `TaskAttempt` and
  `_attempt`, the `next_tasks()` wait refusal, the `max_tasks` and
  `max_sandboxes` warnings, `enqueue_task()` returning handles and passing
  its creator), `_eval/task/sample_source.py` (`CreatorChannel`,
  `samples_from_creator()`), `_eval/task/run.py` (attach and detach the
  channel where the `SampleEnqueuer` is registered and cleared),
  `_eval/run.py` (`configure_task()` clearing `limit` and `sample_id` for
  fed tasks; `_attempt` set in `run_one`; the uncounted start step; channels
  closed with the creator's attempt; no retry, and `can_retry=False`, for
  fed tasks; `channel.stop()` from the `cancel_task` callback),
  `_eval/eval.py` (`_resolve_enqueued_tasks` resolving a fed task for its
  creator's model; the `eval_resolve_tasks` refusal; `max_tasks`,
  `max_samples` and `max_sandboxes` docstrings), `__init__.py` (exports),
  `docs/task-source.qmd`, `docs/parallelism.qmd`, `docs/reference`. Tests:
  those above.

## Open questions

None. Decided: `enqueue_task()` returns `list[TaskHandle]` (Ransom,
2026-11-03), becomes async (2026-11-09), and the receiving task declares that
its creator feeds it (2026-11-09); `result()` closes the handle before it
waits (2026-11-10); a task fed by its creator is never retried automatically
(2026-11-10); and (2026-11-11) a task fed by its creator takes no `max_tasks`
slot, with no slot lent to any awaited task (replacing the 2026-11-03
decision to lend, made before a task could declare that its creator feeds
it), is resolved once under its creator's model (narrowing "one handle per
task × model" to ordinary tasks), and its sent samples get
`send-<token>-<n>` ids with a per-task token.

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()`.
- Recording the creator, or that a task was fed by its creator, in the eval
  log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Keeping an added task's failure in the result of an `eval_set()` whose
  later legacy round (`retry_immediate=False`) does not rerun it. It applies
  to every added task, fed or not, and belongs to the change that handles
  added tasks under `eval_set()`.
- Making the logs of tasks added under `eval_set()` pass its log-directory
  check without `log_dir_allow_dirty=True`; it applies to every added task.
- Detecting waits that cannot finish because task slots or sandbox or
  `max_samples` permits are held by their own waiters; see the wait-for
  graph under "Alternatives considered".
