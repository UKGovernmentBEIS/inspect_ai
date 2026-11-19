# Task dispatch: one queue for every run, and tasks added while it runs

## Overview

Every eval run gets one task queue and one dispatcher. Seed tasks, tasks
added with `enqueue_task()`, tasks a `TaskSource` returns, and task retries
all go through the same queue, and a task starts as soon as a `max_tasks`
slot is free, under `eval()`, `eval_set()` and eval-set selection-mode
workers alike. Adding a task checks its configuration and sample selection
at once, so a mistake raises to the caller (a model's adaptive-concurrency
setting is the exception: it is checked when the task first needs its
model), and the task's log file is
created only when the task starts. Every task in the queue, including one
that has not started, is listed by `inspect ctl task list` and can be
cancelled, and stays listed as finished once it ends.

Each task sets up its own sandboxes (a provider's `task_init`) when its
attempt starts, the way a `SampleSource` task sets up the samples it adds
today. The dispatcher never waits for an image build, so a task without
sandboxes starts at once; a task holds its `max_tasks` slot while it builds;
and a setup failure ends only that task, with its error log, and is retried
like any other task failure. Setup no longer changes the process's working
directory or environment: Inspect makes relative config paths absolute
against the task directory before any provider sees them, and every
provider call runs in the launch directory, as `sample_init` does today.
The `ContextVar` values a provider binds in `task_init` are captured per
setup, so each sample and each `task_cleanup` sees the state its own
configuration's `task_init` produced.

[task-handles.md](task-handles.md) builds on this queue: handles that let a
running task cancel the tasks it adds, send samples to a task fed through
its handle and wait for that task's log.

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
- A task added while `TaskSource.next_tasks()` blocks starts when the call
  returns, ahead of the batch it returned; today, at `max_tasks == 1`, the
  batch runs first.
- A task's sandboxes are set up inside its attempt, after its task-start
  hooks and before its first sample, instead of for the whole batch before
  any task starts. A task without sandboxes starts while another task
  builds, and a task holds its `max_tasks` slot while its own `task_init`
  runs. `on_task_start` now runs before the task's sandboxes are set up.
- During a task's sandbox setup the full-screen task display is suspended
  until the setup finishes, as today, while other tasks keep running
  (today this overlap is limited to live `TaskSource` injection and
  `SampleSource` additions).
- A task's log file, temporary file and sample buffer database are created
  when the task starts, not when the run starts, so a long queue holds none.

API:

- `enqueue_task()` stays synchronous and returns handles
  ([task-handles.md](task-handles.md#the-handle-api)); a call on the run's
  event loop that ignores the result, as every such call does today, is
  unchanged. It stays synchronous because adding a task awaits nothing and
  an async version would silently break every existing call that does not
  await it (the coroutine would never run, so the task would never be
  added).
- `enqueue_task()` called from a worker thread that copied the run's context
  (for example through `anyio.to_thread.run_sync`), which today buffers the
  task, raises `RuntimeError` ("Run shapes and what is refused"). The
  worker calls `anyio.from_thread.run_sync(lambda: enqueue_task(...))`
  instead, which runs it on the run's loop.
- `enqueue_task()` raises at the call for every selection error and for
  every error in the configuration checks made while adding (id
  uniqueness, the eval-level overrides, the epoch reducer against the
  epoch count, the `SampleSource` prerequisites), and nothing of that call
  is added. Model-concurrency settings are not among them: an added task's
  adaptive-connections setting is validated in its attempt ("Model
  controllers"), and a bad one ends that task with its error log.
- `task:id` sample selectors resolve when a task is added, against the task
  names of the run so far and of that call: tasks whose selectors name each
  other must be added in the same `enqueue_task()` call.

Failure reporting (the run's outcome changes only where today it fails or
hides a problem):

- A task whose log cannot be initialised ends with an error log and is
  retried, like a failed `log_start()`, and each failed attempt is reported
  to the run's `TaskSource`; today a seed task's failure raises from
  `eval()`.
- An attempt whose log storage failed after its log was initialised (a
  failed prior-log seed, header flush or final write) is reported to the
  run's `TaskSource` with the unwritten error log that `eval()` already
  returns for it; today it is not reported, so a source whose
  `next_tasks()` waits for each task's report waits forever on a task
  whose final attempt failed this way.
- An attempt stopped by its own abort or retry request before it wrote a
  final log is reported to the run's `TaskSource` with its unwritten "Task
  cancelled by user" log, a task cancelled while queued included; today
  none reaches `task_complete`. The location of such a log can
  name a file the attempt never finished or never wrote. How often a source
  hears about a task is unchanged: once per attempt ("Reporting to the
  source").
- A sandbox setup error ends only the task that needs that configuration,
  with its error log, and the task is retried under `task_retry_attempts`;
  its retry runs `task_init` again. Today a setup error fails the whole run,
  and under `eval_set()` it raises out of the round with no retry.
- Ctrl-C while `TaskSource.next_tasks()` blocks is handled like a Ctrl-C
  during a task: the logs so far are kept, and `eval()` returns them on
  asyncio; on trio, `run_main` still raises `KeyboardInterrupt` once the run
  has finished, as it does for a Ctrl-C during a task. Today the call is
  outside any `eval_run` and `KeyboardInterrupt` propagates from it.
- Adding a task id already in the run raises `ValueError`.
- A task cancelled before it registered with the control channel, while
  queued or in its attempt, is aborted, as `inspect ctl task cancel` aborts
  a running task, and ends with today's "Task cancelled by user (abort)"
  error log; a queued one aborts before it opens a display row or writes a
  file, so its log is held in memory with an empty `location`. When its
  attempt had already returned an error log, it ends with that log and no
  retry. `eval()` returns the log with the other logs, so an eval set or
  selection-mode worker that requested the task reports failure. Under
  `eval_set(retry_immediate=False)` the next round runs such a task again,
  as it does a running task cancelled today.
- `debug_errors=True` raises task errors at every `max_tasks`.
- The control channel lists queued tasks and cancels, drains, pauses and
  resumes them.

Could change what an eval computes:

- **A third-party provider's `task_init`, `task_init_environment` and
  `task_cleanup` run in the launch directory**, the directory its
  `sample_init` already uses: Python-level relative paths and the default
  working directory of the subprocesses it starts both resolve there (see
  "Setup does not change the process's directory or environment" for the
  effect per provider).
- **A sample's relative config path** (a compose file, a Dockerfile, or a
  `ComposeConfig` build context) that exists under the task directory is used
  from the task directory by `task_init` and `sample_init` alike. Today
  `task_init` used the task directory's file (through the `chdir`) and
  `sample_init` the launch directory's, so a run launched from a directory
  holding a file of the same name built one image and ran samples on another.
- **A `ComposeConfig` build context on Modal and Daytona** (decision: Ransom,
  2026-11-11: task-relative for every provider). Their converters resolve a
  relative or omitted context only at sample time, against `Path.cwd()`, so
  a run launched from a directory other than the task's builds the launch
  directory's Dockerfile today. With contexts made absolute against the task
  directory, a run whose launch directory also holds a Dockerfile at the
  same relative path (or at its root, for an omitted context) now builds
  the task directory's Dockerfile, and a context found only under the task
  directory now builds instead of failing. An author who wants the launch
  directory's writes an absolute build context.
- **A task-level relative string sandbox config** is resolved like a
  sample's: made absolute against the task directory only when the file
  exists there. So a relative path missing under the task directory but
  present in the launch directory now resolves against the launch
  directory, where today `resolve_task_sandbox`'s unconditional join gives
  an absolute path to the missing file and setup fails. The same rule keeps
  a task-level inline-JSON string config, which the join rewrites today.
- **Which `ContextVar` values a sample sees**: its own configuration's setup
  state rather than the last setup's.
- **`os.environ` during setup** no longer holds `task_init_environment`
  values; only Docker returns any, and it receives them directly. A
  provider outside Docker's class family whose `task_init_environment`
  returns values is refused before its `task_init` ("Setup does not change
  the process's directory or environment").

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
- No process-wide working-directory or environment change across an `await`;
  per-setup provider state, with no provider release needed.

Non-goals:

- Building sandboxes outside the task's `max_tasks` slot, and retrying a
  setup apart from its task's own retries (setup in background jobs; see
  "Alternatives considered").
- `TaskSource` under `eval_set()` or `eval_retry()` (still rejected; see
  [task-source.md](task-source.md#eval_set-support--feasible-but-only-pays-off-for-deterministic-sources)).
- Recording which task added a task, and selection-mode handling of added
  tasks ("Interactions" says where this design touches them).
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
(`eval.py`: once, under the attempt's model, when called inside a running
attempt; else once per run model) and buffers into the `TaskEnqueuer`; it
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
On trio, the synchronous entry points run under `run_main`
(`src/inspect_ai/_util/_async.py`), whose `_trio_cancel_on_sigint` turns the
first SIGINT into a cancellation of the whole run and raises
`KeyboardInterrupt` after the run returns, even when the task screen
absorbed the cancellation and the logs were written; on asyncio,
`asyncio.run()` returns what the absorbed run returns. This design keeps
that wrapper.

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
  directory in `sample_init`. Docker's compose commands (`compose_up`,
  `compose_build`, `compose_pull`, `compose_services` in `docker/compose.py`)
  pass no `cwd`, so `compose_command` runs them in the process directory;
  only some cleanup commands set it to the compose file's directory. Compose
  itself resolves the paths a compose file names (build contexts,
  `env_file`, the project's `.env`) against the project directory, which is
  the compose file's directory, whatever the working directory.
- A provider's own lookups. Surveyed (inspect_sandboxes, inspect-podman,
  inspect_proxmox_sandbox, inspect_k8s_sandbox, inspect_ec2_sandbox,
  inspect_vagrant_sandbox checkouts beside this repo):
  - E2B warms its template cache in `task_init` from a `ComposeConfig`, whose
    relative build contexts fall back to `Path.cwd()`; its `sample_init`
    resolves the same config in the launch directory. Daytona and Modal
    resolve them only in `sample_init` (`create_single_service_params` and
    `convert_compose_to_modal_params`), against `Path.cwd()` when there is
    no compose-file path, so with a `ComposeConfig` they build from the
    launch directory.
  - Podman, for a missing config, looks for a compose file in `os.getcwd()`
    and writes its generated compose file there, in `task_init` and again in
    `sample_init`; it passes absolute paths to its subprocesses. The
    generated file has one fixed name per directory: an inline
    `ComposeConfig` is written to `<cwd>/.compose.yaml` (`ComposeProject.create`
    in `inspect_podman/util.py`), a missing config reuses that file
    (`resolve_compose_file` in `config.py`), and a failed `task_init` deletes
    every generated file it recorded (`project_cleanup_shutdown(True)` in
    `podman.py` and `cleanup.py`). Two Podman calls in one directory therefore
    share one file: concurrent `sample_init` calls with different inline
    configs already overwrite each other's in the launch directory, and a
    `task_init` that overlaps running samples (the live path, a
    `SampleSource` addition) overwrites or, on failure, deletes theirs when
    the task directory is the launch directory. Inspect's own Docker
    provider writes each project's generated file under its own name in a
    central directory (`auto_compose_file` in `docker/config.py`), so it has
    no such collision.
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
   (`RunQueue.end`), with the log its last attempt returned, or `None` when
   dispatch ended first or, for a fed task, when its channel closed before
   any sample was sent (task-handles.md, "Closing").
3. **A record is visible to the control channel from the moment it is
   added, and after it ends**: in the queued registry until one of its
   attempts first calls `register_eval`, then through its `EvalState`, as
   today; a record that ends without registering gets a terminal
   `EvalState` before it leaves the registry.
4. **A task's logger owns a recorder entry only while an attempt runs.**
   `task_run` calls `logger.init()` when the attempt starts; `log_finish` or
   `discard()` releases it when the attempt ends. A queued record or a
   pending retry holds nothing to release.
5. **Only the run's event loop changes the queue, in synchronous steps**, so
   it needs no lock.
6. **Once dispatch ends, nothing more starts.** In one synchronous step the
   queue closes (no additions, no retries published) and every record not yet
   started ends, before the attempt group joins its attempts.
7. **No `os.chdir` or `os.environ` write across an `await`.** Sandbox
   setup, key resolution and cleanup make none. The two directory changes
   left in a run are synchronous blocks: the one around a task's
   `TaskLogger` construction and today's loading of a task from a file
   ("Setup does not change the process's directory or environment").
8. **Each `task_cleanup` sees what its own `task_init` bound**, and a sample
   sees its configuration's bindings unless it bound its own.

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
  resolved. Tasks a `TaskSource` callback returns then are dropped with a
  log line instead ("Source returns after close are dropped").
- `enqueue_task()` off the run's event loop (a worker thread that copied the
  run's context and calls it there, with no event loop or inside its own
  `anyio.run()`): `RuntimeError`. `_require_run_loop(queue)` compares
  `anyio.lowlevel.current_token()` with the token the queue recorded at
  creation, and refuses the call when they differ or when there is no loop
  (`current_token()` then raises `NoEventLoopError`). Today such a call
  buffers the task. A worker calls it through
  `anyio.from_thread.run_sync(lambda: enqueue_task(...))`, which runs it on
  the run's loop.
- Adding a task id the run already holds: `ValueError` ("Task ids").
- Handle misuse: see
  [task-handles.md](task-handles.md#what-is-refused).

### The run queue

`src/inspect_ai/_eval/task/enqueue.py` replaces `TaskEnqueuer` with
`RunQueue`; `run.py` loses `TaskInjection`, `PreparedFeed`, `_empty_feed`
and `prepare_options`; `eval.py` loses `run_batch`, `run_batches` and
`inject_next`. `eval_run` creates the queue, binds it in the `ContextVar`
that `enqueue_task()` reads, adds the seed and runs the dispatcher.

```python
TaskPhase = Literal["queued", "attempt", "ended"]
TaskReached = Literal["added", "row_opened", "registered"]   # ordered

@dataclass(eq=False)
class TaskRecord:
    task_id: str
    task: str                         # task name; kept after the record ends
    model: str
    index: int                        # result order: seed first, then arrival
    options: TaskRunOptions | None    # configured at add, logger constructed; released at end
    phase: TaskPhase = "queued"
    reached: TaskReached = "added"    # furthest milestone of any attempt; kept across retries
    abort_requested: bool = False     # a cancel while queued and never registered; read by start_attempt
    attempt_cancel: TaskCancel | None = None        # the current attempt's, from start_attempt until run_one publishes a retry or ends the record
    attempt_scope: anyio.CancelScope | None = None  # the scope its `apply` cancels; set and dropped with it
    log: EvalLog | None = None        # the log run_one stored; the final log once ended
    ended: anyio.Event = field(default_factory=anyio.Event)

class RunQueue:
    run_id: str
    closed: bool
    task_names: list[str]             # eval_set_tasks, then each commit's names
    wake: Wake                        # rung by every phase change and addition, waiters or not
    screen_open: bool                 # set while the dispatcher is inside the task screen
    def add(self, resolved: list[ResolvedTask]) -> list[TaskRecord]
    def find(self, task_id: str) -> TaskRecord | None
    def cancel(self, record: TaskRecord) -> None
    def end(self, record: TaskRecord, log: EvalLog | None) -> None
    def close(self) -> None           # idempotent
    def end_unstarted(self) -> None   # ends every queued record with its stored log
    def end_all(self) -> None         # ends every record not yet ended
```

`reached` records how far the record's attempts have got, in order:
`row_opened` when `task_run` opens the task's display row
(`display().task(...)`, which every display mode does), `registered` when
`task_run` calls `register_eval` (after the row). `task_run` moves it forward
through `on_row_opened()` and `on_registered()`, never back, so a retry
whose attempt starts after a registered attempt still reads `registered`.

[task-handles.md](task-handles.md#what-the-handles-add-to-the-run-queue)
adds a sample channel and a creator to the record, and one start rule to the
dispatcher.

#### Adding tasks

`RunQueue.add` is synchronous. It first calls `_require_run_loop` and
raises `RuntimeError` if `closed`. Then, for the whole batch before
anything is committed:

- **Task ids.** An id that a record of this run already holds, or that
  repeats in the batch, raises `ValueError` ("task id '<id>' (task '<task>')
  is already in this run: a ResolvedTask or PreviousTask keeps its id, so it
  can be added once, and from outside a running task only in a run with one
  model; pass the Task to run it once per model"). A `Task` resolves to a new
  id per model, but a `ResolvedTask` or `PreviousTask` keeps its id, and
  `_resolve_enqueued_tasks` resolves an input added outside an attempt once
  per run model, so today such copies run under one id that the control
  channel folds into one. Added inside an attempt it resolves once. The seed paths that pass resolved or
  previous tasks (`eval_set()` rounds, selection workers, `eval_retry()`)
  resolve each once, so this never fires for them.
- **Configuration**, in `configure_task()` (`run.py`): today's
  `prepare_options` body without its awaits. It assigns missing seed sample
  ids, checks id uniqueness, applies the eval-level overrides, runs the
  `SampleSource` prerequisite checks, resolves the task's `task:id`
  selectors (`resolve_task_sample_ids`) against the run's task names plus
  this batch's (see "The run's task names" below), and constructs the
  `TaskLogger` inside `with chdir(task_run_dir(task))`, as `prepare_options`
  does today: the constructor reads `git_context()` and
  `cwd_relative_path()` against the process directory. With
  `logger.init()` moved into `task_run`, that block has no `await`, so no
  other coroutine sees the change (worker threads can, as today and as for
  task loading). The constructor slices the dataset with the resolved
  selection with today's `slice_dataset` rules
  (`src/inspect_ai/_eval/task/util.py`), so for a static dataset a
  selection that matches no sample raises `PrerequisiteError` here, while a
  literal id it lacks beside others that match only logs "sample id '<id>'
  not found"; a dynamic dataset (a `SampleSource`) is filtered with neither.

Any error raises to the caller and nothing of the batch is added. Then, in
the same step, it commits: adds the names to the run's set, orders the
batch sequence-major (the order `run_batches` uses at `max_tasks == 1`),
creates each record in `queued` at the end of the queue, registers it with
the control channel, grows the display's task count (except for the seed,
which the task screen counts when it opens) and rings `wake`.

**Model controllers.** `ensure_controllers(resolved)` awaits
`ensure_model_controller` for each task's primary model with the task's
generate config merged with the run's, as `prepare_options` does today, and
does nothing under `run_samples=False`. `eval_run` awaits it for the seed
before adding it, so the seed's controllers exist before any build, and a
bad adaptive setting on a seed task (`adaptive_connections=0`, which
`GenerateConfig` accepts but `AdaptiveConcurrency` rejects) raises from
`eval()` as today. An added task gets no eager call (decision: Ransom,
2026-11-12): its controller is created lazily, as for every model outside
the seed today, on its model's first `generate`, and no caller of
`RunQueue.add` awaits anything first. A bad adaptive setting on an added
task therefore fails inside its attempt, within `task_run`'s main `try`:

- With no `max_samples`, `task_run` calls `create_sample_semaphore`
  (`src/inspect_ai/_eval/task/run.py`) before `register_eval`. Its adaptive
  branch builds a `DynamicSampleLimiter` from
  `resolve_adaptive(generate_config.adaptive_connections)`
  (`src/inspect_ai/util/_concurrency.py`), which raises the
  `ValidationError` before the task registers and before its sandboxes are
  set up. The
  `except` there writes the task's error log, `run_one` retries it under
  `task_retry_attempts` (each retry fails the same way) and sibling tasks
  go on; the record ends without registering ("Phases and cancelling").
- With an explicit `max_samples` the semaphore is a `ResizableLimiter` and
  nothing resolves the setting until each sample's first `generate`
  (`Model._connection_concurrency` calls `resolve_adaptive()`), so every
  sample errors there, under the task's `fail_on_error` like any sample
  error.

Both were checked by running a two-sample `mockllm` task with
`adaptive_connections=0` with the eager call stubbed out: with no
`max_samples` the log has status `error` and no samples; with
`max_samples=1, fail_on_error=False` both samples carry the validation
error. The cost: an `inspect ctl config --max-connections` retune made
before an added task's first `generate` (while it is queued or building its
sandboxes) is dropped with today's "not using adaptive connections" warning
when no other task has created that model's controller, and the controller
is created later at its configured ceiling. A task fed through a handle
escapes this only when its connection pool already has a controller that
the retune reached: usually it runs under its creator's model, whose
controller the seed's eager call or the creator's own generates created.
A rollout task that sets its own `model`, or whose creator is itself an
added task that has not generated yet, can resolve to a pool with no
controller, and then has the same cost as any other added task.

Creating an added task's controller eagerly, in the synchronous add, would
close that gap but move a bad adaptive setting's failure from the added
task to whoever added it (for a `next_tasks()` return, the whole run), so
it is not done (decision: Ransom, 2026-11-18). A follow-up closes the gap
instead, for added tasks and for every controller created after a retune:
it remembers each `--max-connections` retune and applies it when a
controller is created, with controllers still created lazily ("Not this
design").

**The run's task names.** `RunQueue` is created with the names of
`eval_set_tasks`, which `_eval_async_inner` already receives: the whole eval
set's tasks, including those outside this run when an `eval_set()` round
retries a subset or a selection worker runs some of them. Both of today's
paths seed their name list this way (`eval_run`'s `task_names` and
`_eval_async_inner`'s list for `run_batch`), so a selector `other:1` naming
an eval-set task outside the run still matches no sample of this task
instead of being read as a literal id. Each commit then adds its batch's
names.

Callers: `eval_run` for the seed (errors raise from `eval()`, as today);
`enqueue_task()`, after resolving its argument with
`_resolve_enqueued_tasks` (errors raise to its caller); `_enqueue_source_tasks`,
synchronous as today, for `TaskSource` callback returns; and the dispatcher
for a `next_tasks()` batch (errors end the run, as today).

**Source returns after close are dropped.** `_enqueue_source_tasks` serves
`task_complete`, `sample_complete` and `sample_abandoned`, which can run
after dispatch has closed the queue: an attempt cancelled by Ctrl-C writes
its `cancelled` log and notifies its source in shielded cleanup, and a
callback with no checkpoint returns its follow-ups anyway. So
`_enqueue_source_tasks` reads `queue.closed` first, and when it is set logs "dropping <n> task(s) returned by
the task source after the run stopped" and returns without adding; otherwise an add error there would
escape `notify_task_source`'s callback handler, and `_run_task_screen`,
which absorbs only cancellation, would replace the run's outcome (the logs
after Ctrl-C, a latched cancellation, a `debug_errors` error) with it. The
dispatcher's `next_tasks()` add applies the same check, though it runs in
the loop before the `finally` closes the queue. The direct `enqueue_task()`
refusal after close, and add errors while the run is open, are unchanged.

Selection is resolved at the call because it is synchronous, so its errors
reach the caller. The cost is the batch boundary: today a whole buffered
batch's names were known before any selector resolved, so a creator that
added A, then B, with `sample_id=["parent:1", "B:1"]`, ran no sample of A.
Now A resolves first and reads `B:1` as a literal id of A. Under today's
`slice_dataset` rules, if that leaves a static A with no matching sample it
raises at A's call; if A has other matches it logs "sample id 'B:1' not
found" and runs them; a dynamic A is filtered silently. Tasks whose
selectors name each other are added in one call. The seed is one call, so its selectors resolve as
today; a `next_tasks()` batch is one call too.

#### Phases and cancelling

| from | event | to | made by |
| --- | --- | --- | --- |
| (none) | `add` | `queued` | `RunQueue.add` |
| `queued` | the dispatcher drops a retry carrying the abandon stamp, or dispatch ends | `ended`, with the stored log (`None` if none) | dispatcher; `end_unstarted()` |
| `queued` | the dispatcher picks it (the counted pick or the uncounted pass) | `attempt` | `start_attempt`, the dispatcher's synchronous start step |
| `attempt` | `run_one` publishes a retry | `queued`, with the attempt's log stored | `run_one` |
| `attempt` | `run_one` returns or raises with no retry | `ended`, with the log `run_one` stored (`None` if none) | `run_one` |
| any but `ended` | the attempt group has exited | `ended`, with the stored log | `end_all()` |

`queued` holds a first attempt and a retry alike, both waiting for a pick; a
retry is the one with a stored `log`. `attempt` means the dispatcher has
picked the record and its `run_one` is scheduled or running. The move into
`attempt` is the dispatcher's pick, not `run_one`'s first statement:
`start_attempt(entry, counted)` ("Starting an attempt" in § The
dispatcher), in one synchronous step, removes the entry from the pending
list, counts it against `in_flight` and its model's count when `counted`
(the ordinary pick; the uncounted pass does not count it), moves the record
into `attempt`, creates the attempt's fresh `TaskCancel` and cancel scope
and stores them on the record, requesting `abort` on the new `TaskCancel`
when `abort_requested` is set, and schedules `run_one` with them. So a
cancel of a record that has never registered sees one of two states only (a
record with `reached == "registered"` takes the `cancel_task` route below
first, whatever its phase). A record still `queued` has not been picked for
its next attempt: it gets `abort_requested` and the uncounted start. A record
already picked for its current attempt, including one whose `run_one` has
not yet run its first statement, is an attempt that has not registered: the cancel goes to the pair
`start_attempt` stored on the record, the attempt aborts at `task_run`'s
explicit first checkpoint, and it keeps its counted slot until it ends,
exactly as an aborted running task does today; no slot is converted. In that
window the task holds its slot until its abort finishes, the same as a task
cancelled a moment later, after its `run_one` has started; its report to
the `TaskSource` runs inside `_run_task`, before the slot is released, so a
`task_complete` for it that waits on another task's report at
`max_tasks=1` waits as it does today for any attempt that ends while holding
the only slot. Only `run_one`
(and `end_all()` after the group exits) ends a record in `attempt`:
`end_unstarted()` and, in task-handles.md, the empty-channel close act on
`queued` records only, so a scheduled `run_one` always has its attempt to
run. A cancellation of the attempt group right after the pick does not skip
`run_one`: an AnyIO task started with `start_soon` runs its synchronous
body up to its first checkpoint even when its group is cancelled first
(checked on asyncio and trio). Such a `run_one` is cancelled at its first
`await` and leaves through its exception exit, which ends the record
(below), so no record stays in `attempt`.

**`run_one`'s exception exit ends its record.** When `_run_task` raises
(a cancellation, or an error under `debug_errors`), `run_one` discards an
unfinished logger entry, as today, then calls `RunQueue.end(record,
record.log)` in the same step, before re-raising. That settles every handle
wait on the record (task-handles.md), so a creator sample whose shielded
cleanup awaits `result()` on a fed task that raised is released, and the
attempt group's join, which waits for that cleanup, can finish; the original
exception still propagates. `end_all()` after the group exits stays as the
fallback for a record whose `run_one` never reached either exit.
Registration is `reached`, not a phase: an attempt that has not reached
`register_eval` is initialising the log, seeding prior samples and writing
the header. A retry whose attempt starts after a registered attempt has
`reached == "registered"`, so it is already out of the queued registry.
Handles and the control channel show `queued` until the first registration,
then the `EvalState`.

`RunQueue.cancel(record)`, used by the control channel's cancel or drain of a
queued row and by a handle's `cancel()`, is synchronous:

- `ended`: nothing.
- `reached == "registered"`: today's control-channel task cancel,
  `cancel_task(task_id)` (`_control/cancel.py`), which aborts a running
  attempt or abandons a pending retry (the dispatcher drops it and the
  record ends with its stored log), exactly as `inspect ctl task cancel`
  does today.
- `queued`, never registered: an attempt that aborts before it starts.
  `RunQueue.cancel` records the intent, `record.abort_requested = True`,
  and rings `wake`; it creates no `TaskCancel` or scope. The dispatcher
  starts the record on its next pass ("Start rule": a record with
  `abort_requested` starts at once, uncounted, paused or not);
  `start_attempt` creates the attempt's fresh `TaskCancel` and scope as for
  any attempt and, seeing the flag, requests `abort` on the new pair before
  `run_one` runs, so `_run_task` aborts at its first checkpoint (below). The record keeps
  no special outcome: it ends through the abort path like an attempt
  aborted in its first moments.
- `attempt`, never registered: the attempt's own abort,
  `record.attempt_cancel.request("abort")`, the call `inspect ctl task
  cancel` makes on a running task's `TaskCancel`. This includes a record
  picked by the counted pick whose `run_one` has not yet run its first
  statement: `start_attempt` stored the pair in the step that moved it out
  of `queued`, so the abort is delivered there, and the attempt keeps its
  counted slot until it ends. The abort cancels the attempt's
  scope, which encloses only `task_run`, and today's abort handling ends
  the attempt ("Aborting an attempt that has not registered"). An abort is
  never retried. If `_run_task` has already returned (a failed `init()` or
  startup write) and `run_one` is deciding on a retry or awaiting
  `reinit()`, the `TaskCancel` still takes the abort, since it accepts one
  after an attempt that ended in error and only an error is retried, and
  `run_one` reads it where it reads `queue.closed` ("No retry once
  closed"), so no retry is published and the record ends with that
  attempt's log. No case reports `retry_abandoned`, which stays the answer
  for a pending retry of a registered task only.
- (task-handles.md) A record fed through a handle: after the route above
  (so a queued record's `abort_requested` is already set), `RunQueue.cancel`
  closes the record's sample channel itself, in the same synchronous call,
  in every phase but `ended`, whether or not the route's directive applied:
  once the attempt's `EvalState` is terminal while the record is still in
  `attempt` (its `task_complete` running), `cancel_task` answers "task
  already finished" without calling `apply`.

**Aborting an attempt that has not registered.** `start_attempt` creates
the attempt's cancel scope and its `TaskCancel`, whose `apply` cancels that
scope (today both are created in `_run_task`; for a task fed through a
handle it first closes the task's sample channel, for every action,
[task-handles.md](task-handles.md)), in the synchronous step that
moves the record into `attempt`, and stores them on the record; `run_one`
passes them to `_run_task`, which enters the scope around `task_run` as
today. Every
attempt gets a fresh pair; none is carried from one attempt to the next.
The record holds the pair from that step until the synchronous step in
which `run_one` publishes a retry (after its last abort and closed checks,
"No retry once closed") or ends the record, and drops it there, so the
late-abort checks and the asynchronous `reinit()` still reach it, and a
retry gets its own pair with its own retry budget. So a
cancel that lands before `_run_task` has entered the scope still takes
effect: an AnyIO scope cancelled before it is entered cancels its body at
the first checkpoint (checked on asyncio and trio). `register_eval`
receives the same `TaskCancel`, so after registration `cancel_task` reaches
the same object. The retry-abandon stamp stays only where it is today, for
a pending retry of a registered task through `cancel_task`. For a record
cancelled while queued, `start_attempt` requests `abort` on the fresh pair
before `run_one` runs, so `_run_task` aborts at its first
checkpoint. That
checkpoint must come before any startup side effect, and the recorders do
not provide one: `EvalRecorder.log_init` reaches a lock first, but
`JSONRecorder.log_init`, and `record_inherited_config_updates` with no
retunes, return without one, so `logger.init()` would set the location and
create the sample buffer database and `task_run` could open the display
row before the header flush delivered the cancellation. So `task_run`'s
first statement inside the attempt's scope is an explicit
`await anyio.lowlevel.checkpoint()`, before its first retry-abandon check
and `logger.init()`. A pre-cancelled attempt aborts there, for every
recorder: before the display row opens, before `on_task_start` runs and
before any log file or buffer database exists, with no logger location. Today's abort handling covers every point
before registration:

- before the row opens (`logger.init()`, prior-log seeding): the
  cancellation leaves `task_run`, and `_run_task`, finding no result with
  `cancel_type == "abort"`, returns `unwritten_task_log(logger,
  TerminateTaskError("Task cancelled by user (abort)"))`;
- during `logger.log_start()`: `task_run`'s handler there completes the
  open row with that error and re-raises, and `_run_task` returns the same
  log. That handler sits outside the `try`/`finally` that closes a paged
  dataset (`maybe_page_to_disk`'s `DiskSampleStore`), so today an abort
  there leaves the store's temporary file. `task_run` therefore closes the
  store in a `try`/`finally` opened right after `maybe_page_to_disk`
  returns, replacing the close in the main `finally`, so every exit after
  paging, this one and a cancellation before the row opens included,
  unlinks the file;
- after the header is written: `task_run`'s cancellation handler writes the
  error log and completes the row, as for a running task.

`run_one` takes its no-retry branch for an abort and, as today, discards an
unfinished recorder entry while keeping its destination. The costs
(decisions: Ransom, 2026-11-16 and 2026-11-17): a task cancelled while
queued or in its first moments, a retry included, ends with "Task cancelled
by user (abort)", not the earlier attempt's log; it is still an error log,
so an eval set and a selection-mode worker see a failure. A cancelled queued
retry is reported to the source once more, as its own aborted attempt. A
queued cancel takes effect on the dispatcher's next pass, not at once:
immediately in a run without a `TaskSource`, and after `next_tasks()`
returns while that call blocks, the record staying listed as queued with
an abort requested until then. A repeated cancel of such a record answers
"cancel already requested (abort)". An abort that
interrupts the header write can leave a partial log file, as an abort of a
running task can today, and the returned log's `location` names the file
the attempt was writing, written or not (`unwritten_task_log`, as today).

**Reporting to the source.** One rule: each attempt's outcome reaches the
run's `TaskSource` once, through `notify_task_source` (which awaits
`task_complete` and adds what it returns), whatever ended the attempt, a
task cancelled while queued included, since it ends through an aborted
attempt; nothing is reported twice.
Delivery stays per attempt, as today: a task that fails and is retried
twice is reported three times.

- **One call in `_run_task`.** After the attempt's cancel scope has exited,
  `_run_task` calls `notify_task_source` once with the log the attempt ends
  with: a written log (success, error, or the `cancelled` log of a
  run-level cancellation), the unwritten "Task cancelled by user" log of an
  abort or retry request, the unwritten error log of a failed
  `logger.init()`, which now runs inside the attempt, or the unwritten
  storage-error log of an attempt whose log storage failed after `init()`
  had returned (a failed prior-log seed, header flush or final write that
  left no finished log). That last log is the one `eval()` already returns
  for the attempt, and a source waiting on a task whose final attempt
  failed this way is not left waiting (decision: Ransom, 2026-11-18,
  reversing the 2026-11-16 exception for it). So today's `write_failed`
  flag and its early return are removed: of the two cases that set it, the
  abort or retry with no written log and the storage failure, both are now
  reported. No flag replaces it, and `TaskLogger` gains no `initialized`
  state: a failed `init()` and a later storage failure are reported alike.
  `_run_task` keeps today's early return for an attempt abandoned by the
  retry-abandon stamp, which has no log of its own (below).
- **One exception, today's.** A preview (`run_samples=False`) is not
  reported (`notify_task_source`'s own check).
- **No attempt, no second report.** An attempt that returns no log of its
  own (a pending retry of a registered task abandoned by the stamp, which
  ends the record with its earlier attempt's log) reports nothing; nor does
  an unregistered attempt aborted after `_run_task` returned: in each case
  the attempt whose log the record keeps was reported when it returned. A
  record ended unstarted when dispatch ends is not reported, as today.

The call keeps `notify_task_source`'s rules, as today: a callback exception
is logged (propagated under `debug_errors`), and the tasks a callback
returns go through `_enqueue_source_tasks`, so after the queue closes they
are dropped ("Source returns after close are dropped"). `_run_task` keeps
today's guards unchanged: its private task group and normal-return check
turn a cancellation that no cancellation of the run caused, raised by
`task_complete` or escaping task cleanup, into a contextual `RuntimeError`
(`test_task_complete_raising_stray_cancellation_ends_run`,
`test_stray_cancellation_after_log_finalized_ends_run`).

`RunQueue.end` sets `ended`; for a record whose `reached` is not
`registered`, registers it as a finished eval (below); removes the record
from the queue and the queued registry, rings `wake`, and releases `options`
(and what the handles attach): `ResolvedTask.task` holds the dataset and the configured task is a
shallow copy of it, so both references go for a finished task's samples to
be freed. The record keeps its identity, `log` and `ended`.

**Display rows keep no frames.** Rich keeps each row's result
(`TaskStatus.result`) and Textual keeps every row (`_app_tasks`) for the
life of the task screen, which is now the whole run. Today a failed row's
`TaskError` holds the exception and its live traceback, whose frames hold
`task_run`'s locals, so a failed task's `options`, `Task` and dataset
would outlive its record. So `TaskError` holds a snapshot instead:
`TaskError.from_exception(samples_completed, exc_type, exc_value,
traceback)` keeps `exc_type`, the rendered traceback
(`rich_traceback(...)`, Rich's extracted `Trace`, which follows the
`__cause__` and `__context__` chain and, under
`INSPECT_TRACEBACK_LOCALS=1`, keeps the locals as reprs) and the text of
`traceback.format_exception(...)`, and no exception object or frame.
`task_run` builds it at each `td.complete(TaskError(...))`;
`task_result_error` (`_display/core/results.py`) renders the snapshot.
`LogDisplay._log_result` keeps today's status message, "<title> failed
(<n>/<m> logged)", and passes the snapshot's text instead of `exc_info`, as
`extra={"exc_snapshot": text}`; the text is exactly what
`Formatter.formatException` gives for today's `exc_info`, without its
trailing newline. The logger reads it where it reads `exc_info`
(`_util/logger.py`):

- `LogHandler.emit` sets `record.exc_text` from `exc_snapshot` when the
  record has no `exc_info`, so `Formatter.format`, which appends
  `exc_text` after the message, gives the plain display, the Rich display
  (`RichHandler` formats the message the same way, since Inspect does not
  enable `rich_tracebacks`) and the `INSPECT_PY_LOGGER_FILE` handler the
  same output as today;
- `json_log_record` emits `exc_info` from `record.exc_info` as today, and
  otherwise from `exc_snapshot`, so the JSON record keeps a short `msg` and
  the separate `exc_info` field;
- the trace file's `TraceFormatter` records no exception today and copies
  every unexpected record attribute into its JSON, except a fixed set that
  includes `exc_info` and `exc_text`; `exc_snapshot` joins that set, so the
  trace output stays as it is today.

Under `debug_errors` the original exception still propagates with its
traceback. A run with a failing task looks as it does today on every
display and logger format.

**Terminal identity without registration.** A record that ends before any
attempt calls `register_eval` (cancelled while queued, which aborts before it registers, a startup failure
such as a failed `init()` or a bad adaptive setting with no retry left, an
attempt aborted before it registered, a record ended unstarted, a fed task closed before
any sample was sent) would otherwise vanish from the control channel when
it leaves the queued registry: `latest_eval_for_task` finds nothing, and a
repeated cancel or drain answers 404. So `RunQueue.end`, in the same
synchronous step and before removing the registry entry, calls today's
`register_completed_eval` (`src/inspect_ai/_control/eval_state.py`, used by
`eval_set()` for reused logs) with zero samples (`total=0`, `completed=0`):
the eval id, task name, task id and run id of the final log's eval spec, or
of the logger's when the record ends with no log; the record's model; and
the log's `location` (empty for an in-memory log). `task list` then shows the
task as a finished row with no samples, and a repeated cancel or drain,
`--dry-run` included, answers `changed: false`, "task already finished"
(`_control/cancel.py`), as for a finished task today. The record's `options` and samples
are still released; the `EvalState` holds only counters and names. Under
`eval_set(retry_immediate=False)` a later round's queued record with the
same id is found in the registry first ("Control channel"), and its first
`register_eval` registers after this state, so it is the latest.

The task total on the display counts every record, but the Rich and
Textual displays count completed tasks from the rows attempts open. So a
record that ends with `reached == "added"` (cancelled while queued, ended
unstarted at the end of dispatch, aborted or failed in startup before its
row opened, or, in task-handles.md, a fed task closed before any
sample was sent) takes one off the total, once. A record whose row opened
leaves the total unchanged, as today; an abort from `log_start()` on
completes that row ("Aborting an attempt that has not registered").
`RunQueue.end` calls `display().update_task_count(-1)` only while
`queue.screen_open` is set: the dispatcher sets it on entering the body of
`_run_task_screen`, after Textual's app has loaded and `task_screen(tasks)`
has set the seed's total, and clears it when it leaves the screen. No
record that should count ends outside that window: a cancel only requests
an abort and the dispatcher, inside the screen, runs it; a fed task's
channel is closed by attempt code, by `RunQueue.end` or (task-handles.md)
by `RunQueue.cancel`, which a handle or a control-channel directive can
call at any time, but `RunQueue.cancel` sets a queued record's
`abort_requested` before it closes the channel, so that empty-channel close
keeps the record queued for its abort attempt inside the screen (or for
`end_unstarted()`), and closing a record already in `attempt` leaves its
end to `run_one`; `end_unstarted()` runs in
the dispatcher's `finally`, inside the screen. What ends outside it changes
no display: `end_all()` after the screen has closed, and every record when
a failure came before the screen opened. The displays' counting is
unchanged.

The record's sandbox resolution cache (today's run-wide
`SandboxManager._resolved_no_metadata`, keyed by `(Task, spec)`) is on its
`options` ("Setup does not change the process's directory or environment"),
so it goes with them when the record ends. What lasts until the run's
shutdown is unchanged: the configurations set up, their contexts and
bindings, and the registered `task_cleanup` calls, none of which refer to a
`Task`.

#### A task's log starts with its attempt

`task_run` awaits `logger.init()` as its first startup step, after the
explicit checkpoint ("Aborting an attempt that has not registered") and its
first retry-abandon check, and before prior-log seeding and `log_start()`.
`TaskLogger.reinit()`, which `run_one` awaits before publishing a retry,
still detaches the old attempt's live state and releases an unfinished
attempt's recorder entry (keeping its destination), but no longer calls
`init()`: the retry's own `task_run` does. `TaskLogger.discard()` on a logger
that holds no entry does nothing.

**A logger with no location.** `init()` assigns the location only when
`recorder.log_init()` returns, and a failure can come before that (the
check against existing logs, `_bump_created_past_existing_logs()`, or
`log_init()` itself, whose recorder tracks the entry only after it is set
up). So `TaskLogger._location` starts
as `None` at construction, and `reinit()` resets it to `None`, so a retry
never reports its predecessor's file as its own. Its readers handle it:

- `TaskLogger.location` returns `str | None`.
- `TaskLogger.destination_written` returns `False` while the location is
  `None`, before asking the recorder, which raises for an eval it does not
  track.
- `unwritten_task_log` sets `location=logger.location or ""` (`EvalLog`'s
  default), so it returns the error log instead of raising.
- `run_one` reads `options.logger.location` only after `destination_written`
  is true, when it builds the retry's sample source from the failed
  attempt's log; otherwise the retry keeps the source the attempt ran with,
  as today for an attempt that wrote nothing.

So a failure in `init()`, before or after the location exists, escapes
`task_run` like a failed `log_start()` flush, `_run_task` turns it into an
error log carrying the original storage error (`unwritten_task_log`, built
from the eval spec, which exists from construction), `run_one` discards
whatever the recorder tracked and retries that task alone, and the other
tasks run on. `record_inherited_config_updates` stays inside `init()`, so a
retry's log records the run's process-scoped `ctl` retunes as today.

So the run's end, a queued cancel and a dropped retry release nothing, and a
seed task whose log cannot be initialised ends with an error log instead of
raising from `eval()`.

### The dispatcher

`run_task_retry_attempts` becomes `dispatch_tasks(queue, sandboxes, *,
parallel, task_retry_attempts, task_source, debug_errors) -> list[EvalLog]`,
with today's `run_one`, retry decision, retry-abandon handling and model
balancing:

```
async with _run_task_screen(...):              # absorbs a cancellation of the run body, as today
    queue.screen_open = True                   # cleared on leaving the screen
    async with attempt task group:             # today's group: run_one and the throughput reporter
        add_dispatch_waker(queue.wake.set)
        try:
            source_done = task_source is None
            loop:
                drop queued retries whose task carries the abandon stamp
                    (each ends its record with its stored log)
                while not cancelled and in_flight < effective_max_tasks(parallel):
                    entry = pick_balanced(startable entries)  # skips abort_requested and (task-handles.md) channels
                    if entry is None: break
                    start_attempt(entry, counted=True)        # "Starting an attempt"
                if cancelled: break
                for each pending entry with abort_requested, or (task-handles.md)
                        fed, holding a request and startable, in queue order:
                    start_attempt(entry, counted=False)       # "Start rule"
                idle = no entry is pending and no attempt runs
                if idle and source_done: break
                if idle:
                    more = await task_source.next_tasks()  # inline, as on today's live path
                    if not more: source_done = True        # None or [], as today
                    else: queue.add(resolve(more))
                    continue
                await queue.wake
        finally:
            queue.close(); queue.end_unstarted()           # synchronous, before the group joins
            remove_dispatch_waker(queue.wake.set)
```

- **The dispatcher never awaits a sandbox setup.** Each attempt sets up its
  own selected samples' sandboxes, the way a `SampleSource` addition is set
  up today ("Sandbox setup in the attempt" below).
- **Start rule.** A record in `queued` (a first attempt or a retry) is
  startable when no control-channel pause holds it
  (`task_dispatch_paused`, as today's dispatch loops check). The dispatcher
  takes the earliest startable record among the least-used models, so at
  `max_tasks == 1` sequence grouping holds. One exception, shared with fed
  tasks' start (task-handles.md): a `queued` record with `abort_requested`
  (cancelled while queued) belongs to the uncounted start alone. The
  ordinary picks skip it, as they skip a record with a channel, so it
  never takes a counted slot; the uncounted pass starts it with
  `start_attempt(entry, counted=False)`, which takes it from the same
  pending list the ordinary picks consume and moves it into `attempt` in one
  synchronous step without counting it toward `in_flight`, so a record is
  started once however many passes run before its `run_one` does. It starts whether or not a pause holds it,
  since a cancel overrides a pause, as `apply_cancel` already treats it.
  It is skipped once the dispatcher has latched a cancellation;
  `end_unstarted()` then ends it with its stored log.
- **Starting an attempt.** `start_attempt(entry, counted)` is the one
  synchronous step that starts every attempt, from the ordinary pick
  (`counted=True`) and from the uncounted pass (`counted=False`). With no
  `await` in it, it removes the entry from the pending list; when `counted`,
  adds one to `in_flight` and to the entry's model count, as today's pick
  does; moves the record into `attempt`; creates the attempt's fresh
  `TaskCancel` and cancel scope and stores them on the record, with the
  `TaskCancel`'s `can_retry` set from the record's remaining retry budget,
  as `run_one` passes it to `_run_task` today (always false for a fed task,
  task-handles.md "Retries"), so `task_run`'s retry pre-mark and
  `register_eval(will_retry=...)` read the intended value, requesting
  `abort` on the `TaskCancel` when `abort_requested` is set; and schedules
  `run_one(entry, cancel, scope, counted)` in the attempt group. A counted
  `run_one` gives its slot and model count back once, in the synchronous
  step that publishes a retry or ends the record, as today; an uncounted one
  gives nothing back. A cancel between this step and `run_one`'s first
  statement finds the record in `attempt` and reaches the stored pair
  ("Phases and cancelling"), so an attempt picked by the counted pick and
  cancelled at once holds its slot until its abort ends.
- **Wakers.** The dispatcher registers `queue.wake.set` with
  `add_dispatch_waker` (`_control/pause.py`) for the run and removes it when
  dispatch ends, as today's dispatch loops do, so a `max_tasks` retune
  (`set_max_tasks_override`), a pause and a resume ring it and a run held
  by a limit or a pause starts tasks as soon as the limit is raised or the
  pause lifted.
- **Retries** are today's: `run_one` stores the attempt's log on the record,
  awaits `reinit()` and appends the retry at the back of the queue under the
  record's index. The retry's attempt skips the configurations already set
  up in the run and sets up again any whose `task_init` failed. A cancel or
  drain while a retry waits ends it: through its abort on the dispatcher's
  next pass when no attempt registered, otherwise through the stamp.
  `task_retry_attempts` is one run-wide value: `eval()`'s argument (default
  0), `eval_set()`'s `retry_attempts` (default 10) when `retry_immediate` is
  on (the default) and 0 otherwise, and 0 in a selection-mode worker; there
  is no per-task limit.
- **No retry once closed.** `run_one` reads `queue.closed` where it decides
  on a retry (beside today's abandon-stamp check) and again in the
  synchronous step that appends the retry after `reinit()` returns. Closed
  means no retry, as for an abandoned one: the record ends with this
  attempt's log. The retry's logger was never initialised, so nothing is
  discarded. The same two points read the record's `attempt_cancel`: an
  abort that `RunQueue.cancel` made after `_run_task` returned, for an
  attempt that never registered, means no retry in the same way. The
  second check runs in the synchronous step that publishes the retry, and
  that step also drops the record's `attempt_cancel` and `attempt_scope`;
  a cancel after it finds the record `queued` and sets `abort_requested`. At the first check `run_one` takes today's no-retry branch,
  which unwinds the task runner's pre-mark with `clear_eval_retry_pending`:
  on the attempt's own `EvalState`, or, for an attempt that never
  registered, on the task's latest registered attempt
  (`latest_eval_for_task`). At the second, `run_one` has already re-marked
  the attempt with `mark_eval_retry_pending`, so it clears the flag the same
  way before ending the record; otherwise the flagged `EvalState` would stay
  retry-pending and a later task directive would report abandoning a retry
  that does not exist. This matters only after a latched cancellation, when
  attempts still running can finish after the queue closed.
- **`next_tasks()` is awaited inline**, only when nothing is pending or
  running, as on today's live path. Nothing starts while it blocks: a task
  that a hook or a background coroutine of a finished sample adds during
  the call is queued (listed and cancellable at once) and starts when the
  call returns, ahead of the batch the call returned. `None` or `[]` ends
  the source without calling the resolver, and an exception the call raises
  ends the run, both as today. The call runs inside `_run_task_screen`, so a
  Ctrl-C while it blocks is absorbed like one during a task, and a
  cancellation of the run cancels it.
- **End of dispatch.** The `finally` runs inside the attempt group's body,
  so it runs before the group joins its attempts, on every exit: the source
  done, a latched cancellation (an attempt returned no log or a `cancelled`
  log), an exception (a `debug_errors` error from an attempt, an error from
  `next_tasks()`), or a cancellation from outside (Ctrl-C, a caller's
  scope). It does
  not run before every attempt is cancelled: a child's failure cancels the
  group, and an enclosing cancellation reaches the attempts directly, before
  the dispatcher resumes into its `finally`, so an attempt's shielded cleanup
  (its logging, task-end hooks, a sample's `finally`) can call
  `enqueue_task()` while the queue is still open. Such an addition is
  accepted as an ordinary `queued` record and ended unrun by the sweep below
  when the `finally` runs; one made after it is refused. `close()` refuses
  every later addition and retry. `end_unstarted()` ends every `queued`
  record with its stored log (`None` for one never attempted), which
  settles every handle wait on them at once, including waits in
  shielded code such as `Task.cleanup` and hooks of cancelled samples, which
  would otherwise hold the group's join open. Records in `attempt` are left
  to `run_one`.
- **After the group exits**, `eval_run`'s `finally` calls `queue.close()` and
  `queue.end_all()`, which ends any record still open with its stored log:
  a fallback, since `run_one` ends its record on both exits, and every
  record when a failure came before the loop (the task screen failing to
  open). Then it shuts down the
  sandboxes and cleans up S3 sessions, as today's `finally` does, and resets
  the `ContextVar`.
- **`debug_errors`** is passed to the dispatcher at every `max_tasks`.

`max_tasks` counts attempts in flight, including one building its
sandboxes, with two exceptions, both started by the uncounted pass: a record
cancelled while queued (`abort_requested`), whose attempt runs until its
abort ends, including its report to the `TaskSource`, and, as
[task-handles.md](task-handles.md#tasks-fed-through-a-handle) adds, a task
fed through a handle. So `max_tasks` bounds counted attempts, not every
live attempt: an aborting record and its `task_complete` callback can run
beside `max_tasks` counted attempts. The `max_tasks` docstrings
(`eval()`, `eval_async()`, `eval_set()`, `eval_retry()`) and
`docs/parallelism.qmd` say so for the aborting record (task-handles.md adds
the fed-task exception).

#### Sandbox setup in the attempt

`configure_task()` gives every task with samples to run (not only a
`SampleSource` task, as `prepare_options` does today) a `startup_sandboxes`
callable in its `TaskRunOptions`:
`SandboxManager.start_for_samples` bound to the resolved task and to the
record's own resolution cache, `TaskRunOptions.sandbox_cache`, which
replaces the run-wide `_resolved_no_metadata` and keeps its rule (samples
without metadata resolve once per spec). `task_run` awaits it for the
attempt's selected seed samples after `register_eval` and the task-start
hooks and before it schedules the seed batch; a `SampleSource` task's
feeder keeps awaiting it for the samples it adds. Under
`run_samples=False` there is none, as today.

- **Shared configurations.** `SandboxManager` is run-wide, as on today's
  live path: a configuration already set up in the run is skipped, and
  `task_init` stays serialised by `_init_lock`, with the started set
  re-checked under it, so two tasks that need one configuration set it up
  once and the second waits for the first. `display().suspend_task_app()`
  around the call is today's.
- **Failure.** An error from `task_init` (or from key resolution) raises in
  the attempt, so the task ends with its error log like any attempt error
  and the run goes on. A failed configuration is not added to the started
  set, so the task's retry under `task_retry_attempts`, and any other task
  that needs it, runs `task_init` again. `task_cleanup` is registered only
  when `task_init` returns, as today (`SandboxManager._start_sandboxenvs`),
  so a failed call gets no `task_cleanup`, then or at shutdown, and a
  configuration whose every call failed has none. Nothing runs between
  calls. The provider releases what a failed `task_init` allocated before
  it raises, and a later call for the same configuration either sets it up
  or fails again as an ordinary error; the contract docs say so (below).
- **Cancellation.** Cancelling an attempt during a `task_init` it runs
  cancels that call, as a cancelled `SampleSource` addition does on today's
  live path; nothing is marked started and the next task that needs the
  configuration runs it again. A task waiting on `_init_lock` behind another
  task's setup is cancelled out of the wait.
- **Slots.** The attempt holds its `max_tasks` slot while it builds, and the
  task's display row is open with a running state. The dispatcher starts
  other tasks meanwhile, so a task with no sandboxes, or whose
  configurations are set up, starts at once.

### Control channel

`RunQueue.add` registers each record in a process-level registry,
`src/inspect_ai/_control/queued_tasks.py`, keyed by `task_id`, holding the
record and a `cancel()` callback into `RunQueue.cancel`. The record leaves it
when it ends, after `RunQueue.end` has registered a record that never
registered as a finished eval ("Phases and cancelling"), or in
`on_registered()`, with no `await` between that and `register_eval`, so a
directive always finds the task in one of the two.

The registry takes precedence over `EvalState` history for the same id: under
`eval_set(retry_immediate=False)` each round is its own `eval()` and keeps the
task id, and `EvalState`s persist across those calls.

- `GET /tasks` adds a row for a queued record with `status: "queued"`,
  `attempts: 0` and zero sample totals, or overlays the existing row of a
  task with history (a legacy retry round), setting `status: "queued"` and
  keeping its history. CLI selectors resolve queued tasks like running ones.
- `_task_cancel_directive` looks in the registry first. A cancel or drain of
  a record that has not registered follows `RunQueue.cancel`, which
  requests its abort, and returns `changed: true`, `task_queued: true`,
  `in_flight: 0` (and `queued: 0` for a drain, whose `queued` is a sample
  count); `dry_run` reports without acting. When the record is `queued`
  with `abort_requested` set, a repeated cancel or drain, dry runs
  included, answers `changed: false`, "cancel already requested (abort)".
  When it is in its attempt, the directive first asks the attempt's
  `attempt_cancel`, dry runs included, as today's directive asks a
  registered attempt's: when an abort is already requested it answers `changed: false`, "cancel already requested
  (abort)", and when the attempt has already returned a log that is not an
  error (the `TaskCancel` then accepts nothing) it answers `changed: false`,
  "task already finished", so a repeated cancel or drain while startup or
  cleanup still holds the record changes nothing. The CLI renders such a
  result as a cancel of a task that ran no samples. `action=score|error`
  answers 409 ("task … has not
  started, so there are no samples for a resolution to apply to; use cancel
  or drain").
- `pause_task` and `resume_task` (`_control/pause.py`) look in the registry
  first, as the cancel directive does, and use `latest_eval_for_task` only
  for a task the registry does not hold: under
  `eval_set(retry_immediate=False)` a second round's queued record shares
  its id with the first round's terminal `EvalState`, which would otherwise
  answer "task already finished" to a pause and describe the old eval on a
  resume. For a queued record they close or open the task's pause gate
  (`_task_gate(task_id)`), which is
  the gate the start rule checks: a paused queued task is skipped by the
  dispatcher, which starts the tasks behind it, and starts after a resume
  (the resume fires the dispatch wakers). The response describes the queued
  task with its record's task name and model, `status: "queued"`, and
  `dry_run` reports without acting. A gate closed while the task was queued
  keeps holding its samples after it starts, as for a paused running task.
- `CONTROL_API_VERSION` increases by one.

#### Tasks cancelled before they start under `eval_set()`

A task cancelled before it starts ends with the abort's in-memory error log
("Phases and cancelling"), so `eval_set()`'s checks need nothing new:
`all_evals_succeeded()` reports failure and selection mode returns `False`.
Under immediate retries (the default) no task retry follows, since an abort
is never retried, and the invocation reports the failure.
`run_eval` (`evalset.py`) keeps one rule beside its `cancelled`-log check: a
requested task with no log was still queued when the run was cancelled
(dispatch ended first), so it raises `KeyboardInterrupt`.

Under `eval_set(retry_immediate=False)` each round is its own `eval()`, and
the next round reruns every requested task that did not succeed, so a
requested task cancelled before it started comes back in the next round, as
a running task cancelled under legacy rounds does today;
`inspect ctl process pause` holds it.

### Setup does not change the process's directory or environment

`chdir` and `environ_vars` are removed from setup, key resolution and
cleanup. Every provider call then runs in the launch directory with the
process's own environment, as `sample_init` does today. Two synchronous
directory changes stay: the `chdir` around a task's `TaskLogger`
construction, which no longer contains an `await` ("Adding tasks"), and
loading a task from a file
(`enqueue_task("path/tasks.py@name")`, or a seed given as a file) goes
through `load_file_tasks()` and `create_file_tasks()`, whose `chdir_python`
blocks change the directory and `sys.path` so the file's local imports and
relative reads work while it is imported and its task constructed. Those
blocks are synchronous, with no `await` inside, so no other coroutine sees
them (worker threads can, as today); a test keeps local imports and relative
file reads working for a task file added from a solver, with the directory
restored afterwards. In place of the `chdir`:

- **Inspect resolves config paths against the task directory** in one
  helper, `resolve_config_paths(config, task_dir)`
  (`src/inspect_ai/util/_sandbox/paths.py`): a relative string config, and
  each relative `build` context of a `ComposeConfig` service (a string, or
  `ComposeBuild.context`), becomes absolute when that path exists under the
  task directory. A `ComposeBuild` whose `context` is omitted
  (`ComposeBuild()` or `ComposeBuild(dockerfile="Dockerfile")`, where it is
  `None`) means the compose default `"."`, which Docker's
  `_update_build_context` would otherwise resolve against the process
  directory when `ComposeProject.create` writes the generated file; the helper
  treats it as `"."` and sets the context to the task directory itself, as
  today's setup `chdir` made it. A URI, an absolute path, a string with no such file, and an
  `OSError` from the check (a string too long to be a path) leave the value as
  given. `resolve_task_sandbox` calls it for the task-level config in place of
  its unconditional join, so an inline-JSON string config is no longer
  rewritten; `resolve_sandbox` calls it for a sample's own config.
- **A retry from a log applies the same rule.** `eval_retry_async()` builds
  the `PreviousTask`'s sandbox with `resolve_task_file_sandbox()`
  (`_eval/loader.py`), which today joins every relative string config to the
  logged task file's directory, and `resolve_previous_task()` carries that
  spec into the retry unchanged. It calls `resolve_config_paths()` with that
  directory (`Path(task_file).parent`, as today) in place of its join, so a
  relative config file that exists there still becomes absolute, an absolute
  path and a missing task file leave the value as given, as today, and an
  inline-JSON string the first run kept is kept by the retry too instead of
  being turned into a directory-prefixed string that no longer parses.
  Non-string configs pass through, as today.
- **Samples resolve their config again, to the same spec.**
  `sandboxenv_context` resolves the sample's sandbox through
  `resolve_sandbox`, which applies `resolve_config_paths` with the task
  directory, as key resolution did for `task_init`. The helper does not
  depend on the working directory, so both resolve to the same spec, and
  `sample_init` takes only that spec's config. The sample's configuration
  (for its provider bindings, "Provider state per setup") is found by spec
  and task directory. Only Docker returns a `task_init_environment`, and
  Docker rebinds no `ContextVar`, so setups of one spec that differ only in
  that `env` can share one bindings entry. The cost: a config file created
  or deleted under the task directory between setup and the sample's start
  resolves differently, so the sample gets a config that was not set up and
  no bindings. Resolution is cheap; without metadata, Docker's
  `task_init_environment` runs no subprocess.
- **Docker's `task_init_environment` values** reach Docker directly. A
  private `ContextVar` in `src/inspect_ai/util/_sandbox/setup.py` holds the
  key's `env` around the `task_init` call; Docker's `task_init` reads it and
  passes it to `ComposeProject.create(env=...)`, which its `compose build`
  and `compose pull` already forward. The `env` is what the registered
  provider class's `task_init_environment` returned, so a subclass of Docker
  that overrides it gets its own values. Nothing is merged into other
  subprocesses.
- **Other providers' `task_init_environment` values are refused.** The
  public hook promises variables set for `task_init`, and today
  `resolve_sandbox_for_task_and_sample` records them for every provider and
  the manager sets them in `os.environ` around its `task_init`. Only Docker
  overrides it: no provider in inspect_sandboxes, inspect_k8s_sandbox,
  inspect_ec2_sandbox, inspect_proxmox_sandbox, inspect_vagrant_sandbox,
  inspect-podman or inspect-policy-sandbox does. So rather than a general
  way to pass them, `resolve_sandbox_for_task_and_sample` raises
  `PrerequisiteError` when the hook returns a nonempty mapping for a
  provider class that is not `DockerSandboxEnvironment` or a subclass,
  before any `task_init` runs ("sandbox provider '<type>' returned
  environment variables from task_init_environment(); Inspect no longer sets
  them in the process environment and passes them only to Docker's
  task_init. Put what task_init needs in the sandbox config, and pass
  environment variables to the subprocesses it starts with
  subprocess(env=...); return {} from task_init_environment"). The error
  raises where setup errors raise: once setup runs in the attempt (step 3a),
  that task ends with its error log; under step 1 alone, before that, it
  fails the run from `eval()` as a setup error does today. An empty
  mapping, every provider's default, is unaffected.
- **No other substitute.** `subprocess()` keeps its ordinary default `cwd`,
  the process directory. So Docker's setup subprocesses move from the task
  directory to the launch directory, as its sample subprocesses already run.
  That changes nothing they read: Compose resolves a compose file's own
  paths (build contexts, `env_file`, `.env`) against the file's directory,
  and Inspect hands Docker its config paths resolved. Its remaining lookups
  (a relative build context with no such directory under the task
  directory) run in the launch directory in `task_init` as in
  `sample_init`.
- **Third-party providers** run their task-level calls in the launch
  directory, with no flag to declare and no warning. For the surveyed
  providers:
  - E2B's template warm-up gets a `ComposeConfig` whose build contexts
    Inspect has made absolute, and so does its `sample_init`, so both build
    from the task directory and the warm-up builds the template the samples
    use.
  - Podman's missing-config lookup and generated compose file move to the
    launch directory, where its `sample_init` already looks; it passes
    absolute paths to its subprocesses. Its shared generated file
    ("Current behaviour") then collides whenever a Podman `task_init`
    overlaps running Podman samples, whatever the task directory: a second
    task's setup rewrites the running samples' `.compose.yaml`, and its
    failure deletes it. Today that needs the task directory to be the launch
    directory and an overlapping setup (the live path or a `SampleSource`
    addition); here every task sets up its sandboxes in its own attempt, so
    at `max_tasks > 1` a seed or added task's setup can overlap another
    task's running samples. The fix belongs in inspect-podman, a generated file per
    project as Inspect's Docker writes them, and is a provider follow-up
    that no step here waits for (decision: Ransom, 2026-11-11; see
    "Compatibility and migration").
  - Proxmox resolves a relative `PROXMOX_CONFIG_FILE` against the launch
    directory, as its `default_concurrency()` and `cli_cleanup()` already do.
    A run whose file is found only relative to the task directory falls back
    to `PROXMOX_HOST` or no pools.
  - Modal and Daytona get a `ComposeConfig` whose build contexts Inspect
    has made absolute against the task directory, so their converters build
    the task directory's Dockerfile rather than the launch directory's
    ("Behaviour changes"; decision: Ransom, 2026-11-11). Proxmox and these
    two are the surveyed cases in which a working eval can change.
  - k8s, EC2 and Vagrant take absolute paths or none.
- `SandboxEnvironment`'s docstring and `docs/extensions-sandboxes.qmd` state
  the contract: `task_init_environment`, `task_init` and `task_cleanup` run
  in the launch directory and environment, like `sample_init`; config paths
  arrive resolved; `ContextVar` bindings as below; and the variables
  `task_init_environment` returns reach only Docker's `task_init` (another
  provider returning any is refused, with the migration above). They also
  state the repeat-call rule: `task_init` can be called again for a
  configuration after a call that raised, in the same run; a call that
  raised gets no `task_cleanup`, so it releases whatever it allocated before
  raising; and the next call either sets the configuration up or raises
  again.

### Provider state per setup

`eval_run` enters Docker's `sandbox_lifecycle_scope()` first, in its own
context, before it creates the queue, the sandbox manager or any task (today
`SandboxManager.open()` does this before preparing tasks), keeps it through
the run and its shutdown cleanup, and exits it in that same context in
its `finally`, on every exit, a configuration error in the seed included.
`SandboxManager` is created next and takes `root`, a `copy_context()` of
`eval_run`'s context at that moment, after `eval_run` has set the
`--sandbox-prebuilt` flag and before any task or setup starts: the context
every attempt and sample inherits, holding the lifecycle scope and no
provider state. Each `task_init` runs in a task started from the setup
chain's context, which starts as a copy of `root` (so Docker's lifecycle
scope object is inherited) and which each successful `task_init`'s context
replaces in turn, so a later `task_init` sees what earlier ones bound, as
today (k8s's shared manager stays shared). When `task_init` succeeds, the
manager keeps two things for that configuration:

- `context`: a `copy_context()` taken inside the setup's task as the call
  returns, for its `task_cleanup`.
- `bindings`: every `ContextVar` in that context whose value differs, by
  `is not`, from its value in `root` (a variable missing from `root`
  differs), excluding the `env` variable above. So `bindings` is the
  configuration's whole provider state, including what earlier setups bound
  and this one inherited: for E2B, Modal and Daytona each configuration's
  own rebound list and run id, and for k8s the manager an earlier setup
  created and this one reused without rebinding.

A failed `task_init` keeps neither, and its context does not replace the
chain's, so its bindings reach no later setup.

- **Samples.** `sandboxenv_context` applies the bindings of the
  configuration it finds for the sample (by its resolved spec and task
  directory) in the sample's own context before `sample_init`, but only for a
  variable whose current value is still its value in `root` (the same
  object, or missing from both): a value the sample (or its solver) bound
  itself is left alone. Samples start from `root`'s descendants, so for every
  provider variable that holds, and each sample gets its own configuration's
  state, wherever the setup ran. `sample_init`, the sample's sandbox calls
  and `sample_cleanup` then see it. This fixes the empty-seed `LookupError`
  for E2B, Modal and Daytona.
- **Cleanup.** Each `task_cleanup` runs in a task started from its
  configuration's `context`, so E2B, Modal, Daytona and Podman clean up the
  list their own `task_init` bound, including sandboxes an interrupted
  `sample_cleanup` left behind.
- Docker's `SandboxLifecycleState` is a mutated object, not a rebinding, so it
  never appears in `bindings`.

The lifecycle scope stays internal: with captured bindings, the pattern
providers already use (bind in `task_init`, read in `sample_init` and
`task_cleanup`) is correct for every provider without a new API, and no
inspect_sandboxes change is needed.

### Where the handles attach

[task-handles.md](task-handles.md) returns a `TaskHandle` per added record,
lets a handle send samples to a task whose dataset is
`samples_from_handle()`, and starts such a task outside `max_tasks`. It adds
fields to `TaskRecord`, a creator argument to `RunQueue.add`, a
task-first settings rule in `configure_task()` for a task fed through a
handle (every other task, an ordinary added one included, keeps the
resolution described here), and one start rule to the dispatcher. Nothing
here depends on it.

### Interactions with related changes

- Recording which task added a task: [task-handles.md](task-handles.md)
  records the creator attempt only for tasks fed through a handle, so that
  change records the origin itself.
- Added tasks using their creator's model: `_resolve_enqueued_tasks`
  resolves a task added inside a running attempt once, under the attempt's
  model, including under `eval_set()` and in selection workers, whose run
  model is `none` ([task-source.md](task-source.md#relationship-to-enqueue_task)).
  `enqueue_task()` calls it unchanged, and `RunQueue.add` takes whatever it
  returns.
- Selection-mode handling of added tasks: it changes resolution inside the
  selection-mode `eval_set()`; `RunQueue.add` takes whatever that returns.
- Runtime pruning in selection workers, a prerequisite for adding tasks
  there. A worker resolving a selection prunes `@task` calls that the
  selection does not name: the `@task` wrapper (`_eval/registry.py`) asks
  `prune_task_call()` (`_eval/eval_set_pruning.py`) on every call and
  returns an empty placeholder `Task` instead of running the factory. A
  placeholder added to the run would run in place of the task, with no
  dataset and no `samples_from_handle()` source, so tasks constructed by
  executing attempts, such as a selected creator's `rollout_task()`, must
  be real tasks before `enqueue_task()` resolves them. The guarantee belongs to the pruning code, not to this design: its
  minimal form is that `prune_task_call()` returns `False` while a run is
  in progress (its run queue, or its task enqueuer, is bound), so pruning
  applies only to resolving the eval set's own tasks and every `@task` call
  made by attempt code, including one adapted afterwards with `task_with`,
  runs the factory. A task built before the selection is resolved (at
  module level, say) can be a placeholder; `_resolve_enqueued_tasks`
  refuses one with `RuntimeError` rather than running it. Adding tasks, and
  task handles, in selection workers depend on it (task-handles.md,
  "Implementation plan").
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
  log and resolve its selection in a job after `enqueue_task()` returns).
  It needs admission phases, an admission failure outcome, a queue-owned
  task group for admission and its cancellation, and an end of run
  that waits for admissions; and it holds a temporary file and buffer database
  for every queued task. Starting the log with the attempt and resolving
  selection at the call removes all of it.
- **Resolving `task:id` selectors when tasks are admitted together** rather
  than at the call. Keeps today's batch semantics but needs deferred
  resolution and its failure path; adding mutually-referring tasks in one call
  covers the same use.
- **Running `next_tasks()` beside the loop**, so a task added while it blocks
  starts at once. The call is made only when nothing is queued or running, so
  the only code that can add a task during it is a hook or a coroutine left
  over from a finished sample. Serving that needs a concurrent call with its
  own cancel scope, a stored result or exception, and an ordering rule for
  its batch against tasks added meanwhile. Such a task starts when the call
  returns, as today.
- **Retries in their task's slot.** Changes start order without a reported
  problem.
- **Sandbox setup in background jobs beside the dispatcher**: one job per
  configuration, run once per run, with its own retries and backoff, ending
  only the tasks that need a configuration whose final try failed. Builds
  would run in parallel and outside task slots, so a task waiting on an
  image would not hold a `max_tasks` slot. It needs a setup task group with
  its own lifetime and cancellation rules, per-record setup state, a start
  rule that waits for setups to settle, retry and cleanup rules for
  repeated `task_init` calls, and a setup failure path that bypasses the
  task's own retries. Not taken: tasks fed through a handle keep rollout
  setup off the dispatcher (their samples are set up in their own feeder),
  and setup in the attempt already isolates a failure to its task and
  retries it through the task's own retries.
- **Setting up the seed before the dispatcher starts**, as `prepare_options`
  does today. A slow build holds every task, and one failed configuration
  fails the run.
- **Keeping `os.chdir` for third-party providers, serialized.** Other tasks'
  samples still see the directory change.
- **Running each `task_init` in a thread or child process.** The directory is
  process-wide; a child process loses the provider's in-memory state.
- **Running providers' task-level subprocesses in the task directory**
  (`subprocess()` defaulting its `cwd` there inside a setup). Python-level
  reads would see the launch directory while subprocesses saw the task
  directory. Docker's setup commands (`compose_up`, `compose_build`,
  `compose_pull`, `compose_services`) inherit the launch directory, and
  Compose resolves a compose file's paths against its project directory;
  only some cleanup commands set `cwd` to the compose file's directory
  themselves. No surveyed provider needs the task directory as the
  subprocess default, so one rule (the launch directory, as in
  `sample_init`) is enough.
- **A `task_init_in_launch_dir` class attribute and a warning for providers
  without it.** The attribute's only effect would be to silence the warning,
  which would be a false alarm for every surveyed provider but Proxmox; the
  provider documentation and a Proxmox follow-up cover that case.
- **A public `sandbox_setup()` accessor for the task directory**, and a helper
  that resolves Docker's string configs inside a setup. Once Inspect makes
  config paths absolute, no surveyed provider needs the task directory in
  Python, so the accessor would be API nobody calls.
- **Exporting the lifecycle scope.** Every provider would have to adopt it;
  captured bindings make the existing pattern correct.
- **Clearing a failed row's frames instead of snapshotting its error**:
  keep `TaskError` with the real exception and traceback, and once the
  attempt ends run `traceback.clear_frames` over the exception, its
  `__cause__` and `__context__` chain and any exception-group members, so
  the row keeps file names and line numbers but no locals. Displays and
  logger formats would need no change. Rejected (decision: Ransom,
  2026-11-19) because the end of the attempt does not mean every frame in
  its error chain has finished. On Python 3.11 and 3.12 (Inspect supports
  3.11 and later), clearing the frame of a suspended coroutine or generator
  finalizes it; only 3.13 and later refuse. A failed task's error can carry
  such frames: the shared model `Batcher`
  (`model/_providers/util/batch.py`) catches one exception and awaits its
  fan-out to every waiting request, each of which re-raises that same
  object, so clearing one consumer's error could finalize the publisher
  while it is still failing the other requests. Making it safe would need
  a per-frame walk that skips suspended frames on those versions, a
  regression test that the `Batcher` keeps fanning out and cleans up after
  a consumer's frames are cleared, and recording the error on every path
  that completes a failed row, the error-log write timeout included. The
  snapshot holds no frames at all and needs none of that.

Alternatives for the handles are in
[task-handles.md](task-handles.md#alternatives-considered).

## Compatibility and migration

Eval authors' `enqueue_task()` calls on the run's event loop are unchanged:
it stays synchronous, and its new return value can be ignored. A call from
a worker thread that copied the run's context, which today buffers the
task, now raises `RuntimeError`; the worker calls
`anyio.from_thread.run_sync(lambda: enqueue_task(...))` instead. Third-party sandbox providers need
no change unless their `task_init`,
`task_init_environment` or `task_cleanup` relies on the process directory
being the task directory; of the surveyed providers only Proxmox does, for a
relative `PROXMOX_CONFIG_FILE`. No provider needs a release for any step
here. A provider other than Docker whose `task_init_environment` returns
variables (none of the surveyed ones does) now fails that task's setup
with a `PrerequisiteError` naming the migration: put the values in its
config and pass them to its subprocesses with `subprocess(env=...)`.

Sandbox setup moves from before the batch into each task's attempt. A
provider's `task_init` is called the same way, once per configuration per
run, but now while other tasks run, which today happens only on the live
path and for `SampleSource` additions, and after its task's `on_task_start`
hooks. A setup failure becomes the task's error log and is retried with the
task, where today it raises from `eval()` (and from an `eval_set()` round
without a retry); a provider whose `task_init` fails once and succeeds on a
second call now gets that second call. A call that raised still gets no
`task_cleanup`, as today, so what it allocated is the provider's to release
before it raises; the contract docs state this with the repeat-call rule.

Eval authors whose `ComposeConfig` on Modal or Daytona relies on a relative
or omitted build context resolving against the launch directory, where the
task directory also has a Dockerfile at that path, now build the task
directory's; to keep the launch directory's, write the build context as an
absolute path. A file-based config (a compose file path) is unaffected:
its contexts already resolve against the compose file's directory.

Known inspect-podman limitation, until it writes a generated compose file
per project: with an inline `ComposeConfig` or a missing config, a Podman
`task_init` that overlaps running Podman samples rewrites their shared
`.compose.yaml` in the launch directory and, if it fails, deletes it, so
those samples can lose their compose file. Overlap comes from any task's
setup at `max_tasks > 1`, since every task now sets up in its own attempt,
and from a `SampleSource` addition. A config given as a compose file is
unaffected. The fix is a
provider follow-up, not a gate for any step here (decision: Ransom,
2026-11-11).

Public API:

- `enqueue_task()` returns `list[TaskHandle]` and stays synchronous
  ([task-handles.md](task-handles.md)), and refuses a call off the run's
  event loop (above); its docstring and `docs/task-source.qmd`
  say added tasks start when there is room and that selectors naming each
  other need one call.
- `SandboxEnvironment`'s task-level calls run in the launch directory.

Logs: a task cancelled while queued is returned by `eval()` with today's
abort error log ("Task cancelled by user (abort)") and no file (empty
`location`), where today it would have run; one cancelled in its attempt
before it registers ends with the same abort log.
Code that reads `log.location` from `eval()`'s results gets an empty string
for it, as it already can for a task whose log could not be written. No eval
log schema, viewer type or config file changes here.

Displays: `TaskError` (in the private `inspect_ai._display`) holds a
rendered snapshot of the traceback instead of the exception and its
traceback; the Rich, Textual and log displays show the same output, and the
JSON logger keeps its `msg` and separate `exc_info` fields.

Model controllers: an added task's model gets its adaptive controller on
its first `generate`, not before its sandboxes are built, so an `inspect ctl
config --max-connections` retune made earlier is dropped with today's "not
using adaptive connections" warning when no other task uses that model,
until the follow-up that applies remembered retunes to a controller when
it is created; a bad adaptive setting on an added task ends that task with
its error log instead of raising from `eval()`.

Control channel: `GET /tasks` gains queued rows (`status: "queued"`); task
cancel, drain, pause and resume accept queued tasks (`task_queued` in a
cancel or drain result; a repeated one before the queued task's abort runs
answers "cancel already requested (abort)"); a task that ended without
starting stays listed as finished, and a repeated cancel or drain of it
answers "task already finished";
and `CONTROL_API_VERSION` increases. Older CLIs see an unknown status value.

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
  `task_init` awaits; `task_init`, `task_init_environment` and `task_cleanup`
  see the launch directory, and a `subprocess()` they start runs there;
  `resolve_config_paths` makes a relative
  string and a `ComposeConfig` build context absolute only when they exist
  under the task directory, sets an omitted `ComposeBuild.context` to the
  task directory, and leaves an inline-JSON string, a URI, an
  absolute path and an over-long string as given; a task-level relative
  string config naming a compose file that exists only in the launch
  directory, with the run launched there, sets up from the launch
  directory's file (today the run fails on the joined path); with the task in one
  directory, the run launched from another, and a different `Dockerfile` in
  each, a stub provider's `sample_init` receives a `ComposeConfig` whose
  relative context (`build: "."`, and an omitted context) is the task
  directory's absolute path, while a file-based control (a relative
  `compose.yaml` beside the task) arrives as that file's absolute path with
  its contents unchanged; a task-level inline-JSON config reaches
  `task_init` unchanged; per-setup bindings reach
  `sample_init`, `sample_cleanup` and the matching `task_cleanup` for two
  configurations, an added task's configuration and an empty `SampleSource`
  seed, with samples of both configurations starting from the run's original
  context: an E2B-style provider that rebinds a list per `task_init` gives
  each configuration's samples their own list, and a k8s-style get-or-create
  object created by the first configuration's `task_init` reaches the second
  configuration's samples too; a sample that bound a variable itself keeps
  its value; a failed `task_init`'s bindings reach no later setup; a sample
  whose config is a relative compose file resolves in `sandboxenv_context`
  to the spec its task's `task_init` got, and finds that configuration's
  bindings, for a seed sample and a `SampleSource` addition.
- `tests/test_retry.py`: a task loaded from a file in another directory,
  with the stub provider, fails once and is retried with `eval_retry()` from
  its saved log, run from a working directory different from both the first
  run's and the task's: an inline-JSON string config reaches the retry's
  `task_init` exactly as the first run's did, and a relative config file
  beside the task file (the control) reaches it as that file's absolute
  path.
- `tests/util/sandbox/test_docker_cleanup.py` and
  `test_docker_compatibility.py`: with the task directory different from the
  launch directory and a same-named file in each, a sample-level relative
  `compose.yaml`, a relative `Dockerfile`, a `ComposeConfig` build context,
  and a `ComposeConfig` service with `ComposeBuild()` and with
  `ComposeBuild(dockerfile="Dockerfile")` (no context; a different
  `Dockerfile` in each directory), on a seed sample and on a sample a
  `SampleSource` adds, select the task directory's file in
  `task_init_environment`, `task_init` and `sample_init`; with a file-based
  config beside the task and a relative `env_file` of the same name, with
  different values, in both the task and the launch directory, `task_init`
  and `sample_init` both get the `env_file` values from the compose file's
  directory; for interpolation, the test runs from a launch directory whose
  `.env` `init_dotenv()` loads into the process environment at run start,
  and the task directory has its own `.env`: a variable only the task
  directory's `.env` sets is interpolated from it, and one both set takes
  the launch value, which the compose subprocess inherits and which wins
  over the project's `.env`, as today, in both `task_init` and
  `sample_init`;
  the `SAMPLE_METADATA_*` values reach `compose build` through the project's
  `env`, and a Docker subclass overriding `task_init_environment` gets its own
  values there; a stub non-Docker provider whose `task_init_environment`
  returns `{"X": "1"}` raises the `PrerequisiteError` before its
  `task_init` is called (under step 1 from `eval()`, the run-level failure
  a setup error gives today), the same provider returning `{}` sets up as
  before, and `os.environ` is unchanged throughout. One `--runslow` real-Docker test builds a Dockerfile task
  loaded from another directory.
- `tests/test_enqueue_task.py` (invariants 1–6): an added task starts while
  its creator runs, under `eval()`, `eval_set()` and selection mode; in a
  faceted selection worker with pruning enabled, the selected creator's
  solver calls an unselected `@task` factory and adds the result, and the
  factory body and the added task's solver both run (needs the
  runtime-pruning guarantee, "Interactions with related changes"); a
  configuration error (a task with `epochs=Epochs(1, "at_least_2")`, whose
  reducer `validate_reducer` rejects with `PrerequisiteError`), a duplicate id (a `ResolvedTask` or `PreviousTask`
  added twice, listed twice, or added from outside an attempt in a
  two-model run) and a selection
  error raise at the call and add nothing; a parent that enqueues A and then B
  under `sample_id=["parent:1", "B:1"]` gets the selection error at A's call
  (a static A with no `B:1`), under `["parent:1", "1", "B:1"]` A runs its
  sample 1 and logs the not-found warning for `B:1`, a `SampleSource` A
  is filtered with no error or warning, and the same two in one call run
  as today; a literal namespaced id
  (`user:cybergym/arvo_6008`) still selects its sample; `enqueue_task()` run
  in a worker thread's own loop, and in a worker thread with no loop, raises
  `RuntimeError`, and through `anyio.from_thread.run_sync()` succeeds;
  after `eval_async()` returns, after a
  latched cancellation and after an exception left dispatch, a child task
  that kept the run's context raises `RuntimeError` with the resolver and the
  registry untouched; a queued task holds no recorder entry, temporary file or
  buffer database until it starts; a log-init failure, injected before
  `recorder.log_init()` (the file-name probe), inside it, and after the
  location is set, once and on every attempt, ends in an error log carrying
  the injected error after its retries, for a seed task and an added one,
  with no `AttributeError`, no retry reading the failed attempt's location,
  the other tasks completing and `eval_async()` returning rather than
  raising; at a
  latched cancellation, with a queued record and a pending retry, both end in
  the same step (no log, and the stored log), a sample in a sibling attempt
  awaiting the queued one in a shielded scope returns, and no further retry is
  published by an attempt that errors after the close, including one whose
  `reinit()` is held when the queue closes, after which that attempt's
  `EvalState` is terminal and no longer retry-pending, and a repeat
  `inspect ctl task cancel` answers "task already finished" rather than
  reporting an abandoned retry; the same with a cancellation from
  a scope around `eval_async()` and with a `debug_errors` exception; an
  attempt cancelled before its first step (the dispatcher's pick followed at
  once by a cancel of the record) aborts through the abort path and leaves
  no record in `attempt`, and neither
  does a cancellation of the attempt group right after a pick; with
  `debug_errors`, a fed task that raises while its creator sample's shielded
  `finally` awaits `handle.result()` releases that wait, the run ends, and
  the original error propagates; every record
  has ended when `eval_async()` returns or raises.
- `tests/test_enqueue_task.py` (setup in the attempt; stub provider whose
  `task_init` blocks on an event or fails on demand): at `max_tasks=2`, a
  sandbox-free task starts and finishes while another task's `task_init` is
  held, and the building task holds its slot meanwhile; a seed task whose
  setup fails ends with its error log while a sandbox-free seed task runs to
  completion and `eval_async()` returns both logs, and the same holds for a
  seed task refused for a non-Docker `task_init_environment` mapping (the
  stub provider above returning `{"X": "1"}`), whose error log carries the
  `PrerequisiteError` and whose `task_init` is never called; with
  `task_retry_attempts=1`, a setup that fails once is run again by the
  task's retry, which succeeds; with `task_retry_attempts=2`, a setup that
  fails twice and then succeeds is called three times, no `task_cleanup`
  runs after either failure, one runs at shutdown in the successful call's
  context, and the failed calls' bindings reach no sample; a setup that
  always fails, at `task_retry_attempts=1`, is called twice, the task ends
  with its error log, and no `task_cleanup` runs, then or at shutdown; two tasks needing one configuration call
  `task_init` once; a task cancelled while its `task_init` is held cancels
  the call, and the next task that needs the configuration runs it again;
  `on_task_start` fires before the task's `task_init` and a setup failure
  reaches `on_task_end` with the error log; under `run_samples=False` no
  setup runs and no controller is created.
- `tests/test_enqueue_task.py` (controllers): with two seed tasks on models
  with separate connection pools (two `openai/` model names with a dummy key
  and adaptive connections; two `mockllm` names share one pool and do not
  test this), an `inspect ctl config --max-connections` retune made while
  the first task's `task_init` is held sets both controllers' ceiling; a
  task added by `enqueue_task()` on a model no other task uses has no
  controller until its first `generate`.
- `tests/test_enqueue_task.py` (bad adaptive setting on an added task), with
  `debug_errors` off: a task added with `adaptive_connections=0` and no
  `max_samples` ends with its error log carrying the `AdaptiveConcurrency`
  validation error and no samples, after its retries, while a sibling task
  completes and `eval_async()` returns both logs; with `max_samples=1` and
  `fail_on_error=False` its samples carry the error; the same setting on a
  seed task raises from `eval()` as today.
- `tests/test_enqueue_task.py` (retention): while a long-running task keeps
  the run open, it adds sandbox tasks that end by finishing, by a cancel
  while queued, by a final failed retry, by a task-level error and by a
  sandbox setup failure; a `weakref` to each ended task's `Task` and dataset
  is dead after `gc.collect()` while its failed row is still held, under
  Rich and Textual, and the sandbox configuration they set up is still
  registered for the run's cleanup; the failed rows still render the
  traceback, with a chained cause, and `LogDisplay` logs the same text as
  today.
- `tests/util/test_logger_format.py`: beside
  `test_json_logger_format_includes_exc_info`, a record carrying a
  snapshot's `exc_snapshot` and no `exc_info` gives a JSON line whose `msg`
  is the status message and whose `exc_info` field holds the traceback text,
  and the plain and Rich formats give the same text as the `exc_info`
  record; `TraceFormatter` gives the same JSON for the snapshot record as
  for the `exc_info` record, with no `exc_snapshot` key, and still copies an
  unrelated extra field. `tests/test_task_cancel.py`'s two assertions on
  `TaskError.exc_value` read the snapshot's error text instead.
- `tests/test_enqueue_task.py` (live fixes): at `max_tasks=1`, a long seed
  task holds the only slot and a task it added waits behind it; `inspect
  ctl config --max-tasks 2` starts the added task while the seed task still
  runs; a queued task paused with
  `inspect ctl task pause` is skipped while the task behind it starts, and
  starts after `inspect ctl task resume`.
- `tests/test_enqueue_task.py` (loader exception): a solver's
  `enqueue_task("other_dir/tasks.py@name")`, whose module imports a sibling
  module and whose task reads a relative file at construction, adds and runs
  the task, and `os.getcwd()` afterwards is the launch directory.
- `tests/test_task_source.py`: with a `next_tasks()` held on an
  `anyio.Event`, a task that a background coroutine of the finished seed
  sample adds with `enqueue_task()` is listed and cancellable while the call
  blocks and starts when it returns, ahead of the returned batch; an
  exception from `next_tasks()` ends the run as today; a cancellation while
  `next_tasks()` blocks, from a scope around `eval_async()` on both backends
  and from SIGINT in an isolated child process, keeps the completed logs at
  `max_tasks` 1 and 2: `eval()` returns them on asyncio, and on trio raises
  `KeyboardInterrupt` after writing them (as
  `tests/util/test_async.py::test_run_main_trio_sigint` checks for a
  task); a source task cancelled while running, whose `task_complete`
  returns follow-up tasks with no checkpoint, leaves the outcome unchanged
  (the logs returned, nothing added, the "dropping" log line), and so does
  the same callback after a latched cancellation and during teardown after a
  `debug_errors` error, which still raises its original error;
  `next_tasks()` returning `[]` ends the source without calling the
  resolver; the existing live-injection test passes for a plain task list;
  a source that seeds A and B at `max_tasks=1` and returns from
  `next_tasks()` only after `task_complete` has reported both, each case
  ending B through the abort path with one report, the "Task cancelled by
  user (abort)" log, no retry, no log file, `next_tasks()` released and
  the run ending normally, on asyncio and trio: B cancelled, and in another
  run drained, while queued behind a running A, with `.eval` and `.json`
  logs (no location, no buffer database, no display row); B cancelled
  while queued and paused (the cancel starts it anyway); B cancelled before the task
  screen opens (Textual's app load held on an event), counted once off the
  total; B a queued retry whose first attempt's log init failed, cancelled
  while it waits (two reports: the failed attempt and the aborted one); B
  aborted while its `logger.init()` is held and while its `log_start()` is
  held; with A cancelled while queued ahead of B at `max_tasks=1` and A's
  `task_complete` waiting for B's report, A runs one attempt with one
  report, uncounted, and B starts in the slot; with A picked by the counted
  pick at `max_tasks=1` and cancelled after `start_attempt` returns and
  before its `run_one` runs its first statement (a test wrapper around
  `start_attempt` calls `RunQueue.cancel` on the record), A is aborted once
  at the explicit checkpoint with one report and no startup effects (no
  log file, no buffer database, no display row, no `on_task_start`), its
  counted slot is released once when it ends, B starts after that, and
  `in_flight` and every model count are zero at the end; with the dispatcher made to
  run several passes before an uncounted A's `run_one` begins, A is
  started once; an uncancelled retry gets a fresh `TaskCancel` (a drain of
  its registered attempt takes effect), a cancel while `run_one` awaits
  `reinit()` publishes no retry, and a cancel after the retry is published
  sets `abort_requested` and ends the retry through the abort path, on
  asyncio and trio; the existing stray-cancellation tests
  (`test_task_complete_raising_stray_cancellation_ends_run`,
  `test_stray_cancellation_after_log_finalized_ends_run`) pass unchanged; a source that seeds a successful A and a B whose
  `logger.init()` always fails, and returns from `next_tasks()` only after
  `task_complete` has reported A and B's final attempt, with
  `task_retry_attempts` 0 and 2: B is reported once per attempt (once, and
  three times) with its initialization error, that error stays B's result,
  and the run ends with `next_tasks()` released, on asyncio and trio; the
  same source with a B whose header flush always fails after `init()`
  returned, and in another run a B whose final write fails, with
  `task_retry_attempts` 0 and 2: B is reported once per attempt with the
  unwritten storage-error log that `eval_async()` returns for it, and the
  run ends with `next_tasks()` released; a B aborted, and in another run
  asked to retry, while its `log_start()` is held after `init()` returned
  is reported once with the unwritten "Task cancelled by user" log, on
  asyncio and trio.
- `tests/test_sample_source.py`: a mid-run configuration through
  `SandboxManager.start_for_samples`; its failure fails only that task, as
  today.
- `tests/test_task_cancel.py` and `tests/_control/test_ctl.py` (invariant 3):
  queued rows in `GET /tasks`, listed and cancellable from the moment
  `enqueue_task()` returns, including while `next_tasks()` blocks forever; a
  cancel and a drain of a queued record return `task_queued: true`,
  `in_flight: 0` (and `queued: 0`) in `--json` output and end it, on the
  dispatcher's next pass, with the abort log (status `error`, empty
  `location`, no file, returned by `eval_async()`); a repeated cancel and
  drain before that pass, with and without `--dry-run`, answer
  `changed: false`, "cancel already requested (abort)"; `score`/`error`
  answer 409; pause and resume of a queued task change its gate and report
  `status: "queued"` with its model, and `--dry-run` changes nothing; under
  `eval_set(retry_immediate=False)`, pause, resume and their `--dry-run` on a
  second round's queued record whose first round left a terminal
  `EvalState` act on and describe the queued record, which is skipped while
  paused and starts after resume; a
  cancel of a record in its attempt before `register_eval` aborts it, landing
  before `_run_task` enters the attempt's scope, while `logger.init()` is
  held and while `log_start()` is held, each ending the record with "Task
  cancelled by user (abort)", with retries left and no retry, and with the
  retry-abandon stamp unset and no `retry_abandoned` in the result, a retry's
  attempt included; the abort while `log_start()` is held, with a dataset
  paged to disk (`max_dataset_memory`), leaves no store file; a repeated
  cancel and drain of the aborting attempt, each with and without
  `--dry-run`, answer `changed: false`, "cancel already requested
  (abort)", while `logger.init()` is still held; a cancel landing while
  `run_one` awaits the `reinit()` of an unregistered attempt whose log init
  failed publishes no retry, ends the record with that attempt's error log
  and reports no `retry_abandoned`; a cancel of a queued record whose
  unregistered attempt failed and whose retry is waiting ends it with the
  abort log and no `retry_abandoned`;
  after a queued record is cancelled, after an unregistered attempt is
  aborted, and after an added task's attempt
  fails before `register_eval` with no retry left (`adaptive_connections=0`,
  `task_retry_attempts=0`), `GET /tasks` still lists the task as finished
  with zero samples, and a repeated cancel and drain, each with and without
  `--dry-run`, answer `changed: false`, "task already finished", not 404;
  under `eval_set(retry_immediate=False)` a second round's queued record is
  listed once; with another task keeping the run open, a queued record
  cancelled before it starts and an attempt aborted while `logger.init()`
  is held each lower the task total by one, and an abort while
  `log_start()` is held leaves it unchanged, so completed and total match
  once the run ends, under Rich and under Textual; with Textual's app load
  held on an event, one of two seed tasks cancelled during the load leaves
  1/1 once the survivor completes.
- `tests/test_eval_set.py`: a seed task cancelled while queued under
  immediate retries makes the eval set report failure, with the task's
  abort log among its logs and no task retry; every
  seed task cancelled reports failure; selection mode returns `False`; a run
  cancelled with a seed task still queued raises `KeyboardInterrupt`; a seed
  task whose sandbox setup fails is retried under immediate retries and
  succeeds when the second `task_init` does; under `retry_immediate=False` a
  seed task cancelled while queued in the first round runs in the next.
- inspect_sandboxes: a test per provider that two configurations and an added
  task's configuration clean up every sandbox, against an Inspect build with
  step 2; it needs provider API keys and runs where that repo's live tests run.
  Offline converter tests for Modal (`convert_compose_to_modal_params`) and
  Daytona (`create_single_service_params`): with a different `Dockerfile` in
  the task and launch directories and the working directory set to the
  launch directory, a `ComposeConfig` as Inspect resolves it (relative and
  omitted context) selects the task directory's `Dockerfile`, and the same
  config loaded from a compose file selects the file's directory's, as
  today.

The `--runslow` Docker tests run in the PR CI `slow-tests` job on PRs that
touch `src/inspect_ai/util/_sandbox/**` or `tests/util/sandbox/**` (steps 1
and 2 do); the rest run in the normal test job.

## Implementation plan

Each step is one PR and leaves `main` correct. Unifying the dispatcher first
would extend two of today's live-path bugs to plain evals (the process-wide
`chdir` overlapping running tasks, and a later `task_init` rebinding provider
state in the single `eval_run`), so the setup fixes come first.

1. **Sandbox setup without process-wide directory or environment changes.**
   `util/_sandbox/paths.py` (`resolve_config_paths`), `util/_sandbox/setup.py`
   (the `env` variable), `util/_sandbox/environment.py` (docstrings),
   `util/_sandbox/docker/docker.py` (reads the `env`),
   `_eval/loader.py` (`resolve_task_sandbox` and the retry's
   `resolve_task_file_sandbox` through the helper),
   `_eval/task/sandbox.py` (`resolve_sandbox` through the helper; no `chdir`
   in key resolution; the non-Docker `task_init_environment` refusal), `_eval/run.py` (`SandboxManager` without `chdir` and
   `environ_vars`), `docs/extensions-sandboxes.qmd`. Tests:
   `test_sandbox_setup.py` (the directory, environment and
   `resolve_config_paths` cases), `test_retry.py`, the Docker tests.
   `prepare_options` still awaits `logger.init()` inside its own `chdir`
   after this step; step 3a removes that await from the `chdir`, completing
   invariant 7.
2. **Provider state per setup.** `_eval/run.py` (`SandboxManager` runs each
   `task_init` in the chained context and records each configuration's
   bindings against the run's root context, and its context), `_eval/task/sandbox.py`
   (`sandboxenv_context` finds the sample's configuration by its resolved
   spec and task directory and applies its bindings where the root value
   holds), `_eval/task/run.py`. Fixes the E2B, Modal and Daytona
   leaks and `LookupError` with no inspect_sandboxes release. Independent of
   step 1. Tests: `test_sandbox_setup.py` (the per-setup binding cases:
   bindings reaching `sample_init`, `sample_cleanup` and the matching
   `task_cleanup` for two configurations, the shared k8s-style object, a
   sample's own binding kept, a failed `task_init`'s bindings reaching no
   later setup, and the empty `SampleSource` seed).
3. Step 3 is split in two (decision: Ransom, 2026-11-18): 3a is the queue
   and the dispatcher, which task handles need; 3b is the control channel's
   view of queued tasks, which they do not.

   **3a. One queue and one dispatcher; logs start with their attempt.**
   `_eval/task/enqueue.py` (`RunQueue`, `TaskRecord` with `reached`,
   `RunQueue.cancel` and `RunQueue.end` without the control-channel
   registration, `enqueue_task()` still returning `None`),
   `_eval/run.py` (`configure_task()` with the `chdir` kept around the
   logger's construction, `ensure_controllers()` for the seed only,
   `dispatch_tasks()` with the inline `next_tasks()` call and its dispatch
   waker, the uncounted start of an `abort_requested` record from the
   pending list, `RunQueue.cancel` setting `abort_requested`,
   `_run_task`'s single `notify_task_source` call for every attempt, a
   failed `init()` and a storage failure included, with `write_failed`
   and its early return removed,
   the dispatcher's synchronous `start_attempt` removing the entry from
   pending, counting it when counted, moving the record into `attempt` and
   creating the attempt's fresh `TaskCancel` (its `can_retry` from the
   remaining retry budget) and scope, aborting it when
   `abort_requested` is set, which `run_one` passes to `_run_task`;
   `run_one` dropping the pair when it publishes a retry or ends the
   record, and its closed and abort checks, the
   run's task
   names seeded from `eval_set_tasks`, `startup_sandboxes` and the record's
   resolution cache for every task, the display's task total lowered for a
   record that ends before its row opens; `prepare_options`, `TaskInjection`,
   `PreparedFeed`, `_empty_feed` removed), `_eval/eval.py` (one `eval_run`;
   the `max_tasks` docstrings, with `_eval/evalset.py`'s and
   `docs/parallelism.qmd`, naming the uncounted abort of a task cancelled
   while queued),
   `_eval/task/run.py` (an explicit checkpoint, then `logger.init()`, at the start of `task_run`; the
   seed's `startup_sandboxes` call after the task-start hooks;
   `on_row_opened()` and `on_registered()` moving `reached`;
   `unwritten_task_log` with no location),
   `_eval/task/task_source.py` (the `task_complete` docstring, which says
   "A task finished", says that it is called once per attempt, a failed
   one included, as `docs/task-source.qmd` already does, and drops "they
   run after the current batch"),
   `_display/core/display.py` (`TaskError.from_exception`),
   `_display/core/results.py` and `_display/log/display.py` (rendering the
   snapshot; logging its text as `exc_snapshot`), `_util/logger.py`
   (`LogHandler.emit` setting `exc_text` from it, `json_log_record` reading
   it), `_util/trace.py` (`TraceFormatter` excluding `exc_snapshot`),
   `tests/util/test_logger_format.py`,
   `_eval/task/log.py` (`reinit()` without `init()`, `discard()` without an
   entry, a `location` of `None` until
   `log_init()` returns), `_eval/evalset.py` (the no-log rule);
   `util/_sandbox/environment.py`
   and `docs/extensions-sandboxes.qmd` (the repeat-call rule);
   `design/task-source.md` ("Live
   injection"), `design/sample-source.md`. Tests: `test_enqueue_task.py`,
   `test_task_source.py`, `test_eval_set.py`, and the abort, reporting and
   display-total cases of `test_task_cancel.py`, each cancelling a queued
   or unregistered record through `RunQueue.cancel` (found with
   `RunQueue.find`). Needs steps 1 and 2; its selection-mode support, and
   the faceted-worker test above, rely on the runtime-pruning guarantee
   ("Interactions with related changes").

   The failed-`init()` report to a `TaskSource` cannot be left to a later
   step: once `logger.init()` runs inside the attempt, a source waiting on a
   task whose `init()` failed would otherwise wait forever. 3a leaves `main`
   correct on its own: a queued record, and an attempt that has not reached
   `register_eval`, are invisible to the control channel, as a task waiting
   to start is on `main` today (`inspect ctl task cancel` answers 404 "not
   found"), and a record that ends without registering is not listed
   afterwards, as a task that never registered is not today. Nothing public
   calls `RunQueue.cancel` until 3b or task handles.

   **3b. Queued tasks in the control channel** (invariant 3).
   `_control/queued_tasks.py` (new; the queued registry, which
   `RunQueue.add` fills and `RunQueue.end` and `on_registered()` empty),
   `_control/eval_state.py` and `RunQueue.end` (terminal identity through
   `register_completed_eval` for a record that ends without registering),
   `_control/cancel.py` (the registry first in `_task_cancel_directive`,
   and the attempt's `attempt_cancel` answers), `_control/pause.py` (queued
   pause and resume), `_control/state.py` (queued rows in `GET /tasks`),
   `_control/__init__.py` (`CONTROL_API_VERSION`), `_cli/ctl/_task.py`;
   `design/ctl/task-drain.md` ("Out of scope"). Tests:
   `test_task_cancel.py` and `_control/test_ctl.py` (listing, cancel,
   drain, pause and resume of queued tasks through `inspect ctl`, repeated
   directives, finished rows of records that never registered), and 3a's
   queued and unregistered cancels in `test_task_source.py` and
   `test_eval_set.py` made again through `inspect ctl`. Needs 3a.

Then, needing step 3a: **task handles**, one PR ([task-handles.md](task-handles.md)).

Follow-ups in provider repositories, none a gate (decision: Ransom,
2026-11-11, for Podman):

- inspect_sandboxes adds the per-provider cleanup tests and the offline
  Modal and Daytona converter tests.
- UKGovernmentBEIS/inspect_proxmox_sandbox documents `PROXMOX_CONFIG_FILE`
  as launch-relative, or warns when a set file is not found.
- VectorInstitute/inspect-podman writes a generated compose file per
  project, as Inspect's Docker provider does (in progress). Its test runs
  sample A while setup B writes its generated file and then fails, with an
  inline `ComposeConfig` and with a missing config, and checks that A's
  compose file is unchanged and still present; a file-based config (a
  compose file path) is the control.

## Open questions

None. Decided: Ransom (2026-11-09) that a task's log starts with its attempt,
that selection is resolved at the call, and that config paths are
resolved by Inspect against the task directory;
(2026-11-11) that third-party providers' task-level calls, and the
subprocesses those start, run in the launch directory with no
`task_init_in_launch_dir` attribute and no warning (replacing the 2026-11-03
decision to warn), and that `TaskSource.next_tasks()` is awaited inline; and
(2026-11-12) that each task sets up its own sandboxes in its attempt, the
way `SampleSource` additions are set up, inside its `max_tasks` slot
(replacing the 2026-11-03 and 2026-11-05 decisions to set up beside the
dispatcher and outside the slot, whose evidence was rollout tasks, which
now take the handle path), that a sample resolves its config again rather
than keeping a per-sample key, that the seed's controllers are created
before it is added and an added task's lazily on its model's first
`generate`, with no eager call, that
a record has three phases with registration tracked apart, that the `chdir`
stays around the synchronous construction of a task's logger; and
(2026-11-16) that `enqueue_task()` stays synchronous and returns handles,
reversing the 2026-11-09 decision to make it async once adding a task
awaited nothing (its reasons restated 2026-11-18: adding a task awaits
nothing, and an async version would silently break every existing call
that does not await it), that an attempt cancelled before it registers is stopped
by its own abort, not the retry-abandon stamp (replacing that part of the
2026-11-12 three-phase decision), and that cancels under legacy
`eval_set()` rounds are not refused (replacing the 2026-11-12 refusal),
that a failed task's display row keeps a frame-free snapshot of its error,
and that each attempt's outcome, a failed `init()` included, reaches the
`TaskSource` through one rule (with today's two exceptions, narrowed
2026-11-18 to the preview); and
(2026-11-17) that a queued cancel becomes an attempt that aborts before it
starts, started uncounted on the dispatcher's next pass, so it ends and is
reported through the abort path (replacing the 2026-11-12 in-memory
"cancelled before it started" log and the 2026-11-16 report on the
dispatcher's next pass), and that a record leaves `queued` in the
dispatcher's pick, so a cancel after the pick aborts a counted attempt that
keeps its slot until it ends; and (2026-11-18) that every attempt is
reported to the `TaskSource`, an attempt whose log storage failed after
`init()` included, with no `storage_failed` flag and no
`TaskLogger.initialized` (reversing the 2026-11-16 storage exception), that
step 3 of the plan is split into 3a (the queue, the dispatcher, logs that
start with their attempt with the failed-`init()` report, and the display's
error snapshot) and 3b (queued tasks in the control channel), with task
handles needing 3a only, and that an added task's model controller stays
lazy (the 2026-11-12 decision kept), with remembered `--max-connections`
retunes applied when a controller is created as a follow-up rather than an
eager controller for added tasks; and (2026-11-19) that an ordinary task
added from inside a running task keeps today's settings resolution (the
run's values win), with only a task fed through a handle resolving its own
first ([task-handles.md](task-handles.md#tasks-fed-through-a-handle)),
narrowing the 2026-11-18 decision that every task added from inside a
running task follows one task-first rule and replacing the 2026-11-19
answer that such an ordinary task keeps its own `epochs` and reducer as a
pair, because applying it to ordinary added tasks changed an existing
feature and brought compatibility work that fed tasks, being new, do not
need. The 2026-11-19 decision to keep `TaskError` and clear its frames in
place of the snapshot is withdrawn (decision: Ransom, 2026-11-19), because
clearing a suspended frame on Python 3.11 and 3.12 finalizes a coroutine
that may still be running (see
[Alternatives considered](#alternatives-considered)); the frame-free
snapshot stands.

## Not this design

- Building sandboxes outside the task's slot, and setup retries apart from
  the task's own (background setup; see "Alternatives considered").
- A task added while `next_tasks()` blocks starting before the call returns.
- A `max_connections` retune reaching a controller created after it: a
  task added after the retune gets a controller at its configured ceiling.
  Today's behaviour for every later batch, unchanged. Widened for added
  tasks, which get no eager controller: a retune made before an added
  task's first `generate` (while it is queued or building its sandboxes) is
  dropped with today's "not using adaptive connections" warning when no
  other task has created that model's controller. A task fed through a
  handle escapes it only when its pool already has a controller the retune
  reached, as when it shares a seed creator's model ("Adding tasks").
  The follow-up that fixes it, a PR of its own (decision: Ransom,
  2026-11-18): the control channel keeps every `--max-connections` retune
  for the run, with its model filter, including one that reaches no
  controller when it is made, and controller creation
  (`ensure_model_controller`, and the lazy creation in a model's first
  `generate`) replays the kept retunes in the order they were made,
  applying each whose model filter matches the new controller, so the
  latest matching retune decides its ceiling, as later retunes overwrite
  earlier ones on a live controller. Whether one retune's filter matches a
  controller follows the per-request name rule a live retune uses
  (`_match_controllers`, `_control/limits.py`: a prefix at the name start
  or after a `/`, an exact name winning among the controllers one request
  names); an older exact-name retune does not outrank a newer prefix one.
  Controllers stay lazy; nothing is created eagerly. The follow-up also
  specifies what the retune's answer and the logs record when it reaches
  no controller yet.
- A provider's own lookups in `sample_init` (a missing config's compose-file
  search) seeing the task directory.
- A caller's own cancellation of `eval_async()` (for example
  `anyio.fail_after`) being absorbed by `_run_task_screen` like a Ctrl-C.
- `TaskSource` under `eval_set()` (see `design/task-source.md`).
- The log a retry ends with when it is abandoned inside a startup `await` and
  that startup write then fails: `run_one` stores the returned log over the one
  kept before the retry. Today's behaviour, unchanged.
