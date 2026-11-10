# Zeroing and excluding samples

## Overview

When an operator decides that a sample should not count the way the model ran
it, there are two answers: **zero** it (count it as a failure) or **exclude**
it (leave it out of the metrics). This design adds both to Inspect, for logs
that have landed.

- **Exclude** rewrites each of the sample's scores as
  `Score.unscored(reason="excluded")`. The value is `NaN`, which metrics
  already skip, and the explanation carries the operator's reason. An errored
  sample that holds no score gets one excluded score, under the task's first
  scorer. Epoch reduction learns to drop excluded epochs before the reducer
  sees them, so an excluded epoch counts as one that never ran, and a sample
  with every epoch excluded is reduced to an excluded score.
- **Zero** gives each score the verdict the task's own scorers return for an
  **empty attempt** of the sample. The sample is started as for a run
  (sandbox, files, setup script, `Task.setup`), the task's main solver is
  skipped, and the scorers run on the untouched state. The score's `reason`
  becomes `"zeroed"`. Zero needs samples with string ids, which name the same
  sample however the dataset is reordered, a task whose scorers are the ones
  the log records, and scorers that return a single value (not a dict or a
  list). A zero that cannot give the sample a counted score under every name
  it holds is refused, and the log is left unchanged.

Both keep the sample's transcript and error. Both record who decided and why
as score-edit provenance, so the earlier score stays in `Score.history`, and
both recompute the log's metrics. They are Python functions in
`inspect_ai.log` and two `inspect log` subcommands.

Neither imports a task file the log names. As for the shard merge, the
caller names the task: zero takes the task, the models and the eval settings to run
it with, as `eval()` and `inspect eval` take them, and runs its empty
attempts in a scratch eval of that task restricted to the targeted samples.
Exclusion may take the task to recompute the log's metrics with; without
it, the metrics are rebuilt from the registry as an untrusted recompute does
today. Both recompute the log's results exactly as `recompute_metrics()`
does: with the task's metrics when it is given, and always with the epoch
reducers the log header records, however the run set them. A task is
refused when its name or its scorer names differ from the
log's, but its options, metrics, epochs, code and
settings are the caller's responsibility: the verdict reflects the task and
settings passed. Otherwise zero copies the verdicts in. Neither applies to a
log that is still being written.

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
  `recompute_metrics()`. It edits every score the sample holds, and gives an
  errored sample with no scores one unscored score under the task's first
  scorer. It misses one case: an excluded epoch still reaches the epoch
  reducer, and not every reducer skips `NaN` (see "Epoch reduction" below).
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

- Exclude a sample of a landed log. Every score the sample holds becomes
  unscored with reason `"excluded"`; a sample holding none gets one under the
  task's first scorer. The edit records provenance, and metrics are
  recomputed. An excluded epoch takes no part in epoch reduction.
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
- Rebuilding the task or its run from the log. Zero and exclusion import no
  task file or path the log names, and zero builds no task, model or run
  setting from what the log records; the caller passes the task and the
  settings, as for the shard merge (decision: Ransom, 2026-11-06).
- Checking that the caller's task and settings are the ones the log ran,
  beyond the names compared under "Matching the task". A task edited since
  the log, or settings other than the original run's, change the verdict;
  that is the caller's responsibility (see Compatibility).
- Zeroing the shapes zero refuses, each before the scratch eval or before
  any edit, with a message that names the cause and suggests exclusion,
  which accepts them all (decision: Ransom, 2026-11-06): a task whose names
  differ from the log's; integer ids and sample sources; dict and list
  verdicts. Multi-epoch logs and logs written by eval-retry are supported.
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
  imports no task file named by the log and refuses metric options that name a model or a
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
- **Recorded reducers.** The header's `eval.config.epochs_reducer` holds the
  reducers the run used, however they were set: the runner records an
  eval-level `epochs` reducer when one was given and the task's own
  otherwise (`reducer_log_names(task.epochs_reducer)`,
  `src/inspect_ai/_eval/run.py:316-325`), and `None` when neither set one
  (the default `mean`). Each reducer is recorded by registry name, with a
  `k` parameter as a `_<k>` suffix and no other argument (`reducer_log_name`,
  `src/inspect_ai/scorer/_reducer/registry.py:115-122`). Recomputation
  rebuilds them with `create_reducers()` (`registry.py:133`), in
  `resolve_log_metrics()` and in `reducers_from_log_header()`
  (`src/inspect_ai/_eval/score.py:861`), so a custom reducer configured with
  other arguments is rebuilt with its defaults.
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
    `unique_scorer_name()` (`src/inspect_ai/scorer/_scorer.py:262`) returns
    the plain name when no earlier name collides, so the first scorer's key
    is always its plain name.
  - **Scorer header.** Each `log.eval.scorers` entry records the scorer's
    name, options (its registry arguments), metrics and metadata
    (`resolve_eval_scorers`, `src/inspect_ai/_eval/task/log.py:1351`).
  - **Solver-written scores.** A solver may write `state.scores` itself
    ([Solvers](../docs/solvers.qmd)). Those keys are captured before the task
    scorers run (`run.py:3191`), and they are copied into the sample's events
    and the eval results after them (`run.py:3273`). A task may have no
    scorers at all and rely on these, with task-level metrics
    (`tests/scorer/test_score_editing.py:553`).
  - **Missing keys.** An errored sample that never scored holds no keys
    (verified with a two-sample `mockllm` eval). Metrics count a sample
    under a scorer only when it holds that key, so a missing key counts
    toward neither `scored_samples` nor `unscored_samples`.
  - **Appended scorers.** `inspect score --action append` appends to
    `log.eval.scorers` (`src/inspect_ai/_eval/score.py:443`). It names each
    appended scorer per sample, with `unique_scorer_name()` over the keys
    that sample already holds (`score.py:556`), then adds a `-N` suffix on a
    remaining collision (`score.py:176`). So an appended scorer can write
    under a key an original scorer uses elsewhere: on a sample that errored
    before any scorer ran, an appended `probe` takes the vacant `probe` key
    (verified by the reviewer). The key alone does not say which scorer
    wrote a score.
- **`inspect score`** / `score_async` (`src/inspect_ai/_eval/score.py:234`)
  rebuild a `TaskState` from the logged `EvalSample`
  (`task_state_from_sample`, `:464`) and run scorers on it, with no sandbox.
  A logged `EvalSample` carries only the names of the sample's `files`, so a
  sample's sandbox cannot be rebuilt from the log. Rebuilding it needs the
  task's dataset.
- **Effective settings.** For each sample limit and each policy, the runner
  uses the eval-level value when one is given and otherwise the task's own
  (`src/inspect_ai/_eval/run.py:333-408`), and the generate config is
  `task.config.merge(<eval-level options>)`
  (`src/inspect_ai/_eval/task/run.py:849`), which keeps the task's value for
  every option the eval leaves `None` (`GenerateConfig.merge`,
  `src/inspect_ai/model/_generate_config.py:379`). The log records only the
  values in effect, so it does not say which came from the eval and which
  from the task.
- **Model prices.** `eval_async()` applies `model_cost_config` with
  `set_model_cost()` before it initializes models and resolves tasks
  (`src/inspect_ai/_eval/eval.py:808-815`, then `eval_init()` at `:823` and
  `eval_resolve_tasks()` at `:845`), so a task factory that reads model info
  while it constructs the task sees the configured prices. It also expands
  `model_args` and `task_args` given as file names with `resolve_args()`
  first (`:805-806`).
- **Task resolution.** `eval_resolve_tasks()` (`src/inspect_ai/_eval/eval.py:2086`)
  installs the model roles and then, per model, the active model before it
  constructs tasks (`:2104-2119`), so a task factory can call `get_model()`
  or read a role. `eval_async` calls it in its own child task, and
  `eval_set()` calls it to resolve tasks before passing the `ResolvedTask`s
  to `eval()` (`src/inspect_ai/_eval/evalset.py:1052`, `:551-554`).
- **Sample ids.** A dataset sample without an id gets its 1-based position as
  its id when the task runs (`src/inspect_ai/_eval/run.py:222-228`), after
  any `sample_shuffle` (`src/inspect_ai/_eval/loader.py:106`). That id is an
  `int`, and so is the id a file or Hugging Face loader assigns with
  `auto_id=True` (`data_to_samples`, `src/inspect_ai/dataset/_util.py:129`).
  Every id Inspect assigns to a static dataset is therefore an `int`; a
  string id was supplied by the task's author. `ensure_unique_ids`
  (`src/inspect_ai/_eval/run.py:1457`) refuses a dataset with a repeated id,
  including an `int` and a `str` with the same `str()` form.
- **Sample-id selection** (`eval(sample_id=...)`) is not literal, which is
  why Steward prefixes its ids with the task name:
  1. `resolve_task_sample_ids` (`src/inspect_ai/_eval/task/util.py:76`) reads
     a prefix before the first `:` as a task scope when it names a task in
     the run (`:101-110`), so an id `t1:a:b` of task `t1` loses its prefix.
  2. The remaining selector is a pattern, not a literal. `sample_id_filter`
     matches with `fnmatch` (`util.py:71`), so a selector `case[1]` matches
     `case1` and not itself, and `case*` matches every id starting with
     `case`. Before matching, `normalise_sample_id` treats the string `"12"`
     and the int `12` as the same id.

  Without `sample_id` or `limit`, the runner runs every sample of
  `task.dataset` (`slice_dataset`, `util.py:196-202`). `Task.dataset` is a
  plain attribute, and `MemoryDataset.filter()` returns a new dataset holding
  the same `Sample` objects (`src/inspect_ai/dataset/_dataset.py:384`). The
  runner assigns positional ids only to samples whose id is `None`
  (`src/inspect_ai/_eval/run.py:224-226`).
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
`.eval` logs of `eval_set()` runs launched from definitions it loads itself
(with capture mode, `_marks/run.py:93`), so it can hand zero the task and
the settings it ran with; its tasks have static datasets
whose samples have string ids (its fixture's ids are `user:cybergym/arvo_1`
and so on, `tests/evalset/fixtures/erroring_evalset.py:37` of
meridianlabs-ai/inspect_steward). Its fixture's scorer is `exact()`, which
returns a single string value (`:43`). Searching inspect_ai, inspect_scout,
inspect_flow and inspect_swe for the reasons `excluded` / `zeroed` finds no
other producer or reader, and the viewer shows any reason string as text.

Scorers with dict values exist (inspect_evals' HLE returns `{"score",
"confidence"}`; BrowseComp, TAC and Mind2Web read named keys with
`aggregate(..., on_missing="skip")`, which skips a key that is missing or
`None`), but no zero of one has been asked for. Deciding that a dict or list
verdict is counted by every metric needs rules about the keys the log's
metrics read, so zero supports single-value verdicts only.

The design therefore supports:

- zero with a task the caller passes (a built `Task` or a task spec) that
  has scorers and the log's task name and scorer names, run with the models and settings the caller passes; static
  datasets; samples with string ids that the task's dataset holds; scorers
  whose empty-attempt verdict is a
  single `str`, `int`, `float` or `bool`; and samples whose scores all come
  from those scorers;
- exclusion for any landed log, for a sample that holds a score or of a log
  that names a scorer, with the caller's task's metrics or, without a task,
  with metrics the registry can build from the header.

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

A predicate sits beside it in `src/inspect_ai/scorer/_metric.py`, used by
epoch reduction and by the disposition functions:

```python
def score_is_excluded(score: Score) -> bool:
    """`reason == "excluded"` and the value is a float NaN at the root."""
```

Zero copies single-value verdicts only. A private helper in
`src/inspect_ai/log/_disposition.py` says which of them count:

```python
def _counted_scalar(value: Value) -> bool:
    """A `str`, `int`, `float` or `bool` that is not a float NaN."""
```

A single value cannot be `None` (`Value`, `src/inspect_ai/scorer/_metric.py:68`),
so the only single value the standard score filter treats as unscored is a
root `NaN`: it counts any other scalar as scored. Individual metrics may
apply further input requirements or filtering; `krippendorff_alpha()`, for
example, skips a scalar with a warning because it expects a list of ratings
(`src/inspect_ai/scorer/_metrics/krippendorff.py:95-113`). Successful
recomputation does not prove that every metric uses the score. The helper
is a check on the raw value only:

- A verdict that makes the task's metrics raise (a scalar where a dict
  metric expects a dict) is refused by computing the metrics on staged
  edits before they are committed (see Python API). A metric that accepts
  the verdict and filters it out is not detected.
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
  created by the edit has `answer` and `metadata` `None`. One metadata key
  is not kept: because the edit sets `reason`, `edit_score()` drops a
  legacy `metadata["unscored_reason"]` from the current score
  (`src/inspect_ai/log/_score.py:137-143`), so that an older log's reason
  does not override `"excluded"` when it is read again. The original
  metadata, that key included, stays in `history[0]`. Zero replaces the
  metadata with the verdict's, so the same applies to it.
- **Zero:** `ScoreEdit(value=v.value, answer=v.answer,
  explanation=v.explanation, reason="zeroed", metadata=v.metadata or {},
  provenance=provenance)`, where `v` is the empty attempt's score of the same
  name. When the sample already had that score, the original is `history[0]`.

`ScoreEdit` marks a field to keep with the string `"UNCHANGED"` (`UNCHANGED`,
`src/inspect_ai/scorer/_metric.py:79`). `edit_score()` keeps the current
field for it on an existing score, and on a new score refuses it as a value
and stores `None` for it as an answer or explanation
(`src/inspect_ai/log/_score.py:94-108`, `:126-131`). A copied verdict or an
operator's reason that is that literal string would therefore be dropped.
Both are refused before any edit: the reason with the provenance checks (see
Python API), and a verdict with the zero refusals below. A verdict's
`metadata` is copied as `v.metadata or {}`, a dict, which never equals the
sentinel.

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

Neither disposition infers score names. Each works from the keys the sample
holds, and the log is not asked to say which scorer would have written a key
it does not hold.

**Exclude** follows Steward's rule (`edit.py:185-235`, `_first_scorer`):

- It edits every score key the sample holds: task scorers' keys, appended
  keys and solver-written keys alike.
- A sample that holds no score (an errored sample that never scored) gets one
  excluded score, under the first entry of `log.eval.scorers`. That entry's
  key is always its plain name, because the runner never suffixes the first
  scorer (see "Score names" above).
- A sample that holds no score, of a log whose `log.eval.scorers` is empty or
  `None`, is refused before anything changes: "sample <id> (epoch <n>) holds
  no score and the log names no scorer to record the exclusion under".

An excluded errored sample is therefore recorded under the first scorer
only. That is enough for every metric: a missing key already counts toward
no metric, so the sample is out of every scorer's denominator either way.
The only difference from a score under every scorer is in the other
scorers' `unscored_samples` counts, which do not count it.

**Zero** edits exactly the names the empty attempt scored. A target is
refused, before anything changes, in five cases:

- **No verdict.** The empty attempt produced no score: every scorer returned
  `None`. Message: "the empty attempt of sample <id> (epoch <n>) produced no
  score; exclude it instead".
- **Structured verdict.** A score of the empty attempt has a dict or list
  value. Message: "the empty attempt of sample <id> (epoch <n>) scored
  <name> with a <dict|list> value; zero supports single-value verdicts only,
  so exclude it instead". This is checked first, whatever the other scores
  are.
- **Unscored verdict.** A score of the empty attempt has a root `NaN` value
  (a grader failure, `Score.unscored()`). Copying it would label a sample
  `zeroed` that metrics leave out of the denominator. This holds whether
  every scorer's verdict is unscored or only one. Message: "the empty attempt
  of sample <id> (epoch <n>) was not scored by <name> (<reason>:
  <explanation>); zero it again, or exclude it".
- **Reserved text.** A score of the empty attempt has a `value`, `answer` or
  `explanation` that is the literal string `"UNCHANGED"`, which the edit
  would read as "keep the current field". Message: "the empty attempt of
  sample <id> (epoch <n>) scored <name> with the literal text UNCHANGED in
  its <field>, which a score edit cannot record; exclude it instead".
- **Uncovered score.** The sample holds a score under a name the empty attempt
  did not produce: a scorer that returned `None` on the empty attempt but
  scored the original, or a solver-written score. Leaving that score would
  keep the original verdict on a sample reported as zeroed. Message: "sample
  <id> (epoch <n>) holds scores the empty attempt does not produce (<names>);
  exclude it instead".

These per-target checks rely on a check of the whole log that comes first
("Matching the task", step 3 of `zero_samples_async`): the task's scorer
names must be the ones the log records, in the same order; their options
are not compared. A log with
appended scores usually fails that check, because append adds its scorers
to `log.eval.scorers` and the task does not have them. When the check
passes, zero writes the task's verdicts under the keys the task's scorers
write, and it does not try to attribute a held key to the scorer that wrote
it.

That includes one case where the held key came from another scorer, which
zero accepts (decision: Ransom, 2026-11-04). A task ran `[probe(0)]`; a
sample errored before scoring; `inspect score --action append` added
`probe(1)`, which took that sample's vacant `probe` key while its neighbours
got `probe1`; and the task was then updated to `[probe(0), probe(1)]`, so
the headers match. Zeroing the errored sample writes `probe(0)`'s verdict
under `probe`, replacing the appended `probe(1)` score, and adds
`probe(1)`'s verdict under `probe1`. The sample then has the layout its
neighbours and a fresh run of the updated task have (`probe` from
`probe(0)`, `probe1` from `probe(1)`). The replaced appended score stays in
the score's history as `history[0]`.

A name that the sample does not hold, and that the empty attempt did not
produce, stays absent, as the runner would leave it.

**Idempotence.** A target that already carries the disposition is reported
unchanged and not edited again. Carrying it means its invariant holds, not
only its reason:

- **Exclude:** the sample holds at least one score, and
  `score_is_excluded()` holds for every score it holds.
- **Zero:** the sample holds at least one score, and for every score it
  holds, the last entry of `Score.history` is an edit with reason
  `"zeroed"` and provenance, and `_counted_scalar()` holds for the value.
  `edit_score()` appends every edit to the history, so the last entry
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
it unchanged. It passes an internal plan as `solver=`. `resolve_plan()` takes
a `Plan` as it is, on a shallow copy, and prepends `Task.setup` to its steps
(`src/inspect_ai/_eval/task/run.py:674-692`), so the scratch run executes
`Task.setup` and then this plan's finish solver:

```python
# src/inspect_ai/_eval/zero.py
class SetupWroteScores(Exception):
    """`Task.setup` wrote `state.scores`, so the empty attempt has no verdict of the task's scorers alone."""

@solver(name="empty_attempt_check")
def empty_attempt_check() -> Solver:
    """Refuse an empty attempt in which `Task.setup` wrote scores; otherwise leave the state as it is."""
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.scores:
            raise SetupWroteScores(
                f"Task.setup wrote scores ({', '.join(state.scores)}), which zero "
                "cannot tell from the task scorers' verdicts; exclude the sample instead"
            )
        return state
    return solve

@solver(name="empty_attempt")
def empty_attempt() -> Solver:
    """No steps of its own (`Task.setup` is prepended), and the check as the finish solver."""
    return Plan([], finish=empty_attempt_check(), internal=True)
```

The factory is registered with `@solver` because the runner records every
solver override: `eval_async(solver=...)` passes it through
`as_solver_spec()` (`src/inspect_ai/_eval/run.py:193`), which refuses an
object that a `@solver` function did not create
(`src/inspect_ai/_eval/loader.py:674`). A `Plan` is not registered by being
named, and registering only its finish solver does not register the plan.
`@solver` tags the returned object and keeps its type, so `resolve_plan()`
still sees a `Plan` (`src/inspect_ai/solver/_solver.py:212-226`). The names
carry no package prefix: `@solver` prepends the defining package itself
(`registry_name()`, `src/inspect_ai/_util/registry.py:265`, called from
`src/inspect_ai/solver/_solver.py:194`), so they register as
`inspect_ai/empty_attempt` and `inspect_ai/empty_attempt_check`. I verified
this with `eval(task, solver=empty_attempt())` on a `mockllm` task: the run
records the solver `inspect_ai/empty_attempt`, runs `Task.setup` and the
check and not the task's solver, and a `Task.setup` that writes a score
errors the sample with `SetupWroteScores`, with and without setting
`state.completed`.

`Task.setup` is a solver, and a solver may write `state.scores`. The runner
keeps those keys beside the task scorers' results (`run.py:3191`, `:3273`),
so a score `Task.setup` wrote would reach the scratch sample under its own
key and pass for a verdict even when every task scorer returned `None`.

The check is the plan's `finish` solver, not a step, because a step can be
skipped: `Plan.__call__()` leaves its step loop as soon as
`state.completed` is true (`src/inspect_ai/solver/_plan.py:115`), so a
`Task.setup` that writes a score and completes the state would skip a check
placed after it. The finish solver runs after the steps whether or not they
exited early (`_plan.py:120`), and before the task's scorers. The exception
errors the scratch sample, and step 7 refuses that target with the error's
message, leaving the log unchanged. The main solver is skipped, so
`Task.setup` is the only solver that can have written a score by then.

The finish solver does not run when a step raises (`_plan.py:46`). A
`Task.setup` that raises errors the scratch sample, and one that exceeds a
sample limit records `limit` on it; step 7 refuses a scratch sample with
either, so no verdict from an attempt that did not pass the check is copied.

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
    task: Task | None = None,
) -> DispositionResult: ...

async def zero_samples_async(
    log: EvalLog,
    task: Task | str,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
    *,
    task_args: dict[str, Any] | str = dict(),
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: ModelRoles | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    review: str | list[ReviewPolicy] | ReviewPolicyConfig | None = None,
    sentinel: SentinelSpec | None = None,
    epochs: int | Epochs | None = None,
    message_limit: int | None = None,
    token_limit: int | TokenLimit | None = None,
    turn_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    cost_limit: float | None = None,
    model_cost_config: str | dict[str, ModelCost] | None = None,
    retry_on_error: int | None = None,
    max_samples: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> DispositionResult: ...

def zero_samples(log, task, samples, provenance, *, display: DisplayType | None = None, <the same keywords>) -> DispositionResult: ...
```

Zero's run arguments are a subset of `eval_async()`'s, with the same names,
types and defaults, and each is passed to the scratch eval as given. They
are the ones that say which task runs and how a sample runs: the task and
its arguments, the models, the sandbox, the policies, the epochs, the
sample limits and their prices, the concurrency limits and the generate
config. Zero sets the rest itself (step 5): the solver, the selection, the
logging and the error policy. A caller passes what it passed to `eval()`
for the original run, and the empty attempt runs with exactly that.

Both functions edit `log` in place, like `edit_score()`, and leave writing
to the caller. Neither imports a task file or path the log names: the
task, its code and the settings to run it with come from the caller, the
rule Ransom set for the shard merge's results (decisions: Ransom,
2026-11-03, 2026-11-04 and 2026-11-06). Metrics are recomputed exactly as
`edit_score()` and `recompute_metrics()` recompute them today, with the
registry lookup that implies (see "Recomputation" below; decision: Ransom,
2026-11-09). These rules are checked before anything changes:

- `log.samples` must be present (a log read whole). A header-only read is a
  `ValueError`.
- A log with `log.status == "started"` is refused: it is still being written.
  The message says to run the command once the eval finishes.
- `provenance.reason` must be a non-empty string other than the literal
  `"UNCHANGED"` (see "Vocabulary" above): "the reason UNCHANGED is reserved by
  score edits; give another reason". It is the explanation an exclusion
  records and the only record of why a zero was applied.
- Every selector must match.
  - A bare id matches every epoch of that id.
  - An `(id, epoch)` pair must name a sample in the log.
  - Ids match by value. A string selector also matches an `int` id whose
    `str()` equals it, because the CLI passes strings.
  - A selector that matches two distinct ids is an error.

  Unmatched selectors are a `ValueError` naming them.
- When a task is given (always for zero), it must be the task the log ran,
  by name (see "Matching the task" below).
- Metrics are resolved before the first edit. A log whose metrics cannot be
  built is therefore left unchanged.

**Matching the task.** A task passed to either function is compared with
the log by name only (decision: Ransom, 2026-11-06), by a new helper:

```python
# src/inspect_ai/log/_task_match.py
class TaskDifference(NamedTuple):
    field: str      # "task name" or "scorers"
    given: Any
    ran: Any

def task_difference(task: Task, header: EvalLog) -> TaskDifference | None:
    """The first difference between the task's name and scorer names and the log's."""
```

- **Task name.** `task.name` must equal `header.eval.task`.
- **Scorer names.** The task's scorer names, in order, as the task logger
  records them (`resolve_eval_scorers([as_scorer_spec(s) for s in
  task.scorer])`, `src/inspect_ai/_eval/task/log.py:1351`), must equal
  `[s.name for s in header.eval.scorers or []]`.

The dispositions raise `ValueError` on a difference: "the task passed
differs from the one <log> ran in its <field> (<given>, not <ran>); pass
the task the log ran". These are what the dispositions depend on: zero
writes the task's verdicts under the task's scorer keys (see "Which score
names a disposition covers"). Nothing else is compared: the options of the
task's scorers, its metrics, its epochs, its code and the run settings are
the caller's responsibility, and the docs say so. The task's epoch reducer
is not compared because it is not used: the results are reduced with the
reducers the log header records (below).

**Metrics from the task.** With a task, results are computed with the
task's own metrics, as a native run computes them, and the log's epoch
reducers, through two helpers beside `resolve_log_metrics()`:

```python
# src/inspect_ai/log/_metric.py
def log_reducers(log: EvalLog, *, reducer_advice: str | None = None) -> list[ScoreReducer] | None:
    """The epoch reducers the log header records, rebuilt from the registry."""

def task_log_metrics(task: Task, log: EvalLog) -> LogMetrics:
    """The log's reducers with the task's metrics and scorers, for compute_log_metrics()."""
    return LogMetrics(
        reducers=log_reducers(log),
        metrics=task.metrics,
        scorers=[ScorerInfo.from_scorer(s) for s in task.scorer or []],
    )
```

`log_reducers()` is the reducer block of `resolve_log_metrics()`
(`src/inspect_ai/log/_metric.py:64-75`) moved into a function, which
`resolve_log_metrics()` then calls, unchanged: `create_reducers()` on each
name in `log.eval.config.epochs_reducer`, `None` when the header records
none, and a name the registry cannot build refused with the existing
`REDUCER_MISSING` message (`_metric.py:12`) as a `LookupError`. Both paths,
with a task and without, therefore reduce epochs exactly as
`recompute_metrics()` does (decision: Ransom, 2026-11-10). Because the
header records the reducers the run used ("Recorded reducers" above), a run
given `epochs=Epochs(5, "pass_at_5")` at eval level is reduced as it ran
without the caller giving that setting again. The task is prepared before
`task_log_metrics()` is called, so a custom reducer its file defines is
registered when the header names it. The header records only a reducer's
name and `k`, so a custom reducer configured with other arguments is
rebuilt with its defaults, as `recompute_metrics()` rebuilds it today; the
docs section says so.

`compute_log_metrics()` takes a `LogMetrics` (`src/inspect_ai/log/_metric.py:88`)
and `eval_results()` builds scorer metrics from `ScorerInfo.from_scorer()`
as a native run does (`src/inspect_ai/_eval/task/results.py:61`, `:125`).
Without a task (exclusion only), metrics are rebuilt from the log header
with the existing untrusted `resolve_log_metrics(log)`, which imports no
task file and refuses a metric or reducer the registry cannot build with its
`LookupError` or `DisallowedRegistryArg`. Exclusion calls it with
`trust_log_advice=False`, since it has no such option, and adds advice to
pass the task instead.

**Recomputation.** Either way, the results come from the existing
`compute_log_metrics()` and `eval_results()`, unchanged, so a disposition
recomputes exactly as `recompute_metrics()` does today (decision: Ransom,
2026-11-09). That includes its handling of a score key outside the scorer
list, such as a solver-written score on any sample of the log:
`compute_log_metrics()` builds each `SampleScore` with no scorer
(`src/inspect_ai/log/_metric.py:104-109`), and `eval_results()` looks such
a key up by registry name with `ScorerInfo.from_name()`
(`src/inspect_ai/_eval/task/results.py:70`, `:137-145`). That lookup
(`scorer_from_registry`, `src/inspect_ai/_eval/loader.py:812`) never
parses the key as a path, but it constructs an already-registered scorer or
scanner of that name, and a `pkg/name` key can load an installed package's
Inspect entry point to find it; when nothing is found, the default metrics
apply. The epoch reducers in every case, and exclusion's metrics without a
task, are likewise built from the names the header records
(`log_reducers()` and `resolve_log_metrics()`,
`src/inspect_ai/log/_metric.py:57-83`): `create_reducers()` and
`metric_from_log()` construct registered reducers and metrics through
`registry_lookup()`, which can also load an installed package's entry point
for a `pkg/name` name (`src/inspect_ai/_util/registry.py:311-316`), as
`recompute_metrics()` does. No stricter rule is added for the dispositions,
such as accepting only reducers already registered: other callers of these
lookups load registry code from the same names, so a separate rule here
would close nothing (decision: Ransom, 2026-11-10). The dispositions add no
separate aggregation path: tightening these lookups is a change to
`eval_results()` and the header resolvers for every caller (see Not this
design).

**Staged commit.** Both functions apply their edits to copies of the target
samples, and compute metrics on a second, disposable view of the log, before
the input log changes:

1. `edited` maps each target to `deepcopy(sample)` whose `scores` is then
   replaced by its own `deepcopy(sample.scores)`, before any edit. The second
   copy matters because a sample's final `Score` can be the same object as
   the one its `ScoreEvent` holds: the runner puts the scorer's `Score` in
   both (`src/inspect_ai/_eval/task/run.py:3241-3265`), and the log `eval()`
   returns keeps that sharing for the JSON format
   (`src/inspect_ai/log/_recorders/json.py:251-256`). `deepcopy(sample)`
   preserves the sharing within the copy, so `edit_score()`, which changes
   the current score in place (`src/inspect_ai/log/_score.py:113-145`),
   would also rewrite the earlier `ScoreEvent`'s verdict and history. With
   the score map copied separately, the existing events keep their contents
   and the edits only add `ScoreEditEvent`s. The edits are applied to
   these copies with `edit_score(...)` on a log holding them
   (`log.model_copy(update={"samples": <the list with targets replaced by
   their copies>})`, with `recompute_metrics=False, epoch=...`), which
   changes only the copies' scores and events.
2. `view = log.model_copy(update={"samples": [...], "results":
   deepcopy(log.results)})`, with one entry per sample: `s.model_copy(update=
   {"scores": deepcopy(s.scores), "metadata": deepcopy(s.metadata)})`, where
   `s` is the edited copy for a target and the original sample otherwise.
   Every sample in the view is a shallow copy whose scores and metadata are
   its own.

   `compute_log_metrics()` reads only each sample's `id`, `error`, `scores`
   and `metadata` (`src/inspect_ai/log/_metric.py:98-128`). It wraps the
   score and metadata objects in `SampleScore`s that reach reducers
   (`reduce_scores()` passes them on, `results.py:715`) and metrics,
   which may mutate them, whether or not they then raise. With the view,
   nothing a reducer or metric receives belongs to the input log or to the
   edited targets. Events, messages and outputs are shared, because no
   computation reads them. The log header is small, so `results` is copied
   whole.
3. `compute_log_metrics(view, metrics)` runs once, with the task's metrics or
   those rebuilt from the header. It assigns `view.results` and
   `view.reductions`.
4. Only when that returns are the target entries of `log.samples` replaced
   by their edited copies from step 1, and `log.results` and
   `log.reductions` by the view's. The view's samples are discarded, with
   whatever a callback did to them, so a reducer that stores a value in a
   score it was given (a mean written into the first epoch's score) changes
   neither the committed zeroed or excluded scores nor any other sample.
   Nothing in this step awaits or raises.

An edit, reducer or metric that raises, or mutates its inputs, therefore
leaves the input log as it was until the commit, and the committed targets
are exactly the edits. For zero this is how a verdict that makes the
task's metrics raise is refused: for example, a task whose scorer now returns a
scalar where its dict metrics expect a dict makes `eval_results()` raise
`TypeError` (`results.py:543`). Zero re-raises it as "the empty-attempt
verdicts do not fit the task's metrics (<error>)". It checks only that
the metrics compute: a metric that applies its own input requirements and
skips the verdict without raising is not detected, so successful
recomputation does not prove that every metric uses the zeroed score.

**Task preparation.** Zero resolves the task it is given, and exclusion's
CLI resolves a task spec, through the task resolution a native eval uses,
in a copy of the caller's context:

```python
# src/inspect_ai/log/_disposition.py
def prepare_task(task: Task | str, task_args, model, model_base_url, model_args,
                 model_roles, model_cost_config, sandbox, config: GenerateConfig) -> ResolvedTask:
    def prepare() -> ResolvedTask:
        models = eval_init(model=model, model_base_url=model_base_url,
                           model_args=model_args, **config.model_dump(exclude_none=True))
        resolved, _, _ = eval_resolve_tasks(
            task, task_args, models, model_roles, config,
            approval=None, sandbox=sandbox, sample_shuffle=None,
            input_media_policy="trusted_pre_run",
        )
        return one(resolved)

    if eval_async_running():
        raise RuntimeError("cannot run while an eval is running in this process")
    model_args, task_args = resolve_args(model_args), resolve_args(task_args)
    apply_model_cost_config(model_cost_config)
    prepared = contextvars.copy_context().run(prepare)
    return replace(prepared, task=copy(prepared.task))
```

- **Task specs.** A `Task` is used as given. A string is a task spec, as
  for `inspect eval` (`file.py@name`, a registered name), loaded with
  `task_args` by the same loader; it must resolve to exactly one task. A
  spec is the caller's choice of code, so importing it is the caller's
  decision, exactly as for `inspect eval`. A task file that runs an
  evaluation at module scope (an `eval_set()` definition script) runs it
  when imported, as it does under `inspect eval`; such definitions are
  passed as a built `Task`.
- **Prices and argument files.** Before any model or task is built,
  `prepare_task` expands `model_args` and `task_args` given as file names
  and applies the caller's `model_cost_config`, in the order `eval_async()`
  does (see "Model prices" above). The price loading moves out of
  `eval_async()` into `apply_model_cost_config(model_cost_config)` in
  `src/inspect_ai/_eval/eval.py`, which both call; it accepts the same
  forms (a file name or a dict of `ModelCost`) and does nothing for
  `None`. A task factory that reads model info while it constructs the
  task, for the primary model, a role or an ensemble member, therefore
  sees the caller's prices, as under `eval()`. The scratch eval receives
  `model_cost_config` too and applies it again, which changes nothing.
  `set_model_cost()` is process-wide, as it is for `eval()`, so the prices
  stay registered after zero returns or refuses.
- **Models.** The models are the caller's, resolved by `eval_init()` as for
  `eval()`: `model=NOT_GIVEN` reads `INSPECT_EVAL_MODEL`, and a list of
  models is refused because the scratch eval runs one task once. A task that
  pins its own model or roles keeps them, as in any eval.
- **Model context.** `eval_resolve_tasks()` installs the model roles and the
  primary model in the active context before any task factory runs
  (`src/inspect_ai/_eval/eval.py:2104-2119`), so a factory that calls
  `get_model()` or looks up a role while it constructs the task
  (inspect_evals' NIAH calls `get_model()`, `niah/niah.py:84`) gets the
  caller's models. Running `prepare` in a copy of the caller's context keeps
  those installations out of the caller's context, as native eval keeps them
  in its own child task. `eval_set()` resolves tasks the same way before
  handing `ResolvedTask`s to `eval()` (`src/inspect_ai/_eval/evalset.py:1052`).
- **Running eval.** `eval_init()` resets process-wide state, not only
  context variables: it clears the active-sample registry and replaces the
  concurrency registries (`src/inspect_ai/_eval/context.py:34`, `:51`;
  `src/inspect_ai/log/_samples.py:480`; `src/inspect_ai/util/_concurrency.py:440`).
  `copy_context()` does not isolate those. The native running-eval flag
  (`_eval_async_running`, `src/inspect_ai/_eval/eval.py:795`, read through a
  small accessor) is therefore checked before `prepare` runs, and a call
  while another eval runs in the process is refused, so it leaves that
  eval's active samples, control-channel and TUI views, and concurrency
  limits as they were. `prepare` is synchronous, so nothing interleaves
  between the check and its end; the scratch eval then applies the native
  check again.
- **The caller's task is not changed.** `ResolvedTask` is a frozen dataclass
  (`src/inspect_ai/_eval/task/resolved.py:14`) holding the instance the
  caller passed or the factory returned (a factory may return a cached
  `Task`; `resolve_tasks()` keeps it, `src/inspect_ai/_eval/loader.py:114`).
  `prepare_task` therefore returns it with a shallow copy of the task, as a
  normal run shallow-copies the task before applying its overrides
  (`src/inspect_ai/_eval/run.py:261`), and zero rebinds attributes only on
  that copy: `epochs` for the epoch check (steps 3 and 4), `early_stopping`
  and `dataset` in step 5. `task_with()` is not used, because it changes the
  task it is given.

`exclude_samples`:

1. With a task, checks it with `task_difference()` and takes its metrics
   from `task_log_metrics(task, log)`. Without one, rebuilds the metrics
   from the header with `resolve_log_metrics(log)`. Either way the epoch
   reducers are the header's, so exclusion takes no epoch settings. No task
   file named by the log is imported either way.
   A log with no task scorers is accepted; it is refused only for a target
   that holds no score.
2. Builds the exclusion edits for every target that is not already excluded
   (the keys it holds, or the first scorer's name), and commits them as
   above.

`zero_samples_async`:

1. Requires `log.eval.scorers` to be non-empty. A log with no task scorers
   has no verdict to copy: "the task of <log> has no scorers, so an empty
   attempt has no verdict; exclude the samples instead".
2. Selects the targets that are not already zeroed. When none are left it
   returns without preparing the task.
3. Prepares the task with `prepare_task()` and the caller's task, task
   arguments, models, prices, sandbox and generate config, sets its copy's
   epoch count from the caller's `epochs` when given, as the runner does
   (`src/inspect_ai/_eval/run.py:311-314`), checks it with
   `task_difference()`, and takes its metrics from
   `task_log_metrics(copy, log)`. A reducer given with `epochs` reaches only
   the scratch eval, whose own results are discarded; zero's results are
   reduced with the header's reducers.
4. Establishes that each target can be run by the task, and refuses
   otherwise. Three checks, all before the scratch eval:

   **Epochs.** Every targeted epoch must be at most the copy's epoch count
   (`epochs`, default 1): "sample <id> epoch <n> is beyond the <count>
   epochs the task runs; pass the epochs the log ran (the log ran
   <log.eval.config.epochs>)".

   **Static dataset.** Zero refuses a task whose samples come from a
   `SampleSource` (`prepared.task.sample_source is not None`). Its dataset
   holds only the initial samples, possibly none
   (`src/inspect_ai/_eval/task/task.py:653`), and the samples it produces
   get their ids as they arrive (`src/inspect_ai/_eval/task/run.py:1801`):
   "task <name> produces its samples from a sample source, so a logged id
   need not name the same sample; zero needs a static dataset". The
   string-id rule below holds for zero only because of this refusal: a
   sample source may give the samples it produces string ids generated
   afresh on every attempt, and such an id names nothing stable.

   **String ids.** Every id Inspect assigns to a static dataset is an `int`
   (see "Sample ids" above), so a string id was supplied by the task's
   author. It names the same sample however the dataset was reordered,
   shuffled or extended since the log was written, which is what retry
   relies on too. For each target:

   - Its id in the log must be a `str`. An `int` id is refused, positional or
     explicit, because the log does not record which it was (`EvalDataset`
     holds the ids and the shuffle flag, `src/inspect_ai/log/_log.py:993`):
     "sample <id> has an integer id, which need not name the same sample in
     a new run; zero needs samples with string ids: give the task's samples
     string ids".
   - Exactly one sample of `prepared.task.dataset` must have an id that is
     a `str` equal to it. The comparison is plain string equality, with no
     pattern matching, task scope or normalisation, so an id containing
     `:`, `*` or `[` compares as itself, and a dataset sample with the
     `int` id `12` does not match the logged `"12"`. A sample without an id
     still has `id=None` here, because positional ids are assigned when the
     run starts (`src/inspect_ai/_eval/run.py:224`), so it never matches.
     - No match: "the task's dataset holds no sample with the string id
       <id>".
     - More than one (a dataset the run would also refuse, through
       `ensure_unique_ids`): "the task's dataset holds more than one sample
       with the id <id>".

   Steward's datasets are static and use string ids (see "Who uses which
   shapes"). Exclusion needs none of this: it edits the logged record and
   never re-runs a sample.
5. Restricts the copied task to the targets and runs one scratch eval in a
   temporary local directory:

   ```python
   prepared.task.early_stopping = None
   prepared.task.dataset = prepared.task.dataset.filter(
       lambda sample: isinstance(sample.id, str) and sample.id in target_ids
   )
   eval_async(
       tasks=prepared,               # the ResolvedTask from step 3, which carries its models and sandbox
       model=None,                   # explicit, as eval_set passes it with ResolvedTasks
       solver=empty_attempt(),
       **run_args,                   # the caller's run arguments, as given
       sandbox_cleanup=True,
       ctl_server=False,
       fail_on_error=False,
       log_format="eval",
       log_buffer=1,
       log_dir=<tempdir>,
   )
   ```

   `run_args` holds the caller's approval, review and sentinel policies,
   epochs, sample limits, `model_cost_config`, `retry_on_error`,
   concurrency limits and generate config, each as given; the task, task
   arguments, models and sandbox already reached the `ResolvedTask` in step
   3. Zero adds only its own operational settings below.

   - **What the verdict reflects.** The scratch eval runs the caller's task
     under the caller's settings. A setting the caller leaves out takes the
     task's own value, as in `eval()`, so a run that was given a limit,
     generate option, policy or model at eval level is reproduced only when
     the caller gives it again. Zero does not check these settings, or the
     task's code, against the original run beyond the task match above;
     see Compatibility, "What zero runs".
   - **No second model resolution.** `model=None` is passed explicitly, as
     `eval_set()` passes it with `ResolvedTask`s
     (`src/inspect_ai/_eval/evalset.py:554`). An omitted `model` is
     `NOT_GIVEN`, which `eval_init()` resolves from `INSPECT_EVAL_MODEL`
     (`src/inspect_ai/_eval/eval.py:824`,
     `src/inspect_ai/model/_model.py:2621`): the prepared task would then
     run once per environment model.
   - **Sandbox cleanup.** Zero always cleans up its sandboxes, because
     nothing reads them afterwards.
   - **No control server.** `ctl_server=False` is passed explicitly. When it
     is omitted, `resolve_ctl_server(None)` reads `INSPECT_EVAL_CTL_SERVER`
     (`src/inspect_ai/_control/server.py:149-196`), and with `keep` the
     eval parks after scoring until released
     (`src/inspect_ai/_eval/eval.py:1240-1249`;
     [Control Channel](../docs/control-channel.qmd)), so zero would wait
     indefinitely before reading the verdicts. The scratch eval is internal
     to zero, so nothing needs to reach it over the control channel.
   - **Hooks.** The scratch eval is an ordinary eval, so installed hooks
     receive its run, task and sample events, with the solver
     `inspect_ai/empty_attempt` and the empty-attempt verdicts. A hook that
     exports runs (the MLflow example, `examples/hooks/mlflow_tracking.py`,
     creates a tracking run and exports metrics and the log at task end)
     records the scratch eval as a run of its own, including when zero then
     refuses the result; removing the scratch directory does not retract
     it. Zero does not suppress hooks; the docs say that the scratch eval is
     visible to them.
   - **Early stopping.** Zero clears `early_stopping` (`Task.early_stopping`,
     `src/inspect_ai/_eval/task/task.py:276`) on its copy of the task,
     because the runner may stop a sample-epoch before setup and scoring
     (`run.py:2729`) and the scratch log would still report success. Each
     target's empty attempt is a separate verdict, so nothing in the
     scratch run should stop early.
   - **Target selection.** The scratch eval passes no `sample_id` and no
     `limit`, so the runner runs every sample of the filtered dataset, and
     that dataset holds exactly the targets, by the string equality of step
     4. Selection by `sample_id` is not used, because its selectors are
     patterns read with a task scope (see "Sample-id selection" above): an
     id with `fnmatch` metacharacters or a task name containing `:` would
     each need escaping or qualification rules. The filter needs none.
     `filter()` returns a new dataset holding the same `Sample` objects, and
     only the copy's attribute is rebound, so the caller's task keeps its
     whole dataset. Every target has a string id, so the runner's
     positional-id assignment, which writes to `Sample` objects, leaves them
     alone. I verified this on a `mockllm` task named `benchmark:variant`
     with samples `a`, `benchmark:variant:a`, `case[1]` and `case1`:
     filtering to `a` and `case[1]` ran exactly those two, over two epochs,
     and the original task's dataset still held all four.
   - **Epochs.** The scratch eval runs the task's epochs, with the caller's
     `epochs` applied (step 3). Step 4 has refused a target whose epoch is
     beyond that count. The runner refuses `pass_at_k`, `pass_k_k` and `at_least_k` reducers with
     fewer than `k` epochs (`validate_reducer`,
     `src/inspect_ai/scorer/_reducer/registry.py:176`). `epochs` is global,
     so every targeted id runs every epoch. Zeroing a sample by bare id
     (every epoch, the CLI default) costs nothing extra; zeroing one epoch
     of a five-epoch log runs five empty attempts. The extra ones provision
     their sandboxes and run `Task.setup` and the scorers like any other.
     Only the targeted epoch scores are copied; the scratch log's other
     samples, results and reductions are ignored.
   - **Scratch log.** It is read back whole and the directory removed.
   - **Unbuffered.** `log_buffer=1` writes each scratch sample to the log
     file as it completes. With a larger buffer, the recorder holds the
     sample until a flush (`ZipLogFile.buffer_sample()`,
     `src/inspect_ai/log/_recorders/eval.py:1155`), and the held record
     shares its score objects with the ones end-of-run reduction and metrics
     receive (`condense_sample()`, `src/inspect_ai/log/_condense.py:402`).
     A reducer or metric that writes into its inputs (an epoch mean stored
     in the first score) would then change verdicts before they reach disk:
     the reviewer reproduced this with seven samples, two epochs and
     `max_samples=1`, and confirmed `log_buffer=1` prevents it. Each
     verdict is therefore serialized before any aggregation runs, and the
     verdicts zero reads back are the scorers' own.
6. Checks that the scratch eval completed. Its log must have `status ==
   "success"`. A cancelled or errored scratch log raises with its status and
   error, without editing anything. `eval_async` can return a cancelled log
   whose targets are already scored and error-free (verified by the
   reviewer under Trio with unfinished extra epochs), so valid target records
   alone do not show that the zero completed.
7. For every target, requires a scratch sample with the same `(id, epoch)`,
   no `error` and no `limit`, and applies the zero refusals under "Which
   score names a disposition covers". Any failure raises, naming every
   failing target and its cause, without editing anything. A missing scratch
   sample reads "the empty attempt of sample <id> (epoch <n>) did not run".
   An errored one reads "...did not score: <error>", and one that hit a
   limit reads "...hit its <type> limit". This is atomic where Steward's was
   not required to be: nothing is half-applied.
8. Stages the zero edits and computes metrics with the task's (see "Staged
   commit"), then calls `await anyio.lowlevel.checkpoint()`, which raises if
   the caller was cancelled meanwhile. Only then does it commit the staged
   samples and results, with no further await.

`zero_samples` is the synchronous wrapper. It initializes the display type
from `display` and runs the coroutine, as `score()` does: `anyio.run` with
the configured backend, or `run_coroutine` in a notebook.

### CLI

Two subcommands of `inspect log` (`src/inspect_ai/_cli/log.py`, beside
`recover`):

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME]
                    [--task TASK [-T NAME=VALUE ...] [--model ...] [--model-role ...]]
                    [--json]
inspect log zero    LOG_FILE TASK --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME]
                    [-T NAME=VALUE ...] [--task-config FILE]
                    [--model ...] [--model-base-url ...] [-M ...] [--model-config FILE]
                    [--model-role ...] [--epochs N] [--epochs-reducer ...]
                    [--approval ...] [--message-limit N] [--token-limit N] ...
                    [generate options: --temperature, --max-tokens, ...] [--json]
```

- `TASK` (zero) and `--task` (exclude) name the task as `inspect eval`
  names it: a task file, `file.py@name` or a registered name. Nothing is
  read from the log to find or build it. Zero's other options are `inspect
  eval`'s options of the same names, parsed by the same code: the
  task-argument, model, model-role, epochs, sample-limit, policy,
  concurrency and generate-config options move out of `eval_options`
  (`src/inspect_ai/_cli/eval.py:282`) into option groups that both
  commands apply, and `eval_command`'s conversion of them into `eval()`
  arguments into a helper both call. The trust model is that of `inspect
  eval`: the user names the code to run.
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
  interpreted. Zero's scratch eval runs a copy of the task whose dataset is
  filtered to the target ids by string equality, so no id is read as a
  pattern or a task scope.
- **Changed dataset.** A task's static dataset may have been reordered,
  shuffled or extended since the log was written; a string id still names
  the same sample. A targeted sample the dataset no longer holds, an integer
  id, and a task fed by a `SampleSource` are refused in step 4, and nothing
  is edited.
- **Another task.** A task whose name or scorer names differ from the log's
  is refused before anything runs
  (step 3 for zero, step 1 for exclusion with a task). A log with appended
  scores names scorers the task does not have, so it is refused this way.
- **Different settings or code.** Anything else about the task or its
  settings is taken as the caller gives it; the scratch log is not kept, but
  the zero edits record the scorer's answer and explanation for the empty
  attempt. A verdict that makes the task's metrics raise is refused by the
  staged metric computation, and the log is left unchanged; a metric that
  skips it without raising is not detected.
- **Concurrency.** The functions are synchronous over an in-memory log,
  except zero's scratch eval, which runs before any edit. The CLI's write is
  a conditional write on S3 and last-writer-wins locally, as `edit_score()`
  plus `write_eval_log()` is today.
- **Cancellation.** Cancelling `zero_samples_async` cancels the scratch eval
  and leaves the log unchanged. Sandbox cleanup runs as for any cancelled
  eval. If the scratch eval absorbs the cancellation and returns a cancelled
  log, step 6 refuses it. If the cancellation arrives after the scratch eval
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
- **Zero integer ids by checking that the dataset sample matches the logged
  one** (input, choices, target, setup, file names). The log does not record
  whether an integer id was positional, so the check has to establish
  correspondence from the sample's contents, and contents that match do not
  establish it: two samples can share every compared field and differ in
  metadata the scorer reads (inspect_evals' NIAH grader reads its question
  from metadata), and metadata may have been changed by the original
  solver. A string id is the author's own name for the sample and needs no
  comparison.
- **Exclude under every scorer's name, inferring the names of scorers that
  wrote nothing.** It would make an excluded errored sample count under every
  scorer's `unscored_samples`. The log cannot supply those names reliably:
  the runner names scorers in one ordered pass over the task's scorers,
  append names its scorers per sample from the keys each sample holds, and a
  log combining both does not say which entry a held key belongs to. A
  missing key already counts toward no metric, so the gain is only in the
  other scorers' unscored counts. Steward's rule (the held keys, or the first
  scorer for a sample with none) needs no inference.
- **Select the scratch targets with `sample_id`**, as Steward does from its
  separate eval-set process. Ids would have to be escaped for `fnmatch` and
  qualified with the running task's name, and a task name containing `:`
  cannot be qualified, because the scope ends at the first `:`. Zero runs
  in-process with the prepared task in hand, so filtering its dataset by
  string equality is literal with no encoding.
- **Zero dict and list verdicts**, refusing those with a `NaN` or `None`
  inside and those missing a key the log's other scores hold. Each rule
  infers from the log what the metrics read, and `aggregate()` and dict
  metrics count some keys of a value while skipping others. No real use asks
  for it yet (see Future improvements).
- **Rebuild the task and its run from the log**, as eval-retry does: import
  the log's task file or registered name with its recorded arguments,
  construct the recorded models and replay the recorded eval settings. It
  needs nothing from the caller, but the log does not hold what is needed
  to rebuild the run faithfully: it records only the settings in effect
  (not which came from the eval and which from the task, so a task edited
  since cannot be detected), it does not record a task factory's
  construction context, a retune made while a sample ran or the settings
  of an attempt a retry carried a record over from, and every setting
  rebuilt from it needs its own rules (model memoization and shared config
  objects, prices, base URLs, policies). It also imports code a log names.
  The caller already holds the task and the settings it ran with, as the
  shard merge's callers do, so zero takes them (decision: Ransom,
  2026-11-06).
- **Compare the caller's settings, or the task's declared settings, with
  the recorded ones.** It catches only edits to settings the log records,
  needs a rule per setting and location, refuses an unchanged task run
  with an eval-level value over its own, and never catches an edit to
  `Task.setup` code, the dataset or a scorer's internals. Zero compares
  names only, as the merge does, and leaves the rest to the caller.
- **Rebuild exclusion's metrics from the log with trust** (importing the
  log's task file, as `recompute_metrics(trust_log=True)` does). Exclusion
  instead takes the task when the registry cannot build the metrics, so it
  imports no task file the log names either.
- **Reduce epochs with the caller's task's reducer**, as a native run of
  that task would. A run given its reducer at eval level would then be
  recomputed faithfully only if the caller repeated it, which needs epoch
  options on exclusion and the runner's override rules (a count-only
  `--epochs` keeps the task's reducer, an explicit one replaces it). The
  header already records the reducers the run used, and recomputation
  reads them today; reading them is one rule for every caller (decision:
  Ransom, 2026-11-10).
- **Accept only header reducers that are already registered**, refusing a
  name that would load an entry point. It would close nothing, since other
  callers load registry code from the same names (decision: Ransom,
  2026-11-10).
- **Attribute each held key to a scorer when the scorer list was appended
  to.** Zero could compare options and score-event attribution per key, and
  refuse only ambiguous cases. Refusing any log whose scorer list differs
  from the task's is one rule, and the remedy (zero first, append afterwards)
  is simple.

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
  scores, such as `grader_failed`, reach the reducer as before.

  The reduced score's other fields can change under every reducer, including
  those whose value does not. The built-in reducers build the reduced score
  with `_reduced_score()` (`src/inspect_ai/scorer/_reducer/reducer.py:593`),
  which takes `metadata` from the first input and keeps `answer`,
  `explanation` and `reason` only when every input agrees. With the excluded
  epoch dropped, the reduced metadata comes from the first remaining epoch,
  and an answer and explanation on which the remaining epochs agree are
  kept where the excluded epoch's differing ones used to clear them; `mean`,
  `median`, `max` and `mode` over `[excluded, 1]` keep the value `1` and
  change these fields (verified through `reduce_scores()`). These fields are
  persisted in `log.reductions` and reach metrics that read the reduced
  view (`src/inspect_ai/_eval/task/results.py:220`). That is the intended
  meaning, an excluded epoch counts as one that never ran, and it applies
  to Steward's recomputed logs as well. Consumers of reductions
  (`log.reductions`, `results`, dataframes, the viewer) read the same
  structures.
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
- **Hooks.** A zero runs a scratch eval, which installed hooks see as an
  eval run of the task with the solver `inspect_ai/empty_attempt` (see step
  5). A hook that exports or notifies on every run does so for it, whether
  or not zero then commits the verdicts.
- **What zero runs (limitation).** Zero runs the task and settings the
  caller passes and checks only their names against the log ("Matching the
  task"; decision: Ransom, 2026-11-06). It does not check that the task's
  code, the options of its scorers and metrics, or the settings
  (models, generate config, limits, policies, epochs) are the ones the log
  ran with, and it does not detect a task edited since the log was
  written. When they differ, the verdict reflects what the caller passed.
  Examples: a `Task.setup` that generates or calls tools under another
  model, generate option or policy; a model-graded scorer whose grader, or
  the grader's config, differs; a scorer or setup that reads a limit; and
  edits to setup code, the dataset or a scorer's internals. A setting the
  original run was given at eval level is reproduced only when the caller
  gives it again; the epoch reducers are the exception, read from the log
  header ("Metrics from the task"). Passing the task and settings the log ran is the
  caller's responsibility, as for the shard merge and for eval-retry of an
  edited task. Each zero is recorded as a score edit with its reason and
  author, and the original score stays in `Score.history`, so a zero can be
  inspected and redone. The docs section states this. Exclusion with a task
  likewise recomputes with the task's metrics as passed.
- **Reducer arguments (limitation).** Both dispositions reduce epochs with
  the reducers the header records, rebuilt by name and `k`, as
  `recompute_metrics()` does. A custom reducer the run configured with other
  arguments is rebuilt with its defaults, so its recomputed reductions can
  differ from the run's. This is the existing limit of recomputation, and
  the docs section states it.
- **Eval-set retry.** Unchanged (decision: Ransom, 2026-11-04). A disposition
  does not clear `error`. An errored sample that was zeroed or excluded is
  therefore re-run by `inspect eval-retry` and eval-set retries, and the new
  record replaces the disposition, as with an errored sample scored under
  `score_on_error` today. The `inspect log` help and the docs section say so.
- **Steward.** Its edits keep working. Its `"excluded"` / `"zeroed"` strings
  are the new standard reasons, so its logs read the same as Inspect's. A
  Steward zero that copied a `NaN` verdict is not treated as zeroed: zeroing
  it again runs an empty attempt. Steward zeroes errored samples and clean
  ones it rules on, such as a successful sandbox escape
  (`docs/scanners.qmd:56` of meridianlabs-ai/inspect_steward), and zero
  accepts both. Steward can pass zero the task it loaded from its definition and the
  settings its eval set ran with; like its side run, zero then runs the
  current task.

## Security

- **Log contents** (the `log.eval` task file, task name, args, scorer and
  metric specs, recorded models and settings) are untrusted when the log
  is. The trust boundary is that of score editing today. Neither function
  imports a task file or path the log names, and zero builds no task,
  model or run setting from what the log records: they come from the
  caller. Both rebuild the epoch reducers the header records, and without a
  task exclusion rebuilds metrics with the existing untrusted resolver.
  These lookups use registry names only, never a task file the log names;
  they construct registered reducers and metrics named in the header
  (loading an installed package's entry point for a `pkg/name` name), and
  the metric resolver refuses options that name a model or a non-metric
  registry object. No stricter rule applies to them than to existing
  recomputation (decision: Ransom, 2026-11-10). As in existing recomputation
  (`recompute_metrics()`), a score key outside the scorer list is looked up
  by registry name (`ScorerInfo.from_name()`), which can construct an
  already-registered scorer or scanner, or load an installed package's
  Inspect entry point for a `pkg/name` key; it never imports a path. The
  names compared with the caller's task, the sample ids and the score
  values are otherwise compared or copied as data.
- **The caller's task.** A task spec given to `zero_samples` or on the
  command line is imported and run, with the trust model of `inspect eval`:
  the user names the code. A file that runs an evaluation at module scope
  runs it when imported, as under `inspect eval`.
- **Reason and author** are free text from the local caller: the Python
  caller or the CLI user. A reason that is the literal `"UNCHANGED"` is
  refused, because a score edit would drop it. They are stored as data in
  `ProvenanceData` and
  `Score.explanation`, and the viewer renders explanations as it renders any
  scorer's explanation. They are not interpolated into commands or paths.
- **Sample selectors** are compared with logged ids and never become paths or
  queries. The scratch eval's dataset holds only the samples whose ids equal
  the targets as strings. An id therefore cannot widen the scratch run to
  other samples, which would run their setup, sandboxes and graders.
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
  - `mean`, `median`, `max` and `mode` over `[excluded, kept]`, where the
    excluded epoch's score has its own answer, explanation and metadata:
    the reduced value equals the reduction of `[kept]`, and so do the
    reduced `metadata` (the kept epoch's), `answer` and `explanation` (the
    kept epoch's, not `None`) and `reason`.
- `tests/scorer/test_score_editing.py`:
  - `exclude_samples`, on a multi-scorer sample with a deduplicated name
    (`match1`), an appended one and a solver-written one: every score
    becomes `NaN` with reason, explanation and provenance. `history[0]` is
    the original, and `answer` and `metadata` are unchanged, except that a
    legacy `metadata["unscored_reason"]` on one score is removed from the
    current score and kept in `history[0]`, also after a write and read.
  - `exclude_samples` on an errored sample with no scores, in a log with
    scorers `[match(), includes()]`: it gets one excluded score, under
    `match`, and none under `includes`; `match`'s `unscored_samples` counts
    it and `includes`' counts are unchanged.
  - An errored sample with no scores, in a log whose first scorer has
    `metrics=[]` and always returns `None`: the score is created under that
    scorer's name, and metrics recompute.
  - An appended log in which an errored sample holds an appended score under
    the vacant `probe` key: the exclusion edits that key and creates no
    other.
  - `exclude_samples` on a solver-only log with task-level metrics
    (`log.eval.scorers` `None`): the solver key is excluded and metrics
    recompute. A sample of that log holding no score is refused, with the
    log unchanged.
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
  - Staged commit with callbacks that mutate and succeed: a zero over two
    epochs with values 0 and 1, under a reducer that writes the mean into
    the first epoch's score and a metric that changes a target's sample
    metadata. The committed zeroed scores equal the empty attempt's verdicts
    and their last history entries, the committed metadata is the target's,
    and untargeted samples are unchanged.
  - `exclude_samples(..., task=...)`: a log whose metric is defined in a test
    module and not registered when the log is read, excluded with the task:
    metrics recompute with the task's metric and the log's task file is not
    imported (asserted by patching `load_module`). The same log without a task is
    refused with the untrusted resolver's `LookupError`, whose advice names
    the `task` argument, and is unchanged.
  - Same recomputation: a log with a solver-written key on an untargeted
    sample, excluded with a task and, separately, without one, and zeroed:
    the committed `results` and `reductions` equal those of
    `recompute_metrics()` (with the same metrics) run on a copy of the log
    holding the same edits.
  - Score events kept: on the log `eval(..., log_format="json")` returns
    (where a sample's final score is the object its `ScoreEvent` holds) and
    on a `.eval` log read back, a task-scored sample excluded, the same
    sample zeroed, and a solver-only sample excluded: each pre-existing
    `ScoreEvent` serializes exactly as before the call, the new
    `ScoreEditEvent`s are added, and on a refusal (a metric that raises)
    the whole input log serializes as before.
  - Task match for exclusion: a task with another name, and one with another
    scorer name, are each refused naming the field, with the log unchanged;
    a task whose scorer's options or metric differ is accepted.
  - Header reducers: for each of `pass_at(5)`, `pass_k(5)` and
    `at_least(5)`, a log written with `eval(task, epochs=Epochs(5, r))` on a
    task declaring one epoch and the `mean` reducer, excluded with that
    task and without a task: the recomputed results and reductions over the
    remaining epochs equal those of a native run over the same scores
    reduced with `r`. A log written with a task declaring `majority` and no
    eval-level reducer reduces with `majority`, and one whose header
    records no reducer with `mean`.
  - Reducer arguments: a registered custom reducer with a non-`k` argument,
    run with a non-default value, is rebuilt with its default on exclusion,
    as `recompute_metrics()` rebuilds it.
  - A header reducer the registry cannot build is refused with the
    `REDUCER_MISSING` message, with and without a task, and the log is
    unchanged.
  - Refusals that raise and leave the log unchanged: unknown selectors, a
    `started` log, an empty reason, the reason `"UNCHANGED"` (for both
    functions, on a sample whose score has an explanation), and, without a
    task, an unresolvable metric.
- `tests/log/test_zero_samples.py` (new: no existing file covers running an
  eval to edit a log). The fixture is a task with string sample ids, whose
  `Task.setup` sets a metadata flag and whose main solver would generate; it
  is passed both as a built `Task` and as a `file.py@name` spec with task
  arguments.
  - The happy path: the zeroed scores equal the empty attempt's (`I` for
    `match()`), with reason `zeroed` and the original in `history[0]`. The
    transcript and `error` are unchanged, `Task.setup` ran, and the scratch
    run has no main-solver `ModelEvent`.
  - An errored sample is zeroed.
  - Ids `case[1]`, `case*`, `case?` and `t1:a:b`, in a dataset that also
    holds `case1`, `caseX` and `a:b`: the scratch log holds only the
    targets.
  - The scratch eval goes through the real override path,
    `eval_async(..., solver=empty_attempt())`: its log records the solver
    `inspect_ai/empty_attempt`, and the task's main solver does not run.
  - A multi-epoch log with targets `a/1` and `b/2`: `a/2` and `b/1` run in
    the scratch eval, and those samples are left unedited.
  - Epoch reducers: zeroing epoch 1 of a log written with `Epochs(5, r)`
    succeeds for each of `pass_at_5`, `pass_k_5` and `at_least_5`, with the
    task declaring the epochs and, separately, with a one-epoch task given
    to `eval()` with `epochs=Epochs(5, r)` and to zero with `epochs=5`: the
    results are reduced with the header's `r`.
  - Task preparation, run in a fresh context and in a context whose active
    model and a `grader` role are unrelated `mockllm` models: a task factory
    that calls `get_model()` and one that reads the `grader` role while
    constructing the task both receive the models passed to zero, and the
    caller's active model and roles are unchanged afterwards.
  - A task spec whose file defines its own epoch reducer and metric, absent
    from the registry before the zero: zeroing succeeds in a fresh process,
    with results computed by the task's metric and, through the header's
    name, the reducer the imported file registered.
  - Nothing from the log: zeroing a log whose header names a task file that
    does not exist and a model provider that is not installed succeeds with
    the caller's task and a `mockllm` model; the task file the log names is
    not imported and no model is built from its header.
  - Integer ids, each refused before the scratch eval with the log
    unchanged: a log of a task whose dataset samples have no ids, run with
    and without `sample_shuffle`; and a dataset with explicit `int` ids. A
    logged `"12"` whose dataset sample now has the id `12` is refused as no
    longer held.
  - String ids: a log written with string ids, zeroed after the task file
    reorders its dataset and adds a sample, zeroes the samples with those
    ids. A string id the dataset no longer holds is refused before the
    scratch eval.
  - Sample sources: a task whose `SampleSource` has an empty seed and later
    produces samples is refused before the scratch eval, with the log
    unchanged, also when its produced samples carry string ids.
  - Models: with `model` given, the scratch eval's header records it and
    `INSPECT_EVAL_MODEL` is not read; with `model` omitted, it is read as
    for `eval()`; a list of models is refused before preparation.
  - Task match: each refused before preparation finishes running anything,
    with the log unchanged and the message naming the field: another task
    name; an errored target and a scored neighbour, after `inspect score
    --action append` of a differently configured instance of the task's
    scorer, which wrote under the target's vacant key; a task that added a
    scorer, and one that reordered two. A task whose scorer's options or
    metric differ is accepted, and its verdicts are copied and its metrics
    used (they are the caller's responsibility).
  - Targeted epochs: zeroing epoch 3 of a three-epoch log with a one-epoch
    task and no `epochs` is refused before the scratch eval, naming the
    epochs the log ran.
  - Appended log with matching headers (accepted): the same append, then the
    task updated to `[probe(0), probe(1)]`. Zeroing the errored target
    writes `probe(0)`'s verdict under `probe`, with the appended `probe(1)`
    score as `history[0]`, and `probe(1)`'s verdict under `probe1`.
  - Running eval: zeroing a landed log while another eval in the process
    holds a live sample (asyncio and Trio) is refused before preparation,
    and the running eval's active samples and concurrency registries are
    unchanged; that eval then finishes normally.
  - Early stopping: a task whose early-stopping manager stops after a
    failure, whose original log holds both epochs: zeroing every epoch runs
    both empty attempts and zeroes both, and the task's own
    `early_stopping` object and the log are otherwise unchanged.
  - Task names: a task named `benchmark:variant` whose dataset holds `a`
    and `benchmark:variant:a`, zeroing `a`: only `a` runs in the scratch
    eval, and the factory's task keeps its whole dataset. A log of task
    `old`, zeroed with the task renamed to `new`, is refused for its task
    name before the scratch eval, with the log and the task's dataset
    unchanged.
  - Prices before preparation: a registered task factory that reads
    `get_model_info()` cost for the primary model, a `grader` role and both
    members of a `panel` ensemble while it constructs a scorer, with
    `model_cost_config` given as a dict and, separately, as a JSON file:
    the factory sees the configured prices, as under `eval()` with the same
    arguments.
  - Scratch aggregation: seven samples, two epochs, `max_samples=1`, and a
    reducer that writes the epoch mean into its first input, plus a metric
    that mutates its inputs and succeeds: the zeroed scores equal each
    scorer's per-epoch verdict.
  - The caller's task is not changed: a built `Task` with an early-stopping
    manager, and a registered factory that returns the same cached `Task`,
    each zeroed on a log whose target the dataset no longer holds, so zero
    refuses after preparation, and once successfully: the task keeps its
    dataset, epochs and manager, and a later eval of it stops early as
    before.
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
    - structured verdicts: an empty attempt whose scorer returns `{"x": 0}`,
      one returning `{"score": NaN, "confidence": 100}` (HLE's shape), and
      one returning `[0, 1]`; each refused as structured;
    - an empty attempt whose scorer returns `"UNCHANGED"` as its value, and,
      separately, as its answer and as its explanation, each on a sample
      that already holds a score under that name: refused as reserved text;
    - two scorers, one scored and one unscored;
    - a conditional scorer that scored the original and returns `None` on the
      empty attempt;
    - a solver-written score;
    - a `Task.setup` that writes `state.scores` while the task's only scorer
      returns `None` on the empty attempt, both with and without setting
      `state.completed`: refused with the setup-scores message, and the
      input log's samples, results and reductions are unchanged;
    - a `Task.setup` that generates twice, zeroed with `message_limit=1`:
      the scratch eval hits the limit and the target is refused as having
      hit a limit; likewise a `token_limit` with an `"output"` metering
      type;
    - policies passed to zero, on a task with none of its own, with a
      `Task.setup` that makes one local tool call scored by whether the tool
      ran: an approval policy that rejects the tool, a tool reviewer that
      terminates the sample, and a sentinel that rejects the tool (the
      repository's fake sentinel integration,
      `tests/test_helpers/fake_sentinel.py`). Under the rejecting approval
      policy and the sentinel the tool does not run in the scratch eval
      (asserted through its side effect) and zero copies the "not run"
      verdict. A tool reviewer examines a call after it has run
      (`docs/review.qmd`), so under the terminating reviewer the tool runs
      once, the scratch sample ends with an operator limit, and zero refuses
      the target;
    - a log with no task scorers;
    - a task whose scorer returns a scalar where its dict metrics expect a
      dict: the `TypeError` is re-raised and the samples, results and
      reductions are those of the input log.
  - Settings are the caller's: a log written with `temperature` unset and
    no message limit, zeroed with a task now declaring `message_limit=20`
    and `temperature=0.7` and a `Task.setup` that generates and a scorer
    that reads both: zero succeeds, the scratch eval's header records the
    task's values, and the zeroed score carries the reason and the original
    in `history[0]`.
  - A scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
  - Control server: with `INSPECT_EVAL_CTL_SERVER=keep` set (via
    `monkeypatch`), zero completes and commits its edits; the scratch eval
    binds no control server and never enters the post-scoring park
    (asserted by patching the server start and the release wait).
- `tests/_cli/`: `inspect log exclude|zero` parse `--sample`, `--epoch`,
  `--reason` and `--author`, write in place, and print the per-sample lines
  and the `--json` envelope. `inspect log zero LOG TASK` passes `-T`,
  `--model`, `--model-role`, `--epochs`, a sample limit and a generate
  option through to the scratch eval (asserted on its header), and
  `inspect log exclude --task` recomputes with the task's metric and, for
  a log written with `eval(task, epochs=Epochs(5, "pass_at_5"))` on a
  one-epoch task, with the header's `pass_at_5` reducer.
  `inspect eval`'s own option tests pass unchanged after its options move
  into shared groups.
- Schema drift: the OpenAPI and TypeScript drift checks pass after the
  regeneration step.

No test needs network or a provider key. A Docker sandbox variant of the
zero test is not needed: the `local` sandbox exercises the same provisioning
path.

## Implementation plan

1. **Vocabulary and epoch reduction.**
   - Add the two reasons and `score_is_excluded` to
     `src/inspect_ai/scorer/_metric.py`.
   - Drop excluded epochs in `reduce_scores()`
     (`src/inspect_ai/_eval/task/results.py`).
   - Document the reasons in `docs/scoring-policy.qmd`'s reason table, and
     the reduction rule under "Reducing Epochs" in `docs/metrics.qmd`.
   - Regenerate `src/inspect_ai/_view/inspect-openapi.json` and the ts-mono
     types with the land-ts-mono procedure.

   Tests: the reducer tests.
2. **Exclude.**
   - `task_difference()` and `TaskDifference`, new in
     `src/inspect_ai/log/_task_match.py`.
   - `apply_model_cost_config()` in `src/inspect_ai/_eval/eval.py`, factored
     out of `eval_async()`.
   - `log_reducers()`, factored out of `resolve_log_metrics()`, and
     `task_log_metrics()` in `src/inspect_ai/log/_metric.py`.
   - `src/inspect_ai/log/_disposition.py`: `SampleSelector`,
     `DispositionResult`, `prepare_task()`, and `exclude_samples` with its
     score-key rule and optional task.
   - Exports in `src/inspect_ai/log/__init__.py`.
   - The `inspect eval` options for the task, models, epochs, sample
     limits, policies, concurrency and generate config split out of
     `eval_options` (`src/inspect_ai/_cli/eval.py`) into groups, with their
     conversion into `eval()` arguments in a shared helper; `inspect eval`
     behaves as before.
   - `inspect log exclude` in `src/inspect_ai/_cli/log.py`, with `--task`,
     and the default author helper moved from
     `src/inspect_ai/_cli/ctl/_config.py` to `src/inspect_ai/_cli/util.py`.
   - A "Zeroing and Excluding Samples" section in `docs/eval-logs.qmd`,
     including the retry behaviour, passing the task, and, for a running
     eval, `inspect ctl sample cancel --action cancel` followed by these
     commands once the log lands.

   Tests as above.
3. **Zero.**
   - `src/inspect_ai/_eval/zero.py`: `empty_attempt`, `empty_attempt_check`,
     `SetupWroteScores` and the scratch eval.
   - `zero_samples` / `zero_samples_async` in `_disposition.py`, with a
     function-local import of `_eval.zero`.
   - `inspect log zero LOG TASK` with the shared eval option groups, and the
     docs section extended: zero runs the task and settings the caller
     passes and checks only their names against the log (with the examples
     under Compatibility, "What zero runs"), and hooks see the scratch eval.

   Tests as above.

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
- **A sample-level exclusion field**, should eval-set retry or the viewer
  later need a per-sample mark that does not depend on reading score
  reasons. `EvalSample.invalidation` cannot serve: an invalidated sample is
  one to re-run.
- **Zero for dict and list verdicts**, for scorers such as HLE's. It needs
  a rule for when a structured verdict counts under every metric the log
  computes: no `NaN` or `None` among its values, and every key that a metric
  reading named keys (`aggregate(..., on_missing="skip")`) expects, without
  inferring those keys from other samples' scores.
- **Zero for integer ids**, for datasets that do not give their samples
  string ids, if a reliable way to establish that a logged integer id names
  the same sample turns up (the log would have to record whether its ids
  were assigned by position).
- **Live zero** (`inspect ctl sample cancel --action zero`), for queued and
  initializing samples. The runner would resolve it at start by running a
  setup-only plan (`Task.setup` alone) and passing each scorer's result
  through the zero edit. Beyond what live exclusion needs, it needs a
  disposition carried across `retry_on_error` re-parks, and the zero
  refusals applied at scoring time.
- **Checking the caller's task against the log.** Zero compares names only.
  A fingerprint of the task recorded in the log (its source, dataset and
  the options of its scorers, metrics and reducer), and a record of which
  settings came from the eval, would let zero refuse, or warn about, a task
  or settings other than the ones the log ran.

## Not this design

- Tightening the score-key lookup in recomputation. `eval_results()` looks
  up a score key outside the scorer list by registry name
  (`ScorerInfo.from_name()`), which can construct a registered scorer or
  scanner or load a package entry point, for every caller that recomputes
  metrics (`recompute_metrics()`, `edit_score()`, these dispositions).
  Limiting it to registered names without construction, or to default
  metrics for such keys, is a change to `eval_results()` for all of them.
  The same holds for the header's metric and reducer names, which
  `resolve_log_metrics()` and `log_reducers()` look up for every
  recomputation.

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
    recompute. The same gap reaches scalar scorers: an original `probe`
    that never scored and an appended `probe` written under `probe` report
    counts `[0, 2]`, which a bare `recompute_metrics()` turns into `[2, 0]`
    (`eval_results()` assigns positional names, `results.py:157`).
  - `scorers_from_metric_dict()` expands glob metric keys from a sample's
    current dict value and keeps the literal glob when none is left
    (`results.py:500`). After every score of such a scorer becomes `NaN`,
    the concrete `x`, `y` rows are replaced by a `*` row.
