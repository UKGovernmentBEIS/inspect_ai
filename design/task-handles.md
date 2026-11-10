# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns one `TaskHandle` per task and model it added. A
handle waits for its task's result and cancels it. A task whose dataset is
`samples_from_creator()` takes its samples from the task that added it: the
creator sends each one with `TaskHandle.enqueue_sample()` and gets back the
sample's logged runs. Such a task stays open until its handle is closed or its
creator's attempt ends, and `async with` closes the handle on exit. A task that
a running task is waiting on borrows a slot when every slot is taken, so a
search that drives a rollout task works at any `max_tasks`:

```python
@task
def rollout_task() -> Task:
    return Task(dataset=samples_from_creator(), solver=rollout(), scorer=judge())

@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        handles = await enqueue_task(rollout_task())  # one per model in the run
        async with handles[0] as rollouts:            # closes on exit
            for _ in range(n_steps):
                sample = await propose_next(state)
                runs = await rollouts.enqueue_sample(sample)  # one EvalSample per epoch
                update(state, runs)
        return state

    return solve
```

`propose_next` is the searcher's own async function and may call a model. In a
run with one model `handles` has one entry; in a run with several, the task is
added once per model, and handles the creator does not use close when its
attempt ends.

Handles build on the run queue of [task-dispatch.md](task-dispatch.md): an
added task is a `TaskRecord` in the run's `RunQueue`, and it starts as soon as
a slot is free.

## Behaviour changes

All of these are new API; no existing eval waits on a handle or uses
`samples_from_creator()`.

- `enqueue_task()` is async and returns `list[TaskHandle]`
  ([task-dispatch.md](task-dispatch.md#behaviour-changes) has the migration).
- A task that a running task waits on through a handle can start beyond
  `max_tasks`, and keeps that extra slot until its attempt ends. A supervisor
  that sets `max_tasks` as a ceiling, such as a selection-mode worker's, sees
  at most one extra running task per distinct task started that way.
- A run whose `max_sandboxes` or `max_samples` leaves no room for samples that
  wait through handles can hang; the docs say so and a warning names the
  provider.
- A task fed by its creator is never retried automatically, and
  `eval_retry()` refuses its log.
- `EvalSpec` gains `send_samples`, so the viewer's generated types change.

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
  `max_tasks=2`, one searcher run against two models, or a selection-mode
  worker whose `max_tasks` equals its batch size. Requiring a larger
  `max_tasks` does not fix it (`eval_set()` already defaults to at least 10);
  the wait has to let its own target start.

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
  beyond `--limit` (with a warning); the source is not told. `reserve_runs` gives a sample without an id a
  generated `dyn-<token>-<counter>` id on a `model_copy()`, so the source's
  object is never changed, and fails an explicit id equal to any id it
  generated earlier in the attempt, at any epoch.
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
`SampleAbandonedError`, `samples_from_creator`. One handle per task × model, in
resolution order (decision: Ransom, 2026-11-03).

- `close()` and `cancel()` are synchronous and idempotent; `close()` on a
  handle whose task is not fed by its creator does nothing. `cancel()` is
  `RunQueue.cancel` ([task-dispatch.md](task-dispatch.md#phases-and-cancelling)).
- `async with` closes the handle on exit and never cancels the task: a
  creator that hits a time limit lets the rollouts it already sent finish.
- `result()` closes the handle first (decision: Ransom, 2026-11-10).
  Without that, a creator that awaits `result()` on a task it feeds would
  wait for an end that its own open handle prevents; the cost is that another
  holder of the same handle can no longer send.
- Every method but the attributes checks first that it runs on the run's
  event loop (`_require_run_loop`), as `enqueue_task()` does.

**Terminal outcomes.** Every record ends (task-dispatch.md, invariant 2),
including when dispatch ends, so no wait outlives its target:

| how the target ended | `result()` | an unresolved `enqueue_sample()` |
| --- | --- | --- |
| an attempt returned a log (success, error, setup failure, log-init failure, abort, a run-level cancellation of a running task, a pending retry abandoned) | that log | `TaskEndedError(log=<that log>)` |
| no attempt returned a log (cancelled while queued, or dispatch ended first) | `None` | `TaskEndedError(log=None)` |

A request that already has its runs keeps them; one dropped or abandoned
raises `SampleAbandonedError`. A cancelled caller's wait raises the
cancellation; the sample it sent still runs and its result is dropped.

### Run shapes and what is refused

- **Waits outside a slot-holding attempt.** `result()` and `enqueue_sample()`
  raise `RuntimeError` before they block unless the calling code runs in an
  attempt that holds its slot ("Slot lending"). Inside
  `TaskSource.next_tasks()` the message says why: "a task handle cannot be
  awaited inside TaskSource.next_tasks(): it runs in no task's attempt and
  holds no slot to lend; return the task, and wait for it from a running
  task" (the dispatcher sets a `ContextVar` in the pull it starts). Anywhere
  else outside an
  attempt: "a task handle can be awaited only from code running in a task of
  the eval". A wait already blocked when its attempt gives its slot back
  keeps waiting until its target ends, without lending. `close()`,
  `cancel()` and the attributes work anywhere.
- **`samples_from_creator()` tasks** are added only by `enqueue_task()` from a
  running sample (`sample_active()` set) whose attempt still holds its slot
  (`_attempt` set and `holds_slot` true); that attempt becomes the creator.
  `enqueue_task()` checks both before `RunQueue.add` commits anything, so a
  detached task that kept a finished sample's context, running after its
  attempt gave its slot back and closed its channels, adds nothing and opens
  no channel. Elsewhere:
  - anywhere else, including after the creator attempt has given its slot
    back, a `TaskSource`'s `next_tasks()` or callback returns: `RuntimeError`
    from `enqueue_task()` or `RunQueue.add`;
  - passed to `eval()`, `eval_set()` or a selection worker: `PrerequisiteError`
    from `eval_resolve_tasks`, before any log is read;
  - as a `PreviousTask`, or a `ResolvedTask` carrying a prior sample source:
    `ValueError` ("tasks fed by their creator must start fresh; pass the
    Task");
  - in a run that logs in the deprecated `.json` format: `ValueError`
    (decision: Ransom, 2026-11-03);
  - `eval_retry()` of such a task's log: `PrerequisiteError` ("<log> cannot be
    retried on its own: task '<task>' took its samples from the task that
    added it; retry that task instead"), checked when the logs are read,
    before any recovery writes.
- **`enqueue_sample()`** on a handle whose task is not fed by its creator, or
  after `close()` or `result()`: `RuntimeError`; with a sample that has an
  `id`: `ValueError` (sent samples take generated ids, so that no later
  attempt's reuse can match one to another sample's record);
  after a drain, `score` or `error` cancel of the task:
  `SampleAbandonedError`; after the task ended: `TaskEndedError`.
- Off the run's loop: `RuntimeError` (see "The handle API").

### What the handles add to the run queue

```python
@dataclass(eq=False)
class TaskAttempt:                     # one per run_one attempt
    record: TaskRecord
    holds_slot: bool = True            # cleared in the step run_one gives its slot back
    channels: list[CreatorChannel]     # channels of tasks its samples added

_attempt: ContextVar[TaskAttempt | None]   # set by run_one around _run_task
```

`TaskRecord` gains `channel: CreatorChannel | None` and `loan: Loan | None`.
`RunQueue.add` takes `creator: TaskAttempt | None`, which `enqueue_task()`
passes from `_attempt`. The dispatcher gains one step after the ordinary
picks, skipped once it has latched a cancellation:

```
    for each record whose loan is not running an attempt, in queue order,
            whose next entry is startable (task-dispatch.md "Start rule"):
        set loan.started; start run_one(entry, on_loan=True)
```

An attempt on a loan does not count toward the ordinary `in_flight`.
`RunQueue.end` closes the record's channel, settling its unresolved
requests with `TaskEndedError(log)`, and clears its loan.

### Tasks fed by their creator

`samples_from_creator()` returns a `CreatorChannel`, a `SampleSource` with no
seed. `RunQueue.add` gives each record whose task has one a fresh
`CreatorChannel` on the record's configured copy of the task, so one `Task`
added for two models has two channels, and records it in the creator's
`TaskAttempt.channels`.

```python
class CreatorChannel(SampleSource):
    enqueuer: SampleEnqueuer | None    # the running attempt's buffer, while one runs
    held: list[PortRequest]            # sent before the task's attempt started
    requests: dict[str, PortRequest]   # by the id the attempt gave the sample, until settled
    closed: bool
    stopped: bool                      # a drain, score or error cancel
    pushed: Wake

@dataclass(eq=False)
class PortRequest:
    sample: Sample                     # the channel's copy of the caller's sample, with no id
    id: str | None                     # the id the attempt generated for it
    futures: dict[int, Future[EvalSample]]   # one per epoch
```

- **Sending.** `enqueue_sample(sample)` takes its own copy of the sample
  (`model_copy()`, so the caller's object is unchanged), creates a
  `PortRequest` with one future per configured epoch, and puts the copy in
  the running attempt's buffer (`enqueuer.enqueue`), which wakes the feeder,
  or in `held` before the attempt starts. It rings `pushed` and waits for every
  future.
- **Ids.** A sent sample has no id, so `reserve_runs` gives it today's
  generated `dyn-<attempt token>-<counter>` id on a further copy
  (`dynamic_sample_id`, `dynamic_id_token`), exactly as for every sample a
  `SampleSource` adds without one. `add_and_start` tells
  the channel which id each admitted sample got (`samples_admitted()`, given
  the source's object and its admitted copy; only a `CreatorChannel` has it),
  and the channel records it on the request, keyed in `requests`, so results
  can be matched to it.
- **Delivery.** `task_run`, where it registers the attempt's `SampleEnqueuer`,
  attaches it to the channel and moves `held` into it; where it clears the
  enqueuer, it detaches it. The task has only that one attempt ("Retries"),
  so a request still unsettled then is settled when the task ends. The
  feeder admits the buffer as it admits any enqueued sample, so a sample
  starts as soon as `max_samples` allows. With an empty seed, a sent sample can need a sandbox setup no seed
  sample requested; the feeder runs it through `setups.ensure()` before
  scheduling the batch, as for any `SampleSource` addition.
- **`next_samples()`** waits on `pushed` and returns `[]` after a send, so the
  feeder drains the buffer, or `None` once the channel is closed or stopped,
  which ends the task when nothing is in flight or buffered (samples sent
  while that `None` is returned still run, as for any source).
- **Results.** `sample_complete` resolves the future of the request holding
  that id for the sample's epoch (an errored or operator-cancelled sample is
  returned with its `error`), and `sample_abandoned` fails it with
  `SampleAbandonedError`; both return `None`, and both ignore an id no
  request holds (a record reused from a prior attempt, whose request settled
  then). A future already resolved keeps its first value. A request leaves
  `requests` once every epoch has settled, so the channel holds no sample
  or result after its call returns.
- **Dropped by selection.** `add_samples` collects the samples it drops for
  `--sample-id` or `--limit`, and `add_and_start` passes them to the
  channel's `samples_dropped()` (only a `CreatorChannel` has it), which fails
  their requests with `SampleAbandonedError`, so a caller never waits for a
  sample that will not run. Other sources keep today's behaviour.
- **Graceful cancels stop it.** `_run_task`'s `cancel_task` callback calls
  `channel.stop()` for `drain`, `score` and `error`: `next_samples()` returns
  `None`, `held` requests fail with `SampleAbandonedError`, and later sends
  raise it. Samples already buffered or running follow the directive's
  existing rules and settle through `sample_complete` or `sample_abandoned`.
- **Closing.** The channel closes on `close()`, `result()`, `async with`
  exit, `cancel()`, the end of the creator's attempt (`run_one` closes the
  attempt's channels in the step it gives its slot back) and `RunQueue.end`.
  A creator that forgets to close cannot keep a rollout task open past its own
  attempt.
- **Retries.** A task fed by its creator is never retried automatically
  (decision: Ransom, 2026-11-10). When its attempt fails for any reason,
  sandbox setup included (before the attempt starts, through
  `TaskRunOptions.setup_error`, or while delivering, when `setups.ensure()`
  for a sent sample raises), the task ends with its error log, its
  unresolved `enqueue_sample()` calls raise `TaskEndedError` with that log,
  and the calls already returned keep their runs. The creator holds the
  search state and every result returned, and decides whether to add a fresh
  task. `run_one` passes `can_retry=False` to `_run_task` for such a task and
  queues no retry for it, so no retry is pre-marked or reported
  (`will_retry` is false), a retry the task requests itself through its
  `TaskCancel` is not honoured, as for a task with no retries left, and a
  setting of `task_retry_attempts` does not apply to it.
- **The log says so.** A new `EvalSpec` field, `send_samples: bool = False`,
  after `task_args_passed`: "the task's dataset was samples_from_creator(),
  so its samples were sent by the task that added it". The `TaskLogger` sets
  it from the dataset type when it builds the spec, so it is in the log from
  the first write and in every copy. Its consumer is `eval_retry()`'s refusal.
  Nothing else needs to look: such a task cannot be requested from `eval()`,
  `eval_set()` or a selection worker, so no eval-set or Steward check ever
  meets its log as a requested task's, and it is never retried in-run.

### Slot lending

Decision: Ransom, 2026-11-03: lend, with loans specific to the awaited task.

```python
@dataclass(eq=False)
class Loan:
    target: TaskRecord                 # the only record this loan can start
    waiters: dict[TaskAttempt, int]    # blocked waits on the target, by the attempt each runs in
    started: bool = False              # an attempt of the target runs on this loan
```

- **Who lends.** A `result()` or `enqueue_sample()` wait in an attempt that
  holds its slot (`_attempt` set, `holds_slot` true), on a target that has not
  ended. It counts in the target's loan from the moment it blocks until it
  returns, is cancelled, or its attempt gives its slot back. A wait elsewhere
  is refused ("Run shapes").
- **One loan per target.** The first wait creates `target.loan` and rings the
  queue's `wake`, so a waiting dispatcher rescans; later waits share it. A
  loan costs a slot only while an attempt of the target runs on it, so
  repeated `enqueue_sample()` calls to a rollout task already running on an
  ordinary slot cost nothing.
- **What it starts.** Only its target's next entry (the record itself, or its
  pending retry), and only when that entry is startable. An earlier,
  unrelated queued task never starts on another task's loan: at
  `max_tasks=1`, with running parent P, an earlier queued task U and P's child
  C, P's wait starts C and U waits for an ordinary slot. If an ordinary slot is
  free when the target becomes startable, it takes that instead.
- **Lifetime.** In the synchronous step in which `run_one` gives its slot
  back, it clears `holds_slot` and removes the attempt's entries from every
  loan; for an attempt that ran on a loan it clears `started`. A loan with no
  waiters and no attempt is dropped; a later wait creates a new one.
  `RunQueue.end` clears the target's loan, and every wait then settles by the
  table under "The handle API". Loans nest: a target running on a loan that
  waits on its own child lends to that child.
- **Bound.** Each target has at most one loan, and a loan runs at most one
  attempt at a time, so the extra running tasks never exceed the number of
  distinct targets whose borrowed attempt is still running, and each ends with
  that attempt.
- **Docs.** The `max_tasks` docstrings, `docs/parallelism.qmd` and the handle
  docs in `docs/task-source.qmd` state the exception.

**Sandboxes and samples are not lent.** A waiting sample keeps its
`sandboxes/<provider>` permit and its task's `max_samples` slot, so a run in
which every permit is held by samples waiting on work that needs one hangs.
Lending them is wrong for each of these reasons:

- `max_sandboxes` is often a hard quota (a cloud account's sandbox limit, a
  cluster's capacity), not a scheduling preference.
- A task slot is bookkeeping, but a sandbox is a live resource: lending would
  add live sandboxes, not move them.
- The limiter is a semaphore; it cannot hand a permit to one specific sample.
- One wait can make the target run many sandboxed samples at once.

So a run that waits through handles needs headroom: `max_sandboxes` for each
provider both tasks use must exceed the number of samples that hold one while
waiting, and `max_samples` must leave room for samples that wait on work its
own samples do. The `max_sandboxes` and `max_samples` docstrings,
`docs/parallelism.qmd` and the handle docs say so. Inspect warns once per
provider per run when a handle wait starts while every permit of a provider
the target's task-level or seed configs name is in use
(`sandbox_limiters()`, `in_use >= limit`): "task 'search' is waiting on task
'rollout', which uses 'docker' sandboxes, while all 1 of them (max_sandboxes)
are in use; if their holders are waiting on 'rollout', the run will not
progress: raise max_sandboxes". The warning is advice; holders that finish
release their permits.

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
  accounting. It does have its own control endpoint, discoverable by
  `inspect ctl` as a separate process, but not as part of the parent's run.
  Until in-process sample sending exists, the long-lived child is the way to
  run such a search.
- **A `send_samples=True` keyword on `enqueue_task()`** with a port attached
  to any `SampleSource` task, serviced by a feeder that pulls the source
  concurrently. It lets handle samples share a sample budget with the task's
  own source, but needs a rewritten feeder (a concurrent pull, a held buffer,
  repulls after late additions, cancelling the pull), delivery checks against
  the source's ids, and log bookkeeping for which samples came through the
  port. Declaring the feeding on the receiving task uses the existing buffer
  and callbacks, and makes the log marker correct by construction.
- **Explicit or channel-assigned ids on sent samples.** They would name
  samples in the log, but explicit ids need duplicate checks against the
  task's other ids, and a channel's own counter would be a second id rule
  beside today's generated ids for samples added without one.
- **Retrying a fed task after a sandbox setup failure**, re-running the
  failed setup in place (a fresh task the creator adds would join the cached
  failed job). The retry would have to bring the requests already settled
  into its results without running them again, which the existing reuse path
  does only for records it can read back from the log, so it needs sample
  logging on and every settled record flushed before the failure, and it has
  to hand the unsettled requests to the retry. The creator already holds
  every result returned and can add a fresh task, so the task ends with its
  error log instead (decision: Ransom, 2026-11-10). The same holds for any
  other failure, and for a retry the task requests itself.
- **A `started()` wait and a `state` property.** Nothing in the use case waits
  for a start or polls a state; `result()` and `enqueue_sample()` cover it.
- **`async with` cancelling the task on exit.** A creator that hits a time
  limit would abort rollouts already running.
- **A guard admitting handle waits only from a sample's own code**, with hooks
  isolated from it. Every region outside a sample where the control channel
  stops reaching the task needed handling; instead, a wait needs only an
  attempt that holds a slot, and ending queued tasks as soon as dispatch
  latches a cancel settles waits in shielded code, including shields users
  write.
- **Slot lending counted globally** (raise the limit by the number of waits).
  An unrelated queued task takes the borrowed slot.
- **No lending, and a warning.** Any fixed `max_tasks` deadlocks once its
  slots are held by waiting tasks ("Why").
- **Tasks added by a running task do not count toward `max_tasks`.**
  Unbounded: a task that adds one task per sample runs them all at once.
- **Refusing waits that would never end** with a process-level wait-for graph
  over handle waits and sandbox and sample permits. It must be re-checked at
  every blocking event and limit change (a live retune can lower a limit below
  its use); documented headroom and a warning cover the configurations the use
  case needs.

## Compatibility and migration

Public API: `enqueue_task()` is async and returns `list[TaskHandle]` (the
migration is in [task-dispatch.md](task-dispatch.md#compatibility-and-migration));
new `TaskHandle`, `TaskEndedError`, `SampleAbandonedError` and
`samples_from_creator`. Existing `SampleSource` tasks are unchanged: only a
`CreatorChannel` gets `samples_dropped()` and `stop()`.

Eval logs: new `EvalSpec.send_samples` (default `False`); logs without it read
as `False`. Producer: `TaskLogger`. Consumer: `eval_retry()`. It changes the
viewer's OpenAPI schema and generated TypeScript types (a coordinated ts-mono
update); the viewer does not display it. An Inspect version without the field
also lacks `samples_from_creator()`, so it cannot load the task to retry it.

No control-channel or config file changes.

## Security

- **Sent samples** may carry model output (the search proposes them). They
  enter the receiving task through its existing `SampleEnqueuer` with
  generated ids, so model output never chooses a sample id or log member
  name; their content is sample input, treated as any dataset sample is.
- A handle is an in-process object; nothing new is exposed on the control
  channel.
- **`EvalSpec.send_samples`** only makes `eval_retry()` refuse a log; a log
  edited to clear it fails at task resolution instead.

## Testing

Unit and integration tests on asyncio and trio (`--runtrio` for every async
test touched), with mockllm models; every test that waits is bounded with
`fail_after`.

- `tests/test_enqueue_task.py`:
  - the overview's example as a test at `max_tasks=1`, under `eval()`,
    `eval_set()` and selection mode in-process, and in a two-model run (two
    handles, the unused one closed when the creator's attempt ends);
  - `result()` of a child added without a channel, queued and running;
    `cancel()` queued, starting and running; `close()` and `async with`
    leaving running rollouts to finish;
  - the terminal-outcome table row by row: a target whose setup fails, whose
    log init fails, cancelled while queued, and still queued at a latched
    cancellation (with the waiter in a sibling attempt's shielded cleanup);
  - refusals: a wait in `next_tasks()` and in code outside any attempt, a
    `samples_from_creator()` task added outside a sample, returned from a
    `TaskSource`, passed to `eval()` and `eval_set()`, as a `PreviousTask`, in a
    `.json` run, and `eval_retry()` of its log, each raising and adding
    nothing; off-loop calls raise, and through `anyio.from_thread` succeed;
  - slot lending: U ahead of C at `max_tasks=1`, where C starts on the loan and
    U waits; two waits share one loan; repeated `enqueue_sample()` to a running
    task takes no extra slot; the loan is dropped when C ends; a nested loan;
    a wait begun while C is queued with its setup held starts C once the setup
    settles; a wait begun after the dispatcher is idle on `wake` starts C; a
    retry of C pending under a waiter starts on the loan; a detached wait keeps
    waiting after its attempt gives its slot back, and its entry leaves the
    loan then; a latched cancellation never starts a loan's target;
  - headroom: with `max_sandboxes=1`, a parent holding the only sandbox awaits
    its child's `result()` after its own sample finished, and the warning is
    logged once per provider when a wait starts with every permit in use.
- `tests/test_sample_source.py` (tasks fed by their creator):
  - each sent sample runs under a generated `dyn-` id and its runs come back
    in epoch order; the caller's object keeps `id is None`; a sample with an `id` is
    refused;
  - a sample sent while the task is queued is delivered when it starts; one
    sent while `next_samples()` blocks starts at once; samples sent from
    several solver tasks at once (`asyncio.gather`, `tg_collect`) all return;
  - `--sample-id` and `--limit` drops raise `SampleAbandonedError`, and other
    sources see today's behaviour;
  - drain, `score` and `error`: an idle open channel ends the task, a held
    request and later sends raise `SampleAbandonedError`, a running sample
    settles under the directive's rule;
  - an empty-seed fed task whose request A completes and whose request B then
    needs a sandbox setup that fails (stub provider), with
    `task_retry_attempts` set: the task is not retried and ends with its error
    log, A's call has already returned its run, B's call raises
    `TaskEndedError` carrying that log, and no second setup attempt runs; the
    same for a setup failure before the attempt starts, with requests sent
    while the task was queued;
  - a detached task started in a creator's solver, released after the
    creator's attempt has given its slot back while another task keeps the run
    open, calls `enqueue_task()` with a `samples_from_creator()` task: it
    raises `RuntimeError`, adds no record and opens no channel;
  - a fed task failing for another reason after a sample ran is not retried,
    and its unresolved requests raise `TaskEndedError` with its error log; a
    retry the task requests itself is not honoured;
  - the creator's attempt ending closes its channels and the rollout task ends;
  - retention: after many requests, the channel holds no request, sample or
    result once each call has returned;
  - `eval.send_samples` is set in the rollout's log while unfinished and when
    finished, and `False` for every other task and every existing log.

## Implementation plan

This design is step 5 of [task-dispatch.md](task-dispatch.md#implementation-plan),
one PR, after step 4 (setup beside the dispatcher, whose setup-failure attempt
path loans rely on):

5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, the errors,
   `TaskAttempt` and `_attempt`, `Loan`, the wait refusals and the
   `next_tasks()` `ContextVar`, `enqueue_task()` returning handles and
   passing its creator), `_eval/task/sample_source.py` (`CreatorChannel`,
   `samples_from_creator()`), `_eval/task/run.py` (attach and detach the
   channel where the `SampleEnqueuer` is registered and cleared; the dropped
   samples and admitted ids from `add_samples`), `_eval/run.py` (`_attempt`
   set in `run_one`; loans in the dispatcher and in `run_one`'s slot release;
   channels closed with the creator's attempt; no retry, and `can_retry=False`,
   for fed tasks; `channel.stop()`
   from the `cancel_task` callback), `_eval/task/log.py` and `log/_log.py`
   (`EvalSpec.send_samples`), `_eval/eval.py` (the `eval_resolve_tasks` and
   `eval_retry()` refusals; `max_tasks`, `max_samples` and `max_sandboxes`
   docstrings), `__init__.py` (exports), `docs/task-source.qmd`,
   `docs/parallelism.qmd`, `docs/reference`. The new `EvalSpec` field lands
   with the coordinated ts-mono update. Tests: those above.

## Open questions

None. Decided: `enqueue_task()` returns `list[TaskHandle]` (Ransom,
2026-11-03), becomes async (2026-11-09), and the receiving task declares that
its creator feeds it (2026-11-09); loans are specific to the awaited task
(2026-11-03); and `result()` closes the handle before it waits (2026-11-10),
because a creator that awaits `result()` on a task it feeds, having forgotten
`close()`, would otherwise wait for an end its own open handle prevents, with
nothing to detect the cycle. The cost is that another holder of the same
handle can no longer send once `result()` is called; and a task fed by its
creator is never retried automatically (2026-11-10).

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()`.
- Recording the creator in the eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Making the logs of tasks added under `eval_set()` pass its log-directory
  check without `log_dir_allow_dirty=True`; it applies to every added task.
- Detecting waits that cannot finish because sandbox or `max_samples` permits
  are held by their own waiters; see the wait-for graph under "Alternatives
  considered".
