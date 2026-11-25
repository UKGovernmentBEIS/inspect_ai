# Task dispatch

## Overview

Every eval run has one task queue and one dispatcher. Seed tasks, tasks
added with `enqueue_task()`, tasks a `TaskSource` returns and task retries
all go through that queue, and a task starts as soon as a `max_tasks` slot
is free, under `eval()`, `eval_set()` and eval-set selection-mode workers
alike. Adding a task checks its configuration and sample selection at
once, so a mistake raises to the caller, and a task's log file is created
only when its attempt starts. Every task in the queue, including one that
has not started, is listed by `inspect ctl task list` and can be cancelled
or drained, and stays listed as finished once it ends.

Each task sets up its own sandboxes (a provider's `task_init`) inside its
attempt, so the dispatcher never waits for an image build: a task without
sandboxes starts at once, a task holds its slot while it builds, and a
setup failure ends only that task, which is retried like any other task
failure. Setup never changes the process's working directory or
environment: Inspect makes relative config paths absolute against the task
directory before a provider sees them, and every provider call runs in the
launch directory. The `ContextVar` state a provider binds in `task_init` is
captured per configuration, so each sample and each `task_cleanup` sees
the state its own configuration's `task_init` produced, whichever task's
attempt ran the setup.

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
"Cancellation" and the `--max-tasks` retune in "Configuration" in
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

Tests need no network or provider; the async ones run on asyncio and (with
`--runtrio`) trio, and the Docker ones are `--runslow`:

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
  thread that copied the run's context: `RuntimeError` naming the
  `anyio.from_thread.run_sync()` call that runs it on the loop
  (`test_enqueue_task_off_the_run_loop`).
- A task id the run already holds, or one repeated in the batch:
  `ValueError` ("Adding tasks").
- Handle misuse: see
  [task-handles.md](task-handles.md#what-is-refused).

### The run queue

`_eval_async_inner` creates one `RunQueue` and binds it in the `ContextVar`
that `enqueue_task()` reads; `eval_run` opens it, adds the seed and runs
the dispatcher until every task has ended. Every task × model is one
`TaskRecord` from the moment it is added until it ends. A record has a
phase:

- `queued`: waiting for its next attempt, a first attempt or a retry alike
  (a retry carries the earlier attempt's log);
- `attempt`: picked by the dispatcher, its attempt scheduled or running;
- `ended`, with its final log, or none.

Apart from its phase, a record tracks how far its attempts have got
(`reached`: added, display row opened, registered with the control
channel), which never moves back, so a retry of a task that once
registered reads as registered.

Only the run's event loop changes the queue, in synchronous steps, so it
needs no lock. A record ends exactly once (`RunQueue.end`), releasing its
configured task and dataset so a finished task's samples can be freed
while the run goes on; it keeps its identity, its log and its `ended`
event. [task-handles.md](task-handles.md#what-the-handles-add-to-the-run-queue)
adds a sample channel and a creator to a fed task's record.

#### Adding tasks

`RunQueue.add` is synchronous. For the whole batch, before anything is
committed, it checks that the run is still open and the call is on the
run's loop, refuses a task id the run already holds or the batch repeats
(a `ResolvedTask` or `PreviousTask` keeps its id, so it can be added once,
and from outside a running task only in a run with one model), and
configures each task (`configure_task` in `eval_run`): it assigns missing
sample ids, applies the eval-level overrides, runs the configuration
checks (id uniqueness, the epoch reducer against the epoch count, the
`SampleSource` prerequisites), resolves the task's `task:id` sample
selectors and constructs its `TaskLogger`. Any error raises to the caller
and nothing of the batch is added. It then commits: the batch is ordered
sequence-major, each record is queued, listed with the control channel and
counted in the display's task total, and the dispatcher is woken.

Who adds, and where errors go:

- `eval_run` adds the seed; errors raise from `eval()`.
- `enqueue_task()` adds what `_resolve_enqueued_tasks` resolves (once under
  the creator's model inside a running attempt, else once per run model;
  [task-source.md](task-source.md#relationship-to-enqueue_task)); errors
  raise to its caller.
- `_enqueue_source_tasks` adds what a `TaskSource` callback returns, and
  the dispatcher adds a `next_tasks()` batch; an add error there ends the
  run. Once dispatch has ended, both drop what the source returned with a
  "Dropping <n> task(s) returned by the task source after the run stopped"
  warning instead, so a callback that runs in a cancelled attempt's
  shielded cleanup cannot replace the run's outcome
  (`test_source_returns_after_the_run_stopped_are_dropped`).
- An `on_run_start` hook's `enqueue_task()` resolves at the call and holds
  the batch; `eval_run` adds it right after the seed (`add_held`), counted
  with the seed, so it starts after the seed and a configuration error in
  it raises from `eval()` before any task starts.

**Selection resolves at the call.** A task's `task:id` selectors resolve
against the run's task names so far plus the batch's own. The run starts
with the whole eval set's names (`eval_set_tasks`), so a selector naming an
eval-set task outside this run still matches no sample of this task rather
than being read as a literal id. Tasks whose selectors name each other must
be added in one call: a task added before the task its selector names reads
that selector as a literal sample id, which raises for a static dataset
with no other match, logs "sample id ... not found" beside other matches,
and filters a dynamic dataset silently. The seed and a `next_tasks()` batch
are each one call.

**The logger is built under a synchronous `chdir`.** The `TaskLogger`
constructor reads the git context and relative paths against the process
directory, so `configure_task` builds it inside `chdir(task_run_dir(...))`.
Nothing in that block awaits, so no other coroutine sees the change. It is
one of two directory changes left in a run; the other is loading a task
from a file ("Setup does not change the process's directory or
environment").

**Model controllers.** `ensure_controllers` creates the seed's adaptive
connection controllers before the seed is added, so `inspect ctl config
--max-connections` can retune them while images build, and a bad adaptive
setting on a seed task (`adaptive_connections=0`) raises from `eval()`. An
added task gets no eager controller: its model's controller is created on
its first `generate`, as for any model the seed does not use. A bad
adaptive setting on an added task therefore fails inside its attempt: with
no `max_samples`, building its sample limiter raises before it registers,
and the task ends with its error log after its retries; with an explicit
`max_samples`, each sample errors on its first `generate`, under the task's
`fail_on_error`. A `--max-connections` retune made before an added task's
first `generate` reaches its controller only when another task has already
created that model's controller ("Not this design").

#### Phases and cancelling

| from | event | to | made by |
| --- | --- | --- | --- |
| (none) | added | `queued` | `RunQueue.add` |
| `queued` | picked, counted or uncounted | `attempt` | `start_attempt` |
| `queued` | a retry carrying the abandon stamp is dropped, or dispatch ends | `ended`, with its stored log | the dispatcher; `end_unstarted` |
| `attempt` | the attempt publishes a retry | `queued`, with the attempt's log | `run_one` |
| `attempt` | the attempt returns or raises with no retry | `ended`, with its log | `run_one` |
| any but `ended` | the attempt group has exited | `ended`, with its stored log | `end_all` |

**Starting an attempt.** `start_attempt` is one synchronous step: it takes
the record from the pending list, counts it against `max_tasks` and its
model when the pick is counted, moves it into `attempt`, creates the
attempt's fresh `TaskCancel` and cancel scope (`_attempt_cancel`) and
stores them on the record, and schedules `run_one`. So a cancel that lands
between the pick and `run_one`'s first statement reaches the attempt's own
cancel handle, and the attempt keeps its counted slot until it ends, as a
running task does. Every attempt gets a fresh pair; a retry gets its own.
`task_run`'s first statement inside the scope is an explicit checkpoint,
so an attempt cancelled before it ran stops there, before its display
row, its task-start hooks, its log file or its buffer database exist.

**`RunQueue.cancel`**, used by the control channel for a task waiting for a
slot and by a handle's `cancel()`, is synchronous:

- An ended record: nothing.
- A record that has registered: the control channel's task cancel
  (`cancel_task`), which aborts a running attempt or abandons a pending
  retry through the retry-abandon stamp.
- A `queued` record that never registered: it is marked
  `abort_requested`, and the dispatcher starts it on its next pass outside
  `max_tasks` and whether or not a pause holds it; `start_attempt` requests
  `abort` on the new attempt before it runs, so the attempt aborts at that
  first checkpoint and ends with an unwritten "Task cancelled by user
  (abort)" error log with an empty `location`. While `next_tasks()`
  blocks, that pass waits for the call to return.
- An `attempt` that never registered: the attempt's own abort, as
  `inspect ctl task cancel` aborts a running task. An abort that lands
  after the attempt returned an error log and while `run_one` prepares a
  retry stops the retry, so the record ends with that log.
- A fed record: see
  [task-handles.md](task-handles.md#closing-and-cancelling).

An abort is never retried, so a task cancelled before it registers ends
with the abort's error log, not an earlier attempt's, and an eval set or
selection worker that requested it reports failure. No case reports
`retry_abandoned`, which stays the answer for a pending retry of a
registered task.

**An attempt's exception exit ends its record.** When `_run_task` raises
(a run cancellation, or an error under `debug_errors`), `run_one` releases
the logger's unfinished entry and ends the record before re-raising, so a
wait on the record (a handle's `result()`) held in another attempt's
shielded cleanup is released and the attempt group can join.

**Reporting to the source.** Each attempt's outcome reaches the run's
`TaskSource` once, through `notify_task_source` in `_run_task` after the
attempt's cancel scope has exited: a written log, the unwritten abort log
of an aborted attempt (a task cancelled while queued included), the
unwritten error log of a failed `logger.init()`, or the unwritten
storage-error log of an attempt whose log storage failed later (a failed
prior-log seed, header flush or final write). A task retried twice is
reported three times. Not reported: a preview (`run_samples=False`); an
attempt abandoned by the retry-abandon stamp, which has no log of its own;
a record ended unstarted when dispatch ends; and a fed task that ends
before it starts. A `task_complete` exception is logged and leaves the
attempt's log as its result (it propagates under `debug_errors`), and a
cancellation that no cancellation of the run caused, raised by
`task_complete` or escaping task cleanup, becomes a `RuntimeError` that
ends the run (`test_task_complete_raising_stray_cancellation_ends_run`).

**Listed after it ends.** A record that ends before any attempt registered
(cancelled while queued, failed in startup with no retry left, ended
unstarted) is registered with the control channel as a finished eval with
zero samples (`register_completed_eval`) in the same step that removes it
from the queued registry. `inspect ctl task list` shows it as finished,
and a repeated cancel or drain answers "task already finished" rather
than 404 (`test_task_failing_before_it_registers_stays_listed_as_finished`).

**The display's task total.** The total counts every record, but the Rich
and Textual displays count completed tasks from the rows attempts open. A
record that ends without ever opening its row lowers the total by one,
once, while the task screen is open (`RunQueue.screen_open`); one whose row
opened leaves it unchanged
(`test_task_total_lowered_once_for_a_task_that_never_opened_its_row`).

**Display rows keep no frames.** The task screen lasts the whole run, and
Rich and Textual keep every row's result for its life. A failed row's
`TaskError` holds a frame-free snapshot of the error (its type, the Rich
rendering and the formatted text), and the live exception only until the
row closes (`_RowErrors` in `task_run` calls `release_exception`), so the
log display can log it with `exc_info` as it closes the row and a failed
task's locals, its dataset among them, are not kept for the rest of the
run; the held row renders its traceback from the snapshot
(`test_ended_tasks_are_released_while_their_rows_are_held`). Under
`debug_errors` the original exception propagates with its traceback.

#### A task's log starts with its attempt

`task_run` awaits `logger.init()` after its explicit checkpoint and its
first retry-abandon check, and before prior-log seeding and `log_start()`,
so a queued task or a pending retry holds no recorder entry, temporary
file or sample buffer database (`test_queued_task_holds_no_log_until_it_starts`).
`TaskLogger.reinit()`, which `run_one` awaits before publishing a retry,
releases the old attempt's entry and resets its location but does not
initialise the retry's log; the retry's own `task_run` does. A logger's
`location` is `None` until `log_init()` returns, `destination_written` is
false while it is, and `unwritten_task_log` gives such a log an empty
`location`.

So a failure in `init()` escapes `task_run` as a failed `log_start()` flush
does, `_run_task` turns it into an error log carrying the storage error,
`run_one` retries that task alone, and the other tasks run on: a seed task
whose log cannot be initialised ends with an error log rather than raising
from `eval()` (`test_log_init_failure_ends_only_that_task`).

### The dispatcher

`dispatch_tasks` runs inside `_run_task_screen`, which absorbs a
cancellation of the run body so the run returns the logs it has. Each
pass:

1. ends the queued retries carrying the retry-abandon stamp, with their
   stored logs;
2. while no run cancellation has been latched and fewer than
   `effective_max_tasks(parallel)` counted attempts run, picks the earliest
   startable record among the least-used models and starts it counted;
   a record is startable when no control-channel pause holds it
   (`task_dispatch_paused`), and records with `abort_requested` or a
   handle channel are never picked here;
3. starts, uncounted, every queued record with `abort_requested`, and
   every fed record that holds a sent sample and that no pause holds
   ([task-handles.md](task-handles.md#tasks-fed-through-a-handle));
4. waits on the queue's wake if anything is queued or running, and
   otherwise, if the run has a `TaskSource` that has not finished, awaits
   `next_tasks()` and adds the batch it returns (`None` or `[]` ends the
   source), or else ends.

Behaviour that follows:

- **Starts as soon as a slot is free**, for every run shape, whenever a
  task was added (`test_added_task_starts_while_its_creator_runs`,
  `test_added_task_starts_while_its_creator_runs_in_eval_set`). At
  `max_tasks == 1` the sequence-major order keeps all of one task
  definition's models together, and the run returns its logs in that
  order (`test_initial_tasks_parallel1_preserves_sequence_grouping`).
- **The dispatcher never awaits a sandbox setup**; each attempt sets up
  its own ("Sandbox setup in the attempt").
- **Wakers.** The queue's wake is registered as a dispatch waker
  (`add_dispatch_waker` in `_control/pause.py`), so a `max_tasks` retune, a
  pause and a resume start held tasks at once.
- **Retries** go to the back of the queue under the record's result index.
  `task_retry_attempts` is one run-wide value: `eval()`'s argument,
  `eval_set()`'s `retry_attempts` under immediate retries and 0 otherwise,
  and 0 in a selection-mode worker.
- **No retry once closed.** `run_one` refuses a retry once dispatch has
  ended or the unregistered attempt has been aborted, both where it decides
  on a retry and again after `reinit()` returns, and clears the
  retry-pending flag it set, so no `EvalState` stays retry-pending for a
  retry that does not exist (`test_unregistered_final_retry_clears_retry_pending`).
- **`next_tasks()` is awaited inline**, only when nothing is queued or
  running. Nothing starts while it blocks: a task that a hook or a
  background coroutine of a finished sample adds during the call is queued,
  listed and cancellable at once, and starts when the call returns, ahead
  of the returned batch (`test_task_added_while_next_tasks_blocks_starts_first`).
  The call runs in a child task inside the task screen, so a Ctrl-C while
  it blocks is absorbed like one during a task and the completed logs are
  kept (`test_cancellation_while_next_tasks_blocks_keeps_completed_logs`,
  `test_sigint_while_next_tasks_blocks_keeps_completed_logs`); on trio,
  `run_main` still raises `KeyboardInterrupt` after the run returns, as for
  a Ctrl-C during a task. An exception it raises ends the run.
- **End of dispatch.** On every exit (the source done, a latched
  cancellation, an exception, a cancellation from outside), the dispatcher's
  `finally` closes the queue and ends every queued record with its stored
  log, synchronously and before the attempt group joins its attempts. That
  settles every handle wait on those records, including waits in shielded
  cleanup that would otherwise hold the join open. A task that an
  attempt's shielded cleanup adds before the `finally` runs is queued and
  then ended unrun; one added after it is refused. Records in `attempt` are
  left to `run_one`. After the group exits, `eval_run`'s `finally` ends any
  record still open (`end_all`), shuts the sandboxes down and cleans up S3
  sessions.
- **`debug_errors`** raises task errors at every `max_tasks`
  (`test_debug_errors_raise_at_every_max_tasks`).

`max_tasks` bounds counted attempts, including one building its sandboxes.
Two kinds of attempt are started uncounted: a task cancelled while queued,
which runs until its abort and its report to the source finish, and a fed
task. So an aborting task and its `task_complete` callback can run beside
`max_tasks` counted attempts.

#### Sandbox setup in the attempt

`configure_task` gives every task with samples to run a
`startup_sandboxes` callable: `SandboxManager.start_for_samples` bound to
the resolved task and to the task's own cache of metadata-free
resolutions, which goes with the task when its record ends. `task_run`
awaits it for the attempt's selected seed samples after `register_eval`
and the task-start hooks and before scheduling the seed, and a
`SampleSource` task's feeder awaits it for the samples it adds. A preview
(`run_samples=False`) sets up nothing (`test_preview_runs_no_setup`).

- **Shared configurations.** `SandboxManager` is run-wide. A configuration
  already set up in the run is skipped, and `task_init` is serialised on a
  lock with the started set re-checked under it, so two tasks that need one
  configuration set it up once and the second waits for the first
  (`test_two_tasks_needing_one_configuration_set_it_up_once`). The task
  display is suspended during the call.
- **Slots.** The attempt holds its slot while it builds, with its display
  row open, and the dispatcher starts other tasks meanwhile, so a task with
  no sandboxes, or whose configurations are set up, starts at once
  (`test_sandbox_free_task_runs_while_another_task_builds`).
- **Failure.** An error from `task_init` or from resolving the
  configuration raises in the attempt, so the task ends with its error log
  and is retried under `task_retry_attempts`, and the run goes on
  (`test_setup_failure_ends_only_its_task_and_is_retried`). A failed
  configuration is not marked started, so a retry, or another task that
  needs it, runs `task_init` again. A call that raised gets no
  `task_cleanup`, then or at shutdown, so the provider releases what it
  allocated before raising; the provider docs state this repeat-call rule.
- **Cancellation.** Cancelling an attempt during a `task_init` it runs
  cancels that call, and nothing is marked started; a task waiting on the
  lock behind another task's setup is cancelled out of the wait.
- **Order.** A task's `on_task_start` hooks run before its sandboxes are set
  up (`test_setup_runs_in_the_attempt_after_registration`).

### Control channel

`RunQueue.add` lists each record in a process-level registry
(`_control/queued_tasks.py`), keyed by task id, with a callback into
`RunQueue.cancel`. The record leaves it when its first attempt registers
(`TaskRecord.on_registered`, in the same synchronous step as
`register_eval`) or when it ends, after being registered as a finished
eval, so a directive always finds the task in one of the two. The registry
takes precedence over `EvalState` history for the same id, since each
`eval_set(retry_immediate=False)` round is its own `eval()` that keeps the
task id while `EvalState`s persist across rounds.

- **`GET /tasks`** lists a queued task with `status: "queued"`, no
  `completed_at`, zero sample totals and `attempts` counting its attempts
  that failed before registering; a task with an earlier round's history
  keeps that row with its status set to `queued`. CLI selectors resolve
  queued tasks like running ones, but a queued task is never the default
  target of a mutation. The documented row shape is in
  [Listing Tasks](../docs/control-channel.qmd#listing-tasks).
- **Task cancel and drain** look in the registry first
  (`_queued_task_directive`). Every answer for an unregistered task carries
  `in_flight: 0` (and `queued: 0` for a drain), and `--dry-run` reports
  without acting:
  - a task waiting for a slot follows `RunQueue.cancel`: its next attempt
    aborts before it starts, answered `changed: true`, `task_queued: true`;
  - a task whose attempt is starting gets `abort_requested`, answered
    `changed: true`, `abort_deferred: true`; its startup writes run
    undisturbed, and `on_registered` applies the abort to the attempt's
    cancel handle as an ordinary task abort, even when the attempt
    registers with no samples. An attempt that fails before registering
    ends as it would have, and a retry it queues aborts before it starts
    (`test_ctl_cancel_of_starting_attempt_aborts_it_when_it_registers`);
  - a repeat before the abort runs answers `changed: false`, "cancel
    already requested (abort)"; an attempt that already returned a log that
    is not an error answers "task already finished"; a starting preview,
    which never registers, answers `changed: false` and keeps its `started`
    log (`test_ctl_cancel_of_starting_preview_is_a_no_op`);
  - `--action score` and `--action error` answer 409: the task has no
    samples for a resolution to apply to.
- **Task pause and resume** look a task up only through its `EvalState`,
  so for a queued task that has never registered they answer "not found",
  though `task list` shows the task as queued. An operator holds queued
  tasks with `inspect ctl process pause` or `model pause`, which the start
  rule checks, or cancels them.
- **`CONTROL_API_VERSION`** records the queued rows and the
  `task_queued` and `abort_deferred` results in its history; older CLIs see
  an unknown status value.

**Under `eval_set()`.** A task cancelled before it starts ends with the
abort's error log, so `eval_set()` reports failure, a selection worker
returns `False`, and under immediate retries no task retry follows. A
requested task with no log at all was still queued when the run was
cancelled, so `run_eval` raises `KeyboardInterrupt` for it. Under
`retry_immediate=False` the next round reruns every requested task that
did not succeed, so a task cancelled while queued comes back, as a running
task cancelled under those rounds does
(`test_eval_set_task_cancelled_while_queued_runs_in_the_next_round`).

### Setup does not change the process's directory or environment

No `os.chdir` or `os.environ` write spans an `await` in sandbox setup,
configuration resolution or cleanup. Every provider call
(`task_init_environment`, `task_init`, `sample_init`, `task_cleanup`) runs
in the launch directory with the process's own environment, and a running
sample's `os.getcwd()` and `os.environ` are unchanged while another task
sets up (`test_setup_runs_in_the_launch_directory`,
`test_running_sample_keeps_directory_and_environment_during_setup`). Two
synchronous directory changes remain: the one around a task's
`TaskLogger` construction ("Adding tasks") and loading a task from a file
(`load_file_tasks` and `create_file_tasks`), whose `chdir_python` blocks
let the file's local imports and relative reads work; neither awaits, so
no other coroutine sees them, although worker threads can.

- **Inspect resolves config paths against the task directory**
  (`resolve_config_paths`): a relative string config, and each relative
  build context of a `ComposeConfig` service, becomes absolute when that
  path exists under the task directory, and an omitted
  `ComposeBuild.context` becomes the task directory itself. A URI, an
  absolute path, inline JSON and any string naming no file there are left
  as given. The task-level config (`resolve_task_sandbox`), a sample's own
  config (`resolve_sandbox`) and a config rebuilt by `eval_retry()` from the
  logged task file's directory (`resolve_task_file_sandbox`) all go through
  it. The result does not depend on the working directory, so setup and
  sample start resolve a sample's config to the same spec, and the sample
  finds its configuration's provider state by that spec and the task
  directory (`test_sample_configs_resolve_against_the_task_directory`).
  A config file created or deleted under the task directory between setup
  and a sample's start resolves differently, so that sample gets a config
  that was not set up.
- **Docker's `task_init_environment` values** (the `SAMPLE_METADATA_*`
  variables a compose file interpolates) reach Docker's own compose
  commands only: `_task_init_startup` holds them in a private `ContextVar`
  (`task_init_env`) around the `task_init` call, and Docker's `task_init`
  passes them to its compose project. A Docker subclass that overrides the
  hook gets its own values
  (`test_docker_subclass_task_init_environment_reaches_its_build`). The
  variable is reset before the setup's context is recorded, so no sample
  sees one setup's values.
- **Other providers' `task_init_environment` values are refused.**
  `resolve_sandbox_for_task_and_sample` raises `PrerequisiteError` naming
  the migration (put the values in the config and pass them to
  subprocesses with `subprocess(env=...)`) when the hook returns a nonempty
  mapping for a provider class that is not `DockerSandboxEnvironment` or a
  subclass, before its `task_init` runs. The error ends that task like any
  setup error (`test_non_docker_task_init_environment_is_refused`). An
  empty mapping, every provider's default, is unaffected.
- **Subprocesses keep their ordinary `cwd`**, the process directory, in
  setup as in samples. Compose resolves a compose file's own paths (build
  contexts, `env_file`, `.env`) against the file's directory, and Inspect
  hands Docker its config paths resolved, so Docker builds the task
  directory's files from the launch directory
  (`test_relative_configs_select_the_task_directory`,
  `test_docker_env_files_resolve_from_the_compose_file_directory`).

What the surveyed third-party providers (inspect_sandboxes,
inspect-podman, inspect_proxmox_sandbox, inspect_k8s_sandbox,
inspect_ec2_sandbox, inspect_vagrant_sandbox) see:

- E2B, Modal and Daytona receive `ComposeConfig` build contexts that
  Inspect has made absolute against the task directory, so their
  template warm-up and their sample-time converters build the task
  directory's Dockerfile.
- Podman's missing-config lookup and its generated compose file use the
  launch directory, as its `sample_init` does. Its generated file has one
  fixed name per directory, so a Podman `task_init` that overlaps running
  Podman samples with an inline `ComposeConfig` or a missing config
  rewrites their file and, on failure, deletes it ("Compatibility").
- Proxmox resolves a relative `PROXMOX_CONFIG_FILE` against the launch
  directory, as its other readers of that variable do.
- k8s, EC2 and Vagrant take absolute paths or none.

### Provider state per setup

Providers keep their state in their own `ContextVar`s, which `task_init`
binds and `sample_init` and `task_cleanup` read. `SandboxManager` captures
that state per configuration, for every task of the run:

- `SandboxManager.open()`, which `eval_run` calls before the seed is added,
  enters Docker's lifecycle scope and takes `root`, a copy of the run's
  context holding no provider state. `shutdown()`, in `eval_run`'s
  `finally`, runs every registered `task_cleanup` and exits the scope.
- Each `task_init` runs in a child task started from the setup chain's
  context (`_run_in_context`), which starts as `root` and which each
  successful call's context replaces, so a later setup sees what earlier
  ones bound (k8s's shared manager stays shared). When the call returns,
  its context is kept for the configuration's `task_cleanup`, and its
  bindings (every `ContextVar` whose value differs from `root`'s) are
  recorded in `SandboxSetupBindings`, keyed by spec and task directory. A
  failed call records nothing.
- Every task's `apply_sandbox_bindings` binds its configuration's recorded
  values before `sample_init`, only where the sample's value is still
  `root`'s, so a value the sample bound itself is kept
  (`test_setup_bindings_sample_keeps_own_binding`).

So a configuration's state is recorded once, by whichever attempt set it
up, and reaches the samples of every task that uses it and its own
`task_cleanup`, with no provider API and no provider release
(`test_setup_bindings_per_configuration`,
`test_setup_bindings_sample_starts_during_other_task_setup`).

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
  sees its configuration's bindings unless it bound its own.
- **Each attempt is reported to the run's `TaskSource` once**, with the
  exceptions under "Reporting to the source".
- **Limits.**
  - An added task's model controller is created on its first `generate`,
    so a `--max-connections` retune made before then misses it when no
    other task has created that model's controller.
  - A cancel of a queued task takes effect on the dispatcher's next pass;
    while `next_tasks()` blocks, that is when the call returns, and the
    task stays listed as queued with an abort requested until then.
  - `max_tasks` does not count a task cancelled while queued, or a fed
    task.
  - A task cancelled before it registers ends with the abort's error log,
    even when an earlier attempt left a different error log.
  - An abort that interrupts a header write can leave a partial log file,
    and the returned log's `location` names the file the attempt was
    writing, written or not.
  - A task's setup failure fails the task, not the whole run, but a sample
    a `SampleSource` adds whose own configuration fails to set up fails
    its whole task too ("Not this design").
  - `inspect ctl task pause` and `resume` of a queued task answer "not
    found".
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
  warning (decision: Ransom, 2026-11-11, replacing the 2026-11-03 decision
  to warn); **a `ComposeConfig` build context is task-relative for every
  provider**, Modal and Daytona included; and the Podman shared-file fix is
  a provider follow-up, not a gate (decision: Ransom, 2026-11-11).
- **`TaskSource.next_tasks()` is awaited inline** (decision: Ransom,
  2026-11-11).
- **Each task sets up its own sandboxes in its attempt, inside its
  `max_tasks` slot** (decision: Ransom, 2026-11-12, replacing the
  2026-11-03 and 2026-11-05 decisions to set up beside the dispatcher and
  outside the slot, whose evidence was rollout tasks, which now take the
  handle path); **a sample resolves its config again** rather than keeping
  a per-sample key; **a record has three phases with registration tracked
  apart**; and **the `chdir` stays around the synchronous construction of a
  task's logger** (decision: Ransom, 2026-11-12).
- **The seed's model controllers are created before it is added, an added
  task's on its model's first `generate`** (decision: Ransom, 2026-11-12,
  kept 2026-11-18, with remembered retunes as a follow-up rather than
  eager controllers for added tasks).
- **`enqueue_task()` stays synchronous and returns handles** (decision:
  Ransom, 2026-11-16, reversing the 2026-11-09 decision to make it async;
  reasons restated 2026-11-18: adding a task awaits nothing, and an async
  version would silently break every existing call that does not await
  it).
- **An attempt cancelled before it registers is stopped by its own abort,
  not the retry-abandon stamp, and cancels under legacy `eval_set()` rounds
  are not refused** (decision: Ransom, 2026-11-16).
- **A failed task's display row keeps a frame-free snapshot of its error**
  (decision: Ransom, 2026-11-16; the 2026-11-19 alternative of clearing
  the frames instead was withdrawn the same day, see "Alternatives
  considered").
- **A queued cancel becomes an attempt that aborts before it starts,
  started uncounted on the dispatcher's next pass, and a record leaves
  `queued` in the dispatcher's pick**, so a cancel after the pick aborts a
  counted attempt that keeps its slot until it ends (decision: Ransom,
  2026-11-17).
- **Every attempt is reported to the `TaskSource`**, a failed `init()` and
  a later storage failure included, with no flag to tell them apart
  (decision: Ransom, 2026-11-16 and 2026-11-18, the latter reversing the
  2026-11-16 exception for storage failures).
- **An ordinary task added from inside a running task keeps the run-wins
  settings resolution**; only a fed task resolves its own first (decision:
  Ransom, 2026-11-19).
- **`inspect ctl task pause` and `resume` of a queued task stay "not
  found"** (decision: Ransom, 2026-11-19).
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
  calls it through `anyio.from_thread.run_sync()`. Tasks whose `task:id`
  selectors name each other need one call.
- **Sandbox providers.** `task_init`, `task_init_environment` and
  `task_cleanup` run in the launch directory, after the task's
  `on_task_start` hooks, possibly while other tasks run, and can be called
  again for a configuration after a call that raised. A provider whose
  task-level calls relied on the process directory being the task
  directory needs a change; of the surveyed providers only Proxmox does,
  for a relative `PROXMOX_CONFIG_FILE` found only under the task directory,
  which now falls back to `PROXMOX_HOST` or no pools. A provider other than
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
- **Failures.** A sandbox setup error, a failed log initialisation and a
  bad adaptive setting on an added task end only that task with its error
  log and are retried under `task_retry_attempts`, rather than failing the
  run.
- **Logs.** A task cancelled before it starts is returned by `eval()` with
  the abort error log ("Task cancelled by user (abort)") and an empty
  `location`, as code reading `log.location` can already see for a task
  whose log could not be written. No eval log schema, viewer type or config
  file changes.
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

- A `--max-connections` retune reaching a model controller created after
  it, as an added task's lazily created controller is: remember each
  retune and apply the matching ones when a controller is created
  ([#6645](https://github.com/UKGovernmentBEIS/inspect_ai/issues/6645)).
- A failed sandbox setup for one sample a `SampleSource` (or a handle)
  adds failing only that sample rather than its task
  ([#6646](https://github.com/UKGovernmentBEIS/inspect_ai/issues/6646)).
- Pausing and resuming a queued task through `inspect ctl task pause` and
  `resume`. It needs the pause verbs to look in the queued registry first
  and a pause gate that keeps holding the task's samples after it starts;
  `process pause` and a cancel cover the use (decision: Ransom,
  2026-11-19).
- Building sandboxes outside the task's slot, and setup retries apart from
  the task's own.
- A task added while `next_tasks()` blocks starting before the call
  returns.
- Recording in the log which task added a task.
- A provider's own lookups in `sample_init` (a missing config's compose-file
  search) seeing the task directory.
- A caller's own cancellation of `eval_async()` (for example
  `anyio.fail_after`) being absorbed like a Ctrl-C.
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
