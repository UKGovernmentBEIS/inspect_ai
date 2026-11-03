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

A task's sample ids depend on when samples sent through a handle arrived,
so a task that has received one records that in its log, and nothing is
ever reused from that log: the task is not retried, `eval_retry()` refuses
it, and its creator sends the samples to a fresh task instead. Loans lend
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
  hangs.
- Samples sent through a handle never change which of the receiving task's
  own samples run (`--limit`, `--sample-id`, ids), and a bad request fails
  only its sender. No later run reuses one sample's result for another: the
  log of a task that has received samples through a handle says so, and
  nothing is ever reused from it.
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
  Verified on this branch's base: a sample enqueued while `next_samples()`
  blocks does not run until it returns. A control-channel rerun
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
- On a task retry, the prior attempt's completed samples are reused, and a
  reused sample's `sample_complete` fires again so a completion-driven
  source regenerates its follow-ups (`:1473`); a limited feed's later
  admissions are seeded from the prior log as they are re-admitted
  (`:952-965`).
- Every reuse of a prior log goes through `eval_log_sample_source()`
  (`task/run.py:3743`), which returns the id-and-epoch lookup, the seed
  source and `prior_checkpoints_dir` (checkpoint resume keys on id and epoch
  too, and its existing guards already withhold it when ids are unstable,
  `:3812`). It has two callers: the in-run retry (`src/inspect_ai/_eval/run.py:979`)
  and `resolve_previous_task()` (`src/inspect_ai/_eval/loader.py:363`), which
  every `PreviousTask` reaches: `eval_retry()`
  (`src/inspect_ai/_eval/eval.py:1973`), eval-set resume in ordinary and
  legacy retry rounds (`src/inspect_ai/_eval/evalset.py:1148`, `:1530`) and
  selection-worker resume (`evalset.py:1763`). A task added by
  `enqueue_task()` is resolved fresh (`_resolve_enqueued_tasks`), so today
  its log reaches these paths through the in-run retry, an `eval_retry()`
  pointed at it, or a requested task with the same task identifier.
- Mid-run log state is recorded the way `inspect ctl config` retunes are:
  `.eval` appends a journal member and flushes it at once
  (`src/inspect_ai/log/_recorders/eval.py:281`, `:1133`), header reads of an
  unfinished `.eval` log read the journal (`_read_header_async`, `:2135`;
  `_read_header`, `:2266`), and `log_finish` consolidates it into the header
  (`:365`). The `.json` recorder keeps it on the in-memory log
  (`src/inspect_ai/log/_recorders/json.py:203`), writes the whole file on
  `flush` (`:292`), and its streaming header reader lists header keys one by
  one (`:613`). Only these two recorders exist
  (`src/inspect_ai/log/_recorders/create.py:7`).
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

`enqueue_task(tasks, *, run_id=None) -> list[TaskHandle]`: still
synchronous, one handle per task × model it added, in resolution order
(decision: Ransom, 2026-11-03). Existing callers, which ignore the `None`
returned today, are unaffected. New exports from `inspect_ai`:
`TaskHandle`, `TaskEndedError`, `SampleAbandonedError`.

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
- `eval_retry()` of a log whose task received samples through a handle:
  `PrerequisiteError` (see "Logs of tasks that received samples").

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
feeder (after `log_start`, `task/run.py:1127`), which delivers requests as
they arrive, so a request starts as soon as `max_samples` allows; a request
sent while the task is queued is delivered when its first attempt starts.
The source's own additions can still reserve an id between the check at
the call and the delivery (the source returns or enqueues the same id
first). The feeder therefore delivers each request on its own, in three
steps:

1. It checks the request's planned runs against the attempt's reservations,
   the same check `reserve_runs` makes (`task/run.py:1710-1731`) without
   reserving anything. A clash makes the request **`refused`**: nothing is
   reserved, allocated or written, its futures fail with the same
   `ValueError`, and the receiving task continues. Only an explicit id can
   clash; an automatic id never does. A duplicate from the source's own
   samples still fails the task, as today.
2. If this is the attempt's first delivery to pass step 1, it awaits
   `TaskLogger.log_handle_samples()`, which writes the marker described
   under "Logs of tasks that received samples" before anything is
   reserved. The feeder is the task's only admitter (see "Current
   behaviour"), and the source's additions wait in its buffers while it
   awaits, so nothing changes the reservations between step 1 and step 3.
   A failure to write the marker fails the task as any log write failure
   does.
3. It calls `add_samples` with the request alone, which reserves its runs
   and gives it an automatic id if it has none, then records one of:
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
`enqueue_sample()` returns when every epoch's future has resolved, and the
request is then `done`.

### The feeder services the port while the source blocks

`SampleSource.next_samples()` may block indefinitely
(`sample_source.py:63`), and today the feeder awaits it inline
(`task/run.py:1854`), so nothing buffered starts until it returns (verified
on this branch's base: a sample enqueued while `next_samples()` blocks does
not run until it returns). `feed_samples` changes so that a pull never
blocks the port, while everything the source adds keeps today's order:

```
async with task group tg:                  # owned by the feeder
    pull = None                            # the one outstanding next_samples() call
    while True:
        await checkpoint()
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
        if limit exhausted:                    # held additions are counted over the limit, as today
            await add_and_start(enqueuer.drain()); break   # an outstanding pull is cancelled below
        if pull is not None: await feeder_wake.wait(); continue
        if not source_done:
            port_during_pull = False
            pull = start next_samples() in tg
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
- **Only handle samples start while a pull blocks.** Everything the source
  adds while a pull is outstanding stays in the `SampleEnqueuer` buffer, in
  arrival order, and is admitted when the pull completes, after the batch it
  returns: what `next_samples()` itself enqueues, and the follow-ups that
  `sample_complete` returns for samples finishing meanwhile, whether those
  are control-channel reruns (which start during a pull today, see
  "Current behaviour") or samples sent through a handle. That is today's
  order exactly: the feeder awaits the pull inline, admits the returned
  batch, and drains the buffer on its next pass (`task/run.py:1854-1865`).
  So `--limit`, `--sample-id` and assigned sample ids select exactly the
  samples they select today. Verified on this branch's base: with an empty
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
  `sample_source.py:69`); verified on this branch's base: a `next_samples()`
  that enqueues a sample and returns `None` is called again and its next
  batch runs. When the task is fully idle and the sample limit is
  exhausted, an outstanding pull is cancelled and the task ends, since
  nothing it returned could run.
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

### Logs of tasks that received samples

A task's sample ids depend on the order in which samples were admitted,
and with a port that order interleaves three producers: the source's pulls,
its callbacks (including callbacks fired by port samples), and port
deliveries. With an empty seed, source sample A gets id 1, port request P
id 2, and P's callback follow-up B id 3. A later run of the same task has
no port requests unless its creator sends them again, so B gets id 2, and
a lookup by id and epoch (`task/run.py:3843`, `:3870`) would return P's
result as B's.
So a log that a port has contributed to is never reused:

- **The marker.** A new header field,
  `EvalLog.handle_samples: bool = False`, after `config_updates`:
  "the task received samples through a `TaskHandle`; its sample ids depend
  on when they arrived, so no later run reuses its samples or checkpoints,
  and `eval_retry()` refuses it". `TaskLogger.log_handle_samples()` sets it
  once per attempt, at step 2 of "Delivery", through a new abstract
  `Recorder.log_handle_samples(eval)`, which both registered recorders
  implement:
  - `.eval` appends `_journal/handle_samples.json` and flushes the log at
    once, as a config update is journalled and flushed (see "Current
    behaviour"), but with fsync, which a config update's flush skips. The header readers of an unfinished log
    (`_read_header_async`, `_read_header`) and `log_init`'s re-read of an
    existing destination (`eval.py:181`) read the member, and `log_finish`
    writes the field into `header.json`.
  - `.json` sets the field on the in-memory log and flushes the whole file
    at once; `_read_header_streaming` reads the key with the others
    (`json.py:613`).
  - Every site that copies `config_updates` from one log into another
    carries the field too: whole-log writes (`eval.py:654`, `:774`),
    `convert_eval_logs` (`src/inspect_ai/log/_convert.py:174`), `inspect
    score` (`src/inspect_ai/_cli/score.py:278`) and crashed-log recovery
    (`src/inspect_ai/log/_recover/_read.py:87`, `_write.py:365`), which
    eval-set resume and selection-worker resume run on a crashed log
    (`src/inspect_ai/_eval/evalset.py:1526`, `:1762`).

  The marker is durable before the first request is reserved, so a log
  left by a crash at any later point carries it. A request refused at step
  1 writes nothing, so a race on an explicit id leaves the task's retries as
  they were.
- **No reuse.** `eval_log_sample_source()` returns the empty source (no
  lookup, no seed, no `prior_checkpoints_dir`) for a marked log, with a
  warning naming it, before its other guards. That one check covers every
  path that reuses a prior log (see "Current behaviour"): the in-run retry,
  `eval_retry()`, eval-set resume in ordinary and legacy rounds, and
  selection-worker resume, for samples and checkpoints alike. A path that
  does reach a marked log reruns the task's own samples from scratch.
- **No in-run retry.** Writing the marker also clears the attempt's
  `TaskCancel.can_retry` and the `will_retry` it registered with the control
  channel (`task/run.py:897`, `:1200`), and the dispatcher's retry decision
  (`src/inspect_ai/_eval/run.py:923`) skips a log that carries it. A retry
  would rerun the task without the samples its creator sent, so it ends
  with its error log: every unresolved future fails with
  `TaskEndedError(log=<that log>)` (the table above), `result()` returns that
  log, and the creator, which holds the search state, decides what to do,
  typically enqueueing a fresh rollout task and sending the outstanding
  samples again. A task whose port delivered nothing (for example, its
  first attempt failed in sandbox setup before any request arrived, or its
  only request was refused) has no marker and is retried as today, and its
  `sent` requests are delivered into the retry as new arrivals.
- **`eval_retry()` refuses a marked log** with `PrerequisiteError`
  ("<log> cannot be retried on its own: task '<task>' received samples
  through a task handle from the task that created it; retry that task
  instead"), checked when the logs are read
  (`src/inspect_ai/_eval/eval.py:1712`), before any recovery writes. With
  no creator, a rerun would lack the samples it was sent and could end
  `success` while missing them. After a restart, the creator's own task
  reruns and enqueues fresh rollout tasks.

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
  running task is waiting on through a handle may run beyond `max_tasks`,
  one extra task per awaited task.

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
- **Replaying port requests into an in-run retry**, admitting recorded
  requests first with their limit budget and keeping dropped requests' IDs
  reserved. A retry reuses results by id, and ids follow the first
  attempt's admission order across source pulls, callbacks and port
  deliveries; nothing short of recording and re-enforcing that whole order
  keeps a callback follow-up from taking a source sample's id and reusing
  its result, and a later run (`eval_retry()`, a resume) has no creator to
  send the requests at all. Never reusing a marked log is exact, and the
  creator can resubmit.
- **Recording that a port delivered only in memory.** Enough to stop the
  in-run retry, but `eval_retry()`, eval-set resume and selection-worker
  resume read the log after the process has gone, and would reuse it.
- **Marking every task that has a port at `log_start`.** No mid-run write,
  but a rollout task whose creator never sent it a sample would lose its
  retries and reuse for nothing; the marker is written only when a request
  is first reserved.
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
- New `inspect_ai.TaskHandle`, `TaskEndedError`, `SampleAbandonedError`.
- `SampleSource` docstrings: samples sent through a handle start while
  `next_samples()` is awaiting, and their callbacks may fire meanwhile;
  everything the source adds during a pull is admitted after the batch it
  returns, as today.
- `max_sandboxes` and `max_samples` docstrings: the headroom a run that
  waits through handles needs.

Behaviour changes:

- Slot lending lets a task that a running task is waiting on start beyond
  `max_tasks` (new API only; no existing eval waits on a handle). A
  supervisor that sets `max_tasks` as a ceiling, such as a selection-mode
  worker's, sees one extra running task per awaited task (decision: Ransom,
  2026-11-03).
- The feeder's owned pull changes nothing for existing sources: only
  samples sent through a handle start while a pull blocks. What a pull
  enqueues, and the follow-ups of samples finishing during it (including
  control-channel reruns, which start during a pull today), are admitted
  after the pull's batch in arrival order, as today, so `--limit`,
  `--sample-id` and ids select the same samples.
- A run whose sandbox or `max_samples` limits leave no headroom for samples
  waiting through handles can hang (new API only); the warning names the
  provider.

Eval logs:

- New header field `EvalLog.handle_samples` (default `False`), and in
  unfinished `.eval` logs the journal member `_journal/handle_samples.json`.
  Logs without it read as `False`, so every existing log behaves as today.
  Producers: `TaskLogger` through both recorders. Consumers:
  `eval_log_sample_source()` (no reuse), `eval_retry()` (refusal), the
  dispatcher's retry decision, the header readers, and the copy sites
  listed under "Logs of tasks that received samples". It is part of
  `EvalLog`, so the viewer's OpenAPI schema and generated TypeScript types
  change (a coordinated ts-mono update); the viewer does not display it.
- An Inspect version without the field ignores it (pydantic drops unknown
  keys), so an older `eval_retry()` or eval-set resume would reuse a marked
  log as today: a marked log must be retried or resumed with a version that
  has the field.
- `eval_retry()` of a marked log raises `PrerequisiteError` instead of
  rerunning it.
- No control-channel or config file changes.

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
- **The marker in a log** only restricts reuse. A log edited to clear it
  is reused as any log is today, which is the same trust the reuse paths
  already place in a log's sample ids; setting it only makes Inspect rerun
  samples instead of reusing them.

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
  - headroom: with `max_sandboxes=1` (stub sandbox provider), a parent
    sample holding the only sandbox awaits its child's `started()`, then
    finishes, and the child's sample then gets the sandbox and runs; a
    handle wait that starts while every permit of the target's provider is
    held logs the warning once per provider, and none when the target uses
    another provider or the provider has no limit.
- `tests/test_eval_retry.py` and `tests/test_eval_set.py` (the marker,
  `.eval` and `.json` each):
  - a rollout task that has received a port request and then errors: its
    log carries `handle_samples` (read from the journal while unfinished,
    from the header when finished, and after `recover_eval_log`); it is not
    retried in-run even with `task_retry_attempts` set; its outstanding
    requests raise `TaskEndedError` with its error log; and the log holds
    each sample under the input it was sent with (the empty-seed A/P/B
    case: source sample A, port request P and P's callback follow-up B keep
    ids 1, 2 and 3);
  - the same log after a simulated crash (process killed after the first
    delivery): the marker is on disk;
  - `eval_retry()` of a marked log raises `PrerequisiteError` before any
    recovery writes; eval-set resume (ordinary and legacy
    `retry_immediate=False` rounds) and selection-worker resume of a marked
    log with a requested task's identifier reuse no sample and copy no
    checkpoint, and the A/P/B ids are not crossed;
  - `convert_eval_logs` between `.eval` and `.json`, `inspect score` and
    `write_eval_log` keep the field; an existing log without it reads as
    `False` and is reused as today;
  - a request refused at delivery (the source reserved its id first),
    followed by an otherwise retryable error: no marker, and the task is
    retried and reuses its completed samples.
- `tests/test_sample_source.py`:
  - port validation: an id equal to a seed id, its int/str equivalent
    (`1` and `"1"`), and a seed id excluded by `--sample-id` or `--limit`
    are refused with `ValueError` while the target is queued and the target
    never sees them; a seed id at an explicit epoch above `epochs` is
    accepted; a duplicate of an earlier request is refused; a request that
    the source's own addition reserved first is refused at delivery, keeps
    no reservation, and the target task completes;
  - abandoned and limit-dropped requests raise `SampleAbandonedError`;
  - a rollout task whose first attempt fails in setup before any request
    arrives is retried and receives its pending requests in the retry;
  - the feeder: a sample sent through a handle while `next_samples()` stays
    blocked runs at once; the blocked pull is cancelled when the task is
    cancelled, when the run is cancelled and when the sample limit is
    exhausted, and a pull's exception still fails the task; with an empty
    seed and `limit=1`, a `next_samples()` that enqueues A and returns `[B]`
    runs B, with the ids assigned today; with one seed and `limit=2`, a
    control-channel rerun of the seed during a blocked pull whose
    `sample_complete` returns A, while the pull later returns B, runs B and
    drops A with today's ids (the existing
    `tests/_control/test_requeue.py` case extended); a port sample's
    follow-up during a blocked pull is held until the pull returns; a handle
    sample arriving while the pull blocks is admitted first and takes the
    limit; port requests observed with a completed pull follow its batch
    and held additions; a pull that
    enqueues a sample and returns `None`, and a pull that returns `None`
    after a handle sample arrived during it, are each followed by another
    pull once those samples have run.

## Implementation plan

This design is step 5 of the plan in
[task-dispatch.md](task-dispatch.md#implementation-plan), one PR, after
step 3 (the run queue and dispatcher) and independent of step 4:

5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, `SamplePort`,
   `PortRequest`, the errors, `Loan`, the `next_tasks()` wait refusal, the
   headroom warning; `enqueue_task()` returns handles), `_eval/task/run.py`
   (port attach, the three delivery steps, the result sites, the feeder's
   owned pull and held buffer, the open port, the attempt `ContextVar`, the
   marker check in `eval_log_sample_source()`), `_eval/task/log.py`
   (`TaskLogger.log_handle_samples()`, the field at `log_finish`),
   `log/_log.py` (`EvalLog.handle_samples`), `log/_recorders/recorder.py`,
   `eval.py` and `json.py` (`log_handle_samples`, the journal member and
   header reads), the copy sites (`log/_convert.py`, `_cli/score.py`,
   `log/_recover/`), `_eval/task/sample_source.py` (docstrings),
   `_eval/run.py` (the retry decision reads the marker, port close on
   attempt end, loans in the dispatcher, the `next_tasks()` scope),
   `_eval/eval.py` (the `eval_retry()` refusal, `max_tasks`, `max_samples`
   and `max_sandboxes` docstrings), `_eval/evalset.py` (docstrings),
   `__init__.py` (exports), `docs/task-source.qmd`, `docs/parallelism.qmd`
   and `docs/reference`. The new `EvalLog` field changes the viewer's
   OpenAPI schema and generated TypeScript types, landed with the
   coordinated ts-mono update the repo's process requires. Tests: those
   above.

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
- Detecting waits that cannot finish because sandbox or `max_samples`
  permits are held by their own waiters; see the wait-for graph under
  "Alternatives considered".
