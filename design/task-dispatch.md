# Task dispatch

## Overview

Every eval run has one task queue and one dispatcher. Seed tasks, tasks
added with `enqueue_task()`, tasks a `TaskSource` returns and task retries
all go through that queue, and a task starts as soon as a `max_tasks` slot
is free, under `eval()`, `eval_set()` and eval-set selection-mode workers
alike. Adding a task checks its configuration and sample selection at
once, so a mistake raises to the caller, and a task's log file is created
only when its attempt starts. Every task in the queue, including one that
has not started, is listed by the control channel and can be cancelled
or drained, and stays listed as finished once it ends.

Each task sets up its own sandboxes (a provider's `task_init`) inside its
attempt, so the dispatcher never waits for an image build: a task without
sandboxes starts at once, a task holds its slot while it builds, and a
setup failure ends only that task, which is retried like any other task
failure. Setup never changes the process's working directory or
environment: Inspect makes relative config paths absolute against the task
directory before a provider sees them, and every provider call runs in the
launch directory. The `ContextVar` state a provider binds in `task_init` is
captured per setup, so each `task_cleanup` sees the state its own
`task_init` produced and each sample the state its configuration's
`task_init` produced, whichever task's attempt ran the setup (with one
sharing limit, under "Provider state per setup").

[task-handles.md](task-handles.md) builds on this queue: handles that let a
running task cancel the tasks it adds, send samples to a task fed through
its handle and wait for that task's log.

## Why

A long-running task that decides what to try next from earlier results (an
adversarial search run for hours as one Inspect task) needs to start
rollout tasks beside itself and wait on them, under `eval()`, under
`eval_set()` and under external supervisors whose workers run `eval_set()`
in selection mode. That needs three things of the runner:

- a task added during the run starts while its creator runs, as soon as
  there is a free slot, rather than after some batch of tasks has
  finished, or a creator waiting on it waits forever;
- a task waiting to start is visible to the control channel, so an operator
  can list and cancel it;
- one task's sandbox setup does not change the process-wide working
  directory or environment that other tasks' running samples see.

One queue and one dispatcher for every run shape give all three in one
place.

## How it works

User documentation: "Adding tasks imperatively", "Defining a source" and
"Returning follow-up tasks" in [Task Sources](../docs/task-source.qmd);
the cancelled-task exception in "Multiple Tasks" in
[Parallelism](../docs/parallelism.qmd#sec-multiple-tasks); "Listing Tasks",
"Cancellation", "Pause and Resume" and the task-limit retune in
"Configuration" in
[Control Channel](../docs/control-channel.qmd); and the directory,
environment and repeat-call rules for providers in "Lifecycle Methods" in
[Sandbox Extensions](../docs/extensions-sandboxes.qmd#sec-lifecycle-methods).

Code:

- `src/inspect_ai/_eval/task/enqueue.py`: `enqueue_task()`, the run queue
  (`RunQueue`, `TaskRecord`) and the run-loop check (`_require_run_loop`).
- `src/inspect_ai/_eval/eval.py`: `_eval_async_inner` creates the queue and
  binds it for the run; `_resolve_enqueued_tasks` resolves added tasks.
- `src/inspect_ai/_eval/run.py`: `eval_run` (with `configure_task`),
  `ensure_controllers`, `dispatch_tasks` (with `start_attempt` and
  `run_one`), `_attempt_cancel`, `_run_task`, `_next_tasks`,
  `_run_task_screen` and `SandboxManager`.
- `src/inspect_ai/_eval/task/run.py`: `task_run` (the attempt's startup
  order), `notify_task_source`, `_enqueue_source_tasks`, `_RowErrors` and
  `unwritten_task_log`.
- `src/inspect_ai/_eval/task/log.py`: `TaskLogger.init`, `reinit`,
  `discard`, `location` and `destination_written`.
- `src/inspect_ai/_eval/task/sandbox.py`: `resolve_sandbox`,
  `resolve_sandbox_for_task_and_sample` and `SandboxSetupBindings`;
  `src/inspect_ai/_eval/loader.py`: `resolve_task_sandbox` and
  `resolve_task_file_sandbox`.
- `src/inspect_ai/util/_sandbox/paths.py` (`resolve_config_paths`) and
  `src/inspect_ai/util/_sandbox/setup.py` (`task_init_env`,
  `current_task_init_env`, read by Docker's `task_init`).
- `src/inspect_ai/_control/queued_tasks.py` (the queued registry),
  `src/inspect_ai/_control/cancel.py` (`_queued_task_directive`),
  `src/inspect_ai/_control/state.py` (`_add_queued_tasks`),
  `src/inspect_ai/_control/eval_state.py` (`register_completed_eval`) and
  `src/inspect_ai/_cli/ctl/_task.py`.
- `src/inspect_ai/_display/core/display.py`: `TaskError`.
- `src/inspect_ai/_eval/evalset.py`: `run_eval`'s rule for a requested
  task with no log.

Tests need no network or provider; the async ones also run on trio, and
the Docker ones are gated slow tests:

- `tests/test_enqueue_task.py`, section "one queue, one dispatcher":
  starting while the creator runs, refusals, log start, setup in the
  attempt, the display total and the release of ended tasks.
- `tests/test_task_source.py`, section "one queue, one dispatcher":
  `next_tasks()`, reporting to the source, cancels before registration,
  Ctrl-C and dropped returns.
- `tests/test_task_cancel.py` and `tests/_control/test_ctl.py`: aborts,
  retry-pending state, queued rows and directives
  (`test_queued_task_is_listed_and_cancelled_through_the_control_channel`,
  `test_ctl_lists_and_cancels_a_queued_task_in_a_live_run`).
- `tests/test_eval_set.py`: queued cancels and setup retries under
  `eval_set()` (`test_eval_set_task_cancelled_while_queued_*`,
  `test_eval_set_retries_task_whose_sandbox_setup_failed`).
- `tests/util/sandbox/test_sandbox_setup.py` (launch directory,
  environment, `resolve_config_paths`, `test_setup_bindings_*`),
  `tests/util/sandbox/test_docker_cleanup.py` (Docker's paths and
  `task_init_environment`), `tests/test_retry.py`
  (`test_eval_retry_sandbox_config_from_another_directory`) and
  `tests/util/test_logger_format.py`
  (`test_task_error_snapshot_holds_no_frames_once_released`).

### Run shapes and what is refused

Supported: `eval()`/`eval_async()` with a task list or a `TaskSource`;
`eval_set()` including selection mode; `SampleSource` tasks;
`enqueue_task()` from a solver, scorer, tool, hook or `TaskSource`
callback; the control channel. Refused, each with a clear error and before
anything is added:

- A `TaskSource` passed to `eval_set()`, `eval_retry()` or `score()`.
- `enqueue_task()` with no run in progress or a mismatched `run_id`:
  `RuntimeError`.
- `enqueue_task()` after the run's dispatch has ended, from a task that
  outlived it and kept its context: `RuntimeError`, before anything is
  resolved (`test_enqueue_task_after_dispatch_ended_raises`).
- `enqueue_task()` off the run's event loop, for example from a worker
  thread that copied the run's context: `RuntimeError` that says how to
  call it on the run's loop instead, as "Adding tasks imperatively" in the
  user docs does (`test_enqueue_task_off_the_run_loop`).
- A task id the run already holds, or one repeated in the batch:
  `ValueError` ("Adding tasks").
- Handle misuse: see
  [task-handles.md](task-handles.md#what-is-refused).

### The run queue

The run queue (`RunQueue` in `src/inspect_ai/_eval/task/enqueue.py`) owns
every task of a run. `_eval_async_inner` creates one per run and binds it
for `enqueue_task()`; `eval_run` opens it, adds the seed and runs the
dispatcher until every task has ended. Every task × model is one
`TaskRecord` from the moment it is added until it ends: queued (waiting
for a first attempt or a retry), in an attempt, or ended with its final
log or none. Only the run's event loop changes the queue, in synchronous
steps, so it needs no lock. An ended record releases its configured task
and dataset, so a finished task's samples can be freed while the run goes
on. [task-handles.md](task-handles.md#what-the-handles-add-to-the-run-queue)
adds a sample channel and a creator to a fed task's record.

#### Adding tasks

Adding is synchronous and all or nothing: `RunQueue.add` checks the whole
batch (the run is open, the call is on the run's loop, no task id repeats
one the run holds, and each task configures; `configure_task` in
`eval_run` applies the eval-level overrides, runs the configuration
checks, resolves the sample selection and builds the task's logger) before
it commits any of it. A failed check raises to whoever added the batch and
adds nothing; a `ResolvedTask` or `PreviousTask` keeps its id, so it can
be added once, and from outside a running task only in a run with one
model (`test_enqueue_task_errors_raise_at_the_call_and_add_nothing`).

Who adds, and where errors go:

- `eval_run` adds the seed; errors raise from `eval()`.
- `enqueue_task()` adds what `_resolve_enqueued_tasks` resolves (once under
  the creator's model inside a running attempt, else once per run model;
  [task-source.md](task-source.md#relationship-to-enqueue_task)); errors
  raise to its caller.
- What a `TaskSource` returns is added for the source
  (`_enqueue_source_tasks`), and where an add error goes depends on the
  callback. A `sample_complete` or `sample_abandoned` return is added
  inside its task's attempt, so an add error fails that task, which ends
  with its error log while the other tasks run on. A `task_complete`
  return and a `next_tasks()` batch are added outside any attempt, so an
  add error ends the run (`test_task_complete_returned_task_error_propagates`).
  An exception raised by `task_complete` itself is a separate case
  ("Reporting to the source"). Once dispatch has ended, what the source returns is dropped with a
  warning instead, so a callback that runs in a cancelled attempt's
  shielded cleanup cannot replace the run's outcome
  (`test_source_returns_after_the_run_stopped_are_dropped`).
- An `on_run_start` hook's `enqueue_task()` resolves at the call and is
  added right after the seed, so it starts after the seed and a
  configuration error in it raises from `eval()` before any task starts
  (`test_enqueue_task_from_run_start_hook_config_error_fails_the_run`).

**Selection resolves at the call**, so its errors reach the caller. A
task's `task:id` selectors resolve against the run's task names so far,
which start with the whole eval set's names, plus the batch's own. Tasks
whose selectors name each other must therefore be added in one call: a
task added first reads a selector naming a later task as a literal sample
id. The seed and a `next_tasks()` batch are each one call.

**The logger is built under a synchronous `chdir`** to the task's
directory, because its constructor reads the git context and relative
paths against the process directory. Nothing in that block awaits, so no
other coroutine sees the change.

**Model controllers.** The seed's adaptive connection controllers are
created before the seed is added (`ensure_controllers`), so a
control-channel connection-limit retune reaches them while images build and a bad
adaptive setting on a seed task raises from `eval()`. An added task's
controller is created on its model's first `generate`, as for any model the
seed does not use, so a bad adaptive setting on it fails inside its
attempt (the task, or each of its samples under the task's sample-error
policy, ends with the error) rather than
in whoever added it, and a connection-limit retune made before that
`generate` misses it unless another task already created that model's
controller ("Not this design").

#### Phases and cancelling

**Starting an attempt.** A record leaves `queued` in the dispatcher's pick,
in the same synchronous step that counts its slot and creates the
attempt's own cancel handle (`start_attempt` and `_attempt_cancel` in
`dispatch_tasks`). So a cancel landing at any moment after the pick reaches
that attempt, which keeps its slot until it ends, as a running task does,
and every attempt, a retry included, gets a fresh handle. An attempt
cancelled before it ran stops before any startup side effect: no display
row, task-start hook, log file or buffer database
(`test_cancel_of_attempt_before_it_registers_aborts_it`).

**Cancelling a task that has never registered** (`RunQueue.cancel`, reached
by the control channel and by a handle's `cancel()`):

- An ordinary task is aborted, as the control channel's task cancel
  aborts a running task. A queued one gets an attempt that the dispatcher starts on
  its next pass, outside `max_tasks` and through any pause, and that aborts
  before its log starts; it ends with an unwritten "Task cancelled by user
  (abort)" error log with an empty `location`
  (`test_cancel_of_queued_task_aborts_it_before_it_starts`). A handle's
  `cancel()` that lands while a failed attempt prepares its retry stops the
  retry, and the record ends with that attempt's log. The control
  channel's cancel defers its abort instead ("Control channel"): the retry
  is queued and aborts before it starts, so the task ends with the abort's
  error log and its source hears of both attempts
  (`test_ctl_cancel_while_unregistered_attempt_prepares_retry_ends_it`).
- A fed task still queued ends at once with no log and no attempt
  ([task-handles.md](task-handles.md#closing-and-cancelling)).

A task that has registered is cancelled as the control channel's task
cancel cancels it: a running attempt is aborted, a pending retry abandoned. An
abort is never retried, so an ordinary task whose abort is delivered before
it registers ends with the abort's error log, not an earlier attempt's, and
an eval set or selection worker that requested it reports failure. A
deferred control-channel abort is delivered only when an attempt
registers: if the starting attempt fails first and no retry remains, the
abort is never delivered and the task ends with that failure's error log,
reported to the source once.

**An attempt's exception exit ends its record** before the exception
propagates, so a handle wait on it held in another attempt's shielded
cleanup is released and the attempt group can join.

**Reporting to the source.** Each attempt's outcome reaches the run's
`TaskSource` once (`notify_task_source`), after the attempt's cancel scope
has exited: a written log, an aborted attempt's unwritten abort log, or the
unwritten error log of an attempt whose log initialisation or later log
storage failed (`test_every_attempt_is_reported_including_failed_log_init`,
`test_attempt_whose_log_storage_failed_is_reported`). A task retried twice
is reported three times. Not reported: a preview (`run_samples=False`), an
attempt abandoned by the retry-abandon stamp (it has no log of its own), a
record ended unstarted when dispatch ends, a fed task that ends before
it starts, and an attempt that exits by exception before it is reported: a
run cancellation (Ctrl-C) during its startup, or an error re-raised under
`debug_errors`. A source therefore hears of every attempt that returns,
not of every attempt the dispatcher picked. A `task_complete` exception is logged and leaves the attempt's
log as its result (it propagates under `debug_errors`); a cancellation that
no cancellation of the run caused becomes a `RuntimeError` that ends the
run (`test_task_complete_raising_stray_cancellation_ends_run`).

**Listed after it ends.** A record that ends before any attempt registered
is registered with the control channel as a finished eval with zero
samples (`register_completed_eval`) as it leaves the queued registry, so
the control channel's task list shows it as finished and a repeated cancel or drain
answers "task already finished" rather than 404
(`test_task_failing_before_it_registers_stays_listed_as_finished`).

**The display's task total** counts every record, while the Rich and
Textual displays count completed tasks from the rows attempts open, so a
record that ends without opening its row lowers the total by one, once
(`test_task_total_lowered_once_for_a_task_that_never_opened_its_row`).

**Display rows keep no frames.** The task screen lasts the whole run and
keeps every row's result. A failed row's `TaskError` keeps a frame-free
snapshot of the error, and the live exception only until the row closes
(for the log display, which logs it then), so a failed task's locals, its
dataset among them, are not kept for the rest of the run
(`test_ended_tasks_are_released_while_their_rows_are_held`,
`test_task_error_snapshot_holds_no_frames_once_released`).

#### A task's log starts with its attempt

`task_run` initialises the task's log as the first step of each attempt,
so a queued task or a pending retry holds no recorder entry, temporary
file or sample buffer database
(`test_queued_task_holds_no_log_until_it_starts`). A failed initialisation
ends that attempt with an error log carrying the storage error, the task
is retried alone and the other tasks run on, so a seed task whose log
cannot be initialised no longer fails `eval()`
(`test_log_init_failure_ends_only_that_task`). Such a log's `location`
is empty when the failure came before a destination was allocated, and
otherwise names that destination; a nonempty `location` does not mean a
complete log was written there.

### The dispatcher

`dispatch_tasks` runs every attempt of the run in one task group inside
the task screen (`_run_task_screen`), which absorbs a cancellation of the
run body so the run returns the logs it has. What it guarantees:

- **A task starts as soon as a slot is free**, for every run shape,
  whenever it was added (`test_added_task_starts_while_its_creator_runs`,
  `test_added_task_starts_while_its_creator_runs_in_eval_set`). The
  dispatcher takes the earliest startable task among the least-used
  models; a task held by a control-channel pause is not startable. At
  `max_tasks == 1` all of one task definition's models run together, and
  the run returns its logs in that order
  (`test_initial_tasks_parallel1_preserves_sequence_grouping`).
- **`max_tasks` bounds counted attempts**, including one building its
  sandboxes. A task cancelled while queued and a fed task that holds a
  sent sample start uncounted, so an aborting task and its `task_complete`
  callback can run beside `max_tasks` counted attempts.
- **The dispatcher never awaits a sandbox setup**; each attempt sets up
  its own ("Sandbox setup in the attempt").
- **A retune, pause or resume takes effect at once**: the queue's wake is
  a dispatch waker (`add_dispatch_waker`), so raising `max_tasks` or
  lifting a pause starts held tasks.
- **Retries** go to the back of the queue. `task_retry_attempts` is one
  run-wide value: `eval()`'s argument, `eval_set()`'s `retry_attempts`
  under immediate retries and 0 otherwise, and 0 in a selection-mode
  worker. No retry is published once dispatch has ended or an
  unregistered attempt has been aborted, and no `EvalState` is left
  retry-pending for a retry that does not exist
  (`test_unregistered_final_retry_clears_retry_pending`).
- **`next_tasks()` is awaited inline**, only when nothing is queued or
  running, and nothing starts while it blocks: a task that a hook or a
  leftover coroutine adds during the call is listed and cancellable at
  once and starts when the call returns, ahead of the returned batch
  (`test_task_added_while_next_tasks_blocks_starts_first`). A Ctrl-C while
  it blocks is absorbed like one during a task and the completed logs are
  kept (`test_cancellation_while_next_tasks_blocks_keeps_completed_logs`,
  `test_sigint_while_next_tasks_blocks_keeps_completed_logs`); on trio,
  `run_main` still raises `KeyboardInterrupt` after the run returns, as for
  a Ctrl-C during a task. An exception it raises ends the run.
- **Once dispatch ends, nothing more starts.** On every exit, in one
  synchronous step before the attempt group joins, the queue refuses later
  additions and retries and every queued record ends with its stored log.
  That settles every handle wait on those records, including waits in
  shielded cleanup that would otherwise hold the join open. When the run
  ends, any record still open is ended, then the sandboxes are shut down.
- **`debug_errors`** raises task errors at every `max_tasks`
  (`test_debug_errors_raise_at_every_max_tasks`).

#### Sandbox setup in the attempt

Each attempt sets up the sandboxes its selected seed samples need
(`startup_sandboxes`, bound to `SandboxManager.start_for_samples`) after it
registers and its task-start hooks run, before its first sample, and a
`SampleSource` task's feeder does the same for the samples it adds
(`test_setup_runs_in_the_attempt_after_registration`). A preview sets up
nothing (`test_preview_runs_no_setup`).

- **Shared configurations.** `SandboxManager` is run-wide. A setup is
  identified by the resolved sandbox spec, the task's directory and the
  values Docker's `task_init_environment` returned
  (`TaskSandboxEnvironment` in `src/inspect_ai/_eval/task/sandbox.py`), and
  each identity is set up successfully at most once per run, so two tasks
  that share all three set up once, the second waiting for the first
  (`test_two_tasks_needing_one_configuration_set_it_up_once`). The same
  spec used from two task directories, or with different metadata values
  for its `task_init_environment`, gets a `task_init` and a `task_cleanup`
  of its own for each. The task display is suspended during the call.
- **Setups run one at a time across the run.** A task that needs a
  configuration not yet set up waits for any other setup in progress,
  holding its slot while it waits, and so does a `SampleSource` feeder
  adding samples that need one; tasks and samples whose configurations are
  already set up do not wait.
- **Slots.** An attempt holds its slot while it builds, and the dispatcher
  starts other tasks meanwhile, so a task with no sandboxes, or whose
  configurations are set up, starts at once
  (`test_sandbox_free_task_runs_while_another_task_builds`).
- **Failure.** A setup error ends only that task, with its error log, and
  it is retried under `task_retry_attempts`
  (`test_setup_failure_ends_only_its_task_and_is_retried`). A failed
  configuration is not marked set up, so a retry, or another task that
  needs it, runs `task_init` again; a call that raised gets no
  `task_cleanup`, so the provider releases what it allocated before
  raising. The provider docs state this repeat-call rule.
- **Cancellation.** Cancelling an attempt during its `task_init` cancels
  that call, and nothing is marked set up.

### Control channel

The queued registry (`src/inspect_ai/_control/queued_tasks.py`) lists
every task of the run, fed tasks included, from the moment it is added
until its first attempt registers its `EvalState` or it ends, and a task
that ends without registering is registered as finished as it leaves, so a
directive always finds a task in one of the two. The registry takes
precedence over `EvalState` history for the same id, since each
`eval_set(retry_immediate=False)` round is its own `eval()` that keeps the
task id while `EvalState`s persist across rounds. The user-visible
behaviour is documented in
[Listing Tasks](../docs/control-channel.qmd#listing-tasks) and
[Cancellation](../docs/control-channel.qmd#cancellation):

- **`GET /tasks`** lists a queued task with `status: "queued"`
  (`_add_queued_tasks`): a task with no registered history has zero sample
  totals, and one an earlier `eval_set(retry_immediate=False)` round ran
  keeps that round's counters and log location under the queued status
  (`test_queued_task_with_earlier_round_reads_queued_and_current_pause`).
  CLI selectors resolve a queued task like a running one, but it is never
  the default target of a mutation.
- **Task cancel and drain** of a task that has not registered
  (`_queued_task_directive`) abort it. A task waiting for a slot follows
  `RunQueue.cancel` (`task_queued`). A task whose attempt is starting gets
  its abort when it registers (`abort_deferred`), so its startup writes are
  never interrupted
  (`test_ctl_cancel_of_starting_attempt_aborts_it_when_it_registers`); a
  starting preview never registers, so the directive changes nothing
  (`test_ctl_cancel_of_starting_preview_is_a_no_op`). The score and error
  resolutions are refused: the task has no samples to resolve.
- **Task pause and resume** find a task only through its `EvalState`. A
  queued task that has never registered answers "not found", though `task
  list` shows it; a pending retry of a task that has registered is paused
  and resumed as before, and the pause holds its retry
  (`tests/_control/test_pause.py::test_pause_task_between_attempts_parks_the_retry`).
  Process and model pauses hold queued tasks
  ([Pause and Resume](../docs/control-channel.qmd#pause-and-resume)).
- **`CONTROL_API_VERSION`** records the queued rows and the new cancel
  results; older CLIs see an unknown status value.

**Under `eval_set()`.** An ordinary task cancelled before it starts ends
with the abort's error log, so `eval_set()` reports failure, a selection
worker returns `False`, and under immediate retries no task retry follows.
A requested task with no log at all was still queued when the run was
cancelled, so `run_eval` raises `KeyboardInterrupt`, except for a task
whose retry an operator abandoned between rounds. Under
`retry_immediate=False` the next round reruns every requested task that
did not succeed, a task cancelled while queued included
(`test_eval_set_task_cancelled_while_queued_runs_in_the_next_round`); a
task whose retry was abandoned is passed to later rounds but ends there
with no attempt and no log, its earlier error log standing, and that is
not read as a cancellation of the set
(`test_retry_abandoned_between_passes_is_not_a_cancel`).

### Setup does not change the process's directory or environment

No `os.chdir` or `os.environ` write spans an `await` in sandbox setup,
configuration resolution or cleanup. Every provider call
(`task_init_environment`, `task_init`, `sample_init`, `task_cleanup`) runs
in the launch directory with the process's own environment, and a running
sample's `os.getcwd()` and `os.environ` are unchanged while another task
sets up (`test_setup_runs_in_the_launch_directory`,
`test_running_sample_keeps_directory_and_environment_during_setup`). The
directory changes left in a run are synchronous: building a task's logger
("Adding tasks") and loading a task from a file, whose local imports and
relative reads need its directory; no other coroutine sees them, although
worker threads can.

- **Inspect resolves config paths against the task directory**
  (`resolve_config_paths`): a relative string config, and each relative
  build context of a `ComposeConfig` service, becomes absolute when that
  path exists under the task directory, and an omitted build context
  becomes the task directory. Inline JSON, URIs, absolute paths and strings
  naming no file there are left as given. The task-level config, a
  sample's own config and a config `eval_retry()` rebuilds from the logged
  task file's directory all go through it. The result does not depend on
  the working directory, so setup and sample start resolve a config to the
  same spec, and the sample finds its configuration's provider state by it
  (`test_sample_configs_resolve_against_the_task_directory`). A config file
  created or deleted under the task directory between setup and a sample's
  start resolves differently, so that sample gets a config that was not set
  up.
- **Docker's `task_init_environment` values** (the `SAMPLE_METADATA_*`
  variables a compose file interpolates) reach only Docker's own compose
  commands for that setup, through a private setup context
  (`util/_sandbox/setup.py`); a Docker subclass that overrides the hook
  gets its own values
  (`test_docker_subclass_task_init_environment_reaches_its_build`), and no
  sample sees them.
- **Other providers' `task_init_environment` values are refused** with a
  `PrerequisiteError` naming the migration (put the values in the config
  and pass them to the subprocesses `task_init` starts; "Lifecycle Methods"
  in the provider docs), before the
  provider's `task_init` runs; the error ends that task like any setup
  error (`test_non_docker_task_init_environment_is_refused`). An empty
  mapping, every provider's default, is unaffected.
- **Subprocesses keep their ordinary `cwd`**, the process directory, in
  setup as in samples. Compose resolves a compose file's own paths against
  the file's directory and Inspect hands Docker its config paths resolved,
  so Docker builds the task directory's files from the launch directory
  (`test_relative_configs_select_the_task_directory`,
  `test_docker_env_files_resolve_from_the_compose_file_directory`).

What the surveyed third-party providers (inspect_sandboxes,
inspect-podman, inspect_proxmox_sandbox, inspect_k8s_sandbox,
inspect_ec2_sandbox, inspect_vagrant_sandbox) see:

- E2B, Modal and Daytona receive `ComposeConfig` build contexts made
  absolute against the task directory, so they build the task directory's
  Dockerfile.
- Podman's missing-config lookup and its generated compose file use the
  launch directory, as its `sample_init` does. Its generated file has one
  fixed name per directory ("Compatibility").
- Proxmox resolves a relative `PROXMOX_CONFIG_FILE` against the launch
  directory, as its other readers of that variable do.
- k8s, EC2 and Vagrant take absolute paths or none.

### Provider state per setup

Providers keep their state in their own `ContextVar`s, bound in
`task_init` and read in `sample_init` and `task_cleanup`. `SandboxManager`
captures that state per configuration for the whole run, so the pattern
works when any task's attempt runs the setup, with no provider API and no
provider release:

- each `task_init` sees what earlier successful setups of the run bound
  (k8s's shared manager stays shared);
- each `task_cleanup` runs in the context its own `task_init` produced;
- each sample sees the bindings its configuration's `task_init` made,
  unless it bound a value itself (`SandboxSetupBindings` in
  `src/inspect_ai/_eval/task/sandbox.py`); a failed `task_init` records
  nothing.

Sample bindings are kept per spec and task directory, not per setup:
setups that differ only in their `task_init_environment` values (Docker
and its subclasses, the only providers that return any) share one entry,
which the latest successful setup replaces. So a sample can see another
such setup's bindings, while each `task_cleanup` keeps its own context.
Within a run, Docker keeps its setup state on the run's sandbox
lifecycle scope rather than in a `ContextVar` binding, so only a Docker
subclass that binds its own `ContextVar` in `task_init` is affected.

Tests: `test_setup_bindings_per_configuration`,
`test_setup_bindings_sample_starts_during_other_task_setup`,
`test_setup_bindings_sample_keeps_own_binding` and
`test_setup_bindings_failed_task_init`.

### Interactions with related changes

- **Task handles** ([task-handles.md](task-handles.md)) add a sample
  channel and a creator to a fed task's record, a settings rule for fed
  tasks in `configure_task` (every other task keeps the run-wins
  resolution), and the uncounted start of a fed task that holds a sent
  sample.
- **Added tasks resolve under their creator's model** inside a running
  attempt, including under `eval_set()` and in selection workers
  ([task-source.md](task-source.md#relationship-to-enqueue_task)).
- **Selection-worker pruning** never prunes a `@task` call while a run is
  in progress (`prune_task_call`), so a task an attempt builds is real, and
  `_resolve_enqueued_tasks` refuses a placeholder built before the run
  with `RuntimeError`.
- **The rule that an attempt with no log, or a `cancelled` log, means a run
  cancellation** applies only to attempts `run_one` ran, never to a record
  ended before its first attempt.

## Guarantees and limits

- **One run, one queue, one dispatcher**, for every run shape.
- **Every record ends exactly once**, with its last attempt's log or none,
  and every record has ended when `eval_async()` returns or raises.
- **Once dispatch ends, nothing more starts**: in one synchronous step the
  queue refuses additions and retries and every queued record ends, before
  the attempt group joins.
- **A record is visible to the control channel from the moment it is
  added, and after it ends.**
- **A task's logger owns a recorder entry only while an attempt runs.**
- **No `os.chdir` or `os.environ` write across an `await`**, and every
  provider call runs in the launch directory.
- **Each `task_cleanup` sees what its own `task_init` bound**, and a sample
  sees its configuration's bindings unless it bound its own, with the
  limit for setups that differ only in `task_init_environment` values
  ("Provider state per setup").
- **Each attempt that returns is reported to the run's `TaskSource`
  once**, with the exceptions under "Reporting to the source"; an attempt
  that exits by a run cancellation or a `debug_errors` exception is not.
- **Limits.**
  - An added task's model controller is created on its first `generate`,
    so a connection-limit retune made before then misses it when no
    other task has created that model's controller.
  - A cancel of an ordinary queued task takes effect on the dispatcher's
    next pass; while `next_tasks()` blocks, that is when the call returns,
    and the task stays listed as queued with an abort requested until
    then. A queued fed task ends at once, with no log.
  - `max_tasks` does not count a task cancelled while queued, or a fed
    task.
  - An ordinary task whose abort is delivered before it registers ends with
    the abort's error log, even when an earlier attempt left a different
    error log; a deferred control-channel abort that no attempt registers
    to receive leaves the last attempt's error log instead.
  - An abort that interrupts a header write can leave a partial log file,
    and the returned log's `location` names the file the attempt was
    writing, written or not.
  - A task's setup failure fails the task, not the whole run, but a sample
    a `SampleSource` adds whose own configuration fails to set up fails
    its whole task too ("Not this design").
  - A task pause or resume of a queued task that has never registered
    answers "not found".
  - Tasks whose `task:id` selectors name each other must be added in one
    call.

## Decisions

- **One queue and one dispatcher; an added task starts as soon as a slot is
  free, with no `start=` option to select another policy** (decision:
  Ransom).
- **A task's log starts with its attempt, selection resolves at the call,
  and Inspect resolves config paths against the task directory**
  (decision: Ransom, 2026-11-09).
- **Third-party providers' task-level calls, and the subprocesses they
  start, run in the launch directory**, with no opt-in attribute and no
  warning; **a `ComposeConfig` build context is task-relative for every
  provider**, Modal and Daytona included; and the Podman shared-file fix is
  a provider follow-up, not a gate (decision: Ransom, 2026-11-11).
- **`TaskSource.next_tasks()` is awaited inline** (decision: Ransom,
  2026-11-11).
- **Each task sets up its own sandboxes in its attempt, inside its
  `max_tasks` slot**: rollout tasks, which motivated setup outside the
  slot, take the handle path; **a sample resolves its config again**
  rather than keeping a per-sample key; **a record's registration is
  tracked apart from its phase**; and **the `chdir` stays around the
  synchronous construction of a task's logger** (decision: Ransom,
  2026-11-12).
- **The seed's model controllers are created before it is added, an added
  task's on its model's first `generate`**, so a bad adaptive setting
  fails the task that has it, or its samples, rather than whoever added it
  (decision: Ransom, 2026-11-12 and 2026-11-18).
- **`enqueue_task()` stays synchronous and returns handles**: adding a task
  awaits nothing, and an async version would silently break every
  existing call that does not await it (decision: Ransom, 2026-11-16).
- **An attempt cancelled before it registers is stopped by its own abort,
  not the retry-abandon stamp, and cancels under legacy `eval_set()` rounds
  are not refused** (decision: Ransom, 2026-11-16).
- **A failed task's display row keeps a frame-free snapshot of its error**
  (decision: Ransom, 2026-11-16 and 2026-11-19).
- **An ordinary queued cancel becomes an attempt that aborts before it
  starts, started uncounted on the dispatcher's next pass, and a record
  leaves `queued` in the dispatcher's pick**, so a cancel after the pick
  aborts a counted attempt that keeps its slot until it ends (decision:
  Ransom, 2026-11-17).
- **Every attempt that returns is reported to the `TaskSource`**, a failed
  log initialisation and a later storage failure included, so a source
  waiting on a task's report is never left waiting while the run goes on
  (decision: Ransom, 2026-11-18).
- **An ordinary task added from inside a running task keeps the run-wins
  settings resolution**; only a fed task resolves its own first (decision:
  Ransom, 2026-11-19).
- **Task pause and resume do not reach a queued task that has never
  registered** (decision: Ransom, 2026-11-19).
- **A control-channel cancel of an attempt that is starting is deferred
  until it registers**, so its startup writes are never interrupted
  (decision: Ransom, 2026-11-24).

## Alternatives considered

- **User code on the live `TaskSource` path** (a `TaskSource` at
  `max_tasks > 1`, a rollout `SampleSource` reading a shared queue). Works
  under `eval()` only and leaves the setup and provider-state problems.
- **Admitting a task in the background after it is added** (initialising
  its log and resolving its selection in a job after `enqueue_task()`
  returns). Needs admission phases, an admission failure outcome, a
  queue-owned task group and an end of run that waits for admissions, and
  holds a temporary file and buffer database per queued task.
- **Resolving `task:id` selectors when tasks are admitted together.** Keeps
  batch semantics but needs deferred resolution and its failure path;
  adding mutually-referring tasks in one call covers the use.
- **Running `next_tasks()` beside the loop**, so a task added while it
  blocks starts at once. The call is made only when nothing is queued or
  running, so only a hook or a leftover coroutine can add a task then;
  serving it needs a concurrent call with its own cancel scope, a stored
  result and an ordering rule for its batch.
- **Retries in their task's slot.** Changes start order with no reported
  problem.
- **Sandbox setup in background jobs beside the dispatcher**, once per
  configuration with its own retries, outside task slots. Needs a setup
  task group, per-record setup state, a start rule that waits for setups
  and a failure path that bypasses the task's retries. Fed tasks already
  keep rollout setup off the dispatcher, and setup in the attempt isolates
  and retries a failure through the task's own retries.
- **Setting up the seed before the dispatcher starts.** A slow build holds
  every task, and one failed configuration fails the run.
- **Keeping `os.chdir` for third-party providers, serialised**, or running
  each `task_init` in a thread or child process. The directory is
  process-wide, so other tasks' samples still see it, and a child process
  loses the provider's in-memory state.
- **Running providers' task-level subprocesses in the task directory.**
  Python-level reads would see one directory and subprocesses another; no
  surveyed provider needs it.
- **A `task_init_in_launch_dir` class attribute and a warning for providers
  without it.** A false alarm for every surveyed provider but Proxmox.
- **A public accessor for the task directory during setup.** Once Inspect
  makes config paths absolute, no surveyed provider needs it.
- **Creating an added task's controller eagerly, in the synchronous add.**
  Moves a bad adaptive setting's failure from the added task to whoever
  added it (for a `next_tasks()` return, the whole run) (decision: Ransom,
  2026-11-18).
- **Clearing a failed row's frames instead of snapshotting its error.** On
  Python 3.11 and 3.12, clearing the frame of a suspended coroutine
  finalizes it, and a failed task's error can carry such frames (the
  shared model `Batcher` re-raises one exception object in every waiting
  request), so clearing one consumer's error could finalize a publisher
  still failing the others (decision: Ransom, 2026-11-19).

Alternatives for the handles are in
[task-handles.md](task-handles.md#alternatives-considered).

## Compatibility

- **`enqueue_task()`** stays synchronous and returns `list[TaskHandle]`
  ([task-handles.md](task-handles.md#the-handle-api)), so calls on the
  run's loop that ignore the result work unchanged. A call from a worker
  thread that copied the run's context raises `RuntimeError`; the worker
  hands the call to the run's loop, as "Adding tasks imperatively" in the
  user docs shows. Tasks whose `task:id`
  selectors name each other need one call.
- **Sandbox providers.** `task_init`, `task_init_environment` and
  `task_cleanup` run in the launch directory, after the task's
  `on_task_start` hooks, possibly while other tasks run, and can be called
  again for a configuration after a call that raised. A provider whose
  task-level calls relied on the process directory being the task
  directory needs a change; of the surveyed providers only Proxmox does,
  for a relative `PROXMOX_CONFIG_FILE` found only under the task directory,
  which now falls back to its other configuration. A provider other than
  Docker whose `task_init_environment` returns variables fails setup with
  a `PrerequisiteError` naming the migration.
- **Eval authors.** A `ComposeConfig` on Modal or Daytona with a relative
  or omitted build context builds the task directory's Dockerfile; an
  author who wants the launch directory's writes the context as an
  absolute path. A task-level relative string config is made absolute only
  when the file exists under the task directory, so one present only in
  the launch directory resolves there, and an inline-JSON string config is
  passed unchanged, including through `eval_retry()`. A file-based compose
  config is unaffected.
- **inspect-podman.** While it writes one generated compose file per
  directory, a Podman `task_init` that overlaps running Podman samples (any
  task's setup at `max_tasks > 1`, or a `SampleSource` addition) can
  rewrite or, on failure, delete those samples' `.compose.yaml` when the
  config is an inline `ComposeConfig` or missing. A compose file path is
  unaffected.
- **Failures.** A sandbox setup error and a failed log initialisation end
  only that task with its error log, and it is retried under
  `task_retry_attempts`, rather than failing the run. A bad adaptive
  setting on an added task stays inside that task too: either the task
  fails as above, or its samples error under the task's normal
  sample-error policy, and a task attempt that succeeds despite errored
  samples is not retried.
- **Logs.** An ordinary task cancelled before it starts is returned by
  `eval()` with the abort error log ("Task cancelled by user (abort)") and
  an empty `location`, as code reading `log.location` can already see for a
  task whose log could not be written; a fed task cancelled while queued
  returns no log. No eval log schema, viewer type or config file changes.
- **Control channel.** `GET /tasks` has queued rows; task cancel and drain
  accept queued tasks (`task_queued`, `abort_deferred`); a task that ended
  without starting stays listed as finished; `CONTROL_API_VERSION` records
  the change.
- **Displays.** `TaskError` (in the private `inspect_ai._display`) holds a
  snapshot of the traceback and the live exception only until its row
  closes; the log display still logs the failure with its exception.

## Security

- **`task_init_environment` values** come from sample metadata. They reach
  only Docker's own compose commands for that setup, never `os.environ`,
  so no subprocess of another running sample sees them.
- **Config paths** are made absolute against the task directory, which the
  eval author controls, only when the file exists there; no model output
  reaches them.
- **Control channel.** Cancelling a queued task uses the existing task
  directive's authorization, and queued rows expose what running rows
  expose.

## Not this design

- A connection-limit retune reaching a model controller created after
  it, as an added task's lazily created controller is: remember each
  retune and apply the matching ones when a controller is created
  ([#6645](https://github.com/UKGovernmentBEIS/inspect_ai/issues/6645)).
- A failed sandbox setup for one sample a `SampleSource` (or a handle)
  adds failing only that sample rather than its task
  ([#6646](https://github.com/UKGovernmentBEIS/inspect_ai/issues/6646)).
- Task pause and resume of a queued task that has never registered. It
  needs the pause directives to look in the queued registry first and a
  pause gate that keeps holding the task's samples after it starts; a
  process pause and a cancel cover the use (decision: Ransom,
  2026-11-19).
- Building sandboxes outside the task's slot, and setup retries apart from
  the task's own.
- A task added while `next_tasks()` blocks starting before the call
  returns.
- Recording in the log which task added a task.
- A provider's own lookups in `sample_init` (a missing config's compose-file
  search) seeing the task directory.
- A caller's own cancellation of `eval_async()` (a timeout scope around
  it) being absorbed like a Ctrl-C.
- `TaskSource` under `eval_set()` (see
  [task-source.md](task-source.md#eval_set-support--feasible-but-only-pays-off-for-deterministic-sources)).
- The log a retry ends with when it is abandoned inside a startup `await`
  and that startup write then fails: the returned log replaces the one
  kept before the retry.
- Provider follow-ups: inspect-podman writing a generated compose file per
  project, as Inspect's Docker provider does; inspect_proxmox_sandbox
  documenting `PROXMOX_CONFIG_FILE` as launch-relative or warning when a
  set file is not found; and inspect_sandboxes' per-provider cleanup tests
  and offline Modal and Daytona converter tests.
