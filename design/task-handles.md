# Task handles

## Overview

`enqueue_task()` returns a `TaskHandle` for each task it adds to a running
eval, and every handle can cancel its task. A task whose dataset is
`samples_from_handle()` is *fed through its handle*: it has no samples of
its own, and the task that added it sends each sample with
`TaskHandle.enqueue_sample()`, which returns that sample's logged
`EvalSample`. `TaskHandle.result()` waits for a fed task's final log.

A fed task uses its own model if it sets one, otherwise the model of the
task that added it. It runs one epoch, starts when its first sample is sent, and does not take a `max_tasks`
slot, so a search that waits on the rollouts it sends works at any
`max_tasks`. It stays open until its handle is closed (`close()`,
`result()`, leaving `async with`) or the attempt that added it ends, and
then ends once the samples already sent have run. Closing never stops
those samples; `cancel()` does. A fed task is never retried and cannot run
on its own: its log is marked by the reserved dataset name
`samples_from_handle`, and only logs that are not fed decide an eval set's
result, so a fed task's failure counts only through a task that is not fed
and fails because of it.

Handles build on the run queue of [task-dispatch.md](task-dispatch.md): an
added task is a record in the run's queue, which the run's dispatcher
starts and ends.

## Why

A task added during a run starts while its creator runs, but to use it the
creator needs more than the add:

- a way to wait for the task or cancel it, which a bare `enqueue_task()`
  call does not give;
- a way to send it samples: the free `enqueue_sample()` reaches only the
  calling task's own `SampleSource`;
- a start that does not wait for a `max_tasks` slot. A running task holds
  its slot for its whole life, including while it waits, so a searcher
  waiting on an ordinary rollout task it added holds a slot the queued
  rollout needs. Any fixed limit deadlocks once N waiting tasks hold N
  slots: one searcher at `max_tasks=1`, or a selection-mode worker whose
  `max_tasks` equals its batch size. A larger `max_tasks` does not fix it;
  the rollout task has to start whatever the limit is.

The use case is a search (or any loop) that proposes samples, runs each as
a rollout in another task with its own solver and scorer, and reads the
result before proposing the next.

## How it works

User documentation: "Adding tasks imperatively" and "Tasks fed through a
handle" in [Task Sources](../docs/task-source.qmd) (with the worked search
example), the `max_tasks` exception in "Multiple Tasks" and the headroom in
"Waiting on a handle" in [Parallelism](../docs/parallelism.qmd), and the
`TaskHandle`, `TaskEndedError`, `SampleAbandonedError` and
`samples_from_handle` entries in the `inspect_ai` reference.

Code:

- `src/inspect_ai/_eval/task/enqueue.py`: `enqueue_task()`, `TaskHandle`,
  `TaskEndedError`, `SampleAbandonedError`, the run queue (`RunQueue`,
  `TaskRecord`) and the attempt context (`TaskAttempt`, `attempt_scope`,
  `creator_attempt`, `is_fed`).
- `src/inspect_ai/_eval/task/sample_source.py`: `samples_from_handle()`,
  `HandleChannel` (the fed task's sample source), `HANDLE_DATASET_NAME`,
  and the free `enqueue_sample()`'s refusal.
- `src/inspect_ai/_eval/run.py`: starting fed tasks outside `max_tasks`
  (`dispatch_tasks`), closing a fed task's channel on an operator cancel
  (`_attempt_cancel`) and a fed task's settings
  (`_apply_fed_task_settings`).
- `src/inspect_ai/_eval/task/run.py`: delivering sent samples to a running
  attempt (`task_run`) and running `TaskSource` callbacks outside any
  attempt (`notify_task_source` and the sample callbacks).
- `src/inspect_ai/_eval/eval.py`: resolution under the creator's model
  (`_resolve_enqueued_tasks`), the refusals in `eval_resolve_tasks` and
  `eval_retry_async`.
- `src/inspect_ai/_eval/evalset.py`: `all_evals_succeeded`,
  `validate_eval_set_prerequisites` and `task_identifier`.
- `src/inspect_ai/_eval/task/task.py`: `resolve_dataset_or_source`, which
  names a fed task's dataset and reserves the name.
- `src/inspect_ai/log/_retry.py`: `retryable_eval_logs` leaves fed logs out.

Tests run on mockllm models, need no network, Docker or provider, and the
async ones run on asyncio and (with `--runtrio`) trio:

- `tests/test_enqueue_task.py`: the search at `max_tasks=1` under `eval()`
  and `eval_set()` and in a multi-model run, cancelling, closing, the send
  error order, refusals, discovery, task hooks as creators, the uncounted
  start, sandbox headroom and run cancellation (the `test_*fed*`,
  `test_*handle*`, `test_search_*` and `test_creator_*` tests).
- `tests/test_sample_source.py`: the channel itself: the reserved dataset
  name, sample ids and delivery, settings, the free `enqueue_sample()`
  refusal, graceful cancels, failure, eval-set results and `eval_retry()`
  (the `test_fed_*` tests and their neighbours).
- `tests/test_eval_set.py`: identifiers and the log-directory check
  (`test_fed_task_identifier_is_built_from_its_task_id`,
  `test_eval_set_resume_skips_fed_logs_in_the_log_dir`,
  `test_eval_set_later_round_skips_fed_logs`,
  `test_eval_set_runs_a_requested_task_named_like_a_fed_one`).
- `tests/test_eval_set_selection.py`: a selection worker's creator feeding
  a rollout task, and refusing a fed log as `resume`.
- `tests/test_retry.py`: `test_eval_retryable_leaves_out_fed_task_logs`.

### The handle API

`enqueue_task()` stays synchronous and returns one handle per task it
added, in resolution order. A task added inside a running attempt
(including every fed task) is resolved once, under that attempt's model; a
task added anywhere else is resolved once per run model, with one handle
each. A task that sets its own `model` keeps it.

A handle carries the task's id, name and model. Its methods, documented on
`TaskHandle` and in "Tasks fed through a handle" in the user docs:

- `enqueue_sample(sample)` runs `sample` in a fed task, as one epoch, and
  returns its logged `EvalSample`; an errored or operator-cancelled sample
  comes back with its `error` set.
- `result()` closes the handle, then waits until the fed task ends, and
  returns its final log or `None` if it ended with none. It closes first
  because a creator waiting on a task it feeds would otherwise wait for an
  end its own open handle prevents.
- `close()` accepts no more samples; the task ends once the samples sent
  have run.
- `cancel()` aborts the task, as an operator's task cancel does, and does
  nothing once the task has ended. It works from the moment the task is
  added, including while the task is queued and before the control channel
  can see it ("Closing and cancelling").
- `async with handle` closes the handle on exit and never cancels.

`enqueue_sample()` and `result()` need a task fed through the handle and
raise `RuntimeError` on any other; `close()`, `cancel()` and the attributes
work on every handle. Every method, like `enqueue_task()` itself, must be
called on the run's event loop
(`test_handle_calls_off_the_run_loop`).

The *creator* of a fed task is the attempt that added it. Its end closes
the task's channel. User docs and errors say "the task that added it" or
"fed through its handle", not "creator".

To stop the rollouts it sent when it stops early, a creator calls the
synchronous `cancel()` in an `except BaseException:` block that re-raises.
That block runs on an error, a sample limit and every cancellation (a time
limit and a working limit both reach a sample's code as a cancellation, as
does an operator abort), and `cancel()` awaits nothing, so it runs inside a
cancelled scope. A `finally:` would also run when the search returns
normally, where `cancel()` aborts the rollout task while it is still
finishing its samples and leaves it an error log
(`test_creator_stopping_early_cancels_its_rollouts`).

### What the handles add to the run queue

The run queue ([task-dispatch.md](task-dispatch.md#the-run-queue)) owns
each fed task's record and gives it its own `HandleChannel`, the task's
sample source, which the record's handles send through. The queue gives a
fed record no retries.

Code that an attempt runs, including a background coroutine it starts,
adds tasks with that attempt as their creator until the attempt ends
(`TaskAttempt`, `creator_attempt` in `enqueue.py`). Only such code can add
a fed task.

The dispatcher (`dispatch_tasks` in `src/inspect_ai/_eval/run.py`) starts
a fed record outside `max_tasks` once its channel holds a sent sample,
unless a pause holds it or a run cancellation has been latched; ordinary
`max_tasks` starts never pick a fed record, and no record starts twice.
A fed record's attempt is not counted against `max_tasks`.

### Tasks fed through a handle

**Dataset.** `samples_from_handle()` returns a `HandleChannel`, a
`SampleSource` with no seed. `resolve_dataset_or_source` gives such a task
an empty dataset named `samples_from_handle`, so every fed log records that
dataset name, and refuses the name for any other dataset at `Task`
construction and in `task_with`
(`test_fed_task_dataset_name_is_reserved`). The name lives in the eval
spec, so every copy of the log (conversion, recovery) carries it.

**Starting, with no slot.** A fed task waits queued until its first sample
is sent, then starts whatever `max_tasks` is
(`test_fed_task_takes_no_slot`,
`test_fed_task_starts_while_another_task_builds`). It runs only what its
creator sends, and its samples are bounded by `max_samples`,
`max_sandboxes` and its model's connection limit like any task's, while
its creator's own slot is counted. A fed task whose handle closes before
any sample is sent ends with no attempt and no log, so a handle never used
costs nothing. Its model controller is created lazily on its first
`generate`, as for any added task
([task-dispatch.md](task-dispatch.md#adding-tasks)).

**Model and epochs.** A fed task uses its own `model` if it sets one,
otherwise the model of the task that added it, so a creator in a
multi-model run feeds a rollout task under its own model
(`test_each_creator_feeds_its_own_rollout_task_in_a_multi_model_run`). It
runs one epoch: each send is one epoch of one sample and settles with one
result, and a creator that wants repeats sends the sample again. The
run's sample retries apply to a sent sample as to any sample, so the
result delivered is the one logged after them. An operator requeue of a
sent sample that already returned its result runs it again under the same
id and epoch ([Requeue](../docs/control-channel.qmd#requeue)); the log
then holds the rerun's result, which its sender never receives
(`HandleChannel.sample_complete`; the requeue path in
`src/inspect_ai/_eval/task/scheduler.py`).

**Ids.** The handle sends a copy of the caller's sample (the caller's
object is unchanged) under an id it assigns (`HandleChannel.send`), and
refuses a sample that already has one. The id is built from the fed task's
id and a per-task counter, so it is unique within the task and across
tasks: the rollout tasks of two creators, a fresh rollout task added after
a failure, and the one a retried creator adds again never share an id, and
nothing that reuses a sample record by `(id, epoch)` can match one sent
sample to another (`test_fed_task_sample_ids_and_delivery`,
`test_fed_tasks_of_a_retried_creator_share_no_sample_id`). It is built from
the task's id rather than the attempt's because a sample can be sent before
the attempt starts. Ids sort in send order within a task, up to the
counter width `HandleChannel.send` formats them with.

**Delivery.** A sample sent before the fed task's attempt starts is
delivered when the attempt starts; later ones go to the running attempt
at once (`HandleChannel`, `task_run` in
`src/inspect_ai/_eval/task/run.py`). Sent samples are admitted, set up and
scheduled as any `SampleSource` addition is, so each starts as soon as
`max_samples` allows. A sent sample's failed sandbox setup fails the fed
task (`test_sent_sample_setup_failure_ends_the_fed_task`). Once its handle
is closed, the task ends when nothing sent is still in flight.

**Results.** A sent sample's logged run settles its send; a sample
cancelled before it was logged settles it with `SampleAbandonedError`. The
channel keeps no sample or result once a send has settled. A caller whose
wait is cancelled leaves its send in place: the sample still runs, and its
result is dropped.

**Settings.** A fed task's settings are resolved before its log starts, so
the log's eval config records the values that applied
(`_apply_fed_task_settings` in `src/inspect_ai/_eval/run.py`;
`test_fed_task_settings_resolve_before_the_runs`,
`test_run_selection_does_not_apply_to_a_fed_task`,
`test_run_epoch_reducer_does_not_apply_to_a_fed_task`):

- The sample limits (`message_limit`, `token_limit` with its
  `token_limit_type`, `turn_limit`, `time_limit`, `working_limit`,
  `cost_limit`), error tolerance (`fail_on_error`, `continue_on_fail`,
  `score_on_error`) and `max_samples` are the task's own value if it sets
  one, else the run's, else the default (for `max_samples`, the default
  from its model's connection pool). The control channel retunes
  `max_samples` while it runs, as for any task.
- The run's `epochs`, epoch reducer, `limit` and `sample_id` do not apply:
  one epoch, the task's own reducer if it sets one, no limit, no selection.
  The creator chooses the samples it sends, and a run-wide value would drop
  sends silently or, for a reducer that needs several epochs, refuse every
  fed task.
- The run's `approval`, `review` and `sentinel` win, as for every task:
  they are the operator's oversight controls.
- Tags stay merged; generate config and the run-wide limits (`max_tasks`,
  `max_sandboxes`, `max_connections`) are unchanged.

The creator's own settings are not inherited: the creator passes what it
wants shared when it builds the rollout task. Every task not fed through a
handle, including an ordinary task added from inside a running task, keeps
the run-wins resolution of [task-dispatch.md](task-dispatch.md).

**Never retried.** A fed task is never retried: no retry is queued or
reported, and a retry the task requests itself is not honoured
(`test_fed_task_failing_after_a_sample_is_not_retried`,
`test_fed_tasks_own_retry_request_is_not_honoured`). When it fails, a sent
sample's sandbox setup included, it ends with its error log, its
unresolved sends raise `TaskEndedError` with that log, and the sends
already returned keep their runs. The creator holds the search state and
every result returned, and decides whether to add a fresh task. With the
default `fail_on_error`, the first errored rollout is returned to its
sender with its `error` set and then ends the task; a rollout task sets
`fail_on_error=False` to keep accepting samples after a sample error.

### Closing and cancelling

Every cause closes a fed task's channel the same way, and the task's
feeder sees it at once: `close()`, `result()`, leaving `async with`,
`cancel()`, any operator cancel of the task (`abort`, `drain`, `score` or
`error`), the end of the creator's attempt by any exit (so a fed task that
is itself a creator closes its own channels when it ends) and the end of
the fed task. A creator that forgets to close cannot keep a rollout task
open past its own attempt (`test_creator_attempt_end_closes_its_channels`).

`cancel()` of a fed task still queued (which has never started, since fed
tasks are not retried) ends it at once with no log, whether or not a
sample was sent: no abort attempt runs, the run's `TaskSource` hears
nothing, `eval()` returns no log for it, and the display's task total drops
by one (`test_fed_task_cancelled_while_queued_ends_with_no_log`). Once it
is running, `cancel()` aborts it as for any task
([task-dispatch.md](task-dispatch.md#phases-and-cancelling)) and closes
its channel at once, so a send right after `cancel()` raises
`RuntimeError` whether or not the abort has taken effect
(`test_cancel_of_a_fed_attempt_before_it_registers`). Samples already sent
when a drain, `score` or `error` cancel closes the channel follow that
directive's rules; an abort cancels them with the task.

The control channel sees a fed task only once its attempt registers, as
for any task added during a run: a queued fed task is not listed by the
control channel's task list and cannot be cancelled or drained there, only
through its handle (`RunQueue.cancel`). Listing and cancelling queued tasks
through the control channel belongs to
[task-dispatch.md](task-dispatch.md#control-channel-1).

### Terminal outcomes

Every fed task ends, including when dispatch ends, so no wait outlives its
target. When it ends, each unsettled send fails with its own
`TaskEndedError` and the task holds none of its senders' samples
(`test_each_waiting_sender_gets_its_own_task_ended_error`):

| how the fed task ended | `result()` | an unresolved `enqueue_sample()` |
| --- | --- | --- |
| an attempt returned a log (success, error, setup or log-init failure, abort, a run cancellation after the log was written) | that log | `TaskEndedError` whose `log` is that log |
| no log (closed before any sample was sent, cancelled before it started, still queued when dispatch ended) | `None` | `TaskEndedError` whose `log` is `None` |

A send that already has its run keeps it; one abandoned raises
`SampleAbandonedError`. A cancelled caller's wait raises the cancellation
(`test_run_cancellation_keeps_a_fed_tasks_written_log`,
`test_fed_request_at_run_cancellation_ends_with_no_log`).

A send of a valid sample (no `id`; a sample with one raises `ValueError`
first, whatever the task's state) to a channel that no longer accepts
samples raises by one order, first match wins: once the task has ended, `TaskEndedError` with its final
log or `None`; while the channel is closed (by any cause above) and the
task still runs its last samples, `RuntimeError` ("the handle is closed").
`TaskEndedError` is a `RuntimeError` subclass, and the tests assert the
exact type (`test_handle_send_error_order`,
`test_send_after_the_creator_ends_raises`,
`test_drained_fed_task_refuses_sends`).

A handle kept and used inside `TaskSource.next_tasks()` needs no rule of
its own: the dispatcher calls it only when no attempt is running
([task-dispatch.md](task-dispatch.md#the-dispatcher)), so every fed task's
creator has ended and every fed task has ended; `result()` returns its log
at once and a send raises `TaskEndedError` with it
(`test_fed_task_handle_in_next_tasks_after_its_creator_ended`).

### What is refused

A fed task is added only by `enqueue_task()` from code running inside an
attempt that has not ended, which becomes its creator: a solver, scorer or
tool, a task-level hook such as `on_task_start`, or a coroutine left over
from a finished sample (`test_task_hook_adds_a_fed_task_its_samples_feed`).
Every check runs before anything is added. Elsewhere:

- Outside any attempt, after the creator's attempt ended, or from an
  `on_run_start` hook: `RuntimeError` from `enqueue_task()`
  (`test_fed_task_added_after_its_creator_ended_is_refused`).
- From any `TaskSource` callback (`next_tasks()`, `task_complete`,
  `sample_complete`, `sample_abandoned`), or a coroutine one starts, even
  though `task_complete` and the sample callbacks run inside an attempt: a
  direct `enqueue_task()` raises `RuntimeError` to the callback. A fed task
  the callback returns is refused the same way where Inspect adds the
  returned tasks: returned from `next_tasks()` or `task_complete`, the
  error ends the run and `eval()` raises it; returned from
  `sample_complete` or `sample_abandoned`, it fails the task whose sample
  reported, which ends with an error log. An ordinary `enqueue_task()` from
  a callback is unaffected (`test_source_callbacks_cannot_add_a_fed_task`).
- With `epochs` above 1: `ValueError` ("send a sample again to repeat it").
- As a `ResolvedTask` or `PreviousTask`: `ValueError` ("must start fresh;
  pass the Task"). A fed task is always a fresh `Task`, so its task id is
  new for every addition.
- Passed to `eval()`, `eval_set()` or a selection worker:
  `PrerequisiteError` from `eval_resolve_tasks`. This includes a whole-file
  spec, which loads every decorated task in the file, so a creator whose
  rollout task shares its file is run by name, as the user docs show
  (`test_whole_file_with_a_fed_task_is_refused`).
- Its log passed to `eval_retry()`: `PrerequisiteError` from
  `eval_retry_async`, read from the log's dataset name after crashed logs
  are recovered and before any task is resolved, so a list holding a fed
  log retries nothing (`test_eval_retry_refuses_a_fed_tasks_log`). Reading
  the log rather than the rebuilt task covers a fed task built with
  `task_with(registered_task(), dataset=samples_from_handle())`, whose log
  names a factory whose own dataset is not `samples_from_handle()`.
- The free `enqueue_sample()` inside a fed task: `RuntimeError`, before
  anything is buffered (`test_free_enqueue_sample_is_refused_in_a_fed_task`).
  Only the handle sends samples; without the refusal a rollout solver could
  add work its handle never sent, even after `close()`.
- `TaskHandle.enqueue_sample()` with a sample that has an `id`:
  `ValueError`.

A fed task named like a requested or seed task is not refused: its
identifier keeps its log apart ("Logs, eval sets and retries"). A fed task
and a requested task can then share a name in the display, the control
channel's task list and the viewer, and a control-channel selector by name
and model that matches both gets the existing ambiguity error, which asks
for the task id.

### Logs, eval sets and retries

A fed task's log is an ordinary log whose dataset name is
`samples_from_handle`. `eval()` and `eval_set()` return it with the run's
other logs, it is written to the log directory, and log listings and the
viewer show it. A `.json`-logged run feeds tasks as an `.eval` one does. A
fed task that runs is reported to the run's `TaskSource` like any task.

- **Results.** `all_evals_succeeded`, which is `eval_set()`'s result, its
  retry predicate and a selection worker's result, skips every fed log,
  however deeply it is nested, so only logs that are not fed decide the
  result. A creator that cancels its running rollout task, or replaces a
  failed one, does not fail the set; a creator that is not fed and fails
  does. A fed creator's failure, like any fed failure, counts only if it
  makes a task that is not fed fail in turn
  (`test_fed_task_failure_does_not_fail_an_eval_set`).
  `retryable_eval_logs` likewise leaves fed logs out.
- **Identifier.** `task_identifier()` builds a fed task's identifier, from
  its `ResolvedTask` or its log, from its file, name, model and task id,
  marked with `samples_from_handle` where an ordinary identifier has its
  arguments hash, and hashes neither arguments nor settings
  (`_fed_task_identifier` in `src/inspect_ai/_eval/evalset.py`;
  `test_fed_task_identifier_is_built_from_its_task_id`). The stored
  `EvalSpec.task_id` makes it unique to the fed task and the same from the
  `ResolvedTask`, from every attempt's log and from every later read of the
  header. Settings are left out because the task id alone is enough and
  because a fed task's task-first settings are where the resolved-task and
  log-header computations could disagree. No ordinary identifier has the
  marker, so a fed log never matches a requested task, and a selection
  worker given one as `resume` refuses it with its existing identifier
  check (`test_eval_set_runs_a_requested_task_named_like_a_fed_one`,
  `test_eval_set_selection_refuses_a_fed_log_as_resume`).
- **Log-directory check.** `validate_eval_set_prerequisites`, which a
  resumed `eval_set()` and every later `retry_immediate=False` round run,
  skips fed logs with or without `log_dir_allow_dirty`: no error, and left
  out of the logs it returns, so eval-set info and log matching never see
  them. A search's eval set resumes over its own rollout logs without
  `log_dir_allow_dirty=True`, which would turn the check off for every
  stray log. An ordinary added task's log still needs the flag: it carries
  no mark that it was added.

### Waits and limits

A fed task takes no `max_tasks` slot, and `result()` waits only on fed
tasks, so no handle wait needs a slot. Three limits still apply to work a
handle wait depends on, and none is lent to a waiter:

- **`max_sandboxes`.** A waiting sample keeps its sandbox permit. The
  limit is often a hard quota, a sandbox is a live resource, and the
  limiter cannot hand a permit to one specific sample.
- **`max_samples`** is per task, so a task whose samples wait on its own
  other samples needs room for both.
- **`max_connections`.** A connection permit is held for a whole
  `generate` call, and the public `on_before_model_generate` hook runs
  inside it, so a hook that awaits a sent sample on the creator's model
  holds a permit that sample needs.

A run without that headroom waits, with no warning. Raising the sandbox
or sample limit through the control channel while the run goes on frees
the wait at once
(`test_sandbox_headroom_for_a_send_can_be_raised_while_it_waits`). A
connection wait depends on the model's pool. An explicit `max_connections`
is a fixed pool (a `ResizableSemaphore`), whose limit the control channel's
named-concurrency retune raises at once, freeing the wait
([Configuration](../docs/control-channel.qmd#configuration)). An adaptive
pool is different: the control channel raises only its ceiling, and the
controller grows its live limit only as requests complete, which no
blocked hook does (`AdaptiveConcurrencyController.set_max` in
`src/inspect_ai/util/_concurrency.py`), so raising the ceiling cannot
release the wait; an adaptive pool needs that headroom when the run
starts. The user docs ("Waiting on a handle") state the headroom.

## Guarantees and limits

- **One terminal outcome.** Every fed task ends, with a log or none, and
  every `result()` and unresolved `enqueue_sample()` returns or raises when
  it does ("Terminal outcomes").
- **Works at any `max_tasks`.** A fed task starts on its first sample
  outside the limit, under `eval()`, `eval_set()` and selection mode, and
  runs only what its creator sends.
- **Bounded by its creator.** A creator cannot leave a rollout task open
  past its own attempt, and closing never stops samples already sent.
- **A sent id names one sample**, across tasks, attempts and runs.
- **A fed log never stands in for a requested task**: not in eval-set
  matching, `resume`, `eval_retry()` or the eval set's result.
- **Limits.**
  - A run whose `max_sandboxes`, `max_samples` or fixed connection pool
    leaves no room for the work a handle wait depends on hangs until that
    limit is raised; one whose adaptive connection pool is all held by hooks
    waiting on sent samples hangs for good, since raising its ceiling while
    it runs cannot free them ("Waits and limits").
  - A fed task does not count toward `max_tasks`, so a supervisor that
    sets `max_tasks` as a ceiling (a selection worker's) sees one extra
    running task for each fed task that has been sent a sample and has not
    ended.
  - A fed task's token and cost usage is not counted against its
    creator's limits.
  - A sent sample whose sandbox setup fails ends the whole fed task and
    cancels its running samples.
  - A `max_connections` retune made before a fed task's model controller
    exists misses it when no other task has created that controller (the
    rollout task sets its own `model`, or its creator has not generated
    yet); see [task-dispatch.md](task-dispatch.md#not-this-design).
  - A fed log is only for the run that wrote it: it cannot be retried, so
    a creator that is retried adds and feeds a fresh rollout task.
  - The control channel sees a fed task only once its attempt registers;
    while it is queued, only its handle can cancel it ("Closing and
    cancelling").
  - An operator requeue of a sent sample whose result was already returned
    replaces its logged result without reaching the sender ("Model and
    epochs").

## Decisions

- **`enqueue_task()` returns `list[TaskHandle]`** (decision: Ransom,
  2026-11-03) **and stays synchronous** (decision: Ransom, 2026-11-16,
  reasons restated 2026-11-18): adding a task awaits nothing, and an async
  version would silently break every existing call that does not await it.
- **The receiving task declares that it is fed through its handle**
  (decision: Ransom, 2026-11-09), with `samples_from_handle()` as its
  dataset (name: decision: Ransom, 2026-11-12).
- **`async with` closes and never cancels** (decision: Ransom,
  2026-11-09); a creator stops its rollouts with `cancel()` in an `except
  BaseException:` that re-raises, not a `finally:` (decision: Ransom,
  2026-11-18).
- **`result()` closes the handle before it waits** (decision: Ransom,
  2026-11-10) **and waits only on fed tasks** (decision: Ransom,
  2026-11-12).
- **A fed task is never retried automatically** (decision: Ransom,
  2026-11-10).
- **A fed task takes no `max_tasks` slot, and no slot is lent to any
  awaited task; it is resolved once under its creator's model; its sent
  samples get `send-<token>-<n>` ids with a per-task token** (decision:
  Ransom, 2026-11-11).
- **A fed task may be added from any code inside a running attempt, runs
  one epoch per sent sample, does not decide `eval_set()`'s result, and
  runs in `.json`-logged runs** (decision: Ransom, 2026-11-12).
- **The reserved dataset name `samples_from_handle` marks a fed log**, and
  `eval_retry()` and the eval set's result read it (decision: Ransom,
  2026-11-16).
- **Every cancel through the attempt's `TaskCancel` closes the channel**,
  `abort` included, and `cancel()` closes it too whether or not the
  directive applies, with no separate stopped state (decision: Ransom,
  2026-11-16 and 2026-11-17).
- **A fed task's identifier is built from its task id**, with no settings
  hashed and no change to inspect_flow or inspect_steward, so a fed task
  named like a requested one is not refused (decision: Ransom,
  2026-11-17).
- **Fed-task creation is refused in every `TaskSource` callback**, by
  clearing the attempt context for the call (decision: Ransom, 2026-11-17).
- **A fed task starts on its first sample**, at the cost of the rule that
  closing an empty queued channel ends the record with no log (decision:
  Ransom, 2026-11-17, kept 2026-11-18).
- **The eval set's log-directory check skips fed logs** (decision: Ransom,
  2026-11-18).
- **Only fed tasks resolve their settings task-first**; an ordinary task
  added from inside a running task keeps the run-wins resolution
  (decision: Ransom, 2026-11-19).
- **A fed task's `max_samples` falls back to the run's value** like its
  other settings (decision: Ransom, 2026-11-19).
- **A fed task cancelled while queued ends at once with no log**, with no
  abort attempt (decision: Ransom, 2026-11-19).
- **No warning for handle waits short of headroom**; the docs state it
  (decision: Ransom, 2026-11-19).
- **Protecting a running selection worker's fed logs from Steward's
  archival is a Steward change**, not an Inspect one (decision: Ransom,
  2026-11-17; see "Compatibility").

## Alternatives considered

- **Running the rollout task in a separate Inspect process** (a child
  `inspect eval`). It isolates crashes and needed nothing new, but each
  child pays Inspect's start-up and the sandbox's `task_init`, a long-lived
  child needs a protocol each user builds, connection and sandbox limits
  are not shared, and the child is outside `eval_set()` retry and resume.
- **Lending a slot to the task a running task waits on.** It makes waits on
  any added task safe, but needs a loan per target, a second start step and
  rules for nested loans and waits that outlive their attempt. The use case
  waits only on fed tasks, which need no slot.
- **`result()` on any handle, with a `max_tasks` warning.** A wait on an
  ordinary added task keeps the waiter's slot while the awaited task needs
  one. The use case never waits on one, and refusing it leaves room to
  allow it later.
- **No added task counting toward `max_tasks`.** Unbounded: a task that adds
  one fixed-dataset task per sample would run them all at once.
- **Starting a fed task when it is added.** A handle never used would run an
  attempt, write an empty log and fire the task hooks.
- **A fed task cancelled while queued ending through an abort attempt**, as
  an ordinary queued task does. The abort log serves an eval set's result
  and a source waiting on reports; a fed log serves neither, and ending
  with no log is already an outcome.
- **One fed task per run model.** Every creator would pick its own and close
  the rest.
- **Several epochs per sent sample.** It needs a future per epoch and
  partly abandoned requests; a creator sends the sample again instead.
- **A fed task inheriting its creator's settings.** The creator's limits are
  chosen for the search, not for one rollout.
- **Task-first settings for every task added from inside a running task.**
  It changes an existing feature and brings identifier, `eval_retry()` and
  migration work; fed tasks are new and need none of it.
- **A fed task's `max_samples` skipping the run's value**, going from its
  own straight to its model's default. Unnecessary: a task that wants a
  size apart from the run's sets its own, which already wins.
- **`max_samples` as an `enqueue_task()` argument.** A second precedence
  rule beside the task's own setting, covering only one entry point.
- **A `send_samples=True` option on `enqueue_task()`** attaching a port to
  any `SampleSource` task. It needs a feeder that pulls the source
  concurrently; declaring the feeding on the receiving task reuses the
  existing buffer and callbacks.
- **Generated `dyn-` ids, a plain counter, or caller-chosen ids.** `dyn-`
  ids are assigned at admission, after the request must be keyed; a counter
  with no token repeats across tasks; caller ids need duplicate checks.
- **An `EvalSpec` field marking fed logs.** A log schema change with a
  coordinated viewer update; the dataset name is a field every log already
  has.
- **Refusing `eval_retry()` by the rebuilt task's dataset.** A task adapted
  with `task_with` after its factory returned rebuilds with the factory's
  dataset and would retry without the sent samples.
- **Counting fed logs in the eval set's result.** A creator that recovers
  from a failed rollout task, or cancels one it no longer needs, would fail
  the set.
- **Retrying a fed task.** The retry would have to carry settled requests
  into its results without rerunning them and hand it the unsettled ones;
  the creator already holds every result and can add a fresh task.
- **Applying the run's `--limit` and `--sample-id` to fed tasks.** They
  select among requested tasks' samples; a run limited for debugging would
  drop most rollouts.
- **`async with` cancelling the task on exit.** A creator that hits a
  time limit would abort the rollouts it already sent, and one that returns
  normally would abort the rollout task before it finished its samples.
- **`started()` and `state` on the handle.** Nothing in the use case waits
  for a start or polls a state.
- **A warning when a wait starts with every sandbox permit in use**, or a
  wait-for graph refusing waits that cannot finish. The warning needs each
  sent sample's provider resolved and tracked and fires when holders are
  about to finish; the graph must be rechecked at every blocking event and
  limit change. Documented headroom covers the use case.

## Compatibility

- **Public API.** `enqueue_task()` returns `list[TaskHandle]` and is still
  synchronous, so calls that ignore the result work unchanged; every call
  must be on the run's event loop
  ([task-dispatch.md](task-dispatch.md#run-shapes-and-what-is-refused)).
  `TaskHandle`, `TaskEndedError`, `SampleAbandonedError` and
  `samples_from_handle` are exported from `inspect_ai`. Existing
  `SampleSource` tasks and ordinary added tasks keep their settings
  resolution and sample filtering.
- **Logs and schemas.** No eval log schema, viewer type, control-channel or
  config file change. A user dataset named `samples_from_handle` is refused
  at construction; an existing log whose dataset carries that name is
  treated as a fed log (identifier, eval-set result, `eval_retry()`).
- **Task identifiers.** Ordinary identifiers are unchanged, so
  `TASK_IDENTIFIER_VERSION` is unchanged and no eval-set manifest or
  inspect_flow store column changes. inspect_flow and inspect_steward treat
  identifiers as opaque strings, so they observe, publish and copy fed logs
  like any log, under an identifier that never matches another task's.
- **inspect_flow and inspect_steward reporting.** Neither knows a fed log's
  role: each treats it as the log of a task the set does not request, as
  for an ordinary added task, so Flow reports "Log returned that does not
  match any task" for it, and "Some logs failed even though the eval set
  succeeded" when the creator succeeds and a fed task fails.
- **Steward selection workers.** Steward archives (moves) a log whose
  identifier is not in its manifest unless the identifier is in its running
  set, and a worker's running set holds its creators' identifiers, not
  their fed tasks'. Steward can therefore move a fed log while the worker
  is still writing it. Using handles in Steward selection workers needs
  Steward to treat a running worker's logs as in flight until it exits.

## Security

- **Sent samples** can carry model output (the search proposes them). They
  enter the fed task through its existing sample buffer with ids the
  channel assigns, so model output never chooses a sample id or a log
  member name; their content is sample input, treated as any dataset
  sample is.
- A handle is an in-process object; nothing new is exposed on the control
  channel.
- **The `max_tasks` exemption** is reached only through
  `samples_from_handle()`, which the eval author writes; a fed task's
  samples stay under `max_samples`, `max_sandboxes` and the connection
  limits.
- **Oversight controls.** A run-level `approval`, `review` or `sentinel`
  policy applies to a fed task even when the task sets its own, so a
  rollout task cannot opt out of the operator's policy.

## Not this design

- Handles across processes (a task in another selection-mode worker).
- A handle for tasks a `TaskSource` returns from `next_tasks()`.
- Recording the creator in the eval log; see
  [task-dispatch.md](task-dispatch.md#interactions-with-related-changes).
- Showing open handle waits in the control channel's task list: a
  per-task count of waits in the control state, a `GET /tasks` field and a
  CLI column.
- Counting a fed task's token or cost usage against its creator's limits.
- Keeping an ordinary added task's failure in the result of an `eval_set()`
  whose later legacy round (`retry_immediate=False`) does not rerun it. It
  applies to every added task not fed through a handle, and belongs to the
  change that handles added tasks under `eval_set()`.
- Making the logs of ordinary added tasks pass the eval set's log-directory
  check without `log_dir_allow_dirty=True`. They need a mark of their own
  first, such as a record of the task that added them.
- A sent sample's failed sandbox setup failing only that sample (returned
  to its sender with its `error` set) rather than ending the fed task. It
  belongs in the shared `SampleSource` feeder, for every task whose source
  adds samples.
- Detecting waits that cannot finish because sandbox, `max_samples` or
  connection permits are held by their own waiters.
- Waiting in-run on an ordinary added task through `result()`. It needs a
  rule for the waiting task's `max_tasks` slot (a warning that names the
  control channel's `max_tasks` retune, or a lent slot) and for waits inside
  `TaskSource.next_tasks()`.
