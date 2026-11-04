# Zeroing and excluding samples

## Overview

When an operator decides that a sample should not count the way the model ran
it, there are two answers: **zero** it (count it as a failure) or **exclude**
it (leave it out of the metrics). This design adds both to Inspect for landed
logs, and adds exclusion for samples of a running eval.

- **Exclude** rewrites each of the sample's scores as
  `Score.unscored(reason="excluded")`. The value is `NaN`, which every metric
  and epoch reducer already skips, and the explanation carries the operator's
  reason.
- **Zero** gives each score the verdict the task's own scorers return for an
  **empty attempt** of the sample. The sample is started as for a run
  (sandbox, files, setup script, `Task.setup`), the task's main solver is
  skipped, and the scorers run on the untouched state. The score's `reason`
  becomes `"zeroed"`. A zero that cannot produce a counted score for every
  score the sample holds is refused, and the log is left unchanged.

Both keep the sample's transcript and error. Both record who decided and why
as score-edit provenance, so the earlier score stays in `Score.history`, and
both recompute the log's metrics. On a landed log they are Python functions in
`inspect_ai.log` and two `inspect log` subcommands. Zero runs its empty
attempts in a scratch eval of the same task and copies the verdicts in. In a
running eval, `inspect ctl sample cancel --action exclude` excludes a sample
that is initializing or still running its solver; the eval runner writes the
excluded scores in place of running the scorers.

## Why

The task is meridianlabs-ai/inspect_ai#450. Inspect Steward already zeroes and
excludes samples, but it does so outside Inspect, with machinery that Inspect
can replace with something simpler and deterministic. Steward is an operator
layer over `eval_set` runs. An operator may rule that a class of failed or
flagged samples (a provider outage, a reward hack found by a scanner) should be
excluded from scoring or counted as failures. Steward then writes that ruling
into the landed log, so that every reader of the log directory (the viewer,
`inspect log` tools, dataframes) sees the result the operator signed. Its
user documentation describes the two dispositions in
`docs/errors.qmd:49-57` of meridianlabs-ai/inspect_steward.

What Steward does, and what it costs:

- **Exclude** is a score edit and works well. It needs nothing from Inspect
  beyond `edit_score()`, `Score.unscored()`'s `NaN` sentinel and
  `recompute_metrics()`. It misses one case. An errored sample with no scores
  is given an unscored score only under the task's *first* scorer, so a
  multi-scorer task's other metrics still count it as missing rather than
  unscored.
- **Zero** needs the task's scorer, because what a zero is depends on the
  scorer (`I` for `match()`, `0` for a numeric scorer, a fail for a sandbox
  test). Steward gets that verdict from a side run:
  - It spawns a whole `eval_set` worker process on the ruled sample ids, with
    a scratch log directory.
  - It polls the worker's control channel every 0.5 s.
  - It issues `inspect ctl sample cancel --action score` on each sample the
    moment the sample reads as running, so the scorer scores whatever the
    solver did before the cancel landed.

  That is not an empty attempt. Every solver step before the first
  cancellation checkpoint runs: a `system_message()` or prompt template always
  does, and `Task.setup` runs partly or fully. An agent may also reach its
  first model call within the poll interval. The side run also needs a process
  launcher, a socket watcher, a 30-minute cap, a capture guard against
  definitions that call `eval_set()` at import, and a workaround for sample
  ids containing `:`.

Inspect can do both natively. Exclusion is a library function over a log.
An empty attempt is a run of the sample with the main solver skipped, which
the runner can do deterministically. Doing this in Inspect also lets an
operator exclude samples of a running eval through `inspect ctl`. Steward
cannot do that, because it defers rulings on logs that are still being
written.

## Goals and non-goals

Goals:

- Exclude a sample of a landed log. Every score the sample holds, and every
  score name the task's scorers write, becomes unscored with reason
  `"excluded"`. The edit records provenance, and metrics are recomputed.
- Zero a sample of a landed log. Every score the sample holds becomes the
  verdict on an empty attempt, with reason `"zeroed"`. The edit records
  provenance, and metrics are recomputed.
- Exclude a sample of a running eval through `inspect ctl sample cancel`,
  while the sample is initializing or running its solver.
- One empty-attempt definition: the sample is initialized as for a run,
  `Task.setup` runs, the main solver is skipped, and the task's scorers run.
- `"excluded"` and `"zeroed"` join the standard `ScoreReason` vocabulary.

Non-goals:

- Steward's other rulings (`rerun`, `accept`, `score`, `dismiss`), and its
  journal, anomaly classes and sign-off. Re-running is already covered by
  `inspect ctl sample requeue` and by eval-retry with sample invalidation.
- Changing a sample's `error`, the log's `status`, or which samples an
  eval-set retry re-runs (decision: Ransom, 2026-11-04; see Compatibility).
- Zeroing a sample of a running eval (see Future improvements).
- Excluding, in a running eval, a sample that has not started, that has
  finished its solver, or that has finished. Each is refused with advice to
  cancel it or to exclude it in the landed log.
- Bulk selection by error class or status (`--errored`-style sweeps).
- A separate `excluded_samples` count beside `unscored_samples`.
- Changing Steward. Moving Steward onto these functions is its own change.

## Current behaviour

### Steward's implementation

All paths are in meridianlabs-ai/inspect_steward, `src/inspect_steward/_marks/`.

- `edit.py:185-235` (`mark_unscored`) handles each ruled sample. The sample is
  located by `(id, epoch)` and held to its uuid (`locate`, `:174-182`). Every
  existing score is then edited with `edit_score(..., ScoreEdit(value=float("nan"),
  explanation=f"{reason} — excluded by {by}", reason="excluded",
  provenance=...), recompute_metrics=False, epoch=...)`. A sample with no
  scores gets one score, under the first name in `log.eval.scorers`
  (`_first_scorer`, `:311-316`). The scorer's metadata is left as it stands.
- `edit.py:238-290` (`harvest_scores`) handles a zero. Each score of the side
  run's sample is copied in with `edit_score(..., ScoreEdit(value, answer,
  explanation, reason="zeroed", metadata, provenance))`.
- `edit.py:135-153` (`provenance`) builds `ProvenanceData(author=<ruler>,
  reason=<ruling reason>, metadata={"steward": {class, generation, ruling ts,
  disposition}})`. `marked_by` (`:156-171`) reads the ruling timestamp back
  out of `Score.history`, which makes a crashed runner's retry idempotent.
- `edit.py:293-308` (`commit`) refuses a log with no scorers. It calls
  `recompute_metrics(log)` once and writes the whole log with
  `write_eval_log(log, location, if_match_etag=log.etag)`.
- `run.py:107-179` (`_carry_out`) reads each target log whole under
  Steward's workspace claim and defers a log whose status is `started`. It
  then applies `mark_unscored` or `harvest_scores`, commits, and journals what
  it wrote.
- `run.py:264-364` (`_side_run`) and `:453-484` (`_watch`) implement the zero
  side run described under Why.
- `run.py:434-439` (`_selectors`) prefixes each id with the task name, because
  Inspect's sample-id selection reads a leading `name:` as a task scope.
- `run.py:93` sets `INSPECT_EVAL_SET_CAPTURE`, so that importing an
  `eval_set()` script does not run it.
- `spawn.py:35-79` starts each marking run as a detached process, partly
  because `recompute_metrics` may import the task module.

After a Steward exclusion, the log holds the following for each score:

- `value: NaN` and `reason: "excluded"`, with the reason text in
  `explanation`.
- The original score as `history[0]`, and the edit (with provenance) as
  `history[1]`.
- A `ScoreEditEvent` in the sample's events.

Metrics count the sample under `unscored_samples`. A zero leaves the same
shape, but with the side run's value, answer, explanation and metadata and
`reason: "zeroed"`. The sample counts in the denominator.

### Inspect primitives this design builds on

- `Score.unscored()` (`src/inspect_ai/scorer/_metric.py:178`) sets `value` to
  `NaN`. Metrics count a score as unscored exactly when its value is a float
  `NaN` (`scorer_for_metrics`, `src/inspect_ai/_eval/task/results.py:409`).
  Scorers produce such scores themselves too. For example, `model_graded_*`
  returns `Score.unscored(reason="grader_failed")` when the grade is missing
  from the grader's output (`src/inspect_ai/scorer/_model.py:370`). The
  semantics are documented in [Scoring policy](../docs/scoring-policy.qmd) and
  [Unscored Samples](../docs/custom-scorers.qmd#unscored-samples).
- `ScoreReason` (`src/inspect_ai/scorer/_metric.py:49`) is a `Literal` of five
  standard reasons. `Score.reason` is typed `ScoreReason | str | None`, so any
  string is accepted. The literal is exported to
  `src/inspect_ai/_view/inspect-openapi.json` (the `enum` beside `string`),
  and from there to the viewer's generated types. The viewer renders the
  reason as plain categorical text (`ScoreEventView.tsx` in ts-mono).
- `edit_score()` (`src/inspect_ai/log/_score.py:13`) applies a `ScoreEdit` to
  one score of one sample (`:88-145`).
  - When the score is absent it creates it, with `history=[edit]`.
  - Otherwise it records the original as `history[0]` before applying the
    edit.
  - It inserts a `ScoreEditEvent` into the scorers span.
  - With `recompute_metrics=True` it resolves metrics *before* mutating, so a
    missing metric leaves the log unchanged.

  Documented in [Editing Logs](../docs/eval-logs.qmd#sec-eval-log-modification).
- `recompute_metrics()` / `compute_log_metrics()`
  (`src/inspect_ai/log/_metric.py:136`, `:88`) rebuild `results` from every
  sample that has scores, errored or not. I verified this with a
  three-sample, two-scorer `mockllm` eval with one errored sample. Excluding
  the errored sample and one scored sample, with `NaN` edits on both scorers,
  gave `scored_samples=1, unscored_samples=2` per scorer and
  `completed_samples=2`.
- Score names:
  - **Task scorers.** The runner names each task scorer's score with
    `unique_scorer_name()` applied in order to the task's scorers
    (`src/inspect_ai/_eval/task/run.py:1162-1166`).
    `log.eval.scorers[i].name` is the unqualified registry name
    (`as_scorer_spec`, `src/inspect_ai/scorer/_scorer.py:207`). Verified: a
    task with `[match(), includes(), match()]` records `eval.scorers` names
    `match, includes, match` and score keys `match, includes, match1`.
  - **Solver-written scores.** A solver may write `state.scores` itself
    ([Solvers](../docs/solvers.qmd)). Those keys are captured before the task
    scorers run (`run.py:3191`), and they are copied into the sample's events
    and the eval results after them (`run.py:3273`).
  - **`log.results.scores`.** Its entries carry the score key in
    `EvalScore.scorer` (`name` is the metric key for dict-valued metrics,
    `results.py:586-588`). They hold every configured scorer, including one
    that scored no sample, and every solver-written key. I verified both with
    a two-sample `mockllm` eval. One scorer always returned `None`, a solver
    wrote `solver_score`, and one sample errored. The results held `probe`,
    `probe1` (0 scored, 0 unscored) and `solver_score`. The errored sample
    held no keys.
  - **No sample scored.** When every sample errored, `log.results` is `None`
    (verified, with `fail_on_error` both off and on).
  - **Appended scorers.** `inspect score --action append` appends to
    `log.eval.scorers` (`src/inspect_ai/_eval/score.py:443`). It dedupes
    colliding keys differently from the runner (`-N` suffixes,
    `src/inspect_ai/_eval/score.py:176`), so `log.eval.scorers` alone does
    not name the keys of an appended log.
- `inspect score` / `score_async` (`src/inspect_ai/_eval/score.py:234`)
  rebuild a `TaskState` from the logged `EvalSample`
  (`task_state_from_sample`, `:464`) and run scorers on it, with no sandbox.
  A logged `EvalSample` carries only the names of the sample's `files`, so a
  sample's sandbox cannot be rebuilt from the log. Rebuilding it needs the
  task's dataset.
- `eval_retry_async` (`src/inspect_ai/_eval/eval.py:1580`) reconstructs a
  runnable task from a log:
  - the task spec, from `task_file` and `task_registry_name`
    (`:1781-1803`, with its errors for unregistered package tasks);
  - the model and model roles (`:1814-1825`);
  - `task_args_passed`;
  - the sandbox (`resolve_task_file_sandbox`).
- Sample-id selection goes through two steps:
  1. `resolve_task_sample_ids` (`src/inspect_ai/_eval/task/util.py`) strips a
     leading `<task>:` scope. `_requalify_sample_ids`
     (`src/inspect_ai/_eval/eval.py:1562`) prefixes ids with the task name so
     that an id containing `:` survives that step. This is the in-Inspect
     answer to Steward's `_selectors` workaround.
  2. The remaining selector is a pattern, not a literal. `sample_id_filter`
     matches with `fnmatch` (`util.py:71`), so a selector `case[1]` matches
     `case1` and not itself, and `case*` matches every id starting with
     `case`. Before matching, `normalise_sample_id` treats the string `"12"`
     and the int `12` as the same id.
- `resolve_plan()` (`src/inspect_ai/_eval/task/run.py:674`) prepends
  `Task.setup` to whatever solver is in effect (`:685-692`). `Task.setup` is
  documented as "always run even when the main `solver` is replaced".
  I verified this with a `mockllm` task. `eval(task, solver=<solver returning
  state unchanged>, sample_id=["t1:a:b"])` ran the setup solver (it set a
  metadata flag) and skipped `system_message()` and `generate()`. It then
  scored the empty output `I` under `match()` and `includes()`.
- A global `epochs=N` runs every selected sample for epochs 1 through N
  (`run.py:2011`). There is no per-sample epoch selection.
- Retry reuse: a prior record is reused only when `error is None` and
  `invalidation is None` (`classify`, `src/inspect_ai/_eval/task/run.py:3886`).
  An errored sample that also has scores (today, through `score_on_error`) is
  therefore re-run by `inspect eval-retry` and by eval-set retries.

### The running-eval control surface

- `inspect ctl sample cancel TASK SID [EPOCH] --action score|error|cancel`
  (`src/inspect_ai/_cli/ctl/_sample.py:573`) posts to
  `POST /evals/<id>/sample/cancel` (`src/inspect_ai/_control/server.py:1228`).
  The route returns a 400 for an unknown `action`, and maps `cancel_sample()`
  (`src/inspect_ai/_control/cancel.py:537`) results to 200 / 404 / 409.
  User documentation: [Control Channel](../docs/control-channel.qmd).
- A **running** sample is interrupted through `ActiveSample.interrupt(action)`
  (`src/inspect_ai/log/_samples.py:413`), which stamps `interrupt_action` and
  cancels the sample's task group. The runner's handler (`run.py:3003`)
  resolves the action. The scorers span (`run.py:3211`) then runs when the
  sample has no error.
- An **initializing** sample (registered, not started) has the intent stamped
  with no task group to cancel. The start-time self-check fires it right after
  `active.start(tg)` (`run.py:2940`), before the plan runs. A stamped
  per-sample intent fires first and excludes the task-level resolutions.
  Repeating a request on an initializing sample with a stamp is a
  `changed: false` no-op (`cancel.py:588`).
  [initializing-sample-cancel.md](ctl/initializing-sample-cancel.md) owns that
  window.
- A **queued** sample is one that never started, or a `retry_on_error`
  re-park. It is reachable through its `_SampleRun`
  (`src/inspect_ai/_eval/task/scheduler.py:133`) and the at-the-queue accept
  (`cancel_before_start`, `:720`). `score` and `error` on it are a 409
  (`not_cancellable`, `cancel.py:700`): there is no attempt to score. A task
  drain or a graceful task score or error abandons queued samples as they
  leave the queue (`run.py:2565`): they count as `cancelled` and are absent
  from the log. [queued-sample-cancel.md](ctl/queued-sample-cancel.md) owns
  the queued rows and the task-level gates.
- The task score/error sweep interrupts in-flight samples only when they carry
  no `interrupt_action` and no pending `limit_exceeded_error` (`cancel.py:433`):
  the first resolution wins.
- The solver phase ends at a fixed point. The sample's solver task group
  exits at `run.py:3113`, and `run()`'s `finally` cancels the group's scope
  at `run.py:3086`. Scoring, task cleanup, sandbox teardown and logging follow
  that exit. `ActiveSample.completed` is set only when the active-sample
  context exits (`src/inspect_ai/log/_samples.py:579`), and `cancel_sample()`
  treats a sample as running until then (`cancel.py:585`). So today an
  interrupt accepted during scoring or cleanup cancels a task group that has
  already exited.
- An attempt that errors with retries left is retried unless an interrupt is
  stamped (`run.py:3492-3508`).
- Free-text provenance from the CLI follows the `ctl config` precedent:
  `--author` defaults to the git identity (`_default_provenance_author`,
  `src/inspect_ai/_cli/ctl/_config.py:860`).

### Who uses which shapes

The only existing producer of zero and exclude is Steward. It works on landed
`.eval` logs of tasks loaded from a file or the registry, with static datasets
whose samples have ids. Searching inspect_ai, inspect_scout, inspect_flow and
inspect_swe for the reasons `excluded` / `zeroed` finds no other producer or
reader, and the viewer shows any reason string as text. The design therefore
supports:

- zero for tasks that eval-retry can reload (file or registered), samples the
  task's dataset still holds, and samples whose scores all come from the
  task's scorers;
- exclusion for any log or live sample.

Every other shape is refused with an error (see Design).

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

Every disposition is a `ScoreEdit` carrying a `ProvenanceData` (author and a
non-empty reason). It is applied with the same code `edit_score()` uses. That
code moves into a helper that both the log functions and the eval runner
call: the create-or-update block of `edit_score`
(`src/inspect_ai/log/_score.py:88-145`), without the event insertion and the
metric recompute.

```python
# src/inspect_ai/log/_score.py
def apply_score_edit(scores: dict[str, Score], score_name: str, edit: ScoreEdit) -> Score:
    """Apply one edit to `scores[score_name]` in place (creating it if absent); return it."""
```

`edit_score()` keeps its signature and behaviour and calls the helper.

The edits:

- **Exclude:** `ScoreEdit(value=float("nan"), reason="excluded",
  explanation=provenance.reason, provenance=provenance)`. `answer` and
  `metadata` are `UNCHANGED`. The scorer's answer and grader metadata are
  evidence about the sample; the exclusion is a decision about it. A score
  created by the edit has `answer` and `metadata` `None`.
- **Zero:** `ScoreEdit(value=v.value, answer=v.answer,
  explanation=v.explanation, reason="zeroed", metadata=v.metadata or {},
  provenance=provenance)`, where `v` is the empty attempt's score of the same
  name. When the sample already had that score, the original is `history[0]`.

The sample's `error`, `events` (beyond the appended `ScoreEditEvent`s),
`messages`, `output`, `limit` and `invalidation` are untouched.

### Which score names a disposition covers

**Exclude** covers the sample's own score keys plus each *task score name*
the sample lacks. The task score names are the ordered, de-duplicated union
of three sets:

1. the `EvalScore.scorer` of every entry in `log.results.scores`, which holds
   each configured scorer as the runner named it (including one that scored
   no sample), each solver-written key and each appended key;
2. every score key of every sample in the log;
3. when `log.results` is `None` (no sample scored), `unique_scorer_name()`
   applied in order to `log.eval.scorers` names. This is the runner's
   derivation (`run.py:1162-1166`). It is used only in this case, because an
   appended log has results and its appended entries are not named this way.

An excluded errored sample is therefore unscored under every scorer, not only
the first. That includes a scorer that never produced a score for any sample.

**Zero** edits exactly the names the empty attempt scored. A target is
refused, before anything changes, in two cases:

- **Unscored verdict.** A score of the empty attempt is unscored (a float
  `NaN`, as a grader failure produces). Copying it would label a sample
  `zeroed` that metrics still leave out of the denominator. This holds when
  every scorer returned `NaN`, and when only some of them did. Message: "the
  empty attempt of sample <id> (epoch <n>) was not scored by <name>
  (<reason>: <explanation>); zero it again, or exclude it".
- **Uncovered score.** The sample holds a score under a name the empty attempt
  did not produce. Examples: a scorer that returned `None` on the empty
  attempt but scored the original, a solver-written score, a scorer appended
  with `inspect score --action append`, or a scorer removed from the task
  since. Leaving that score would keep the original verdict on a sample
  reported as zeroed. Message: "sample <id> (epoch <n>) holds scores the empty
  attempt does not produce (<names>); exclude it instead".

A task score name that the sample does not hold, and that the empty attempt
did not produce, stays absent, as the runner would leave it.

**Idempotence.** A target that already carries the disposition is reported
unchanged and not edited again:

- **Exclude:** every covered name is present with reason `"excluded"`.
- **Zero:** the sample holds at least one score and every score it holds has
  reason `"zeroed"`. Zero spends no empty attempt on such a target.

Otherwise dispositions stack. Excluding a zeroed sample, or zeroing an
excluded one, adds an edit to the history.

### The empty attempt

An empty attempt of a sample is the runner's ordinary sample run with the
task's main solver skipped:

1. sample state is built from the dataset sample;
2. the sample's sandbox, files and setup script are provisioned;
3. `Task.setup` runs;
4. the task's scorers run on the resulting state: an empty `output`, and the
   input `messages` plus whatever `Task.setup` added;
5. sandbox cleanup and the task's `cleanup` run.

Running `Task.setup` is deliberate. It prepares the environment the scorers
inspect, and its documented contract is that it runs whatever solver is in
effect.

The runner already supports this through the solver override, so zero uses
it unchanged. It passes an internal registered solver as `solver=`, which
makes `resolve_plan()` produce `Task.setup` followed by this no-op:

```python
# src/inspect_ai/_eval/zero.py
@solver(name="inspect_ai/empty_attempt")
def empty_attempt() -> Solver:
    """Leave the state as `Task.setup` left it, so the scorers see an attempt that did nothing."""
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state
    return solve
```

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
caller. These rules are checked before anything changes:

- `log.samples` must be present (a log read whole). A header-only read is a
  `ValueError`.
- A log with `log.status == "started"` is refused: it is still being written.
  Its live samples are reached with `inspect ctl` instead.
- `log.eval.scorers` must be non-empty; with no scorers there is nothing to
  recompute metrics from.
- `provenance.reason` must be a non-empty string. It is the explanation an
  exclusion records and the only record of why a zero was applied.
- Every selector must match.
  - A bare id matches every epoch of that id.
  - An `(id, epoch)` pair must name a sample in the log.
  - Ids match by value. A string selector also matches an `int` id whose
    `str()` equals it, because the CLI passes strings.
  - A selector that matches two distinct ids is an error.

  Unmatched selectors are a `ValueError` naming them.
- Metrics are resolved before the first edit (`resolve_log_metrics`, with
  `trust_log` for exclusion). A log whose metrics cannot be rebuilt is
  therefore left unchanged, with the existing `LookupError` and its advice.
  After the edits, `compute_log_metrics` runs once.

`exclude_samples` is pure over the log. It builds the edits for the covered
names, applies them with `edit_score(..., recompute_metrics=False,
epoch=...)`, and recomputes.

`zero_samples_async` additionally:

1. Selects the targets that are not already zeroed.
2. Reconstructs the task as eval-retry does. The task-spec resolution
   (`src/inspect_ai/_eval/eval.py:1781-1803`) and the model and model-role
   reconstruction (`:1814-1825`) move into a helper that both call:

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

   The `model` and `model_roles` arguments override the reconstructed ones,
   as for `score()`. A task that is neither in a task file nor registered
   raises the same `FileNotFoundError` that eval-retry raises.
3. Runs one scratch eval in a temporary local directory:

   ```python
   eval_async(
       tasks=spec.task,
       task_args=spec.task_args,
       model=..., model_roles=...,
       sandbox=spec.sandbox,
       solver=empty_attempt(),
       sample_id=_requalify_sample_ids(
           log.eval.task, [literal_sample_id(id) for id in target_ids]
       ),
       epochs=<highest targeted epoch>,
       time_limit=..., working_limit=..., retry_on_error=...,
       max_samples=..., max_sandboxes=...,   # from log.eval.config
       sandbox_cleanup=True,
       fail_on_error=False,
       log_format="eval",
       log_dir=<tempdir>,
   )
   ```

   - **Literal ids.** `literal_sample_id(id: str | int) -> str | int`, a new
     helper in `src/inspect_ai/_eval/task/util.py` beside `sample_id_filter`,
     escapes the `fnmatch` metacharacters of a string id (`*` as `[*]`, `?` as
     `[?]`, `[` as `[[]`) and returns an int unchanged. Re-qualification then
     protects a `:`. I verified this by running the selection functions on
     candidates `case[1]`, `case1`, `case*`, `caseX`, `case?`, `t1:a:b` and
     `a:b`: each escaped and re-qualified target selected only itself.
   - **Normalised ids.** Because selection normalises ids, a dataset holding
     both `"12"` and `12` runs both. Step 4 matches by value and ignores the
     extra one.
   - **Epochs.** `epochs` is global, so every targeted id runs every epoch up
     to the highest targeted one. Targets `a/1` and `b/2` also run `a/2` and
     `b/1`. Those extra empty attempts provision their sandboxes and run
     `Task.setup` and the scorers like any other. Their results are ignored,
     and they are not edited. A caller who zeroes widely spread epochs of
     different ids can split the call to avoid the cost.
   - **Scratch log.** It is read back whole and the directory removed.
4. For every target, requires a scratch sample with the same `(id, epoch)`
   and no `error`, then applies the zero refusals under "Which score names a
   disposition covers". Any failure raises, naming every failing target and
   its cause, without editing anything. A missing scratch sample reads "the
   empty attempt of sample <id> (epoch <n>) did not run: the task's dataset no
   longer holds it". An errored one reads "...did not score: <error>". This is
   atomic where Steward's was not required to be: nothing is half-applied.
5. Applies the zero edits and recomputes metrics once.

`zero_samples` is the synchronous wrapper. It initializes the display type
from `display` and runs the coroutine, as `score()` does: `anyio.run` with
the configured backend, or `run_coroutine` in a notebook.

Zero imports and runs the task's code, exactly as `inspect eval-retry` does,
so only zero logs you trust. Because the task module is imported first, the
metrics it registers resolve without `trust_log`.

### Landed logs: CLI

Two subcommands of `inspect log` (`src/inspect_ai/_cli/log.py`, beside
`recover`):

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--trust-log] [--json]
inspect log zero    LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--model ...] [--model-role ...] [--json]
```

- `--sample` is repeatable and required. `--epoch N` narrows every named
  sample to that epoch; without it, every epoch of each named sample is
  covered.
- `--author` defaults to the git identity, else the OS user name. This is the
  `ctl config` helper, moved to a shared CLI utility.
- The command reads the log whole, applies the function, and writes the log
  back in place with `write_eval_log(log, location, if_match_etag=log.etag)`.
  A concurrent rewrite of an S3 log therefore fails with `WriteConflictError`
  instead of being overwritten. When nothing changed, nothing is written.
- Output: one line per sample (`excluded` / `zeroed` / `unchanged`) and the
  recomputed headline metric. `--json` prints
  `{"log": ..., "applied": [[id, epoch], ...], "unchanged": [...]}`.

### Running evals: `inspect ctl sample cancel --action exclude`

Exclusion is a new outcome of the existing sample-cancel directive. Like
`score`, it ends a sample's attempt with a chosen outcome, and that route
already owns the per-state decision table, the task-level gates and the
idempotence rules. Exclusion is an **interrupt action**: it is stamped as
`interrupt_action`, like `score`. Every first-resolution guard already keys
on that stamp: the start-time self-check, the task sweep (`cancel.py:433`)
and the retry suppression (`run.py:3492-3508`). So a task-level score, error
or drain cannot override an accepted exclusion, whether it arrives while the
sample initializes or while it runs.

**Surface.** `inspect ctl sample cancel TASK SID [EPOCH] --action exclude
--reason TEXT [--author NAME]`.

- `--reason` is required with `exclude` and rejected with the other actions.
  `--author` defaults as above.
- The route `POST /evals/<id>/sample/cancel` accepts `action=exclude` and new
  `reason` and `author` query params. A missing `reason` with `exclude`, or
  either param with `score|error|cancel`, is a 400.
- `SampleCancelAction` gains `"exclude"`, and `SAMPLE_CANCEL_OUTCOME` gains
  `"exclude": "excluded from scoring"`.

**Decision table.** Rows are as in the cancel design. Task-level gates are
unchanged and evaluated first.

| Sample state | `exclude` |
|---|---|
| queued: never started, or a `retry_on_error` re-park | **409**: "sample <id> (epoch <n>) has not started — there is no attempt to exclude; use `--action cancel` to remove it from the run, or exclude it once it starts" |
| queued re-run (pending requeue, prior record stands), or cancelled before start | **409**, as the existing non-`cancel` actions answer these rows; a queued re-run's message adds "exclude its prior record in the landed log with `inspect log exclude`" |
| initializing | stamped as a deferred interrupt; fired by the start-time self-check before any of the plan runs; `changed: true` with the deferred reason |
| running its solver | interrupted now: transcript kept, scorers not run, every score name excluded |
| solver phase over (scoring, task cleanup, sandbox teardown, logging), or a fired limit not yet handled | **409**: "sample <id> (epoch <n>) has finished its solver; exclude it in the landed log with `inspect log exclude` once the eval finishes" |
| finished (completed, error, cancelled) | **409**: "sample <id> has finished; exclude it in the landed log with `inspect log exclude` once the eval finishes" |
| initializing or running, already carrying an interrupt | `changed: false`, "already requested (<action>)"; first resolution wins |

The first-resolution rule runs in both directions for running samples. Today
a second `score|error|cancel` on a running sample overwrites the stamp. With
this design, an `exclude` on a running sample that is already stamped, or any
action on a sample stamped `exclude`, is the `changed: false` no-op. Without
that, a later `score` would silently undo an accepted exclusion.

A sample that has not started is refused rather than stamped, for the same
reason `score` and `error` are refused there. If a drain or a graceful task
resolution arrived while it was queued, it would be abandoned without a
record at the queue exit (`run.py:2565`), and the accepted exclusion would
leave no trace. An operator who wants it out of the run now cancels it before
start.

A finished sample, or one past its solver, is refused rather than reported
as a `changed: false` no-op, for the reason requeue refuses `completed`: the
desired end state will not come to pass, and a success-shaped answer would
mislead an agent. The landed log is where the exclusion belongs, with the
transcript intact.

**Where provenance and the boundary live** (`src/inspect_ai/log/_samples.py`).

- `ActiveSample.interrupt(action, provenance: ProvenanceData | None = None)`
  stores `provenance` as `interrupt_provenance` when given. An `"exclude"`
  with no stored provenance is a `ValueError`. The start-time re-fire calls
  `interrupt(pending)` with no provenance and keeps the stored one.
- `ActiveSample.end_solver()` sets `solver_ended = True`. The runner calls it
  in `run()`'s `finally` (`run.py:3086`), before `tg.cancel_scope.cancel()`.
  Nothing awaits between the plan returning or raising and that `finally`, so
  a request either lands while the plan is suspended (the solver task group
  is live, and the interrupt cancels it) or sees `solver_ended`. The resolver
  refuses `exclude` when `solver_ended` is set or `limit_exceeded_error` is
  pending.
- An attempt that fails during initialization never reaches `active.start`,
  so a stamped exclusion does not fire. It resolves as a stamped `score` does
  today: the stamp suppresses the retry, and the attempt is recorded with its
  error, or abandoned as cancelled when retries remained. The operator
  excludes that record in the landed log.

**Resolution in the runner** (`src/inspect_ai/_eval/task/run.py`):

- Start-time self-check (`run.py:2940`): unchanged. A stamped `exclude` is a
  pending interrupt and fires first.
- Interrupt handler (`run.py:3003`): `case "exclude"` captures the latest
  state and sets the operator `EvalSampleLimit`, as `case "score"` does. The
  sample proceeds to scoring with no error.
- Scoring (`run.py:3207-3290`): when `active.interrupt_action == "exclude"`
  and `cancelled_error is None`, an exclusion branch replaces the scorer
  loop, inside the same `scorers` span. It applies whether or not the attempt
  also recorded an error (a solver that raised as the cancel landed), because
  no scorer code runs.
  1. For each name in `solver_score_names`, it applies
     `apply_score_edit(state.scores, name, <exclusion edit>)`, so the solver's
     score becomes `history[0]`.
  2. For each task scorer, under `scorer_names[i]` and inside its scorer span,
     it applies `apply_score_edit(state.scores, scorer_names[i], <exclusion
     edit>)` without calling the scorer. It then emits the `ScoreEvent` and
     sets `results[scorer_names[i]]`, as the scorer loop does.
  3. The existing solver-score loop (`run.py:3273`) then emits the events and
     results for the solver keys from the edited `state.scores`. The copy
     carries the exclusion rather than restoring the original.

  Live metrics, the final `results` and the logged record all see excluded
  scores.
- The sample terminal-records as `completed`, or as errored when it also
  recorded an error. Either way it carries the transcript of whatever ran.

**API version.** No `CONTROL_API_VERSION` bump. An older server answers
`action=exclude` with its existing 400 ("action must be 'score', 'error' or
'cancel'"), so a new CLI against an old eval fails loudly. The CLI recognizes
that 400 and says the eval runs an older Inspect.

### Errors and edge cases

- **Selectors and ids.** Ids are matched against the log or the live eval
  only, never interpreted. For zero's scratch eval, ids are escaped and
  re-qualified so that selection is literal.
- **Changed dataset.** Suppose a task's dataset changed so that a targeted
  sample no longer exists, or its samples come from a `SampleSource` feed
  that no longer yields it. Zero then fails step 4 with that said, and
  nothing is edited.
- **Edited task file.** A task file edited since the log was written runs as
  edited, as eval-retry does. The scratch log is not kept, but the zero edits
  record the scorer's answer and explanation for the empty attempt.
- **Concurrency.** The landed-log functions are synchronous over an in-memory
  log, except zero's scratch eval, which runs before any edit. The CLI's
  write is a conditional write on S3 and last-writer-wins locally, as
  `edit_score()` plus `write_eval_log()` is today.
- **Cancellation.** Cancelling `zero_samples_async` cancels the scratch eval
  and leaves the log unchanged. Sandbox cleanup runs as for any cancelled
  eval, and edits start only after the scratch eval returns.

## Alternatives considered

- **Steward's side run and cancel-as-it-starts, moved into Inspect.** It
  works without runner changes, but it has three costs:
  - The attempt is not empty: synchronous solver steps and possibly a model
    call run before the cancel lands.
  - It needs a second process with a control channel and a polling watcher.
  - Its outcome depends on timing.

  The solver override gives the same verdict deterministically, in-process,
  with less code.
- **Zero by re-running the sample with an empty solver and replacing its
  record** (invalidate, then eval-retry or requeue). It reuses existing
  mechanisms, but it discards the transcript, which is usually the evidence
  for the decision. Steward keeps the transcript and moves only the scores,
  and so does this design.
- **Score the logged `EvalSample` with an emptied output, as `inspect score`
  does.** This needs no task reload, but it has no sandbox and no
  `Task.setup`. A sandbox scorer would score a sandbox that does not exist,
  and a logged sample cannot rebuild one, because only file names are logged.
  A second, partially correct zero is worse than one that always reloads the
  task.
- **Copy an unscored empty-attempt verdict as the zero.** It is simple, but
  the sample would read `zeroed` while metrics leave it out of the
  denominator, which is an exclusion under another name. Refusal tells the
  operator to retry the zero or exclude the sample.
- **Exclude by removing the sample**, as cancel-before-start does. Metrics
  would silently change denominators, and the record of the decision would be
  gone. `NaN` keeps the sample visible and counted as unscored.
- **A new `EvalSample.disposition` field.** Every reader would have to learn
  it: the viewer, dataframes, retry reuse, Scout. A score `reason` already
  flows through metrics, `score_<name>_reason` dataframe columns and the
  viewer.
- **Separate `inspect ctl sample exclude` verb.** The name is clearer, but it
  would need a second copy of the per-state table, the gates and the
  idempotence rules that the cancel route already has. `--action score` set
  the precedent for outcome-choosing actions on that verb.
- **A separate live disposition field (on `_SampleRun` / `ActiveSample`)
  instead of an interrupt stamp.** It would let a queued sample carry an
  exclusion across a re-park. But the task sweep, the start-time self-check
  and the retry decision would each need to learn the new field. The queue
  exit would also have to materialize a record for a sample that never
  started, including when a drain abandons it. Refusing queued samples, and
  using the stamp the guards already honour, is smaller.
- **Accept exclusions through scoring and cleanup, and rewrite scores already
  produced.** By then the scores have been emitted as events and live
  results, and the terminal record may be in flight. Rewriting would need a
  second edit pass over each of those. The landed-log exclusion gives the
  same result after the run.

## Compatibility and migration

No migration required.

- **Score reasons.** `ScoreReason` gains `"excluded"` and `"zeroed"`. Logs
  are unchanged in shape: older Inspect reads these values as the plain
  strings `Score.reason` already admits. The OpenAPI schema
  (`src/inspect_ai/_view/inspect-openapi.json`) and the viewer's generated
  TypeScript types change (an enum widens), which needs the coordinated
  ts-mono regeneration. The viewer already renders any reason string.
- **Log contents.** Dispositions write existing structures only:
  - `Score` fields;
  - `Score.history` entries with `ProvenanceData`;
  - `ScoreEditEvent`s on landed logs, and `ScoreEvent`s in a live exclusion;
  - recomputed `results` / `reductions`.

  Readers of score history (the viewer, `EvalSample` consumers, Steward's
  `marked_by`) see ordinary edits.
- **Public Python API.** New in `inspect_ai.log`: `exclude_samples`,
  `zero_samples`, `zero_samples_async`, `DispositionResult` and
  `SampleSelector`. `edit_score()` is unchanged; its mutation moves into
  `apply_score_edit` (internal).
- **CLI.** New `inspect log exclude` and `inspect log zero`.
  `inspect ctl sample cancel --action` gains `exclude` and the `--reason` /
  `--author` options. Existing actions are unchanged, except that a second
  request on a running sample stamped `exclude` is a `changed: false` no-op
  instead of overwriting the stamp.
- **Control API.** `POST /evals/<id>/sample/cancel` accepts `action=exclude`
  and the `reason` / `author` params. Old clients are unaffected. New clients
  against old servers get a 400 (see API version). `CancelSample*` response
  shapes are unchanged.
- **Eval-set retry.** Unchanged (decision: Ransom, 2026-11-04). A disposition
  does not clear `error`. An errored sample that was zeroed or excluded is
  therefore re-run by `inspect eval-retry` and eval-set retries, and the new
  record replaces the disposition, as with an errored sample scored under
  `score_on_error` today. The `inspect log` help and the docs section say so.
- **Steward.** Its edits keep working. Its `"excluded"` / `"zeroed"` strings
  are the new standard reasons, so its logs read the same as Inspect's.

## Security

- **Log contents** (the `log.eval` task file, task name, args, scorer and
  metric specs) are untrusted when the log is. `exclude_samples` imports
  nothing unless `trust_log=True` (metric resolution, as `recompute_metrics()`
  does it). `zero_samples` imports and runs the task, like
  `inspect eval-retry`. The docstring, CLI help and docs say to zero only
  trusted logs. There is no new code-execution path beyond eval-retry's.
- **Reason and author** are free text from the local caller: the Python
  caller, the CLI user, or a local ctl client already admitted by the control
  channel's socket and peer checks. They are stored as data in
  `ProvenanceData` and `Score.explanation`, and the viewer renders
  explanations as it renders any scorer's explanation. They are not
  interpolated into commands or paths.
- **Sample selectors** are compared with logged ids and never become paths or
  queries. The scratch eval's sample ids are escaped so that the runner's
  selection matches them literally. An id therefore cannot widen the scratch
  run to other samples, which would run their setup, sandboxes and graders.
- **Model output, tool output and sandbox output** reach a zero only through
  the task's own scorers in the empty attempt, exactly as in an eval run. A
  live exclusion runs no scorer.
- **Scratch directory.** It is a fresh `tempfile.TemporaryDirectory`, removed
  after the scores are read.

## Testing

Pure and `mockllm` tests run in the default suite. Async tests run under both
backends; run the control tests with `--runtrio` locally.

- `tests/scorer/test_score_editing.py`:
  - `exclude_samples`, on a multi-scorer sample with a deduplicated name
    (`match1`), an appended one and a solver-written one: every score
    becomes `NaN` with reason, explanation and provenance. `history[0]` is
    the original, and `answer` and `metadata` are unchanged.
  - `exclude_samples` on an errored sample: it is unscored under every task
    score name. That includes a configured scorer that scored no sample, the
    solver-written key, and, on a log with no results, every name derived
    from `log.eval.scorers`.
  - Metrics recompute: `accuracy` over the rest, and `unscored_samples`
    counted.
  - Selection: a bare id covers every epoch, and an `(id, epoch)` pair covers
    one. A repeat reports the target `unchanged`.
  - Refusals that raise and leave the log unchanged: unknown selectors, a
    `started` log, an empty reason, and an unresolvable metric.
  - `apply_score_edit` and `edit_score` produce identical scores and history
    (a regression test for the extraction).
- `tests/log/test_zero_samples.py` (new: no existing file covers running an
  eval to edit a log). The fixture is a task file whose `Task.setup` sets a
  metadata flag and whose main solver would generate.
  - The happy path: the zeroed scores equal the empty attempt's (`I` for
    `match()`), with reason `zeroed` and the original in `history[0]`. The
    transcript and `error` are unchanged, `Task.setup` ran, and the scratch
    run has no main-solver `ModelEvent`.
  - An errored sample is zeroed.
  - Ids `case[1]`, `case*`, `case?` and `t1:a:b`, in a dataset that also
    holds `case1`, `caseX` and `a:b`: the scratch log holds only the
    targets.
  - A multi-epoch log with targets `a/1` and `b/2`: `a/2` runs in the scratch
    eval, and the sample is left unedited.
  - Refusals that leave the log unchanged:
    - a target missing from the dataset;
    - an empty attempt that errors;
    - an empty attempt whose only scorer returns
      `Score.unscored(reason="grader_failed")`;
    - two scorers, one scored and one unscored;
    - a conditional scorer that scored the original and returns `None` on the
      empty attempt;
    - a solver-written score;
    - an appended scorer;
    - an ephemeral task.
  - A scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
- `tests/_cli/`: `inspect log exclude|zero` parse `--sample`, `--epoch`,
  `--reason` and `--author`, write in place, and print the per-sample lines
  and the `--json` envelope.
- `tests/_control/test_cancel.py`, each row of the decision table through the
  route and the CLI:
  - **Running exclusion.** The record has excluded scores under every task
    scorer name and the solver-written key. The solver's score is in
    `history[0]`. The record has the operator limit and no error, and keeps
    its transcript. Live results count the sample unscored.
  - **Initializing exclusion.** It fires at start, and the plan does not run.
    A task-level score, error or drain arriving while the exclusion is
    stamped does not override it. An initialization error after the stamp
    resolves as for a stamped `score`.
  - **Boundary 409s.** An `exclude` sent during a scorer's await, during the
    task's `cleanup`, and during final logging (via a hook awaited there) is
    a 409, and the record is unaffected. So is an `exclude` sent while a
    fired limit is pending.
  - **Queued 409s.** A queued, queued re-run or cancelled-before-start
    sample, and a finished sample, are each a 409.
  - **Repeats.** A repeat `exclude` is `changed: false`, and so is a `score`
    after an `exclude` on a running sample.
  - **Reason param.** A missing `reason`, and a stray `reason` on another
    action, are each a 400.
- Schema drift: the OpenAPI and TypeScript drift checks pass after the
  regeneration step.

No test needs network or a provider key. A Docker sandbox variant of the
zero test is not needed: the `local` sandbox exercises the same provisioning
path.

## Implementation plan

1. **Vocabulary and shared edit helper.**
   - Add the two reasons to `ScoreReason` (`src/inspect_ai/scorer/_metric.py`).
   - Extract `apply_score_edit` in `src/inspect_ai/log/_score.py`.
   - Document the reasons in `docs/scoring-policy.qmd`'s reason table.
   - Regenerate `src/inspect_ai/_view/inspect-openapi.json` and the ts-mono
     types with the land-ts-mono procedure.

   Tests: the extraction regression.
2. **Exclude on landed logs.**
   - `src/inspect_ai/log/_disposition.py`: `SampleSelector`,
     `DispositionResult`, `exclude_samples` and the covered-names rule.
   - Exports in `src/inspect_ai/log/__init__.py`.
   - `inspect log exclude` in `src/inspect_ai/_cli/log.py`, with the default
     author helper moved from `src/inspect_ai/_cli/ctl/_config.py` to
     `src/inspect_ai/_cli/util.py`.
   - A "Zeroing and Excluding Samples" section in `docs/eval-logs.qmd`,
     including the retry behaviour.

   Tests as above.
3. **Zero on landed logs.**
   - `log_task_spec`, extracted in `src/inspect_ai/_eval/eval.py` and used by
     `eval_retry_async`.
   - `literal_sample_id` in `src/inspect_ai/_eval/task/util.py`.
   - `src/inspect_ai/_eval/zero.py`: `empty_attempt` and the scratch eval.
   - `zero_samples` / `zero_samples_async` in `_disposition.py`, with a
     function-local import of `_eval.zero`.
   - `inspect log zero`, and the docs section extended.

   Tests as above, plus the existing eval-retry tests unchanged.
4. **Live exclusion.**
   - In `src/inspect_ai/log/_samples.py`: `"exclude"` in `SampleCancelAction`,
     and on `ActiveSample` the `interrupt(..., provenance)`,
     `interrupt_provenance`, `end_solver()` and `solver_ended` members.
   - In `src/inspect_ai/_eval/task/run.py`: the `end_solver()` call, the
     `exclude` handler case, and the scoring branch.
   - In `src/inspect_ai/_control/cancel.py`: the decision table and the
     two-way first-resolution rule.
   - Route params in `src/inspect_ai/_control/server.py`, and CLI options in
     `src/inspect_ai/_cli/ctl/_sample.py`.
   - Docs: `docs/control-channel.qmd`, and the cancel table in
     `design/ctl/control-channel.md`.

   Tests as above.

## Open questions

- **Live exclusion refuses samples that have not started.** Without the
  refusal, a queued exclusion would be lost when a drain or graceful task
  resolution abandons the sample at the queue exit (`run.py:2565`). The
  alternative is to carry the exclusion on `_SampleRun` and have the queue
  exit materialize an excluded record without running the sample. That needs
  a new record path, plus changes to the sweep, the start-time check and the
  retry rules. Recommendation: refuse. `--action cancel` already takes a
  queued sample out of the run, and the sample can be excluded once it
  starts. Confidence: high.

## Future improvements

Left out of this design (decision: Ransom, 2026-11-04) and possible
additions later:

- **Scorer-declared zero values.** A scorer could declare its verdict for an
  empty attempt, either as a static value or as an optional hook, with the
  empty attempt as the fallback when the hook is absent or declines.
  - Benefit: it would make zero cheap where it is safe (no task reload, no
    sandbox).
  - Cost: it is a second path that scorer authors must keep in step with
    their scorer.
  - Limit: it is wrong for scorers whose verdict depends on the environment,
    such as sandbox tests and model graders.
- **Caller-supplied scorers for zero.** `zero_samples(..., scorers=...)` and
  `inspect log zero --scorer`, as `inspect score --scorer` does. This changes
  what a zero means away from the task's own verdict, and it needs naming
  rules for scores the task's scorers did not produce.
- **Live zero for queued and initializing samples** (`inspect ctl sample
  cancel --action zero`). The runner would resolve it at start by running a
  setup-only plan (`Task.setup` alone) and passing each scorer's result
  through the zero edit. It needs:
  - a disposition carried across `retry_on_error` re-parks;
  - the queue-exit abandonment (`run.py:2565`) honouring that disposition;
  - the task sweep and the start-time self-check protecting it while setup
    runs;
  - the unscored-verdict and uncovered-score refusals applied at scoring
    time;
  - a refusal once the solver has started.

## Not this design

- Moving Steward's `_marks` package onto `exclude_samples` / `zero_samples`,
  which would delete the side run, the watcher and the id workaround.
- A bulk ctl sweep (`inspect ctl sample cancel TASK --errored --action
  exclude`), as requeue has.
- An `excluded_samples` count on `EvalScore` beside `unscored_samples`, so a
  reader can tell exclusions from grader failures without reading reasons.
- Showing dispositions distinctly in the viewer: a badge for `excluded` /
  `zeroed`, and the provenance author and reason on the sample header.
- Applying a disposition to a finished sample of a running eval, which would
  rewrite a terminal record mid-run and update live results.
- An `inspect log invalidate`-style CLI for the existing re-run path.
- The existing `score|error|cancel` actions accept a running-row request
  during scoring, cleanup and logging, and target a solver task group that
  has already exited (`cancel.py:585`, `run.py:3113`). The `solver_ended`
  boundary introduced here could serve them too. Changing their answers is
  separate work.
