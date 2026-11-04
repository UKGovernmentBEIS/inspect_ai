# Zeroing and excluding samples

## Overview

An operator who decides that a sample should not count as the model ran it
has two answers: **zero** it (count it as a failure) or **exclude** it (leave
it out of the metrics). This design adds both to Inspect, for landed logs and
for samples of a running eval.

- **Exclude** rewrites each of the sample's scores as
  `Score.unscored(reason="excluded")`: the value is `NaN`, which every metric
  and epoch reducer already skips, and the explanation carries the operator's
  reason.
- **Zero** gives each score the verdict the task's own scorers return for an
  **empty attempt** of the sample: the sample is started as for a run
  (sandbox, files, setup script, `Task.setup`), the task's main solver is
  skipped, and the scorers run on the untouched state. The score's `reason`
  becomes `"zeroed"`.

Both keep the sample's transcript and error, record who decided and why as
score-edit provenance (the earlier score stays in `Score.history`), and
recompute the log's metrics. On a landed log they are Python functions in
`inspect_ai.log` and two `inspect log` subcommands; zero runs its empty
attempts in a scratch eval of the same task and copies the verdicts in. In a
running eval, `inspect ctl sample cancel` gains `--action exclude` (for a
queued, initializing or running sample) and `--action zero` (for a sample that
has not started its solver yet), resolved by the eval runner itself.

## Why

The task is meridianlabs-ai/inspect_ai#450: Inspect Steward already zeroes and
excludes samples, but outside Inspect and with machinery Inspect can replace
with something simpler and deterministic. Steward is an operator layer over
`eval_set` runs: when an operator rules that a class of failed or flagged
samples (a provider outage, a reward hack found by a scanner) should be
excluded from scoring or counted as failures, Steward writes that ruling into
the landed log so that every reader of the log directory (the viewer,
`inspect log` tools, dataframes) sees the result the operator signed. Its
user documentation describes the two dispositions in
`docs/errors.qmd:49-57` of meridianlabs-ai/inspect_steward.

What Steward does, and what it costs:

- **Exclude** is a score edit and works well. It needs nothing from Inspect
  beyond `edit_score()`, `Score.unscored()`'s `NaN` sentinel and
  `recompute_metrics()`. It misses one case: an errored sample with no scores
  is given an unscored score only under the task's *first* scorer, so a
  multi-scorer task's other metrics still count it as missing rather than
  unscored.
- **Zero** needs the task's scorer, because what a zero is depends on it (`I`
  for `match()`, `0` for a numeric scorer, a fail for a sandbox test). Steward
  obtains it with a side run: it spawns a whole `eval_set` worker process on
  the ruled sample ids into a scratch directory, polls the worker's control
  channel every 0.5 s, and issues `inspect ctl sample cancel --action score` on
  each sample the moment it reads as running, so the scorer scores whatever
  the solver did before the cancel landed. That is not an empty attempt: every
  solver step before the first cancellation checkpoint runs (a
  `system_message()` or prompt template always does, `Task.setup` partly or
  fully), and an agent may reach its first model call within the poll
  interval. It also needs a process launcher, a socket watcher, a 30-minute
  cap, a capture guard against definitions that call `eval_set()` at import,
  and a workaround for sample ids containing `:`.

Inspect can do both natively: exclusion is a library function over a log, and
an empty attempt is a run of the sample whose main solver is skipped, which
the runner can do deterministically. Doing it in Inspect also lets the same
dispositions apply to samples of a running eval through `inspect ctl`, which
Steward cannot do (it defers rulings on logs still being written).

## Goals and non-goals

Goals:

- Exclude a sample of a landed log: every score the task's scorers write
  becomes unscored with reason `"excluded"`, with provenance, metrics
  recomputed.
- Zero a sample of a landed log: every score the task's scorers write becomes
  the verdict on an empty attempt, with reason `"zeroed"`, with provenance,
  metrics recomputed.
- The same two dispositions for samples of a running eval through
  `inspect ctl sample cancel`, where the sample's state allows them.
- One empty-attempt definition everywhere: sample initialized as for a run,
  `Task.setup` run, main solver skipped, the task's scorers run.
- `"excluded"` and `"zeroed"` join the standard `ScoreReason` vocabulary.

Non-goals:

- Steward's other rulings (`rerun`, `accept`, `score`, `dismiss`) and its
  journal, anomaly classes and sign-off. Re-running is already
  `inspect ctl sample requeue` and eval-retry with sample invalidation.
- Changing a sample's `error`, the log's `status`, or which samples an
  eval-set retry re-runs (see Open questions).
- Zeroing a sample of a running eval after its solver has started, or
  rewriting the record of a sample that already finished in a running eval:
  both are refused with advice to apply the disposition to the landed log.
- Bulk selection by error class or status (`--errored`-style sweeps), and a
  separate `excluded_samples` count beside `unscored_samples`.
- Changing Steward. Moving Steward onto these functions is its own change.

## Current behaviour

### Steward's implementation

All paths are in meridianlabs-ai/inspect_steward, `src/inspect_steward/_marks/`.

- `edit.py:185-235` (`mark_unscored`): for each ruled sample, located by
  `(id, epoch)` and held to its uuid (`locate`, `:174-182`), every existing
  score is edited with `edit_score(..., ScoreEdit(value=float("nan"),
  explanation=f"{reason} — excluded by {by}", reason="excluded",
  provenance=...), recompute_metrics=False, epoch=...)`. A sample with no
  scores gets one, under the first name in `log.eval.scorers`
  (`_first_scorer`, `:311-316`). The scorer's metadata is left as it stands.
- `edit.py:238-290` (`harvest_scores`): for a zero, each score of the side
  run's sample is copied in with `edit_score(..., ScoreEdit(value, answer,
  explanation, reason="zeroed", metadata, provenance))`.
- `edit.py:135-153` (`provenance`) builds `ProvenanceData(author=<ruler>,
  reason=<ruling reason>, metadata={"steward": {class, generation, ruling ts,
  disposition}})`; `marked_by` (`:156-171`) reads the ruling timestamp back
  out of `Score.history` to make a crashed runner's retry idempotent.
- `edit.py:293-308` (`commit`) refuses a log with no scorers, calls
  `recompute_metrics(log)` once, and writes the whole log with
  `write_eval_log(log, location, if_match_etag=log.etag)`.
- `run.py:107-179` (`_carry_out`) reads each target log whole under
  Steward's workspace claim, defers a log whose status is `started`, applies
  `mark_unscored` or `harvest_scores`, commits, and journals what it wrote.
- `run.py:264-364` (`_side_run`) and `:453-484` (`_watch`) are the zero side
  run described under Why. `run.py:434-439` (`_selectors`) prefixes each id
  with the task name because Inspect's sample-id selection reads a leading
  `name:` as a task scope; `run.py:93` sets `INSPECT_EVAL_SET_CAPTURE` so that
  importing an `eval_set()` script does not run it.
- `spawn.py:35-79` starts each marking run as a detached process, partly
  because `recompute_metrics` may import the task module.

The log after a Steward exclusion holds, per score, `value: NaN`,
`reason: "excluded"`, the reason text in `explanation`, the original score as
`history[0]` and the edit (with provenance) as `history[1]`, plus a
`ScoreEditEvent` in the sample's events. Metrics count the sample under
`unscored_samples`. After a zero, the same shape with the side run's value,
answer, explanation and metadata and `reason: "zeroed"`; the sample counts in
the denominator.

### Inspect primitives this design builds on

- `Score.unscored()` (`src/inspect_ai/scorer/_metric.py:178`) sets `value` to
  `NaN`; metrics and reducers skip it and count it as unscored. The semantics
  are documented in [Scoring policy](../docs/scoring-policy.qmd) and
  [Unscored Samples](../docs/custom-scorers.qmd#unscored-samples).
- `ScoreReason` (`src/inspect_ai/scorer/_metric.py:49`) is a `Literal` of five
  standard reasons; `Score.reason` is typed `ScoreReason | str | None`, so any
  string is accepted. The literal is exported to
  `src/inspect_ai/_view/inspect-openapi.json` (the `enum` beside `string`) and
  from there to the viewer's generated types. The viewer renders the reason as
  plain categorical text (`ScoreEventView.tsx` in ts-mono).
- `edit_score()` (`src/inspect_ai/log/_score.py:13`) applies a `ScoreEdit` to
  one score of one sample, creating the score when absent (`history=[edit]`)
  or recording the original as `history[0]` before applying the edit
  (`:88-145`); it inserts a `ScoreEditEvent` into the scorers span, and with
  `recompute_metrics=True` resolves metrics *before* mutating so a missing
  metric leaves the log unchanged. Documented in
  [Editing Logs](../docs/eval-logs.qmd#sec-eval-log-modification).
- `recompute_metrics()` / `compute_log_metrics()`
  (`src/inspect_ai/log/_metric.py:136`, `:88`) rebuild `results` from every
  sample that has scores, errored or not. Verified by running a three-sample,
  two-scorer `mockllm` eval with one errored sample: excluding the errored
  sample and one scored sample with `NaN` edits on both scorers gave
  `scored_samples=1, unscored_samples=2` per scorer, `completed_samples=2`.
- Score keys are `unique_scorer_name()` applied in order to the task's
  scorers (`src/inspect_ai/_eval/task/run.py:1162-1166`), and
  `log.eval.scorers[i].name` is the unqualified registry name
  (`as_scorer_spec`, `src/inspect_ai/scorer/_scorer.py:207`). Verified: a task
  with `[match(), includes(), match()]` records `eval.scorers` names
  `match, includes, match` and score keys `match, includes, match1`.
  `inspect score --action append` dedupes differently (`match-1`,
  `src/inspect_ai/_eval/score.py:176`).
- `inspect score` / `score_async` (`src/inspect_ai/_eval/score.py:234`)
  rebuild a `TaskState` from the logged `EvalSample`
  (`task_state_from_sample`, `:464`) and run scorers on it, with no sandbox.
  A logged `EvalSample` carries only the names of the sample's `files`, so a
  sample's sandbox cannot be rebuilt from the log; it needs the task's
  dataset.
- `eval_retry_async` (`src/inspect_ai/_eval/eval.py:1580`) reconstructs a
  runnable task from a log: the task spec from `task_file` and
  `task_registry_name` (`:1781-1803`, with its errors for unregistered
  package tasks), the model and model roles (`:1814-1825`), `task_args_passed`,
  the sandbox (`resolve_task_file_sandbox`), and sample ids re-qualified with
  the task name so an id containing `:` survives a second resolution
  (`_requalify_sample_ids`, `:1562`). This is the in-Inspect answer to
  Steward's `_selectors` workaround.
- `resolve_plan()` (`src/inspect_ai/_eval/task/run.py:674`) prepends
  `Task.setup` to whatever solver is in effect (`:685-692`); `Task.setup` is
  documented as "always run even when the main `solver` is replaced". Verified
  with a `mockllm` task: `eval(task, solver=<solver returning state
  unchanged>, sample_id=["t1:a:b"])` ran the setup solver (it set a metadata
  flag), skipped `system_message()` and `generate()`, and scored the empty
  output `I` under `match()` and `includes()`.
- Retry reuse: a prior record is reused only when `error is None` and
  `invalidation is None` (`classify`, `src/inspect_ai/_eval/task/run.py:3886`),
  so an errored sample that also has scores (today: `score_on_error`) is
  re-run by `inspect eval-retry` and eval-set retries.

### The running-eval control surface

- `inspect ctl sample cancel TASK SID [EPOCH] --action score|error|cancel`
  (`src/inspect_ai/_cli/ctl/_sample.py:573`) posts to
  `POST /evals/<id>/sample/cancel` (`src/inspect_ai/_control/server.py:1228`),
  which 400s an unknown `action` and maps `cancel_sample()`
  (`src/inspect_ai/_control/cancel.py:537`) results to 200 / 404 / 409.
  User documentation: [Control Channel](../docs/control-channel.qmd).
- A **running** sample is interrupted through `ActiveSample.interrupt(action)`
  (`src/inspect_ai/log/_samples.py:413`), which cancels the sample's task
  group; the runner's handler (`run.py:3003`) resolves the action, then the
  scorers span runs (`run.py:3211`) when the sample has no error.
- An **initializing** sample (registered, not started) gets the intent stamped;
  the start-time self-check fires it right after `active.start(tg)`
  (`run.py:2922-2972`), before the plan (`run.py:2983`) runs.
  [initializing-sample-cancel.md](ctl/initializing-sample-cancel.md) owns that
  window.
- A **queued** sample (parked at the sample semaphore, never started or a
  `retry_on_error` re-park) is reachable through its `_SampleRun`
  (`src/inspect_ai/_eval/task/scheduler.py:133`) and the at-the-queue accept
  (`cancel_before_start`, `:720`); `score`/`error` on it are a 409 today.
  [queued-sample-cancel.md](ctl/queued-sample-cancel.md) owns the queued
  rows and the task-level gates.
- An attempt that errors with retries left is retried unless an interrupt is
  stamped (`run.py:3492-3508`).
- Free-text provenance from the CLI follows the `ctl config` precedent:
  `--author` defaults to the git identity (`_default_provenance_author`,
  `src/inspect_ai/_cli/ctl/_config.py:860`).

### Who uses which shapes

The only existing producer of zero and exclude is Steward, on landed `.eval`
logs of tasks loaded from a file or the registry, with static datasets whose
samples have ids. Searching inspect_ai, inspect_scout, inspect_flow and
inspect_swe for the reasons `excluded` / `zeroed` finds no other producer or
reader; the viewer shows any reason string as text. The design therefore
supports tasks that eval-retry can reload (file or registered) and samples
the task's dataset still holds; every other shape is refused with an error
(see Design).

## Design

### Vocabulary

`ScoreReason` gains an operator group:

```python
ScoreReason = Literal[
    # model under test
    "invalid_response_format",
    "refusal",
    "no_response",
    # measurement instrument
    "grader_failed",
    "scoring_failed",
    # operator decision
    "excluded",  # excluded from scoring; the value is NaN
    "zeroed",    # scored as an empty attempt
]
```

A *disposition* is one of these two decisions applied to one sample:

```python
# src/inspect_ai/log/_disposition.py
SampleDispositionKind = Literal["zero", "exclude"]

class SampleDisposition(NamedTuple):
    kind: SampleDispositionKind
    provenance: ProvenanceData   # author and a non-empty reason
```

Every disposition is a `ScoreEdit` carrying `provenance`, applied with the
same code `edit_score()` uses. That code (the create-or-update block of
`edit_score`, `src/inspect_ai/log/_score.py:88-145`, without the event
insertion and metric recompute) moves into a helper both the log functions
and the eval runner call:

```python
# src/inspect_ai/log/_score.py
def apply_score_edit(scores: dict[str, Score], score_name: str, edit: ScoreEdit) -> Score:
    """Apply one edit to `scores[score_name]` in place (creating it if absent); return it."""
```

`edit_score()` keeps its signature and behaviour and calls the helper.

The edits:

- **Exclude:** `ScoreEdit(value=float("nan"), reason="excluded",
  explanation=provenance.reason, provenance=provenance)`. `answer` and
  `metadata` are `UNCHANGED`: the scorer's answer and grader metadata are
  evidence about the sample, and the exclusion is a decision about it.
- **Zero:** `ScoreEdit(value=v.value, answer=v.answer,
  explanation=v.explanation, reason="zeroed", metadata=v.metadata or {},
  provenance=provenance)` where `v` is the empty attempt's score of the same
  name. On a sample that already had that score the original is
  `history[0]`; in a running eval (below) the empty attempt's own score is
  `history[0]`, so its own reason (for example `no_response`) is kept.

The sample's `error`, `events` (beyond the appended `ScoreEditEvent`s),
`messages`, `output`, `limit` and `invalidation` are untouched.

**Which score names a disposition covers.** For a sample of a landed log:

- Exclude edits every key in the sample's `scores`, plus each *task score
  name* the sample lacks. The task score names are the ordered union of the
  score keys of all samples in the log; when no sample has scores (every
  sample errored), they are `unique_scorer_name()` applied in order to
  `log.eval.scorers` names, the derivation the runner uses. An errored sample
  is therefore unscored under every scorer, not only the first.
- Zero edits exactly the names the empty attempt produced. A sample holding
  a score the empty attempt did not produce (a scorer appended later with
  `inspect score --action append`, or a scorer removed from the task since)
  is refused before anything is changed: "sample <id> (epoch <n>) has scores
  the task's scorers do not produce (<names>); exclude it, or zero it in a
  log scored only by the task's scorers". An empty attempt whose scorer
  returned `None` leaves that name unedited, as the runner would.

**Idempotence.** A sample whose covered scores all already carry the
disposition's reason is reported unchanged and not edited again (zero then
spends no empty attempt on it). Dispositions stack otherwise: excluding a
zeroed sample, or zeroing an excluded one, adds an edit to the history.

### The empty attempt

An empty attempt of a sample is the runner's ordinary sample run with the
task's main solver skipped: sample state built from the dataset sample, the
sample's sandbox, files and setup script provisioned, `Task.setup` run, then
the task's scorers on the resulting state (empty `output`, the input
`messages` plus whatever `Task.setup` added), then sandbox cleanup and the
task's `cleanup`. Running `Task.setup` is deliberate: it prepares the
environment the scorers inspect, and its documented contract is that it runs
whatever solver is in effect.

The runner already supports this through the solver override, so landed-log
zero uses it unchanged: an internal registered solver

```python
# src/inspect_ai/_eval/zero.py
@solver(name="inspect_ai/empty_attempt")
def empty_attempt() -> Solver:
    """Leave the state as `Task.setup` left it, so the scorers see an attempt that did nothing."""
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state
    return solve
```

passed as `solver=` makes `resolve_plan()` produce `Task.setup` followed by
this no-op. In a running eval the runner selects a setup-only plan instead
(see "Running evals").

### Landed logs: Python API

In `src/inspect_ai/log/_disposition.py`, exported from `inspect_ai.log`:

```python
SampleSelector = int | str | tuple[int | str, int]
"""A sample id (every epoch of it) or an (id, epoch) pair."""

class DispositionResult(NamedTuple):
    applied: list[tuple[int | str, int]]     # (id, epoch) edited now
    unchanged: list[tuple[int | str, int]]   # already carried this disposition

def exclude_samples(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
    *,
    trust_log: bool = False,
) -> DispositionResult: ...

def zero_samples(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
    *,
    model: str | Model | None = None,
    model_roles: ModelRoles | None = None,
    display: DisplayType | None = None,
) -> DispositionResult: ...

async def zero_samples_async(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
    *,
    model: str | Model | None = None,
    model_roles: ModelRoles | None = None,
) -> DispositionResult: ...
```

Both edit `log` in place, like `edit_score()`, and leave writing to the
caller. Common rules, checked before anything changes:

- `log.samples` must be present (a log read whole); a header-only read is a
  `ValueError`.
- `log.status == "started"` is refused: the log is still being written, and
  its live samples are reached with `inspect ctl` instead.
- `log.eval.scorers` must be non-empty (nothing to recompute metrics from).
- `provenance.reason` must be a non-empty string; it is the explanation an
  exclusion records and the only record of why a zero was applied.
- Every selector must match: a bare id matches every epoch of that id; an
  `(id, epoch)` pair must name a sample in the log. Ids match by value; a
  string selector also matches an `int` id whose `str()` equals it (the CLI
  passes strings), and a selector that matches two distinct ids is an error.
  Unmatched selectors are a `ValueError` naming them.
- Metrics are resolved before the first edit (`resolve_log_metrics`, with
  `trust_log` for exclusion), so a log whose metrics cannot be rebuilt is
  left unchanged, with the existing `LookupError` and its advice. After the
  edits `compute_log_metrics` runs once.

`exclude_samples` is pure over the log: it builds the edits, applies them with
`edit_score(..., recompute_metrics=False, epoch=...)`, and recomputes.

`zero_samples_async` additionally:

1. Selects the targets that are not already zeroed.
2. Reconstructs the task as eval-retry does. The task-spec resolution
   (`src/inspect_ai/_eval/eval.py:1781-1803`) and the model and model-role
   reconstruction (`:1814-1825`) move into a helper both call:

   ```python
   # src/inspect_ai/_eval/eval.py
   class LogTaskSpec(NamedTuple):
       task: str                     # "<file>@<name>" or a registry name
       task_args: dict[str, Any]
       sandbox: SandboxEnvironmentType | None
       model: Model
       model_roles: dict[str, Model | list[Model]] | None

   def log_task_spec(eval_log: EvalLog) -> LogTaskSpec: ...
   ```

   `model` / `model_roles` arguments override the reconstructed ones, as for
   `score()`. A task that is neither in a task file nor registered raises the
   same `FileNotFoundError` eval-retry raises.
3. Runs one scratch eval in a temporary local directory:
   `eval_async(tasks=spec.task, task_args=spec.task_args, model=...,
   model_roles=..., sandbox=spec.sandbox, solver=empty_attempt(),
   sample_id=_requalify_sample_ids(log.eval.task, <target ids>),
   epochs=<highest targeted epoch>, time_limit=..., working_limit=...,
   retry_on_error=..., max_samples=..., max_sandboxes=... (from
   log.eval.config), sandbox_cleanup=True, fail_on_error=False,
   log_format="eval", log_dir=<tempdir>)`. Only the targeted
   ids run; epochs above a target's own epoch are not run, and untargeted
   epochs below it are run and ignored (an empty attempt is cheap: no
   solver). The scratch log is read back whole and the directory removed.
4. Requires, for every target, a scratch sample with the same `(id, epoch)`,
   no `error`, and scores. Otherwise it raises without editing anything:
   "the empty attempt of sample <id> (epoch <n>) did not score: <error, or
   'the task's dataset no longer holds it'>". This is atomic where Steward's
   was not required to be: nothing is half-applied.
5. Checks the score-name rule above, applies the zero edits, recomputes
   metrics once.

`zero_samples` is the synchronous wrapper: it initializes the display type
from `display` and runs the coroutine (`anyio.run` with the configured
backend, `run_coroutine` in a notebook), as `score()` does.

Zero imports and runs the task's code, exactly as `inspect eval-retry` does;
only zero logs you trust. Because the task module is imported first, metrics
it registers resolve without `trust_log`.

### Landed logs: CLI

Two subcommands of `inspect log` (`src/inspect_ai/_cli/log.py`, beside
`recover`):

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--trust-log] [--json]
inspect log zero    LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--model ...] [--model-role ...] [--json]
```

- `--sample` is repeatable and required; `--epoch N` narrows every named
  sample to that epoch; without it every epoch of each named sample is
  covered.
- `--author` defaults to the git identity, else the OS user name (the
  `ctl config` helper, moved to a shared CLI utility).
- The command reads the log whole, applies the function, and writes it back
  in place with `write_eval_log(log, location, if_match_etag=log.etag)`, so a
  concurrent rewrite of an S3 log fails with `WriteConflictError` instead of
  being overwritten. When nothing changed, nothing is written.
- Output: one line per sample (`excluded` / `zeroed` / `unchanged`) and the
  recomputed headline metric; `--json` prints
  `{"log": ..., "applied": [[id, epoch], ...], "unchanged": [...]}`.

### Running evals: `inspect ctl sample cancel --action zero|exclude`

The two dispositions are new outcomes of the existing sample-cancel
directive, because both end a sample's attempt with a chosen outcome and that
route already owns the per-state decision table, the task-level gates and the
idempotence rules.

**Surface.** `inspect ctl sample cancel TASK SID [EPOCH] --action
zero|exclude --reason TEXT [--author NAME]`. `--reason` is required with
`zero` and `exclude` and rejected with the other actions; `--author` defaults
as above. The route `POST /evals/<id>/sample/cancel` accepts
`action=zero|exclude` and new `reason` and `author` query params: missing
`reason` with these actions, or either param with `score|error|cancel`, is a
400. `SampleCancelAction` gains the two values; `SAMPLE_CANCEL_OUTCOME` gains
`"zero": "scored as an empty attempt"` and `"exclude": "excluded from
scoring"`.

**Decision table** (rows as in the cancel design; task-level gates unchanged
and evaluated first):

| Sample state | `exclude` | `zero` |
|---|---|---|
| queued: never started, or a `retry_on_error` re-park | stamped on its `_SampleRun`; resolved when it starts (below); `changed: true` with a reason saying so | stamped; runs as an empty attempt when it starts |
| initializing | stamped; resolved at start | stamped; runs as an empty attempt at start |
| running | interrupted now: transcript kept, scorers not run, each score excluded | **409**: "sample <id> has started its solver; zero needs an empty attempt — exclude it now, or cancel it (`--action cancel`) and zero it in the landed log with `inspect log zero`" |
| finished (completed, error, cancelled) | **409**: "sample <id> has finished; apply it to the landed log with `inspect log exclude`" | **409**, same with `inspect log zero` |
| queued re-run (pending requeue, prior record stands) | **409**: as finished, naming the prior record | same |
| already carries a disposition or an interrupt | `changed: false`, "already requested (<action>)" (first resolution wins) | same |

A finished sample is refused rather than reported as a `changed: false`
no-op for the reason requeue refuses `completed`: the desired end state will
not come to pass, and a success-shaped answer would mislead an agent. Its
landed log is where the disposition belongs, with the transcript intact.

**Where the disposition lives.** `_SampleRun` gains
`disposition: SampleDisposition | None`, and `SampleRequeue` gains
`dispose(sample_id, epoch, disposition)`, which stamps the run that currently
owns the key (asserting, as `cancel_before_start` does, the state the
resolver validated with no await in between). `ActiveSample` gains
`disposition: SampleDisposition | None`. The resolver stamps the run for every
accepted row, and also the `ActiveSample` when one is registered; at
registration in `_task_run_sample_attempt` (right after `active_sample(...)`
is entered) the runner copies the run's disposition onto the new
`ActiveSample`. Keeping it on the run, which survives a `retry_on_error`
re-park, means an attempt that errors during initialization is retried as
usual and the next attempt still carries the disposition. A disposition is
therefore *not* an interrupt stamp until the sample starts, and the
retry-suppression rule (`run.py:3492-3508`) does not apply to it before
start.

**Resolution in the runner** (`src/inspect_ai/_eval/task/run.py`):

- `task_run` builds `setup_plan = Plan(unroll(task.setup), internal=True)`
  (empty when the task has no setup) next to `resolve_plan()`'s result and
  passes it to `task_run_sample` with the plan.
- Start-time self-check (`run.py:2940`): a disposition is a per-sample intent
  and, like a pending interrupt, fires first and exclusively over task-level
  resolutions. `exclude` calls `active.interrupt("exclude")`, which takes the
  running path below. `zero` does not interrupt: the plan run in the
  `solvers` span is `setup_plan` instead of `plan`.
- Interrupt handler (`run.py:3003`): `case "exclude"` captures the latest
  state and sets the operator `EvalSampleLimit`, as `case "score"` does, so
  the sample proceeds to scoring with no error.
- Scorers span (`run.py:3211`): for `exclude`, each task score name gets
  `apply_score_edit({}, name, <exclusion edit>)` instead of calling the
  scorer; for `zero`, each scorer runs as usual and its result is passed
  through `apply_score_edit` with the zero edit (so the empty attempt's own
  score is `history[0]`). Both emit the usual `ScoreEvent` with the resulting
  score and add it to `results`, so live metrics, the final `results` and the
  logged record all see it. A scorer exception during a zero is an ordinary
  scoring error.
- The sample terminal-records as `completed` (its counters, listing status,
  hooks and log record are a completed sample's), with the transcript of
  whatever ran.

A running sample's transcript is kept by `exclude`, and a queued or
initializing sample's record under `zero` is the empty attempt itself, so in
every accepted row the record and its scores agree about what ran.

**API version.** No `CONTROL_API_VERSION` bump. An older server answers
`action=zero|exclude` with its existing 400 ("action must be 'score', 'error'
or 'cancel'"), and a strict server 400s the unknown `reason` / `author`
params, so a new CLI against an old eval fails loudly; the CLI recognizes that
400 and says the eval runs an older Inspect.

### Errors and edge cases

- Selectors and ids: ids are matched against the log or the live eval only,
  never interpreted; an id containing `:` is re-qualified for the scratch
  eval as eval-retry does.
- A task whose dataset changed so that a targeted sample no longer exists, or
  whose samples come from a `SampleSource` feed that no longer yields it,
  fails step 4 of zero with that said, and nothing is edited.
- A task file edited since the log was written runs as edited, as eval-retry
  does; the scratch log is not kept, but the zero edits record the scorer's
  answer and explanation for the empty attempt.
- Concurrency: the landed-log functions are synchronous over an in-memory
  log, except zero's scratch eval, which runs before any edit. The CLI's write
  is a conditional write on S3 and last-writer-wins locally, as
  `edit_score()` plus `write_eval_log()` is today.
- Cancellation: cancelling `zero_samples_async` cancels the scratch eval
  (sandbox cleanup runs as for any cancelled eval) and leaves the log
  unchanged, because edits start only after the scratch eval returns.

## Alternatives considered

- **Steward's side run and cancel-as-it-starts, moved into Inspect.** It
  works without runner changes, but the attempt is not empty (synchronous
  solver steps and possibly a model call run before the cancel), it needs a
  second process with a control channel and a polling watcher, and its
  outcome depends on timing. The solver override gives the same verdict
  deterministically, in-process, with less code.
- **Pre-stamping `--action score` on an initializing sample.** Inspect
  already fires a deferred `score` interrupt at start; but the plan is
  cancelled at its first checkpoint rather than skipped, so how much of
  `Task.setup` and the solver runs depends on where the first await falls.
  A setup-only plan is explicit.
- **Zero by re-running the sample with an empty solver and replacing its
  record** (invalidate, then eval-retry or requeue). One mechanism for
  landed and live logs, but it discards the transcript that is usually the
  evidence for the decision. Steward keeps the transcript and moves only the
  scores; so does this design.
- **Score the logged `EvalSample` with an emptied output, as
  `inspect score` does.** No task reload, but no sandbox and no `Task.setup`:
  a sandbox scorer would score a sandbox that does not exist, and a logged
  sample cannot rebuild one (only file names are logged). A second,
  partially-correct zero is worse than one that always reloads the task.
- **Scorer-declared zero values** (`@scorer(..., zero=...)`). Cheaper, but a
  second path that every scorer author must remember to fill in, and wrong
  for scorers whose verdict depends on the environment. Left as an open
  question.
- **Exclude by removing the sample**, as cancel-before-start does. Metrics
  would silently change denominators and the record of the decision would be
  gone; `NaN` keeps the sample visible and counted as unscored.
- **A new `EvalSample.disposition` field.** Every reader (viewer, dataframes,
  retry reuse, scout) would have to learn it; a score `reason` already flows
  through metrics, `score_<name>_reason` dataframe columns and the viewer.
- **Separate `inspect ctl sample zero` / `exclude` verbs.** Clearer names, but
  a second copy of the per-state table, gates and idempotence the cancel
  route already has. `--action score` set the precedent for outcome-choosing
  actions on that verb.
- **Running zero by interrupting and running a second, unlogged empty attempt
  whose scores are merged into the interrupted record.** Keeps the
  transcript in a live run, but two attempts would share one `(id, epoch)`
  in the sample buffer and the attempt loop would need a new result kind.
  The landed-log path gives the same result after the run.

## Compatibility and migration

No migration required.

- **Score reasons.** `ScoreReason` gains `"excluded"` and `"zeroed"`. Logs
  are unchanged in shape: older Inspect reads these values as the plain
  strings `Score.reason` already admits. The OpenAPI schema
  (`src/inspect_ai/_view/inspect-openapi.json`) and the viewer's generated
  TypeScript types change (an enum widens), which needs the coordinated
  ts-mono regeneration; the viewer already renders any reason string.
- **Log contents.** Dispositions write existing structures only: `Score`
  fields, `Score.history` entries with `ProvenanceData`, `ScoreEditEvent`s, and
  recomputed `results` / `reductions`. Readers of score history (viewer,
  `EvalSample` consumers, Steward's `marked_by`) see ordinary edits.
- **Public Python API.** New: `exclude_samples`, `zero_samples`,
  `zero_samples_async`, `SampleDisposition`, `DispositionResult`,
  `SampleSelector` in `inspect_ai.log`. `edit_score()` is unchanged; its
  mutation moves into `apply_score_edit` (internal).
- **CLI.** New `inspect log exclude` and `inspect log zero`.
  `inspect ctl sample cancel --action` gains `zero` and `exclude` and the
  `--reason` / `--author` options; existing actions are unchanged.
- **Control API.** `POST /evals/<id>/sample/cancel` accepts two more
  `action` values and the `reason` / `author` params; old clients are
  unaffected; new clients against old servers get a 400 (see API version).
  `CancelSample*` response shapes are unchanged.
- **Eval-set retry.** Unchanged: a disposition does not clear `error`, so an
  errored sample that was zeroed or excluded is re-run by a retry, as an
  errored sample scored under `score_on_error` is today (see Open
  questions).
- **Steward.** Its edits keep working; its `"excluded"` / `"zeroed"` strings
  are the new standard reasons, so its logs read the same as Inspect's.

## Security

- **Log contents** (`log.eval` task file, task name, args, scorer and metric
  specs) are untrusted when the log is. `exclude_samples` imports nothing
  unless `trust_log=True` (metric resolution as `recompute_metrics()` does
  it). `zero_samples` imports and runs the task, like `inspect eval-retry`;
  the docstring, CLI help and docs say to zero only trusted logs. No new
  code-execution path beyond eval-retry's.
- **Reason and author** are free text from the local caller (the Python
  caller, the CLI user, or a local ctl client already admitted by the control
  channel's socket and peer checks). They are stored as data in
  `ProvenanceData` and `Score.explanation`; the viewer renders explanations as
  it renders any scorer's explanation. They are not interpolated into
  commands or paths.
- **Sample selectors** are compared with logged ids; they never become paths
  or queries. The scratch eval's sample ids are passed to the runner's
  existing selection.
- **Model output, tool output and sandbox output** reach a zero only through
  the task's own scorers in the empty attempt, exactly as in an eval run.
- **Scratch directory** is a fresh `tempfile.TemporaryDirectory`, removed
  after the scores are read.

## Testing

Pure and `mockllm` tests run in the default suite; async tests run under both
backends (`--runtrio` locally for the control tests).

- `tests/scorer/test_score_editing.py`:
  - `exclude_samples`: every score of a multi-scorer sample, including a
    deduplicated name (`match1`) and an appended one (`match-1`), becomes
    `NaN` with reason, explanation and provenance; `history[0]` is the
    original; `answer` and `metadata` unchanged; an errored sample is
    unscored under every task score name; metrics recompute (`accuracy` over
    the rest, `unscored_samples` counted); a bare id covers every epoch; an
    `(id, epoch)` pair covers one; repeat is `unchanged`; unknown selectors,
    a `started` log, an empty reason, and an unresolvable metric each raise
    and leave the log unchanged.
  - `apply_score_edit` and `edit_score` produce identical scores and history
    (regression for the extraction).
- `tests/log/test_zero_samples.py` (new: no existing file covers running an
  eval to edit a log), with a task file fixture whose `Task.setup` sets a
  metadata flag and whose main solver would generate:
  - the zeroed scores equal the empty attempt's (`I` for `match()`), reason
    `zeroed`, original in `history[0]`, transcript and `error` unchanged,
    `Task.setup` ran, no main-solver `ModelEvent` in the scratch run;
  - an errored sample is zeroed; ids containing `:`; a multi-epoch log with
    one targeted epoch;
  - refusals that leave the log unchanged: a target missing from the
    dataset, an empty attempt that errors, extra score names, an ephemeral
    task;
  - a scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
- `tests/_cli/` (CLI): `inspect log exclude|zero` parse `--sample`, `--epoch`,
  `--reason`, `--author`, write in place, print per-sample lines and the
  `--json` envelope.
- `tests/_control/test_cancel.py`: each row of the decision table, through
  the route and the CLI: running `exclude` (record has excluded scores for
  every scorer, operator limit, no error, transcript kept); initializing and
  queued `exclude` and `zero` (zero runs `Task.setup` and the scorers, not the
  main solver); running `zero`, finished and queued-re-run rows are 409;
  repeat is `changed: false`; missing `reason` and stray `reason` are 400; an
  initialization error on a disposition-stamped sample retries and the retry
  carries the disposition; a task drain or score in flight does not override
  a stamped disposition.
- Schema drift: the OpenAPI and TypeScript drift checks pass after the
  regeneration step.

No test needs network or a provider key. A Docker sandbox variant of the
zero test is not needed: the `local` sandbox exercises the same provisioning
path.

## Implementation plan

1. **Vocabulary and shared edit helper.** Add the two reasons to
   `ScoreReason` (`src/inspect_ai/scorer/_metric.py`); extract
   `apply_score_edit` in `src/inspect_ai/log/_score.py`; document the reasons
   in `docs/scoring-policy.qmd`'s reason table; regenerate
   `src/inspect_ai/_view/inspect-openapi.json` and the ts-mono types with
   the land-ts-mono procedure. Tests: the extraction regression.
2. **Exclude on landed logs.** `src/inspect_ai/log/_disposition.py`
   (`SampleDisposition`, `SampleSelector`, `DispositionResult`,
   `exclude_samples`), exports in `src/inspect_ai/log/__init__.py`,
   `inspect log exclude` in `src/inspect_ai/_cli/log.py` (with the default
   author helper moved from `src/inspect_ai/_cli/ctl/_config.py` to
   `src/inspect_ai/_cli/util.py`), a "Zeroing and Excluding Samples" section
   in `docs/eval-logs.qmd`. Tests as above.
3. **Zero on landed logs.** `log_task_spec` extracted in
   `src/inspect_ai/_eval/eval.py` and used by `eval_retry_async`;
   `src/inspect_ai/_eval/zero.py` (`empty_attempt`, the scratch eval);
   `zero_samples` / `zero_samples_async` in `_disposition.py` (function-local
   import of `_eval.zero`); `inspect log zero`; docs section extended. Tests
   as above.
4. **Running evals.** `SampleCancelAction` and `ActiveSample.disposition`
   (`src/inspect_ai/log/_samples.py`); `_SampleRun.disposition` and
   `SampleRequeue.dispose` (`src/inspect_ai/_eval/task/scheduler.py`);
   `setup_plan`, the start-time branch, the `exclude` handler case and the
   scorers-span branch (`src/inspect_ai/_eval/task/run.py`); the decision
   table (`src/inspect_ai/_control/cancel.py`); route params
   (`src/inspect_ai/_control/server.py`); CLI options
   (`src/inspect_ai/_cli/ctl/_sample.py`); `docs/control-channel.qmd`; the
   cancel table in `design/ctl/control-channel.md`. Tests as above.

## Open questions

- **Should a zeroed or excluded errored sample stop being re-run by eval-set
  retries and `inspect eval-retry`?** Today retry reuse requires
  `error is None`, so a retry re-runs it and the disposition is lost with the
  old record. Options: (a) leave reuse unchanged and document it (this
  design; consistent with `score_on_error`, and Steward drives its own
  retries); (b) treat a sample whose scores all carry `excluded` or `zeroed`
  as reusable in `classify`; (c) move `error` into `error_retries` when a
  disposition is applied, so the sample reads as completed everywhere.
  Recommendation: (a) now, and (b) as a follow-up if an eval-set user hits
  it; (c) rewrites the sample's error history, which other readers rely on.
  Confidence: low — it depends on whether you expect dispositions on
  eval-set logs that will be retried, which the issue does not say.
- **What did "could also add scorer support" mean?** Read as scorers
  declaring their own zero value, it is a cheaper second path that is wrong
  for sandbox and model-graded scorers; read as letting the caller pass
  other scorers to `zero_samples` (as `inspect score --scorer` does), it
  changes what "zero" means away from the task's own verdict. Recommendation:
  neither in this design; the empty attempt with the task's scorers is the
  one definition. Confidence: low — the issue's phrase is ambiguous.
- **Should `--action zero` on a running sample be refused (this design) or
  discard the running attempt and re-run it as an empty attempt?** The
  refusal keeps the transcript, which is usually why the operator is zeroing
  it, and the landed-log zero gives the same scores after the run.
  Recommendation: refuse. Confidence: high.

## Not this design

- Moving Steward's `_marks` package onto `exclude_samples` / `zero_samples`
  (deleting the side run, the watcher and the id workaround).
- A bulk ctl sweep (`inspect ctl sample cancel TASK --errored --action
  exclude`), as requeue has.
- An `excluded_samples` count on `EvalScore` beside `unscored_samples`, so a
  reader can tell exclusions from grader failures without reading reasons.
- Showing dispositions distinctly in the viewer (a badge for `excluded` /
  `zeroed`, the provenance author and reason on the sample header).
- Applying a disposition to a finished sample of a running eval (rewriting a
  terminal record mid-run and updating live results).
- `inspect log invalidate`-style CLI for the existing re-run path.
