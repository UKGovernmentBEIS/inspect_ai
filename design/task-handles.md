# Task handles: waiting on tasks added during a run and sending them samples

## Overview

`enqueue_task()` returns one `TaskHandle` per task and model it added. A
handle waits for its task to start or end and cancels it. Called from a
running task with `send_samples=True`, for a task whose dataset is a
`SampleSource`, it also sends that task samples and returns each sample's
logged result, keeping the task open until the handle is closed or its
creator's attempt ends. A task that a running task is waiting on borrows a
slot when every slot is taken, so a search that drives a rollout task works
at the default `max_tasks=1`:

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
- Mid-run log state is recorded the way `inspect ctl config` retunes are:
  `.eval` appends a journal member and flushes it at once
  (`src/inspect_ai/log/_recorders/eval.py:281`, `:1133`), header reads of an
  unfinished `.eval` log read the journal (`_read_header_async`, `:2135`;
  `_read_header`, `:2266`), and `log_finish` consolidates it into the header
  (`:365`). The deprecated `.json` recorder keeps it on the in-memory log
  (`src/inspect_ai/log/_recorders/json.py:203`) and writes the whole file
  on `flush` without fsync (`:292-296`), through a snapshot write that
  skips the file on `PermissionError` (`src/inspect_ai/log/_recorders/file.py:33-38`,
  `:60-70`), so a mid-run `.json` write is not guaranteed to reach disk.
  Its streaming header reader lists header keys one by one (`json.py:613`).
  Only these two recorders exist (`src/inspect_ai/log/_recorders/create.py:7`).
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

- that it is called from a running task attempt, which becomes the
  creator: otherwise `RuntimeError` (the port would close at once);
- that the dataset is a `SampleSource`: otherwise `TypeError` naming the
  task;
- that the resolved task carries no prior state
  (`ResolvedTask.sample_source is None`): a `PreviousTask`, or a
  `ResolvedTask` with a `sample_source`, raises `ValueError` ("tasks that
  receive samples through a handle must start fresh; pass the Task"). Ids
  of samples sent through a handle depend on when they arrive, so a prior
  lookup keyed on id and epoch could hand one sample another's result (see
  "Logs of tasks that received samples"). Those inputs stay supported with
  `send_samples=False`;
- that the run logs in the `.eval` format (the log format `eval()` or
  `eval_set()` resolved for its loggers): with the deprecated `.json`
  format it raises `ValueError` ("send_samples=True needs the .eval log
  format: a task that receives samples records that in its log, durably,
  before each first delivery, and only .eval logs are written that way")
  (decision: Ransom, 2026-11-03). See "Logs of tasks that received
  samples" for why the record must be durable; the `enqueue_task()`
  docstring and the handle docs in `docs/task-source.qmd` say the same.

Nothing is enqueued when a check fails.

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

- `enqueue_task(..., send_samples=True)` outside a running task attempt
  (for example in `TaskSource.next_tasks()`), for a task whose dataset is
  not a `SampleSource`, for a task with prior state, or in a run that logs
  in the `.json` format: the errors under "The handle API".
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
None`. Every later step (the check at the call, the delivery checks, the
marker write and `add_samples`) uses that copy. The runner's allocator
assigns an automatic id by rebinding the top-level `id` field of the sample
it reserves (`reserve_runs`, `task/run.py:1710-1717`), and nothing else it
does changes the sample object, so a shallow copy is the depth needed: the
id lands on the copy, and the nested input, metadata and files stay shared
and read-only, as a source's own samples share them with its dataset
today. So the caller's object never gains an id, and one anonymous
`Sample` sent to two tasks, or to two task × model handles, gets an
automatic id in each target independently; neither target sees the
other's id as an explicit one, and a target suspended at the marker write
(step 2 of "Delivery") cannot have its request's id changed under it.

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
`enqueue_sample()` returns when every epoch's future has resolved; the
request is then `done` and leaves the port (see "Retention").

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
when the task attempt that created the handle ends, and when the run ends.
So a creator that forgets `close()` cannot keep a rollout task open past
its own attempt, and a task added without `send_samples` ends when its
source is done, as today.

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
  once per attempt, at step 2 of "Delivery", through a new
  `Recorder.log_handle_samples(eval)`:
  - `.eval` (`EvalRecorder`) appends `_journal/handle_samples.json` and
    flushes the log at once, as a config update is journalled and flushed
    (see "Current behaviour"), but with fsync, which a config update's
    flush skips; a failed write raises, and nothing is delivered. The
    header readers of an unfinished log (`_read_header_async`,
    `_read_header`) and `log_init`'s re-read of an existing destination
    (`eval.py:181`) read the member, and `log_finish` writes the field
    into `header.json`.
  - `.json` is never written with the marker: its mid-run writes are not
    durable (see "Current behaviour"), so `send_samples=True` refuses a run
    that logs in that format (see "The handle API"), and the base
    `Recorder.log_handle_samples` raises `NotImplementedError` naming the
    format for any recorder that reaches it anyway. A `.json` log carries
    the field only when converted from a marked `.eval` log, so
    `_read_header_streaming` reads the key with the others (`json.py:613`)
    and the reuse and `eval_retry()` rules below apply to such a log too.
  - Every site that copies `config_updates` from one log into another
    carries the field too. Whole-log writes (`eval.py:654`, `:774`) write
    the header and samples in one step and copy it with the header. Three
    paths instead stream samples into a destination and flush it before
    they finish, carrying `config_updates` only at `log_finish`:
    `convert_eval_logs` (`src/inspect_ai/log/_convert.py:150`, `:158-159`,
    `:174`), streamed `inspect score` (`src/inspect_ai/_cli/score.py:249`,
    `:253-254`, `:278`), and crashed-log recovery, both its buffer-sample
    and its crashed-`.eval` sample paths
    (`src/inspect_ai/log/_recover/_write.py:146-147`, `:178`, `:253`,
    `:365`), whose source it reads with the marker
    (`log/_recover/_read.py:87`) and which eval-set resume and
    selection-worker resume run on a crashed log
    (`src/inspect_ai/_eval/evalset.py:1526`, `:1762`). An interrupted copy
    must not leave a readable destination holding a marked log's samples
    without the marker, so these paths set it at the start, not at the
    end. `Recorder.log_start(eval, plan, *, handle_samples: bool = False)`
    gains the keyword, and each of the three passes its source header's
    `handle_samples` to it. That is copy initialization, separate from
    the live `log_handle_samples()` and allowed for both formats:
    - `.eval`: with `handle_samples=True`, `log_start` writes
      `_journal/handle_samples.json` right after `start.json`, under the
      same lock, before any sample can be buffered. A sample becomes
      visible only through a flush, and every flush writes the members
      already in the archive, so the first flush that publishes a copied
      sample publishes the marker with it, readable by the unfinished-log
      header readers above.
    - `.json`: `log_start` sets the field on the in-memory log, so every
      snapshot `flush` writes holds the field with the samples it holds.
    - `log_finish` keeps the field set at start (the `.eval` journal member
      is consolidated into `header.json`, the `.json` in-memory log already
      has it); no copy path can clear it.
  - The errored `EvalLog` that `_run_task` builds when a log write, a
    retry's checkpoint startup copy or a task-completion callback escapes
    the attempt (`src/inspect_ai/_eval/run.py:682-687`) sets
    `handle_samples` from the attempt's `TaskLogger`, so the log the
    dispatcher, `result()` and `eval()` see is marked whenever the attempt
    was.

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
- **Never counted complete.** `list_latest_eval_logs()` puts a marked log
  among the incomplete logs whatever its status, checked with
  `invalidated` (`src/inspect_ai/_eval/evalset.py:1858-1861`) and so after
  any resolving recovery has finalized it, so `eval_set()` never returns a
  marked log as an existing success; it reruns the task through a
  `PreviousTask`, which reuses nothing (above). The deprecated
  `retryable_eval_logs()` (`src/inspect_ai/log/_retry.py`) lists logs for
  `eval_retry()`, which refuses a marked one.
- **Steward does the same** (a companion change in `inspect_steward`).
  `LogAttempt` gains `handle_samples: bool`, read from the header in
  `_attempt()`; `_incomplete_reason()` returns a new
  `IncompleteReason.HANDLE_SAMPLES` for a marked attempt before its other
  checks, so a marked log is never counted complete and never imported
  from the reuse store (`_store/match.py` skips it and logs why);
  `CACHE_VERSION` goes up because `LogAttempt` changes shape, so attempts
  cached without the field are re-read. Steward then runs the task again,
  and if it resumes from the marked log, Inspect's own guard reuses
  nothing. Steward's `inspect-ai` floor rises to the first release with
  `EvalLog.handle_samples`, since it reads the field.
- **No in-run retry.** `TaskLogger.handle_samples` is set in memory when
  step 2 of "Delivery" begins, before the write is awaited, and is never
  cleared within the attempt; `reinit()` for a retry starts a new log with
  it unset. Setting it also clears the attempt's `TaskCancel.can_retry` and
  the `will_retry` it registered with the control channel
  (`task/run.py:897`, `:1200`). The dispatcher's retry decision
  (`src/inspect_ai/_eval/run.py:921-923`) reads that flag from
  `options.logger`, before `reinit()`, as well as the returned log's field,
  so a fallback log, a failed marker write or a failed final write cannot
  turn it back into a retry. A retry would rerun the task without the samples its creator sent, so it ends
  with its error log: every unresolved future fails with
  `TaskEndedError(log=<that log>)` (the table above), `result()` returns that
  log, and the creator, which holds the search state, decides what to do,
  typically enqueueing a fresh rollout task and sending the outstanding
  samples again. A task whose port delivered nothing (for example, its
  first attempt failed in sandbox setup before any request arrived, or its
  only request was refused) has no marker and is retried, and its `sent`
  requests are delivered into the retry as new arrivals.
- **A retry of a task that can receive samples reuses nothing.** An unmarked attempt
  can still have completed samples of its own before it failed. If the retry
  reused them, a port request delivered before the source regenerates one
  could take its id: with an empty seed, source sample A completes as id 1,
  the attempt fails, and in the retry an anonymous request P arrives first,
  is given id 1, and the prior lookup (`task/run.py:1403-1424`) returns A's
  result for it; checkpoints copied at the retry's start (`task/run.py:957`,
  `:989-998`) would likewise restore A's state into P. A closed port does
  not prevent this: requests accepted before `close()`, or whose caller was
  cancelled, are still delivered. So when the dispatcher queues an in-run
  retry of a record that has a port, open or closed, it gives the retry the
  empty sample source instead of the one built at
  `src/inspect_ai/_eval/run.py:979` or the previous attempt's
  (`:989-995`): no lookup, no seed, no checkpoint copy. The retry reruns
  the task's own samples from scratch, and ids are assigned in its own
  admission order. A record without a port is retried with reuse as today.
  The first attempt starts clean too: `send_samples=True` refuses a task
  with prior state (see "The handle API").
- **`eval_retry()` refuses a marked log** with `PrerequisiteError`
  ("<log> cannot be retried on its own: task '<task>' received samples
  through a task handle from the task that created it; retry that task
  instead"), checked when the logs are read
  (`src/inspect_ai/_eval/eval.py:1712`), before any recovery writes. With
  no creator, a rerun would lack the samples it was sent and could end
  `success` while missing them. After a restart, the creator's own task
  reruns and enqueues fresh rollout tasks.
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
- **Refusing the first delivery into a retry that reuses prior state.**
  Also exact, but the creator's requests would fail for the whole of that
  attempt, and it would have to enqueue a fresh task anyway; rerunning the
  retry's own samples keeps the task usable.
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

- `enqueue_task()` returns `list[TaskHandle]` instead of `None` and gains
  the keyword-only `send_samples=False`; synchronous behaviour unchanged.
  Without `send_samples` an added task has no port and ends when its
  source is done, as today, whatever the caller does with the handles.
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
  Producers: `TaskLogger` through the `.eval` recorder, and conversion of
  a marked `.eval` log to `.json`. Consumers:
  `eval_log_sample_source()` (no reuse), `eval_retry()` (refusal), the
  dispatcher's retry decision, the header readers, and the copy sites
  listed under "Logs of tasks that received samples". It is part of
  `EvalLog`, so the viewer's OpenAPI schema and generated TypeScript types
  change (a coordinated ts-mono update); the viewer does not display it.
- An Inspect version without the field ignores it (pydantic drops unknown
  keys), so an older `eval_retry()` or eval-set resume would reuse a marked
  log as today: a marked log must be retried or resumed with a version that
  has the field.
- Steward reads the field through the companion change (step 6 of the
  plan). A Steward release without it would count a marked successful log
  complete and could import one from its reuse store, so runs that use
  `send_samples=True` under Steward need a Steward release with the change;
  its `inspect-ai` floor rises with it.
- `eval_retry()` of a marked log raises `PrerequisiteError` instead of
  rerunning it.
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
- `tests/test_eval_retry.py` and `tests/test_eval_set.py` (the marker, in
  `.eval` logs):
  - a rollout task that has received a port request and then errors: its
    log carries `handle_samples` (read from the journal while unfinished,
    from the header when finished, and after `recover_eval_log`); it is not
    retried in-run even with `task_retry_attempts` set; its outstanding
    requests raise `TaskEndedError` with its error log; and the log holds
    each sample under the input it was sent with (the empty-seed A/P/B
    case: source sample A, port request P and P's callback follow-up B keep
    ids 1, 2 and 3);
  - the same log after a simulated crash (process killed after the first
    delivery): the marker is on disk; a failing marker write (stub
    filesystem) fails the task and delivers nothing;
  - `eval_retry()` of a marked log raises `PrerequisiteError` before any
    recovery writes; eval-set resume (ordinary and legacy
    `retry_immediate=False` rounds) and selection-worker resume of a marked
    log with a requested task's identifier reuse no sample and copy no
    checkpoint, and the A/P/B ids are not crossed;
  - `convert_eval_logs` from a marked `.eval` log to `.json` and back,
    `inspect score` and `write_eval_log` keep the field, and `eval_retry()`
    refuses the converted `.json` log;
  - interrupted copies: conversion to `.eval` and to `.json`, streamed
    `inspect score`, and recovery through its buffer-sample and its
    crashed-`.eval` sample paths, each copying a marked log and cancelled
    (or failing in a stub recorder) after its first intermediate flush and
    before `log_finish`: the destination's header read (`header_only`)
    reports `handle_samples`, recovering the destination keeps it,
    `eval_retry()` refuses the destination, and eval-set resume of it
    reuses no sample; the same copies of an unmarked log leave the field
    `False` and are reused as today; under `eval_set(log_dir_allow_dirty=True)`,
    a parent that adds a rollout task, sends it a sample and then fails is
    retried in a legacy round (`retry_immediate=False`) and in a second
    invocation over the same directory: the rollout logs are ignored, the
    parent reruns and adds fresh rollout tasks, and nothing is reused from
    the rollout logs; without the flag, the existing prerequisite error is
    raised and names the option; `eval_set()` over a log directory
    holding a marked successful log of a requested empty-seed task (so
    `planned == 0`), and over a marked crashed log that recovery under
    `incomplete_action="error"` finalizes as `success`, reruns the task
    rather than returning the log as an existing success, and reuses none
    of its samples; an existing log without it reads as
    `False` and is reused as today;
  - a request refused at delivery (the source reserved its id first),
    followed by an otherwise retryable error: no marker; the task is
    retried, and since it has a port the retry reuses nothing;
  - the fallback log: after a delivery, a failing final log write (stub
    recorder) and a raising task-completion callback each end the task
    without a retry, and the log the dispatcher and `result()` return has
    `handle_samples` set;
  - a retry with an open port: with an empty seed, source sample A
    completes as id 1, the attempt errors before any delivery, and in the
    retry an anonymous request P arrives before the source regenerates A;
    P's `EvalSample` has P's input and its own output, A reruns, and nothing
    is reused, with sample logging on and off and with checkpointing on (no
    checkpoint is copied into the retry); the same with the port closed,
    and with the caller of a pending request cancelled, after P is sent and
    before the failure (P is still delivered into the retry with its own
    result, and no checkpoint of A is restored into it); a task added
    without `send_samples` that fails the same way reuses A as today.
- `tests/test_enqueue_task.py` (existing callers and the new keyword):
  - a parent under a `TaskSource` at `max_tasks=2` enqueues a finite
    `SampleSource` child, ignores the return value and awaits the child's
    `task_complete` event: the child ends when its source is done and the
    parent completes (bounded with `fail_after`);
  - `send_samples=True` outside a running attempt, for a non-`SampleSource`
    dataset, for a `PreviousTask`, a list of them, a mixed
    `PreviousTask`/`ResolvedTask` list, and a `ResolvedTask` with a
    `sample_source` each raise and enqueue nothing; the same inputs without
    `send_samples` still run as today (the existing `ResolvedTask` case at
    `tests/test_enqueue_task.py:147`), and `enqueue_sample()` on their
    handles raises `RuntimeError`;
  - with `send_samples=True` and a fresh task, P sent before the source's
    first pull gets its own id and result (initial admission), as in the
    retry case above;
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
    id; the caller's object still has `id is None`; with B's delivery held
    at the marker write while A's delivery assigns its id, B's request is
    admitted with B's own id and B does not fail; sending one object with
    an explicit id that clashes is still refused with `ValueError`.
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
    pull once those samples have run; with `limit=1` and a pull blocked, a
    port sample P whose `sample_complete` returns P at epoch 2, whose own
    callback returns P at epoch 3, runs all three epochs before the pull is
    cancelled and the task ends.

## Implementation plan

This design is step 5 of the plan in
[task-dispatch.md](task-dispatch.md#implementation-plan), one PR, after
step 3 (the run queue and dispatcher) and independent of step 4, plus a
companion change in Steward (step 6):

5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, `SamplePort`,
   `PortRequest`, the errors, `Loan`, the `next_tasks()` wait refusal, the
   headroom warning; `enqueue_task()` returns handles and checks
   `send_samples=True`), `_eval/task/run.py`
   (port attach, the three delivery steps, the result sites, the feeder's
   owned pull and held buffer, the open port, the attempt `ContextVar`, the
   marker check in `eval_log_sample_source()`), `_eval/task/log.py`
   (`TaskLogger.log_handle_samples()`, the field at `log_finish`),
   `log/_log.py` (`EvalLog.handle_samples`), `log/_recorders/recorder.py`
   and `eval.py` (`log_handle_samples`, `log_start(..., handle_samples=)`,
   the journal member and header reads), `json.py` (`log_start(...,
   handle_samples=)`, the streaming header key), the copy sites
   (`log/_convert.py`, `_cli/score.py`, `log/_recover/`, each passing its
   source's marker to `log_start`), `_eval/task/sample_source.py` (docstrings),
   `_eval/run.py` (the retry decision reads the logger's flag and the
   marker, the fallback log carries it, an open-port retry gets the empty
   sample source, port close on attempt end, `SamplePort.stop()` from the
   `cancel_task` callback for drain, score and error, loans in the
   dispatcher, the `next_tasks()` scope),
   `_eval/eval.py` (the `eval_retry()` refusal, `max_tasks`, `max_samples`
   and `max_sandboxes` docstrings), `_eval/evalset.py` (a marked log is
   incomplete in `list_latest_eval_logs()`; docstrings),
   `__init__.py` (exports), `docs/task-source.qmd`, `docs/parallelism.qmd`
   and `docs/reference`. The new `EvalLog` field changes the viewer's
   OpenAPI schema and generated TypeScript types, landed with the
   coordinated ts-mono update the repo's process requires. Tests: those
   above.
6. **Steward companion** (`inspect_steward`, after the Inspect release that
   adds `EvalLog.handle_samples`): `_evalset/observe.py` (`LogAttempt.handle_samples`,
   read in `_attempt()`; `IncompleteReason.HANDLE_SAMPLES`, checked first in
   `_incomplete_reason()`), `_store/match.py` (the skipped candidate's log
   line), `_evalset/cache.py` (`CACHE_VERSION` raised), `pyproject.toml`
   (the `inspect-ai` floor). Tests in its suite: an observed marked success
   log of an empty-seed manifest task is incomplete with that reason; a
   marked log in the reuse store is not imported; a cache written by the
   previous version is discarded and the marked attempt re-read.

## Open questions

None. Ransom decided (2026-11-03) that `enqueue_task()` stays synchronous
and returns `list[TaskHandle]`, that sending samples is enabled by the
keyword-only `send_samples=False` and refused for `.json` logs ("The handle
API"), and that a task a running task waits on borrows a slot through a
loan specific to it ("Slot lending").

## Not this design

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
