# A foreign `CancelledError` escaping the solver becomes a sample error

Status: proposed, 2026-09-22. Issue:
[meridianlabs-ai/inspect_ai#521](https://github.com/meridianlabs-ai/inspect_ai/issues/521).
Author: agent (Claude), reviewed by Codex; see the PR. Companion:
[`sample-lifecycle.md`](sample-lifecycle.md) (the per-sample state machine
this design adds one transition to).

## Why

When a solver raises a backend cancellation exception that none of inspect's
own cancel scopes is *currently* delivering (a *foreign* cancellation: a
library caught a real cancellation and re-raised a fresh one, raised one on
its own, or re-raised a saved one after its scope had exited), the sample
runner does not notice. The solver is cut off, the sample is scored on
whatever `TaskState` it had (usually the pre-solver state with no model
output), and the log records a completed sample with `error: None`, no
`limit`, and eval `status: success`. Nothing on the console or in the log
says the solver never finished.

Reproduced on this branch's base (`472cf7dd2`, Python 3.13.7, anyio 4.14.2,
trio 0.34.0) with the issue's two-sample `mockllm` task whose solver is
`raise asyncio.CancelledError()`, and with a backend-neutral variant that
catches the backend's own cancellation inside a locally cancelled
`CancelScope`, saves it, and raises it after leaving that scope:

| fixture | backend | configuration | eval status | sample `error` | scores |
| --- | --- | --- | --- | --- | --- |
| fresh `asyncio.CancelledError()` | asyncio | `fail_on_error=False` | `success` | `None` | `includes: I` on both |
| fresh `asyncio.CancelledError()` | asyncio | `retry_on_error=1, fail_on_error=False` | `success` | `None` | `includes: I` on both; no retry happened |
| fresh `asyncio.CancelledError()` | asyncio | `fail_on_error=True` (default) | `success` | `None` | `includes: I` on both |
| saved backend cancellation | asyncio | `fail_on_error=False` | `success` | `None` | `includes: I` |
| saved backend cancellation | trio | `fail_on_error=False` | `success` | `None` | `includes: I` |

The consequences: a sample whose solver never ran counts in
`completed_samples` and scores as incorrect, silently lowering accuracy in a
log that says success; `fail_on_error`, `retry_on_error`, `score_on_error`
and every sample-error view (`inspect ctl sample errors`, the viewer's error
badge, eval-set retry) never see it. The confirmed real-world trigger is the
Grok provider's unary gRPC call cut off by `attempt_timeout` (#517, fixed
separately at the provider); the pattern is not specific to it, and it is
not specific to asyncio. The same hole swallows a `background()` coroutine
that dies with a foreign cancellation: the group cancels the solver, the
solver's cancellation is absorbed, and the sample is scored on partial state
(verified below).

## Goals and non-goals

Goals:

- A foreign cancellation escaping the solver ends the sample as an ordinary
  **sample error**: an `ErrorEvent` in the transcript, `error` set on the
  logged sample, subject to `retry_on_error`, `fail_on_error` and
  `score_on_error` exactly like an exception the solver raised.
- Genuine cancellations keep their current behaviour: operator interrupts
  (`ctl sample cancel`, `ctl task cancel --action ...`), the working limit,
  the time limit, task-level abort/retry teardown, `^C`, and a sibling's
  `fail_on_error` teardown.
- Backend-neutral: the same code and the same tests on asyncio and trio.
- No change to how the sample runner distinguishes those cases today (no
  inspection of anyio's private cancellation marker), and no new
  configuration.

Non-goals (see "Not this design" for the ones worth filing):

- A foreign cancellation raised by a **scorer**.
- The `TimeoutError` that reaches the top of the sample stack and proceeds
  to scoring with a warning (`run.py:2905`).
- A cancellation landing in the unguarded window between the solver's
  exception handling and the scoring `try` (`run.py:2961`), which drops the
  sample today for every kind of solver error.
- The provider-side leak in #517.
- Distinguishing "library re-raised our cancellation" from "library raised
  its own": both are foreign from the runner's point of view and both get
  the same treatment.

## Current behaviour

All references are to `src/inspect_ai/_eval/task/run.py` at `472cf7dd2`
unless another file is named.

**Where the solver runs.** `_task_run_sample_attempt` defines a closure
`run(tg)` (`run.py:2693`) that calls `state = await plan(state, generate)`
(`run.py:2760`) and is started as a **child task** of a fresh task group:
`async with anyio.create_task_group() as tg: tg.start_soon(run, tg)`
(`run.py:2887-2888`). The host task's body of the `async with` is only the
`start_soon`; it never raises. The group is wrapped by the sample's limit
scopes (`run.py:2678-2691`), of which only the time limit is a cancel scope.

**The handler.** `run` catches `anyio.get_cancelled_exc_class()`
(`run.py:2766`) and dispatches on state the runner set itself:

- `active.interrupt_action` (`run.py:2767`): an operator interrupt.
  `ActiveSample.interrupt()` stamps the action and cancels `tg.cancel_scope`
  (`log/_samples.py:408-430`), so the cancellation is attributable.
- `active.limit_exceeded_error` (`run.py:2823`): the working limit (or a
  sandbox-service bridged limit) via `ActiveSample.limit_exceeded()`, which
  likewise stamps and cancels (`log/_samples.py:432-440`).
- otherwise `raise` (`run.py:2855-2856`): the comment says "this was not a
  user interrupt or working time limit so propagate".

Its `finally` runs `tg.cancel_scope.cancel()` (`run.py:2857-2860`) so
`monitor_working_limit()` and `background()` coroutines stop.

**What the backends do with a child that dies of a cancellation.** In
anyio's asyncio backend (`anyio/_backends/_asyncio.py`), the child's done
callback `task_done` (line 836) treats *any* `CancelledError` from a child
as a cancellation, not an error: it is not appended to the group's exception
list, and the group's scope is cancelled if it is not already. The host,
waiting in `TaskGroup.__aexit__` (line 768) on `_on_completed_fut`, then
receives anyio's **own** marked cancellation from that scope, sets it as
`exc_val` and re-raises it; `CancelScope.__exit__` (line 455) swallows it
because the scope is `cancel_called` and no *parent* scope's cancellation is
visible. The `async with tg:` therefore exits normally. Trio's nursery
applies the same structured-concurrency rule to a child's `trio.Cancelled`:
a cancellation that belongs to no enclosing live scope is the nursery's own
and is absorbed (`trio/_core/_run.py:632-700`, `CancelScope._close`).

Verified with a standalone anyio script (no inspect):

| child task raises ... | asyncio | trio |
| --- | --- | --- |
| a fresh `asyncio.CancelledError()`, no explicit scope cancel | `async with tg` exits cleanly | n/a (not trio's exception) |
| a fresh `asyncio.CancelledError()`, with `tg.cancel_scope.cancel()` in its `finally` (as `run` does) | exits cleanly | n/a |
| the backend's cancellation, saved inside a locally cancelled scope and raised after that scope exited | exits cleanly | exits cleanly |
| after an enclosing scope was cancelled (external cancel) | propagates out of the group | propagates out of the group |
| a fresh `asyncio.CancelledError()` from the host body instead of a child | propagates (`CancelledError()`) | n/a |

So the issue's step 3 (anyio replacing the *host's* foreign `exc_val`) is
not the operative path here, because `run` is a child, not the host body.
The absorption is the ordinary structured-concurrency rule for a child that
is "cancelled", on both backends, and the `finally` cancel is not what
causes it. The consequence is the same: after the `else: raise`, control
resumes at `run.py:2889` as though the solver had returned.
`state.completed = True` (`run.py:2944`), scoring runs because `error is
None` (`run.py:2972`), the sample is logged without an error and reported
`completed`.

**Trio is reachable.** `trio.Cancelled` has no public constructor
(verified), so a library cannot manufacture one; but it can catch a real
one and re-raise it later, after the scope that issued it has exited. The
saved-cancellation fixture above is exactly that, and it walks the same
path (`run.py:2766` → `2855` → `2887`) with the same outcome on both
backends (table in "Why"). The `asyncio.CancelledError`-specific variants
of #521 are asyncio-only, the mechanism is not.

**Why the genuine cases are not affected by this absorption.** An external
cancellation (task abort/retry, `^C`, sibling `fail_on_error` teardown) is
delivered from a scope *enclosing* the group, so the group's scope does not
swallow it; it reaches `except anyio.get_cancelled_exc_class()` at
`run.py:2933`, which sets `cancelled_error` and records an `ErrorEvent`, and
the tail re-raises it (`run.py:3282-3296`). The time limit is the same
shape: `_TimeLimit.__enter__` opens a cancel scope around the group
(`util/_limit.py:1376-1386`) and `__exit__` converts a caught cancellation
into `LimitExceededError` (`util/_limit.py:1391-1428`), handled at
`run.py:2915`.

**What is not a foreign cancellation (asyncio).** A fresh
`asyncio.CancelledError` raised *inside* an `except` for anyio's
cancellation, while still inside the cancelled scope, carries the marked one
as `__context__`; anyio's `is_anyio_cancellation` walks `__context__`
(`_backends/_asyncio.py:363`) and treats it as its own. Verified: a solver
doing that inside `anyio.fail_after(0.01)` never reaches `run`'s handler;
`fail_after` swallows the cancellation and raises `TimeoutError`
(`anyio/_core/_tasks.py:154`), which hits `except TimeoutError` at
`run.py:2905` and proceeds to scoring with the "Unexpected timeout error
reached top of sample stack" warning. On trio the same fixture raises an
exception trio does not recognise at all; it escapes the nursery as a
`BaseExceptionGroup` and the eval fails with "Exceptions from Trio nursery"
and no logged samples. Both outcomes are pre-existing and unchanged by this
design (verified against the spike); the asyncio one is listed under "Not
this design".

**How errors are classified downstream.** `handle_error` (`run.py:2459`)
routes an exception to `SampleErrorHandler` (`_eval/task/error.py:23`),
which counts it against `fail_on_error`, and records an `ErrorEvent`;
the logged `EvalError.message` is `repr(ex)` (`exception_message`,
`_util/error.py:64`) and its traceback is `traceback.format_exception` with
the default cause chain (`_util/rich.py:79`). Several readers decide
"cancelled vs errored" purely from that message via
`is_cancellation_message` (`_util/error.py:32`, prefix `CancelledError(` or
`Cancelled(`): the control channel's sample status (`_control/state.py:903,
926, 1035`), requeue reconciliation (`_control/requeue.py:235`), interim
scoring (`_control/scoring.py:722`), the task log's cancelled-key set
(`_eval/task/log.py:789`), and task-retry seeding (`run.py:3838`). The
operator `error` disposition already wraps the cancellation in a
`RuntimeError` with `__cause__` for exactly this reason (`run.py:2792-2807`).

**How scores reach the log on an error.** The scoring block runs the
configured scorers only when `error is None` or `score_on_error` applies
(`run.py:2972-2976`), but scores a solver already wrote into `state.scores`
are copied to `results` outside that gate (`run.py:3036-3047`), and a
tolerated error reports `results or None` to metrics (`run.py:3335, 3339`).

## Design

One new local, two lines in `run`, and one statement after the task group.
No new module, type, event or configuration; nothing backend-specific.

### Record the unattributed cancellation in `run`

In `_task_run_sample_attempt`, next to the other outcome locals
(`run.py:2539-2542`):

```python
solver_cancel: BaseException | None = None
```

In `run`, add it to the `nonlocal` list (`run.py:2695-2696`) and set it in
the fall-through branch of the cancellation handler (`run.py:2855-2856`):

```python
# not an interrupt or a limit: either an external cancel (which the
# task group re-raises below) or a cancellation nothing in inspect
# is delivering (which the task group absorbs) — remember it and let
# the group decide which
else:
    solver_cancel = ex
    raise
```

The `finally: tg.cancel_scope.cancel()` stays exactly as it is.

### Convert it after the group exits normally

Immediately after the `async with` (`run.py:2887-2888`), inside the same
`try` whose `except Exception` unwraps groups:

```python
async with anyio.create_task_group() as tg:
    tg.start_soon(run, tg)
if solver_cancel is not None:
    # the group exited normally, so no enclosing scope was cancelled:
    # the solver was cancelled by something inspect did not issue
    raise RuntimeError(
        "Sample errored: solver cancelled by an unattributed cancellation "
        "(not a sample limit, an operator interrupt, or an eval cancel)"
    ) from solver_cancel
```

The discriminator is structural, not an inspection of the exception, which
is why it is the same on both backends:

- If a scope enclosing the group was cancelled (external cancel, time
  limit), the group re-raises out of `async with tg` and the statement never
  runs; `solver_cancel` is set but nothing reads it. The existing handlers
  at `run.py:2915` and `run.py:2933` behave as today.
- If an interrupt or limit fired, `run` took the first two branches and
  `solver_cancel` is `None`.
- If the group absorbed the cancellation, no enclosing scope was cancelled,
  which is precisely the case the runner cannot attribute. The `raise`
  passes through the limit scopes (none is `cancelled_caught`), through
  `inner_exception` unchanged (`util/_anyio.py:12`: a `__cause__` stops the
  `__context__` walk and a non-group returns itself), and lands in
  `except Exception as ex: error, raise_error = handle_error(ex)`
  (`run.py:2940-2941`). From there it is an ordinary solver exception.

### Resulting behaviour

Through `handle_error`, the sample follows the existing errored paths of
`sample-lifecycle.md` unchanged:

- `retry_on_error` with retries remaining: warning "Sample will be
  retried", `_SampleRetry` returned (`run.py:3238-3251`), the error appended
  to `error_retries` of the next attempt. This is the outcome the #517 case
  wants: a cut-off unary call is a transient failure.
- final attempt: `ErrorEvent` recorded, `SampleErrorHandler` counts it, the
  sample is logged with `error` set, terminal `errored` returned or raised
  per `fail_on_error` (`run.py:3310-3339`).
- scores follow ordinary-error semantics: the configured scorers do **not**
  run unless `score_on_error` is set for the final attempt
  (`run.py:2972-2976`); scores the solver had already written to
  `state.scores` before it was cut off are still copied to the log and, on a
  tolerated error, reported to metrics (`run.py:3036-3047, 3335, 3339`); with
  `score_on_error=True` the scorers' scores contribute to metrics while the
  sample stays errored and outside `completed_samples`. None of this is new
  behaviour; it is what any solver exception gets.
- the console warning is the ordinary `Sample error (id: …, epoch: …):
  RuntimeError('Sample errored: solver cancelled by an unattributed
  cancellation …')`.

The wrapped exception is a `RuntimeError`, not the cancellation itself, for
the same reason the operator `error` disposition wraps: the logged message
must not start with `CancelledError(` or `Cancelled(`, or every
`is_cancellation_message` reader would show the sample as cancelled, skip it
in requeue seeding and exclude it from task-retry counts. The original
exception is `__cause__`, so the logged traceback shows where the
cancellation came from (grpc frames, in the #517 case). A plain
`RuntimeError` matches the operator path; `EvalError` keeps only message
and traceback, so a dedicated exception class would not survive into the
log anyway.

### Interaction with a `background()` coroutine

`background()` re-raises everything (`util/_background.py:60-76`), so a
background coroutine dying of a foreign cancellation makes the group cancel
`run` with a *genuine* cancellation that also falls into the `else` branch
(no interrupt, no limit). Today that sample is scored on partial state
(verified on asyncio: the solver's post-`sleep` assignment never ran, score
`I`, status `success`). Under this design it errors with the same message.
The message names the solver's cancellation as unattributed rather than
claiming the solver itself raised, which is true in both cases; the
recorded traceback is the solver's cancellation stack, and does not
necessarily include the background worker's frames (see "Not this design").

### Races

- **Operator interrupt landing after the handler ran.** `run` read
  `interrupt_action` as `None`, then an interrupt is stamped before the tail.
  Its `tg.cancel_scope.cancel()` is a no-op (the scope is already cancelled
  or exited); the sample errors. With retries remaining the existing
  drain-window rule (`run.py:3263-3280`) abandons the attempt as cancelled,
  as it does for any error racing an interrupt; with none, the sample is
  errored and the interrupt's disposition is moot, as for any other
  exception. No new behaviour.
- **External cancel landing right after `handle_error`.** The `raise` and
  `handle_error` are synchronous, so the conversion itself cannot be
  interrupted. The first `await` after it is `emit_sample_scoring`
  (`run.py:2961`), which sits *before* the scoring `try` at `run.py:2967`
  and is unshielded when `cancelled_error` is `None`. A cancellation landing
  there bypasses the scoring-block handler (`run.py:3053`) and the task
  `cleanup` call (`run.py:3081`), and the sample is not logged. That is the
  existing behaviour for every solver exception (Codex reproduced it on the
  unmodified base with an ordinary `ValueError`); this design adds one more
  kind of error to the set that can hit it and does not change the window.
  Listed under "Not this design".

### Verified with a spike

The four-line change above was applied to this worktree (and reverted;
nothing of it is committed) and run against the reproductions:

| fixture | backend | configuration | eval status | sample `error` | `error_retries` | scores |
| --- | --- | --- | --- | --- | --- | --- |
| fresh `asyncio.CancelledError()` | asyncio | `fail_on_error=False` | `success` | `RuntimeError('Sample errored: …')` | 0 | none |
| fresh `asyncio.CancelledError()` | asyncio | `retry_on_error=1, fail_on_error=False` | `success` | same | 1 (one retry ran) | none |
| fresh `asyncio.CancelledError()` | asyncio | `fail_on_error=True` | `error`, eval error is the same message | same | 0 | none |
| saved backend cancellation | asyncio | `fail_on_error=False` | `success` | same | 0 | none |
| saved backend cancellation | trio | `fail_on_error=False` | `success` | same | 0 | none |
| `background()` dying of a fresh `asyncio.CancelledError()` | asyncio | `fail_on_error=False` | `success` | same | 0 | none |

`tests/test_cancellation_logging.py`, `tests/test_task_cancel.py`,
`tests/test_operator_interrupt.py`, `tests/test_score_on_error.py`,
`tests/test_task_retry_error_history.py`, `tests/test_eval.py`,
`tests/test_sample_limits.py` and `tests/test_task_with.py` passed against
the spike on asyncio (154 passed, 36 skipped: trio variants, `--runslow`,
a live-key test). Codex's round-1 review applied the same change in memory
and additionally confirmed: the three operator dispositions, the time
limit, `score_on_error`, solver-authored scores, retry with an awaited task
`cleanup`, and enclosing-scope cancellation on both backends behave as
before.

## Alternatives considered

**Treat it as a cancellation (the issue's second option).** Set
`cancelled_error` and record an `ErrorEvent`, no scoring. Re-raising at the
tail would tear down the whole task for one sample's library hiccup;
returning like the operator `cancel` disposition would count the sample
cancelled, bypass `fail_on_error` and `retry_on_error`, and still leave the
eval `success` with a sample the retry loop never re-runs. A cancellation
nothing in inspect issued is a failure of the solver's code path, and the
error semantics (retry, then fail or tolerate) are what users configured
for those.

**Classify inside `run` with anyio's marker.** Call
`anyio._backends._asyncio.is_anyio_cancellation(ex)` in the handler and
convert a foreign exception there. Rejected: private API, asyncio-only
(the saved-cancellation case on trio carries trio's own `Cancelled` and
would pass any marker check), and it would misclassify a *genuine*
cancellation caused by a background coroutine's foreign death, which the
structural check handles. `asyncio.Task.cancelling()` was considered as a
public discriminator; it is 3.11+ and the repo supports 3.10, and it is
asyncio-only for the same reason.

**Stop the group from absorbing it.** Make `run` re-raise as a non-cancel
exception in the `else` branch. Impossible without first knowing whether
the cancellation is external, which is the question the group answers by
whether it re-raises.

**Also reset `solver_cancel` in the genuine-cancel handlers.** Unnecessary:
the only reader is the statement after the group, which those paths skip.
Adding resets would spread the new state across four handlers for no
behavioural difference.

## Compatibility and migration

- **Logs.** No schema change. Affected samples move from "completed,
  scored, `error: None`" to the existing errored shape (`error` set,
  `error_retries` when retried). Old logs are unaffected; a re-run of a
  task that previously hid these failures may now show sample errors or
  fail with the default `fail_on_error=True`, which is the intended
  visibility.
- **Metrics.** Such samples are no longer counted in `completed_samples`,
  and the configured scorers no longer run on them unless `score_on_error`
  is set; solver-authored scores keep ordinary-error semantics (above).
  Accuracy on affected tasks will change; that is the bug.
- **Public API / CLI / viewer types.** None. No new field, event or option.
- **Control channel and requeue.** The wrapped `RuntimeError` message
  classifies as an error, so `ctl sample errors`, `ctl sample requeue
  --errored` and retry seeding include these samples, matching the operator
  `error` disposition.
- **Trio.** Same behaviour change as asyncio for the saved-cancellation
  case (verified on the base and against the spike); the code adds nothing
  backend-specific. The fresh-`asyncio.CancelledError` fixtures do not
  apply to trio.
- **Python 3.10.** The mechanism relies on the backends' task-group
  semantics, which are not version-gated in the paths read above; the tests
  below run in the 3.10/3.11 CI matrix.

## Security

The new code handles one input from outside inspect: an exception object
raised by solver or library code. It stores a reference, wraps it as
`__cause__`, and lets the existing error path format it. The formatted
message is the fixed string above; the traceback is produced by the same
`format_traceback` every sample error already uses, with the same
truncation. No file names, URLs, model output or sandbox output reach the
new lines; the `__cause__` chain is bounded by what Python already attached
to the exception.

## Testing

All in `tests/test_cancellation_logging.py` (the module for "cancellation
error handling and logging"), plain `pytest`, no network, Docker or model.
The backend-neutral tests are `async def` and call `eval_async`, so
`tests/conftest.py`'s `pytest_pycollect_makeitem` hook parametrizes them
over both backends; the trio variants run under `--runtrio`. Two shared
fixtures:

- `saved_cancellation_solver()`: catches `anyio.get_cancelled_exc_class()`
  inside a `CancelScope` it cancelled itself, saves the exception, and
  raises it after leaving the scope. Backend-neutral (this is the trio
  reproduction); a `calls` counter and an optional "succeed on attempt N"
  switch for the retry test.
- `fresh_cancelled_error_solver()`: `raise asyncio.CancelledError()`, the
  issue's fixture. asyncio-only (`skip_if_trio` from `test_helpers.utils`).

Tests:

1. `test_unattributed_cancel_in_solver_is_sample_error` (both backends,
   saved fixture): `fail_on_error=False`; assert `status == "success"`, each
   sample has `error` whose message starts with `RuntimeError('Sample
   errored:`, `is_cancellation_message` is false for it, no scores, an
   `ErrorEvent` in events, and `log.results is None` (every sample errored
   unscored, so no aggregate results object is built: `run.py:1855, 1877`;
   verified in the spike runs, which all returned `results=None`).
2. `test_unattributed_cancel_in_solver_fails_eval_by_default` (both
   backends, saved fixture): `fail_on_error` unset; assert `status == "error"`.
3. `test_unattributed_cancel_in_solver_is_retried` (both backends, saved
   fixture succeeding on the second attempt): `retry_on_error=1`; assert
   the sample completes, one `error_retries` entry, solver called twice,
   and a task `cleanup` callback ran once per attempt.
4. `test_fresh_asyncio_cancelled_error_is_sample_error` (asyncio only,
   fresh fixture): the issue's exact reproduction; same assertions as 1.
5. `test_unattributed_cancel_from_background_is_sample_error` (asyncio
   only: the background worker raises a fresh `asyncio.CancelledError`):
   assert the sample errored and the solver's post-await code did not run.
   Synchronize on an `anyio.Event`, not a sleep.
6. `test_enclosing_cancel_is_still_a_cancellation` (both backends): the
   solver cancels a `CancelScope` wrapping `eval_async` (handle shared via a
   closure) and then awaits; assert the logged sample's error message
   satisfies `is_cancellation_message`, is not the new `RuntimeError`, and
   the task `cleanup` callback ran. This pins the "group re-raises an
   enclosing cancellation" half of the discriminator on both backends.
7. `test_context_chained_cancel_is_not_unattributed` (asyncio only,
   `skip_if_trio`): a solver that raises a fresh `asyncio.CancelledError`
   *inside* `except anyio.get_cancelled_exc_class()` while still inside
   `anyio.fail_after`; assert the sample is not recorded with the new
   `RuntimeError` (today's outcome is the `TimeoutError` warning and a
   scored sample, which the test asserts so a future change to that path is
   deliberate). Not defined for trio: there the fixture is an exception the
   backend does not recognise and the eval fails before any sample is
   logged, a pre-existing behaviour this design does not assert or change.

Existing coverage that must stay green and exercises the untouched
branches: `tests/test_task_cancel.py` (external, operator, drain-window),
`tests/test_operator_interrupt.py`, `tests/test_sample_limits.py` (time and
working limits), `tests/test_score_on_error.py`,
`tests/test_task_retry_error_history.py`. CI runs the asyncio variants;
the implementer runs `pytest tests/test_cancellation_logging.py --runtrio`
locally and reports it in the PR, since no CI job passes `--runtrio`.

## Implementation plan

One PR, two commits:

1. `src/inspect_ai/_eval/task/run.py`: add `solver_cancel`, set it in the
   `else` branch of `run`'s cancellation handler, raise the wrapped
   `RuntimeError` after the task group. Update the handler's comment to say
   what the `else` branch now means. `CHANGELOG.md` under `## Unreleased`:
   "Samples whose solver is cut off by a cancellation that inspect did not
   issue are now recorded as sample errors instead of being scored as
   completed."
2. `tests/test_cancellation_logging.py`: the fixtures and seven tests
   above. `design/sample-lifecycle.md`: one sentence in the "running"
   anchor noting that an unattributed cancellation escaping the solver
   takes the errored transition.

## Open questions

- **Message wording.** The design uses "Sample errored: solver cancelled by
  an unattributed cancellation (not a sample limit, an operator interrupt,
  or an eval cancel)". Recommendation: keep it; it mirrors the operator
  `error` wording and says what the runner knows without guessing a cause.

## Not this design

- **Foreign cancellation in a scorer.** Verified on the base (asyncio): a
  scorer raising `asyncio.CancelledError()` is caught at `run.py:3053`, sets
  `cancelled_error`, and the tail re-raises it through the task; the run
  ends with eval `status: success`, `results: None`, and the sample logged
  with `error: CancelledError()`. Scoring runs in the host task with no
  task group, so the structural discriminator here does not apply. Worth
  its own issue.
- **Cancellation in the pre-scoring window.** A cancellation delivered
  while `await emit_sample_scoring(...)` (`run.py:2961`) is suspended, after
  any solver error, bypasses the scoring handler (`run.py:3053`) and task
  `cleanup` (`run.py:3081`); the eval ends cancelled with that sample
  unlogged. Reproduced by Codex on the unmodified base with an ordinary
  `ValueError`. An inherited limitation of the error path this design
  joins; fixing it (moving the hook inside the shielded `try`, or shielding
  it when `error` is set) is a separate change.
- **`TimeoutError` at the top of the sample stack** (`run.py:2905`)
  proceeds to scoring with only a warning; on asyncio the context-chained
  re-raise pattern lands there. Same "scored as completed" smell, separate
  decision.
- **`background()` workers dying of a foreign cancellation** get the fix
  as a side effect but with the solver-centric message and the solver's
  cancellation traceback; naming the worker or preserving its frames would
  need the group to report which child died first.
- **#517** provider-side guard, in progress separately.
