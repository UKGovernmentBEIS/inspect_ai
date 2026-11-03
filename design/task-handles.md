# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns one `TaskHandle` per task and model it added. A
handle waits for its task to start or end, cancels or closes it, and, when
the task's dataset is a `SampleSource`, sends it samples and returns each
sample's logged result. A task that a running task is waiting on borrows a
slot when every slot is taken, so a search that drives a rollout task works
at the default `max_tasks=1`:

```python
@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [rollouts] = enqueue_task(rollout_task())
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
  hangs.
- Samples sent through a handle never change which of the receiving task's
  own samples run (`--limit`, `--sample-id`, ids), including across task
  retries, and a bad request fails only its sender.
- The search example works at the default `max_tasks=1`; a wait that
  sandbox capacity would block forever is refused with a clear error rather
  than exceeding `max_sandboxes`.

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
  Verified on this branch's base: a sample enqueued while `next_samples()`
  blocks does not run until it returns.
- Admission (`add_samples`, `task/run.py:1745`) reserves `(str(id), epoch)`
  runs. The reservations start from the complete seed before `--limit` or
  `--sample-id` slices it (`:810`, `:1689-1693`), so a dynamic sample can
  reclaim neither an excluded seed id nor an int/str-equivalent one, while a
  seed id at an epoch above the configured `epochs` is a distinct run
  (`:1710-1731`). A duplicate raises `ValueError` inside the receiving task
  and fails it. `--limit` counts distinct ids against a budget recomputed at
  each attempt (`:1674-1678`); `--sample-id` drops non-matching samples.
- On a task retry, the prior attempt's completed samples are reused, and a
  reused sample's `sample_complete` fires again so a completion-driven
  source regenerates its follow-ups (`:1473`); a limited feed's later
  admissions are seeded from the prior log as they are re-admitted
  (`:952-965`).
- The sites that report a sample to the source are `task/run.py:1480`,
  `:1619` and `:3372` (`sample_complete`, and `sample_abandoned` for a
  sample cancelled before it was logged).
- The dispatcher awaits `TaskSource.next_tasks()` inline, only when nothing
  is queued or running (`src/inspect_ai/_eval/run.py:1103`), so a task
  enqueued inside it starts only after it returns. Verified on this
  branch's base on asyncio and trio at `max_tasks=2`.
- A sample's sandboxes are counted by a process-wide limiter per provider,
  `sandboxes/<provider>` (`max_sandboxes`, or the provider's
  `default_concurrency()`), which `sandboxenv_context` holds from before
  `sample_init` until after `sample_cleanup`, across the whole solver
  (`src/inspect_ai/_eval/task/sandbox.py:118-128`, `:51-80`). The sample
  limiter (`max_samples`) is per task (`task/run.py:3898`), and model
  connection slots are held only during a `generate` call
  (`src/inspect_ai/model/_model.py:1066`).
- A second `eval()` in the same process while one runs is refused
  ("Multiple concurrent calls to eval_async are not allowed",
  `src/inspect_ai/_eval/eval.py:797`).

## Design

### The handle API

`enqueue_task(tasks, *, run_id=None) -> list[TaskHandle]`: still
synchronous, one handle per task × model it added, in resolution order
(decision: Ransom, 2026-11-03). Existing callers, which ignore the `None`
returned today, are unaffected. New exports from `inspect_ai`:
`TaskHandle`, `TaskEndedError`, `SampleAbandonedError`,
`SandboxCapacityError`.

```python
class TaskHandle:
    task_id: str
    task: str                       # task name
    model: str
    @property
    def state(self) -> Literal["queued", "running", "ended"]: ...
    async def started(self) -> None:
        """Wait until the task's first attempt starts.

        Returns once an attempt has started, including one that then fails
        (a setup failure starts an attempt that writes an error log).
        Raises TaskEndedError(log=None) if the task ends before its first
        attempt starts.
        """
    async def result(self) -> EvalLog | None:
        """Wait until the task ends.

        Returns its latest attempt's log, or None if it ended before its first
        attempt started (cancelled while queued, admission failed, or the run
        ended first). Never raises TaskEndedError.
        """
    def cancel(self) -> None:
        """Abort it, like `inspect ctl task cancel`.

        A task whose first attempt has not started ends with no log; a task
        waiting for a retry keeps its latest attempt's log.
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
    log: EvalLog | None             # the task's final log, None if it never started
    error: BaseException | None     # the admission failure, if that is why it never started

class SampleAbandonedError(RuntimeError):
    sample: Sample
    epoch: int
```

`cancel()` and `close()` are synchronous requests and idempotent. Each
record has at most one handle per `enqueue_task()` call; under a run with
two models, `enqueue_task(task)` returns two handles, each addressing one
task × model.

**Terminal outcomes, per method.** Every record ends (a run-level
cancellation ends every queued record with no log), so no wait outlives its
target. What each wait does when the target ends:

| how the target ended | `started()` | `result()` | an `enqueue_sample()` request still unresolved |
| --- | --- | --- | --- |
| one or more attempts ran (success, error, setup failure, abort, run-level cancellation of a running task), including a task cancelled, drained or left queued at run end while waiting for a retry | returned when the first attempt started | the latest attempt's log | `TaskEndedError(log=<latest log>)` |
| cancelled or drained, or the run ended, before its first attempt started | `TaskEndedError(log=None, error=None)` | `None` | `TaskEndedError(log=None, error=None)` |
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
or `TaskSource` callback, under `eval()`, `eval_set()` and selection mode.
Everything else is refused with a clear error:

- `TaskHandle.enqueue_sample()` on a task whose dataset is not a
  `SampleSource`: `TypeError` naming the task.
- `TaskHandle.enqueue_sample()` on a handle that was not created by a
  running task (for example from `TaskSource.next_tasks()`), or after
  `close()`: `RuntimeError`.
- `TaskHandle.enqueue_sample()` after the task has ended: `TaskEndedError`
  as in the table.
- Awaiting `started()`, `result()` or `enqueue_sample()` inside
  `TaskSource.next_tasks()`: `RuntimeError` ("a task handle cannot be
  awaited inside TaskSource.next_tasks(): no task starts until
  next_tasks() returns; return the task, and wait for it from a task or a
  task callback"). The dispatcher awaits `next_tasks()` inline (see
  "Current behaviour"), so it could never start the awaited task. The
  dispatcher sets a `ContextVar` around that await, and the handle checks
  it before waiting. Calling `enqueue_task()` there, and `cancel()` or
  `close()` on its handles, stays allowed.
- A wait whose target could never get a sandbox because waiting samples
  hold every permit of a provider it needs: `SandboxCapacityError` (see
  "Slot lending").

### What the handles add to the run queue

[task-dispatch.md](task-dispatch.md#the-run-queue) defines `TaskRecord`,
`RunQueue`, admission and the dispatch loop. This design adds to the record:

```python
    creator: TaskAttempt | None      # the running task attempt that called enqueue_task(), if any
    port: SamplePort | None = None   # only when the dataset is a SampleSource
    loan: Loan | None = None         # see "Slot lending"
```

and to the dispatch loop one step after the ordinary picks, with the
ordinary count excluding records running on a loan:

```
    while not cancelled and ordinary_in_flight < effective_max_tasks(parallel):
        ... ordinary picks, unchanged ...
    for record in startable records holding a loan, in queue order:
        start run_one(record, on_loan=True)
```

The creator is the attempt whose context `enqueue_task()` was called in (a
`ContextVar` that `_run_task` sets per attempt); `TaskSource` callbacks fired
by a task count as that task. `RunQueue.end` also clears `loan` and closes
the port, releasing the requests it kept for retry replay.

### Sending samples

A record whose dataset is a `SampleSource` has a `SamplePort` (in
`enqueue.py`), created when the record is configured. It keeps one
`PortRequest` per `enqueue_sample()` call:

```python
@dataclass(eq=False)
class PortRequest:
    sample: Sample                   # as sent; an id assigned at delivery is kept
    epoch: int | None
    state: Literal["sent", "admitted", "dropped", "refused", "done"]
    futures: dict[int, Future[EvalSample]]   # one per planned epoch
```

**Validation at the call.** `enqueue_sample()` validates `epoch` as the
task-side `enqueue_sample()` does. For a sample with an id it computes the
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
- the runs of earlier requests on this port;
- while an attempt runs, that attempt's own reservations.

A sample without an id is given one at delivery by the runner's auto-id
rule.

**Delivery.** While an attempt runs, the port is attached to that attempt's
`SampleEnqueuer`, so a request starts as soon as `max_samples` allows; a
request sent while the task is queued is delivered when its first attempt
starts. The source's own additions can still reserve an id between the
check and the delivery (the source returns or enqueues the same id first).
The port therefore delivers each request through `add_samples` on its own,
and records which of three things happened:

- **`refused`**: its runs were reserved by then, so `reserve_runs` raised
  before reserving or allocating anything (only an explicit id can clash;
  an automatic id never does). Its futures fail with the same `ValueError`
  and the receiving task continues. A duplicate from the source's own
  samples still fails the task, as today.
- **`dropped`**: `add_samples` reserved its runs, and gave it an automatic
  id if it had none, before `--sample-id` or `--limit` filtered it out
  (`task/run.py:1749-1755`). Its futures fail with `SampleAbandonedError`,
  so a caller never waits for a sample that will not run, and the port
  keeps the id and runs it was given, because they are part of the
  attempt's id history: with seed id 1 and `sample_id=[1, 3]`, an anonymous
  request is given id 2 and dropped, and the source's next anonymous
  follow-up is given id 3 and runs.
- **`admitted`**: `add_samples` accepted it, with the id it was given.

**Results.** At the sites that already report samples to the source (see
"Current behaviour"), before the source's own `sample_complete` the port
resolves the matching future with the `EvalSample` (an errored or
operator-cancelled sample is returned, with its `error`); before
`sample_abandoned` it fails the future with `SampleAbandonedError`.
`enqueue_sample()` returns when every epoch's future has resolved, and the
request is then `done`.

### The feeder services the port while the source blocks

`SampleSource.next_samples()` may block indefinitely
(`sample_source.py:63`), and today the feeder awaits it inline
(`task/run.py:1854`), so nothing buffered starts until it returns (verified
on this branch's base: a sample enqueued while `next_samples()` blocks does
not run until it returns). `feed_samples` changes so that a pull never
blocks the buffer, while everything a pull itself adds keeps today's order:

```
async with task group tg:                  # owned by the feeder
    pull = None                            # the one outstanding next_samples() call
    while True:
        await checkpoint()
        if pull is done:                   # checked first: a returned batch keeps priority
            more = pull.result(); pull = None
            if more: await add_and_start(more)
            own = await add_and_start(pull_buffer.drain())   # the pull's own enqueue_sample() calls
            source_done = more is None and not own and not added_during_pull
            continue
        if buffered := enqueuer.drain():   # port, and callbacks of samples running meanwhile
            if await add_and_start(buffered):
                if pull is not None: added_during_pull = True
                else: source_done = False
            continue
        if scheduler.outstanding > 0:
            await feeder_wake.wait(); continue   # rung by settle, enqueue, pull done, port close
        # no samples in flight or buffered
        if limit exhausted: break              # cancels an outstanding pull below
        if pull is not None: await feeder_wake.wait(); continue
        if not source_done:
            added_during_pull = False
            pull = start next_samples() in tg  # with the pull scope set (below)
            continue
        if port is open: await feeder_wake.wait(); continue
        break
    cancel tg                              # an outstanding pull is cancelled, then joined
```

- A pull starts only when the task is fully idle, as today, and at most one
  is outstanding. It runs as a child of the feeder's task group, so it is
  joined before the feeder returns, its exception fails the task as an
  inline pull's does today, and a task cancel, a run cancel or the task
  ending cancels it with the feeder.
- **What a pull adds keeps today's order.** The pull task runs with a pull
  scope set (a `ContextVar` the feeder sets inside that task only), and
  `enqueue_sample()` called within it goes to a separate `pull_buffer`
  that is admitted only when the pull completes, after the batch the pull
  returns. That is today's order: the feeder awaits the pull inline, admits
  the returned batch, and drains what was enqueued meanwhile on its next
  pass (`task/run.py:1854-1865`). So `--limit`, `--sample-id` and assigned
  sample ids select exactly the samples they select today; verified on this
  branch's base: with an empty seed and `limit=1`, a `next_samples()` that
  enqueues A and returns `[B]` runs B, and the design keeps B.
- **Additions from elsewhere start at once.** While a pull is outstanding
  and still blocked, samples arriving through a handle, and the follow-ups
  returned by callbacks of the samples running meanwhile (which today
  cannot exist, because nothing runs during a pull), are admitted as they
  arrive, ahead of whatever the pull later returns, and their
  `sample_complete` and `sample_abandoned` may fire while `next_samples()`
  is still awaiting. The `SampleSource` docstrings say so. Under `--limit`
  they take the limit in arrival order. When the feeder observes a
  completed pull and such additions in the same pass, the pull's batch and
  its own enqueues go first and the other additions follow. No existing
  source sees a difference: only the new handle API adds samples while a
  pull blocks.
- **A late addition always earns a repull.** When the pull returns `None`,
  the source is consulted again after the samples added during or at the
  end of that pull have run, whichever buffer they came through:
  `added_during_pull` records additions admitted while the pull was
  outstanding, and `own` those the pull enqueued itself, so the pull's
  `None` cannot erase them. That is today's rule for a late enqueue during a
  terminal call (`task/run.py:1855-1860`, `sample_source.py:69`); verified
  on this branch's base: a `next_samples()` that enqueues a sample and
  returns `None` is called again and its next batch runs. When the task is
  fully idle and the sample limit is exhausted, an outstanding pull is
  cancelled and the task ends, since nothing it returned could run.
- A port closing does not end an outstanding pull: the source still decides
  when the task ends. An open port only keeps the task from ending after
  the source is done.

### Keeping the task open

A `SampleSource` task with an open port does not end when its source is
exhausted: the feeder waits for the port (a new sample or a close) instead
of finishing. The port closes on `close()`, on `cancel()`, when the task
attempt that created the handle ends, and when the run ends. A handle
created outside any task attempt has its port closed from the start. So a
creator that forgets `close()` cannot keep a rollout task open past its own
attempt.

### Retries: replaying requests

If the target's attempt ends and no retry follows, every unresolved future
fails with `TaskEndedError(log=<final log>)` (the table above). If a retry
follows, the futures stay pending and the port replays requests into the
retry attempt by their recorded state, so a replay never changes the
admitted plan:

- **Delivered requests reserve their ids first.** Before the retry
  attempt's feeder starts, the runs and id of every `dropped`, `admitted`
  and `done` request are added to the attempt's reservations and used ids
  (`reserved_runs`, `seen_ids`), so the runner's automatic ids, which only
  ever move up past used ones, give the source's regenerated follow-ups the
  ids they had in the first attempt. In the `sample_id=[1, 3]` example,
  the retry's follow-up is again given id 3 and runs, where without the
  reservation it would be given id 2 and filtered out.
- **`dropped` and `refused` requests never run again.** Their futures have
  already failed; a `dropped` request keeps only its reservation, is not
  admitted and is not charged to `--limit`, and a `refused` request
  reserved nothing. Example, with `limit=2`: seed S produces follow-up A,
  and port request D arrives while A runs and is dropped by the limit. If
  A then errors and the task retries, D stays dropped, S is reused and
  regenerates A, and A runs again in the second place.
- **`admitted` and `done` requests are re-admitted first, with their
  budget.** Before the retry attempt's feeder starts, their ids also join the
  attempt's limit set (`admitted_ids`) and the limit's remaining budget is
  reduced by their count, so they take exactly the places they held and
  cannot displace a regenerated follow-up; each keeps the id the first
  attempt gave it, so completed runs are reused from the prior log (their
  re-fired `sample_complete` does not resolve a future twice) and the rest
  run again. Their ids are seeded from the prior log as a limited feed's
  admissions are today.
- **`sent` requests** (never delivered) are delivered as new arrivals after
  the retry starts, under the delivery rules above.

### Slot lending

Decision: Ransom, 2026-11-03: lend, with loans specific to the awaited
task. Without it the use case deadlocks at the default `max_tasks=1`, and in
selection-mode workers whose supervisor sets `max_tasks` to the selected
batch size: the creator holds the only slot while it waits for its rollout.

```python
@dataclass(eq=False)
class Loan:
    target: TaskRecord              # the only record this loan can start
    waiters: int = 0                # waits on the target that are blocked now
    started: bool = False           # the target is running on this loan
```

- **Who lends.** A wait lends when it is made from inside a running task
  attempt (a sample, scorer, tool or callback of a task the dispatcher
  started, including one that is itself running on a loan) on a target
  record that is queued: `started()`, `result()`, or an `enqueue_sample()`
  whose sample cannot run until the target starts. A wait from outside any
  running attempt lends nothing, because nothing is holding a slot while it
  waits.
- **One loan per target.** The first such wait creates `target.loan` and
  rings the queue; later waits on the same queued target add to `waiters`
  and share it. A wait on a target that is already running lends nothing,
  so repeated `enqueue_sample()` calls to a running rollout task cost no
  more slots.
- **What it starts.** The dispatcher starts a record above the ordinary
  limit only if the record holds a loan, after the ordinary picks, and only
  when it is startable (admitted, setups settled, not paused). An earlier,
  unrelated queued task never starts on another task's loan: at
  `max_tasks=1`, with running parent P, an earlier queued task U and P's
  child C, P's wait starts C, and U waits for an ordinary slot. If an
  ordinary slot is free when the target becomes startable, the target takes
  it and the loan is dropped unused.
- **Lifetime.** While the target is queued, the loan lives while
  `waiters > 0`; if every waiter stops waiting (cancelled, or its attempt
  ended), the loan is dropped. Once the target has started on the loan, it
  keeps its extra slot until that attempt ends, whatever its waiters do; the
  loan is returned then. A retry of the target goes back to the queue
  without a loan and borrows again only if someone is still waiting on it.
  Loans nest: a target running on a loan that waits on its own child lends
  to that child. The number of running loans is bounded by the number of
  distinct tasks that running tasks are waiting on.
- **Waits that sandbox capacity would block forever.** A loan lends a task
  slot, not a sandbox: `max_sandboxes` is never exceeded. A sandboxed
  waiting sample keeps its sandbox, and so its permit of
  `sandboxes/<provider>`, while it waits, and the target's samples need
  permits of the providers their sandboxes use. If every permit of one of
  those providers is held by samples that are themselves waiting through a
  handle, none is ever released and the target's sample would wait for
  ever. So each wait that would block (`started()`, `result()` or
  `enqueue_sample()` on a target that has not finished) first registers its
  sample as a waiter holding the providers it holds, then checks each
  provider the target can need (the task's sandbox type, its seed samples'
  and, for `enqueue_sample()`, the sent sample's): when the permits held by
  waiting samples equal that provider's current limit, the wait
  unregisters and raises `SandboxCapacityError` (a `RuntimeError`, exported
  from `inspect_ai`): "waiting on task 'rollout' would never end: all 1
  'docker' sandboxes (max_sandboxes) are held by samples waiting on tasks
  that need a 'docker' sandbox; raise max_sandboxes, or run the waiting
  task without a sandbox". The check runs at every new wait, so the wait
  that would complete the cycle is the one refused, and the samples already
  waiting keep waiting for capacity that the refused sample's cleanup then
  releases. A provider with no limit is never checked. Waiting while other
  samples hold the permits is ordinary waiting: they release them when they
  finish. `max_samples` is per task and model connections are held only
  inside `generate`, so neither can be held by a waiting sample on the
  target's behalf, and neither needs a rule here.
- **Waits on a target that cannot run.** A loan only starts a startable
  target. A target whose setup failed becomes startable, starts and ends
  with an error log; a target cancelled while queued, whose admission
  failed, or still queued when the run ends, ends without starting. Each
  wait then ends as the table under "The handle API" says, so a loan never
  leaves a waiter blocked.
- **Docs.** The `max_tasks` docstrings, `docs/parallelism.qmd` and the
  handle docs in `docs/task-source.qmd` state the exception: a task that a
  running task is waiting on through a handle may run beyond `max_tasks`,
  one extra task per awaited task.

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
- **Replaying every sent request on a retry.** Simple, but a request the
  limit dropped could take a place a regenerated follow-up held, changing
  which samples the task runs.
- **Forgetting dropped requests on a retry.** Also simple, but the ids
  they consumed would go to the source's follow-ups instead, and
  `--sample-id` would then select different follow-ups.
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

- `enqueue_task()` returns `list[TaskHandle]` instead of `None`; signature
  and synchronous behaviour unchanged.
- New `inspect_ai.TaskHandle`, `TaskEndedError`, `SampleAbandonedError`,
  `SandboxCapacityError`.
- `SampleSource` docstrings: samples sent through a handle start while
  `next_samples()` is awaiting, and their callbacks may fire meanwhile;
  what `next_samples()` itself enqueues is admitted after the batch it
  returns, as today.

Behaviour changes:

- Slot lending lets a task that a running task is waiting on start beyond
  `max_tasks` (new API only; no existing eval waits on a handle). A
  supervisor that sets `max_tasks` as a ceiling, such as a selection-mode
  worker's, sees one extra running task per awaited task (decision: Ransom,
  2026-11-03).
- The feeder's owned pull changes nothing for existing sources: what a
  pull enqueues keeps today's order, and only handle samples (and their
  follow-ups) start while a pull blocks.
- No eval log schema, viewer type, control-channel or config file changes.

## Security

- **Samples sent through a handle** may carry model output (the search
  proposes them). They enter the receiving task through the same
  `SampleEnqueuer` path as `enqueue_sample()`: ids are checked for
  duplicates by `(str(id), epoch)` against the seed, earlier requests and
  the running attempt before they reach the task, and again at delivery,
  so a crafted id can neither reclaim a seed id (excluded ones included)
  nor fail the receiving task; ids become log member names through the
  existing path; content is sample input, which the task treats as it
  treats any dataset sample.
- A handle is an in-process object; nothing new is exposed on the control
  channel.

## Testing

Unit and integration tests, asyncio and trio (`--runtrio` for every async
test touched), with mockllm models:

- `tests/test_enqueue_task.py`:
  - the overview's example as a test at `max_tasks=1`, under `eval()`,
    `eval_set()` and eval-set selection mode in-process;
  - `started()`, `result()`, `cancel()` queued and running, `close()`,
    `enqueue_sample()` results per epoch;
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
  - slot lending: an earlier unrelated queued task U ahead of the awaited
    child C at `max_tasks=1`, where C starts on the loan and U waits for an
    ordinary slot; several samples waiting on one queued task share one
    loan; repeated `enqueue_sample()` calls on a running task lend nothing;
    the loan is returned when C ends; a nested loan;
  - sandbox capacity, with a stub provider: a sandboxed search sample
    waiting on a rollout task of the same provider at `max_sandboxes=1`
    raises `SandboxCapacityError` at the wait instead of hanging, and the
    rollout then runs once the search sample's sandbox is cleaned up; the
    same at `max_sandboxes=2` runs the rollout; a rollout on a different
    provider runs at `max_sandboxes=1`; two search samples at
    `max_sandboxes=2` that wait in turn, where the second wait is refused;
    a provider with no limit is not checked.
- `tests/test_sample_source.py`:
  - port validation: an id equal to a seed id, its int/str equivalent
    (`1` and `"1"`), and a seed id excluded by `--sample-id` or `--limit`
    are refused with `ValueError` while the target is queued and the target
    never sees them; a seed id at an explicit epoch above `epochs` is
    accepted; a duplicate of an earlier request is refused; a request that
    the source's own addition reserved first is refused at delivery, keeps
    no reservation, and the target task completes;
  - abandoned and limit-dropped requests raise `SampleAbandonedError`;
  - retry replay: the `limit=2` S/A/D case under "Retries", where D stays
    dropped and A runs again in the retry; with seed id 1 and
    `sample_id=[1, 3]`, an anonymous port request dropped as id 2 and an
    anonymous source follow-up run as id 3, the follow-up again gets id 3
    and runs in the retry while the request does not run; an admitted request is reused
    from the prior log when it completed and re-run when it did not, with
    its id and without resolving its future twice; a request sent while
    the attempt was ending is delivered in the retry;
  - the feeder: a sample sent through a handle while `next_samples()` stays
    blocked runs at once; the blocked pull is cancelled when the task is
    cancelled, when the run is cancelled and when the sample limit is
    exhausted, and a pull's exception still fails the task; with an empty
    seed and `limit=1`, a `next_samples()` that enqueues A and returns `[B]`
    runs B, with the ids assigned today; a handle sample arriving while the
    pull blocks is admitted first and takes the limit; additions buffered
    when a completed pull is observed follow its batch; a pull that
    enqueues a sample and returns `None`, and a pull that returns `None`
    after a handle sample arrived during it, are each followed by another
    pull once those samples have run.

## Implementation plan

This design is step 5 of the plan in
[task-dispatch.md](task-dispatch.md#implementation-plan), one PR, after
step 3 (the run queue and dispatcher) and independent of step 4:

5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, `SamplePort`,
   `PortRequest`, errors including `SandboxCapacityError`, `Loan`, the
   `next_tasks()` wait refusal, the waiting-sample sandbox check;
   `enqueue_task()` returns handles), `_eval/task/run.py` (port attach and
   per-request delivery, the result sites, the feeder's owned pull, pull
   buffer and open port, retry replay by request state (reservations of
   delivered requests first), attempt
   `ContextVar`), `_eval/task/sandbox.py` (records which provider permits
   a sample holds), `_eval/task/sample_source.py` (`SampleEnqueuer` routes
   calls made in the pull scope to the pull buffer; docstrings),
   `_eval/run.py` (port close on attempt end, loans in the dispatcher, the
   `next_tasks()` scope), `_eval/eval.py` and `_eval/evalset.py`
   (`max_tasks` docstrings), `__init__.py` (exports), `docs/task-source.qmd`,
   `docs/parallelism.qmd` and `docs/reference`. Tests: those above.

## Open questions

None. Ransom decided (2026-11-03) that `enqueue_task()` stays synchronous
and returns `list[TaskHandle]` ("The handle API"), and that a task a running
task waits on borrows a slot through a loan specific to it ("Slot
lending").

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()` (only
  `enqueue_task()` returns handles).
- Recording the creator in the eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
