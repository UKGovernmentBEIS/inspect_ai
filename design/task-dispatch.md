# Task dispatch: one queue for every run, and tasks added while it runs

## Overview

Every eval run gets one task queue and one dispatcher. Seed tasks, tasks
added with `enqueue_task()`, tasks a `TaskSource` returns, and task retries
all go through the same queue, and a task starts as soon as a `max_tasks`
slot is free, under `eval()`, `eval_set()` and eval-set selection-mode
workers alike. Adding a task checks its configuration and sample selection
at once, so a mistake raises to the caller, and the task's log file is
created only when the task starts. Every task in the queue, including one
that has not started, is listed by `inspect ctl task list` and can be
cancelled.

Sandbox setup (a provider's `task_init`) runs beside the dispatcher, once per
sandbox configuration per run, while tasks that need no setup start. A failed
setup ends only the tasks that need it, each with an error log, and their
retries apply. Setup no longer changes the process's working directory or
environment: Inspect makes relative config paths absolute against the task
directory before any provider sees them, and the `ContextVar` values a
provider binds in `task_init` are captured per setup, so each sample and each
`task_cleanup` sees the state its own configuration's `task_init` produced.

Handles that let a running task wait on the tasks it adds and send them
samples are a separate design on this queue:
[task-handles.md](task-handles.md).

## Behaviour changes

Sorted by whether they can change what an eval computes (the eval-defaults
rule: a change that could shift established trajectories needs explicit
configuration unless today's behaviour is broken).

Scheduling only (which task runs when; every sample runs with the same inputs,
sandbox and model):

- A task added with `enqueue_task()` starts when a slot is free under `eval()`
  and `eval_set()`, not after the current batch.
- A sandbox configuration used by added tasks is set up once per run, not
  once per batch, and cleaned up at the end of the run.
- A task that needs no setup, or whose setup is done, starts while other
  setups run; at `max_tasks == 1` it can start ahead of an earlier task that
  waits for an image.
- A task's log file, temporary file and sample buffer database are created
  when the task starts, not when the run starts, so a long queue holds none.

API:

- `enqueue_task()` becomes `async` and returns one handle per task × model
  ([task-handles.md](task-handles.md#the-handle-api)). An un-awaited call adds
  nothing; Python warns "coroutine 'enqueue_task' was never awaited" and type
  checkers flag it. Callers add `await`. The only callers today are inspect_ai's
  own tests and `docs/task-source.qmd`, all inside async solvers; no satellite
  repository (inspect_swarm, inspect_flow, inspect_steward, inspect_swe and
  the others checked out beside this repo) calls it.
- `enqueue_task()` raises at the call for every configuration or selection
  error, and nothing of that call is added.
- `task:id` sample selectors resolve when a task is added, against the task
  names of the run so far and of that call: tasks whose selectors name each
  other must be added in the same `enqueue_task()` call.

Failure reporting (the run's outcome changes only where today it fails or
hides a problem):

- A failed setup ends only the tasks that need it, each with an error log and
  its retries, and with `on_task_start`/`on_task_end`; today the run fails.
  This includes the seed's setups.
- A task whose log cannot be initialised ends with an error log and is
  retried, like a failed `log_start()`; today a seed task's failure raises
  from `eval()`.
- Ctrl-C while `TaskSource.next_tasks()` blocks returns the logs so far
  instead of raising `KeyboardInterrupt` without them.
- Adding a task id already in the run raises `ValueError`.
- An eval set or selection-mode worker whose seed task was cancelled while
  queued reports failure and names the task.
- `debug_errors=True` raises task errors at every `max_tasks`.
- A sandbox provider that has not declared that its setup runs in the launch
  directory logs a warning when it sets up a task outside it.
- The control channel lists queued tasks and cancels or drains them.

Could change what an eval computes:

- **Python-level relative paths in a third-party provider's `task_init`**
  resolve against the launch directory, the directory its `sample_init`
  already uses (see "Setup does not change the process's directory or
  environment" for the boundary per provider).
- **A sample's relative config path** (a compose file, a Dockerfile, or a
  `ComposeConfig` build context) that exists under the task directory is used
  from the task directory by `task_init` and `sample_init` alike. Today
  `task_init` used the task directory's file (through the `chdir`) and
  `sample_init` the launch directory's, so a run launched from a directory
  holding a file of the same name built one image and ran samples on another.
- **Which `ContextVar` values a sample sees**: its own configuration's setup
  state rather than the last setup's.
- **`os.environ` during setup** no longer holds `task_init_environment`
  values; only Docker returns any, and it receives them directly.

## Why

A long-running task that decides what to try next from earlier results (an
adversarial search for misalignment, run for hours as one Inspect task)
needs to start rollout tasks beside itself, send them samples and wait for
each sample's result, under `eval()`, under `eval_set()`, and under external
supervisors whose workers run `eval_set()` in selection mode. Today:

- Under plain `eval()` and `eval_set()`, a task added with `enqueue_task()`
  starts only after every task of the current batch has finished, even with
  free slots, so a task that waits for a task it added waits forever.
- A task waiting to start has no control-channel state, so
  `inspect ctl task cancel` answers 404 "not found".
- Sandbox setup for an added task runs inside the dispatcher loop, so a slow
  image build stops every task from starting, sandbox-free ones included, and
  a setup error fails the whole run.
- Setup changes the process-wide working directory and environment while
  other tasks run: a running sample that reads `os.getcwd()` while an added
  task's `task_init` awaits sees the added task's directory.
- Providers that keep their sandbox list in `ContextVar`s bound by
  `task_init` (E2B, Modal, Daytona) lose earlier lists when a later
  `task_init` rebinds them, so end-of-run cleanup misses sandboxes, and a
  `SampleSource` task with an empty seed fails every later sample.

There are two drivers, so each of these has to be fixed twice.

## Goals and non-goals

Goals:

- One queue and one dispatcher for `eval()` with a task list or a
  `TaskSource`, `eval_set()` (including selection mode), `SampleSource`
  tasks and the control channel.
- An added task starts as soon as a slot is free; no option selects another
  policy (decision: Ransom, no `start=` option: one always-correct path).
- Ctrl-C behaves the same at every point of every run shape.
- Every task, including one waiting to start, is listed and cancellable
  through the control channel.
- Sandbox setup beside the dispatcher, once per configuration per run; a
  failed setup ends only the tasks that need it.
- No process-wide working-directory or environment change anywhere in a run;
  per-setup provider state; a compatibility path for third-party providers.

Non-goals:

- `TaskSource` under `eval_set()` or `eval_retry()` (still rejected; see
  [task-source.md](task-source.md#eval_set-support--feasible-but-only-pays-off-for-deterministic-sources)).
- Recording which task added a task, choosing the creator's model for an
  added task under `eval_set()`, and selection-mode handling of added tasks
  ("Interactions" says where this design touches them).
- Streaming setup output to the task display (see "Not this design").
- Task handles; see [task-handles.md](task-handles.md).

## Current behaviour

### Two drivers

`_eval_async_inner` (`src/inspect_ai/_eval/eval.py`) registers a
`TaskEnqueuer` (`src/inspect_ai/_eval/task/enqueue.py`) and takes one of two
paths:

- `run_batches`, for every plain `eval()`/`eval_set()` and for a
  `TaskSource` at `max_tasks == 1`, calls `run_batch` (one `eval_run` per
  batch), then drains the enqueuer and, if that is empty, awaits
  `task_source.next_tasks()` outside any `eval_run`. An added task waits for
  the whole batch. At `max_tasks == 1` the batch is ordered sequence-major
  and handed to one dispatcher.
- The live path, a `TaskSource` at `max_tasks > 1` only, makes one
  `eval_run` fed through `TaskInjection` (constructed in `eval.py` with
  `inject_next`) and wrapped by `eval_run` as a `PreparedFeed`
  (`src/inspect_ai/_eval/run.py`).

Both end in `run_task_retry_attempts` (`run.py`); a fixed run is an empty
feed (`_empty_feed`). Its loop drains the feed, dispatches up to
`effective_max_tasks(parallel)` with model balancing (`pick_balanced`), and
when idle awaits `feed.next()`. `run_one` runs an attempt through
`_run_task`, decides on a retry, awaits `logger.reinit()` and appends the
retry at the back of `pending`. `eval_set()` rejects a `TaskSource`
(`src/inspect_ai/_eval/loader.py`), so the live path is unreachable there.

`enqueue_task()` resolves synchronously through `_resolve_enqueued_tasks`
(`eval.py`, once per run model) and buffers into the `TaskEnqueuer`; it
returns `None`. `TaskSource` callback returns go through the same buffer
(`_enqueue_source_tasks`, `src/inspect_ai/_eval/task/run.py`).

Each batch is prepared by `prepare_options` inside `eval_run`: it assigns
missing sample ids, awaits `ensure_model_controller` for each task's model
(so `inspect ctl config` can retune `max_connections` during long image
pulls), awaits `SandboxManager.start`, and for each task, inside
`with chdir(task_run_dir(task))`, resolves its `task:id` selectors against
every name seen so far, builds the `TaskLogger` (whose constructor reads
`git_context()` and `cwd_relative_path()` against the process directory)
and awaits `logger.init()`, which allocates the recorder entry, its
temporary file and the sample buffer database. `TaskLogger.reinit()` ends
by calling `init()` again.

### Control channel

`register_eval` is called only when `task_run` starts an attempt, just
before samples run. Task directives look the task up with
`latest_eval_for_task` (`src/inspect_ai/_control/eval_state.py`), so for a
task still waiting to start, `_task_cancel_directive`
(`src/inspect_ai/_control/cancel.py`) finds nothing and the server answers
404. `design/ctl/task-drain.md` leaves not-yet-started tasks to
`process pause`. A cancel of a task between attempts writes the per-task
stamp `abandon_task_retry(task_id)`, which `task_run` checks before
registering (`task_retry_abandoned`) and the dispatcher reads to drop a
pending retry. The stamp lasts until `reset_run_registries()`, at the end of
a standalone `eval()` or of the whole `eval_set()`.

### Ctrl-C

The dispatcher runs inside `_run_task_screen`, which absorbs a cancellation
of the run body so the run returns the logs it has. On the live path
`feed.next()` is awaited inside it. `run_batches` awaits `next_tasks()`
outside any `eval_run`, so a Ctrl-C there raises `KeyboardInterrupt`.

### Sandbox setup and the working directory

`SandboxManager._start_sandboxenvs` serializes setups on `_init_lock`,
suspends the task display (`display().suspend_task_app()`) and awaits
`task_init` inside `with chdir(sandboxenv.run_dir), environ_vars(...)`.
`resolve_sandbox_for_task_and_sample` (`src/inspect_ai/_eval/task/sandbox.py`)
awaits `task_init_environment` inside the same `chdir`, and
`SandboxManager.shutdown` awaits each `task_cleanup` inside it. `chdir` is
`os.chdir` and `environ_vars` writes `os.environ`, and both wrap awaits, so
every running coroutine sees the changed directory and environment.
`sample_init` runs with no `chdir`, in the launch directory. A setup error in
`prepare_options` fails the whole run; a `SampleSource` task's mid-run setup
(`startup_sandboxes`, `SandboxManager.start_for_samples`) fails only that
task.

Paths reach providers in three ways:

- The task's string config is joined to the task directory by
  `resolve_task_sandbox` (`loader.py`) whenever it is not absolute, so a
  string config that is not a file path (inline JSON, for example) is
  rewritten to `<task dir>/<string>`. The config-file probe looks in the task
  directory.
- A sample's own config is forwarded unchanged by `resolve_sandbox`, so a
  relative compose file or Dockerfile (documented in `docs/sandboxing.qmd`)
  or a `ComposeConfig` with a relative `build` context reaches the provider
  relative. Docker resolves it against the process directory
  (`ComposeProject.create` in `util/_sandbox/docker/util.py`, which bases a
  `ComposeConfig`'s generated file on `os.getcwd()`; `resolve_config_environment`
  in `docker/docker.py`): the task directory in `task_init`, the launch
  directory in `sample_init`.
- A provider's own lookups. Surveyed (inspect_sandboxes, inspect-podman,
  inspect_proxmox_sandbox, inspect_k8s_sandbox, inspect_ec2_sandbox,
  inspect_vagrant_sandbox checkouts beside this repo):
  - E2B warms its template cache in `task_init` from a `ComposeConfig`, whose
    relative build contexts fall back to `Path.cwd()`; its `sample_init`
    resolves the same config in the launch directory. Daytona and Modal
    resolve them only in `sample_init`.
  - Podman, for a missing config, looks for a compose file in `os.getcwd()`
    and writes its generated compose file there, in `task_init` and again in
    `sample_init`; it passes absolute paths to its subprocesses.
  - Proxmox reads `PROXMOX_CONFIG_FILE` in `task_init`; its other readers of
    that variable (`default_concurrency()`, `cli_cleanup()`) already resolve
    it against the launch directory.
  - k8s, EC2 and Vagrant take absolute paths or none.

`task_init_environment` is implemented only by Docker; it returns the
`SAMPLE_METADATA_*` variables a compose file interpolates, which
`environ_vars` exposes to Docker's `compose build` and `compose pull`.

### Provider state

`SandboxManager.open()` binds Docker's `SandboxLifecycleState`
(`src/inspect_ai/util/_sandbox/lifecycle.py`) in `eval_run`'s context. Every
other provider keeps state in its own `ContextVar`s, and every `task_init`
and `task_cleanup` runs in `eval_run`'s context:

| provider | what `task_init` binds | effect today |
| --- | --- | --- |
| E2B, Modal | rebinds `_running_sandboxes` (E2B also `_run_id`) | a later `task_init` replaces the list; `task_cleanup` sees only the last one |
| Daytona | rebinds the list, run id and `_daytona_client` | same; client of the last configuration only |
| Podman | rebinds project and compose-file registries | same |
| k8s | get-or-create `HelmReleaseManager` and `PodOpExecutor` | shared across configurations |
| Proxmox, EC2, Vagrant | class state or nothing | unaffected |

With an empty `SampleSource` seed, `task_init` runs in the feeder, a sibling
of the samples, so its bindings are invisible to them: E2B and Modal raise
`LookupError`, Daytona raises "client not initialized".

## Design

### Invariants

The design keeps these, and each section below says how:

1. **One run, one queue, one dispatcher.** `_eval_async_inner` calls
   `eval_run` once; it owns one `RunQueue` and runs `dispatch_tasks`.
2. **Every task × model is one record, and every record ends exactly once**
   (`RunQueue.end`), with the log its last attempt returned, or `None`.
3. **A record is visible to the control channel from the moment it is
   added**: in the queued registry until one of its attempts first calls
   `register_eval`, then through its `EvalState`, as today.
4. **A task's logger owns a recorder entry only while an attempt runs.**
   `task_run` calls `logger.init()` when the attempt starts; `log_finish` or
   `discard()` releases it when the attempt ends. A queued record or a
   pending retry holds nothing to release.
5. **Only the run's event loop changes the queue, in synchronous steps**, so
   it needs no lock.
6. **Once dispatch ends, nothing more starts.** In one synchronous step the
   queue closes (no additions, no retries published) and every record not yet
   started ends, before any attempt is cancelled or joined.
7. **Nothing in a run calls `os.chdir` or writes `os.environ`.**
8. **Each `task_cleanup` sees what its own `task_init` bound**, and a sample
   sees its configuration's bindings unless it bound its own.
9. **A setup failure ends only the tasks that need it**, through an ordinary
   errored attempt.

### Run shapes and what is refused

Supported, and covered by the tests: `eval()`/`eval_async()` with a task
list or a `TaskSource`; `eval_set()` including selection mode;
`SampleSource` tasks; `enqueue_task()` from a solver, scorer, tool, hook or
`TaskSource` callback; the control channel. Refused with a clear error:

- `TaskSource` passed to `eval_set()`, `eval_retry()` or `score()`: as today.
- `enqueue_task()` outside a running eval or with a mismatched `run_id`:
  `RuntimeError`, as today.
- `enqueue_task()` after the run's dispatch has ended (from a task that
  outlived it and kept its context): `RuntimeError`, before anything is
  resolved.
- `enqueue_task()` from another event loop (a worker thread that copied the
  run's context and runs the coroutine with `anyio.run()`): `RuntimeError`.
  `_require_run_loop(queue)` compares `anyio.lowlevel.current_token()` with
  the token the queue recorded at creation. A worker calls it through
  `anyio.from_thread.run()`, which runs it on the run's loop.
- Adding a task id the run already holds: `ValueError` ("Task ids").
- Handle misuse: see
  [task-handles.md](task-handles.md#run-shapes-and-what-is-refused).

### The run queue

`src/inspect_ai/_eval/task/enqueue.py` replaces `TaskEnqueuer` with
`RunQueue`; `run.py` loses `TaskInjection`, `PreparedFeed`, `_empty_feed`
and `prepare_options`; `eval.py` loses `run_batch`, `run_batches` and
`inject_next`. `eval_run` creates the queue, binds it in the `ContextVar`
that `enqueue_task()` reads, adds the seed and runs the dispatcher.

```python
TaskPhase = Literal["queued", "starting", "running", "retry_pending", "ended"]

@dataclass(eq=False)
class TaskRecord:
    task_id: str
    task: str                         # task name; kept after the record ends
    model: str
    index: int                        # result order: seed first, then arrival
    options: TaskRunOptions | None    # configured at add, logger constructed; released at end
    phase: TaskPhase = "queued"
    registered: bool = False          # an attempt has called register_eval
    setups: TaskSetups | None = None  # see "Sandbox setup"; None under run_samples=False
    log: EvalLog | None = None        # the log run_one stored; the final log once ended
    ended: anyio.Event

class RunQueue:
    run_id: str
    closed: bool
    wake: Wake                        # rung by every phase change, addition and setup result
    def add(self, resolved: list[ResolvedTask], *, ahead: bool = False) -> list[TaskRecord]
    def find(self, task_id: str) -> TaskRecord | None
    def cancel(self, record: TaskRecord) -> None
    def end(self, record: TaskRecord, log: EvalLog | None) -> None
    def close(self) -> None           # idempotent
    def end_unstarted(self) -> None   # ends every record no attempt is running for
    def end_all(self) -> None         # ends every record not yet ended
```

[task-handles.md](task-handles.md#what-the-handles-add-to-the-run-queue)
adds a sample channel, a loan and a creator to the record, and a loan step
to the dispatcher.

#### Adding tasks

`RunQueue.add` is synchronous. It first calls `_require_run_loop` and
raises `RuntimeError` if `closed`. Then, for the whole batch before
anything is committed:

- **Task ids.** An id that a record of this run already holds, or that
  repeats in the batch, raises `ValueError` ("task id '<id>' (task '<task>')
  is already in this run: a ResolvedTask or PreviousTask keeps its id, so it
  can be added once, in a run with one model; pass the Task to run it once
  per model"). A `Task` resolves to a new id per model, but a `ResolvedTask`
  or `PreviousTask` keeps its id and `_resolve_enqueued_tasks` resolves its
  input once per run model, so today such copies run under one id that the
  control channel folds into one. The seed paths that pass resolved or
  previous tasks (`eval_set()` rounds, selection workers, `eval_retry()`)
  resolve each once, so this never fires for them.
- **Configuration**, in `configure_task()` (`run.py`): today's
  `prepare_options` body without its awaits. It assigns missing seed sample
  ids, checks id uniqueness, applies the eval-level overrides, runs the
  `SampleSource` prerequisite checks, resolves the task's `task:id`
  selectors (`resolve_task_sample_ids`) against the run's task names plus
  this batch's, and constructs the `TaskLogger` with the task directory
  passed explicitly (`TaskLogger(task_dir=...)`, which `git_context()` and
  `cwd_relative_path()` take as their directory), so no `chdir` is needed.
  The constructor slices the dataset with the resolved selection, so a
  selection error (a literal id the dataset lacks) raises here.

Any error raises to the caller and nothing of the batch is added. Then, in
the same step, it commits: adds the names to the run's set, orders the
batch sequence-major (the order `run_batches` uses at `max_tasks == 1`),
creates each record in `queued` at the end of the queue (or ahead of tasks
enqueued during the current `next_tasks()` call, with `ahead=True`),
registers it with the control channel, requests its sandbox setups (unless
`run_samples=False`), grows the display's task count and rings `wake`.

Callers: `eval_run` for the seed (errors raise from `eval()`, as today); the
async `enqueue_task()`, after resolving its argument with
`_resolve_enqueued_tasks` (errors raise to its caller); `_enqueue_source_tasks`
for `TaskSource` callback returns; and the dispatcher for a `next_tasks()`
batch, with `ahead=True` (errors end the run, as today).

Selection is resolved at the call because it is synchronous, so its errors
reach the caller. The cost is the batch boundary: today a whole buffered
batch's names were known before any selector resolved, so a creator that
added A, then B, with `sample_id=["parent:1", "B:1"]`, ran no sample of A.
Now A resolves first and reads `B:1` as a literal id of A, which raises at
A's call unless A has such a sample. Tasks whose selectors name each other
are added in one call. The seed is one call, so its selectors resolve as
today; a `next_tasks()` batch is one call too. Sandbox key resolution, which
can start one `docker compose config` subprocess per sample, stays in the
background setup jobs.

#### Phases and cancelling

| from | event | to | made by |
| --- | --- | --- | --- |
| (none) | `add` | `queued` | `RunQueue.add` |
| `queued` | cancel, or dispatch ends | `ended`, no log | `RunQueue.cancel`; `end_unstarted()` |
| `queued`, `retry_pending` | `run_one` begins for the entry the dispatcher picked | `starting` | `run_one`'s first statement |
| `starting` | an attempt calls `register_eval` | `running` | `on_registered`, called by `task_run` right after `register_eval` |
| `starting`, `running` | `run_one` publishes a retry | `retry_pending` | `run_one` |
| `retry_pending` | the dispatcher drops the abandoned retry, or dispatch ends | `ended`, with the stored log | dispatcher; `end_unstarted()` |
| `starting`, `running` | `run_one` returns or raises with no retry | `ended`, with the log `run_one` stored (`None` if none) | `run_one` |
| any but `ended` | the attempt group has exited | `ended`, with the stored log | `end_all()` |

`starting` means `run_one` is running for the record and the current attempt
has not registered: it is initialising the log, seeding prior samples and
writing the header. The move into `starting` is `run_one`'s first statement,
not the dispatcher's pick: if the record ended between the pick and that
statement (a cancel, or dispatch ending), `run_one` gives the slot back and
returns. So a record is never left in `starting` by an attempt that never ran
(an AnyIO task cancelled before its first step runs none of its body).
`registered` is set at the first `register_eval` and kept, so a record whose
retry is starting after a registered attempt is `starting` but already out of
the queued registry. Handles and the control channel show `queued` until the
first registration, then the `EvalState`.

`RunQueue.cancel(record)`, used by the control channel's cancel or drain of a
queued row and by a handle's `cancel()`, is synchronous:

- `ended`: nothing.
- `registered`: today's control-channel task cancel, `cancel_task(task_id)`
  (`_control/cancel.py`), which aborts a running attempt or abandons a
  pending retry, exactly as `inspect ctl task cancel` does today.
- `queued` (never registered): `RunQueue.end(record, None)`. Nothing was
  initialised, so nothing is discarded.
- `starting` or `retry_pending`, never registered: today's stamp,
  `abandon_task_retry(task_id)`, which rings the dispatcher. A pending retry
  is dropped by the dispatcher and the record ends with its stored log; an
  attempt starting stops at `task_run`'s stamp checks before `register_eval`
  (the last runs with no `await` before it), `run_one` discards whatever
  `init()` allocated, and the record ends with the log an earlier attempt
  stored, or none. An attempt that returns a log before it reaches a check (a
  failed `init()` or startup write, or `run_samples=False`'s `started` log)
  ends the record with it, and the stamp stops any retry.

The stamp is per task id and lasts until `reset_run_registries()`; ids are
unique in a run, and a legacy `eval_set()` round that reruns a task reuses
its id, which "Queued cancels under `eval_set()`" keeps out of later rounds,
so the stamp reaches only this record's task.

`RunQueue.end` sets `ended`, removes the record from the queue and the queued
registry, rings `wake`, and releases `options` and `setups` (and what the
handles attach): `ResolvedTask.task` holds the dataset and the configured
task is a shallow copy of it, so both references go for a finished task's
samples to be freed. The record keeps its identity, `log` and `ended`.

#### A task's log starts with its attempt

`task_run` awaits `logger.init()` as its first startup step, after its first
retry-abandon check and before prior-log seeding and `log_start()`.
`TaskLogger.reinit()`, which `run_one` awaits before publishing a retry,
still detaches the old attempt's live state and releases an unfinished
attempt's recorder entry (keeping its destination), but no longer calls
`init()`: the retry's own `task_run` does. `TaskLogger.discard()` on a logger
that holds no entry does nothing.

A failure in `init()` escapes `task_run` like a failed `log_start()` flush,
and `_run_task` already turns that into an error log
(`unwritten_task_log`, built from the logger's eval spec, which exists from
construction), which `run_one` retries. `record_inherited_config_updates`
stays inside `init()`, so a retry's log records the run's process-scoped
`ctl` retunes as today.

So the run's end, a queued cancel and a dropped retry release nothing, and a
seed task whose log cannot be initialised ends with an error log instead of
raising from `eval()`.

### The dispatcher

`run_task_retry_attempts` becomes `dispatch_tasks(queue, setups, *, parallel,
task_retry_attempts, task_source, debug_errors) -> list[EvalLog]`, with
today's `run_one`, retry decision, retry-abandon handling and model
balancing:

```
async with _run_task_screen(...):              # absorbs a cancellation of the run body, as today
    async with setups.open():                  # setup jobs run here; the seed's start now
        async with attempt task group:         # today's group: run_one and the throughput reporter
            try:
                loop:
                    drop pending retries whose task carries the abandon stamp
                        (each ends its record with its stored log)
                    while not cancelled and in_flight < effective_max_tasks(parallel):
                        entry = pick_balanced(startable entries)
                        if entry is None: break
                        start run_one(entry)
                    [loaned starts: task-handles.md]
                    if cancelled: break
                    if an entry is pending, an attempt is running or a setup job is running:
                        await queue.wake; continue
                    if source_done: break
                    more = await task_source.next_tasks() if task_source else None
                    if not more: source_done = True            # None or [], as today
                    else: queue.add(resolve(more), ahead=True)
            finally:
                queue.close(); queue.end_unstarted()           # synchronous, before the group joins
```

- **Start rule.** An entry is a record in `queued` or a pending retry. It is
  startable when its setups have settled (succeeded or failed) or it needs
  none, and no control-channel pause holds it. An entry whose setup is still
  running does not block the queue: the dispatcher takes the earliest
  startable entry among the least-used models, so at `max_tasks == 1`
  sequence grouping holds among startable tasks.
- **Retries** are today's: `run_one` stores the attempt's log on the record,
  awaits `reinit()`, requests the retry's setups and appends the retry at the
  back of the queue under the record's index. A cancel or drain while it
  waits abandons it through the stamp.
- **No retry once closed.** `run_one` reads `queue.closed` where it decides
  on a retry (beside today's abandon-stamp check) and again in the
  synchronous step that appends the retry after `reinit()` returns. Closed
  means no retry, as for an abandoned one: the record ends with this
  attempt's log. The retry's logger was never initialised, so nothing is
  discarded. This matters only after a latched cancellation, when attempts
  still running can finish after the queue closed.
- **`next_tasks()`** is awaited only when nothing is pending, running or
  being set up, as today, and now inside `_run_task_screen`, so a Ctrl-C
  while it blocks is absorbed like one during a task.
- **End of dispatch.** The `finally` runs inside the attempt group's body,
  so it runs before the group cancels or joins any attempt, on every exit:
  the source done, a latched cancellation (an attempt returned no log or a
  `cancelled` log), an exception (a `debug_errors` error from an attempt), or
  a cancellation from outside (Ctrl-C, a caller's scope). `close()` refuses
  every later addition and retry. `end_unstarted()` ends every `queued`
  record with no log and every `retry_pending` record with its stored log,
  which settles every handle wait on them at once, including waits in
  shielded code such as `Task.cleanup` and hooks of cancelled samples, which
  would otherwise hold the group's join open. Records in `starting` or
  `running` are left to `run_one`.
- **After the group exits**, `eval_run`'s `finally` calls `queue.close()` and
  `queue.end_all()`, which ends any record still open with its stored log:
  one whose `run_one` raised, and every record when a failure came before
  the loop (the task screen failing to open). Then it shuts down the setups
  and cleans up S3 sessions, as today's `finally` does, and resets the
  `ContextVar`.
- **`debug_errors`** is passed to the dispatcher at every `max_tasks`.

`max_tasks` counts attempts in flight;
[task-handles.md](task-handles.md#slot-lending) adds loans for tasks that a
running task waits on.

### Control channel

`RunQueue.add` registers each record in a process-level registry,
`src/inspect_ai/_control/queued_tasks.py`, keyed by `task_id`, holding the
record and a `cancel()` callback into `RunQueue.cancel`. The record leaves it
when it ends, or in `on_registered`, with no `await` between that and
`register_eval`, so a directive always finds the task in one of the two.

The registry takes precedence over `EvalState` history for the same id: under
`eval_set(retry_immediate=False)` each round is its own `eval()` and keeps the
task id, and `EvalState`s persist across those calls.

- `GET /tasks` adds a row for a queued record with `status: "queued"`,
  `attempts: 0` and zero sample totals, or overlays the existing row of a
  task with history (a legacy retry round), setting `status: "queued"` and
  keeping its history. Both carry `setup: "waiting" | "running" | "failed" |
  null`. CLI selectors resolve queued tasks like running ones.
- `_task_cancel_directive` looks in the registry first. A cancel or drain of
  a queued record follows `RunQueue.cancel` and returns `changed: true`,
  `task_queued: true`, `in_flight: 0` (and `queued: 0` for a drain, whose
  `queued` is a sample count), plus `retry_abandoned: true` when an earlier
  unregistered attempt stored a log; `dry_run` reports without acting. The
  CLI renders such a result as "queued task … cancelled before it started;
  no samples ran". `action=score|error` answers 409 ("task … has not
  started, so there are no samples for a resolution to apply to; use cancel
  or drain").
- `CONTROL_API_VERSION` increases by one.

#### Queued cancels under `eval_set()`

A seed task cancelled while queued ends with no log, but `eval_set()` judges
success from the logs it gets back (`try_eval()`, `all_evals_succeeded()`),
which would report "Completed all tasks". A task cancelled in `starting` can
instead return a log written before a stamp check, and a legacy round would
rerun it under its still-stamped id. So:

- `_control/queued_tasks.py` keeps the ids of records that a cancel or drain
  reached before any attempt registered (the tasks *cancelled before
  starting*), whatever log they ended with, exposed as
  `queued_cancelled_task_ids()` and cleared by `reset_run_registries()`, so
  it lives as long as the stamp.
- `run_eval` (`evalset.py`), after `eval()` returns, finds the requested
  tasks with no log. Those in the set were cancelled; any other was still
  queued when the run was cancelled, so `run_eval` raises
  `KeyboardInterrupt`, as it does today for a `cancelled` log.
- The eval set keeps the cancelled tasks by `task_identifier()` for the rest
  of the invocation and leaves them out of later legacy rounds, so a retry
  never undoes a cancel or reruns a stamped id. (Legacy rounds and selection
  workers run with `task_retry_attempts=0`, so every stamp a legacy round can
  carry comes from a cancel before starting.) A task left out that ended with
  a log keeps the log `list_latest_eval_logs()` selects for it.
- The retry predicate and the final result use `all_evals_succeeded` over the
  logs of the other tasks, and the result is failure when any task was
  cancelled before starting; the closing message names them. Selection mode
  returns `False` in the same case.

### Sandbox setup beside the dispatcher

`src/inspect_ai/_eval/sandbox_setups.py` replaces `SandboxManager`:

```python
SetupKey = TaskSandboxEnvironment     # spec, run_dir, env (unchanged NamedTuple)

class SetupJob:
    key: SetupKey
    attempt: int                       # 1, or the retry attempt that re-ran a failed key
    state: Literal["waiting", "running", "succeeded", "failed"]
    error: BaseException | None
    bindings: Mapping[ContextVar[Any], Any]   # see "Provider state per setup"
    base: Mapping[ContextVar[Any], Any]       # the chain's values those vars replaced
    context: Context                   # task_init's context as it returned, for task_cleanup

class TaskSetups:                      # one per record
    def settled(self) -> bool
    def failure(self) -> BaseException | None
    def key_for(self, sample_index: int) -> SetupKey | None
    async def ensure(self, samples: list[tuple[int, Sample]]) -> None   # SampleSource additions

class SandboxSetups:                   # one per run
    def request(self, record: TaskRecord) -> TaskSetups
    def request_retry(self, record: TaskRecord, attempt: int) -> TaskSetups
    def open(self) -> AsyncContextManager[None]
    async def shutdown(self) -> None
```

- **Where it runs.** `open()` holds the setup jobs' task group inside the
  task screen, beside the attempt group; requests made before it opens (the
  seed's) start when it opens. Inside the screen, a cancellation of the run
  is absorbed with the rest of the run body, and the display has loaded
  before any setup can suspend it.
- **A record's job.** `request` starts one background job per record: it
  awaits `ensure_model_controller` for the record's model (the eager creation
  `prepare_options` does today before image pulls), then resolves the
  `SetupKey` of each selected sample, recording it by the sample's index in
  the attempt's sample list (the `sample_index` that `run_sample` receives;
  seed samples first, then added samples in arrival order, so two objects
  with one id get separate entries), and requests the `task_init` jobs. A
  record with no sandbox needs no job: its first `generate` creates the
  controller lazily, as for any model today.
- **Once per configuration per run.** `task_init` jobs are keyed by
  `SetupKey` across all records and kept until the run ends; they run one at
  a time (a provider never gets two `task_init` calls at once, as
  `_init_lock` ensures today), in request order, except that a job needed now
  (a `SampleSource` task's `ensure()`, a task retry) goes first.
- **Failure.** A failed key resolution or `task_init` marks the job failed.
  Every record needing it becomes startable, and its attempt ends at once
  through the normal path: `task_run` receives the failure in
  `TaskRunOptions.setup_error`, registers, fires `on_task_start`, writes an
  error log whose error is the setup exception, and fires `on_task_end`. A
  `KeyboardInterrupt` or `SystemExit` from a setup ends the run.
- **Retry rule.** A record's retry attempt `k` re-runs a failed job only if it
  failed for an attempt below `k`; otherwise it joins the job. However many
  tasks share a broken configuration, it is set up at most once per attempt
  number.
- **`SampleSource` additions.** `startup_sandboxes` becomes
  `options.setups.ensure(samples)`: resolve the added samples' keys, request
  missing jobs as needed now, and await them. A failure fails that task, as
  today.
- **Samples use the key resolved for them.** `run_sample` passes
  `options.setups.key_for(sample_index)` to `sandboxenv_context`, which uses
  that key's spec instead of resolving the sample's sandbox again, so the
  path `task_init` used is the path `sample_init` gets.
- **Cancelled records** drop their waiting jobs that no other record needs.
  A job that has started runs to its end (interrupting `task_init` can leave
  resources nothing cleans up), and the dispatcher waits for it before it
  calls `next_tasks()` or ends.
- **Display.** Every setup suspends the task display while `task_init` runs,
  as today (`display().suspend_task_app()`), since providers write to the
  terminal. Other tasks keep running meanwhile, as on today's live path.
- **Cleanup.** `shutdown()`, from `eval_run`'s `finally` after the screen has
  closed, runs each succeeded job's `task_cleanup` once, in a task started
  from that job's captured context, shielded, as today. Failed or unstarted
  jobs get none; a `task_init` interrupted by a run-level cancellation gets
  none, as today.

Seed setups run beside the dispatcher like every other setup (decision:
Ransom, 2026-11-03).

### Setup does not change the process's directory or environment

`chdir` and `environ_vars` are removed from setup, key resolution and
cleanup, and the `chdir` around `TaskLogger` construction goes too
("Adding tasks"). In their place:

- **Inspect resolves config paths against the task directory** in one
  helper, `resolve_config_paths(config, task_dir)`
  (`src/inspect_ai/util/_sandbox/paths.py`): a relative string config, and
  each relative `build` context of a `ComposeConfig` service (a string, or
  `ComposeBuild.context`), becomes absolute when that path exists under the
  task directory. A URI, an absolute path, a string with no such file, and an
  `OSError` from the check (a string too long to be a path) leave the value as
  given. `resolve_task_sandbox` calls it for the task-level config in place of
  its unconditional join, so an inline-JSON string config is no longer
  rewritten; `resolve_sandbox` calls it for a sample's own config. Key
  resolution records the result, and the sample uses it ("Samples use the key
  resolved for them"), so it is resolved once.
- **An internal setup scope**, a `ContextVar` in
  `src/inspect_ai/util/_sandbox/setup.py` holding the task directory and the
  key's `env`, is set around `task_init_environment`, `task_init` and
  `task_cleanup`, and cleared when the call returns. `subprocess()` uses the
  task directory as its default `cwd` inside it (a relative `cwd` is joined
  to it), so providers' subprocesses run where they run today. The `env` is
  not merged into subprocesses: Docker's `task_init` reads it from the scope
  and passes it to `ComposeProject.create(env=...)`, which its `compose build`
  and `compose pull` already forward. The `env` is what the registered
  provider class's `task_init_environment` returned, so a subclass of Docker
  that overrides it gets its own values.
- **Declaring it.** `SandboxEnvironment` gains

  ```python
  task_init_in_launch_dir: ClassVar[bool] = False
  """True when task_init_environment, task_init and task_cleanup resolve
  every relative path they read themselves against the launch directory, as
  sample_init does (or read none)."""
  ```

  When a provider that leaves it `False` runs `task_init` for a task whose
  directory is not the launch directory, Inspect logs a warning once per
  provider type and task directory per run: "Sandbox provider 'proxmox' runs
  task_init for task 'ctf' in the launch directory (/home/me) rather than the
  task directory (/home/me/evals/ctf); relative paths it resolves itself are
  resolved against the launch directory." An older Inspect ignores the
  attribute. Docker sets it: with its config paths resolved by Inspect, its
  remaining lookups (a missing config's compose-file search, a relative build
  context with no such directory under the task directory) run in the launch
  directory in `task_init` as in `sample_init`.
- **Providers that leave it unset** (decision: Ransom, 2026-11-03: the launch
  directory, with the warning). Their subprocesses through `subprocess()` run
  in the task directory, as today; Python-level reads of the working
  directory see the launch directory. For the surveyed providers:
  - E2B's template warm-up gets a `ComposeConfig` whose build contexts
    Inspect has made absolute, and so does its `sample_init`, so both build
    from the task directory and the warm-up builds the template the samples
    use. E2B can set the flag with no other change.
  - Podman's missing-config lookup and generated compose file move to the
    launch directory, where its `sample_init` already looks, so both calls
    address the same files; it passes absolute paths to its subprocesses, so
    the mixed directories do not matter. It can set the flag.
  - Proxmox resolves a relative `PROXMOX_CONFIG_FILE` against the launch
    directory, as its `default_concurrency()` and `cli_cleanup()` already do.
    A run whose file is found only relative to the task directory falls back
    to `PROXMOX_HOST` or no pools; this is the one surveyed case in which a
    working eval changes, and the warning names it.
- `SandboxEnvironment`'s docstring and `docs/extensions-sandboxes.qmd` state
  the contract: `task_init` may run while other tasks run, one call at a
  time, in the launch directory and environment; config paths arrive
  resolved; set `task_init_in_launch_dir` once the provider's own lookups
  are launch-relative; `ContextVar` bindings as below.

### Provider state per setup

Each `task_init` runs in a task started from the setup chain's context, which
starts as a copy of `eval_run`'s (so Docker's lifecycle scope object is
inherited) and which each job's resulting context replaces in turn, so a
later `task_init` sees what earlier ones bound, as today (k8s's shared
manager stays shared). When `task_init` returns, the job records `context`
(`copy_context()` inside the job), `bindings` (the `ContextVar` values in it
that differ, by `is not`, from the chain's values before the job, excluding
the setup scope) and `base` (those prior values, or a missing marker).

- **Samples.** `sandboxenv_context` applies the bindings of the sample's
  key in the sample's own context before `sample_init`, but only for a
  variable whose current value is still the job's `base` value: a value the
  sample (or its solver) bound itself is left alone. `sample_init`, the
  sample's sandbox calls and `sample_cleanup` then see their configuration's
  state, wherever the setup ran. This fixes the empty-seed `LookupError` for
  E2B, Modal and Daytona.
- **Cleanup.** Each `task_cleanup` runs in its job's captured context, so
  E2B, Modal, Daytona and Podman clean up the list their own `task_init`
  bound, including sandboxes an interrupted `sample_cleanup` left behind.
- Docker's `SandboxLifecycleState` is a mutated object, not a rebinding, so it
  never appears in `bindings`.

The lifecycle scope stays internal: with captured bindings, the pattern
providers already use (bind in `task_init`, read in `sample_init` and
`task_cleanup`) is correct for every provider without a new API, and no
inspect_sandboxes change is needed.

### Where task handles attach

[task-handles.md](task-handles.md) returns a `TaskHandle` per added record,
lets a handle send samples to a task whose dataset is
`samples_from_creator()`, and lets a task that a running task waits on start
on a loan beyond `max_tasks`. It adds fields to `TaskRecord` and one step to
the dispatcher; nothing here depends on it.

### Interactions with related changes

- Recording which task added a task: [task-handles.md](task-handles.md)
  records the creator attempt only for tasks fed through a handle, so that
  change records the origin itself.
- Added tasks under `eval_set()` using their creator's model: it changes
  `_resolve_enqueued_tasks`, which `enqueue_task()` calls unchanged.
- Selection-mode handling of added tasks: it changes resolution inside the
  selection-mode `eval_set()`; `RunQueue.add` takes whatever that returns.
- The dispatcher rule that an attempt with no log or a `cancelled` log means a
  run-level cancellation applies only to attempts `run_one` ran; a record
  ended before its first attempt never reaches it.

## Alternatives considered

- **User code on today's live path** (a `TaskSource` at `max_tasks > 1`, a
  rollout `SampleSource` reading a shared queue). Works under `eval()` only
  and keeps the setup and provider-state problems.
- **A `start=` option on `enqueue_task()`.** Rejected by Ransom: added tasks
  always start when there is room.
- **Admitting a task in the background after it is added** (initialise its
  log and resolve its selection in a job, so `enqueue_task()` stays
  synchronous). It needs admission phases, an admission failure outcome, a
  queue-owned task group for admission and its cancellation, and an end of run
  that waits for admissions; and it holds a temporary file and buffer database
  for every queued task. Starting the log with the attempt and resolving
  selection at the call removes all of it.
- **Keeping `enqueue_task()` synchronous**, with a new async function for
  handles. Two functions for one operation; no caller needs the synchronous
  one (all are in async code), and the API is young enough that the break is
  cheap now.
- **Resolving `task:id` selectors when tasks are admitted together** rather
  than at the call. Keeps today's batch semantics but needs deferred
  resolution and its failure path; adding mutually-referring tasks in one call
  covers the same use.
- **The prototype's table recomputed each pass, with a two-stage pipeline.**
  Requesting setups at add and keeping a startable set gives the same starts
  with one less mechanism.
- **Running each task's setup inside its own slot.** A slot would hold an
  image build and sandbox-free tasks would wait behind it (decision: Ransom,
  2026-11-05).
- **Retries in their task's slot.** Changes start order without a reported
  problem.
- **Keeping `os.chdir` for providers that have not opted in, serialized.**
  Other tasks' samples still see the directory change.
- **Running each `task_init` in a thread or child process.** The directory is
  process-wide; a child process loses the provider's in-memory state.
- **A public `sandbox_setup()` accessor for the task directory**, and a helper
  that resolves Docker's string configs inside a setup. Once Inspect makes
  config paths absolute, no surveyed provider needs the task directory in
  Python, so the accessor would be API nobody calls.
- **Exporting the lifecycle scope.** Every provider would have to adopt it;
  captured bindings make the existing pattern correct.
- **Streaming build output to the task display** instead of suspending it.
  Useful, but it changes where provider output goes and needs a provider
  opt-in; it is its own change (see "Not this design").

Alternatives for the handles are in
[task-handles.md](task-handles.md#alternatives-considered).

## Compatibility and migration

Eval authors who call `enqueue_task()` add `await` (see "Behaviour changes").
Third-party sandbox providers need no change; one whose `task_init` resolves no
relative path against the process directory sets
`task_init_in_launch_dir = True` to silence the warning. No provider needs a
release for any step here.

Public API:

- `enqueue_task()` is `async` (breaking) and returns `list[TaskHandle]`
  ([task-handles.md](task-handles.md)); its docstring and `docs/task-source.qmd`
  say added tasks start when there is room and that selectors naming each
  other need one call.
- New class attribute `SandboxEnvironment.task_init_in_launch_dir` (default
  `False`).
- `subprocess()` defaults `cwd` to the task directory inside a provider's
  task-level calls, as the `chdir` did.

Control channel: `GET /tasks` gains queued rows (`status: "queued"`, a new
`setup` field), task cancel/drain accept queued tasks (`task_queued` in the
result), and `CONTROL_API_VERSION` increases. Older CLIs see an unknown status
value. No eval log schema, viewer type or config file changes here.

## Security

- **`task_init_environment` values** come from sample metadata interpolated
  into Docker's environment. Today they are in `os.environ` for the whole
  setup, visible to every subprocess any running sample starts; now they reach
  only Docker's own compose commands for that setup.
- **Config paths** are resolved against the task directory, which the eval
  author controls, only when the file exists there; nothing from model output
  reaches them.
- **Control channel:** cancelling a queued task uses the existing task
  directive's authorization; queued rows expose what running rows expose.
- **Captured provider bindings** are the provider's own objects, applied only
  inside samples of the same run and configuration.

## Testing

Unit and integration tests on asyncio and trio (`--runtrio` for every async
test touched), mostly with a stub sandbox provider registered with
`@sandboxenv` whose `task_init` blocks on an `anyio.Event`, records
`os.getcwd()` and `os.environ`, and binds `ContextVar`s as E2B does. Every
test that waits on a run is bounded with `fail_after`.

- `tests/util/sandbox/test_sandbox_setup.py` (new; invariants 7 and 8): a
  running sample's `os.getcwd()` and `os.environ` are unchanged while
  `task_init` awaits; `subprocess()` defaults to the task directory inside a
  setup and merges no setup `env`; `resolve_config_paths` makes a relative
  string and a `ComposeConfig` build context absolute only when they exist
  under the task directory, and leaves an inline-JSON string, a URI, an
  absolute path and an over-long string as given; a task-level inline-JSON
  config reaches `task_init` unchanged; per-setup bindings reach
  `sample_init`, `sample_cleanup` and the matching `task_cleanup` for two
  configurations, an added task's configuration and an empty `SampleSource`
  seed; a sample that bound a variable itself keeps its value; a k8s-style
  get-or-create object is shared; the warning is logged once for a provider
  without the flag and a task outside the launch directory, and not with the
  flag.
- `tests/util/sandbox/test_docker_cleanup.py` and
  `test_docker_compatibility.py`: with the task directory different from the
  launch directory and a same-named file in each, a sample-level relative
  `compose.yaml`, a relative `Dockerfile` and a `ComposeConfig` build context,
  on a seed sample and on a sample a `SampleSource` adds, select the task
  directory's file in `task_init_environment`, `task_init` and `sample_init`;
  the `SAMPLE_METADATA_*` values reach `compose build` through the project's
  `env`, and a Docker subclass overriding `task_init_environment` gets its own
  values there. One `--runslow` real-Docker test builds a Dockerfile task
  loaded from another directory.
- `tests/test_enqueue_task.py` (invariants 1–6): an added task starts while
  its creator runs, under `eval()`, `eval_set()` and selection mode; a
  configuration error, a duplicate id (a `ResolvedTask` or `PreviousTask`
  added twice, listed twice, or added in a two-model run) and a selection
  error raise at the call and add nothing; a parent that enqueues A and then B
  under `sample_id=["parent:1", "B:1"]` gets the selection error at A's call,
  and the same two in one call run as today; a literal namespaced id
  (`user:cybergym/arvo_6008`) still selects its sample; `enqueue_task()` run
  in a worker thread's own loop raises `RuntimeError`, and through
  `anyio.from_thread.run()` succeeds; after `eval_async()` returns, after a
  latched cancellation and after an exception left dispatch, a child task
  that kept the run's context raises `RuntimeError` with the resolver and the
  registry untouched; a queued task holds no recorder entry, temporary file or
  buffer database until it starts; a log-init failure, injected once and on
  every attempt, ends in an error log after its retries, for a seed task and
  an added one, with `eval_async()` returning rather than raising; at a
  latched cancellation, with a queued record and a pending retry, both end in
  the same step (no log, and the stored log), a sample in a sibling attempt
  awaiting the queued one in a shielded scope returns, and no further retry is
  published by an attempt that errors after the close, including one whose
  `reinit()` is held when the queue closes; the same with a cancellation from
  a scope around `eval_async()` and with a `debug_errors` exception; an
  attempt cancelled before its first step (the dispatcher's pick followed at
  once by a cancel of the record) leaves no record in `starting`; every record
  has ended when `eval_async()` returns or raises.
- `tests/test_task_source.py`: Ctrl-C while `next_tasks()` blocks returns
  the completed logs at `max_tasks` 1 and 2; `next_tasks()` returning `[]`
  ends the source without calling the resolver; the existing live-injection
  test passes for a plain task list.
- `tests/test_sample_source.py`: a mid-run configuration through
  `setups.ensure()`; its failure fails only that task.
- Setup beside dispatch (invariant 9): a setup failure ends only the tasks
  that need it, with error logs and `on_task_start`/`on_task_end`; a shared
  broken key is set up at most once per attempt number; a sandbox-free task
  starts while a setup blocks; `run_samples=False` starts no setup and no
  model controller; a cancelled record's unshared waiting job is dropped.
- `tests/test_task_cancel.py` and `tests/_control/test_ctl.py` (invariant 3):
  queued rows in `GET /tasks`, listed and cancellable from the moment
  `enqueue_task()` returns, including while `next_tasks()` blocks forever; a
  cancel and a drain of a queued record end it with no log and return
  `task_queued: true`, `in_flight: 0` (and `queued: 0`) in `--json` output,
  rendered as cancelled before it started; `score`/`error` answer 409; a
  cancel of a `starting` record stops it before `register_eval`, landing
  before the first stamp check and while `log_start()` is held; a cancel of a
  record whose unregistered attempt failed and whose retry is pending keeps
  the stored log; a second cancel changes nothing; under
  `eval_set(retry_immediate=False)` a second round's queued record is listed
  once and cancel ends it rather than answering "task already finished".
- `tests/test_eval_set.py`: a seed task cancelled while queued makes the eval
  set report failure and name it, under immediate retries and the legacy loop
  (which then never reruns it); every seed task cancelled reports failure;
  selection mode returns `False`; a run cancelled with a seed task still
  queued raises `KeyboardInterrupt`; the stamp and the cancelled set are empty
  after `eval_set()` returns.
- inspect_sandboxes: a test per provider that two configurations and an added
  task's configuration clean up every sandbox, against an Inspect build with
  step 2; it needs provider API keys and runs where that repo's live tests run.

The `--runslow` Docker tests run in the PR CI `slow-tests` job on PRs that
touch `src/inspect_ai/util/_sandbox/**` or `tests/util/sandbox/**` (steps 1, 2
and 4 do); the rest run in the normal test job.

## Implementation plan

Each step is one PR and leaves `main` correct. Steps 1–4 are this design; step
5 is [task-handles.md](task-handles.md). Unifying the dispatcher first would
extend two of today's live-path bugs to plain evals (the process-wide `chdir`
overlapping running tasks, and a later `task_init` rebinding provider state in
the single `eval_run`), so the setup fixes come first.

1. **No process-wide directory or environment changes.**
   `util/_sandbox/paths.py` (`resolve_config_paths`), `util/_sandbox/setup.py`
   (the internal scope), `util/_subprocess.py` (default `cwd`),
   `util/_sandbox/environment.py` (`task_init_in_launch_dir`, docstrings),
   `util/_sandbox/docker/docker.py` (reads the scope's `env`; sets the flag),
   `_eval/loader.py` (`resolve_task_sandbox` through the helper),
   `_eval/task/sandbox.py` (`resolve_sandbox` through the helper; no `chdir`
   in key resolution), `_eval/run.py` (`SandboxManager` without `chdir` and
   `environ_vars`; the warning), `_eval/task/log.py`, `_util/git.py` and
   `_util/path.py` (the task directory passed explicitly),
   `docs/extensions-sandboxes.qmd`. Tests: `test_sandbox_setup.py`, the
   Docker tests.
2. **Provider state per setup.** `_eval/run.py` (`SandboxManager` runs each
   `task_init` in the chained context and records bindings, base values,
   contexts and the per-sample keys), `_eval/task/sandbox.py`
   (`sandboxenv_context` applies bindings where the base value holds and uses
   the recorded key), `_eval/task/run.py`. Fixes the E2B, Modal and Daytona
   leaks and `LookupError` with no inspect_sandboxes release. Independent of
   step 1.
3. **One queue and one dispatcher; logs start with their attempt; queued
   tasks in the control channel.** `_eval/task/enqueue.py` (`RunQueue`,
   `TaskRecord`, async `enqueue_task()` still returning `None`),
   `_eval/run.py` (`configure_task()`, `dispatch_tasks()`, `run_one`'s move
   into `starting` and closed checks; `prepare_options`, `TaskInjection`,
   `PreparedFeed`, `_empty_feed` removed), `_eval/eval.py` (one `eval_run`),
   `_eval/task/run.py` (`logger.init()` at the start of `task_run`;
   `_enqueue_source_tasks`; `on_registered`), `_eval/task/log.py` (`reinit()`
   without `init()`, `discard()` without an entry),
   `_control/queued_tasks.py` (new), `_control/eval_state.py`,
   `_control/cancel.py`, `_control/state.py`, `_control/__init__.py`,
   `_cli/ctl/_task.py`, `_eval/evalset.py`; the callers of `enqueue_task()` in
   `tests/` and `docs/task-source.qmd` gain `await`; `design/task-source.md`
   ("Live injection"), `design/ctl/task-drain.md` ("Out of scope"),
   `design/sample-source.md`. Until step 4 the dispatcher awaits
   `ensure_model_controller` and `SandboxManager.start` for a record before
   it starts the record, as today's live path does in its feed, and a setup
   error there still fails the run. Tests: `test_enqueue_task.py`, `test_task_source.py`,
   `test_task_cancel.py`, `_control/test_ctl.py`, `test_eval_set.py`. Needs
   steps 1 and 2.
4. **Setup beside the dispatcher.** `_eval/sandbox_setups.py` (new; replaces
   `SandboxManager`), `_eval/run.py` (start rule, `setup_error`,
   `setups.open()` inside the screen), `_eval/task/run.py` (setup-failure
   attempt path, `setups.ensure()`), `_control/queued_tasks.py` (`setup`
   field). Tests: the setup-beside-dispatch cases. Needs step 3.
5. **Task handles**, in [task-handles.md](task-handles.md). Needs step 4,
   whose setup-failure attempt path lets a loan start a target whose setup
   failed and a handle report it.

Follow-ups in provider repositories, none a gate: inspect_sandboxes sets
`task_init_in_launch_dir` for E2B, Modal and Daytona and adds the per-provider
cleanup tests; inspect-podman sets it; UKGovernmentBEIS/inspect_proxmox_sandbox
sets it once `PROXMOX_CONFIG_FILE` is documented as launch-relative, or warns
when a set file is not found.

## Open questions

None. Ransom decided (2026-11-03) that providers that have not opted in run
setup in the launch directory with a warning, and that seed setups run beside
the dispatcher; and (2026-11-09) that a task's log starts with its attempt,
that `enqueue_task()` becomes async with selection resolved at the call, that
config paths are resolved by Inspect against the task directory, and that
build-output streaming is a separate change.

## Not this design

- Streaming setup output to the task display's console (prefixed by
  configuration, with a provider opt-in) instead of suspending the display:
  its own change.
- A provider's own lookups in `sample_init` (a missing config's compose-file
  search) seeing the task directory.
- Pausing or resuming a queued task by task id; queued tasks are only listed
  and cancelled here.
- A setup-progress row in the task display.
- A caller's own cancellation of `eval_async()` (for example
  `anyio.fail_after`) being absorbed by `_run_task_screen` like a Ctrl-C.
- `TaskSource` under `eval_set()` (see `design/task-source.md`).
- A stale `retry_pending` flag after an unregistered final retry: `run_one`
  clears the flag using the unregistered attempt's eval id, which
  `clear_eval_retry_pending` ignores, so the registered attempt stays
  flagged. Today's behaviour, unchanged.
- The log a retry ends with when it is abandoned inside a startup `await` and
  that startup write then fails: `run_one` stores the returned log over the one
  kept before the retry. Today's behaviour, unchanged.
