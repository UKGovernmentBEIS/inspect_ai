# Task dispatch: one queue for every run, and tasks added while it runs

## Overview

Every eval run gets one task queue and one dispatcher. The seed tasks, tasks
added with `enqueue_task()`, tasks a `TaskSource` returns or produces from
`next_tasks()`, and task retries all go through the same queue, and a task
starts as soon as a `max_tasks` slot is free, under `eval()`, `eval_set()`
and eval-set selection-mode workers alike. Every task in the queue, including
one that has not started, is listed by `inspect ctl task list` and can be
cancelled.

Sandbox setup (a provider's `task_init`) moves beside the dispatcher. It runs
once per sandbox configuration per run, in a background worker, while tasks
that need no setup (or whose configuration is already set up) start. A failed
setup ends only the tasks that need it, each with an error log, and their
retries apply. Setup no longer changes the process's working directory or
environment: the task directory and the setup's environment variables reach
the provider through `sandbox_setup()` and are applied by Inspect's
`subprocess()`. The `ContextVar` values a provider binds in `task_init` are
captured per setup and given to that configuration's samples and its
`task_cleanup`, so each cleanup sees the state its own `task_init` produced.

`enqueue_task()` returns one `TaskHandle` per task and model it added. A
handle waits for its task to start or end, cancels or closes it, and, when
the task's dataset is a `SampleSource`, sends it samples and returns each
sample's logged result:

```python
@solver
def search(n_steps: int) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [rollouts] = enqueue_task(rollout_task())
        for _ in range(n_steps):
            [result] = await rollouts.enqueue_sample(propose_next(state))
            update(state, result)
        rollouts.close()
        return state

    return solve
```

## Why

A long-running task that decides what to try next from earlier results
(an adversarial search for misalignment, run for hours as one Inspect task)
needs to start rollout tasks beside itself, send them samples and wait for
each sample's result. It has to work under `eval()`, under `eval_set()`, and
under external supervisors whose workers run `eval_set()` in selection mode,
one process per selected task. Today none of that works end to end:

- Under plain `eval()` and `eval_set()`, a task added with `enqueue_task()`
  starts only after every task of the current batch has finished, even with
  free slots. A task that waits for a task it added waits forever.
  Reproduced on this branch's base with `max_tasks=4`: a solver calls
  `enqueue_task(child)` and waits five seconds for the child's solver to run;
  it never does, and the child runs after the parent's task ends.
- `enqueue_task()` returns `None`, so the caller cannot wait for the task,
  send it samples or cancel it. `enqueue_sample()` reaches only the calling
  task's own `SampleSource`.
- A task waiting to start has no control-channel state, so
  `inspect ctl task cancel` answers 404 "not found".
- Sandbox setup for an added task runs inside the dispatcher loop, so a slow
  image build stops every task from starting, sandbox-free ones included, and
  a setup error fails the whole run.
- Setup changes the process-wide working directory and environment while
  other tasks run. Reproduced on this branch's base: with a `TaskSource` at
  `max_tasks=4`, a running sample that reads `os.getcwd()` while an added
  task's `task_init` awaits sees the added task's directory.
- Providers that keep their sandbox list in `ContextVar`s bound by
  `task_init` (E2B, Modal, Daytona) lose earlier lists when a later
  `task_init` rebinds them, so end-of-run cleanup misses sandboxes; a
  `SampleSource` task with an empty seed fails every later sample.

There are two drivers, so each of these has to be fixed twice.

## Goals and non-goals

Goals:

- One queue and one dispatcher for every run shape the product uses:
  `eval()` with a task list, `eval()` with a `TaskSource`, `eval_set()`
  (including selection mode), `SampleSource` tasks, the control channel.
- An added task starts as soon as a slot is free under `max_tasks`; no
  option selects another policy (decision: Ransom, no `start=` option: one
  always-correct path).
- Ctrl-C behaves the same at every point of every run shape, including while
  a `TaskSource`'s `next_tasks()` is awaited.
- Every task, including one waiting to start, is listed and cancellable
  through the control channel.
- Sandbox setup beside the dispatcher, once per configuration per run; a
  failed setup ends only the tasks that need it, with an error log, and
  retries apply.
- No process-wide working-directory or environment changes during setup;
  per-setup provider state; a compatibility path and an opt-in for
  third-party providers.
- A handle from `enqueue_task()` that waits, cancels, closes, and sends
  samples to a `SampleSource` task and returns their results.

Non-goals:

- `TaskSource` under `eval_set()` or `eval_retry()` (still rejected; see
  [task-source.md](task-source.md#eval_set-support--feasible-but-only-pays-off-for-deterministic-sources)).
- Recording which task added a task, choosing the creator's model for an
  added task under `eval_set()`, and selection-mode handling of added tasks.
  Those are separate changes; "Interactions" below says where this design
  touches them.
- The two companion fixes this design assumes: an abort while a sample is
  failing no longer stops the run (a task's own abort or retry request
  always leaves an `error` log, so the dispatcher's rule that an attempt
  ending with no log or a `cancelled` log was ended by a run-level
  cancellation holds), and `on_task_end` fires for every task whose
  `on_task_start` fired.
- Handles that reach a task in another process (another selection-mode
  worker). A handle is in-process only.
- Making `sample_init` resolve relative paths against the task directory
  (see "Not this design").

## Current behaviour

### Two drivers

`_eval_async_inner` registers a `TaskEnqueuer`
(`src/inspect_ai/_eval/eval.py:1071-1072`) and then takes one of two paths:

- `run_batches` (`eval.py:1157`) for every plain `eval()` / `eval_set()` and
  for a `TaskSource` at `max_tasks == 1`. It calls `eval_run` once per batch,
  then `enqueuer.drain()` (`eval.py:1194`) and, if that is empty,
  `await task_source.next_tasks()` (`eval.py:1196`) outside any `eval_run`.
  An added task therefore waits for the whole batch. At `max_tasks == 1` the
  batch is ordered sequence-major (`eval.py:1162-1173`) and handed to one
  dispatcher, which dispatches in queue order.
- The live path (`eval.py:1202`, a `TaskSource` at `max_tasks > 1` only)
  makes one `eval_run` with a `TaskInjection` (`src/inspect_ai/_eval/run.py:125`)
  that `eval_run` wraps as a `PreparedFeed` (`run.py:145`, `run.py:512-521`).

Both end in `run_task_retry_attempts` (`run.py:711`); a fixed run is an
empty feed (`_empty_feed`, `run.py:560`). Its loop drains the feed
(`run.py:1048`), dispatches up to `effective_max_tasks(parallel)` with
model balancing, and when fully idle awaits `feed.next()` (`run.py:1103`).
`TaskEnqueuer`, `TaskInjection` and `PreparedFeed` are adapters around one
buffer and one blocking pull. `design/task-source.md` gives keeping
sequence-group order at `max_tasks == 1` as the reason live injection is
`TaskSource`-only, but `run_batches` at `max_tasks == 1` already passes the
whole ordered queue to one dispatcher, and that dispatcher appends injected
tasks at the end, so the ordering argument no longer needs two drivers.

`eval_set()` rejects a `TaskSource` (`src/inspect_ai/_eval/loader.py:88-100`,
`src/inspect_ai/_eval/evalset.py:790`, `:867`), so the live path is
unreachable there and in selection-mode workers.

`enqueue_task()` (`src/inspect_ai/_eval/task/enqueue.py`) resolves
synchronously through `_resolve_enqueued_tasks` (`eval.py:1291`) and buffers
into the `TaskEnqueuer` found through a `ContextVar`; it returns `None`.
`TaskSource` callback returns go through the same buffer
(`_enqueue_source_tasks`, `src/inspect_ai/_eval/task/run.py:708`).
`enqueue_sample()` (`src/inspect_ai/_eval/task/sample_source.py:267`) works
only through the calling task's own `SampleEnqueuer` `ContextVar` and returns
nothing.

Under `eval()` the use case can be approximated in user code today: a
`TaskSource` at `max_tasks > 1`, a rollout task whose `SampleSource` reads a
shared queue in `next_samples()`, and a future resolved in its
`sample_complete`. That needs the live path, so it does not work under
`eval_set()` or in selection-mode workers.

### Control channel

`register_eval` is called only when `task_run` starts an attempt
(`task/run.py:1185`). Task directives look the task up with
`latest_eval_for_task` (`src/inspect_ai/_control/eval_state.py:823`), so for
a task still waiting to start `cancel_task` / `drain_task`
(`src/inspect_ai/_control/cancel.py:183`, `:225`) return `None` and the
server answers 404 "task … not found" (`src/inspect_ai/_control/server.py:1011-1034`).
`design/ctl/task-drain.md` ("Out of scope") leaves not-yet-started tasks to
`process pause`. `GET /tasks` (`server.py:769`) lists only registered
attempts.

### Ctrl-C

The dispatcher runs inside `_run_task_screen` (`run.py:817`, `:1320`), which
absorbs a cancellation of the run body so the run returns the logs it has.
On the live path `feed.next()` is awaited inside it. `run_batches` awaits
`next_tasks()` outside any `eval_run`, so a Ctrl-C there raises
`KeyboardInterrupt` and the logs of completed batches are not returned.

### Sandbox setup

`prepare_options` (`run.py:212`) runs inside the dispatcher's feed for added
tasks: it awaits `SandboxManager.start` (`run.py:245`) and then, per task,
builds the `TaskLogger` and awaits `logger.init()` inside
`with chdir(task_run_dir(...))` (`run.py:250`, `:450`).
`SandboxManager._start_sandboxenvs` (`run.py:1238`) serializes setups on
`_init_lock`, suspends the task display (`run.py:1262`) and awaits
`task_init` inside `with chdir(sandboxenv.run_dir), environ_vars(...)`
(`run.py:1278`); `chdir` is `os.chdir` (`src/inspect_ai/_util/path.py:27`)
and `environ_vars` writes `os.environ` (`src/inspect_ai/_util/environ.py:30`).
The same chdir wraps `await task_init_environment(...)`
(`src/inspect_ai/_eval/task/sandbox.py:265`) and each `task_cleanup` at
shutdown (`run.py:1307`). Because these are awaited, every running coroutine
sees the changed directory and environment for the whole call; subprocesses
inherit `os.environ` (`src/inspect_ai/util/_subprocess.py:260`); Docker
resolves `ComposeConfig` build paths and the no-config compose lookup against
`os.getcwd()` (`src/inspect_ai/util/_sandbox/docker/util.py:54`, `:75`).

A setup error in `prepare_options` escapes into the dispatcher's task group
and fails the whole run. A `SampleSource` task's mid-run setup
(`options.startup_sandboxes`, `task/run.py:1827`) fails only that task.

The task's string sandbox config is made absolute against the task
directory at resolution (`loader.py:500-506`), and the config-file probe
looks in the task directory (`loader.py:439-446`), so a relative path reaches
a provider's `task_init` only inside a structured config or through a
provider's own default lookup. `sample_init` runs in the launch directory
(no chdir around `sandboxenv_context`, `sandbox.py:86`), so for a task loaded
from another directory a provider's `task_init` and `sample_init` already
resolve relative paths against different directories.

`task_init_environment` is implemented only by Docker among the providers
surveyed below (`src/inspect_ai/util/_sandbox/docker/docker.py:173`); every
other provider returns `{}`, so `environ_vars` changes nothing for them.

### Provider state

`SandboxManager.open()` (`run.py:1158`, `:497`) binds Docker's
`SandboxLifecycleState` (`src/inspect_ai/util/_sandbox/lifecycle.py`) in
`eval_run`'s context; it is not exported from `inspect_ai.util`. Every other
provider keeps state in its own `ContextVar`s, and all `task_init` and
`task_cleanup` calls run in `eval_run`'s context. Surveyed providers (the
inspect_sandboxes checkout at `bbe0ff4` and the third-party checkouts beside
this repo):

| provider | what `task_init` binds | effect today |
| --- | --- | --- |
| E2B (`e2b/_e2b.py:53-59`) | rebinds `_running_sandboxes` to a new list and `_run_id` | a later `task_init` replaces the list; `task_cleanup` sees only the last one |
| Modal (`modal/_modal.py:78-82`) | rebinds `_running_sandboxes` | same |
| Daytona (`daytona/_daytona.py:57-67`, `:105`) | rebinds the list, run id and `_daytona_client` | same; client of the last config only |
| Podman (`inspect_podman/cleanup.py:22-26`) | rebinds project and compose-file registries | same |
| k8s (`k8s_sandbox/_manager.py:26-37`, `_sandbox_environment.py:170-174`) | get-or-create `HelmReleaseManager` and `PodOpExecutor`; comment says sample contexts copy the task context | shared across configs because all `task_init` run in one context |
| EC2, Proxmox, Vagrant | process-level class state or nothing | unaffected |

With an empty `SampleSource` seed, `task_init` runs in the feeder, a sibling
of the samples, so its bindings are invisible to them: E2B and Modal raise
`LookupError`, Daytona raises "client not initialized". Docker was fixed by
its lifecycle scope.

Relative-path resolution in Python during `task_init`, among those providers:
Daytona's compose loader falls back to `Path.cwd()` for a `ComposeConfig`
(`daytona/_compose.py:42`); Podman's no-config lookup searches `os.getcwd()`
(`inspect_podman/util.py:67`). The others take absolute paths or none.

## Design

### Run shapes and what is refused

The design supports, and its tests cover, the shapes that exist:
`eval()`/`eval_async()` with a task list or a `TaskSource`; `eval_set()`
including selection mode (an external supervisor's worker runs `eval_set()`
in selection mode, one process per selected task); `SampleSource` tasks;
`enqueue_task()` from a solver, scorer, tool or `TaskSource` callback; the
control channel. Everything else is refused with a clear error:

- `TaskSource` passed to `eval_set()`, `eval_retry()` or `score()`: rejected
  as today.
- `TaskHandle.enqueue_sample()` on a task whose dataset is not a
  `SampleSource`: `TypeError` naming the task.
- `TaskHandle.enqueue_sample()` on a handle that was not created by a
  running task (for example from `TaskSource.next_tasks()`), or after
  `close()`: `RuntimeError`.
- `TaskHandle.enqueue_sample()` after the task has ended: `TaskEndedError`.
- `enqueue_task()` outside a running eval or with a mismatched `run_id`:
  `RuntimeError`, as today.

### The run queue

`src/inspect_ai/_eval/task/enqueue.py` replaces `TaskEnqueuer` with a
`RunQueue`, and `src/inspect_ai/_eval/run.py` loses `TaskInjection`,
`PreparedFeed` and `_empty_feed`. `eval.py` loses `run_batch`, `run_batches`
and `inject_next`: `_eval_async_inner` calls `eval_run` exactly once with the
seed, the `TaskSource` (or `None`) and the resolve closure
(`_resolve_enqueued_tasks`, unchanged). `eval_run` creates the run's
`RunQueue`, registers it in the `ContextVar` that `enqueue_task()` reads for
the duration of the run, and runs the dispatcher.

```python
TaskState = Literal["queued", "running", "ended"]

@dataclass(eq=False)
class TaskRecord:
    """One task × model of the run, from queuing until it ends."""
    task_id: str
    resolved: ResolvedTask
    options: TaskRunOptions          # configured at add time; logger built, not yet initialised
    index: int                       # result order: seed first in input order, then arrival order
    creator: TaskAttempt | None      # the running task attempt that called enqueue_task(), if any
    state: TaskState = "queued"
    setups: TaskSetups | None = None # see "Sandbox setup"; None until admitted
    log: EvalLog | None = None       # latest attempt's log; final log once ended
    ended: anyio.Event               # set exactly once, by RunQueue.end()
    port: SamplePort | None = None   # only when the dataset is a SampleSource

class RunQueue:
    run_id: str
    def add(self, resolved: list[ResolvedTask], *, ahead: bool = False) -> list[TaskRecord]
    def find(self, task_id: str) -> TaskRecord | None
    def end(self, record: TaskRecord, log: EvalLog | None) -> None
    wake: Wake                       # rung by every add/end/cancel and by setups as they settle
```

`RunQueue.add` is synchronous. It orders the addition sequence-major (the
order `run_batches` uses at `max_tasks == 1` today), then configures each
task: assigns missing sample ids, checks id uniqueness, applies the eval-level
overrides and the `SampleSource` prerequisite checks, and constructs the
`TaskLogger`. That is today's `prepare_options` body minus its awaits, moved
into a function `configure_task()` in `run.py`. Configuration errors
(`PrerequisiteError`, duplicate ids, unresolvable tasks) therefore raise to
the caller: to `eval()` for the seed, to the `enqueue_task()` caller for an
added task, and into the dispatcher for a `next_tasks()` batch (ending the
run, as today). `enqueue_task()` appends to the end of the queue; a
`next_tasks()` batch goes ahead of any tasks enqueued while `next_tasks()`
was running (`ahead=True`), matching the order `run_batches` produces today.
The set of task names the run has seen, used to resolve `task:id` sample
selectors, moves from `eval_run` into the queue.

Admission is the dispatcher's first step for each new record. It awaits
`ensure_model_controller` and `logger.init()` (as `prepare_options` does
today), requests the record's sandbox setups, registers the record with the
control channel as queued, and grows the display's task count. The seed is
admitted before the dispatch loop starts, and an admission failure raises
from `eval()` as today. For an added task an admission failure ends that
record (its handle raises the error; no log exists) and the run continues.

Records are kept until the run ends so the control channel and handles can
report on them; an ended record drops its `options` (and with them the
dataset) so a finished task's samples are not held until the run ends.

### The dispatcher

`run_task_retry_attempts` becomes `dispatch_tasks(queue, setups, *, parallel,
task_retry_attempts, task_source, debug_errors) -> list[EvalLog]` in
`run.py`. `run_one`, the retry decision, the retry-abandon handling and
model balancing are unchanged. The loop, inside `_run_task_screen` as today:

```
loop:
    admit records added since the last pass
    drop queued records cancelled through the control channel or a handle
    drop pending retries abandoned by a drain/cancel            (as today)
    while not cancelled and in_flight < effective_max_tasks(parallel) + lent:
        record = pick_balanced(startable)        # setups settled, not paused
        if record is None: break
        start run_one(record)
    if cancelled: break
    if any record queued or running, or a setup or admission in progress:
        await queue.wake; continue
    if source_done: break
    more = await task_source.next_tasks() if task_source else None
    if more is None: source_done = True
    else: queue.add(resolve(more), ahead=True)
```

- **Start rule.** A record is startable when its setups have settled
  (succeeded, or one failed) or it needs none. A record whose setup is still
  running does not block the queue: the dispatcher takes the earliest
  startable record among the least-used models. At `max_tasks == 1` this keeps
  sequence grouping among startable tasks; a sandbox-free task can start
  ahead of an earlier task that is waiting for its image.
- **Retries** go to the back of the queue under their original index, as
  today. A retry's setups are requested again under the retry rule in
  "Sandbox setup".
- **`next_tasks()` call point** is unchanged in meaning: it is awaited only
  when nothing is queued, running, being set up or being admitted, so no
  completion can add a task while it blocks. Under plain `eval()` that is the
  same point `run_batches` reaches after a batch; under the live path it is
  the same point as today.
- **End of run.** The loop ends when the source is done and nothing remains,
  or on a run-level cancellation. Records still queued then end with no log
  (their handles' `result()` returns `None`).
- **Ctrl-C.** `next_tasks()` is now awaited inside `_run_task_screen`, so a
  cancellation while it blocks is absorbed like one during a task: the run
  returns the logs it has. A cancellation reaches the run at exactly one
  place for every run shape, so whatever a Ctrl-C during a plain eval's tasks
  does on a backend today, it does at every other point of every run.
- **`debug_errors`** is passed to the dispatcher at every `max_tasks` (today
  only the `max_tasks == 1` path passes it).

`max_tasks` counts running records. One addition, the slot lending in
"Task handles", lets a task that a running task is waiting on start beyond
the limit; see Open question 4.

### Control channel

A queued record is registered in a new process-level registry,
`src/inspect_ai/_control/queued_tasks.py`, keyed by `task_id`, holding the
task name, model, queue position, setup state and a `cancel()` callback into
the `RunQueue`. The record leaves the registry when its first attempt calls
`register_eval`.

- `GET /tasks` (`current_eval_summaries`) appends one row per queued record
  with `status: "queued"`, `attempts: 0`, `samples` totals of zero, and
  `setup: "waiting" | "running" | "failed" | null`. Selector resolution in the
  CLI uses this listing, so `inspect ctl task cancel <id>` resolves a queued
  task by any selector it accepts for running ones.
- `_task_cancel_directive` consults the registry when `latest_eval_for_task`
  returns `None`. A plain cancel or a drain of a queued record ends it with no
  log (`changed: true`, `queued: true` in the result; `dry_run` reports
  without acting). `action=score|error` on a queued record answers 409:
  "task … has not started, so there are no samples for a resolution to apply
  to; use cancel or drain", the same rule the between-attempts case uses.
- Cancelling a queued record drops its setup jobs that have not started and
  that no other queued or running record needs. A job that has started runs
  to the end (interrupting `task_init` can leave resources nothing cleans up).
- `CONTROL_API_VERSION` (`src/inspect_ai/_control/__init__.py:84`) increases
  by one; `inspect ctl task list` shows queued rows.
- Under `eval_set()`, a seed task cancelled while queued has no log, so the
  eval set reads it as not run, exactly as for a task the run never reached.

### Sandbox setup

A new module, `src/inspect_ai/_eval/sandbox_setups.py`, replaces
`SandboxManager`.

```python
SetupKey = TaskSandboxEnvironment     # spec, run_dir, env (unchanged NamedTuple)

class SetupJob:
    key: SetupKey
    attempt: int                       # 1, or the retry attempt that re-ran a failed key
    state: Literal["waiting", "running", "succeeded", "failed"]
    error: BaseException | None
    bindings: Mapping[ContextVar[Any], Any]   # what task_init bound (see "Provider state")
    context: Context                   # task_init's context as it returned, for task_cleanup
    done: anyio.Event

class TaskSetups:                      # one per record
    def settled(self) -> bool
    def failure(self) -> BaseException | None
    def bindings_for(self, sample_id: str | int) -> Mapping[ContextVar[Any], Any]
    async def ensure(self, samples: list[Sample]) -> None   # SampleSource additions

class SandboxSetups:                   # one per run
    def request(self, record: TaskRecord) -> TaskSetups
    def request_retry(self, record: TaskRecord, attempt: int) -> TaskSetups
    def drop_unneeded(self, record: TaskRecord) -> None
    async def shutdown(self) -> None
```

- **Where it runs.** `SandboxSetups` owns a task group that `eval_run` opens
  beside the dispatcher. Key resolution for a record (resolving each selected
  sample's `TaskSandboxEnvironment`, which may call `task_init_environment`)
  runs as one background job per record, bounded by the subprocess limiter as
  today. `task_init` jobs run one at a time, as `_init_lock` serializes them
  today; a provider is never asked to run two `task_init` calls at once.
- **Once per configuration per run.** Jobs are keyed by `SetupKey` across
  all records of the run and kept until the run ends; a record whose keys all
  have succeeded jobs is startable at once. Because the run has one
  `eval_run`, a configuration used by tasks added after the seed is set up
  once, where follow-up batches today set it up again per batch.
- **Order.** Jobs run in the order records request them, except that a job
  someone needs now goes first: a running `SampleSource` task's `ensure()`
  and a task retry. Within each class, first requested first.
- **Failure.** A failed key-resolution or `task_init` marks the job failed.
  Every record needing it becomes startable and its attempt ends at once
  through the normal attempt path: `task_run` receives the failure in
  `TaskRunOptions.setup_error`, registers the attempt, fires
  `on_task_start`, writes an error log whose error is the setup exception,
  and fires `on_task_end`. So the control channel, hooks and the
  dispatcher's retry decision all see an ordinary errored attempt. A
  `KeyboardInterrupt` or `SystemExit` from a setup ends the run.
- **Retry rule.** A record's retry attempt `k` re-runs a failed job only if
  that job failed for an attempt below `k`; otherwise it joins the job (which
  may be a re-run another record's retry already started). However many
  tasks share a broken configuration, it is set up at most once per attempt
  number.
- **`SampleSource` additions.** `startup_sandboxes` becomes
  `options.setups.ensure(samples)`: resolve the added samples' keys, request
  any missing jobs as needed now, and await them. A failure fails that task,
  as today.
- **Cleanup.** `shutdown()` runs each succeeded job's `task_cleanup` once,
  in a task started from that job's captured context, inside the setup scope
  for its directory and environment (below), shielded as today. Jobs that
  failed or never started get no cleanup, as today. On a run-level
  cancellation the setup task group is cancelled first; a `task_init`
  interrupted that way gets no cleanup, as today.
- **Display and output.** The task display is no longer suspended for a
  setup. While a setup job runs, the output of subprocesses that would go to
  the terminal is collected in a bounded buffer (the last 64 KiB) instead.
  Setup start and end are logged at info level and shown in the queued
  rows' `setup` field. On failure, the buffer's tail is logged at warning
  level (shown above the task display and written to the trace file), and the
  task's error log carries the exception only (see "Security"). Open
  question 3 asks whether the seed's setups should instead run before the
  display opens, as today.

### Setup without changing the process's directory or environment

New public API in `inspect_ai.util` (module
`src/inspect_ai/util/_sandbox/setup.py`):

```python
@dataclass(frozen=True)
class SandboxSetup:
    """The task a sandbox provider's task-level call is for."""
    task_dir: str            # the task's directory, absolute
    env: dict[str, str]      # for task_init: what task_init_environment returned

def sandbox_setup() -> SandboxSetup | None:
    """The current setup, inside task_init_environment, task_init and task_cleanup.

    None elsewhere, including in background work such a call started once
    the call has returned.
    """
```

- Inspect sets it (through a `ContextVar` holding a mutable cell that is
  cleared when the call returns, so background tasks copied from the call's
  context stop seeing it) around `task_init_environment`, `task_init` and
  `task_cleanup`, and never calls `os.chdir` or writes `os.environ` for them.
  `chdir` and `environ_vars` are removed from setup and cleanup
  (`SandboxManager`, then its replacement) and from
  `resolve_sandbox_for_task_and_sample`.
- `inspect_ai.util.subprocess()` applies it: the default `cwd` is
  `task_dir` (a relative `cwd` is joined to it), and the child environment is
  `os.environ | setup.env | env`. While a setup job runs, it also routes
  output that would go to the terminal into the job's buffer (internal; not
  part of `SandboxSetup`).
- Docker adopts it: `ComposeProject.create` resolves `ComposeConfig` build
  paths and the no-config compose lookup against `sandbox_setup().task_dir`
  when set, else `os.getcwd()` (so `sample_init` keeps today's behaviour),
  and any Python-side read of a `task_init_environment` variable reads
  `setup.env`. Docker's own subprocesses already go through `subprocess()`.
  For Docker the directory and environment its setup sees are therefore
  exactly today's.
- **Compatibility path for providers that have not adopted it:** their
  subprocesses started through `inspect_ai.util.subprocess()` run in the task
  directory with the setup's environment, as today. Python-level reads of the
  working directory during their `task_init`/`task_cleanup` see the launch
  directory, which is what their `sample_init` already sees. Subprocesses
  they start another way (`asyncio.create_subprocess_exec`, an SDK) run in the
  launch directory; the setup environment is empty for every provider but
  Docker, so only the directory can differ.
- **Opt-in:** a provider reads `sandbox_setup().task_dir` wherever it
  resolves a relative path in Python during `task_init` or `task_cleanup`. A
  provider that must also run on older Inspect versions feature-detects it
  (`getattr(inspect_ai.util, "sandbox_setup", None)`) and falls back to
  `os.getcwd()`, which older versions set to the task directory, so it needs
  no raised dependency floor.
- What remains: one synchronous `with chdir(task_run_dir(task))` block
  around `TaskLogger` construction in `configure_task()` (it reads
  `git_context()` and `cwd_relative_path()` against the task directory). It
  contains no `await`, so no other coroutine observes it; worker threads can,
  as today. `await logger.init()` moves out of it.
- `SandboxEnvironment`'s class docstring and the sandbox extension docs
  state the contract: `task_init` may run while other tasks run, one call at
  a time; it runs in the launch directory and environment; use
  `sandbox_setup()` for the task directory and environment; `ContextVar`
  bindings as described next.

### Provider state per setup

Each `task_init` runs in a task started from the setup chain's context, a
`Context` that starts as a copy of `eval_run`'s (so Docker's lifecycle scope
object is inherited) and that each job's resulting context replaces in turn.
When `task_init` returns, the job records:

- `context`: `copy_context()` taken inside the job task, used to start its
  `task_cleanup`;
- `bindings`: the `ContextVar` values in that context that differ (`is not`)
  from the chain's base, excluding the setup-scope variable Inspect itself
  sets.

Because the chain carries each job's bindings to the next, a later
`task_init` sees what earlier ones bound, as all `task_init` calls in one
`eval_run` context do today. k8s's get-or-create manager and pod-op executor
are therefore shared across configurations, as today.

The bindings reach the code that uses them:

- **Samples.** `sandboxenv_context` (`task/sandbox.py:86`) takes the
  sample's bindings (`options.setups.bindings_for(sample.id)`, recorded when
  the sample's key was resolved) and sets each one in the sample's own task
  context before `sample_init`. `sample_init`, the sample's sandbox calls and
  `sample_cleanup` then see the state their configuration's `task_init`
  produced, whether the setup ran before the task started, in a
  `SampleSource` feeder, or for another task. This fixes the empty-seed
  `LookupError` for E2B, Modal and Daytona.
- **Cleanup.** Each job's `task_cleanup` runs in its own captured context, so
  E2B, Modal, Daytona and Podman clean up the list their own `task_init`
  bound, and sandboxes that an interrupted `sample_cleanup` left behind are
  found. Under k8s the shared manager's first cleanup uninstalls every
  release and the others find nothing, as today.
- Docker's `SandboxLifecycleState` keeps working unchanged: it is a mutated
  object, not a rebinding, so it never appears in `bindings`.

The lifecycle scope stays internal. With captured bindings, the ordinary
pattern (bind `ContextVar`s in `task_init`, read them in `sample_init` and
`task_cleanup`) is correct for every provider without adopting a new API, so
exporting the scope would add a second way to do the same thing. No
inspect_sandboxes change is needed for its state to be cleaned up correctly.

### Task handles

`enqueue_task(tasks, *, run_id=None) -> list[TaskHandle]`: still synchronous,
one handle per task × model it added, in resolution order. Existing callers,
which ignore the `None` returned today, are unaffected. New exports from
`inspect_ai`: `TaskHandle`, `TaskEndedError`, `SampleAbandonedError`.

```python
class TaskHandle:
    task_id: str
    task: str                       # task name
    model: str
    @property
    def state(self) -> Literal["queued", "running", "ended"]: ...
    async def started(self) -> None:
        """Wait until its first attempt starts. Raises TaskEndedError if it ends first."""
    async def result(self) -> EvalLog | None:
        """Wait until it ends; its final log, or None if it never started."""
    def cancel(self) -> None:
        """Abort it, like `inspect ctl task cancel`; a queued task ends with no log."""
    def close(self) -> None:
        """Send no more samples; the task ends once its samples have run."""
    async def enqueue_sample(self, sample: Sample, *, epoch: int | None = None) -> list[EvalSample]:
        """Run `sample` in the task and return its logged runs, one per epoch, in epoch order."""

class TaskEndedError(RuntimeError):
    log: EvalLog | None             # the task's final log, None if it never started

class SampleAbandonedError(RuntimeError):
    sample: Sample
    epoch: int
```

`cancel()` and `close()` are synchronous requests and idempotent; `await
handle.result()` waits for the end. Each record has at most one handle per
`enqueue_task()` call; under a run with two models, `enqueue_task(task)`
returns two handles, each addressing one task × model.

**Sending samples.** A record whose dataset is a `SampleSource` has a
`SamplePort` (in `enqueue.py`). `enqueue_sample()` validates `epoch` as
`enqueue_sample()` does, checks the `(id, epoch)` against the ids the port
has sent and, while an attempt runs, against that attempt's registry (a
duplicate raises `ValueError` to the caller and never reaches the task), and
buffers the sample. While an attempt runs, the port is attached to that
attempt's `SampleEnqueuer`, so the sample starts as soon as `max_samples`
allows; a sample sent while the task is queued is delivered when its first
attempt starts.

Results come from the sites that already report samples to the source
(`task/run.py:1480`, `:1619`, `:3372`): before the source's own
`sample_complete`, the port resolves the matching future with the
`EvalSample` (an errored or operator-cancelled sample is returned, with its
`error`); before `sample_abandoned`, it fails the future with
`SampleAbandonedError`; a sample that `--limit` or `--sample-id` drops at
`add_samples` fails with `SampleAbandonedError` too, so a caller never waits
for a sample that will not run. `enqueue_sample()` returns when every epoch's
future has resolved.

**Keeping the task open.** A `SampleSource` task with an open port does not
end when its source is exhausted: in `feed_samples`, when `next_samples()`
returned `None` and nothing was buffered, the feeder waits for the port
(a new sample or a close) instead of finishing; after a sent sample runs, the
source may be consulted again, as it may today after a late enqueue. The port
closes on `close()`, on `cancel()`, when the task attempt that created the
handle ends, and when the run ends. The creator is the attempt whose context
`enqueue_task()` was called in (a `ContextVar` `_run_task` sets per attempt);
`TaskSource` callbacks fired by a task count as that task. A handle created
outside any task attempt has its port closed from the start. So a creator
that forgets `close()` cannot keep a rollout task open past its own attempt.

**When the task ends with samples outstanding.** If the task attempt ends
and no retry follows (success after close, an abort, a setup failure, an
error with no retries left, a run-level cancellation), every unresolved
future fails with `TaskEndedError(log=<final log>)`. If a retry follows, the
futures stay pending: the port replays every sample it has sent into the
retry attempt, each with the id the first attempt gave it, so completed
samples are reused from the prior log (their re-fired `sample_complete` does
not resolve a future twice) and the rest run again. A cancelled caller's
`enqueue_sample()` raises the cancellation; the sample it sent still runs
and its result is dropped.

**Slot lending.** While a running task's sample awaits `started()`,
`result()` or `enqueue_sample()` on a queued task, that queued task may start
even when `max_tasks` is reached: each such wait lends one start, counted in
`lent`, and the lent task keeps its slot until it ends. Without this, the
use case deadlocks at the default `max_tasks=1` (and in selection-mode
workers, which run one task per process): the creator holds the only slot
while waiting for its rollout. Open question 4 asks whether to lend or to
warn.

### Interactions with related changes

- Recording which task added a task: `TaskRecord.creator` is the attempt
  that change would record.
- Added tasks under `eval_set()` using their creator's model: it changes
  `_resolve_enqueued_tasks`, which this design calls unchanged; with it, a
  call made from a task returns one handle instead of one per run model.
- Selection-mode handling of added tasks: it changes resolution inside the
  selection-mode `eval_set()`; `RunQueue.add` receives whatever that
  resolution returns. With this design an added task runs live inside the
  selection-mode worker that added it.
- The abort fix's dispatcher rule (an attempt with no log or a `cancelled`
  log means a run-level cancellation) applies only to attempts `run_one`
  ran. A record ended while queued, or by an admission failure, never
  reaches `run_one`, so its missing log does not end the run. A setup
  failure always produces an `error` log through the attempt path.

## Alternatives considered

- **User code on today's live path** (a `TaskSource` at `max_tasks > 1`, a
  rollout `SampleSource` reading a shared queue, a future resolved in
  `sample_complete`). Works under `eval()` only, needs the run restructured
  around a `TaskSource`, gives the waiting task no control-channel view of
  the rollout, and carries the setup and provider-state problems above.
- **A `start=` option on `enqueue_task()`** (`"when_free"` or
  `"after_batch"`). Rejected by Ransom: added tasks always start when there
  is room. The batch behaviour has no use that the queue does not serve.
- **The prototype's table recomputed each pass, with a two-stage pipeline
  (set up the first `max_tasks` waiting tasks, then start).** It works, but
  requesting setups at admission and keeping a startable set gives the same
  starts with one less mechanism, and requesting every queued task's setup
  keeps today's "build everything early" behaviour for a long seed instead of
  building only `max_tasks` ahead.
- **The prototype's async `enqueue_task()` returning `list[TaskHandle]`.**
  Async was needed because the prototype resolves sandbox configs at the
  call. Here the call stays synchronous (resolution and configuration are
  synchronous today; key resolution moves to the background), so the return
  value is additive and nobody migrates. See Open question 1.
- **The prototype's run-wide provider state** (every task started later sees
  the latest value of each `ContextVar`, whichever configuration set it).
  Also fixes cleanup, but a task started before a later setup keeps the old
  values while its added samples need the new configuration's, which is why
  the binding is applied per sample from its own job here.
- **Retries in their task's slot.** Changes start order without a reported
  problem; retries keep today's place at the back of the queue.
- **Keeping `os.chdir` for providers that have not adopted
  `sandbox_setup()`, serialized.** Serializing setups does not stop other
  tasks' samples from seeing the directory change (reproduced above), so a
  running sample's relative file reads, `Sample.files` and subprocesses
  would change. Not correct for any run where setups overlap tasks.
- **Running each `task_init` in a thread or a child process** to isolate the
  directory. The directory is process-wide, so a thread does not help; a
  child process loses the provider's in-memory state.
- **Exporting the lifecycle scope** so providers keep state on a shared
  object. Works, but every provider must adopt it, and captured bindings
  make the pattern providers already use correct without a change.
- **Breaking `enqueue_sample()` out as a free function taking a task id.**
  A handle carries the record directly and has a clear owner, which the port
  lifetime rule needs.

## Compatibility and migration

No migration required for eval authors. Third-party sandbox providers that
resolve relative paths in Python during `task_init`/`task_cleanup` should
read `sandbox_setup().task_dir` (see "Opt-in").

Public API (additive):

- `enqueue_task()` returns `list[TaskHandle]` instead of `None`; signature
  and synchronous behaviour unchanged. Its docstring and
  `docs/task-source.qmd` say added tasks always start when there is room.
- New `inspect_ai.TaskHandle`, `TaskEndedError`, `SampleAbandonedError`;
  new `inspect_ai.util.SandboxSetup`, `sandbox_setup()`.
- `inspect_ai.util.subprocess()` applies the setup's directory and
  environment inside a provider's task-level calls.

Control channel: `GET /tasks` gains queued rows (`status: "queued"`, a new
`setup` field), task cancel/drain accept queued tasks, and
`CONTROL_API_VERSION` increases. Older CLIs see the new rows as unknown
status values. No eval log schema, viewer type or config file changes.

Behaviour changes, sorted by whether they can change what an eval computes
(the eval-defaults rule: a change that could shift established trajectories
needs explicit configuration unless today's behaviour is broken):

Scheduling only (which task runs when; every sample runs with the same
inputs, sandbox and model):

- An added task starts when a slot is free under `eval()` and `eval_set()`,
  not after the current batch.
- A configuration used by tasks added after the seed is set up once per run,
  not once per batch, and cleaned up at the end of the run.
- A task that needs no setup, or whose setup is done, starts while other
  setups run; at `max_tasks == 1` it can start ahead of an earlier task that
  waits for an image.
- `next_tasks()` batches go through the same queue; their order relative to
  concurrent `enqueue_task()` calls is today's.
- Slot lending lets a task that a running task is waiting on start beyond
  `max_tasks` (new API only; no existing eval waits on a handle).

Failure reporting (the run's outcome changes only where today it fails):

- A failed setup ends only the tasks that need it, each with an error log and
  its retries; today the run fails. Hooks see `on_task_start`/`on_task_end`
  for those tasks; today they see none and `on_run_end` gets the exception.
- Ctrl-C while `next_tasks()` blocks returns the logs so far instead of
  raising `KeyboardInterrupt` without them.
- An added task whose admission fails ends alone; today the run fails.
- `debug_errors=True` now raises task errors at every `max_tasks` (explicit
  configuration only).
- The seed's setup output no longer streams to the terminal before the task
  display opens (Open question 3).

Could change what an eval computes:

- **`task_init`'s working directory for a third-party provider that has not
  adopted `sandbox_setup()`,** when the task is loaded from a file in another
  directory than the launch directory and the provider resolves a relative
  path in Python (Daytona's and Podman's fallbacks above). Today such a
  provider's `task_init` and `sample_init` already resolve that path against
  different directories, so an eval that depends on the difference prepares
  in `task_init` something its samples do not address by the same path. The
  usual result of the change is a loud "not found", or the two calls now
  agreeing. Docker, subprocesses through `subprocess()`, installed-package
  tasks (whose task directory is the launch directory) and runs launched from
  the task directory are unaffected. This is the reason for Open question 2.
- **Which `ContextVar` values a sample sees.** A sample now sees its own
  configuration's setup state rather than the last setup's. For the surveyed
  providers this changes which registry or run id a sandbox is recorded
  under, not the sandbox itself. A provider whose `task_init` binds a value
  that samples of another configuration are meant to use would see a
  difference; none of the surveyed providers does.
- **`os.environ` during setup** no longer contains `task_init_environment`
  variables; only Docker returns any, and it passes them explicitly.

## Security

- **Samples sent through a handle** may carry model output (the search
  proposes them). They enter the receiving task through the same
  `SampleEnqueuer` path as `enqueue_sample()`: ids are checked for duplicates
  by `(str(id), epoch)` before they reach the task and become log member
  names through the existing path; content is sample input, which the task
  treats as it treats any dataset sample.
- **`task_init_environment` values** come from sample metadata (dataset
  content) interpolated into Docker's environment. Today they are written to
  `os.environ` for the whole setup, visible to every subprocess any running
  sample starts meanwhile. Now they reach only the setup's own subprocesses.
- **Setup output** (image build logs) can contain whatever a build prints.
  Today it goes to the terminal only. The design keeps it out of the eval log
  and the control channel: it is logged (terminal and trace file) on
  failure, and the task's error log carries only the exception.
- **Control channel:** cancelling a queued task uses the existing task
  directive's authorization (the control socket's permissions); the queued
  rows expose task name, model and setup state, which the running rows
  already expose.
- **Captured provider bindings** are the provider's own objects, applied only
  inside samples of the same run and configuration.
- **The task directory** passed to providers and used as subprocess `cwd`
  comes from the task file's location, which the eval author controls, as
  the `chdir` target does today.

## Testing

Unit and integration tests, asyncio and trio (`--runtrio` for every async
test touched), mostly with a stub sandbox provider registered with
`@sandboxenv` whose `task_init` blocks on an `anyio.Event` the test controls,
records `os.getcwd()` and `os.environ`, and binds `ContextVar`s the way E2B
does (a new list per call):

- `tests/util/sandbox/test_sandbox_setup.py` (new; no existing file covers the
  provider contract): `sandbox_setup()` is set in `task_init_environment`,
  `task_init`, `task_cleanup` and cleared in background tasks after return;
  `subprocess()` uses `task_dir` as default and joined `cwd` and merges
  `env`; a concurrently running sample's `os.getcwd()` and `os.environ` are
  unchanged while `task_init` awaits (the reproduction above, inverted);
  per-setup bindings reach `sample_init`, `sample_cleanup` and the matching
  `task_cleanup` for two configurations, an added task's configuration, and
  an empty `SampleSource` seed; a k8s-style get-or-create object is shared
  across configurations.
- `tests/util/sandbox/test_docker_cleanup.py`: Docker under the setup scope
  resolves `ComposeConfig` and no-config compose files against the task
  directory with the launch directory elsewhere (stubbed daemon, as the file
  does today). One `--runslow` real-Docker test builds a Dockerfile task
  loaded from another directory.
- `tests/test_enqueue_task.py`: an added task starts while its creator runs
  under `eval()` and `eval_set()` (the probe above, as a test bounded with
  `fail_after`); under eval-set selection mode in-process; ordering at
  `max_tasks == 1` (sequence-major per addition, `next_tasks()` batch ahead of
  concurrent enqueues); configuration errors raise at the call; admission
  failure ends one task; a setup failure ends only the tasks that need it,
  with error logs and `on_task_start`/`on_task_end`; the retry rule (a shared
  broken key set up at most once per attempt number); a sandbox-free task
  starts while a setup blocks; handles: `started()`, `result()`, `cancel()`
  queued and running, `close()`, `enqueue_sample()` results per epoch,
  abandoned and limit-dropped samples, duplicate ids, the task ending with
  outstanding samples, a retry replaying sent samples with reuse, the port
  closing when the creator attempt ends, refusals listed under "Run shapes",
  and slot lending at `max_tasks=1` (the overview's example as a test).
- `tests/test_task_source.py`: Ctrl-C (cancelling the run) while
  `next_tasks()` blocks returns the completed logs, at `max_tasks` 1 and > 1;
  the existing live-injection test also passes for a plain task list with
  `enqueue_task()`.
- `tests/test_sample_source.py`: a mid-run configuration through
  `setups.ensure()`; a failure fails only that task.
- `tests/test_task_cancel.py` and `tests/_control/test_ctl.py`: queued rows
  in `GET /tasks`; cancel and drain of a queued task (no log, handle result
  `None`, its unshared waiting setups dropped); `score`/`error` answer 409;
  `dry_run`.
- inspect_sandboxes: a test per provider that two configurations and an
  added task's configuration clean up every sandbox, run against an Inspect
  build with step 2; it needs the providers' API keys, so it runs where their
  live tests already run.

The `--runslow` Docker tests in `tests/util/sandbox` run in the PR CI
`slow-tests` job on PRs that touch `src/inspect_ai/util/_sandbox/**` or
`tests/util/sandbox/**` (steps 1, 2 and 4 do); everything else runs in the
normal test job. The inspect_sandboxes tests need provider API keys and run
where that repo's live tests run.

## Implementation plan

Each step is one PR and leaves `main` correct. The order differs from
"dispatcher first" because unifying the dispatcher alone would extend two of
today's live-path bugs to plain evals: `task_init`'s process-wide `chdir`
would overlap running tasks, and a second configuration's `task_init` would
rebind provider state inside the single `eval_run` (today each follow-up
batch has its own `eval_run` and cleans up its own state).

1. **Setup without process-wide directory or environment changes.**
   `src/inspect_ai/util/_sandbox/setup.py` (new), `util/__init__.py` (export),
   `util/_subprocess.py`, `util/_sandbox/docker/util.py` and `config.py`,
   `_eval/run.py` (`SandboxManager` uses the scope; `await logger.init()` out
   of the `chdir` block), `_eval/task/sandbox.py:265`,
   `util/_sandbox/environment.py` docstrings, `docs/extensions-sandboxes.qmd`.
   Tests: `tests/util/sandbox/test_sandbox_setup.py`, Docker tests. Needs Open
   question 2 answered.
2. **Provider state per setup.** `_eval/run.py` (`SandboxManager` runs each
   `task_init` in the chained context and records bindings, contexts and the
   per-sample key map), `_eval/task/sandbox.py` (`sandboxenv_context` applies
   bindings), `_eval/task/run.py` (passes them). Tests: bindings across
   configurations, empty seed, cleanup per configuration. Fixes the E2B,
   Modal and Daytona leaks and `LookupError` with no inspect_sandboxes
   release. Independent of step 1.
3. **One queue, one dispatcher, queued tasks in the control channel.**
   `_eval/task/enqueue.py` (`RunQueue`, `TaskRecord`; `enqueue_task()` still
   returns `None`), `_eval/run.py` (`configure_task()`, `dispatch_tasks()`,
   `eval_run` owns the queue; `TaskInjection`/`PreparedFeed`/`_empty_feed`
   removed), `_eval/eval.py` (one `eval_run` call), `_eval/task/run.py`
   (`_enqueue_source_tasks`), `_control/queued_tasks.py` (new),
   `_control/cancel.py`, `_control/state.py`, `_control/__init__.py`,
   `_cli/ctl/_task.py`; `docs/task-source.qmd`; `design/task-source.md`
   ("Live injection"), `design/ctl/task-drain.md` ("Out of scope"),
   `design/sample-source.md` (the `SandboxManager` notes). Setups still run at
   admission inside the dispatcher, as the live path does today. Tests:
   `tests/test_enqueue_task.py`, `tests/test_task_source.py`,
   `tests/test_task_cancel.py`, `tests/_control/test_ctl.py`. Needs steps 1
   and 2.
4. **Setup beside the dispatcher.** `_eval/sandbox_setups.py` (new; replaces
   `SandboxManager`), `_eval/run.py` (start rule, `setup_error`),
   `_eval/task/run.py` (setup-failure attempt path, `setups.ensure()`),
   `util/_subprocess.py` (output collection), `_control/queued_tasks.py`
   (`setup` field). Tests: setup failure, retry rule, sandbox-free start,
   output collection, cancel dropping waiting jobs. Needs step 3 and Open
   question 3 answered.
5. **Task handles.** `_eval/task/enqueue.py` (`TaskHandle`, `SamplePort`,
   errors), `_eval/task/run.py` (port attach, result sites, feeder open
   while the port is open, attempt `ContextVar`), `_eval/run.py` (port close
   on attempt end, slot lending), `__init__.py` (exports),
   `docs/task-source.qmd` and `docs/reference`. Tests: handle tests above.
   Needs step 3 and Open questions 1 and 4 answered; independent of step 4.
6. **inspect_sandboxes adopts `sandbox_setup()`.** Daytona's `ComposeConfig`
   fallback (`daytona/_compose.py:42`) and any other relative-path
   resolution in `task_init` the audit finds, feature-detected so the
   dependency floor does not move; the cleanup tests above; a release. The
   only step that needs an inspect_sandboxes release, and only for the
   working-directory change in step 1; steps 1-5 do not wait for it.

## Open questions

1. **How should `enqueue_task()` hand back handles?**
   Options: (a) keep it synchronous and return `list[TaskHandle]`, one per
   task × model (additive; callers ignoring the result are unaffected);
   (b) make it async and return `list[TaskHandle]` (the prototype; breaking:
   every existing call must be awaited, and calls from synchronous code such
   as a `TaskSource` callback's helpers break); (c) keep `enqueue_task()` as
   is and add `start_task(task, *, model=None) -> TaskHandle` for exactly one
   task × model (additive, single handle, two functions to document).
   Recommendation: (a). Nothing in the handle needs an await at the call, so
   there is no reason to break callers, and one function covers both uses.
   Confidence: high.

2. **Where should a provider that has not adopted `sandbox_setup()` resolve
   relative paths in Python during `task_init`/`task_cleanup`?**
   Options: (a) the launch directory, with subprocesses through
   `subprocess()` still in the task directory and `sandbox_setup()` as the
   opt-in (one rule; affects only third-party providers that resolve relative
   paths in Python for tasks loaded from another directory, whose
   `sample_init` already uses the launch directory; the prototype's survey
   of 30 providers found about five that resolve such a path); (b) the
   launch directory for setups that overlap running tasks, but keep the
   process-wide `chdir` for the seed's setups by running them before dispatch
   starts (exactly today's behaviour for every established eval; two
   policies, and the seed gives up starting sandbox-free tasks early; ties to
   question 3); (c) keep `chdir` everywhere (unsafe: running samples see the
   change).
   Recommendation: (a). It is the only rule that is correct when setups
   overlap tasks, Docker keeps its exact behaviour by adopting the accessor,
   and the affected providers are few and get a feature-detectable fix.
   Confidence: low, because under the eval-defaults rule (b) is the
   conservative answer for established evals, and the choice is about how
   much compatibility to buy with a second policy.

3. **Should the seed's setups run beside the dispatcher, or before it as
   today?**
   Options: (a) beside, like every other setup (sandbox-free seed tasks start
   at once; a broken seed configuration ends only its tasks; build output is
   collected rather than streamed, and shown on failure); (b) before
   dispatch, with output streamed to the terminal and the first failure
   raising from `eval()` (today's start-up experience and fail-fast; the
   prototype does this; a second policy).
   Recommendation: (a), one rule for every setup. Users lose the live build
   output at start-up; the failure tail and the queued rows' `setup` state
   replace it.
   Confidence: low, because it changes the start-up experience every
   sandboxed eval sees.

4. **What happens when a running task waits on a task it added and every
   slot is taken (the default `max_tasks=1`, and selection-mode workers)?**
   Options: (a) slot lending: the waited-on task starts beyond `max_tasks`
   (one start per waiting sample; the use case works with no configuration);
   (b) no lending, and the handle logs a warning once when it waits on a
   queued task while every slot is held, naming `max_tasks` and
   `inspect ctl config --max-tasks` (simpler; the use case needs
   `max_tasks >= 2`, which a selection-mode worker may not allow); (c) tasks
   added by a running task do not count toward `max_tasks` (simplest rule,
   but unbounded: a task that adds one task per sample runs them all at
   once).
   Recommendation: (a). It is bounded by the number of waits, applies only
   to the new handle API, and without it the use case deadlocks by default.
   Confidence: low, because it is a new exception to what `max_tasks` means.

## Not this design

- Making `sample_init` see the task directory (`sandbox_setup()` or
  otherwise). Today a provider's `task_init` and `sample_init` resolve
  relative paths against different directories for a task loaded from
  another directory; this design leaves `sample_init` unchanged.
- Removing the last synchronous `chdir` around `TaskLogger` construction by
  passing the directory to `git_context()` and `cwd_relative_path()`. It is
  visible to worker threads only.
- Pausing or resuming a queued task by task id (`ctl task pause`); queued
  tasks are only listed and cancelled here.
- A setup-progress row in the task display.
- A caller's own cancellation of `eval_async()` (for example
  `anyio.fail_after`) being absorbed by `_run_task_screen` like a Ctrl-C;
  this design keeps today's absorption point and behaviour.
- A seed task whose log cannot be initialized still fails the run, as today.
- Handles across processes (a task in another selection-mode worker).
- `TaskSource` under `eval_set()` (see `design/task-source.md`).
