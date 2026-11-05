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
retries apply. Build output streams to the task display's console, each line
prefixed with its configuration. Setup no longer changes the process's
working directory or environment: the task directory and the setup's
environment variables reach the provider through `sandbox_setup()` and are
applied by Inspect's `subprocess()`; a provider declares that it uses them,
and Inspect warns when one that has not runs setup for a task outside the
launch directory. The `ContextVar` values a provider binds in `task_init` are
captured per setup and given to that configuration's samples and its
`task_cleanup`, so each cleanup sees the state its own `task_init` produced.

Handles that let a running task wait on the tasks it adds and send them
samples are a separate design built on this queue:
[task-handles.md](task-handles.md).

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
  send it samples or cancel it ([task-handles.md](task-handles.md) covers
  this).
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
- A queue and dispatcher that [task-handles.md](task-handles.md) can build
  handles on.

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
- Task handles and sending samples to another task; see
  [task-handles.md](task-handles.md).
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
(`run.py:1278`). The provider type's `default_concurrency()` is read for the
sandbox limiter before that, outside the `chdir` (`run.py:1270`,
`task/sandbox.py:51`). `chdir` is `os.chdir` (`src/inspect_ai/_util/path.py:27`)
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

Setup output reaches the terminal directly. Docker's `compose build` and
`compose pull` (`src/inspect_ai/util/_sandbox/docker/compose.py:263`, `:275`)
run through `subprocess()` without capturing output, so the child inherits
the terminal, which is why the task display is suspended around `task_init`.
`subprocess()` already has a line-streaming path for output it does not
capture (`_log_stream`, selected by `INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER`,
`_subprocess.py:251`, `:523`). Third-party providers print too (Podman's
`task_init` calls `print("")`). `display().print()` writes to the textual
display's Console tab (`ConsoleView`,
`src/inspect_ai/_display/textual/widgets/console.py`, which counts unread
lines), above the progress area for the rich display, to stdout for the plain
display and to the logger for the log display.

The task's string sandbox config is made absolute against the task
directory at resolution (`loader.py:500-506`), and the config-file probe
looks in the task directory (`loader.py:439-446`). A sample-level config is
not: `resolve_sandbox()` forwards a sample's own string config unchanged
(`src/inspect_ai/_eval/task/sandbox.py:305`, `:345`), for seed samples and
samples a `SampleSource` adds alike, and per-sample compose files and
Dockerfiles given as relative paths are documented use
(`docs/sandboxing.qmd:183-189`; `tests/util/sandbox/test_docker_compatibility.py:313`,
`:336`). So a relative path reaches a provider's `task_init_environment`
and `task_init` as a sample's string config, inside a structured config, or
through a provider's own default lookup. Docker reads such a string
against the process directory, which the chdir makes the task directory
during setup: `ComposeProject.create` resolves it
(`src/inspect_ai/util/_sandbox/docker/util.py:47`, and a Dockerfile's
generated compose file is based on its parent, `:60-65`), and
`resolve_config_environment` checks that it exists and reads it to
interpolate sample metadata (`docker/docker.py:824-828`), called from
`task_init_environment` (`:177`) and `sample_init` (`:211`). `sample_init` runs in the launch directory
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
| Proxmox (`_proxmox_pool.py:115-130`) | builds instance pools in class state from `PROXMOX_CONFIG_FILE` | shared across configs; see the working-directory note below |
| EC2, Vagrant | process-level class state or nothing | unaffected |

With an empty `SampleSource` seed, `task_init` runs in the feeder, a sibling
of the samples, so its bindings are invisible to them: E2B and Modal raise
`LookupError`, Daytona raises "client not initialized". Docker was fixed by
its lifecycle scope.

Relative paths that these providers resolve in Python during `task_init`
(checkouts: inspect_sandboxes `bbe0ff4`, inspect-podman `8f1151e`,
inspect_proxmox_sandbox `bb359d4`):

- **E2B** warms its template cache in `task_init` from a single-service
  `ComposeConfig` (`e2b/_e2b.py:115`), whose build paths fall back to
  `Path.cwd()` (`e2b/_compose.py:59`): the task directory today. Its
  `sample_init` resolves the same config again (`_e2b.py:157`) in the launch
  directory. Daytona's and Modal's identical fallbacks
  (`daytona/_compose.py:42`, `modal/_compose.py:64`) run only in
  `sample_init`, so they already use the launch directory.
- **Podman** resolves a `None` config with a compose-file lookup in
  `os.getcwd()` (`inspect_podman/util.py:67`, `config.py:80`) and writes the
  YAML for a `ComposeConfig` to an auto-compose file there
  (`util.py:52`), in `task_init` (`podman.py:77`) and again in
  `sample_init` (`podman.py:126`). The loader's probe has already turned a
  compose file or Dockerfile in the task directory into an absolute config,
  so the lookup is reached only when the task directory has none.
- **Proxmox** reads `PROXMOX_CONFIG_FILE` in `task_init`
  (`_proxmox_sandbox_environment.py:360` → `_proxmox_pool.py:125` →
  `schema.py:484`), so a relative value resolves against the task directory
  and the pools it builds are cached for the samples. Its other readers of
  the same variable, `default_concurrency()` (`_proxmox_pool.py:205`, read
  outside the setup `chdir`) and `cli_cleanup()`
  (`_proxmox_sandbox_environment.py:637`), already resolve it against the
  launch directory. A path that is not found falls back to the single
  instance named by `PROXMOX_HOST`, or to no pools. The README's example is
  an absolute path, and GitHub code search finds no Inspect project other
  than inspect_proxmox_sandbox that sets the variable.
- k8s, EC2 and Vagrant take absolute paths or none.

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
- Handle misuse (for example awaiting a handle inside
  `TaskSource.next_tasks()`): see
  [task-handles.md](task-handles.md#run-shapes-and-what-is-refused).
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
TaskPhase = Literal[
    "waiting", "admitting", "admitting_cancelled", "admitted",
    "finalizing", "starting", "starting_cancelled", "running", "ended",
]

@dataclass(eq=False)
class TaskRecord:
    """One task × model of the run, from queuing until it ends.

    `phase` is the record's whole lifecycle; it changes only through
    `RunQueue._move(record, to)`, which checks the move against the
    transition table and rings `wake`. Every move is a synchronous step on
    the run's event loop with no `await` inside it, so no lock is needed.
    """
    task_id: str
    task: str                        # task name and model: kept after the record ends
    model: str
    resolved: ResolvedTask | None    # released when the record ends
    options: TaskRunOptions | None   # configured at add time; released when the record ends
    index: int                       # result order: seed first in input order, then arrival order
    phase: TaskPhase = "waiting"
    setups: TaskSetups | None = None # see "Sandbox setup"; None until admitted
    log: EvalLog | None = None       # the log run_one stored for the task; final log once ended
    error: BaseException | None = None  # admission failure
    started: anyio.Event             # set once, at the first move into "running"
    ended: anyio.Event               # set exactly once, by RunQueue.end()

class RunQueue:
    run_id: str
    def add(self, resolved: list[ResolvedTask], *, ahead: bool = False) -> list[TaskRecord]
    def find(self, task_id: str) -> TaskRecord | None
    def cancel(self, record: TaskRecord) -> None
    def end(self, record: TaskRecord, log: EvalLog | None) -> None
    wake: Wake                       # rung by every phase move and by setups as they settle
```

[task-handles.md](task-handles.md#what-the-handles-add-to-the-run-queue)
adds `creator`, `port` and `loan` fields to the record and a loaned-start
step to the dispatch loop.

`RunQueue.add` is synchronous. It orders the addition sequence-major (the
order `run_batches` uses at `max_tasks == 1` today), adds the tasks' names to
the run's set of task names (which moves from `eval_run` into the queue),
assigns each record its `task_id` (`resolved_task.id`, or a new id, which
the `TaskLogger` later receives), and configures each task's name-independent
part: assigns missing sample ids, checks id uniqueness, applies the
eval-level overrides other than `sample_id`, and runs the `SampleSource`
prerequisite checks. That is the part of today's `prepare_options` body that
needs no other task's name, moved into a function `configure_task()` in
`run.py`. Its errors (`PrerequisiteError`, duplicate ids, unresolvable
tasks) raise to the caller: to `eval()` for the seed, to the
`enqueue_task()` caller for an added task, and into the dispatcher for a
`next_tasks()` batch (ending the run, as today). `enqueue_task()` appends to
the end of the queue; a `next_tasks()` batch goes ahead of any tasks
enqueued while `next_tasks()` was running (`ahead=True`), matching the order
`run_batches` produces today.

**Task ids are unique in a run.** The queued registry, `RunQueue.find` and
the control channel's grouping of `EvalState`s
(`src/inspect_ai/_control/state.py:191`) each treat one `task_id` as one
task, but resolution can repeat an id. A `Task` resolves to a new id for
each model, while a `ResolvedTask` or `PreviousTask` keeps the id it
carries (`src/inspect_ai/_eval/loader.py:135`, `:296`, `:362`), and
`_resolve_enqueued_tasks` resolves its input once per model
(`src/inspect_ai/_eval/eval.py:1313`). So adding one in a run with two
models, adding it twice, or listing it twice in one call gives records that
share an id; today they run as separate tasks that the control channel
folds into one. `RunQueue.add` therefore checks the batch's ids before it
changes anything: an id that any record of this run already holds (queued,
running or ended), or that repeats within the batch, raises `ValueError`
("task id '<id>' (task '<task>') is already in this run: a ResolvedTask or
PreviousTask keeps its id, so it can be added once, in a run with one
model; pass the Task to run it once per model"), and no task of the batch
is ordered, named, configured or registered. For the seed it raises from
`eval()`; the seed paths that pass resolved or previous tasks resolve each
once (`eval_set()` rounds and selection workers pass `model=None`,
`src/inspect_ai/_eval/evalset.py:554`; `eval_retry()` runs each log with
its own model, `src/inspect_ai/_eval/eval.py:1973-1985`), so it does not
fire for them. A retry is not an addition: an in-run retry keeps its record
and id, and `eval_set(retry_immediate=False)` runs its retry rounds as
separate `eval()` calls, each with its own `RunQueue`.

**Sample selection waits for admission.** A `task:id` selector names a task
only when that task's name is in the run's set
(`resolve_task_sample_ids`, `src/inspect_ai/_eval/task/util.py:80-123`);
otherwise the colon is part of a literal id, which `slice_dataset` requires
to exist (`:179`). Today `prepare_options` adds a whole buffered batch's
names before resolving any of its selectors (`run.py:215-219`, `:264`), so a
parent that enqueues A and then B under `sample_id=["parent:1", "B:1"]` runs
no sample of A. Resolving A's selectors inside its own `enqueue_task()` call
would not yet know B and would read `B:1` as a literal id of A. So the
name-dependent part of configuration runs at admission instead, in
`admit_task()`: it resolves the task's `sample_id` against the run's set of
names as it stands then, logs the existing "No sample_id selector names
task" warning, constructs the `TaskLogger` with that `sample_id`, and
requests the sandbox setups for the samples that selection keeps, so the
logger, the setup keys and the attempt all use one resolved selection, as
`SandboxManager.start` and `prepare_options` share one today
(`run.py:1179`). Admission is a background job, which cannot run until the
code that called `enqueue_task()` next awaits, so every task added before
that `await` (one call with several tasks, or consecutive calls) is in the
set when any of them resolves its selectors, and so is every task added
earlier. The seed is added in one step, so its selectors resolve against
the whole seed as today. A task that a selector names must therefore be
enqueued before its creator awaits, so that it is admitted in the same
group (decision: Ransom, 2026-11-03). A selection error (a literal id the dataset does
not have) is an admission failure: for the seed it raises from `eval()` as
today, and for an added task it ends that record with no log, keeping the
error for its handles.

`RunQueue.add` also registers each new record with the control channel as
queued, in the same synchronous step, so a record is listed and cancellable
from the moment `add` returns, before anything about it is awaited (see
"Control channel").

**Admission** prepares a record to start: it resolves the record's sample
selection and constructs its `TaskLogger` (above), awaits
`ensure_model_controller` and `logger.init()` (as `prepare_options` does
today), requests the record's sandbox setups, and grows the display's task
count. A run with `run_samples=False` runs no samples, so, as
`prepare_options` does today (`src/inspect_ai/_eval/run.py:236-245`), its
admission skips `ensure_model_controller` and requests no setups: the
record gets an empty `TaskSetups`, which has settled, so it is startable as
soon as it is admitted. It still initializes its logger, and its attempt
returns the existing `started` log (`task/run.py:1131-1132`). The rule is
the same for the seed, for added tasks and for a retry's setups
(`SandboxSetups.request` and `request_retry` both return the empty
`TaskSetups` when the attempt's `TaskRunOptions.run_samples` is false).
Admissions run one record at a time, in queue order, in a background
job in the dispatcher's task group, so a slow `logger.init()` blocks neither
the dispatch loop nor the listing or cancelling of later records. The seed is
admitted before the dispatch loop starts, and a seed admission failure raises
from `eval()` as today. For an added task an admission failure ends that
record with no log, keeping the failure in `error` (what its handles report
is in [task-handles.md](task-handles.md#the-handle-api)), and the run
continues.

**Cancelling a record** (`RunQueue.cancel`, called by the control channel's
cancel or drain of a queued row and by a handle's `cancel()`) is
synchronous and acts on the record's phase alone (see "Task phases" below
for the full table). A cancel of a record whose first attempt has not
started is finished by the queue itself, never by the dispatcher, so it
completes while the
dispatcher is blocked anywhere, including inside a `next_tasks()` call that
never returns (the source contract allows one,
`src/inspect_ai/_eval/task/task_source.py:56`):

- `waiting` (admission not begun): it ends the record at once with
  `RunQueue.end(record, None)`; the admission job skips a record that has
  ended;
- `admitting`: it moves the record to `admitting_cancelled`; the admission
  runs to the end (interrupting `logger.init()` part-way leaves a recorder
  entry and temporary file behind), then moves the record to `finalizing`
  instead of `admitted` and runs the finalization below;
- `admitted`: it moves the record to `finalizing` and starts the
  finalization as its own task in the dispatcher's task group, where the
  admission job runs; a child of that group runs while the dispatcher
  itself awaits, so the finalization runs at once, whatever the dispatcher
  or the admission job is doing;
- `starting` (the dispatcher has handed the record to `run_one`, and no
  attempt of it has called `register_eval`): it moves the record to
  `starting_cancelled` and, in the same step, writes the existing
  retry-abandon stamp (`abandon_task_retry(task_id)`,
  `src/inspect_ai/_control/eval_state.py:897`, which rings the
  dispatcher); today's readers of that stamp then stop the attempt and drop
  any retry of it (see "Task phases");
- `running`: an attempt has registered its `EvalState`, so a handle's
  cancel runs the control channel's existing task cancel
  (`cancel_task(task_id)`, `src/inspect_ai/_control/cancel.py:183`) in
  process, which aborts the running attempt, or abandons the retry the task
  is waiting for, exactly as `inspect ctl task cancel` does today; the
  control channel itself reaches this phase through that path, not through
  the queue;
- `admitting_cancelled`, `starting_cancelled`, `finalizing`, `ended`: a
  cancel is already in hand or the record has ended, so it does nothing.

The dispatcher starts a record's first attempt only from `admitted`, so a
record cancelled before that is never started, and a cancel in `starting`
reaches the attempt and its retries through the stamp.

Finalization (`RunQueue._finalize_queued(record)`) runs at most once per
record: only the move into `finalizing` starts it, and that move is
synchronous and allowed only from `admitting_cancelled` and `admitted`, so
a second cancel, or the run's end, finds `finalizing` and does nothing. It
awaits `logger.discard()` in a shielded scope, then calls
`RunQueue.end(record, None)`, which sets `ended`, removes the record from
the queued registry and from the queue, releases what it holds (below) and
so resolves every handle wait on it (`started()` and an unresolved request
raise `TaskEndedError(log=None)`, `result()` returns `None`; see
[task-handles.md](task-handles.md#the-handle-api)). The run's end waits for
finalizations still in progress, as it waits for admissions.

A record that ends before its first attempt starts, for any reason (cancel,
run end), and whose logger was initialised calls `logger.discard()`
(`src/inspect_ai/_eval/task/log.py:1076`), which releases the recorder entry
and its temporary file; nothing reaches the log directory. It drops its
setup jobs that have not started and that no other record needs.

**Releasing what an ended record holds.** Records are kept until the run ends
so that the control channel and handles can report on them, but an ended
record keeps only its identity (`task_id`, `task`, `model`, `index`), its
final `log` (the same object the run returns), `error` and `ended`.
`RunQueue.end` clears `resolved`, `options` and `setups` (and what the
handles design attaches). `ResolvedTask.task` holds the
original dataset (`src/inspect_ai/_eval/task/resolved.py:17`) and the
configured task is a shallow copy of it (`run.py:260`), so both references
have to go for a finished added task's samples to be freed. A retained
admission failure would otherwise keep them through its traceback: a
selection failure raised in `slice_dataset()` holds its dataset argument in
a frame (`src/inspect_ai/_eval/task/util.py:143`, `:191`), directly or
through a chained `__cause__` or `__context__`. So when `RunQueue.end`
stores an admission failure in `error`, it first logs it once with its
traceback (an error naming the task and model), then clears `__traceback__`
on every exception in the chain (`__cause__`, `__context__` and the members
of an exception group, each visited once). The exception keeps its type,
message and chain, which is what the handles report
([task-handles.md](task-handles.md#the-handle-api)). The seed's
`ResolvedTask`s are also held by `_eval_async_inner`'s own list until the run
ends, as today.

#### Task phases

The field `phase` holds the record's queue lifecycle plus what the queue,
the control channel and the handles need to know about its attempts:
whether one has registered, and whether a cancel arrived before one did.
Once the dispatcher hands a record to `run_one`, its attempts, its retries,
the retry decision and retry abandonment are today's `run_one` and
`_run_task` (`src/inspect_ai/_eval/run.py:594-696`, `:855-1043`), unchanged;
the phase does not track them. The phases:

- `waiting`: added, admission not begun.
- `admitting`: the admission job is admitting it.
- `admitting_cancelled`: cancelled during admission; the admission runs to
  the end and then finalizes it.
- `admitted`: ready for its first attempt; the dispatcher starts it once
  its setups have settled.
- `finalizing`: a cancelled record whose first attempt never started is
  discarding its logger before it ends.
- `starting`: the dispatcher has handed the record to `run_one`, and no
  attempt has called `register_eval` yet. An attempt can end without
  registering: `_run_task` converts a startup error (prior-log seeding, a
  retry's checkpoint startup copy, the `log_start()` flush, recording
  inherited configuration updates) into an error log
  (`src/inspect_ai/_eval/run.py:662-687`), and with `run_samples=False`
  `task_run` returns the `started` log before registering
  (`src/inspect_ai/_eval/task/run.py:1131-1132`). Any retry of such an
  attempt waits and runs inside this phase.
- `starting_cancelled`: cancelled while `starting`.
- `running`: an attempt has registered. Entered at the first
  `register_eval` and kept until the record ends, through later attempts
  and while a retry waits between them.
- `ended`: `RunQueue.end` has run; `ended` is set.

What the public surfaces show is a function of the phase:

| phase | `TaskHandle.state` | control channel |
| --- | --- | --- |
| `waiting`, `admitting`, `admitting_cancelled` | `queued` | queued registry row, `setup: "admitting"` |
| `admitted`, `finalizing`, `starting`, `starting_cancelled` | `queued` | queued registry row, `setup` from the record's setups |
| `running` | `running` | the task's `EvalState`s, as today, including today's between-attempts state (`retry_pending`) while a retry waits |
| `ended` | `ended` | the last registered attempt's `EvalState`, if one registered |

`TaskHandle.started()` returns when `started` is set, at the move into
`running`; a record that ends first raises `TaskEndedError` with its final
log, which is `None` when no attempt returned one (see
[task-handles.md](task-handles.md#the-handle-api)). A control-channel pause
(the existing `task_dispatch_paused` latch,
`src/inspect_ai/_eval/run.py:796`) is not a phase: it holds an `admitted`
record or a pending retry from being picked without changing what it is.

Transitions. Each is one synchronous step on the event loop, made by the
component named; `RunQueue._move` raises `RuntimeError` on a move the table
does not list, which would be a bug in Inspect.

| from | event | to | made by |
| --- | --- | --- | --- |
| (none) | `RunQueue.add` | `waiting` | `add` |
| `waiting` | the admission job takes the record | `admitting` | admission job |
| `waiting` | cancel, or the run ends | `ended`, no log | `RunQueue.cancel`; the dispatcher at run end |
| `admitting` | cancel | `admitting_cancelled` | `RunQueue.cancel` |
| `admitting` | admission succeeds (setups requested) | `admitted` | admission job |
| `admitting_cancelled` | admission succeeds | `finalizing` | admission job, which then runs the finalization |
| `admitting`, `admitting_cancelled` | admission fails | `ended`, no log, `error` kept | admission job, after discarding a logger it initialised |
| `admitted` | cancel, or the run ends | `finalizing` | `RunQueue.cancel`; the dispatcher at run end |
| `finalizing` | `logger.discard()` returns | `ended`, no log | the finalization |
| `admitted` | the dispatcher hands the record to `run_one` (an ordinary pick or a loan) | `starting` | dispatcher |
| `starting` | cancel | `starting_cancelled`, with the retry-abandon stamp written in the same step | `RunQueue.cancel` |
| `starting` | an attempt calls `register_eval` | `running` | `task_run`, through `on_registered` |
| `starting_cancelled` | an attempt calls `register_eval` | `running`, and the attempt is aborted at once | `task_run`, through `on_registered` |
| `running` | cancel | no change: today's task cancel or drain of the running attempt or of the retry it waits for | the control channel; a handle through `cancel_task(task_id)` |
| `starting`, `starting_cancelled`, `running` | the record's attempts are over: `run_one` returns or raises without queuing a retry, or the dispatcher drops the record's pending retry (abandoned, or the run ends) | `ended`, with the log today's code leaves for the task (`None` if no attempt returned one) | `run_one`, or the dispatcher, in the synchronous step where today's code stores the result or drops the retry |

**The rest of the attempt lifecycle is today's.** `run_one` runs an
attempt through `_run_task`, makes the retry decision, stores the result
(`results[item.idx]` today, `record.log` here) and appends a retry item to
the queue; the dispatcher drops a pending retry whose task carries the
abandon stamp and discards its unstarted logger (`run.py:1052-1070`); and
`_run_task` stops an attempt that finds the stamp before it registers
(`task/run.py:944`, `:977`, `:1177`). The log a record ends with is the log
that code leaves for the task, chosen as today. The design does not
re-specify those paths; the table holds only the moves the phase makes
around them.

**A cancel in `starting`** writes the existing per-task stamp,
`abandon_task_retry(task_id)`, in the same step as the move, and today's
readers of the stamp do the rest, as they do for a retry abandoned in the
same window today: the dispatcher drops a retry already pending; `run_one`'s
retry decision queues none (`run.py:932`); and an attempt still starting
stops at the stamp checks before `register_eval` (the last, `:1177`, runs
with no `await` before `register_eval`), after which `run_one` discards its
logger (`run.py:882`). So the record ends with the log its earlier
attempts stored, or with no log for a first attempt, unless the attempt
returns a log before it reaches a check (a startup write that fails, or
`run_samples=False`'s `started` log), which it then ends with. The stamp is
per task id and per run (`reset_retry_abandoned` at the run boundary), and
task ids are unique in a run, so it reaches only this record. Because the
last check runs synchronously before `register_eval`, today's runner never
registers an attempt of a `starting_cancelled` record; `on_registered`
aborts one that does, so the phase alone holds the rule that a cancel
before registration lets no samples run.

`on_registered` is a new `TaskRunOptions` field, a callback the dispatcher
sets when it hands a record to `run_one`. `task_run` calls it immediately
after `register_eval` (`src/inspect_ai/_eval/task/run.py:1185`), with no
`await` between. From `starting` or `starting_cancelled` it moves the
record to `running`, removes it from the queued registry and sets
`started`, and it returns `True` from `starting_cancelled`, when `task_run`
then fires the attempt's `TaskCancel` with `"abort"`. From `running` (a
later attempt registering) it does nothing.

A cancel of a `running` record that waits for a retry stays where it is
today: the control channel's between-attempts path writes the same stamp
for a registered task (it can land while the errored attempt is still
running, since the runner flags the attempt's `EvalState` `retry_pending`
before its final log write, `src/inspect_ai/_eval/task/run.py:880-900`),
and the readers above act on it.

### The dispatcher

`run_task_retry_attempts` becomes `dispatch_tasks(queue, setups, *, parallel,
task_retry_attempts, task_source, debug_errors) -> list[EvalLog]` in
`run.py`. `run_one`, the retry decision, the retry-abandon handling and
model balancing are unchanged. The loop, inside `_run_task_screen` as today:

```
loop:
    drop pending retries whose task carries the abandon stamp   (as today;
        each discards its unstarted logger and ends its record)
    while not cancelled and in_flight < effective_max_tasks(parallel):
        entry = pick_balanced(startable)     # see the start rule
        if entry is None: break
        if entry is a record: move it from admitted to starting
        start run_one(entry)                 # a retry entry: today's PendingTask
    if cancelled: break
    if any record is not ended, or a setup is in progress:
        await queue.wake; continue
    if source_done: break
    more = await task_source.next_tasks() if task_source else None
    if not more: source_done = True          # None or [] ends the source, as today
    else: queue.add(resolve(more), ahead=True)
```

- **Start rule.** The queue's entries are records awaiting their first
  attempt and retry items (today's `PendingTask`, which now also carries
  its record). An entry is startable when it is a record in `admitted` or a
  pending retry, its setups have settled (succeeded, or one failed) or it
  needs none, and no control-channel pause holds it. An entry whose setup is still
  running does not block the queue: the dispatcher takes the earliest
  startable entry among the least-used models. At `max_tasks == 1` this keeps
  sequence grouping among startable tasks; a sandbox-free task can start
  ahead of an earlier task that is waiting for its image.
- **Retries** are today's: `run_one` decides on a retry, stores the
  attempt's log on the record and appends the retry item at the back of the
  queue under the record's index (`src/inspect_ai/_eval/run.py:1037-1039`),
  and the dispatcher starts it like any entry. A retry's setups are
  requested again under the retry rule in "Sandbox setup". The record's
  phase does not change: a retry after an attempt that never registered
  waits and runs in `starting`, and one after a registered attempt in
  `running` ("Task phases"). A cancel or drain while a retry waits
  abandons it as today (`run.py:871`, `:1064`), through the stamp: from the
  queued registry in `starting` (`RunQueue.cancel`), and through today's
  between-attempts path in `running`. Only the retry's unstarted logger is
  discarded, and the stored log stays the record's log.
- **An empty batch.** `next_tasks()` returning `None` or `[]` ends the
  source, and the resolver is never called for it, as both drivers do today
  (`src/inspect_ai/_eval/eval.py:1196-1199`, `:1214-1215`): the resolver
  reads `resolve_tasks([])` as "discover tasks in the working directory"
  (`src/inspect_ai/_eval/loader.py:129`).
- **`next_tasks()` call point** is unchanged in meaning: it is awaited only
  when nothing is queued, running, being set up or being admitted, so no
  completion can add a task while it blocks. Under plain `eval()` that is the
  same point `run_batches` reaches after a batch; under the live path it is
  the same point as today.
- **End of run.** The loop ends when the source is done and nothing remains,
  or on a run-level cancellation. The run's end waits for the admission job
  and for finalizations in progress, then ends the records still queued: a
  `waiting` record ends with no log, an `admitted` one is finalized as a
  cancelled one is (no log), and a record whose retry is still pending ends
  with its stored log, the retry's unstarted logger discarded as the drop
  step discards one.
- **Ctrl-C.** `next_tasks()` is now awaited inside `_run_task_screen`, so a
  cancellation while it blocks is absorbed like one during a task: the run
  returns the logs it has. A cancellation reaches the run at exactly one
  place for every run shape, so whatever a Ctrl-C during a plain eval's tasks
  does on a backend today, it does at every other point of every run.
- **`debug_errors`** is passed to the dispatcher at every `max_tasks` (today
  only the `max_tasks == 1` path passes it).

`max_tasks` counts attempts in flight.
[task-handles.md](task-handles.md#slot-lending) adds one exception: a task
that a running task is waiting on through a handle can start on a loan
beyond the limit.

### Control channel

`RunQueue.add` registers each record in a new process-level registry,
`src/inspect_ai/_control/queued_tasks.py`, keyed by `task_id`, holding the
task name, model, queue position, the record (whose phase and setups the
listing reads) and a `cancel()` callback into `RunQueue.cancel`.
Registration is synchronous and comes before admission, so a record whose
`logger.init()` is slow, and every record behind it, is listed and
cancellable at once. The record leaves the registry in the same
synchronous step in which an attempt of it first calls `register_eval`
(`task/run.py:1185`): `on_registered` (see "Task phases") does both, with
no `await` between, so a directive always finds it in one of the two. A
cancel that arrives after the dispatcher has handed the record to `run_one`
but before any attempt registers moves it from `starting` to
`starting_cancelled` and writes the retry-abandon stamp, which stops the
attempt before it registers and drops any retry of it (see "Task
phases"). A record that ends before any attempt registers leaves the
registry when it ends. A record whose attempts have all ended before
registering (a startup error returned as a log) stays in the registry, in
`starting`, while its retry waits and starts; a record with a registered
attempt is not in it (see "Retries" under "The dispatcher").

A queued record's `task_id` can already have `EvalState`s from earlier
`eval()` calls in the same process: `eval_set(retry_immediate=False)` runs
each retry round as its own `eval()` and keeps the task id
(`PreviousTask`, `src/inspect_ai/_eval/evalset.py:1531`,
`src/inspect_ai/_eval/loader.py:362`), and `EvalState`s persist across those
calls (`src/inspect_ai/_eval/eval.py:1284`). The queued registry therefore
takes precedence over that history wherever both have the task:

- `GET /tasks` (`current_eval_summaries`) shows one row per task id, as
  it does today by folding `EvalState`s by task id
  (`src/inspect_ai/_control/state.py:191`). A queued record with no
  history adds a row with `status: "queued"`, `attempts: 0` and `samples`
  totals of zero; a queued record whose task already has a row (a legacy
  retry round) overlays that row instead, setting `status: "queued"` and
  keeping its attempts and history, so no task is listed twice. Both carry
  `setup: "admitting" | "waiting" | "running" | "failed" | null`
  (`"admitting"` in the phases `waiting`, `admitting` and
  `admitting_cancelled`, before admission has requested the setups; `null`
  when the task needs none). Selector resolution in the CLI uses this listing, so
  `inspect ctl task cancel <id>` resolves a queued task by any selector it
  accepts for running ones.
- `_task_cancel_directive` looks in the queued registry first and uses
  `latest_eval_for_task` only when the task is not queued, so a finished
  `EvalState` from an earlier round can no longer answer "task already
  finished" (`src/inspect_ai/_control/cancel.py:332`) while the queued
  attempt goes on to run. A plain cancel or a drain of a queued record in
  `waiting`, `admitting` or `admitted` ends it with no log (`changed: true`,
  `queued: true` in the result; `dry_run` reports without acting). In
  `starting` it stops the attempt that has not registered and drops any
  retry of it, through the stamp ("Task phases"): `changed: true`,
  `queued: true`, plus `retry_abandoned: true` when an earlier attempt has
  stored a log, which the record then ends with. `action=score|error` on a queued record answers 409:
  "task … has not started, so there are no samples for a resolution to apply
  to; use cancel or drain", the same rule the between-attempts case uses.
- Cancelling a queued record follows "Cancelling a record" above; a
  setup job that has started runs to the end (interrupting `task_init` can
  leave resources nothing cleans up).
- `CONTROL_API_VERSION` (`src/inspect_ai/_control/__init__.py:84`) increases
  by one; `inspect ctl task list` shows queued rows.
- Under `eval_set()`, see "Queued cancels under `eval_set()`" below.

#### Queued cancels under `eval_set()`

A seed task cancelled or drained while queued, before its first attempt
started, ends with no log, but
`eval_set()` decides success and retries from the logs it gets back:
`try_eval()` returns only produced logs (`src/inspect_ai/_eval/evalset.py:1175`),
and the final status (`:1232`) and selection mode (`:1664`) call
`all_evals_succeeded()` (`:1778`), which is true for a successful subset and
for an empty list. Without a change, a run whose only other task succeeded,
or whose every seed task was cancelled while queued, would report "Completed
all tasks", contradicting the documented result (`docs/eval-sets.qmd:49`).
The no-log outcome stays; the eval set learns about it explicitly:

- `_control/queued_tasks.py` keeps the `task_id`s of records that end with
  no log after a cancel or drain directive or a handle's `cancel()` reached
  them before any attempt registered (in `waiting`, `admitting`, `admitted`
  or `starting`; never a record that ends with a log, such as a retry
  abandoned after an attempt that stored its error log, which reaches the
  eval set as a failure, as today), for the
  current run (reset when `eval_run` starts), and exposes
  `queued_cancelled_task_ids()`.
- `run_eval` (`evalset.py:542`), after `eval()` returns, computes the
  requested tasks with no log: their `ResolvedTask.id`s (the run's
  `task_id`, `run.py:425`) less the logs' `eval.task_id`s. Those in
  `queued_cancelled_task_ids()` were cancelled explicitly. Any other
  requested task without a log was still queued when the run was cancelled,
  so `run_eval` raises `KeyboardInterrupt`, exactly as it does today for a
  cancelled log (`evalset.py:632`).
- The eval set keeps the explicitly cancelled tasks, by task identifier, for
  the rest of the invocation. Later attempts of the legacy retry loop
  (`retry(try_eval)`) leave them out of the tasks they run, so a retry never
  undoes an explicit cancel. With immediate retries (`retry_immediate`) a
  record cancelled while queued never ran, so the dispatcher has no attempt
  to retry, as for an aborted running task.
- The retry predicate stays `all_evals_succeeded` over the logs, so the
  loop stops once every task that was not cancelled has succeeded. The
  final result is `all_evals_succeeded(results)` and no task cancelled
  while queued; the closing message names the cancelled tasks ("Did not
  successfully complete all tasks: cancelled before starting: …").
- Selection mode (`_run_selected`, `evalset.py:1655-1664`) applies the same
  detection and returns `False` when one or all of its selected tasks were
  cancelled while queued.
- A later `eval_set()` on the same log directory finds no log for them and
  runs them: running the remainder after all is a deliberate later action,
  as for a drained task ("No eval-set in-run retry" in
  [task-drain.md](ctl/task-drain.md)).

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
    def bindings_for(self, sample_index: int) -> Mapping[ContextVar[Any], Any]
    async def ensure(self, samples: list[tuple[int, Sample]]) -> None   # SampleSource additions

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
- **Which samples use which job.** Key resolution records, for each sample
  of the attempt, the `SetupKey` its sandbox resolves to, keyed by the
  sample's index in the attempt's sample list: the `sample_index` that
  `run_sample` receives (`task/run.py:1330`), seed samples first, then added
  samples in the order they were added (`task/run.py:1757`). Each added
  `Sample` object gets its own index, including separate objects added with
  the same id for different explicit epochs (`task/run.py:1769`), whose
  sandbox configuration or metadata (and so `task_init_environment` values)
  may differ (`task/sandbox.py:249`). An id, or an `(id, epoch)` pair, is
  not used as the key: one object can run several epochs with one
  configuration, and two objects with one id can have two configurations.
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
- **No samples, no setups.** Under `run_samples=False`, `request` and
  `request_retry` return an empty `TaskSetups` that has settled and resolve
  no keys, so no job runs for the record (see "Admission" under "The run
  queue").
- **`SampleSource` additions.** `startup_sandboxes` becomes
  `options.setups.ensure(samples)`, called by `add_and_start` with each
  added sample and the index `add_samples` gave it: resolve the added
  samples' keys, request any missing jobs as needed now, and await them. A
  failure fails that task, as today.
- **Cleanup.** `shutdown()` runs each succeeded job's `task_cleanup` once,
  in a task started from that job's captured context, inside the setup scope
  for its directory and environment (below), shielded as today. Jobs that
  failed or never started get no cleanup, as today. On a run-level
  cancellation the setup task group is cancelled first; a `task_init`
  interrupted that way gets no cleanup, as today.
- **Display and output.** For a provider that declares support for
  `sandbox_setup()` (below; Docker does), the task display is not suspended
  while its setup runs. `subprocess()` pipes the output of a child that
  would otherwise inherit the terminal (`capture_output=False`, as Docker's
  `compose build` and `compose pull` use) and forwards each line, as it
  arrives, prefixed with the setup's configuration (for example
  `[docker tasks/ctf/compose.yaml]`: the sandbox type and the config file
  relative to the launch directory, or the type alone for a structured or
  empty config), to `display().print()`. In the textual display that is the
  Console tab, whose unread count shows that output arrived; the rich display
  prints it above the progress area, the plain display to stdout, and the
  log display to the logger. With the `none` display the lines go to the
  Python logger at info level, as `_log_stream` does today, so stdout stays
  machine-readable. The same lines also go to the job's bounded buffer (the
  last 64 KiB), and on failure the job logs a warning naming the
  configuration and the exception and writes the buffer to the trace file;
  the task's error log carries the exception only (see "Security"). Setup
  start and end are logged at info level and shown in the queued rows'
  `setup` field.
- **Providers that have not declared support** keep today's terminal
  behaviour: their `task_init` runs inside
  `display().suspend_task_app()`, as every setup does today
  (`run.py:1262`), and their subprocesses inherit the terminal. A provider
  may start processes itself (an SDK, `asyncio.create_subprocess_exec`) or
  print, as Podman's `task_init` does, and only suspension keeps that output
  from corrupting the textual display. Other tasks keep running while the
  display is suspended, as they do on today's live path. Seed setups run
  beside the dispatcher like every other setup (decision: Ransom,
  2026-11-03: one rule for every setup, with build output streamed to the
  console rather than the terminal).

### Setup without changing the process's directory or environment

New public API in `inspect_ai.util` (module
`src/inspect_ai/util/_sandbox/setup.py`):

```python
@dataclass(frozen=True)
class SandboxSetup:
    """The task a sandbox provider's task-level call is for."""
    task_dir: str            # the task's directory, absolute
    env: dict[str, str]      # for task_init: what task_init_environment returned

    def print(self, message: str) -> None:
        """Show a line of setup output: prefixed with the setup's configuration,
        sent where subprocess output of this setup goes, and kept in its
        failure buffer ("Display and output")."""

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
  `os.environ | setup.env | env`. While a setup job of a provider that
  declares support runs, it also pipes and forwards output that would go to
  the terminal ("Display and output" above; internal, not part of
  `SandboxSetup`).
- **Declaring support.** `SandboxEnvironment` gains a class attribute:

  ```python
  supports_sandbox_setup: ClassVar[bool] = False
  """True when the provider's task-level calls take the task directory and
  environment from `sandbox_setup()`, and write to the terminal only
  through `subprocess()` or `sandbox_setup().print()`."""
  ```

  It decides two things: whether the display is suspended around the
  provider's setup ("Display and output"), and whether Inspect warns about
  the working directory (next). An older Inspect ignores the attribute.
- **Warning.** When a provider that does not declare support runs
  `task_init` for a task whose directory is not the launch directory, Inspect
  logs a warning once per provider type and task directory per run:
  "Sandbox provider 'proxmox' does not declare support for sandbox_setup(),
  so its task_init for task 'ctf' runs in the launch directory (/home/me)
  rather than the task directory (/home/me/evals/ctf). Relative paths it
  resolves itself are resolved against the launch directory."
- Docker adopts it and declares support: `ComposeProject.create` resolves
  `ComposeConfig` build paths and the no-config compose lookup against
  `sandbox_setup().task_dir` when set, else `os.getcwd()` (so `sample_init`
  keeps today's behaviour), and any Python-side read of a
  `task_init_environment` variable reads `setup.env`. A string config
  (a sample's relative compose file or Dockerfile) goes through one new
  helper, `setup_config_path(config) -> str`: inside a setup it joins a
  relative path to `sandbox_setup().task_dir` (an absolute path is
  returned unchanged), and outside one it returns the string as today, so
  it resolves against the process directory. Both read sites call it
  before using the path: `ComposeProject.create` (`docker/util.py:47`,
  including the Dockerfile branch, which bases the generated compose file
  on the resolved file's parent) and `resolve_config_environment`
  (`docker/docker.py:824-828`), so the file `task_init_environment`
  interpolates metadata from, the file `task_init` builds, and the file
  today's chdir selected are the same. Docker's own
  subprocesses already go through `subprocess()`, and its one direct
  `print()` in `task_init`, the "Service …: using local image …" message
  (`src/inspect_ai/util/_sandbox/docker/docker.py:149`), becomes
  `sandbox_setup().print(...)`, so it is prefixed, buffered and kept off
  stdout with the `none` display like the rest of the setup's output. For
  Docker the directory and environment its setup sees are therefore exactly
  today's, and all its setup output takes the setup-output route.
- **Providers that have not adopted it** (decision: Ransom, 2026-11-03: the
  launch directory, with the warning above). Their subprocesses started
  through `inspect_ai.util.subprocess()` run in the task directory with the
  setup's environment, as today. Python-level reads of the working directory
  during their `task_init`/`task_cleanup` see the launch directory.
  Subprocesses they start another way run in the launch directory; the setup
  environment is empty for every provider but Docker, so only the directory
  can differ. For the providers surveyed in "Current behaviour" that resolve
  a relative path in `task_init`, this is the boundary:
  - E2B's template warm-up for a `ComposeConfig` resolves build paths
    against the launch directory, the directory its `sample_init` already
    uses for the same config, so the warm-up now builds the template the
    samples ask for.
  - Podman's `task_init` looks up the compose file and writes the
    auto-compose file in the launch directory, as its `sample_init` already
    does, so both calls now address the same project files.
  - Proxmox's `task_init` resolves a relative `PROXMOX_CONFIG_FILE` against
    the launch directory, as its `default_concurrency()` and `cli_cleanup()`
    already do. A run whose config file is found only relative to the task
    directory (a relative path, and a task loaded from another directory)
    falls back to `PROXMOX_HOST` or to no pools instead of the file's pools.
    This is the one surveyed case in which a working eval's behaviour
    changes, and the warning names it. Making Proxmox adopt
    `sandbox_setup()`, or warn when a set `PROXMOX_CONFIG_FILE` is not found,
    is a follow-up in UKGovernmentBEIS/inspect_proxmox_sandbox, not a gate
    for any step here.
- **Opt-in:** a provider reads `sandbox_setup().task_dir` wherever it
  resolves a relative path in Python during `task_init` or `task_cleanup`,
  sends terminal output through `subprocess()` or `sandbox_setup().print()`,
  and sets
  `supports_sandbox_setup = True`. A provider that must also run on older
  Inspect versions feature-detects the accessor
  (`getattr(inspect_ai.util, "sandbox_setup", None)`) and falls back to
  `os.getcwd()`, which older versions set to the task directory, so it needs
  no raised dependency floor.
- What remains: one synchronous `with chdir(task_run_dir(task))` block
  around `TaskLogger` construction in `admit_task()` (it reads
  `git_context()` and `cwd_relative_path()` against the task directory). It
  contains no `await`, so no other coroutine observes it; worker threads can,
  as today. `await logger.init()` moves out of it.
- `SandboxEnvironment`'s class docstring and the sandbox extension docs
  state the contract: `task_init` may run while other tasks run, one call at
  a time; it runs in the launch directory and environment; use
  `sandbox_setup()` for the task directory and environment and declare
  `supports_sandbox_setup`; `ContextVar` bindings as described next.

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

- **Samples.** `run_sample` passes `options.setups.bindings_for(sample_index)`
  (the bindings of the job for the key recorded for that sample index) to
  `sandboxenv_context` (`task/sandbox.py:86`), which sets each one in the
  sample's own task context before `sample_init`. `sample_init`, the sample's sandbox calls and
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

### Where task handles attach

[task-handles.md](task-handles.md) builds on this design: `enqueue_task()`
returns a `TaskHandle` per added record, a handle can send samples to a
`SampleSource` task through a port attached to the record, and a task that
a running task waits on can start on a loan beyond `max_tasks`. It adds
fields to `TaskRecord` and one step to the dispatch loop; nothing in this
design depends on it.

### Interactions with related changes

- Recording which task added a task: `TaskRecord.creator` is the attempt
  that change would record.
- Added tasks under `eval_set()` using their creator's model: it changes
  `_resolve_enqueued_tasks`, which this design calls unchanged; with it, a
  call made from a task adds one task × model instead of one per run
  model.
- Selection-mode handling of added tasks: it changes resolution inside the
  selection-mode `eval_set()`; `RunQueue.add` receives whatever that
  resolution returns. With this design an added task runs live inside the
  selection-mode worker that added it.
- The abort fix's dispatcher rule (an attempt with no log or a `cancelled`
  log means a run-level cancellation) applies only to attempts `run_one`
  ran. A record ended before its first attempt, or by an admission failure,
  never reaches `run_one`, so its missing log does not end the run. A setup
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
- **Keeping the `chdir` for the seed's setups by running them before
  dispatch** (today's directory for every established eval, with output on
  the terminal and the first failure raising from `eval()`). Two setup
  policies, and sandbox-free seed tasks wait for every image. Not chosen:
  one rule for every setup, with the warning for providers that have not
  adopted `sandbox_setup()` (decision: Ransom, 2026-11-03).
- **Suspending the display for every setup, as today.** Keeps output on the
  terminal for every provider, but stops the textual display for every
  image build while other tasks run. Kept only for providers that have not
  declared support, which may write to the terminal by other routes.
- **Running each `task_init` in a thread or a child process** to isolate the
  directory. The directory is process-wide, so a thread does not help; a
  child process loses the provider's in-memory state.
- **Exporting the lifecycle scope** so providers keep state on a shared
  object. Works, but every provider must adopt it, and captured bindings
  make the pattern providers already use correct without a change.
- **A record state plus separate admission, cancel and finalizing fields.**
  Describes the same lifecycle, but allows combinations that cannot occur
  (a running record whose admission is waiting, a cancel pending on a
  record that has ended), so every reader must know which pairs are real.
  One `phase` with a checked transition table makes an impossible
  combination unrepresentable and a wrong move an error.
- **Phases for every attempt path** (a phase for a retry waiting and one
  for a retry starting, with a transition for each way an attempt can end).
  This re-specifies what `run_one` and `_run_task` already do after a record
  leaves the queue, and the table then has to match every path of that code:
  startup errors returned as logs, `run_samples=False`'s `started` log, and
  an abandonment racing a returned log or a later `await`. The queue, the
  control channel and the handles need only whether an attempt has
  registered and whether a cancel came first, so the phase holds that and
  the attempt lifecycle stays today's (decision: Ransom, 2026-11-05).
- **A cancel flag beside one `dispatched` phase.** The cancel between
  dispatch and `register_eval` is part of the record's lifecycle, so it is
  the phase `starting_cancelled`, not a field read beside the phase
  (decision: Ransom, 2026-11-05).
- **Running each task's sandbox setup inside its own slot**, as part of its
  attempt. Simpler, but a slot holds an image build, and sandbox-free tasks
  wait behind it: the prototype's load runs showed sandbox-free tasks
  waiting 2.5 to 5 minutes behind image builds when setup ran inline. Setup
  stays beside the dispatcher (decision: Ransom, 2026-11-05).

Alternatives for the handles (including running the rollout in a separate
Inspect process) are in
[task-handles.md](task-handles.md#alternatives-considered).

## Compatibility and migration

No migration required for eval authors. Third-party sandbox providers that
resolve relative paths in Python during `task_init`/`task_cleanup` should
read `sandbox_setup().task_dir`, and every provider that writes to the
terminal only through `subprocess()` should declare
`supports_sandbox_setup = True` (see "Opt-in"); until then they get the
working-directory warning and today's display suspension. No provider needs
a release for any step here.

Public API (additive):

- `enqueue_task()`'s docstring and `docs/task-source.qmd` say added tasks
  always start when there is room (its return value changes in
  [task-handles.md](task-handles.md)).
- New `inspect_ai.util.SandboxSetup` (with `print()`), `sandbox_setup()`;
  new class attribute
  `SandboxEnvironment.supports_sandbox_setup` (default `False`).
- `inspect_ai.util.subprocess()` applies the setup's directory and
  environment inside a provider's task-level calls.

Control channel: `GET /tasks` gains queued rows (`status: "queued"`, a new
`setup` field), task cancel/drain accept queued tasks, and
`CONTROL_API_VERSION` increases. A task whose only attempts failed before
registering (for example a failed `log_start()` flush) and that waits for a
retry is listed as queued and can be cancelled; today it has no row and a
cancel answers 404. A cancel or drain of a task the dispatcher has started
but whose attempt has not yet registered stops that attempt before it
registers, as today's retry-abandon path stops a retry in the same window,
and the task ends with no log (or with the log of an earlier unregistered
attempt); today such a task has no row and the cancel answers 404. Older CLIs see the new rows as unknown
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

Sample selection (`task:id` selectors, which can change which samples
run):

- Tasks added before the creator's next `await` (one `enqueue_task()` call
  or consecutive ones) and every earlier task are known when any of them
  resolves its selectors, so they select what they select today. Today a
  whole batch's names were known, so a creator that adds A, awaits, then
  adds B shared one batch; now A may be admitted first, and for A a `B:1`
  selector is a literal id: an admission failure if A has no sample `B:1`
  (loud, with the `slice_dataset` error), or that sample if it has one.
  Adding the tasks in one call, or naming each selected task before the
  `await`, keeps today's result (decision: Ransom, 2026-11-03). Literal namespaced ids
  (`user:cybergym/arvo_6008`) resolve as today.

Failure reporting (the run's outcome changes only where today it fails):

- A failed setup ends only the tasks that need it, each with an error log and
  its retries; today the run fails. Hooks see `on_task_start`/`on_task_end`
  for those tasks; today they see none and `on_run_end` gets the exception.
- Ctrl-C while `next_tasks()` blocks returns the logs so far instead of
  raising `KeyboardInterrupt` without them.
- An added task whose admission fails ends alone; today the run fails.
- Adding a task id that is already in the run (a `ResolvedTask` or
  `PreviousTask` added twice, listed twice, or added in a run with several
  models) raises `ValueError` and adds nothing; today the copies run under
  one id, which the control channel shows as one task.
- An eval set or selection-mode worker with a seed task cancelled while
  queued reports failure, does not re-run that task in the same
  invocation, and names it in its closing message.
- `debug_errors=True` now raises task errors at every `max_tasks` (explicit
  configuration only).
- Seed setups run beside the dispatcher: a broken seed configuration ends
  only its tasks instead of raising from `eval()`.
- Build output from a provider that declares support (Docker) streams to the
  task display's console, prefixed with its configuration, instead of to the
  terminal with the display suspended.
- A provider that has not declared support logs a working-directory warning
  when it sets up a task outside the launch directory.

Could change what an eval computes:

- **`task_init`'s working directory for a third-party provider that has not
  adopted `sandbox_setup()`,** when the task is loaded from another
  directory than the launch directory and the provider resolves a relative
  path in Python during `task_init` ("Providers that have not adopted it"
  lists the boundary per provider). For E2B and Podman, `task_init` and
  `sample_init` now resolve the path against the same directory, where today
  they disagree. For Proxmox, a relative `PROXMOX_CONFIG_FILE` that exists
  only relative to the task directory stops being found by `task_init`, as
  it already is not found by `default_concurrency()` and `cli_cleanup()`, so
  the run uses `PROXMOX_HOST` or no pools instead; the warning names the
  directories. Docker (including a sample's relative compose file or
  Dockerfile, resolved against the task directory during setup as the
  chdir resolved it), subprocesses through `subprocess()`, installed-package
  tasks (whose task directory is the launch directory) and runs launched from
  the task directory are unaffected. Ransom accepted this under the
  eval-defaults rule on the strength of the warning and the existing
  inconsistency (decision: Ransom, 2026-11-03).
- **Which `ContextVar` values a sample sees.** A sample now sees its own
  configuration's setup state rather than the last setup's. For the surveyed
  providers this changes which registry or run id a sandbox is recorded
  under, not the sandbox itself. A provider whose `task_init` binds a value
  that samples of another configuration are meant to use would see a
  difference; none of the surveyed providers does.
- **`os.environ` during setup** no longer contains `task_init_environment`
  variables; only Docker returns any, and it passes them explicitly.

## Security

- **`task_init_environment` values** come from sample metadata (dataset
  content) interpolated into Docker's environment. Today they are written to
  `os.environ` for the whole setup, visible to every subprocess any running
  sample starts meanwhile. Now they reach only the setup's own subprocesses.
- **Setup output** (image build logs) can contain whatever a build prints.
  Today it goes to the terminal only. It now goes to the task display's
  console (or the logger with the `none` display), and on failure its tail
  goes to the trace file. It stays out of the eval log and the control
  channel: the task's error log carries only the exception. The rich and
  textual displays' `print()` already passes `markup=False`, so build output
  cannot inject Rich markup into the display.
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
  an empty `SampleSource` seed; two samples with one id added for different
  explicit epochs whose configurations differ, admitted before either runs,
  each get their own configuration's bindings; a k8s-style get-or-create
  object is shared across configurations; the working-directory warning is
  logged once for a provider that does not declare support and a task
  outside the launch directory, and not for one that does; output of a
  `capture_output=False` subprocess during a declaring provider's setup
  reaches `display().print()` line by line with the configuration prefix and
  the failure buffer, while a non-declaring provider's setup suspends the
  display and leaves output on the terminal; `sandbox_setup().print()`
  takes the same route, and with the `none` display writes nothing to
  stdout.
- `tests/util/sandbox/test_docker_cleanup.py`: Docker under the setup scope
  resolves `ComposeConfig` and no-config compose files against the task
  directory with the launch directory elsewhere (stubbed daemon, as the file
  does today), and the local-image branch's message reaches the display with
  the configuration prefix and not stdout under the `none` display. With
  the task directory different from the launch directory, and a file of the
  same name in each, a sample-level relative `compose.yaml` and a relative
  `Dockerfile`, on a seed sample and on a sample a `SampleSource` adds,
  select the task directory's file in `task_init_environment` and
  `task_init`, the `SAMPLE_METADATA_*` variables the task directory's file
  names are interpolated, the Dockerfile's generated compose file is based
  in the task directory, and an absolute path is used as given; outside a
  setup, `setup_config_path` returns the string unchanged (the existing
  `tests/util/sandbox/test_docker_compatibility.py` cases still pass). One
  `--runslow` real-Docker test builds a Dockerfile task loaded from another
  directory.
- `tests/test_enqueue_task.py`: `RunQueue._move` accepts every row of the
  "Task phases" transition table and raises on every other pair, and a
  run's records pass only through listed moves (a spy on `_move`, over a
  run with an admission failure, a queued cancel, a cancel in `starting`, a
  retry after a registered attempt and one after an unregistered attempt,
  and an abandoned retry); a later attempt registering leaves a `running`
  record's phase and `started` unchanged; attempts that end before registering, each
  bounded with `fail_after` and checked for its final log, its slot and
  registry entry released, no recorder entry or temporary file left, and its
  handle's `started()`, `result()` and pending requests: a `log_start()`
  failure, a prior-log seed failure, a checkpoint startup copy failure and
  an inherited-config recording failure, each injected once (the record
  stays `starting`, is listed queued and cancellable through the queue
  while its retry waits and starts, and moves to `running` when the retry
  registers and succeeds), injected on every attempt until the budget is
  spent (ends with the latest error log, `started()` raises
  `TaskEndedError(log=<that log>)`), and injected while the attempt's
  `log_start()` is held on an event and a cancel lands (ends with that
  error log and no retry); a cancel and a drain of such a record while its
  retry is pending (the retry is dropped, its logger discarded, and the
  record ends with the stored error log); a cancel of a first attempt in
  `starting`, landing before the attempt's first stamp check and while its
  `log_start()` is held (each ends with no log, its logger discarded with
  nothing in the log directory, no `EvalState` registered, `started()`
  raising `TaskEndedError(log=None)`, and the task in the
  cancelled-before-starting set); `run_samples=False` with no cancel and
  with a cancel while `log_start()` is held (ends with the `started` log,
  never retried, no `EvalState`, `started()` raises
  `TaskEndedError(log=<that log>)`); `run_samples=False` with a task-level
  and a sample-level sandbox, for a seed task, an added task, and a retry
  after an injected `log_start()` failure: spies on
  `ensure_model_controller` and the provider's `task_init` record no call,
  and each record is startable as soon as it is admitted, with no setup
  job; an exception propagated under `debug_errors`; an added task starts while its creator runs
  under `eval()` and `eval_set()` (the probe above, as a test bounded with
  `fail_after`); under eval-set selection mode in-process; task ids: a
  `ResolvedTask` added in a run with two models, added twice, and listed
  twice in one call, and a `PreviousTask` added the same ways, each raise
  `ValueError` and leave nothing of the batch queued, configured or listed,
  while the earlier record is still listed and cancellable; a `Task` in a
  two-model run adds two records with distinct ids; a single `ResolvedTask`
  in a one-model run still runs (`tests/test_enqueue_task.py:147`); an
  in-run retry keeps its record's id; ordering at
  `max_tasks == 1` (sequence-major per addition, `next_tasks()` batch ahead of
  concurrent enqueues); configuration errors raise at the call; admission
  failure ends one task; sample selection under
  `sample_id=["parent:1", "B:1"]`: a parent that enqueues A and then B
  (consecutive calls, and one call with both) runs no sample of A even when
  A's dataset has a literal `B:1` sample, and no error is raised at either
  `enqueue_task()` call or at A's admission; a literal namespaced id
  (`user:cybergym/arvo_6008`) with no task of that name still selects that
  sample; a `task:id` selector for an unknown task with no such literal id
  in an added task fails that task's admission with the `slice_dataset`
  error and its handles report it; the logger's recorded `sample_id` and
  the sandbox setups requested match the samples the attempt runs; a setup failure ends only the tasks that need it,
  with error logs and `on_task_start`/`on_task_end`; the retry rule (a shared
  broken key set up at most once per attempt number); a sandbox-free task
  starts while a setup blocks; an ended record no longer references its
  `ResolvedTask`, options or dataset; an added task whose admission fails in
  `slice_dataset()` (directly, and re-raised from another exception so the
  failure is chained) keeps its record and handle alive with
  `TaskEndedError.error` of the same type and message, the traceback is in
  the run's log output, and a weak reference to that task's otherwise
  unreferenced dataset is dead after `gc.collect()`.
- `tests/test_task_source.py`: Ctrl-C (cancelling the run) while
  `next_tasks()` blocks returns the completed logs, at `max_tasks` 1 and > 1;
  the existing live-injection test also passes for a plain task list with
  `enqueue_task()`; `next_tasks()` returning `[]` ends the source at
  `max_tasks` 1 and 2 without calling the resolver (a resolver spy, and a
  working directory holding an unrelated task file that must not load).
- `tests/test_sample_source.py`: a mid-run configuration through
  `setups.ensure()`; a failure fails only that task.
- `tests/test_task_cancel.py` and `tests/_control/test_ctl.py`: queued rows
  in `GET /tasks`; cancel and drain of a queued task (no log, its unshared
  waiting setups dropped, its initialised logger
  discarded with nothing in the log directory); `score`/`error` answer 409;
  `dry_run`; while an earlier record's `logger.init()` blocks, a later
  record is listed and can be cancelled, and the blocked record cancelled
  during admission ends with no log once admission finishes; with a
  `TaskSource` whose `next_tasks()` enqueues a task and then blocks on an
  `anyio.Event` nobody sets, a cancel and a drain from another coroutine,
  each before, during (a `logger.init()` held on an event) and after the
  task's admission, end the record while `next_tasks()` stays blocked: its
  `ended` event is set, it leaves `GET /tasks`, `logger.discard()` runs
  exactly once when a logger was initialised (a recorder spy; no recorder
  entry, temporary file or log-directory file remains), and its handle's
  `started()` raises `TaskEndedError(log=None)` and `result()` returns
  `None` (each bounded with `fail_after`); a second cancel of the same
  record, in each of `admitting_cancelled`, `starting_cancelled`,
  `finalizing` and `ended`, changes nothing; a cancel
  between dispatch and `register_eval` stops the attempt before it
  registers (the result carries `changed: true`, `queued: true`); a run
  cancelled, and a cancel or drain, while a task waits in the queue for its
  retry keep the prior attempt's error log (the existing between-attempts
  test, extended to the run-cancel case) and add nothing to the
  cancelled-before-starting set; under `eval_set(retry_immediate=False)`,
  while the admission of the second round's record is blocked, the task is
  listed once (queued, with its first round's attempts), selectors resolve
  it, and cancel and drain end the queued record rather than answering
  "task already finished" from the first round's `EvalState` (a different
  case from an in-run retry after a registered attempt, which has no queued
  record).
- `tests/test_eval_set.py`: with seed tasks A and B and B cancelled while
  queued, the eval set reports failure and its message names B, under
  immediate retries and under the legacy retry loop (with A first erroring,
  so a second attempt runs A only and never B); every seed task cancelled
  while queued reports failure, not success; selection mode with one and
  with all selected tasks cancelled returns `False`; a run cancelled while
  a seed task is still queued raises `KeyboardInterrupt`; a later
  `eval_set()` on the same directory runs B.
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

Each step is one PR and leaves `main` correct. Steps 1-4 are this design;
step 5 is [task-handles.md](task-handles.md). The order differs from
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
   `util/_sandbox/environment.py` (`supports_sandbox_setup`, docstrings),
   `util/_sandbox/docker/docker.py` (declares support; its local-image
   message through `sandbox_setup().print()`, which prints as today until
   step 4 routes it; `resolve_config_environment` through
   `setup_config_path`), `util/_sandbox/docker/util.py`
   (`setup_config_path`, used by `ComposeProject.create`),
   `docs/extensions-sandboxes.qmd`; the working-directory warning. The
   display suspension stays for every provider in this step. Tests:
   `tests/util/sandbox/test_sandbox_setup.py`, Docker tests.
2. **Provider state per setup.** `_eval/run.py` (`SandboxManager` runs each
   `task_init` in the chained context and records bindings, contexts and the
   per-sample key map), `_eval/task/sandbox.py` (`sandboxenv_context` applies
   bindings), `_eval/task/run.py` (passes them). Tests: bindings across
   configurations, empty seed, cleanup per configuration. Fixes the E2B,
   Modal and Daytona leaks and `LookupError` with no inspect_sandboxes
   release. Independent of step 1.
3. **One queue, one dispatcher, queued tasks in the control channel.**
   `_eval/task/enqueue.py` (`RunQueue`, `TaskRecord` and `TaskPhase` with
   the checked transitions; `enqueue_task()` still
   returns `None`), `_eval/run.py` (`configure_task()`, `admit_task()` with
   sample selection and logger construction, and no model-controller or
   setup startup under `run_samples=False`; `dispatch_tasks()` with
   today's `run_one` and retry items,
   `eval_run` owns the queue; `TaskInjection`/`PreparedFeed`/`_empty_feed`
   removed), `_eval/eval.py` (one `eval_run` call), `_eval/task/run.py`
   (`_enqueue_source_tasks`; `TaskRunOptions.on_registered`, called after
   `register_eval`), `_control/queued_tasks.py` (new),
   `_control/cancel.py`, `_control/state.py`, `_control/__init__.py`,
   `_cli/ctl/_task.py`, `_eval/evalset.py` (queued cancels in success,
   retries and selection mode); `docs/task-source.qmd`; `design/task-source.md`
   ("Live injection"), `design/ctl/task-drain.md` ("Out of scope"),
   `design/sample-source.md` (the `SandboxManager` notes). Records register
   with the control channel at `add`; admission runs as a background job.
   Setups still run at
   admission inside the dispatcher, as the live path does today. Tests:
   `tests/test_enqueue_task.py`, `tests/test_task_source.py`,
   `tests/test_task_cancel.py`, `tests/_control/test_ctl.py`,
   `tests/test_eval_set.py`. Needs steps 1
   and 2.
4. **Setup beside the dispatcher.** `_eval/sandbox_setups.py` (new; replaces
   `SandboxManager`), `_eval/run.py` (start rule, `setup_error`),
   `_eval/task/run.py` (setup-failure attempt path, `setups.ensure()`),
   `util/_subprocess.py` and `util/_sandbox/setup.py` (forwarding output and
   `SandboxSetup.print()` to the display and the failure buffer), suspension only for providers that do not declare support,
   `_control/queued_tasks.py` (`setup` field). Tests: setup failure, retry
   rule, sandbox-free start, no setup under `run_samples=False`, output
   forwarding, cancel dropping waiting jobs.
   Needs step 3.
5. **Task handles**, designed in [task-handles.md](task-handles.md) (its
   "Implementation plan" lists the files and tests). Needs step 3 and the
   separate change that gives anonymous dynamic samples unique ids;
   independent of step 4.

Follow-ups in provider repositories, none a gate for any step above:
inspect_sandboxes declares `supports_sandbox_setup` for E2B, Modal and
Daytona, with E2B's template warm-up reading `sandbox_setup().task_dir`
(feature-detected, so its dependency floor does not move) and the
per-provider cleanup tests above; inspect-podman adopts it for its compose
lookup and auto-compose file; UKGovernmentBEIS/inspect_proxmox_sandbox
adopts it for `PROXMOX_CONFIG_FILE`, or warns when a set
`PROXMOX_CONFIG_FILE` is not found.

## Open questions

None. The questions raised by this design are decided (Ransom,
2026-11-03) and recorded where they apply (the two about handles are in
[task-handles.md](task-handles.md#open-questions)):

- A provider that has not adopted `sandbox_setup()` resolves relative paths
  in Python against the launch directory, with a warning when the task
  directory differs ("Providers that have not adopted it").
- Seed setups run beside the dispatcher like every other setup, with build
  output streamed to the display's console ("Display and output").
- Task-prefixed `sample_id` selectors resolve at admission against the task
  names added so far; a task a selector names must be enqueued before its
  creator awaits ("Sample selection waits for admission", and "Sample
  selection" under "Compatibility and migration").

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
- `TaskSource` under `eval_set()` (see `design/task-source.md`).
- A stale `retry_pending` flag after an unregistered final retry. When a
  registered attempt A errors and its last retry B fails before it
  registers, `run_one` clears the flag using B's eval id
  (`src/inspect_ai/_eval/run.py:1021`), which `clear_eval_retry_pending`
  ignores as unregistered (`src/inspect_ai/_control/eval_state.py:870-889`),
  so A stays flagged: a task cancel or drain offers to abandon a retry that
  is not coming, and `score`/`error` reject the task as between attempts.
  Today's behaviour, unchanged here.
- The log a retry ends with when it is abandoned while inside a startup
  `await` before it registers: if that startup write then fails, or with
  `run_samples=False` returns the `started` log, `run_one` queues no further
  retry but stores the returned log over the one kept before the retry was
  queued (`src/inspect_ai/_eval/run.py:932-937`, `:1037`), and the retry's
  file can stay in the log directory. Today's behaviour, which this design
  keeps for records in `starting` and `running` alike.
