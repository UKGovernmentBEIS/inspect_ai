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
attempts in a scratch eval of the same task, with the log's recorded
models, and copies the verdicts in.
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
    `results.py:586-588`). They hold every configured scorer that has
    metrics, including one that scored no sample, and every solver-written
    key. I verified both with a two-sample `mockllm` eval. One scorer always
    returned `None`, a solver wrote `solver_score`, and one sample errored.
    The results held `probe`, `probe1` (0 scored, 0 unscored) and
    `solver_score`. The errored sample held no keys. A scorer with
    `metrics=[]` has no row when epoch reduction is enabled
    (`results.py:213`), so a configured scorer with no metrics that never
    returns a score appears neither in the results nor in any sample.
    inspect_evals' BFCL prerequisite scorer is one (`metrics=[]`, always
    `None`, `bfcl/prereqs.py:169`).
  - **No sample scored.** When every sample errored, `log.results` is `None`
    (verified, with `fail_on_error` both off and on).
  - **Appended scorers.** `inspect score --action append` appends to
    `log.eval.scorers` (`src/inspect_ai/_eval/score.py:443`). It names each
    appended scorer per sample, with `unique_scorer_name()` over the keys
    that sample already holds (`score.py:556`), then adds a `-N` suffix on a
    remaining collision (`score.py:176`). So a sample that lacked an earlier
    key can hold an appended score under a different key from its
    neighbours, and `log.eval.scorers` alone does not name every key of an
    appended log.
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
- **Task resolution.** `eval_resolve_tasks()` (`src/inspect_ai/_eval/eval.py:2086`)
  installs the model roles and then, per model, the active model before it
  constructs tasks (`:2104-2119`), so a task factory can call `get_model()`
  or read a role. `eval_async` calls it in its own child task, and
  `eval_set()` calls it to resolve tasks before passing the `ResolvedTask`s
  to `eval()` (`src/inspect_ai/_eval/evalset.py:1052`, `:551-554`).
- **Sample ids.** A dataset sample without an id gets its 1-based position as
  its id when the task runs (`src/inspect_ai/_eval/run.py:222-228`), after
  any `sample_shuffle` (`src/inspect_ai/_eval/loader.py:106`).
- **Epoch reducers on recompute.** `resolve_log_metrics()` builds the epoch
  reducers before it considers importing the task file for missing metrics
  (`src/inspect_ai/log/_metric.py:64`).
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
  have scorers, run with the log's recorded models; datasets whose samples
  carry their own ids; samples the task's dataset still holds; and samples
  whose scores all come from the task's scorers;
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

`score_value_is_counted` is the rule for an epoch score that every metric
over it counts. It is stricter than the metrics, which count a dict's finite
keys even when another key is `NaN`. A zero requires the stricter rule, so
that each zeroed epoch score is counted, under every key, by the metrics
that read epoch scores. It is a check on raw values only:

- Whether the verdict fits the log's metrics (a scalar where a dict metric
  expects a dict, after the task changed) is checked by computing the
  metrics on staged edits before they are committed (see Python API).
- A reduced sample score is whatever the configured epoch reducer makes of
  its epochs, as for any run. `majority` over finite `[I, C]` is unscored,
  because neither value has a majority. Zero does not change reducer
  semantics, and it does not promise that the reduced score is counted.

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
3. names for configured scorers that hold no key, added only where the log
   determines them, as below.

Sets 1 and 2 are the keys the log actually holds, so every appended key is
covered as written, including one that `inspect score --action append`
named differently on one sample. Set 3 exists for a configured scorer that
wrote nothing anywhere and has no result row: a scorer with `metrics=[]`
that always returns `None` (BFCL's prerequisite scorer), alone or beside
other scorers. It is built per base name. For each registry name `n` in
`log.eval.scorers`, let `k` be the number of entries named `n`, and `R` the
held keys (sets 1 and 2) that `unique_scorer_name()` or append could have
given such a scorer: `n`, `n` followed by digits, and `n-` followed by
digits.

- `len(R) >= k`: every entry is represented; set 3 adds nothing for `n`.
  An appended scorer that took a vacant key (an original `probe` that
  never scored, and an appended `probe` written under `probe`) adds no
  invented `probe1`.
- `R` is empty: no scorer named `n` wrote anything, so there is no appended
  key to conflict with. Set 3 adds the runner's names for those `k` entries,
  `unique_scorer_name()` in order (`run.py:1162-1166`): `n`, `n1`, ...
- `0 < len(R) < k`: the log cannot tell which entries the held keys belong
  to, so the name a silent entry would use is unknown. Exclusion refuses,
  before anything changes: "the log has <k> scorers named <n> but scores
  only under <R>; exclude cannot tell which name the others would use".
  This needs two scorers of one name, one of which never scored, so it is
  rare, and refusing is safer than writing a score under a guessed name.

A scorer without metrics affects no metric, so set 3 changes no result. It
keeps the promise that an excluded sample is unscored under every scorer.

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
- **Zero:** the sample holds at least one score, and for every score it
  holds, the last entry of `Score.history` is an edit with reason
  `"zeroed"` and provenance, and `score_value_is_counted()` holds for the
  value. `edit_score()` appends every edit to the history, so the last entry
  is the most recent edit. A later `ScoreEdit(value=1)` keeps
  `reason="zeroed"` on the score (an `UNCHANGED` field keeps its value), but
  it is the last history entry, and its reason is `UNCHANGED`. Zero spends no
  empty attempt on a target that passes this check.

A target that fails its check is not unchanged, and it is disposed again
like any other target. Examples:

- an excluded score given a counted value by a later
  `edit_score(..., ScoreEdit(value=1))`, which keeps the reason;
- a zeroed score given another value by such an edit;
- a Steward zero that copied a `NaN` verdict.

The new edit is appended to the score's history, and a zero applies its
refusals as usual.

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
    display: DisplayType | None = None,
) -> DispositionResult: ...

async def zero_samples_async(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
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
  existing `LookupError` or `DisallowedRegistryArg` and its advice.

**Staged commit.** Both functions apply their edits to a staged log and
compute its metrics before the input log changes:

1. `staged = log.model_copy(update={"samples": samples, "results":
   deepcopy(log.results)})`, where `samples` is a new list with one entry per
   sample:
   - a target: `deepcopy(sample)`, since the edits change its scores and
     events;
   - any other sample: `sample.model_copy(update={"scores":
     deepcopy(sample.scores), "metadata": deepcopy(sample.metadata)})`, a
     shallow copy whose scores and metadata are its own.

   `compute_log_metrics()` reads only each sample's `id`, `error`, `scores`
   and `metadata` (`src/inspect_ai/log/_metric.py:98-128`). It wraps the
   score and metadata objects in `SampleScore`s that reach reducers
   (`reduce_scores()`, `results.py:715`) and metrics, which may mutate them.
   With these copies, nothing a reducer or metric receives belongs to the
   input log. Events, messages and outputs of untargeted samples are shared,
   because no computation reads them. The log header is small, so `results`
   is copied whole.
2. The edits are applied to `staged` with `edit_score(staged, ...,
   recompute_metrics=False, epoch=...)`, which changes only the copied
   target samples' scores and events.
3. `compute_log_metrics(staged, resolved)` runs once. It assigns
   `staged.results` and `staged.reductions`.
4. Only when that returns are the target entries of `log.samples` replaced
   by their staged copies, and `log.results` and `log.reductions` by the
   staged ones. Untargeted samples keep their original objects; their staged
   copies are discarded, with whatever a callback did to them. Nothing in
   this step awaits or raises.

An edit, reducer or metric that raises, or mutates its inputs before
raising, therefore leaves the input log exactly as it was. For zero this is how a verdict that does not fit the
log's metrics is refused: for example, a task edited since the log was
written now returns a scalar where the logged dict metrics expect a dict,
and `eval_results()` raises `TypeError` (`results.py:543`). Zero re-raises
it as "the empty-attempt verdicts do not fit the log's metrics (<error>);
the task may have changed since the log was written".

`exclude_samples`:

1. Resolves metrics with the caller's `trust_log`, as `recompute_metrics()`
   does. With `trust_log=True` this may import the task file, so it runs
   inside `inline_eval_set_suppressed()`. A log with no task scorers is
   accepted; it is refused only for a target with no covered name.
2. Builds the exclusion edits for the covered names of every target that is
   not already excluded, and commits them as above.

`zero_samples_async`:

1. Requires `log.eval.scorers` to be non-empty. A log with no task scorers
   has no verdict to copy: "the task of <log> has no scorers, so an empty
   attempt has no verdict; exclude the samples instead".
2. Selects the targets that are not already zeroed. When none are left it
   returns without loading the task.
3. Reconstructs the task spec as eval-retry does. The task-spec resolution
   (`src/inspect_ai/_eval/eval.py:1781-1803`) and the model and model-role
   construction (`:1817-1825`) move into a helper that both call:

   ```python
   # src/inspect_ai/_eval/eval.py
   class LogTaskSpec(NamedTuple):
       task: str                     # "<file>@<name>" or a registry name
       task_args: dict[str, Any]
       sandbox: SandboxEnvironmentType | None
       model: Model                  # constructed from the recorded config, as eval-retry does
       model_roles: dict[str, Model | list[Model]] | None
       config: GenerateConfig        # log.plan.config, as eval-retry passes it

   def log_task_spec(eval_log: EvalLog) -> LogTaskSpec: ...
   ```

   Zero runs with the log's recorded models, exactly as eval-retry does and
   as Steward's zero does; it takes no model overrides (see Future
   improvements). Constructing a recorded model needs its provider's
   credentials and SDK, as eval-retry does. A task that is neither in a task
   file nor registered raises the same `FileNotFoundError` that eval-retry
   raises.
4. Prepares the task and the log's metrics in one isolated step, through the
   task resolution a native eval uses:

   ```python
   def prepare() -> tuple[ResolvedTask, LogMetrics]:
       with inline_eval_set_suppressed():
           models = eval_init(model=spec.model, **spec.config.model_dump(exclude_none=True))
           resolved, _, _ = eval_resolve_tasks(
               spec.task, spec.task_args, models, spec.model_roles, spec.config,
               approval=None, sandbox=spec.sandbox, sample_shuffle=None,
               input_media_policy="trusted_pre_run",
           )
           metrics = resolve_log_metrics(log, trust_log=True)
       return one(resolved), metrics

   if eval_async_running():
       raise RuntimeError("zero cannot run while an eval is running in this process")
   prepared, metrics = contextvars.copy_context().run(prepare)
   prepared.task.early_stopping = None
   ```

   - **Running eval.** `eval_init()` resets process-wide state, not only
     context variables: it clears the active-sample registry and replaces
     the concurrency registries (`src/inspect_ai/_eval/context.py:34`,
     `:51`; `src/inspect_ai/log/_samples.py:480`;
     `src/inspect_ai/util/_concurrency.py:440`). `copy_context()` does not
     isolate those. Zero therefore checks the native running-eval flag
     (`_eval_async_running`, `src/inspect_ai/_eval/eval.py:795`, read
     through a small accessor) before `prepare` runs, and refuses while
     another eval runs in the process, so a refused zero leaves that eval's
     active samples, control-channel and TUI views, and concurrency limits
     as they were. `prepare` is synchronous, so nothing interleaves between
     the check and its end; the scratch eval then applies the native check
     again.
   - **Early stopping.** The prepared `Task` is a scratch-only instance,
     built by the task factory in `prepare`. Zero clears its
     `early_stopping` (`Task.early_stopping`,
     `src/inspect_ai/_eval/task/task.py:276`), because the runner may stop a
     sample-epoch before setup and scoring (`run.py:2729`) and the scratch
     log would still report success. Each target's empty attempt is a
     separate verdict, so nothing in the scratch run should stop early. The
     original task and log are untouched.

   - **Model context.** `eval_resolve_tasks()` installs the model roles and
     the primary model in the active context before any task factory runs
     (`src/inspect_ai/_eval/eval.py:2104-2119`). A factory that calls
     `get_model()` or looks up a role while it constructs the task
     (inspect_evals' NIAH calls `get_model()`, `niah/niah.py:84`) gets the
     log's models, not whatever the caller's context holds or nothing.
     Running `prepare` in a copy of the caller's context keeps those
     installations out of the caller's context, as native eval keeps them in
     its own child task. `eval_set()` resolves tasks the same way before
     handing `ResolvedTask`s to `eval()` (`src/inspect_ai/_eval/evalset.py:1052`).
   - **Order.** The task is resolved first, so importing the task file
     registers its reducers and metrics before `resolve_log_metrics()`
     rebuilds them. `resolve_log_metrics()` builds epoch reducers before it
     considers importing the task file (`src/inspect_ai/log/_metric.py:64`),
     so a task-file reducer such as HLE's (`hle/hle.py:98`) would otherwise
     be missing in a fresh process. The resolver's own trust and refusal
     rules are unchanged; zero only calls it after the import.
   - **Trust.** Metrics are resolved with `trust_log=True`. Zero imports and
     runs the task's code, exactly as `inspect eval-retry` does, so the
     caller has already decided to trust the log. With trusted resolution,
     metric options naming a model or solver rebuild, as they do when
     `inspect score` runs the log's own scorers. The docstring, CLI help and
     docs say to zero only logs you trust.
   - **Import guard.** Both the task resolution and any import by metric
     resolution run inside `inline_eval_set_suppressed()` (see "Inline
     `eval_set()` calls" below), so importing the task file never starts an
     evaluation the file runs at module scope.
   - **Task-constructed models.** `Task(model=...)` and `Task(model_roles=...)`
     are constructed when the task factory runs (`Task.__init__`,
     `src/inspect_ai/_eval/task/task.py:254`), and a task-pinned primary
     takes precedence (`src/inspect_ai/_eval/loader.py:119`), as in any eval
     of the task. Their providers must be available, as for eval-retry.

   `eval_resolve_tasks()` must return exactly one task; the scratch eval
   reuses it, so the task file is executed once.
5. Establishes that each target id names the same sample it named in the
   original run, and refuses otherwise. Three checks, all before the scratch
   eval:

   **Ids of its own.** Zero refuses a dataset whose sample ids are
   assigned by position. Inspect
   gives a sample without an id the id of its position, after any shuffle
   (`src/inspect_ai/_eval/run.py:222-228`, shuffling at
   `src/inspect_ai/_eval/loader.py:106`). A logged positional id therefore
   need not name the same sample in a new run: with source samples `[A, B]`
   shuffled, the logged id 1 can be `B` while the scratch eval's id 1 is `A`,
   and every later identity check would pass on the wrong sample. Zero
   requires every sample of `prepared.task.dataset` to carry its own id
   before the run assigns any. Otherwise it refuses before the scratch eval:
   "the dataset of task <name> assigns sample ids by position, so a logged
   id need not name the same sample; zero needs a dataset with sample ids".
   Zero also refuses a task whose samples come from a `SampleSource`
   (`prepared.task.sample_source is not None`). Its dataset holds only the
   initial samples, possibly none (`src/inspect_ai/_eval/task/task.py:653`),
   and samples it produces later get automatic ids as they arrive
   (`src/inspect_ai/_eval/task/run.py:1801`), so the check above cannot
   cover them: "task <name> produces its samples from a sample source, so a
   logged id need not name the same sample; zero needs a static dataset with
   sample ids". Steward's datasets are static and have ids (see "Who uses
   which shapes").

   **Same sample as logged.** Today's dataset having ids does not show that
   the original run's ids meant the same samples: a log written when the
   dataset numbered `[A, B]` by position after a shuffle (logged id 1 is
   `B`) is followed by a task edit that gives `A` id 1 and `B` id 2. The log
   does not record where its ids came from (`EvalDataset` holds the ids and
   the shuffle flag, `src/inspect_ai/log/_log.py:993`), so zero checks the
   correspondence itself. For each target, the dataset sample with the
   target's id must match the logged `EvalSample` on `input`, `choices`,
   `target`, `setup` and the names of `files`. Logged attachments are
   resolved first (`resolve_sample_attachments`,
   `src/inspect_ai/log/_condense.py:678`), and message inputs are compared
   by role and content, without message ids. A mismatch refuses: "the
   task's sample <id> does not match the logged sample (<field> differs);
   the dataset or its sample ids changed since the log was written". This
   fails closed: a sample whose input the dataset now renders differently
   (for example an image materialized another way) is refused rather than
   zeroed from a sample that might be another one.

   Exclusion needs none of this: it edits the logged record and never
   re-runs a sample.
6. Runs one scratch eval in a temporary local directory:

   ```python
   eval_async(
       tasks=prepared,               # the ResolvedTask from step 4, which carries its models and sandbox
       model=None,                   # explicit, as eval_set passes it with ResolvedTasks
       solver=empty_attempt(),
       sample_id=_requalify_sample_ids(
           log.eval.task, [literal_sample_id(id) for id in target_ids]
       ),
       epochs=<Epochs(config.epochs, config.epochs_reducer), or None when unrecorded, as eval-retry>,
       time_limit=..., working_limit=..., retry_on_error=...,
       max_samples=..., max_sandboxes=...,   # from log.eval.config
       sandbox_cleanup=True,
       fail_on_error=False,
       log_format="eval",
       log_dir=<tempdir>,
   )
   ```

   - **No second model resolution.** `model=None` is passed explicitly, as
     `eval_set()` passes it with `ResolvedTask`s
     (`src/inspect_ai/_eval/evalset.py:554`). An omitted `model` is
     `NOT_GIVEN`, which `eval_init()` resolves from `INSPECT_EVAL_MODEL`
     (`src/inspect_ai/_eval/eval.py:824`,
     `src/inspect_ai/model/_model.py:2621`): the prepared task would then
     run once per environment model, and an unavailable environment provider
     would fail the scratch eval before the task ran.
   - **Generate config.** `log.plan.config`, as eval-retry passes it.
   - **Literal ids.** `literal_sample_id(id: str | int) -> str | int`, a new
     helper in `src/inspect_ai/_eval/task/util.py` beside `sample_id_filter`,
     escapes the `fnmatch` metacharacters of a string id (`*` as `[*]`, `?` as
     `[?]`, `[` as `[[]`) and returns an int unchanged. Re-qualification then
     protects a `:`. I verified this by running the selection functions on
     candidates `case[1]`, `case1`, `case*`, `caseX`, `case?`, `t1:a:b` and
     `a:b`: each escaped and re-qualified target selected only itself.
   - **Normalised ids.** Because selection normalises ids, a dataset holding
     both `"12"` and `12` runs both. Step 8 matches by value and ignores the
     extra one.
   - **Epochs.** The scratch eval runs the log's recorded epoch count and
     reducers, as eval-retry passes them (`eval.py:1844-1846`). A smaller
     count would keep the task's reducers, and the runner refuses
     `pass_at_k`, `pass_k_k` and `at_least_k` reducers with fewer than `k`
     epochs (`validate_reducer`,
     `src/inspect_ai/scorer/_reducer/registry.py:176`), so zeroing epoch 1
     of an `Epochs(5, "pass_at_5")` task would fail before any empty attempt
     ran. The recorded configuration is one the task already ran with.
     `epochs` is global, so every targeted id runs every recorded epoch.
     Zeroing a sample by bare id (every epoch, the CLI default) costs
     nothing extra; zeroing one epoch of a five-epoch log runs five empty
     attempts. The extra ones provision their sandboxes and run `Task.setup`
     and the scorers like any other. Only the targeted epoch scores are
     copied; the scratch log's other samples, results and reductions are
     ignored.
   - **Scratch log.** It is read back whole and the directory removed.
7. Checks that the scratch eval completed. Its log must have `status ==
   "success"`. A cancelled or errored scratch log raises with its status and
   error, without editing anything. `eval_async` can return a cancelled log
   whose targets are already scored and error-free (verified by the
   reviewer under Trio with unfinished extra epochs), so valid target records
   alone do not show that the zero completed.
8. For every target, requires a scratch sample with the same `(id, epoch)`
   and no `error`, then applies the zero refusals under "Which score names a
   disposition covers". Any failure raises, naming every failing target and
   its cause, without editing anything. A missing scratch sample reads "the
   empty attempt of sample <id> (epoch <n>) did not run: the task's dataset no
   longer holds it". An errored one reads "...did not score: <error>". This is
   atomic where Steward's was not required to be: nothing is half-applied.
9. Stages the zero edits and computes metrics (see "Staged commit"), then
   calls `await anyio.lowlevel.checkpoint()`, which raises if the caller was
   cancelled meanwhile. Only then does it commit the staged samples and
   results, with no further await.

`zero_samples` is the synchronous wrapper. It initializes the display type
from `display` and runs the coroutine, as `score()` does: `anyio.run` with
the configured backend, or `run_coroutine` in a notebook.

### Inline `eval_set()` calls

An eval-set definition may call `eval_set()` at module scope, so importing it
runs the evaluation. Steward's definitions are such files: its fixture
`tests/evalset/fixtures/erroring_evalset.py:47` of meridianlabs-ai/inspect_steward
calls `eval_set(..., log_dir="logs")` unguarded, and Steward sets
`INSPECT_EVAL_SET_CAPTURE` before its first import of a definition
(`_marks/run.py:93`) for that reason. Inspect imports a task file by executing
it (`load_module`, `src/inspect_ai/_util/module.py:35`), both when loading a
task (`load_tasks`) and when trusted metric resolution imports the log's task
file (`load_file_tasks`, `src/inspect_ai/_eval/score.py:678`). Capture mode
is not a library guard: it writes a manifest and raises `SystemExit(0)`
(`src/inspect_ai/_eval/evalset.py:845`), which would end the caller's
process.

The disposition functions therefore import task files inside a new guard:

```python
# src/inspect_ai/_util/module.py, beside load_module(); eval_set() and eval() import it
_inline_eval_set_suppressed: ContextVar[bool] = ContextVar(..., default=False)

class InlineEvalSetSuppressed(BaseException):
    """Raised by `eval_set()` / `eval()` called while a task file is imported under the guard."""

@contextmanager
def inline_eval_set_suppressed() -> Iterator[None]:
    """Stop a task file's module-scope `eval_set()` or `eval()` call from running while it is imported."""
```

- The context manager sets the variable and resets it with its token in a
  `finally`, so it is restored when the body raises or is cancelled.
- While it is set, `eval_set()` raises `InlineEvalSetSuppressed` as its first
  statement, before the capture branch or any log-directory side effect.
  `eval()` (the synchronous entry point a script calls at module scope) does
  the same. `eval_async()` does not check it, because zero's own scratch
  eval runs inside the guard, and a module cannot await at its top level.
- `load_module()` catches `InlineEvalSetSuppressed` around
  `loader.exec_module(module)` and returns the module, executed up to the
  call. Tasks the file defines above its `eval_set()` call are registered
  and load normally, which is what capture mode also relies on. The
  notebook loader does the same around its cell execution.
- A task defined below the call is never registered, and loading it fails
  with the loader's ordinary "task not found" error.

The exception derives from `BaseException`, so a definition's own
`except Exception` around its `eval_set()` call does not swallow it. The
variable is a `ContextVar`, so it reaches the task loading that `eval_async`
does in its child tasks, and it does not leak to unrelated tasks.

### CLI

Two subcommands of `inspect log` (`src/inspect_ai/_cli/log.py`, beside
`recover`):

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--trust-log] [--json]
inspect log zero    LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--json]
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
- **Changed dataset.** Suppose a task's static dataset changed so that a
  targeted sample no longer exists. Zero then fails step 8 with that said,
  and nothing is edited. A task fed by a `SampleSource` is refused in step 5.
- **Edited task file.** A task file edited since the log was written runs as
  edited, as eval-retry does. The scratch log is not kept, but the zero edits
  record the scorer's answer and explanation for the empty attempt. A
  verdict whose shape no longer fits the log's metrics is refused by the
  staged metric computation, and the log is left unchanged.
- **Concurrency.** The functions are synchronous over an in-memory log,
  except zero's scratch eval, which runs before any edit. The CLI's write is
  a conditional write on S3 and last-writer-wins locally, as `edit_score()`
  plus `write_eval_log()` is today.
- **Cancellation.** Cancelling `zero_samples_async` cancels the scratch eval
  and leaves the log unchanged. Sandbox cleanup runs as for any cancelled
  eval. If the scratch eval absorbs the cancellation and returns a cancelled
  log, step 7 refuses it. If the cancellation arrives after the scratch eval
  returns, the checkpoint before the commit raises it. The commit itself has
  no await, so a cancellation lands either before it (log unchanged) or after
  it (edits complete).

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
- **Task-file imports.** `eval_set()`, `eval()` and `load_module()` behave
  as today unless `inline_eval_set_suppressed()` is active, which only the
  disposition functions enter. Capture mode is unchanged.
- **Eval-retry.** Its task and model reconstruction moves into
  `log_task_spec()`, with the same results and the
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
  code-execution path beyond eval-retry's. Both functions import task files
  under `inline_eval_set_suppressed()`, so a definition's module-scope
  `eval_set()` or `eval()` does not start an evaluation, write logs or reach
  a provider.
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
  - A scorer with `metrics=[]` that always returns `None` (as BFCL's
    prerequisite scorer does): excluded under its derived name both when it
    is the task's only scorer and when it sits beside a scorer that produced
    scores and result rows.
  - An appended log in which one sample lacked an earlier key, so append
    named its score differently there: the exclusion covers both appended
    keys and adds no other name.
  - An original `probe` that never scored and an appended `probe` written
    under the vacant `probe` key on every sample: the exclusion edits
    `probe` and creates no `probe1`.
  - Two configured scorers named `probe`, one with keys and one silent, on
    a log whose keys cannot be attributed (`0 < len(R) < k`): refused, with
    the log unchanged.
  - `exclude_samples` on a solver-only log with task-level metrics
    (`log.eval.scorers` `None`): the solver key is excluded and metrics
    recompute. A log that names no score refuses the target.
  - Metrics recompute: `accuracy` over the rest, and `unscored_samples`
    counted.
  - Selection: a bare id covers every epoch, and an `(id, epoch)` pair covers
    one. A repeat reports the target `unchanged`.
  - Idempotence holds only with the invariant: an excluded score later given
    `ScoreEdit(value=1)` is excluded again, not reported unchanged.
  - Staged commit, each leaving the input log's samples, scores, score and
    sample metadata, events, results and reductions unchanged:
    - an epoch reducer that mutates an untargeted sample's score and its
      nested metadata, then raises;
    - a metric (taking `list[SampleScore]`) that mutates an untargeted
      sample's metadata, then raises.
  - Inline `eval_set()`: a task file that defines a task and then calls
    `eval_set(..., log_dir=<tmp>/inline)` at module scope.
    `exclude_samples(..., trust_log=True)` and `zero_samples` both succeed,
    `<tmp>/inline` is never created, and the guard variable is reset
    afterwards, also when the body raises.
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
  - A multi-epoch log with targets `a/1` and `b/2`: `a/2` and `b/1` run in
    the scratch eval, and those samples are left unedited.
  - Epoch reducers: zeroing epoch 1 of a log recorded with `Epochs(5, r)`
    succeeds for each of `pass_at_5`, `pass_k_5` and `at_least_5`.
  - Task preparation, run in a fresh context and in a context whose active
    model and a `grader` role are unrelated `mockllm` models: a task factory
    that calls `get_model()` and one that reads the `grader` role while
    constructing the task both receive the log's recorded models, and the
    caller's active model and roles are unchanged afterwards.
  - A file-backed task with its own epoch reducer, defined in the task file
    and absent from the registry before the zero: zeroing succeeds in a
    fresh process (the reducer is registered by step 4 before metrics
    resolve).
  - Positional ids: a log of a task whose dataset samples have no ids, run
    with `sample_shuffle`, is refused before the scratch eval, with the log
    unchanged; so is the same task run without a shuffle.
  - Sample sources: a task whose `SampleSource` has an empty seed and later
    produces samples without ids is refused before the scratch eval, with
    the log unchanged.
  - Environment models: with `INSPECT_EVAL_MODEL` naming two `mockllm`
    models, the scratch eval runs the prepared task once, with the recorded
    model; with it naming an unregistered provider, zero still succeeds.
  - Changed ids: a log written when the dataset numbered `[A, B]` by
    position after a shuffle, zeroed after the task file gives `A` id 1 and
    `B` id 2, is refused by the same-sample check, with the log unchanged.
  - Running eval: zeroing a landed log while another eval in the process
    holds a live sample (asyncio and Trio) is refused before preparation,
    and the running eval's active samples and concurrency registries are
    unchanged; that eval then finishes normally.
  - Early stopping: a task whose early-stopping manager stops after a
    failure, whose original log holds both epochs: zeroing every epoch runs
    both empty attempts and zeroes both, and the task's own
    `early_stopping` object and the log are otherwise unchanged.
  - A task defined below its file's module-scope `eval_set()` call fails
    with the loader's "task not found" error, and the log is unchanged.
  - A metric whose options name a model resolves.
  - A sample whose `zeroed` score holds `NaN` (a Steward zero) is zeroed
    again rather than reported unchanged.
  - A zeroed score later edited with `ScoreEdit(value=1)` is zeroed again
    rather than reported unchanged.
  - Cancellation: with the targets scored and an extra epoch blocked on an
    `anyio.Event`, cancelling `zero_samples_async` (asyncio and Trio) leaves
    the log unchanged. So does a stubbed `eval_async` that returns a
    `cancelled` log with valid target records.
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
    - a task edited to return a scalar under a name whose logged metrics
      expect a dict: the `TypeError` is re-raised and the samples, results
      and reductions are those of the input log;
    - an ephemeral task.
  - A scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
- `tests/test_eval.py`: the existing eval-retry tests pass unchanged after
  the reconstruction moves into `log_task_spec()`.
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
   - `inline_eval_set_suppressed()` and `InlineEvalSetSuppressed` in
     `src/inspect_ai/_util/module.py`, caught by `load_module()` and the
     notebook loader (`src/inspect_ai/_util/notebook.py`), and checked first
     in `eval_set()` (`src/inspect_ai/_eval/evalset.py`) and `eval()`
     (`src/inspect_ai/_eval/eval.py`).
   - A "Zeroing and Excluding Samples" section in `docs/eval-logs.qmd`,
     including the retry behaviour and, for a running eval, `inspect ctl
     sample cancel --action cancel` followed by these commands once the log
     lands.

   Tests as above.
3. **Zero.**
   - `log_task_spec` and `LogTaskSpec`, extracted in
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
- **Model overrides for zero.** `zero_samples(..., model=..., model_roles=...)`
  and `inspect log zero --model / --model-role`, for a log whose recorded
  provider is unavailable, plus a task-argument override for tasks that take
  their model as an argument. Overrides need rules for models the task
  constructs or pins itself, which take precedence over or are constructed
  before an eval-level model, and neither the issue nor Steward needs them
  (decision: Ransom, 2026-11-04).
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
- Two recomputation defects that affect any score edit today, with or
  without these functions:
  - `compute_log_metrics()` passes no scorer identities to `eval_results()`
    (`src/inspect_ai/log/_metric.py:113`), and the fallback deduplicates
    against the result `name` (a dict metric key) rather than `scorer`
    (`src/inspect_ai/_eval/task/results.py:161`). Two dict-valued scorers of
    the same name can then both report the first one's data after a
    recompute.
  - `scorers_from_metric_dict()` expands glob metric keys from a sample's
    current dict value and keeps the literal glob when none is left
    (`results.py:500`). After every score of such a scorer becomes `NaN`,
    the concrete `x`, `y` rows are replaced by a `*` row.
