# Zeroing and excluding samples

## Overview

When an operator decides that a sample of a finished log should not count the
way the model ran it, there are two answers: **zero** it (score it as an
empty attempt, which for most tasks is a failure) or **exclude** it (leave it
out of the metrics). Each is a
synchronous edit of the log that runs no task code: it rewrites the sample's
scores as score edits recording who decided and why, keeps the earlier score
in `Score.history` and the sample's transcript and error as they were, and
recomputes the log's metrics from the log header.

**Exclude** rewrites each score the sample holds as an unscored `NaN` with
the reason `"excluded"`. An errored sample that holds no score gets one,
under the log's first scorer. Epoch reduction drops excluded epochs before
the reducer sees them, so an excluded epoch counts as one that never ran.

**Zero** takes two steps. First the operator runs an **empty attempt** of the
samples: an ordinary eval of the task with the built-in solver
`empty_attempt()`, which does nothing. `Task.setup` still runs, so the
sample's environment is prepared, and the task's own scorers then score the
state setup leaves. Then `zero_samples()` copies those verdicts from the
empty-attempt log into the target log, with the reason `"zeroed"`. A missing,
unscored or structured (dict or list) verdict is refused, and the operator
can exclude the sample instead.

Both are Python functions in `inspect_ai.log` (`exclude_samples()`,
`zero_samples()`) and two `inspect log` subcommands (`exclude`, `zero`).

The code is [`log/_disposition.py`](../src/inspect_ai/log/_disposition.py)
(the two functions and their checks), `empty_attempt()` in
[`solver/_empty.py`](../src/inspect_ai/solver/_empty.py) (and the eval-set
selection's `empty_attempt` field in
[`_eval/eval_set_selection.py`](../src/inspect_ai/_eval/eval_set_selection.py)),
`score_is_excluded()`
and the `ScoreReason` vocabulary in
[`scorer/_metric.py`](../src/inspect_ai/scorer/_metric.py), `reduce_scores()`
in [`_eval/task/results.py`](../src/inspect_ai/_eval/task/results.py), and
the `exclude` and `zero` commands in
[`_cli/log.py`](../src/inspect_ai/_cli/log.py). The user docs are
[Excluding Samples](../docs/eval-logs.qmd#excluding-samples),
[Zeroing Samples](../docs/eval-logs.qmd#zeroing-samples),
[Reducing Epochs](../docs/metrics.qmd#reducing-epochs) and
[Recording the reason](../docs/scoring-policy.qmd#recording-the-reason).

## Why

Operator layers over `eval_set` runs, such as Inspect Steward, rule on
samples after a task's log lands, so that every reader of the log directory
sees the result the operator signed. Exclusion is a score edit, but an
excluded epoch would still reach the epoch reducer, and not every reducer
skips `NaN` (`majority` counts it toward the panel; a custom reducer may turn
it into a counted `0.0`). Zero needs the task's scorer, because what a zero
is depends on it: typically `I` for `match()`, `0` for a numeric scorer, a
failed test in a sandbox. Zero copies whatever verdict the scorer gives the
empty attempt, once it passes the verdict rule below, and does not check that
it is a failure: a scorer that accepts an empty answer (`match()` against a
target with no letters or digits scores an empty completion `C`) zeroes the
sample as a success. Getting that verdict by cancelling a re-run as each
sample starts is not empty and depends on timing: solver steps before the
first cancellation checkpoint run, and an agent may reach its first model
call.

The no-op solver skips the main solver without relying on cancellation
timing. The rest is an ordinary eval, with `Task.setup` and the task's
scorers as usual (a model-graded scorer still calls its grader, so its
verdict need not repeat between runs), and both dispositions are log-to-log
edits.

## Scope

- Logs that have landed: neither function works on a running eval.
- Exclusion works on any landed log with samples.
- Zero works on samples with **string ids**, from an empty-attempt log of
  the same task whose verdicts are **single values that are not
  `NaN`, without transcript references**. The producers that exist (Steward's rulings over
  static datasets with string ids and scalar scorers) need nothing more;
  every other shape is refused with an error naming the sample and cause.
- A disposition never changes a sample's `error`, the log's `status`, or
  which samples an eval-set retry re-runs.
- The empty attempt is not run by Inspect's disposition code. The operator
  runs it with the entry point they ran the task with (for a worker of an
  external eval-set runner, through the selection's `empty_attempt` field;
  see [The empty attempt](#the-empty-attempt)), and its models, task
  arguments, sandbox, limits, policies, epochs, display, hooks and control
  server belong to that eval.

## Vocabulary

`ScoreReason` has an operator group beside the model-under-test and
measurement-instrument groups:

```python
    # operator decision
    "excluded",  # excluded from scoring; the value is NaN
    "zeroed",  # scored as an empty attempt
```

`score_is_excluded(score)`, an internal helper that no package exports, is
true when `score.reason == "excluded"` and the value is a float `NaN` at the
root. A score with the reason `"excluded"` that
a later edit gave a counted value is therefore not excluded.

## Epoch reduction

`reduce_scores()` drops the scores for which `score_is_excluded()` holds from
each sample's group of epoch scores before calling the reducer:

- When some remain, the reducer sees only those, so the sample reduces as if
  the excluded epochs had not run, and the reduced score's sample id and
  sample metadata come from the first remaining epoch. `majority` over
  `[C, excluded]` reduces to `C`. A grader's unscored `NaN` (any other
  reason) still reaches the reducer, so `majority`'s treatment of it is
  unchanged. A reducer that depends on the number of epochs sees the
  remaining ones.
- When none remain, the reducer is not called. The reduced score is a copy of
  the group's first excluded score with an empty history, and it counts as
  unscored.

`reduce_scores()` is the one place final scores are reduced, so this holds
live and on recompute. Metrics that read unreduced scores see an excluded
epoch as a root `NaN`, which the standard score filter counts as unscored:
`@metric(scores="unreduced")` metrics, and legacy `scores="auto"` metrics
when reducers are disabled (`Epochs(n, [])`, `--no-epochs-reducer`). With
reducers disabled, a metric that declares `scores="reduced"` is refused when
sample ids repeat, and excluded epochs still count toward that repetition
(see [Reducing Epochs](../docs/metrics.qmd#reducing-epochs)).

## The empty attempt

`empty_attempt()` is a `@solver` in `inspect_ai.solver` whose solve function
returns the state unchanged. It registers as `inspect_ai/empty_attempt`.
It runs as any solver override does: `resolve_plan()` prepends `Task.setup`
to it, the sample is provisioned as for any run, and the task's scorers
score the state left by `Task.setup` (an empty `output` unless setup wrote
one); the override makes no further changes. The one place the runner names
it is the eval-set selection path, below. Its log, the
**empty-attempt log**, is an ordinary log whose header records the override
in `eval.solver`: `inspect_ai/empty_attempt` when it is passed as a Python
object or by registry name, `empty_attempt` when passed as
`--solver empty_attempt`.

The operator runs it with the entry point they ran the task with:

```
inspect eval TASK --solver inspect_ai/empty_attempt --sample-id a,b --log-dir logs/empty
```

or `eval(task, solver=empty_attempt(), sample_id=[...], log_dir=...)`. The
advice on running it (its own log directory, the original run's settings,
`--sample-id` patterns, epochs) is in
[Zeroing Samples](../docs/eval-logs.qmd#zeroing-samples).

An eval set needs more than a solver argument. The solver is part of task
identity, so `eval_set(solver=empty_attempt())` gives each task an
identifier of its own rather than the original run's; it is a separate eval
set, in its own log directory. An external runner that drives workers with
an eval-set selection document (`INSPECT_EVAL_SET_SELECTION`, the wire
format in
[`_eval/eval_set_selection.py`](../src/inspect_ai/_eval/eval_set_selection.py))
sets the selection's `empty_attempt` field instead (schema version 8).
`eval_set()` then matches the selected tasks to their identifiers with the
definition's own solver and runs them with `empty_attempt()` as the solver
override, so the log records `inspect_ai/empty_attempt`. A resumed task
would reuse samples run with the definition's solver, and its prior log is
checked against an identifier that an empty attempt's log never carries, so
a selection that sets `empty_attempt` may not `resume` any task: reading
the selection raises `PrerequisiteError` naming the resumed tasks.

## Python API

```python
SampleSelector: TypeAlias = int | str | tuple[int | str, int]
"""A sample id (every epoch of it) or an (id, epoch) pair."""

def exclude_samples(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> None: ...

def zero_samples(
    log: EvalLog,
    empty: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> None: ...
```

All three are exported from `inspect_ai.log`. Both functions return
`None`, as `edit_score()` does: every target is edited, so the caller reads
the outcome from the log. Both are synchronous, edit `log` in place and
leave writing to the caller. Neither takes a task or a `trust_log` option. Every refusal is
raised before the first edit, so a refused call leaves the log as it was.

### Checks on the log and the selectors

Both functions first check, each failure a `ValueError`:

- `log.samples` is present (the log was read whole) and `log.status` is not
  `"started"` (the log is still being written).
- `provenance.reason` is a non-empty string.
- Every selector is an id or an `(id, epoch)` pair, and every selector
  matches at least one sample. A bare id covers every epoch; a pair covers
  one. Ids match by type and value, except that a string selector also
  matches an `int` id with the same `str()`, because the CLI passes strings.
  All unmatched selectors are named in one error.

The targets are the matched samples in selector order, without repeats. An
empty selector sequence is accepted and selects no target; the call then
edits nothing, but still resolves and recomputes the metrics as below. (The CLI cannot pass one: `--sample` is required.)

### Exclude

For each target:

- A target that holds scores is edited under every key it holds, whichever
  scorer, solver or appended rescoring wrote it. This includes a target whose
  scores are all excluded already: excluding it again adds a history entry
  and a `ScoreEditEvent` recording the new reason and author.
- A target that holds no score is edited under one key: the name of the
  first entry of `log.eval.scorers`. If the log names no scorer, the call is
  refused ("sample ... holds no score and the log names no scorer to record
  the exclusion under"), naming every such target.

Each edit is `ScoreEdit(value=float("nan"), reason="excluded",
explanation=provenance.reason, provenance=provenance)`. `answer` and
`metadata` are left `UNCHANGED`, because they are evidence about the sample.

### Zero

After the log and selector checks, the empty-attempt log is checked as a
whole, each failure a `ValueError`:

- `empty.samples` is present and `empty.status == "success"`. A run whose
  metrics could not aggregate its verdicts ends with status `"error"`, so
  this also refuses a verdict the task's metrics cannot take.
- `empty.eval.solver` is `inspect_ai/empty_attempt` or `empty_attempt`.
- `empty.eval.task == log.eval.task`.
- The scorer names of the two headers (`[s.name for s in eval.scorers or
  []]`) are equal, in order, and not empty. Only the names are compared, not
  where they came from: when the log has scorers appended by `inspect score
  --action append`, the empty-attempt log can get matching entries through
  the same append rescoring, or from a task that declares the full scorer
  list.

Nothing else about the two runs is compared: the task's code, options and
dataset and the run's settings are the operator's.

Then each target is checked. Every failing target is listed in one error,
with its cause and the advice that a sample without a counted verdict can be
excluded instead:

- The target's id is a `str`. Inspect assigns positional `int` ids to
  samples without one, and the log does not record which ids were assigned,
  so an `int` id need not name the same sample in another run.
- The empty-attempt log holds a sample with that id and the target's epoch,
  and that sample has no `error` and no `limit`.
- **The verdict rule.** The empty-attempt sample holds at least one score,
  and every score it holds meets all of these:
  - its value is a `str`, `int`, `float` or `bool` (not a dict or list);
  - its value is not a float `NaN` (an unscored verdict, such as a grader
    failure; the error quotes its reason and explanation);
  - its `metadata` holds no non-empty `scanner_references` (the verdict
    would cite messages or events of the empty attempt, which the target's
    transcript does not hold);
  - none of its value, answer or explanation is the string `"UNCHANGED"`,
    which a score edit reads as "keep the current one".
- Every score name the target holds is produced by the empty attempt (a
  conditional scorer, a solver-written score or an appended rescoring can
  leave one behind).

The root-`NaN` check follows the standard unscored filter. Refusing dict
and list verdicts is zero's own restriction: ordinary metrics count
dict-valued scores (keyed metrics read them), but zero supports single-value
verdicts only. Individual metrics may apply further requirements
(`krippendorff_alpha()` skips a scalar with a warning), so a successful
recomputation does not prove that every metric uses the score.

For each score `v` the empty-attempt sample holds, the edit under the same
name is `ScoreEdit(value=v.value, answer=v.answer,
explanation=v.explanation, metadata=deepcopy(v.metadata or {}),
reason="zeroed", provenance=provenance)`. A name the target does not hold is
added.

Neither function checks whether a target already carries its disposition:
excluding or zeroing a sample again applies the edits again and appends to
the history. An operator layer that re-applies its rulings on every pass and
wants no repeat entries checks each target first, across its whole score
map: it skips the target only when the target holds at least one score and
every score it holds carries the disposition. For an exclusion that means
`reason == "excluded"` and a float `NaN` value at the root, both public
`Score` fields; for a zero it means `reason == "zeroed"` alone, since zero
refuses `NaN` verdicts and a value test adds nothing. Because `edit_score()`
keeps the reason unless the edit sets one, a score edited back to a counted
value still reads `"excluded"`, and the value test makes replay exclude it
again. Any other target still needs the disposition: a sample with no
score, or one where `inspect score --action append` has added a counted
score beside an excluded one.

### Edits and recomputation

Every edit is applied with `edit_score(log, id, name, edit,
recompute_metrics=False, epoch=epoch)`, which records the original score as
`history[0]` (or creates an absent score with the edit as its history) and
adds a `ScoreEditEvent`. Because each edit sets `reason`, `edit_score()`
drops a legacy `metadata["unscored_reason"]` from the current score; the
original stays in the history. The sample's `error`, `messages`, `output`,
`limit`, `invalidation` and events (beyond the added `ScoreEditEvent`s) are
untouched. Dispositions stack: excluding a zeroed sample, or zeroing an
excluded one, adds an edit.

The sequence is the same whether or not there are targets:

1. `resolve_log_metrics(log, trust_log_advice=False)`, before the first edit.
   Metrics and epoch reducers are rebuilt from the header by the untrusted
   resolver, with the reducers rebuilt by registry name and `k`. A metric or
   reducer the registry cannot build raises `RegistryNameNotFound` (a
   `LookupError`) whose message advises installing or importing the module
   that defines it, without the `trust_log` advice, since neither function
   has that option. The log is unchanged.
2. The edits.
3. `compute_log_metrics(log, resolved)`, which replaces `results` and
   `reductions`.

If metric computation raises after the edits, the in-memory log has been
edited and must not be written, as with `edit_score()`.

## CLI

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME]
inspect log zero    LOG_FILE --from EMPTY_LOG --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME]
```

- Neither loads a task or runs an eval, so neither takes task, model or eval
  options.
- `--sample` is repeatable and required, and passes each id as a string.
  `--epoch N` (at least 1) narrows every named sample to that epoch; without
  it every epoch is covered.
- `--author` defaults to `default_provenance_author()` in
  [`_cli/util.py`](../src/inspect_ai/_cli/util.py), shared with
  `inspect ctl`: the git identity, else the OS user name.
- The command reads the log (and for zero, first the empty-attempt log)
  whole, applies the function, and writes the log back in place with
  `write_eval_log(log, LOG_FILE, if_match_etag=log.etag)`, so a concurrent rewrite of an S3 log fails with
  `WriteConflictError`. A `ValueError`, `LookupError` or
  `WriteConflictError` is reported as a command error.
- Output, after the write: one summary line (`excluded 3 samples`,
  `zeroed 1 sample`), then the log's headline metric after recomputation (`<score>/<metric>: <value>`).
  The count is the number of targets, `(id, epoch)` pairs: after the
  function succeeds, `_run_disposition()` counts
  `_select_samples(log, selectors)`, the same helper the functions use, so
  a bare id counts each of its epochs, a string matches an `int` id, and a
  repeated selector counts once. There is no `--json` option.

## Decisions

- 2026-11-04: zero supports string ids only; integer ids are refused.
- 2026-11-04: a disposition does not change a sample's `error`, the log's
  `status`, or which samples an eval-set retry re-runs.
- 2026-11-04: scorer-declared zero values, caller-supplied scorers for zero,
  live dispositions, a sample-level exclusion field and zero for structured
  verdicts are left out (see Future improvements).
- 2026-11-11: the operator runs the empty attempt as an ordinary eval with
  the entry point they ran the task with; Inspect's disposition code does
  not run it, and zero is a log-to-log edit like exclusion.
- 2026-11-17: exclusion has no "already excluded" no-op, the same as zero;
  there is no `DispositionResult`, both functions return `None`, and the
  CLI has no `--json` option and prints one summary line instead of a line
  per target. An operator's replay check for exclusion
  tests the reason and a root `NaN` value; the check for zero tests the
  reason alone.

## Alternatives considered

- **Inspect runs the empty attempt itself** (`zero_samples(log, task,
  **eval_kwargs)`, `inspect log zero LOG TASK`). One call, but it duplicates
  or constrains `eval()` wherever the two meet (reserved keywords, one model,
  a running-eval gate, control server, early stopping, hooks, cancellation),
  and its CLI needs `inspect eval`'s options and task construction.
- **Cancel a re-run as each sample starts.** The attempt is not empty, it
  needs a second process and a watcher, and its outcome depends on timing.
- **Re-run the sample and replace its record** (invalidate, then retry). It
  discards the transcript, which is usually the evidence for the decision.
- **Score the logged sample with an emptied output, as `inspect score`
  does.** It has no sandbox and no `Task.setup`, and a logged sample cannot
  rebuild its sandbox.
- **Copy an unscored verdict as the zero.** The sample would read `zeroed`
  while metrics leave it out of the denominator: an exclusion under another
  name.
- **Leave epoch reduction alone and refuse exclusions a reducer would
  mishandle.** Inspect cannot tell whether a reducer skips `NaN`; dropping
  excluded epochs is one rule for every reducer.
- **Exclude by removing the sample.** Denominators would change silently and
  the record of the decision would be gone.
- **A new `EvalSample.disposition` field.** Every reader would have to learn
  it; a score `reason` already flows through metrics, dataframes and the
  viewer.
- **Exclude under every scorer's name.** The log cannot say which scorer a
  missing key belongs to once rescoring has appended scores, and a missing
  key already counts toward no metric.
- **Zero integer ids by comparing sample contents.** Matching input, target
  and files does not establish that two samples are the same; a string id is
  the author's own name for the sample.
- **Zero dict and list verdicts.** Deciding that a structured verdict counts
  under every metric needs rules about which keys the metrics read; no use
  asks for it.

## Compatibility

- **Score reasons.** `"excluded"` and `"zeroed"` are standard `ScoreReason`
  values, listed in the OpenAPI schema and the viewer's generated types.
  Older Inspect reads them as the plain strings `Score.reason` admits.
- **Epoch reduction.** A score with the reason `"excluded"` and a root `NaN`
  does not reach the epoch reducer. Values differ from passing it through
  only under a reducer that does not omit `NaN` (`majority` over a partly
  excluded sample; a custom reducer that turns `NaN` epochs into a counted
  value, whose fully excluded samples now read as unscored). The reduced
  score's other fields can differ under every reducer: the built-in reducers
  take `metadata` from the first input and keep `answer`, `explanation` and
  `reason` only when all inputs agree, so these come from the remaining
  epochs.
- **Log contents.** Dispositions write existing structures only: `Score`
  fields, `Score.history` entries with `ProvenanceData`, `ScoreEditEvent`s,
  and recomputed `results` and `reductions`.
- **What zero copies.** Zero compares only the task name and scorer names of
  the two logs. The verdict reflects the task code, dataset, models and
  settings of the empty-attempt run.
- **Reducer arguments.** Epochs are reduced with the reducers the header
  records, rebuilt by name and `k`, as `recompute_metrics()` does; a custom
  reducer configured with other arguments is rebuilt with its defaults.
- **Later rescoring.** `inspect score` rescores the preserved transcript and
  output, not the empty attempt. `--action append` keeps a disposition and
  adds the new scores beside it, under keys of their own that count in their
  own metrics; `--action overwrite` replaces the score map, removing the
  disposition, which must then be applied again.
- **Eval-set retry.** A disposition does not clear `error`, so an errored
  sample that was zeroed or excluded is re-run by `inspect eval-retry` and
  eval-set retries, and the new record replaces the disposition.

## Security

- **Log contents** of both logs are untrusted when the logs are. Neither
  function imports a task file or runs task code. Metrics and reducers are
  rebuilt from header names by the untrusted resolver described in
  [Code execution from a malicious eval log](malicious-log-code-execution.md),
  with the same registry lookups as `recompute_metrics()`, whose metric
  options may construct only registered metrics and score reducers (see its
  [allow-list](malicious-log-code-execution.md#untrusted-metric-options-construct-only-metrics-and-reducers)).
- **Copied verdicts** (value, answer, explanation, metadata) are data from
  the empty-attempt log, stored as a score edit. Verdicts with transcript
  references are refused, so no copied link points into another transcript.
- **Reason and author** are free text from the local caller, stored as data
  and rendered as any scorer explanation.
- **Sample selectors** are compared with logged ids and never become paths
  or queries.
- **The empty-attempt run** is the operator's own eval, with the trust model
  of `inspect eval`.

## Future improvements

Left out (decision: Ransom, 2026-11-04) and possible later:

- **Scorer-declared zero values**: a scorer declares its verdict for an
  empty attempt. Cheap where safe, but a second path to keep in step, and
  wrong for sandbox and model-graded scorers.
- **Caller-supplied scorers for zero**, as `inspect score --scorer` does. It
  changes what a zero means and needs naming rules for new scores.
- **Live exclusion and live zero** (`inspect ctl sample cancel --action
  exclude|zero`) for a sample of a running eval. Today the operator cancels
  the sample with `inspect ctl sample cancel --action cancel` and applies the
  disposition once the log lands.
- **A sample-level exclusion field**, should retry or the viewer need a mark
  that does not depend on score reasons.
- **Zero for dict and list verdicts**, and for **integer ids**, if a rule
  for counted structured verdicts, or a record of positional ids, turns up.
- **Referenced empty-attempt evidence**: copying a verdict whose
  `scanner_references` cite the empty attempt, with a way for the viewer to
  resolve them in the empty-attempt log.
- **Checking the empty-attempt run against the original**: a task
  fingerprint and a record of eval-level settings in the log.

## Not this design

- A `--trust-log` or `--import` option for logs whose metric is defined only
  in a task file; the Python caller imports the module first.
- Existing `edit_score()` behaviours the dispositions inherit: a metric or
  reducer that changes its inputs, and a `ScoreEvent` that shares its `Score`
  object with the sample on a log returned by `eval()`, so an in-place edit
  also changes that event.
- A `Task.setup` that writes `state.scores`: its keys reach the
  empty-attempt sample and are copied as verdicts. No known task does this.
- Tightening the registry lookups recomputation makes (score keys outside
  the scorer list, header metric and reducer names), which is a change for
  every caller.
- Moving Steward onto these functions.
- An `excluded_samples` count beside `unscored_samples`, and a viewer badge
  for dispositions.
- An `inspect log invalidate`-style CLI for the existing re-run path.
- The CLI reads the log (and the empty-attempt log) outside the handler
  that turns `ValueError`, `LookupError` and `WriteConflictError` into a
  command error, so a read-time `ValueError` from a malformed log surfaces
  as a raw exception.
- Two recomputation defects that affect any score edit: two dict-valued
  scorers of the same name can both report the first one's data after a
  recompute (`compute_log_metrics()` keys each sample's scores by name, and
  `eval_results()` looks them up by the scorer's unique name), and glob
  metric keys collapse to a `*` row once every score of the scorer is `NaN`
  (`scorers_from_metric_dict()` has no dict-valued score to expand the glob
  against).
