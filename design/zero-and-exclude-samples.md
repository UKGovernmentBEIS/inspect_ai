# Zeroing and excluding samples

## Overview

When an operator decides that a sample should not count the way the model ran
it, there are two answers: **zero** it (count it as a failure) or **exclude**
it (leave it out of the metrics). This design adds both to Inspect, for logs
that have landed.

- **Exclude** rewrites each of the sample's scores as
  `Score.unscored(reason="excluded")`. The value is `NaN`, which metrics
  already skip, and the explanation carries the operator's reason. Epoch
  reduction learns to drop excluded epochs before the reducer sees them, so
  an excluded epoch counts as one that never ran, and a sample with every
  epoch excluded is reduced to an excluded score.
- **Zero** gives each score the verdict the task's own scorers return for an
  **empty attempt** of the sample. The sample is started as for a run
  (sandbox, files, setup script, `Task.setup`), the task's main solver is
  skipped, and the scorers run on the untouched state. The score's `reason`
  becomes `"zeroed"`. A zero that cannot give the sample a counted score
  under every name it holds is refused, and the log is left unchanged.

Both keep the sample's transcript and error. Both record who decided and why
as score-edit provenance, so the earlier score stays in `Score.history`, and
both recompute the log's metrics. They are Python functions in
`inspect_ai.log` and two `inspect log` subcommands. Zero runs its empty
attempts in a scratch eval of the same task and copies the verdicts in.
Neither applies to a log that is still being written.

## Why

The task is meridianlabs-ai/inspect_ai#450. Inspect Steward already zeroes and
excludes samples, but it does so outside Inspect, with machinery that Inspect
can replace with something simpler and deterministic. Steward is an operator
layer over `eval_set` runs. An operator may rule that a class of failed or
flagged samples (a provider outage, a reward hack found by a scanner) should be
excluded from scoring or counted as failures. Once the task's log has landed,
Steward writes that ruling into it, so that every reader of the log directory
(the viewer, `inspect log` tools, dataframes) sees the result the operator
signed. Its user documentation describes the two dispositions in
`docs/errors.qmd:49-57` of meridianlabs-ai/inspect_steward.

What Steward does, and what it costs:

- **Exclude** is a score edit and works well. It needs nothing from Inspect
  beyond `edit_score()`, `Score.unscored()`'s `NaN` sentinel and
  `recompute_metrics()`. It misses two cases:
  - An errored sample with no scores is given an unscored score only under
    the task's *first* scorer, so a multi-scorer task's other metrics still
    count it as missing rather than unscored.
  - An excluded epoch still reaches the epoch reducer, and not every reducer
    skips `NaN` (see "Epoch reduction" below).
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
the runner can do deterministically.

## Goals and non-goals

Goals:

- Exclude a sample of a landed log. Every score the sample holds, and every
  score name the log's scorers write, becomes unscored with reason
  `"excluded"`. The edit records provenance, and metrics are recomputed. An
  excluded epoch takes no part in epoch reduction.
- Zero a sample of a landed log. Every score the sample holds becomes the
  counted verdict on an empty attempt, with reason `"zeroed"`. The edit
  records provenance, and metrics are recomputed.
- One empty-attempt definition: the sample is initialized as for a run,
  `Task.setup` runs, the main solver is skipped, and the task's scorers run.
- `"excluded"` and `"zeroed"` join the standard `ScoreReason` vocabulary.

Non-goals:

- Zeroing or excluding a sample of a running eval (see Future improvements).
  During a run, `inspect ctl sample cancel --action cancel` stops a sample and
  keeps its transcript in the log; the operator zeroes or excludes it with
  `inspect log zero|exclude` once the log lands. Steward has no live
  equivalent either: it applies both only after a task's log has landed.
- Steward's other rulings (`rerun`, `accept`, `score`, `dismiss`), and its
  journal, anomaly classes and sign-off. Re-running is already covered by
  `inspect ctl sample requeue` and by eval-retry with sample invalidation.
- Changing a sample's `error`, the log's `status`, or which samples an
  eval-set retry re-runs (decision: Ransom, 2026-11-04; see Compatibility).
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
  explanation, reason="zeroed", metadata, provenance))`. The copied value is
  not checked, so an unscored side-run verdict becomes a `zeroed` `NaN`. A
  side-run sample with no scores is deferred (`:269`).
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
`reason: "zeroed"`. The sample counts in the denominator when that value is
counted.

### Inspect primitives this design builds on

- **Unscored values.** `Score.unscored()` (`src/inspect_ai/scorer/_metric.py:178`)
  sets `value` to `NaN`. Metrics count a score as unscored when its value is
  a float `NaN` at the root (`scorer_for_metrics`,
  `src/inspect_ai/_eval/task/results.py:409`). For a dict-valued score with
  dict metrics, a `NaN` under a metric's key is unscored for that metric
  alone (`results.py:521-535`). A score `{"x": NaN}` therefore records
  `scored_samples=0, unscored_samples=1` for `x`. Scorers produce such values
  themselves:
  - `model_graded_*` returns `Score.unscored(reason="grader_failed")` when the
    grade is missing from the grader's output
    (`src/inspect_ai/scorer/_model.py:370`).
  - inspect_evals' HLE scorer returns `{"score": NaN, "confidence": 100}` on a
    grading failure (`inspect_evals/hle/scorers.py:131`).

  The semantics are documented in [Scoring policy](../docs/scoring-policy.qmd)
  and [Unscored Samples](../docs/custom-scorers.qmd#unscored-samples).
- **`ScoreReason`** (`src/inspect_ai/scorer/_metric.py:49`) is a `Literal` of
  five standard reasons. `Score.reason` is typed `ScoreReason | str | None`,
  so any string is accepted. The literal is exported to
  `src/inspect_ai/_view/inspect-openapi.json` (the `enum` beside `string`),
  and from there to the viewer's generated types. The viewer renders the
  reason as plain categorical text (`ScoreEventView.tsx` in ts-mono).
- **`edit_score()`** (`src/inspect_ai/log/_score.py:13`) applies a `ScoreEdit`
  to one score of one sample (`:88-145`).
  - When the score is absent it creates it, with `history=[edit]`.
  - Otherwise it records the original as `history[0]` before applying the
    edit. A field the edit leaves `UNCHANGED` keeps its value: a later
    `ScoreEdit(value=1)` on an excluded score keeps `reason="excluded"` while
    the value is counted (`:132`).
  - It inserts a `ScoreEditEvent` into the scorers span.
  - With `recompute_metrics=True` it resolves metrics *before* mutating, so a
    missing metric leaves the log unchanged.

  Documented in [Editing Logs](../docs/eval-logs.qmd#sec-eval-log-modification).
- **`recompute_metrics()`** / `resolve_log_metrics()` / `compute_log_metrics()`
  (`src/inspect_ai/log/_metric.py:136`, `:28`, `:88`) rebuild `results` from
  every sample that has scores, errored or not. `resolve_log_metrics()`
  rebuilds metrics and reducers from the log header. Without `trust_log` it
  imports nothing and refuses metric options that name a model or a
  non-metric registry object (`metric_from_log`,
  `src/inspect_ai/_eval/score.py:833`); with it, the log's task file is
  imported and options are rebuilt without that restriction. `inspect score`
  passes trusted resolution when it runs the log's own scorers (`score.py:342`).
  I verified recomputation with a three-sample, two-scorer `mockllm` eval with
  one errored sample. Excluding the errored sample and one scored sample,
  with `NaN` edits on both scorers, gave `scored_samples=1,
  unscored_samples=2` per scorer and `completed_samples=2`. A log scored
  only by a solver, with task-level metrics and `log.eval.scorers` `None`,
  also recomputes.
- **Epoch reduction.** `reduce_scores()` (`results.py:703`) groups a scorer's
  scores by sample id and calls the epoch reducer on each group, also when
  there is one epoch (the default reducer is `mean`). It is the only caller
  of reducers on final scores, live and in `compute_log_metrics()`. The
  built-in reducers treat a root `NaN` in two ways:
  - `mean`, `median`, `mode`, `max`, `at_least`, `pass_at`, `pass_k` and
    `collect` omit it.
  - `majority` counts it toward the panel size on purpose
    (`src/inspect_ai/scorer/_reducer/reducer.py:41-60`), so a grader that
    fails withholds its vote without lowering the bar. Today, excluding one of
    two correct epochs reduces the sample from `C` to `NaN`, where dropping
    the epoch would leave `C` (verified by running the reducer).

  Custom reducers vary. In inspect_evals (at 4d879c906), HLE's reducer
  delegates to `mean`, MASK's and Fortress's pass a single root `NaN` through,
  and ZeroBench's `reliability_at(5)` counts a `NaN` epoch as a failed one, so
  five excluded epochs reduce to a counted `0.0`
  (`zerobench/reducer.py:15-40`, configured at `zerobench.py:150`).
- **Score names:**
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
    and the eval results after them (`run.py:3273`). A task may have no
    scorers at all and rely on these, with task-level metrics
    (`tests/scorer/test_score_editing.py:553`).
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
- **`inspect score`** / `score_async` (`src/inspect_ai/_eval/score.py:234`)
  rebuild a `TaskState` from the logged `EvalSample`
  (`task_state_from_sample`, `:464`) and run scorers on it, with no sandbox.
  A logged `EvalSample` carries only the names of the sample's `files`, so a
  sample's sandbox cannot be rebuilt from the log. Rebuilding it needs the
  task's dataset.
- **`eval_retry_async`** (`src/inspect_ai/_eval/eval.py:1580`) reconstructs a
  runnable task from a log:
  - the task spec, from `task_file` and `task_registry_name`
    (`:1781-1803`, with its errors for unregistered package tasks);
  - the model, constructed at once with `get_model()` from the recorded name,
    generate config, base URL and model args (`:1817-1822`);
  - the model roles, constructed at once by
    `model_roles_config_to_model_roles()` (`:1825`,
    `src/inspect_ai/model/_model_config.py:40`);
  - `task_args_passed`;
  - the sandbox (`resolve_task_file_sandbox`).

  Constructing a model checks its provider's credentials. `get_model("openai/gpt-4o")`
  raises without `OPENAI_API_KEY` (`src/inspect_ai/model/_providers/openai.py:257`),
  and so does constructing a recorded role on that provider (both verified).
- **Sample-id selection** goes through two steps:
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
- **`resolve_plan()`** (`src/inspect_ai/_eval/task/run.py:674`) prepends
  `Task.setup` to whatever solver is in effect (`:685-692`). `Task.setup` is
  documented as "always run even when the main `solver` is replaced".
  I verified this with a `mockllm` task. `eval(task, solver=<solver returning
  state unchanged>, sample_id=["t1:a:b"])` ran the setup solver (it set a
  metadata flag) and skipped `system_message()` and `generate()`. It then
  scored the empty output `I` under `match()` and `includes()`.
- **Epochs.** A global `epochs=N` runs every selected sample for epochs 1
  through N (`run.py:2011`). There is no per-sample epoch selection.
- **Retry reuse.** A prior record is reused only when `error is None` and
  `invalidation is None` (`classify`, `src/inspect_ai/_eval/task/run.py:3886`).
  An errored sample that also has scores (today, through `score_on_error`) is
  therefore re-run by `inspect eval-retry` and by eval-set retries.
- **Stopping a running sample.** `inspect ctl sample cancel --action cancel`
  records a running sample as cancelled. Its transcript is kept in the log
  and it is not scored ([Control Channel](../docs/control-channel.qmd)).

### Who uses which shapes

The only existing producer of zero and exclude is Steward. It works on landed
`.eval` logs of tasks loaded from a file or the registry, with static datasets
whose samples have ids. Searching inspect_ai, inspect_scout, inspect_flow and
inspect_swe for the reasons `excluded` / `zeroed` finds no other producer or
reader, and the viewer shows any reason string as text. The design therefore
supports:

- zero for tasks that eval-retry can reload (file or registered) and that
  have scorers, samples the task's dataset still holds, and samples whose
  scores all come from the task's scorers;
- exclusion for any landed log that names at least one score: from its
  results, its samples or its scorers.

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

Two predicates sit beside it in `src/inspect_ai/scorer/_metric.py`, used by
epoch reduction and by the disposition functions:

```python
def score_is_excluded(score: Score) -> bool:
    """`reason == "excluded"` and the value is a float NaN at the root."""

def score_value_is_counted(value: Value) -> bool:
    """No float NaN at the root, among a dict's values, or among a list's elements."""
```

`score_value_is_counted` is the rule for a value that every metric over it
counts. It is stricter than the metrics, which count a dict's finite keys
even when another key is `NaN`. A zero requires the stricter rule, so that a
zeroed sample is in the denominator of every metric of its scorer.

Every disposition is a `ScoreEdit` carrying a `ProvenanceData` (author and a
non-empty reason), applied with `edit_score(..., recompute_metrics=False,
epoch=...)`:

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

### Epoch reduction

`reduce_scores()` (`src/inspect_ai/_eval/task/results.py:703`) drops the
scores for which `score_is_excluded()` holds from each sample's group before
calling the reducer:

- When some remain, the reducer sees only those. The sample reduces as if the
  excluded epochs had not run, whatever the reducer does with `NaN`.
  `majority` over `[C, excluded]` reduces to `C` (verified by running the
  reducer on `[C]`), and its treatment of a grader's `NaN` is unchanged,
  because only the `"excluded"` reason is dropped.
- When none remain, the reducer is not called, and the reduced score is the
  group's first excluded score. The sample counts as unscored, and a reducer
  that would turn `NaN` epochs into a counted value (ZeroBench's
  `reliability_at`) never sees them.

A reducer that depends on the number of epochs sees the remaining ones.
`reliability_at(5)` over four remaining epochs returns its own answer for
four epochs (`0.0`), which is what dropping the epoch means.

This is the one change outside the disposition functions. It applies wherever
final scores are reduced, live and on recompute, so a scorer that itself
returns `Score.unscored(reason="excluded")` gets the same treatment. Today
only Steward writes that reason.

### Which score names a disposition covers

**Exclude** covers the sample's own score keys plus each *log score name*
the sample lacks. The log score names are the ordered, de-duplicated union of
three sets:

1. the `EvalScore.scorer` of every entry in `log.results.scores`, which holds
   each configured scorer as the runner named it (including one that scored
   no sample), each solver-written key and each appended key;
2. every score key of every sample in the log;
3. when `log.results` is `None` (no sample scored), `unique_scorer_name()`
   applied in order to the `log.eval.scorers` names. This is the runner's
   derivation (`run.py:1162-1166`). It is used only in this case, because an
   appended log has results and its appended entries are not named this way.

An excluded errored sample is therefore unscored under every scorer, not only
the first. That includes a scorer that never produced a score for any sample,
and the solver-written key of a log with no task scorers. A target whose
covered set is empty (the log names no score at all) is refused: "sample
<id> (epoch <n>) has no score to exclude: the log records no scorer and no
score".

**Zero** edits exactly the names the empty attempt scored. A target is
refused, before anything changes, in three cases:

- **No verdict.** The empty attempt produced no score: every scorer returned
  `None`. Message: "the empty attempt of sample <id> (epoch <n>) produced no
  score; exclude it instead".
- **Unscored verdict.** A score of the empty attempt fails
  `score_value_is_counted()`: a root `NaN` (a grader failure), or a `NaN`
  among a dict's or list's values (HLE's `{"score": NaN, ...}`), whether the
  other values are finite or not. Copying it would label a sample `zeroed`
  that some metric leaves out of its denominator. This holds whether every
  scorer's verdict is unscored or only one. Message: "the empty attempt of
  sample <id> (epoch <n>) was not scored by <name> (<reason>:
  <explanation>); zero it again, or exclude it".
- **Uncovered score.** The sample holds a score under a name the empty attempt
  did not produce. Examples: a scorer that returned `None` on the empty
  attempt but scored the original, a solver-written score, a scorer appended
  with `inspect score --action append`, or a scorer removed from the task
  since. Leaving that score would keep the original verdict on a sample
  reported as zeroed. Message: "sample <id> (epoch <n>) holds scores the empty
  attempt does not produce (<names>); exclude it instead".

A log score name that the sample does not hold, and that the empty attempt
did not produce, stays absent, as the runner would leave it.

**Idempotence.** A target that already carries the disposition is reported
unchanged and not edited again. Carrying it means its invariant holds, not
only its reason:

- **Exclude:** every covered name is present and `score_is_excluded()` holds
  for it.
- **Zero:** the sample holds at least one score, and every score it holds has
  reason `"zeroed"` and a value for which `score_value_is_counted()` holds.
  Zero spends no empty attempt on such a target.

A target whose reason and value disagree is not unchanged, and it is
disposed again like any other target. Examples are an excluded score given a
counted value by a later `edit_score(..., ScoreEdit(value=1))`, which keeps
the reason, or a Steward zero that copied a `NaN` verdict. The new edit is
appended to the score's history, and a zero applies its refusals as usual.

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

### Python API

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
  The message says to run the command once the eval finishes.
- `provenance.reason` must be a non-empty string. It is the explanation an
  exclusion records and the only record of why a zero was applied.
- Every selector must match.
  - A bare id matches every epoch of that id.
  - An `(id, epoch)` pair must name a sample in the log.
  - Ids match by value. A string selector also matches an `int` id whose
    `str()` equals it, because the CLI passes strings.
  - A selector that matches two distinct ids is an error.

  Unmatched selectors are a `ValueError` naming them.
- Metrics are resolved before the first edit (`resolve_log_metrics()`). A log
  whose metrics cannot be rebuilt is therefore left unchanged, with the
  existing `LookupError` or `DisallowedRegistryArg` and its advice. After the
  edits, `compute_log_metrics()` runs once.

`exclude_samples`:

1. Resolves metrics with the caller's `trust_log`, as `recompute_metrics()`
   does. A log with no task scorers is accepted; it is refused only for a
   target with no covered name.
2. Builds the exclusion edits for the covered names of every target that is
   not already excluded, applies them, and recomputes.

`zero_samples_async`:

1. Requires `log.eval.scorers` to be non-empty. A log with no task scorers
   has no verdict to copy: "the task of <log> has no scorers, so an empty
   attempt has no verdict; exclude the samples instead".
2. Resolves metrics with `trust_log=True`. Zero imports and runs the task's
   code, exactly as `inspect eval-retry` does, so the caller has already
   decided to trust the log. With trusted resolution, the log's task file is
   imported and metric options naming a model or solver rebuild, as they do
   when `inspect score` runs the log's own scorers. The docstring, CLI help
   and docs say to zero only logs you trust.
3. Selects the targets that are not already zeroed.
4. Reconstructs the task as eval-retry does. The task-spec resolution
   (`src/inspect_ai/_eval/eval.py:1781-1803`) and the recorded model
   configuration move into helpers that both call. The spec holds the
   recorded models as configurations, not as constructed models, so an
   override replaces a recorded model before anything constructs it:

   ```python
   # src/inspect_ai/_eval/eval.py
   class LogTaskSpec(NamedTuple):
       task: str                     # "<file>@<name>" or a registry name
       task_args: dict[str, Any]
       sandbox: SandboxEnvironmentType | None
       model: ModelConfig            # eval.model, model_generate_config, model_base_url, model_args
       model_roles: dict[str, ModelConfig | list[ModelConfig]] | None   # eval.model_roles

   class LogTaskModels(NamedTuple):
       model: Model
       model_roles: ModelRoles | None

   def log_task_spec(eval_log: EvalLog) -> LogTaskSpec: ...

   def log_task_models(
       spec: LogTaskSpec,
       model: str | Model | None = None,
       model_roles: ModelRoles | None = None,
   ) -> LogTaskModels: ...
   ```

   `log_task_models` constructs only what is not overridden:
   - the primary model: `model` resolved with `get_model()` when given,
     otherwise the recorded configuration, constructed with the same
     `get_model(model=..., config=..., base_url=..., **args)` call eval-retry
     makes today;
   - the roles: every role in `model_roles` as given (`eval_async` resolves
     them), and every recorded role not named there, constructed and labelled
     with its role as `model_roles_config_to_model_roles()` does.

   A recorded model whose provider is unavailable (no credentials, no SDK) is
   therefore never constructed when the caller overrides it. Eval-retry calls
   `log_task_models(spec)` with no overrides and constructs exactly what it
   constructs today. A task that is neither in a task file nor registered
   raises the same `FileNotFoundError` that eval-retry raises.
5. Runs one scratch eval in a temporary local directory:

   ```python
   eval_async(
       tasks=spec.task,
       task_args=spec.task_args,
       model=models.model, model_roles=models.model_roles,
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
     both `"12"` and `12` runs both. Step 6 matches by value and ignores the
     extra one.
   - **Epochs.** `epochs` is global, so every targeted id runs every epoch up
     to the highest targeted one. Targets `a/1` and `b/2` also run `a/2` and
     `b/1`. Those extra empty attempts provision their sandboxes and run
     `Task.setup` and the scorers like any other. Their results are ignored,
     and they are not edited. A caller who zeroes widely spread epochs of
     different ids can split the call to avoid the cost.
   - **Scratch log.** It is read back whole and the directory removed.
6. For every target, requires a scratch sample with the same `(id, epoch)`
   and no `error`, then applies the zero refusals under "Which score names a
   disposition covers". Any failure raises, naming every failing target and
   its cause, without editing anything. A missing scratch sample reads "the
   empty attempt of sample <id> (epoch <n>) did not run: the task's dataset no
   longer holds it". An errored one reads "...did not score: <error>". This is
   atomic where Steward's was not required to be: nothing is half-applied.
7. Applies the zero edits and recomputes metrics once.

`zero_samples` is the synchronous wrapper. It initializes the display type
from `display` and runs the coroutine, as `score()` does: `anyio.run` with
the configured backend, or `run_coroutine` in a notebook.

### CLI

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
  `ctl config` helper (`_default_provenance_author`,
  `src/inspect_ai/_cli/ctl/_config.py:860`), moved to a shared CLI utility.
- The command reads the log whole, applies the function, and writes the log
  back in place with `write_eval_log(log, location, if_match_etag=log.etag)`.
  A concurrent rewrite of an S3 log therefore fails with `WriteConflictError`
  instead of being overwritten. When nothing changed, nothing is written.
- Output: one line per sample (`excluded` / `zeroed` / `unchanged`) and the
  recomputed headline metric. `--json` prints
  `{"log": ..., "applied": [[id, epoch], ...], "unchanged": [...]}`.

### Errors and edge cases

- **Selectors and ids.** Ids are matched against the log only, never
  interpreted. For zero's scratch eval, ids are escaped and re-qualified so
  that selection is literal.
- **Changed dataset.** Suppose a task's dataset changed so that a targeted
  sample no longer exists, or its samples come from a `SampleSource` feed
  that no longer yields it. Zero then fails step 6 with that said, and
  nothing is edited.
- **Edited task file.** A task file edited since the log was written runs as
  edited, as eval-retry does. The scratch log is not kept, but the zero edits
  record the scorer's answer and explanation for the empty attempt.
- **Concurrency.** The functions are synchronous over an in-memory log,
  except zero's scratch eval, which runs before any edit. The CLI's write is
  a conditional write on S3 and last-writer-wins locally, as `edit_score()`
  plus `write_eval_log()` is today.
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
- **Leave epoch reduction alone, and refuse an exclusion the log's reducer
  would mishandle.** Inspect cannot tell, from a reducer, whether it skips
  `NaN`; it would need a list of reducers known to be safe, and it would
  refuse ordinary cases (one epoch of a `majority` panel). Dropping excluded
  epochs before any reducer runs is one rule for every reducer, and it
  leaves `majority`'s treatment of grader failures as it is.
- **Exclude by removing the sample**, as cancel-before-start does. Metrics
  would silently change denominators, and the record of the decision would be
  gone. `NaN` keeps the sample visible and counted as unscored.
- **A new `EvalSample.disposition` field.** Every reader would have to learn
  it: the viewer, dataframes, retry reuse, Scout. A score `reason` already
  flows through metrics, `score_<name>_reason` dataframe columns and the
  viewer.

## Compatibility and migration

No migration required.

- **Score reasons.** `ScoreReason` gains `"excluded"` and `"zeroed"`. Logs
  are unchanged in shape: older Inspect reads these values as the plain
  strings `Score.reason` already admits. The OpenAPI schema
  (`src/inspect_ai/_view/inspect-openapi.json`) and the viewer's generated
  TypeScript types change (an enum widens), which needs the coordinated
  ts-mono regeneration. The viewer already renders any reason string.
- **Epoch reduction.** A score with reason `"excluded"` and a root `NaN` no
  longer reaches the epoch reducer, live or on recompute. Producers of that
  shape: these functions, and Steward's exclusions. For Steward's logs the
  recomputed results change only under a reducer that does not omit `NaN`:
  `majority` with a partly excluded sample, which now reduces over the
  remaining epochs, and a custom reducer such as ZeroBench's, whose fully
  excluded samples now read as unscored instead of `0.0`. Other `NaN`
  scores, such as `grader_failed`, reach the reducer as before. Consumers of
  reductions (`log.reductions`, `results`, dataframes, the viewer) read the
  same structures.
- **Log contents.** Dispositions write existing structures only:
  - `Score` fields;
  - `Score.history` entries with `ProvenanceData`;
  - `ScoreEditEvent`s;
  - recomputed `results` / `reductions`.

  Readers of score history (the viewer, `EvalSample` consumers, Steward's
  `marked_by`) see ordinary edits.
- **Public Python API.** New in `inspect_ai.log`: `exclude_samples`,
  `zero_samples`, `zero_samples_async`, `DispositionResult` and
  `SampleSelector`. `edit_score()` and `recompute_metrics()` are unchanged.
- **CLI.** New `inspect log exclude` and `inspect log zero`. `inspect ctl` is
  unchanged.
- **Eval-retry.** Its task and model reconstruction moves into
  `log_task_spec()` and `log_task_models()`, with the same results and the
  same errors.
- **Eval-set retry.** Unchanged (decision: Ransom, 2026-11-04). A disposition
  does not clear `error`. An errored sample that was zeroed or excluded is
  therefore re-run by `inspect eval-retry` and eval-set retries, and the new
  record replaces the disposition, as with an errored sample scored under
  `score_on_error` today. The `inspect log` help and the docs section say so.
- **Steward.** Its edits keep working. Its `"excluded"` / `"zeroed"` strings
  are the new standard reasons, so its logs read the same as Inspect's. A
  Steward zero that copied a `NaN` verdict is not treated as zeroed: zeroing
  it again runs an empty attempt.

## Security

- **Log contents** (the `log.eval` task file, task name, args, scorer and
  metric specs) are untrusted when the log is. `exclude_samples` imports
  nothing unless `trust_log=True` (metric resolution, as `recompute_metrics()`
  does it). `zero_samples` imports and runs the task, like
  `inspect eval-retry`, and resolves the log's metrics trusted. The
  docstring, CLI help and docs say to zero only trusted logs. There is no new
  code-execution path beyond eval-retry's.
- **Reason and author** are free text from the local caller: the Python
  caller or the CLI user. They are stored as data in `ProvenanceData` and
  `Score.explanation`, and the viewer renders explanations as it renders any
  scorer's explanation. They are not interpolated into commands or paths.
- **Sample selectors** are compared with logged ids and never become paths or
  queries. The scratch eval's sample ids are escaped so that the runner's
  selection matches them literally. An id therefore cannot widen the scratch
  run to other samples, which would run their setup, sandboxes and graders.
- **Model output, tool output and sandbox output** reach a zero only through
  the task's own scorers in the empty attempt, exactly as in an eval run.
- **Scratch directory.** It is a fresh `tempfile.TemporaryDirectory`, removed
  after the scores are read.

## Testing

Pure and `mockllm` tests run in the default suite. Async tests run under both
backends; run the zero tests with `--runtrio` locally.

- `tests/scorer/test_reducers.py` (epoch reduction through `reduce_scores`):
  - `majority` over `[C, C-excluded]` reduces to `C`, and over `[C,
    grader_failed]` still reduces to `NaN`.
  - A test reducer that turns `NaN` epochs into a counted `0.0` (modelled on
    ZeroBench's `reliability_at`) is not called for a sample with every epoch
    excluded; the sample reduces to the excluded score and counts unscored.
  - `mean` gives the same result with and without an excluded epoch.
- `tests/scorer/test_score_editing.py`:
  - `exclude_samples`, on a multi-scorer sample with a deduplicated name
    (`match1`), an appended one and a solver-written one: every score
    becomes `NaN` with reason, explanation and provenance. `history[0]` is
    the original, and `answer` and `metadata` are unchanged.
  - `exclude_samples` on an errored sample: it is unscored under every log
    score name. That includes a configured scorer that scored no sample, the
    solver-written key, and, on a log with no results, every name derived
    from `log.eval.scorers`.
  - `exclude_samples` on a solver-only log with task-level metrics
    (`log.eval.scorers` `None`): the solver key is excluded and metrics
    recompute. A log that names no score refuses the target.
  - Metrics recompute: `accuracy` over the rest, and `unscored_samples`
    counted.
  - Selection: a bare id covers every epoch, and an `(id, epoch)` pair covers
    one. A repeat reports the target `unchanged`.
  - Idempotence holds only with the invariant: an excluded score later given
    `ScoreEdit(value=1)` is excluded again, not reported unchanged.
  - Refusals that raise and leave the log unchanged: unknown selectors, a
    `started` log, an empty reason, and an unresolvable metric.
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
  - Models: a log whose recorded model is `openai/gpt-4o`, zeroed with
    `OPENAI_API_KEY` unset and `model="mockllm/model"`, succeeds; so does a
    log with a recorded `openai` role overridden by a `mockllm` role.
  - A metric whose options name a model resolves.
  - A sample whose `zeroed` score holds `NaN` (a Steward zero) is zeroed
    again rather than reported unchanged.
  - Refusals that leave the log unchanged:
    - a target missing from the dataset;
    - an empty attempt that errors;
    - an empty attempt whose scorers all return `None`, on an errored sample
      with no scores;
    - an empty attempt whose only scorer returns
      `Score.unscored(reason="grader_failed")`;
    - an empty attempt whose scorer returns `{"x": NaN}`, and one returning
      `{"x": 0, "y": NaN}`;
    - two scorers, one scored and one unscored;
    - a conditional scorer that scored the original and returns `None` on the
      empty attempt;
    - a solver-written score;
    - an appended scorer;
    - a log with no task scorers;
    - an ephemeral task.
  - A scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
- `tests/test_eval.py`: the existing eval-retry tests pass unchanged after
  the reconstruction moves into `log_task_spec()` and `log_task_models()`.
- `tests/_cli/`: `inspect log exclude|zero` parse `--sample`, `--epoch`,
  `--reason` and `--author`, write in place, and print the per-sample lines
  and the `--json` envelope.
- Schema drift: the OpenAPI and TypeScript drift checks pass after the
  regeneration step.

No test needs network or a provider key. A Docker sandbox variant of the
zero test is not needed: the `local` sandbox exercises the same provisioning
path.

## Implementation plan

1. **Vocabulary and epoch reduction.**
   - Add the two reasons, `score_is_excluded` and `score_value_is_counted` to
     `src/inspect_ai/scorer/_metric.py`.
   - Drop excluded epochs in `reduce_scores()`
     (`src/inspect_ai/_eval/task/results.py`).
   - Document the reasons in `docs/scoring-policy.qmd`'s reason table, and
     the reduction rule under "Reducing Epochs" in `docs/metrics.qmd`.
   - Regenerate `src/inspect_ai/_view/inspect-openapi.json` and the ts-mono
     types with the land-ts-mono procedure.

   Tests: the reducer tests.
2. **Exclude.**
   - `src/inspect_ai/log/_disposition.py`: `SampleSelector`,
     `DispositionResult`, `exclude_samples` and the covered-names rule.
   - Exports in `src/inspect_ai/log/__init__.py`.
   - `inspect log exclude` in `src/inspect_ai/_cli/log.py`, with the default
     author helper moved from `src/inspect_ai/_cli/ctl/_config.py` to
     `src/inspect_ai/_cli/util.py`.
   - A "Zeroing and Excluding Samples" section in `docs/eval-logs.qmd`,
     including the retry behaviour and, for a running eval, `inspect ctl
     sample cancel --action cancel` followed by these commands once the log
     lands.

   Tests as above.
3. **Zero.**
   - `log_task_spec`, `log_task_models` and their types, extracted in
     `src/inspect_ai/_eval/eval.py` and used by `eval_retry_async`.
   - `literal_sample_id` in `src/inspect_ai/_eval/task/util.py`.
   - `src/inspect_ai/_eval/zero.py`: `empty_attempt` and the scratch eval.
   - `zero_samples` / `zero_samples_async` in `_disposition.py`, with a
     function-local import of `_eval.zero`.
   - `inspect log zero`, and the docs section extended.

   Tests as above, plus the existing eval-retry tests unchanged.

## Open questions

None.

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
- **Live exclusion** (`inspect ctl sample cancel --action exclude`), for a
  sample of a running eval. The runner would write excluded scores in place
  of running the scorers. It needs:
  - a fixed end to the solver phase, after which an exclusion is refused,
    including when initialization fails before the sample starts;
  - first-resolution protection of the stamped exclusion at the common
    interrupt boundary (`ActiveSample.interrupt()`), which ctl, ACP and the
    TUI all call;
  - a terminal record for an exclusion that races a solver error with
    retries left;
  - a rule for samples that have not started, which a drain or graceful task
    resolution abandons at the queue exit (`run.py:2565`).
- **Live zero** (`inspect ctl sample cancel --action zero`), for queued and
  initializing samples. The runner would resolve it at start by running a
  setup-only plan (`Task.setup` alone) and passing each scorer's result
  through the zero edit. Beyond what live exclusion needs, it needs a
  disposition carried across `retry_on_error` re-parks, and the zero
  refusals applied at scoring time.

## Not this design

- Moving Steward's `_marks` package onto `exclude_samples` / `zero_samples`,
  which would delete the side run, the watcher and the id workaround.
- An `excluded_samples` count on `EvalScore` beside `unscored_samples`, so a
  reader can tell exclusions from grader failures without reading reasons.
- Showing dispositions distinctly in the viewer: a badge for `excluded` /
  `zeroed`, and the provenance author and reason on the sample header.
- An `inspect log invalidate`-style CLI for the existing re-run path.
