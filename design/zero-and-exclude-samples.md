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
`inspect_ai.log` and two `inspect log` subcommands. Zero runs its empty
attempts in a scratch eval of the same task, restricted to the targeted
samples and run with the log's recorded models and with the run settings
eval-retry restores from a log (epochs, approval, review and sentinel
policies, sample limits, generate config), through a helper the two share.
Zero refuses a sample whose limits were retuned while it ran, and a log too
old to record the limits each sample ran under. It copies the verdicts in.
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
  - the sandbox (`resolve_task_file_sandbox`);
  - the run settings, from `log.eval.config` (`:1844-1935`): epochs and
    reducers, the approval, review and sentinel policies, the message,
    token (with its metering type), turn, time and working limits,
    `retry_on_error`, the concurrency limits and the sandbox flags, each
    overridable by a retry argument, and the generate config from
    `log.plan.config` (`:1943-1952`). It does not restore `cost_limit`.
    The runner applies an eval-level policy or limit to its run-local copy
    of the task (`src/inspect_ai/_eval/run.py:333-412`), so reloading the
    task factory does not recover one; only these arguments do.

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
  any `sample_shuffle` (`src/inspect_ai/_eval/loader.py:106`). That id is an
  `int`, and so is the id a file or Hugging Face loader assigns with
  `auto_id=True` (`data_to_samples`, `src/inspect_ai/dataset/_util.py:129`).
  Every id Inspect assigns to a static dataset is therefore an `int`; a
  string id was supplied by the task's author. `ensure_unique_ids`
  (`src/inspect_ai/_eval/run.py:1457`) refuses a dataset with a repeated id,
  including an `int` and a `str` with the same `str()` form.
- **Per-sample effective limits.** `inspect ctl config` retunes a running
  task's message, token and time limits through a per-task override store
  (`src/inspect_ai/util/_limit_overrides.py:45`), which applies to the
  task's running samples from their next limit check and to samples started
  later (`:71-80`). The log header keeps the launch values; each
  `EvalSample` records the ceilings it ran under in `message_limit`,
  `token_limit` with `token_limit_type`, and `time_limit`
  (`src/inspect_ai/log/_log.py:598-611`, written at
  `src/inspect_ai/_eval/task/run.py:3647-3653`). With no retune these equal
  the header's values, except that the sample records the metering type
  `"all"` for a plain token count where the header records none (verified
  with `mockllm` runs with and without limits). The `.eval` writer drops
  `None` fields (`src/inspect_ai/log/_recorders/eval.py:1228`), so a
  missing field reads as "no limit". Retunes arrived one release before the
  sample fields: Inspect 0.3.260 can retune but records no per-sample
  message or time limit, and 0.3.261 is the first release that records all
  three. The log records the Inspect version that wrote it in
  `log.eval.packages["inspect_ai"]`.
- **Epoch reducers on recompute.** `resolve_log_metrics()` builds the epoch
  reducers before it considers importing the task file for missing metrics
  (`src/inspect_ai/log/_metric.py:64`).
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
`.eval` logs of tasks loaded from a file or the registry, with static datasets
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

- zero for tasks that eval-retry can reload (file or registered) and that
  have scorers, run with the log's recorded models; static datasets; samples
  with string ids that the task's dataset still holds; tasks whose scorers
  are the ones the log records; scorers whose empty-attempt verdict is a
  single `str`, `int`, `float` or `bool`; and samples whose scores all come
  from those scorers;
- exclusion for any landed log, for a sample that holds a score or of a log
  that names a scorer.

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
so the only single value that metrics skip is a root `NaN`. The helper is a
check on the raw value only:

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
(step 8 of `zero_samples_async`): the task's scorers must be the ones the log
records, with the same names and options, in the same order. A log with
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

@solver(name="inspect_ai/empty_attempt_check")
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

@solver(name="inspect_ai/empty_attempt")
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
still sees a `Plan` (`src/inspect_ai/solver/_solver.py:212-226`). I verified
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
errors the scratch sample, and step 8 refuses that target with the error's
message, leaving the log unchanged. The main solver is skipped, so
`Task.setup` is the only solver that can have written a score by then.

The finish solver does not run when a step raises (`_plan.py:46`). A
`Task.setup` that raises errors the scratch sample, and one that exceeds a
sample limit records `limit` on it; step 8 refuses a scratch sample with
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
- Metrics are resolved before the first edit (`resolve_log_metrics()`). A log
  whose metrics cannot be rebuilt is therefore left unchanged, with the
  existing `LookupError` or `DisallowedRegistryArg` and its advice.

**Staged commit.** Both functions apply their edits to copies of the target
samples, and compute metrics on a second, disposable view of the log, before
the input log changes:

1. `edited` maps each target to `deepcopy(sample)`. The edits are applied to
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
3. `compute_log_metrics(view, resolved)` runs once. It assigns
   `view.results` and `view.reductions`.
4. Only when that returns are the target entries of `log.samples` replaced
   by their edited copies from step 1, and `log.results` and
   `log.reductions` by the view's. The view's samples are discarded, with
   whatever a callback did to them, so a reducer that stores a value in a
   score it was given (a mean written into the first epoch's score) changes
   neither the committed zeroed or excluded scores nor any other sample.
   Nothing in this step awaits or raises.

An edit, reducer or metric that raises, or mutates its inputs, therefore
leaves the input log as it was until the commit, and the committed targets
are exactly the edits. For zero this is how a verdict that does not fit the
log's metrics is refused: for example, a task edited since the log was
written now returns a scalar where the logged dict metrics expect a dict,
and `eval_results()` raises `TypeError` (`results.py:543`). Zero re-raises
it as "the empty-attempt verdicts do not fit the log's metrics (<error>);
the task may have changed since the log was written".

`exclude_samples`:

1. Resolves metrics with the caller's `trust_log`, as `recompute_metrics()`
   does. With `trust_log=True` this may import the task file, so it runs
   inside `inline_eval_set_suppressed()`. A log with no task scorers is
   accepted; it is refused only for a target that holds no score.
2. Builds the exclusion edits for every target that is not already excluded
   (the keys it holds, or the first scorer's name), and commits them as
   above.

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

   The run settings eval-retry reads from `log.eval.config` move into a
   second helper, which both call:

   ```python
   # src/inspect_ai/_eval/eval.py, beside log_task_spec()
   class RecordedEvalArgs(TypedDict):
       """The `eval_async()` arguments that reproduce how a log's samples ran, read from its recorded config."""
       epochs: Epochs | None              # Epochs(config.epochs, config.epochs_reducer), None when unrecorded
       approval: ApprovalPolicyConfig | None
       review: ReviewPolicyConfig | None
       sentinel: SentinelConfig | None
       message_limit: int | None
       token_limit: int | TokenLimit | None   # TokenLimit(tokens, type) when a type other than "all" is recorded
       turn_limit: int | None
       time_limit: int | None
       working_limit: int | None
       cost_limit: float | None
       retry_on_error: int | None
       max_samples: int | None
       max_subprocesses: int | None
       max_sandboxes: int | None
       sandbox_cleanup: bool | None
       sandbox_prebuilt: bool | None

   def recorded_eval_args(eval_log: EvalLog) -> RecordedEvalArgs: ...
   ```

   `eval_retry_async` builds its arguments from `recorded_eval_args()` and
   then applies its own caller overrides with the expressions it uses today
   (`max_samples or recorded`, `sandbox_cleanup if not None else recorded`,
   and so on). Zero passes the dict to its scratch eval as it is, apart from
   the overrides in step 6. A run setting added to the helper later reaches
   both, so zero cannot fall behind what retry restores. The selection
   (`limit`, `sample_id`, `sample_shuffle`), logging, display, notification
   and error-policy (`fail_on_error`, `continue_on_fail`, `score_on_error`)
   settings stay in `eval_retry_async`: they say which samples run and how
   the run reports, not what a sample does. The generate config travels in
   `LogTaskSpec.config`.

   The helper also restores `cost_limit`, which eval-retry drops today, so
   an eval-retry of a log written with an eval-level cost limit keeps it
   (see Compatibility). The other values are the ones retry passes now.

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
   prepared = replace(prepared, task=copy(prepared.task))
   prepared.task.early_stopping = None
   ```

   Zero rebinds two attributes on its copy of the task, `early_stopping`
   here and `dataset` in step 6.

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
   - **Early stopping.** Zero clears `early_stopping` (`Task.early_stopping`,
     `src/inspect_ai/_eval/task/task.py:276`) on its own shallow copy of the
     prepared `Task`, because the runner may stop a sample-epoch before
     setup and scoring (`run.py:2729`) and the scratch log would still
     report success. Each target's empty attempt is a separate verdict, so
     nothing in the scratch run should stop early. The copy matters because
     task resolution can return an instance the caller owns: a factory may
     return a cached `Task`, and `resolve_tasks()` keeps the instance it
     returns (`src/inspect_ai/_eval/loader.py:114`). Clearing the field on
     that instance would disable early stopping for every later eval of the
     task, even after zero refused. `ResolvedTask` is a frozen dataclass
     (`src/inspect_ai/_eval/task/resolved.py:14`), so zero replaces it with
     `dataclasses.replace(prepared, task=copy(prepared.task))`, as a normal
     run shallow-copies the task before applying its overrides
     (`src/inspect_ai/_eval/run.py:261`). `task_with()` is not used, because
     it changes the task it is given. Zero only rebinds attributes on the
     copy, so the shared nested state is not changed.

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
   original run, and that it ran under the limits the scratch eval
   replays, and refuses otherwise. Three checks, all before the scratch
   eval:

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
     - No match: "the task's dataset no longer holds a sample with the
       string id <id>".
     - More than one (a dataset the run would also refuse, through
       `ensure_unique_ids`): "the task's dataset holds more than one sample
       with the id <id>".

   **Recorded limits.** The scratch eval replays the log's header limits
   (step 6), which are not the limits a sample ran under when an operator
   retuned it with `inspect ctl config` (see "Per-sample effective limits"
   above). Zero does not replay a retune; it refuses the target instead:

   - The log must be written by an Inspect that records each sample's
     effective limits: `log.eval.packages["inspect_ai"]` must be present and
     at least 0.3.261, compared with the PEP 440 ordering
     `_installed_version()` already applies (`src/inspect_ai/_util/version.py`;
     its parsing moves into a `parse_version(raw)` helper beside it), so a
     development build before that release counts as older. Otherwise: "<log>
     was written by Inspect <version or 'an unknown version'>, which does not
     record the limits each sample ran under, so zero cannot tell whether
     they were retuned; zero needs a log written by Inspect 0.3.261 or later:
     exclude the samples instead". A missing field is never read as an equal
     limit.
   - For every targeted record (each targeted epoch), three pairs must be
     equal: the record's `message_limit` and the replayed `message_limit`;
     its `time_limit` and the replayed `time_limit`; and its
     (`token_limit`, `token_limit_type`) and the replayed token limit,
     normalized to (count, type) with type `"all"` for a plain count and
     (`None`, `None`) for no limit. `None` on both sides is equal. Otherwise:
     "sample <id> epoch <n> ran under <field> <recorded>, not the log's
     <replayed> (it was retuned while it ran); zero replays the log's limits
     only: exclude the sample instead".

   The turn, working and cost limits cannot be retuned, so the header holds
   the values every sample ran under. Targets may differ among themselves only
   through a retune, and each retuned one is refused by name, so every target
   that passes ran under the limits the scratch eval passes. A record holds
   the ceilings in force when the sample ended, so a retune that was set and
   then cleared while a sample ran leaves no trace on it, and zero cannot
   detect that one.

   Steward's datasets are static and use string ids (see "Who uses which
   shapes"). Exclusion needs none of this: it edits the logged record and
   never re-runs a sample.
6. Restricts the copied task to the targets and runs one scratch eval in a
   temporary local directory:

   ```python
   prepared.task.dataset = prepared.task.dataset.filter(
       lambda sample: isinstance(sample.id, str) and sample.id in target_ids
   )
   run_args = recorded_eval_args(log)   # step 3's helper, shared with eval-retry
   run_args["sandbox_cleanup"] = True
   eval_async(
       tasks=prepared,               # the ResolvedTask from step 4, which carries its models and sandbox
       model=None,                   # explicit, as eval_set passes it with ResolvedTasks
       solver=empty_attempt(),
       **run_args,
       fail_on_error=False,
       log_format="eval",
       log_buffer=1,
       log_dir=<tempdir>,
       **dict(spec.config),          # log.plan.config, as eval-retry passes it
   )
   ```

   Every argument that says how a sample runs comes from
   `recorded_eval_args()`; zero lists only its own operational settings.
   It always cleans up its sandboxes, whatever the log recorded, because
   nothing reads them afterwards. Its other settings are the ones below.

   - **No second model resolution.** `model=None` is passed explicitly, as
     `eval_set()` passes it with `ResolvedTask`s
     (`src/inspect_ai/_eval/evalset.py:554`). An omitted `model` is
     `NOT_GIVEN`, which `eval_init()` resolves from `INSPECT_EVAL_MODEL`
     (`src/inspect_ai/_eval/eval.py:824`,
     `src/inspect_ai/model/_model.py:2621`): the prepared task would then
     run once per environment model, and an unavailable environment provider
     would fail the scratch eval before the task ran.
   - **Policies.** The recorded approval, review and sentinel policies are
     passed as eval-level policies, as eval-retry passes them. The runner
     records a task's own policy in the same fields when no eval-level one
     overrode it (`src/inspect_ai/_eval/run.py:388-408`), so the scratch
     eval's `Task.setup` runs under the policies the original attempt ran
     under. Omitting them would let a setup tool call that the recorded
     approver rejected, or that the recorded reviewer or sentinel stopped,
     run and produce a different, error-free verdict. `eval_async` resolves
     the policies before any sample runs (`src/inspect_ai/_eval/eval.py:845`,
     `:861`), so one that cannot be rebuilt (an approver or reviewer the
     imported task file does not register, a sentinel whose package is not
     installed) raises there and zero refuses with the log unchanged, as
     eval-retry would. A recorded policy that asks a human asks during the
     scratch eval, as it does during eval-retry.
   - **Sample limits.** The recorded message, token (with its metering type),
     turn, time, working and cost limits are passed. The runner records a
     task's own limits there when no eval-level limit overrides them
     (`src/inspect_ai/_eval/run.py:333-368`), and step 5 has refused every
     target that a retune moved off them, so they are the limits each target
     ran under. An omitted limit would fall back to the task's default,
     which is none for a limit that was given only to `eval()`; a
     `Task.setup` that generates would then run unbounded and produce an
     error-free verdict that step 8 accepts, where the original run would
     have hit the limit.
   - **Cost prices.** A log records its cost ceiling, not the prices it was
     computed with (`set_model_cost()`, `set_model_info()` or
     `--model-cost-config` are not persisted). With a recorded `cost_limit`,
     the scratch eval's native price check (`resolve_model_costs`,
     `src/inspect_ai/model/_util.py:67`, called from
     `src/inspect_ai/_eval/eval.py:871`) requires cost data for the primary
     model and every model role, and raises `PrerequisiteError` naming the
     unpriced models before any sample runs, so zero refuses with the log
     unchanged. Prices in Inspect's model database need nothing. A Python
     caller restores custom prices before calling zero with
     `set_model_cost()`, or `set_model_info()` for a model the database does
     not know ([Model Cost](../docs/setting-limits.qmd#model-cost)). A fresh
     `inspect log zero` process has only the database prices and those the
     task file registers when it is imported; zero adds no pricing flag or
     stored pricing format, and the docs section says so.
   - **Hooks.** The scratch eval is an ordinary eval, so installed hooks
     receive its run, task and sample events, with the solver
     `inspect_ai/empty_attempt` and the empty-attempt verdicts. A hook that
     exports runs (the MLflow example, `examples/hooks/mlflow_tracking.py`,
     creates a tracking run and exports metrics and the log at task end)
     records the scratch eval as a run of its own, including when zero then
     refuses the result; removing the scratch directory does not retract
     it. Zero does not suppress hooks; the docs say that the scratch eval is
     visible to them.
   - **Target selection.** The scratch eval passes no `sample_id` and no
     `limit`, so the runner runs every sample of the filtered dataset, and
     that dataset holds exactly the targets, by the string equality of step
     5. Selection by `sample_id` is not used, because its selectors are
     patterns read with a task scope (see "Sample-id selection" above): an
     id with `fnmatch` metacharacters, a task renamed since the log was
     written, or a task name containing `:` would each need escaping or
     qualification rules. The filter needs none, and the task's name plays
     no part. `filter()` returns a new dataset holding the same `Sample`
     objects, and only the copy's attribute is rebound, so the task the
     factory returned keeps its whole dataset. Every target has a string id,
     so the runner's positional-id assignment, which writes to `Sample`
     objects, leaves them alone. I verified this on a `mockllm` task named
     `benchmark:variant` with samples `a`, `benchmark:variant:a`, `case[1]`
     and `case1`: filtering to `a` and `case[1]` ran exactly those two, over
     two epochs, and the original task's dataset still held all four.
   - **Epochs.** The scratch eval runs the log's recorded epoch count and
     reducers from `recorded_eval_args()`, as eval-retry passes them
     (`eval.py:1844-1848`). A smaller
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
7. Checks that the scratch eval completed. Its log must have `status ==
   "success"`. A cancelled or errored scratch log raises with its status and
   error, without editing anything. `eval_async` can return a cancelled log
   whose targets are already scored and error-free (verified by the
   reviewer under Trio with unfinished extra epochs), so valid target records
   alone do not show that the zero completed.
8. Checks that the task's scorers are the ones the log records. The original
   log's `eval.scorers` and the scratch log's, both as read from disk, must
   hold the same entries in the same order, compared by `name` and
   `options`. Otherwise zero refuses: "the task's scorers differ from those
   the log records (<first difference>): scores may have been appended with
   `inspect score --action append`, or the task's scorers changed since the
   log was written; zero the samples before appending scores". This catches
   an appended log, because append adds its scorers to `log.eval.scorers`
   (`src/inspect_ai/_eval/score.py:443`), and a task whose scorers were
   added, removed, reordered or reconfigured. When the lists match, zero
   writes the task's verdicts under the task's keys; an appended log whose
   headers match an updated task is accepted, with the limitation described
   under "Which score names a disposition covers".

   Then, for every target, it requires a scratch sample with the same
   `(id, epoch)`, no `error` and no `limit`, and applies the zero refusals under "Which
   score names a disposition covers". Any failure raises, naming every
   failing target and its cause, without editing anything. A missing scratch
   sample reads "the empty attempt of sample <id> (epoch <n>) did not run".
   An errored one reads "...did not score: <error>", and one that hit a
   limit reads "...hit its <type> limit". This is atomic where
   Steward's was not required to be: nothing is half-applied.
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
  the same. `eval_async()` does not check it: a module cannot await at its
  top level, so a module-scope evaluation goes through `eval()` or
  `eval_set()`.
- `load_module()` catches `InlineEvalSetSuppressed` around
  `loader.exec_module(module)` and returns the module, executed up to the
  call. Tasks the file defines above its `eval_set()` call are registered
  and load normally, which is what capture mode also relies on. The
  notebook loader does the same around its cell execution.
- A task defined below the call is never registered, and loading it fails
  with the loader's ordinary "task not found" error.

The exception derives from `BaseException`, so a definition's own
`except Exception` around its `eval_set()` call does not swallow it. The
guard covers task-file imports only: zero sets it inside step 4's `prepare`,
which runs in a copied context and resets it before returning, and
`exclude_samples` sets it around trusted metric resolution alone. Zero's
scratch eval (step 6) runs outside it. That eval receives the
`ResolvedTask` that `prepare` returned, which task loading passes through
without importing anything (`src/inspect_ai/_eval/loader.py:134`), so no
import happens there; and the task's own code that runs during it (setup,
scorers, metrics) sees the variable unset, so a nested `eval()` there
behaves as it does in any other eval.

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
  interpreted. Zero's scratch eval runs a copy of the task whose dataset is
  filtered to the target ids by string equality, so no id is read as a
  pattern or a task scope.
- **Changed dataset.** A task's static dataset may have been reordered,
  shuffled or extended since the log was written; a string id still names
  the same sample. A targeted sample the dataset no longer holds, an integer
  id, and a task fed by a `SampleSource` are refused in step 5, and nothing
  is edited.
- **Retuned limits and older logs.** A target whose recorded limits differ
  from the log's header, because an operator retuned them while it ran, and
  every target of a log written before Inspect recorded per-sample limits,
  are refused in step 5, and nothing is edited. Exclusion accepts both.
- **Edited task file.** A task file edited since the log was written runs as
  edited, as eval-retry does, provided its scorers' names and options are
  unchanged (step 8). The scratch log is not kept, but the zero edits record
  the scorer's answer and explanation for the empty attempt. A verdict whose
  shape no longer fits the log's metrics is refused by the staged metric
  computation, and the log is left unchanged.
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
- **List the scratch eval's arguments in zero itself.** Zero would pick the
  recorded settings it needs one by one. Each setting it forgot (approval,
  review, sentinel, a limit, its metering type) would let a scratch attempt
  run differently from the original and produce an error-free verdict, and
  a setting added to eval-retry later would not reach zero. One helper
  shared with eval-retry restores the same settings in both.
- **Replay each target's effective limits.** The scratch eval runs one task
  with one set of limits, so targets retuned to different limits would need
  one scratch eval each, or a per-sample limit override the runner does not
  have. Retunes are an operator's live intervention and rare in a log that
  is then zeroed; refusing a retuned target, which can still be excluded,
  keeps one scratch eval.
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
  6). A hook that exports or notifies on every run does so for it, whether
  or not zero then commits the verdicts.
- **Task-file imports.** `eval_set()`, `eval()` and `load_module()` behave
  as today unless `inline_eval_set_suppressed()` is active, which only the
  disposition functions enter. Capture mode is unchanged.
- **Eval-retry.** Its task and model reconstruction moves into
  `log_task_spec()` and its run settings into `recorded_eval_args()`, with
  the same results and errors and one addition: it now restores a recorded
  `cost_limit`, which it drops today. An eval-retry of a log written with an
  eval-level cost limit therefore runs under that limit, as the original
  did, and needs cost data for its models, as the original did; one
  written with a task's own cost limit is unchanged, because the reloaded
  task carries it. The CLI's `inspect eval-retry` gains no flag; a caller who
  wants no cost limit on the retry has no way to drop it, as for the other
  recorded limits.
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
    the original, and `answer` and `metadata` are unchanged.
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
  - Inline `eval_set()`: a task file that defines a task and then calls
    `eval_set(..., log_dir=<tmp>/inline)` at module scope.
    `exclude_samples(..., trust_log=True)` and `zero_samples` both succeed,
    `<tmp>/inline` is never created, and the guard variable is reset
    afterwards, also when the body raises.
  - Refusals that raise and leave the log unchanged: unknown selectors, a
    `started` log, an empty reason, the reason `"UNCHANGED"` (for both
    functions, on a sample whose score has an explanation), and an
    unresolvable metric.
- `tests/log/test_zero_samples.py` (new: no existing file covers running an
  eval to edit a log). The fixture is a task file with string sample ids,
  whose `Task.setup` sets a metadata flag and whose main solver would
  generate.
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
  - Environment models: with `INSPECT_EVAL_MODEL` naming two `mockllm`
    models, the scratch eval runs the prepared task once, with the recorded
    model; with it naming an unregistered provider, zero still succeeds.
  - Scorer list: each refused with the log unchanged:
    - an errored target and a scored neighbour, after `inspect score
      --action append` of a differently configured instance of the task's
      scorer, which wrote under the target's vacant key;
    - a task file whose scorer's options changed since the log was written;
    - a task file that added a scorer, and one that reordered two.
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
    and `benchmark:variant:a`, zeroing `a`; and a log of task `old` with a
    target `a`, zeroed after the task file renames the task to `new` and
    adds a sample `old:a`. In both only `a` runs in the scratch eval, and
    the factory's task keeps its whole dataset.
  - Scratch aggregation: seven samples, two epochs, `max_samples=1`, and a
    reducer that writes the epoch mean into its first input, plus a metric
    that mutates its inputs and succeeds: the zeroed scores equal each
    scorer's per-epoch verdict.
  - Cached task: a registered factory that returns the same cached `Task`
    with an early-stopping manager, zeroed on a log whose target the dataset
    no longer holds, so zero refuses after preparation: the cached task's
    manager is still installed, and a later eval of the task stops early as
    before.
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
    - a `Task.setup` that generates twice, in a log written with
      `eval(..., message_limit=1)` and a task with no limit of its own:
      the scratch eval hits the recorded limit and the target is refused as
      having hit a limit; likewise a recorded `token_limit` with an
      `"output"` metering type;
    - a log written with a `cost_limit`, a primary model and a model role
      priced through `set_model_info()`, zeroed after the price cache is
      cleared: refused with the native `PrerequisiteError` naming both models
      and the log unchanged; restoring only the primary's price still refuses
      on the role; restoring both, zero succeeds;
    - recorded policies, each given only to `eval()` on a task with none of
      its own, with a `Task.setup` that makes one local tool call scored by
      whether the tool ran: an approval policy that rejects the tool, a
      tool reviewer that terminates the sample, and a sentinel that rejects
      the tool (the repository's fake sentinel integration,
      `tests/test_helpers/fake_sentinel.py`). In each case the tool does not
      run in the scratch eval (asserted through its side effect), and zero's
      outcome is the one the policy gives a native run: under approval it
      copies the "not run" verdict, under the reviewer the scratch sample
      ends with an operator limit and zero refuses the target. A policy
      naming an approver the task file does not register refuses before the
      scratch eval, with the log unchanged;
    - retuned limits: a two-sample log in which a hook calls
      `set_sample_limit_override()` as the first sample starts, so that
      sample records message, token and time limits that differ from the
      header while the second keeps the launch limits. Zeroing the first is
      refused naming the field, before any scratch sample runs; zeroing the
      second succeeds; zeroing both is refused and nothing is edited. A
      plain-count token limit (`token_limit_type` absent in the header,
      `"all"` on the sample) passes;
    - an older log: the same log with `eval.packages["inspect_ai"]` set to
      `0.3.260`, to `0.3.261.dev3`, and removed, is refused as not recording
      per-sample limits; `0.3.261` passes;
    - a log with no task scorers;
    - a task edited to return a scalar under a name whose logged metrics
      expect a dict: the `TypeError` is re-raised and the samples, results
      and reductions are those of the input log;
    - an ephemeral task.
  - A scorer that needs a sandbox, using the `local` sandbox, sees files from
    `Sample.files` and nothing the original attempt wrote.
- `tests/test_eval.py`: the existing eval-retry tests pass unchanged after
  the reconstruction moves into `log_task_spec()` and
  `recorded_eval_args()`. One new test: a log written with
  `eval(..., cost_limit=...)` on a task with none of its own is retried, and
  the retried log's `eval.config.cost_limit` equals the original's.
  `recorded_eval_args()` gets a unit test over a log carrying every field,
  asserting each value and the `TokenLimit` rebuilt for an `"output"` type.
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
   - `src/inspect_ai/log/_disposition.py`: `SampleSelector`,
     `DispositionResult`, and `exclude_samples` with its score-key rule.
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
   - `log_task_spec` and `LogTaskSpec`, and `recorded_eval_args` and
     `RecordedEvalArgs`, extracted in `src/inspect_ai/_eval/eval.py` and used
     by `eval_retry_async`.
   - `parse_version()` in `src/inspect_ai/_util/version.py`, factored out of
     `_installed_version()`.
   - `src/inspect_ai/_eval/zero.py`: `empty_attempt`, `empty_attempt_check`,
     `SetupWroteScores` and the scratch eval.
   - `zero_samples` / `zero_samples_async` in `_disposition.py`, with a
     function-local import of `_eval.zero`.
   - `inspect log zero`, and the docs section extended, including that
     hooks see the scratch eval and that a log with a cost limit needs its
     custom prices restored (linking Model Cost).

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
    recompute. The same gap reaches scalar scorers: an original `probe`
    that never scored and an appended `probe` written under `probe` report
    counts `[0, 2]`, which a bare `recompute_metrics()` turns into `[2, 0]`
    (`eval_results()` assigns positional names, `results.py:157`).
  - `scorers_from_metric_dict()` expands glob metric keys from a sample's
    current dict value and keeps the literal glob when none is left
    (`results.py:500`). After every score of such a scorer becomes `NaN`,
    the concrete `x`, `y` rows are replaced by a `*` row.
