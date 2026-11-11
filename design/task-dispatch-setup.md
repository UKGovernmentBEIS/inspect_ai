# Sandbox setup beside the dispatcher

## Overview

Sandbox setup (a provider's `task_init`) moves out of the dispatcher of
[task-dispatch.md](task-dispatch.md) into background jobs, one per sandbox
configuration per run. Tasks that need no setup, or whose setup is done,
start while other setups run, so a slow image build delays only the tasks
that need it. A setup that fails retries itself, up to the run's task retry
limit, with a backoff between tries; if it still fails, it ends only the
tasks that need it, each with an error log, and a task that failed in setup
is not retried as a task.

This design changes when setups run and what their failure does. The
provider contract (the launch directory, resolved config paths, per-setup
`ContextVar` state) is task-dispatch.md's and is unchanged here.
[task-handles.md](task-handles.md) does not depend on this design.

## Behaviour changes

Scheduling only (every sample runs with the same inputs, sandbox and model):

- A task that needs no setup, or whose setup is done, starts while other
  setups run; at `max_tasks == 1` it can start ahead of an earlier task that
  waits for an image.
- The seed's setups run while tasks start, not all before the first task.

Failure reporting:

- A failed setup is retried by the setup itself, up to the run's
  `task_retry_attempts`, with a backoff between tries; if it still
  fails, it ends only the tasks that need it, each with an error log and with
  `on_task_start`/`on_task_end`, and those tasks are not retried as tasks;
  today the run fails. This includes the seed's setups.
- A configuration whose `task_init` failed or was interrupted is cleaned up
  at the end of the run; today `task_cleanup` runs only after a successful
  `task_init`.
- `GET /tasks` shows a queued task's setup state.

Provider contract:

- A provider's `task_init` can be called again after it raised, in the same
  run, with no `task_cleanup` between the calls, and can run while other
  tasks' samples run.

## Why

With [task-dispatch.md](task-dispatch.md) the dispatcher sets up each
record's sandboxes itself, before the record is startable:

- While a setup awaits, the dispatcher starts nothing, so a slow image
  build for one added task stops every task from starting, sandbox-free ones
  included. A task fed by its creator
  ([task-handles.md](task-handles.md#tasks-fed-by-their-creator)) whose
  first sample arrives during such a build waits for it.
- A setup error fails the whole run, although only the tasks that use that
  configuration cannot run.
- A transient setup failure (a registry timeout during a pull) is not
  retried, although task errors are.

## Goals and non-goals

Goals:

- Setup beside the dispatcher, once per configuration per run.
- A failed setup retries itself and, when it fails for good, ends only the
  tasks that need it.
- One cleanup rule: every configuration whose `task_init` was called is
  cleaned up once, at the end of the run.

Non-goals:

- Stopping a setup that no task needs any more (see "Alternatives
  considered").
- Streaming setup output to the task display (see "Not this design").
- Carrying a setup failure across `eval_set()` rounds.

## Current behaviour

After [task-dispatch.md](task-dispatch.md):

- `dispatch_tasks` (`src/inspect_ai/_eval/run.py`) prepares each queued
  record in queue order before it is startable: `ensure_model_controller`,
  then `SandboxManager.start` for its selected seed samples. An error there
  raises from the dispatcher and fails the run.
- `SandboxManager._start_sandboxenvs` serializes setups on `_init_lock`,
  awaits `ensure_sandbox_limiter`, suspends the task display
  (`display().suspend_task_app()`) and awaits `task_init` in a task started
  from the setup chain's context. On success it keeps the configuration's
  `context` and `bindings` and registers its `task_cleanup`.
- A `SampleSource` task's mid-run setup (`startup_sandboxes`,
  `SandboxManager.start_for_samples`) fails only that task.
- `SandboxManager.shutdown`, from `eval_run`'s `finally`, runs each
  registered `task_cleanup` in its configuration's captured context.
- `run_one` retries a failed attempt up to `task_retry_attempts`, with no
  wait between attempts. `eval_set()`'s `retry_wait` applies only between
  legacy rounds (`retry_immediate=False`).

## Design

### Invariant

**A setup retries itself, and its final failure ends only the tasks that
need it**, through an ordinary errored attempt that is never retried as a
task. task-dispatch.md's invariants hold unchanged. The isolation is
Inspect's: a provider that shares one file across its setups and samples
can still let a failing setup damage running samples. Podman's generated
`.compose.yaml` is the surveyed case
([task-dispatch.md](task-dispatch.md), "Setup does not change the process's
directory or environment").

### Setup jobs

`src/inspect_ai/_eval/sandbox_setups.py` replaces `SandboxManager`:

```python
SetupKey = TaskSandboxEnvironment     # spec, run_dir, env (unchanged NamedTuple)

class SetupJob:
    key: SetupKey
    tries: int                         # task_init tries made, at most task_retry_attempts + 1
    state: Literal["waiting", "running", "succeeded", "failed"]
    error: BaseException | None
    bindings: Mapping[ContextVar[Any], Any]   # set on success; task-dispatch.md "Provider state per setup"
    context: Context                   # the last try's context as it exited, for task_cleanup

class TaskSetups:                      # one per record
    def settled(self) -> bool
    def failure(self) -> BaseException | None
    def key_for(self, sample_index: int) -> SetupKey | None
    async def ensure(self, samples: list[tuple[int, Sample]]) -> None   # SampleSource additions

class SandboxSetups:                   # one per run
    root: Context                      # eval_run's context when the setups are created
    def request(self, records: list[TaskRecord]) -> list[TaskSetups]   # one commit's records
    def open(self) -> AsyncContextManager[None]
    async def shutdown(self) -> None
```

`TaskRecord` gains `setups: TaskSetups | None` in place of `prepared`
(`None` under `run_samples=False`), and `RunQueue.add` calls
`setups.request(records)` with the records of each commit (the seed is one
commit). The dispatcher loses its
`prepare()` step, and `setups.open()` wraps the attempt group inside the
task screen:

```
async with _run_task_screen(...):
    async with setups.open():                  # setup jobs run here; the seed's start now
        async with attempt task group:
            ...                                # task-dispatch.md's loop, without prepare()
```

`RunQueue.wake` is also rung by every setup result.

- **Start rule.** An entry is startable when its record's setups have
  settled (succeeded or failed) or it needs none, and no control-channel
  pause holds it. An entry whose setup is still running does not block the
  queue: the dispatcher takes the earliest startable entry among the
  least-used models, so at `max_tasks == 1` sequence grouping holds among
  startable tasks. The idle check is unchanged (no entry pending, no attempt
  running): an entry waiting on a setup is pending.
- **Where it runs.** `open()` holds the setup jobs' task group inside the
  task screen, beside the attempt group; requests made before it opens (the
  seed's) start when it opens. Inside the screen, a cancellation of the run
  is absorbed with the rest of the run body, and the display has loaded
  before any setup can suspend it.
- **A record's job.** When `run_samples` is true, `request` starts one
  background job per record, sandbox or not. Every job of a commit first
  waits until `ensure_model_controller` has returned for each record of that
  commit (one controller step per commit, in the setup group and under no
  record's cancel scope, awaiting them in queue order, as `prepare()`'s
  first pass did), so no setup of the seed starts before every
  seed task's controller exists, and `inspect ctl config` can retune
  `max_connections` for every queued or starting task during a long build
  and before its first `generate`. A record with no sandbox is then
  settled. Otherwise the job resolves the `SetupKey` of each selected
  sample (which can await a provider's `task_init_environment`, Docker's
  running a `docker compose config` subprocess), recording it by the
  sample's index in the attempt's sample list, and requests the `task_init`
  jobs. Under `run_samples=False` no job starts and no controller is
  created, as today. The record's job runs in its own cancel scope:
  `RunQueue.end` cancels it when the record ends before the job has
  finished, and `setups.open()` cancels every such scope when it exits. A
  cancelled job publishes nothing into the record and writes no resolution
  cache entry; `RunQueue.end` then calls `SandboxManager.forget(record)`,
  as in task-dispatch.md, and drops `record.setups`. Setup jobs
  are keyed by `SetupKey`, which holds no `Task`, so they and their cleanup
  registrations stay until the run's shutdown. The `task_init` jobs it
  requested are not under this scope and carry on.
- **Once per configuration per run.** `task_init` jobs are keyed by
  `SetupKey` across all records and kept until the run ends. They run one at
  a time (a provider never gets two `task_init` calls at once, as
  `_init_lock` ensures today), in request order, except that a job needed now
  (a `SampleSource` task's `ensure()`) goes first. Before its first try a
  job awaits `ensure_sandbox_limiter`, as today, so a `--max-sandboxes`
  retune issued during a long build applies.
- **The job retries itself** (decision: Ransom, 2026-11-10). A `task_init`
  that raises is tried again, up to `task_retry_attempts` more times (the
  run-wide value of task-dispatch.md's dispatcher; 3 means up to four tries,
  and 0, `eval()`'s default, means none). Between tries the job waits 5
  seconds, doubling each time and capped at 60 seconds, for every entry
  point (decision: Ransom, 2026-11-10). This is not `eval_set()`'s backoff
  between legacy rounds: `retry_wait` stays a legacy-round setting and does
  not affect setup. The job releases the one-at-a-time slot while it waits,
  so other setups run meanwhile, then tries again from the setup chain's
  current context. No provider cleanup runs between tries: a provider's
  `task_cleanup` can act on everything it tracks (Docker's shuts down every
  project in the lifecycle registry, k8s's uninstalls every release of a
  shared manager, Vagrant's and EC2's destroy every VM or instance in
  module or class state), so running it mid-run could tear down another
  configuration's running sandboxes. A provider's `task_init` must therefore
  tolerate being called again after a failed call in the same run; one that
  cannot simply fails every try, as it fails today's single try. Records
  needing the key keep waiting through the tries, and new requests for it
  join the same job. A failed key resolution (`task_init_environment`, a
  missing config file) is not retried: it fails the same way every time.
- **A job runs to its end whoever still needs it.** A job that has been
  requested makes its tries until it succeeds or fails for good, even when
  every record that requested it has since been cancelled or has ended. A
  later record needing the key joins the job or finds its result. The run
  does not wait for such a job: dispatch ends when no record is left, and on
  a normal exit `setups.open()` cancels every job waiting for its first try
  or in backoff and waits only for a `task_init` call that is running to
  return (interrupting it can leave resources half-created). On a run-level
  cancellation it cancels every job, a running `task_init` included, as
  today.
- **Failure.** When the last try fails, the job is failed for the rest of the
  run. Every record needing it becomes startable, and its attempt ends at once
  through the normal path: `task_run` receives the failure in
  `TaskRunOptions.setup_error`, registers, fires `on_task_start`, writes an
  error log whose error is the setup exception, and fires `on_task_end`. A
  record added later that needs the key ends the same way without a new try.
  An attempt that failed in setup, here or in `ensure()`, is not retried as a
  task within the run: the shared setup job has already used its retries,
  and its failure is final for this run. The attempt says so before it
  writes its log, so the control channel never advertises a retry that will
  not come:
  - When the dispatcher starts an attempt whose `setup_error` is already set,
    `run_one` passes `can_retry=False` to `_run_task`, so the registered
    `EvalState.will_retry` is false and `finish_task_log` writes no
    retry-pending pre-mark.
  - When a setup fails during the attempt (in `ensure()` for a sample a
    `SampleSource` adds), `task_run`, in the synchronous step in which
    `ensure()` raises and before the error reaches the attempt's error
    handling, clears `task_cancel.can_retry` and sets the registered state's
    `will_retry` to false (a new `disable_eval_retry(eval_id)` in
    `_control/eval_state.py`, which does for one attempt what
    `abandon_task_retry` does for `will_retry`). So the pre-mark is skipped,
    cancelled sibling samples read terminal rather than pending, and a cancel
    or drain during the error-log write does not report abandoning a retry.

  A `KeyboardInterrupt` or `SystemExit` from a setup ends the run.
- **Task retries** reuse the record's own setups, which have all succeeded
  by the time an attempt runs. An attempt that fails for another reason
  while a setup its `ensure()` requested is still running or in backoff is
  retried as usual (`failure()` is not set); the job carries on, and the
  retry's `ensure()` joins it or finds its result.
- **`SampleSource` additions.** `startup_sandboxes` becomes
  `options.setups.ensure(samples)`: resolve the added samples' keys, request
  missing jobs as needed now, and await them. A final failure of a job
  `ensure()` awaits sets `failure()` and fails that task, as today.
- **Samples use the key resolved for them**, as in task-dispatch.md:
  `run_sample` passes `options.setups.key_for(sample_index)` to
  `sandboxenv_context`.
- **Display.** Every setup suspends the task display while `task_init` runs,
  as today (`display().suspend_task_app()`), since providers write to the
  terminal. Other tasks keep running meanwhile.
- **Cleanup.** A job registers its configuration's `task_cleanup` when its
  first try starts, before `task_init` is called (decision: Ransom,
  2026-11-10). `shutdown()`, from `eval_run`'s `finally` after the screen
  has closed and no sample runs, runs each registered cleanup once, whether
  the job's tries succeeded, failed or were interrupted by a run-level
  cancellation: in a task started from the job's `context`, never from
  `root`, shielded, with errors logged as today. A job that never started a
  try registers nothing. That pass clears what failed tries left: the
  aggregate cleanups above reach everything their provider tracks, and the
  surveyed providers that rebind per-call state (E2B, Modal, Daytona) create
  no sandboxes in `task_init`. At run end this is safe for the surveyed
  providers (an aggregate cleanup run again finds nothing left, and one that
  finds no state of its own raises, which is logged).

### Provider state with retried setups

task-dispatch.md captures a configuration's `context` when its `task_init`
succeeds. With cleanup registered at the first try, a job needs a context
for a `task_init` that never succeeded too. So each try captures
`copy_context()` inside the try's task, in a synchronous `finally` around the
`task_init` call: it is taken on every exit (return, raise or cancellation)
before the task exits, and holds whatever the provider bound before it
raised or was cancelled (E2B and Podman bind their lists before their
awaited build work). The job keeps the last try's capture as `context`, for
its cleanup. As in task-dispatch.md, only a successful try's capture
replaces the setup chain's context and yields `bindings`, so a failed try's
bindings reach no later try, job or sample.

### Control channel

A queued row in `GET /tasks` gains `setup: "waiting" | "running" | "failed"
| null`, from the record's `TaskSetups`. `CONTROL_API_VERSION` increases by
one.

### Setup failures across `eval_set()` rounds

A setup failure is final only for the run it happened in. With immediate
retries (the default) the eval set is one run, whose setups retry
themselves up to `retry_attempts`, so a task whose setup failed is not run
again. Legacy rounds (`retry_immediate=False`) run with `task_retry_attempts`
of 0, so each round's setups get one try, and each round is a new `eval()`
with its own `SandboxSetups`: a task whose setup failed in one round is
retried in the next like any failed task, as today, and that is the only
setup retry legacy mode gets. Nothing about setup failures is carried across
rounds (decision: Ransom, 2026-11-10).

## Alternatives considered

- **Running each task's setup inside its own slot.** A slot would hold an
  image build and sandbox-free tasks would wait behind it (decision: Ransom,
  2026-11-05).
- **Retrying a setup through its tasks' retries** (the attempt errors, the
  task retry requests the setup again). Every try would write an error log
  for every task waiting on the configuration, and tasks sharing a
  configuration would each spend their own retries on one shared failure.
- **Stopping a job that no record needs any more**, and forgetting its key.
  It saves the remaining tries of a setup whose tasks were all cancelled,
  but needs a count of waiters per job, a decision taken when a running
  `task_init` call returns (a new waiter may have joined meanwhile), a rule
  for the retry budget of a forgotten key set up again, a second cleanup
  registration for it, `ensure()` keys owned by one attempt, and a running
  `task_init` counted in the dispatcher's idle check. Without it the run
  still ends as soon as no record is left; the only cost is setup work for
  cancelled tasks while other tasks keep the run going.
- **Cleaning up between tries.** A provider's `task_cleanup` can reach other
  configurations' running sandboxes ("The job retries itself").
- **Registering cleanup only after a successful `task_init`**, as today.
  Failed tries can leave resources, and with retries there are more of them.
- **The prototype's table recomputed each pass, with a two-stage pipeline.**
  Requesting setups at add and keeping a startable set gives the same starts
  with one less mechanism.
- **Streaming build output to the task display** instead of suspending it.
  Useful, but it changes where provider output goes and needs a provider
  opt-in; it is its own change.

## Compatibility and migration

No migration required for eval authors. Third-party sandbox providers need no
change if their `task_init` can be called again after it raised and their
`task_cleanup` tolerates running for a configuration whose `task_init`
failed; a provider whose `task_cleanup` raises in that case gets the error
logged, as cleanup errors are today. `SandboxEnvironment`'s docstring and
`docs/extensions-sandboxes.qmd` add both points and that `task_init` may run
while other tasks run, one call at a time.

Control channel: queued rows in `GET /tasks` gain a `setup` field, and
`CONTROL_API_VERSION` increases. No public Python API, eval log schema,
viewer type or config file changes.

## Security

Nothing new is exposed: setup jobs run the provider code that runs today,
with the same configuration, and the `setup` field reports only a state.

## Testing

Unit and integration tests on asyncio and trio (`--runtrio` for every async
test touched), with a stub sandbox provider registered with `@sandboxenv`
whose `task_init` blocks on an `anyio.Event` or fails a set number of times
and counts its calls and its `task_cleanup` calls. Every test that waits on
a run is bounded with `fail_after`.

- Scheduling: a sandbox-free task starts while a setup blocks; at
  `max_tasks == 1` a task whose setup is done starts ahead of an earlier
  task whose setup blocks; `run_samples=False` starts no setup.
- Retries:
  - a transient failure (fails once, `task_retry_attempts=2`) is absorbed by
    the setup's own retries for a seed task and an added task, each of which
    then runs normally; no `task_cleanup` runs between the tries (a patched
    wait records the backoff), and the configuration's cleanup runs once at
    shutdown;
  - a permanent failure (`task_retry_attempts=2`) makes three tries with no
    cleanup between them, then ends every task waiting on the key with its
    error log and `on_task_start`/`on_task_end`, none retried as a task; a
    task added later that needs the key ends the same way with no fourth try;
    the configuration's cleanup still runs once at shutdown, and an error it
    raises is logged;
  - with `task_retry_attempts=0` the first failure is final;
  - the backoff is 5, 10, 20, 40, 60, 60 seconds (patched wait) under
    `eval()` and `eval_set()`, whatever `retry_wait` is;
  - requests for the key arriving during the tries join the same job, and
    other setups run while it waits;
  - a failed `task_init_environment` is not retried;
  - with configuration A's samples running while B fails on every try,
    nothing of A's is cleaned up before shutdown.
- No task retry after a setup failure: with retry budget left, for a task
  whose setup failed before it started and for a `SampleSource` task whose
  `ensure()` fails finally mid-attempt, each with a sibling sample cancelled
  and the error-log write held on an event: the registered `will_retry` is
  false and no retry is pre-marked, the cancelled sibling reads terminal, a
  cancel and a drain during the held write report no retry abandoned, and no
  retry follows.
- Cancelled records:
  - with `task_init_environment()` held on an event before it yields a key,
    cancelling the queued record, and separately closing the run, end the
    record's job promptly; the run completes, nothing is published into the
    ended record, and no `task_init` starts for that key;
  - cancelling the only record waiting on a job during its backoff (patched
    wait held on an event) ends the run promptly with no further try;
    cancelling it while its `task_init` runs ends the run once that call
    returns; with another task keeping the run open, the job makes its
    remaining tries and a record added later that needs the key uses its
    result;
  - an unrelated sample failure: a `SampleSource` task under strict
    `fail_on_error` loses a sample while an added sample's setup is in
    backoff; the task is retried as an ordinary error and the retry's
    `ensure()` joins the same job.
- Cleanup registration: a run cancelled during a configuration's first
  `task_init` runs its `task_cleanup` once at shutdown; one cancelled during
  the second try, after a failed first, also runs it once, and with a stub
  that binds a list before it awaits (or raises), the cleanup sees that
  binding; a configuration whose tries all failed runs it once; a job
  cancelled before its first try runs none.
- Startup settings: a Docker job started from the captured `root` under
  `--sandbox-prebuilt` verifies the prebuilt images instead of building;
  with `task_init` held, an `inspect ctl config --max-sandboxes` retune
  applies to the provider's limiter rather than being dropped.
- Eager controllers (`tests/model/test_adaptive_connections.py`): with an
  adaptive-connections model and `run_samples` true, a queued sandbox-free
  record, and a sandbox-free solver held on an event before its first
  `generate`, each have their controller, and an early `inspect ctl config
  --max-connections` retune applies to it rather than being dropped; with
  two seed tasks on models with separate connection pools (two `openai/`
  names with a dummy key; two `mockllm` names share one pool), a retune made
  while the first task's `task_init` is held sets both controllers' ceiling;
  under `run_samples=False` no controller is created.
- `tests/test_sample_source.py`: a mid-run configuration through
  `setups.ensure()`; its final failure fails only that task; with
  `task_retry_attempts=2` a setup that fails once is absorbed and the added
  sample runs. The same for a sample sent to a task fed by its creator, when
  [task-handles.md](task-handles.md) has landed: a failure on every try ends
  the fed task with its error log, and a fresh fed task needing the same
  configuration ends the same way with no further try.
- `tests/test_eval_set.py`: under `eval_set(retry_immediate=False,
  retry_attempts=2)` (legacy mode counts the first round in
  `retry_attempts`, so 2 allows one more), a task whose setup fails in the
  first round (stub provider whose `task_init` fails only on its first call)
  is re-run in the second round, with a fresh setup that succeeds, and the
  eval set succeeds; with immediate retries, a setup that fails on every try
  is not run again and the eval set fails.
- `tests/_control/test_ctl.py`: the `setup` field of a queued row while its
  setup waits, runs and has failed.

The `--runslow` Docker tests run in the PR CI `slow-tests` job, since this
PR touches `src/inspect_ai/util/_sandbox/**`; the rest run in the normal
test job.

## Implementation plan

One PR, after step 3 of
[task-dispatch.md](task-dispatch.md#implementation-plan); independent of
[task-handles.md](task-handles.md).

- `_eval/sandbox_setups.py` (new; replaces `SandboxManager`; setup retries,
  the per-try context capture, cleanup registered at a job's first try),
  `_eval/task/enqueue.py` (`TaskRecord.setups`, requested in
  `RunQueue.add`), `_eval/run.py` (the start rule, `setup_error`,
  `setups.open()` inside the screen, `prepare()` removed; no task retry
  after a setup failure, `can_retry=False` for an attempt started with
  `setup_error`), `_control/eval_state.py` (`disable_eval_retry()`),
  `_eval/task/run.py` (retry disabled when `ensure()` fails; the
  setup-failure attempt path; `setups.ensure()`),
  `_control/queued_tasks.py` (the `setup` field),
  `util/_sandbox/environment.py` and `docs/extensions-sandboxes.qmd` (the
  provider contract). Tests: those above.

## Open questions

None. Decided: Ransom (2026-11-03) that seed setups run beside the dispatcher like
every other setup; (2026-11-05) that a setup does not run inside its task's
slot; and (2026-11-10) that a failed setup retries itself up to the run's
`task_retry_attempts`, with its own backoff (5 seconds doubling to 60) and
no cleanup between tries, that its cleanup is registered at its first try
and runs once at run end, and that a task whose attempt failed in setup is
not retried as a task within that run, while `eval_set()`'s legacy rounds,
each a new run with fresh setups, retry it as they do today; and
(2026-11-11) that a requested job makes its tries whoever still needs it,
and the run ends without waiting for it (replacing the 2026-11-10 decision
that a job no record needs stops after its current call and is forgotten).

## Not this design

- Streaming setup output to the task display's console (prefixed by
  configuration, with a provider opt-in) instead of suspending the display.
- A setup-progress row in the task display.
- Stopping a setup whose tasks were all cancelled.
