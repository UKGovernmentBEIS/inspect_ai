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
  own samples run (`--limit`, `--sample-id`, ids), and a bad request fails
  only its sender. A retry never reuses one sample's result for another:
  a task that has received samples through a handle is not retried in-run.
- The search example works at the default `max_tasks=1`; a wait that a
  held sandbox or sample permit would block for ever is refused with a
  clear error rather than exceeding `max_sandboxes`.

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
`TaskDeadlockError`.

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
- A wait, or a sample's wait for a sandbox or `max_samples` permit, that
  would never end because the permit's holders are themselves waiting on
  it: `TaskDeadlockError` (see "Waits that would never end").

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
the port, releasing its requests.

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
  (`task/run.py:1749-1755`), as it does for the source's own samples. Its
  futures fail with `SampleAbandonedError`, so a caller never waits for a
  sample that will not run.
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

### Retries of a task that has received samples

A task attempt that has received at least one request through its port
(any request reached `add_samples`, whatever its outcome) is not retried
in-run: when it ends in error, the dispatcher's retry decision treats it as
having no retries left (`can_retry=False` at `src/inspect_ai/_eval/run.py:860`,
`:923`). Its error log is its final log, every unresolved future fails with
`TaskEndedError(log=<that log>)` (the table above), and `result()` returns
that log. The creator, which holds the search state, decides what to do:
typically it enqueues a fresh rollout task and sends the outstanding
samples again. A task whose port has delivered nothing (for example, its
first attempt failed in sandbox setup before any request arrived) is
retried as today, and its `sent` requests are delivered into the retry as
new arrivals.

The reason is identity. A retry reuses completed samples by id and epoch
(`task/run.py:1410`, `:1423`, `:3875`), so it is correct only if every
sample gets the id it had in the first attempt. Automatic ids are handed out
in admission order, and with a port that order interleaves three producers:
the source's pulls, its callbacks (including callbacks fired by port
samples), and port deliveries. With an empty seed, source sample A gets id 1,
port request P id 2, and P's callback follow-up B id 3; a retry that
replays P before the source's pull regenerates A gives B id 1 and silently
reuses A's result for B. Replaying faithfully would mean recording and
re-enforcing the first attempt's whole admission order across pulls,
callbacks and deliveries. The rollout tasks this design serves are driven by
their creator, which can resubmit, so in-run retry is refused for them
rather than made approximately right. (Reservations and limit budgets alone,
tried in earlier drafts, do not fix the order.)

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
- **Loans never lend sandboxes.** A loan lends a task slot only:
  `max_sandboxes` is never exceeded. A wait that capacity would block for
  ever is refused instead; see "Waits that would never end".
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

### Waits that would never end

A sandboxed sample keeps its sandbox, and so its permit of
`sandboxes/<provider>`, from before `sample_init` to after
`sample_cleanup`, including while it waits through a handle (see "Current
behaviour"). So a waiting sample can hold the permit its target's samples
need, and the target's sample can wait for a permit that only the waiter
will release. That can arise when the wait starts (the target already has
a sample waiting for the permit) or later (the target admits a sample
needing the provider from a pull, a callback or the port), so a check at
the wait alone is not enough. Inspect keeps a wait-for graph and checks it
at every event that makes a sample block:

- **Blocking events.** A sample awaiting `result()` or `enqueue_sample()`
  on a task that has not ended; a sample about to wait for a permit of a
  limited resource it cannot take at once, namely a `sandboxes/<provider>`
  permit (`task/sandbox.py:128`) or a slot of its own task's `max_samples`
  limiter (`task/run.py:3898`). `started()` is not a blocking event here:
  the start of an attempt needs a task slot, which a loan provides, and
  setup, neither of which waits for a sample (the attempt registers at
  `task/run.py:1185`, before its samples fan out at `:1928` and acquire
  sandboxes at `:2520`), so a parent holding the only sandbox can await its
  child's start, finish, and release the sandbox to the child's sample.
  Model connections are held only inside `generate`
  (`src/inspect_ai/model/_model.py:1066`), never by a blocked sample, and
  a provider with no limit has no permits, so neither appears.
- **Liveness**, recomputed as a least fixpoint over the samples currently
  blocked: a sample that is running and not blocked is live; a sample
  waiting for a permit is live if a permit is free or a live sample holds
  one; a sample in `result()` is live if its target has not started yet
  (its samples will be checked when they block) or every blocked sample of
  the target is live; a sample in `enqueue_sample()` is live if the
  request's samples have not blocked or are live.
- **Refusal.** If the sample that is about to block would not be live, it
  does not block: the operation raises `TaskDeadlockError` (a
  `RuntimeError`, exported from `inspect_ai`) naming the resource and the
  chain, for example "sample 3 of task 'rollout' would wait for ever for a
  'docker' sandbox: all 1 (max_sandboxes) are held by samples waiting on
  task 'rollout' (sample 1 of task 'search'); raise max_sandboxes, or run
  the waiting task without a sandbox". Raised from a handle wait, the
  caller gets it; raised in a sample's permit wait, that sample fails with
  it as an ordinary sample error (logged on the sample; a port request's
  future resolves with that `EvalSample`; the source's `sample_complete`
  sees it). Because every transition to blocked is checked, the samples
  already blocked were all live before it, and refusing the new one keeps
  them so: the cycle is never closed, and the cap is never exceeded.
- **Scope of the check.** Waiting while live samples hold the permits is
  ordinary waiting. A source whose own `next_samples()` blocks for ever is
  the source's behaviour, not a resource wait, and is not checked.

The graph lives in a new module, `src/inspect_ai/_eval/task/wait_graph.py`:
process-level, in-memory, updated without awaits (no lock needed, as the
eval runs on one event loop), with entries removed when a wait or a permit
wait ends.

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
- **Replaying port requests into an in-run retry** (earlier drafts: replay
  admitted requests first with their limit budget, keep dropped requests'
  ids reserved). Each fix closed one id mismatch, but a retry reuses
  results by id, and ids follow the first attempt's admission order across
  source pulls, callbacks and port deliveries; nothing short of recording
  and re-enforcing that whole order keeps a callback follow-up from taking
  a source sample's id and reusing its result. Refusing in-run retry for a
  task that has received samples is exact, and the creator can resubmit.
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
  `TaskDeadlockError`.
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
  - waits that would never end (`tests/test_enqueue_task.py`, stub sandbox
    providers with `max_sandboxes` set): a parent sample holding the only
    sandbox awaits its child's `started()`, then finishes, and the child's
    sample then gets the sandbox and runs; with the child's sample already
    waiting for that sandbox, the parent's `result()` raises
    `TaskDeadlockError`; with the parent already in `result()`, a child
    sample that needs the sandbox and was added by the child's
    `next_samples()`, and one added by a completion callback, each fail with
    `TaskDeadlockError` while the parent's `result()` returns the child's
    log; the same shapes at `max_sandboxes=2`, with a child on a different
    provider, and with a provider that has no limit run to completion; two
    parents at `max_sandboxes=2` whose children both need the sandbox: the
    second child sample to block is refused and the other completes; a
    two-provider cycle (parent holds X and waits on a child needing Y, whose
    holder waits on a task needing X) is refused at the event that would
    close it; a cycle through a task's `max_samples` slot is refused the
    same way.
- `tests/test_sample_source.py`:
  - port validation: an id equal to a seed id, its int/str equivalent
    (`1` and `"1"`), and a seed id excluded by `--sample-id` or `--limit`
    are refused with `ValueError` while the target is queued and the target
    never sees them; a seed id at an explicit epoch above `epochs` is
    accepted; a duplicate of an earlier request is refused; a request that
    the source's own addition reserved first is refused at delivery, keeps
    no reservation, and the target task completes;
  - abandoned and limit-dropped requests raise `SampleAbandonedError`;
  - retries: a rollout task that has received a port request and then
    errors is not retried even with `task_retry_attempts` set, its
    outstanding requests raise `TaskEndedError` with its error log, and the
    log holds each sample under the input it was sent with (the empty-seed
    A/P/B case: source sample A, port request P and P's callback follow-up
    B keep ids 1, 2 and 3, and nothing is reused across them); a rollout
    task whose first attempt fails in setup before any request arrives is
    retried and receives its pending requests in the retry;
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
   `PortRequest`, errors including `TaskDeadlockError`, `Loan`, the
   `next_tasks()` wait refusal; `_eval/task/wait_graph.py` (new: the
   wait-for graph and its liveness check);
   `enqueue_task()` returns handles), `_eval/task/run.py` (port attach and
   per-request delivery, the result sites, the feeder's owned pull, pull
   buffer and open port, attempt
   `ContextVar`, the `max_samples` permit wait reported to the wait graph),
   `_eval/task/sandbox.py` (the sandbox permit wait reported to the wait
   graph), `_eval/task/sample_source.py` (`SampleEnqueuer` routes
   calls made in the pull scope to the pull buffer; docstrings),
   `_eval/run.py` (no in-run retry once a port has delivered, port close on
   attempt end, loans in the dispatcher, the
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
