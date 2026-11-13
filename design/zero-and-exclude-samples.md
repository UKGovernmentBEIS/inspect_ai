# Zeroing and excluding samples

## Overview

When an operator decides that a sample should not count the way the model ran
it, there are two answers: **zero** it (count it as a failure) or **exclude**
it (leave it out of the metrics). This design adds both to Inspect, for logs
that have landed. Each is a synchronous edit of the log that runs no task
code: it rewrites the sample's scores as a score edit recording who decided
and why, keeps the earlier score in `Score.history` and the sample's
transcript and error as they are, and recomputes the log's metrics from the
log header.

**Exclude** rewrites each score the sample holds as an unscored `NaN` with
the reason `"excluded"`. An errored sample that holds no score gets one,
under the log's first scorer. Epoch reduction drops excluded epochs before
the reducer sees them, so an excluded epoch counts as one that never ran.

**Zero** takes two steps. First the operator runs an **empty attempt** of the
samples: an ordinary eval of the task with the new built-in solver
`empty_attempt()`, which does nothing. `Task.setup` still runs, so the
sample's environment is prepared, and the task's own scorers then score the
untouched state. Then `zero_samples` copies those verdicts from the
empty-attempt log into the target log, with the reason `"zeroed"`. A verdict
that would not count (no score, an unscored value, a dict or list) is
refused, and the operator can exclude the sample instead.

Both are Python functions in `inspect_ai.log` and two `inspect log`
subcommands.

## Why

The task is meridianlabs-ai/inspect_ai#450. Inspect Steward, an operator
layer over `eval_set` runs, already zeroes and excludes samples after a
task's log lands, so that every reader of the log directory sees the result
the operator signed. It does so outside Inspect:

- **Exclude** is a score edit and works, except that an excluded epoch still
  reaches the epoch reducer, and not every reducer skips `NaN` (see "Epoch
  reduction").
- **Zero** needs the task's scorer, because what a zero is depends on it (`I`
  for `match()`, `0` for a numeric scorer, a fail for a sandbox test).
  Steward gets the verdict from a side run: an `eval_set` worker process on
  the ruled samples, polled over the control channel every 0.5 s, with
  `inspect ctl sample cancel --action score` sent as each sample starts. That
  is not an empty attempt: solver steps before the first cancellation
  checkpoint run, and an agent may reach its first model call. It also needs
  a process launcher, a socket watcher and a time cap.

Inspect can make both simple and deterministic: exclusion as a library
function over a log, and zero as a no-op solver override, whose log is then
copied in by the same kind of function.

## Goals and non-goals

Goals:

- Exclude a sample of a landed log, with provenance and recomputed metrics;
  an excluded epoch takes no part in epoch reduction.
- Zero a sample of a landed log from an empty-attempt log, with provenance
  and recomputed metrics.
- A built-in `empty_attempt()` solver that makes an empty attempt an
  ordinary eval.
- `"excluded"` and `"zeroed"` join the standard `ScoreReason` vocabulary.

Non-goals:

- Running the empty attempt inside Inspect's disposition code. The operator
  runs it with the entry point they ran the task with; its models, task
  arguments, sandbox, limits, policies, epochs, display, hooks and control
  server belong to that eval (decision: Ransom, 2026-11-11).
- Zeroing or excluding a sample of a running eval (see Future improvements).
- Steward's other rulings, journal and sign-off.
- Changing a sample's `error`, the log's `status`, or which samples an
  eval-set retry re-runs (decision: Ransom, 2026-11-04).
- Zeroing integer ids and dict or list verdicts (refused; see Design).
- Bulk selection by error class or status.

## Current behaviour

- **Steward** (meridianlabs-ai/inspect_steward, `src/inspect_steward/_marks/`).
  `mark_unscored` (`edit.py:185-235`) edits every score the sample holds to
  `ScoreEdit(value=NaN, reason="excluded", ...)` with
  `recompute_metrics=False`, or creates one under the first entry of
  `log.eval.scorers` for a sample with none. `harvest_scores`
  (`edit.py:238-290`) copies each score of the side run's sample in with
  `reason="zeroed"`, unchecked, so an unscored verdict becomes a zeroed
  `NaN`. `commit` (`edit.py:293-308`) calls `recompute_metrics(log)` once and
  writes with `if_match_etag`. The side run and watcher are `run.py:264-364`
  and `:453-484`.
- **Unscored values.** `Score.unscored()` sets `value` to `NaN`
  (`src/inspect_ai/scorer/_metric.py:178`). The standard score filter counts
  a score as unscored when its value is a float `NaN` at the root
  (`scorer_for_metrics`, `src/inspect_ai/_eval/task/results.py:396-409`), and
  any other scalar as scored. A single value cannot be `None`.
- **`edit_score()`** (`src/inspect_ai/log/_score.py:13`) applies a
  `ScoreEdit` to one score of one sample and epoch. It records the original
  as `history[0]` (or creates an absent score with `history=[edit]`), keeps
  any field the edit leaves `UNCHANGED`, and adds a `ScoreEditEvent`. With
  `recompute_metrics=True` it resolves metrics before editing and computes
  them after.
- **`recompute_metrics()`** (`src/inspect_ai/log/_metric.py:136`) is
  `resolve_log_metrics()` (`:28`) then `compute_log_metrics()` (`:88`).
  Resolution reads only the header. Without `trust_log` it imports no task
  file and raises `RegistryNameNotFound` (a `LookupError`) for a metric or
  reducer the registry cannot build; `trust_log_advice=False` drops its
  advice to pass `trust_log=True`. Verified: a metric defined in a task file
  resolves once that module has been imported in the process, and raises
  otherwise.
- **Recorded reducers.** The header's `eval.config.epochs_reducer` holds the
  reducers the run used: an eval-level reducer when given, otherwise the
  task's, and `None` for the default `mean`
  (`src/inspect_ai/_eval/run.py:316-325`). Each is recorded by registry name
  plus `k` only (`reducer_log_name`,
  `src/inspect_ai/scorer/_reducer/registry.py:115`), and resolution rebuilds
  them with `create_reducers()` (`:133`), so other reducer arguments take
  their defaults.
- **Epoch reduction.** `reduce_scores()` (`results.py:703`) calls the epoch
  reducer on each sample's group of scores, also for one epoch. `mean`,
  `median`, `mode`, `max`, `at_least`, `pass_at`, `pass_k` and `collect`
  omit a root `NaN`; `majority` counts it toward the panel on purpose
  (`src/inspect_ai/scorer/_reducer/reducer.py:41-60`), so excluding one of
  two correct epochs reduces `C` to `NaN` today. Custom reducers vary:
  inspect_evals' ZeroBench `reliability_at(5)` counts five `NaN` epochs as a
  counted `0.0`.
- **Score names.** The runner names task scorers' scores with
  `unique_scorer_name()` in order (`src/inspect_ai/_eval/task/run.py:1162-1166`,
  `src/inspect_ai/scorer/_scorer.py:262`), so
  `[match(), includes(), match()]` writes `match`, `includes`, `match1`, and
  the first scorer's key is its plain name. `log.eval.scorers[i].name` is the
  unqualified registry name. A solver may write `state.scores` itself; an
  errored sample that never scored holds no keys; `inspect score --action
  append` appends to `log.eval.scorers` and names its scores per sample, so a
  key alone does not say which scorer wrote it.
- **Solver override.** `resolve_plan()` (`src/inspect_ai/_eval/task/run.py:674`)
  prepends `Task.setup` to whatever solver is in effect (`:685-692`), as
  documented ("always run even when the main `solver` is replaced"). The
  header records an override by its registry name in `eval.solver`
  (`inspect eval --solver inspect_ai/generate` records
  `"inspect_ai/generate"`; no override records `None`). `@solver` prefixes
  the defining package (`registry_name()`, `src/inspect_ai/_util/registry.py:265`),
  so a solver defined in `inspect_ai.solver` registers as `inspect_ai/<name>`.
- **Verified with `mockllm`.** A two-epoch task with string ids, a `Task.setup`
  that sets a metadata flag and a `system_message()`/`generate()` solver, run
  with a no-op `@solver` override and `sample_id=["a"]`: both epochs of `a`
  ran setup, had no model events and scored `I` under `match()` and
  `includes()`; the log was `success` with the original's task name and
  scorer names. Copying those scores into the original log with
  `edit_score(..., recompute_metrics=False, epoch=...)` after
  `resolve_log_metrics(log, trust_log_advice=False)`, then
  `compute_log_metrics()`, gave `reason="zeroed"`, the original `C` in
  `history[0]`, and accuracy recomputed from `0.5` to `0.0`.
- **Retry reuse.** A prior record is reused only when `error is None` and
  `invalidation is None` (`classify`,
  `src/inspect_ai/_eval/task/run.py:3886`).

### Who uses which shapes

The only producer of zero and exclude is Steward. It works on landed `.eval`
logs of `eval_set()` runs whose tasks have static datasets with string ids
(its fixture's ids are `user:cybergym/arvo_1` and so on) and a scalar scorer
(`exact()`); see `tests/evalset/fixtures/erroring_evalset.py:37-43` of
meridianlabs-ai/inspect_steward. Searching inspect_ai, inspect_scout,
inspect_flow and inspect_swe for the reasons `excluded` / `zeroed` finds no
other producer or reader; the viewer shows any reason as text. Scorers with
dict values exist (inspect_evals' HLE), but no zero of one has been asked
for. Inspect Scout's `as_scorer()` returns scalar verdicts whose
`metadata["scanner_references"]` cite messages and events of the transcript
it scored (`src/inspect_ai/scorer/_metric.py:243-261`).

The design therefore supports exclusion of any landed log, and zero of
samples with string ids from an empty-attempt log of the same task whose
verdicts are counted scalars without transcript references. Every other
shape is refused with an error.

## Design

### Vocabulary

`ScoreReason` (`src/inspect_ai/scorer/_metric.py:49`) gains an operator
group:

```python
    # operator decision
    "excluded",  # excluded from scoring; the value is NaN
    "zeroed",    # scored as an empty attempt
```

and a predicate beside it, used by epoch reduction and exclusion:

```python
def score_is_excluded(score: Score) -> bool:
    """`reason == "excluded"` and the value is a float NaN at the root."""
```

### Epoch reduction

`reduce_scores()` drops the scores for which `score_is_excluded()` holds from
each sample's group before calling the reducer:

- When some remain, the reducer sees only those, so the sample reduces as if
  the excluded epochs had not run. `majority` over `[C, excluded]` reduces
  to `C`; its treatment of a grader's `NaN` is unchanged, because only the
  `"excluded"` reason is dropped. A reducer that depends on the number of
  epochs sees the remaining ones.
- When none remain, the reducer is not called, and the reduced score is the
  group's first excluded score, counted as unscored.

This applies wherever final scores are reduced, live and on recompute.

### The empty attempt

`empty_attempt()` in `inspect_ai.solver` (`src/inspect_ai/solver/_empty.py`,
exported from `inspect_ai/solver/__init__.py`):

```python
@solver
def empty_attempt() -> Solver:
    """Leave the state unchanged, so the task's scorers score an empty attempt.

    `Task.setup` still runs: it is prepended to any solver override.
    """
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state
    return solve
```

It registers as `inspect_ai/empty_attempt`. Nothing else in the runner
changes: `resolve_plan()` prepends `Task.setup`, the sample is provisioned
as for any run, and the task's scorers score an empty `output`.

The operator runs it with the entry point they ran the task with:

```
inspect eval TASK --solver inspect_ai/empty_attempt --sample-id a,b --log-dir logs/empty
```

or `eval(task, solver=empty_attempt(), sample_id=[...], log_dir=...)`, or
`eval_set()` with the same `solver`. The result is an ordinary log, called
the empty-attempt log. Everything about that run belongs to `eval()`, and
this design specifies none of it. The user docs give short advice:

- Write the empty-attempt log to its own log directory (an `eval_set()` log
  directory is also where it looks for logs to reuse).
- Pass the settings the original run had: the verdict reflects the task and
  settings of the empty-attempt run.
- `--sample-id` is a pattern and may carry a task prefix. Samples it selects
  beyond the targets are ignored by the copy; a target it misses is refused.
- The run uses the task's epochs (or `--epochs`), and every targeted epoch
  must be in the empty-attempt log.

### Python API

In `src/inspect_ai/log/_disposition.py`, exported from `inspect_ai.log`:

```python
SampleSelector = int | str | tuple[int | str, int]
"""A sample id (every epoch of it) or an (id, epoch) pair."""

class DispositionResult(NamedTuple):
    applied: list[tuple[int | str, int]]     # (id, epoch) edited now
    unchanged: list[tuple[int | str, int]]   # already excluded (exclude only)

def exclude_samples(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> DispositionResult: ...

def zero_samples(
    log: EvalLog,
    empty: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> DispositionResult: ...
```

Both are synchronous, edit `log` in place and leave writing to the caller.
Neither takes a task or a `trust_log` option.

**Checks for both,** before any edit, each a `ValueError`:

- `log.samples` is present (a log read whole), and `log.status != "started"`
  (still being written; run the command once the eval finishes).
- `provenance.reason` is a non-empty string.
- Every selector matches. A bare id covers every epoch; `(id, epoch)` covers
  one. Ids match by value, and a string selector also matches an `int` id
  with the same `str()`, because the CLI passes strings. Unmatched selectors
  are named in the error.

**Zero's checks on the empty-attempt log,** before any edit:

- `empty.samples` is present and `empty.status == "success"`. A run whose
  metrics could not aggregate its verdicts ends with `status="error"`
  (aggregation runs inside the task run, `src/inspect_ai/_eval/task/run.py:2050`), so this also refuses a verdict
  the task's metrics cannot take.
- `empty.eval.solver == "inspect_ai/empty_attempt"`.
- `empty.eval.task == log.eval.task`, and the scorer names of the two
  headers (`[s.name for s in eval.scorers or []]`) are equal, in order, and
  not empty. Nothing else is compared: the task's code, options, dataset and
  the run's settings are the operator's (see Compatibility). A log with
  appended scorers therefore matches only an empty-attempt log whose task
  has the full scorer list.

**Zero's checks per target,** before any edit. Every failing target is named
in one error, with its cause, and nothing is edited:

- The target's id is a `str` (decision: Ransom, 2026-11-04). An `int` id
  need not name the same sample in another run, because Inspect assigns
  positional `int` ids and the log does not record which ids were assigned.
- The empty-attempt log holds a sample whose id is that `str` and whose
  epoch is the target's, with no `error` and no `limit`.
- **The verdict rule.** The empty-attempt sample holds at least one score;
  every score it holds is a counted single value (a `str`, `int`, `float` or
  `bool` that is not a float `NaN`) whose `metadata` holds no non-empty
  `scanner_references`; and it holds every score name the target holds. The
  message names each offending key with its cause and suggests exclusion:
  - no verdict (the empty attempt holds no score);
  - a dict or list value (zero supports single-value verdicts only);
  - an unscored value (a root `NaN`, such as a grader failure), with the
    score's reason and explanation;
  - transcript references (the verdict cites messages or events of the
    empty attempt, which the target's transcript does not hold);
  - a name the target holds and the empty attempt does not produce (a
    conditional scorer, a solver-written or appended score).

The counted-value rule is the standard score filter's. Individual metrics may
apply further requirements (`krippendorff_alpha()` skips a scalar with a
warning), so a successful recomputation does not prove that every metric uses
the score.

**Edits.** Every disposition is a `ScoreEdit` carrying `provenance`, applied
with `edit_score(log, id, name, edit, recompute_metrics=False, epoch=epoch)`:

- **Exclude:** for every key the sample holds, or, for a sample that holds
  none, one key: the first entry of `log.eval.scorers` (refused when that is
  empty or `None`: "sample <id> (epoch <n>) holds no score and the log names
  no scorer to record the exclusion under"). The edit is
  `ScoreEdit(value=float("nan"), reason="excluded",
  explanation=provenance.reason, provenance=provenance)`; `answer` and
  `metadata` are `UNCHANGED`, because they are evidence about the sample. A
  target whose every held score satisfies `score_is_excluded()` (and that
  holds at least one) is reported `unchanged` and not edited.
- **Zero:** for every score `v` the empty-attempt sample holds,
  `ScoreEdit(value=v.value, answer=v.answer, explanation=v.explanation,
  metadata=v.metadata or {}, reason="zeroed", provenance=provenance)` under
  the same name. There is no idempotence check: zeroing again applies the
  verdicts again and appends to the history, so `unchanged` is always empty.

Because each edit sets `reason`, `edit_score()` drops a legacy
`metadata["unscored_reason"]` from the current score
(`src/inspect_ai/log/_score.py:137-143`); the original stays in `history[0]`.
The sample's `error`, `messages`, `output`, `limit`, `invalidation` and
events (beyond the added `ScoreEditEvent`s) are untouched. Dispositions
stack: excluding a zeroed sample, or zeroing an excluded one, adds an edit.

**Recomputation,** for both, is the sequence `edit_score()` uses today:

1. `resolve_log_metrics(log, trust_log_advice=False)` before the first edit,
   so a metric or reducer the registry cannot build leaves the log
   unchanged. Its `RegistryNameNotFound` is re-raised with the advice:
   "import the module that registers <name> before running this".
2. The edits.
3. `compute_log_metrics(log, resolved)`.

Metrics and epoch reducers therefore come from the log header through the
existing untrusted resolver, exactly as `recompute_metrics(log)` builds them.
Every refusal happens before the first edit; if metric computation raises
after the edits, the in-memory log must not be written, as with
`edit_score()`.

### CLI

Two subcommands of `inspect log` (`src/inspect_ai/_cli/log.py`):

```
inspect log exclude LOG_FILE --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--json]
inspect log zero    LOG_FILE --from EMPTY_LOG --sample ID [--sample ID ...] [--epoch N]
                    --reason TEXT [--author NAME] [--json]
```

- Neither loads a task or runs an eval, so neither takes task, model or eval
  options.
- `--sample` is repeatable and required. `--epoch N` narrows every named
  sample to that epoch; without it every epoch is covered.
- `--author` defaults to the git identity, else the OS user name: the
  `ctl config` helper (`_default_provenance_author`,
  `src/inspect_ai/_cli/ctl/_config.py:860`), moved to
  `src/inspect_ai/_cli/util.py`.
- The command reads the log (and for zero, the empty-attempt log) whole,
  applies the function, and writes the log back in place with
  `write_eval_log(log, location, if_match_etag=log.etag)`, so a concurrent
  rewrite of an S3 log fails with `WriteConflictError`. When nothing changed,
  nothing is written.
- Output: one line per sample (`excluded` / `zeroed` / `unchanged`) and the
  recomputed headline metric. `--json` prints
  `{"log": ..., "applied": [[id, epoch], ...], "unchanged": [...]}`.

## Alternatives considered

- **Inspect runs the empty attempt itself** (`zero_samples(log, task,
  **eval_kwargs)` and `inspect log zero LOG TASK`). It gives one call, but it
  duplicates or constrains `eval()` wherever the two meet: reserved
  keywords, one model, a running-eval gate, control server, early stopping,
  the scratch directory, hooks and cancellation. Its CLI needs `inspect
  eval`'s options and task construction. With the empty attempt as an
  ordinary eval, all of that is `eval()`'s, and zero becomes a log-to-log
  edit like exclusion (decision: Ransom, 2026-11-11).
- **Steward's side run and cancel-as-it-starts, moved into Inspect.** The
  attempt is not empty, it needs a second process and a watcher, and its
  outcome depends on timing. The solver override is deterministic.
- **Zero by re-running the sample and replacing its record** (invalidate,
  then retry). It discards the transcript, which is usually the evidence for
  the decision.
- **Score the logged sample with an emptied output, as `inspect score`
  does.** It has no sandbox and no `Task.setup`, and a logged sample cannot
  rebuild its sandbox (only file names are logged).
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
  missing key belongs to once append has named scores per sample, and a
  missing key already counts toward no metric.
- **Zero integer ids by comparing sample contents.** Matching input, target
  and files does not establish that two samples are the same (a scorer may
  read metadata); a string id is the author's own name for the sample.
- **Zero dict and list verdicts.** Deciding that a structured verdict counts
  under every metric needs rules about which keys the metrics read; no use
  asks for it yet.

## Compatibility and migration

No migration required.

- **Score reasons.** `ScoreReason` gains `"excluded"` and `"zeroed"`. Older
  Inspect reads them as the plain strings `Score.reason` already admits. The
  OpenAPI schema (`src/inspect_ai/_view/inspect-openapi.json`) and the
  viewer's generated types change (an enum widens), which needs the
  coordinated ts-mono regeneration.
- **Epoch reduction.** A score with reason `"excluded"` and a root `NaN` no
  longer reaches the epoch reducer, live or on recompute. The only existing
  producer is Steward's exclusion. Recomputed values change only under a
  reducer that does not omit `NaN`: `majority` over a partly excluded sample,
  and a reducer such as ZeroBench's, whose fully excluded samples now read as
  unscored instead of `0.0`. The reduced score's other fields can change
  under every reducer: the built-in reducers take `metadata` from the first
  input and keep `answer`, `explanation` and `reason` only when all inputs
  agree (`_reduced_score()`, `src/inspect_ai/scorer/_reducer/reducer.py:593`),
  so these now come from the remaining epochs. That is the intended meaning:
  an excluded epoch counts as one that never ran.
- **Log contents.** Dispositions write existing structures only: `Score`
  fields, `Score.history` entries with `ProvenanceData`, `ScoreEditEvent`s
  and recomputed `results` / `reductions`.
- **Public API.** New: `exclude_samples`, `zero_samples`,
  `DispositionResult` and `SampleSelector` in `inspect_ai.log`;
  `empty_attempt` in `inspect_ai.solver`.
- **CLI.** New `inspect log exclude` and `inspect log zero`.
- **What zero copies (limitation).** Zero compares only the task name and
  scorer names of the two logs. The verdict reflects the task code, dataset,
  models and settings of the empty-attempt run, which are the operator's;
  the docs say to pass the settings the original run had.
- **Reducer arguments (limitation).** Epochs are reduced with the reducers
  the header records, rebuilt by name and `k`, as `recompute_metrics()` does
  today; a custom reducer configured with other arguments is rebuilt with
  its defaults.
- **Later rescoring.** `inspect score` rescores the preserved transcript and
  output, not the empty attempt. `--action append` keeps a disposition and
  adds the new verdict beside it; `--action overwrite` replaces the score map
  (`src/inspect_ai/_eval/score.py:179-194`), removing the disposition, which
  should then be applied again. The docs say so.
- **Eval-set retry.** Unchanged (decision: Ransom, 2026-11-04). A
  disposition does not clear `error`, so an errored sample that was zeroed or
  excluded is re-run by `inspect eval-retry` and eval-set retries, and the
  new record replaces the disposition. The help and docs say so.
- **Steward.** Its logs read the same, since its strings become the standard
  reasons. Its change, separately: add `empty_attempt()` to its side run,
  drop the watcher and cancel, and call `zero_samples` in place of its
  harvest.

## Security

- **Log contents** of both logs are untrusted when the logs are. Neither
  function imports a task file or runs task code. Metrics and reducers are
  rebuilt from header names by the existing untrusted resolver, with the
  registry lookups `recompute_metrics()` makes today (registered objects, and
  an installed package's entry point for a `pkg/name` name); it refuses
  metric options that name a model or a non-metric registry object. A score
  key outside the scorer list is looked up by registry name
  (`ScorerInfo.from_name()`), as in existing recomputation.
- **Copied verdicts** (value, answer, explanation, metadata) are data from
  the empty-attempt log, stored as a score edit. Verdicts with transcript
  references are refused, so no copied link points into another transcript.
- **Reason and author** are free text from the local caller, stored as data
  and rendered as any scorer explanation.
- **Sample selectors** are compared with logged ids and never become paths
  or queries.
- **The empty-attempt run** is the operator's own eval, with the trust model
  of `inspect eval`.

## Testing

Pure and `mockllm` tests in the default suite; no network, provider key or
Docker.

- `tests/scorer/test_reducers.py`, through `reduce_scores()`:
  - `majority` over `[C, C-excluded]` reduces to `C`, and over `[C,
    grader_failed]` still to `NaN`.
  - A reducer that turns `NaN` epochs into a counted `0.0` is not called for
    a sample with every epoch excluded; the sample reduces to the excluded
    score and counts unscored.
  - `mean`, `median`, `max` and `mode` over `[excluded, kept]` equal the
    reduction of `[kept]`, including `metadata`, `answer`, `explanation` and
    `reason`.
- `tests/scorer/test_score_editing.py` (exclude):
  - Key rule: a sample with a deduplicated key (`match1`), an appended key
    and a solver-written key has every score excluded, with provenance,
    `history[0]` the original, and `answer` and `metadata` kept (a legacy
    `unscored_reason` removed from the current score only). An errored
    sample with no scores in a log with `[match(), includes()]` gets one
    excluded score, under `match`. A sample with no scores in a log with no
    scorers is refused.
  - Selectors: a bare id covers every epoch, `(id, epoch)` one; a string
    selector matches an `int` id; unknown selectors are refused.
  - `unchanged`: a repeat reports the target unchanged; an excluded score
    later given `ScoreEdit(value=1)` is excluded again.
  - Recomputation: accuracy over the rest and `unscored_samples` counted; a
    log written with `epochs=Epochs(5, "pass_at_5")` on a one-epoch task
    reduces with the header's `pass_at_5`; a header recording `majority`
    reduces with `majority`.
  - Refusals leaving the log unchanged: a `started` log, a header-only log,
    an empty reason, and a metric or reducer the registry cannot build (with
    the import advice).
- `tests/log/test_zero_samples.py` (new). The fixture is a task with string
  ids, a `Task.setup` that sets a metadata flag, a generating main solver
  and `[match(), includes()]`; the empty-attempt log comes from `eval(task,
  solver=empty_attempt(), sample_id=[...])`.
  - Happy path: the empty-attempt log records the solver
    `inspect_ai/empty_attempt`, `Task.setup` ran and no main-solver
    `ModelEvent` exists; the zeroed scores equal its verdicts (`I`), with
    reason `zeroed`, the original in `history[0]`, and the transcript and
    `error` unchanged; metrics recompute.
  - An errored target with no scores is zeroed under both scorers.
  - A multi-epoch log with targets `a/1` and `b/2`, from an empty-attempt
    log holding every epoch of both: only the targets are edited. A target
    epoch the empty-attempt log lacks is refused.
  - Empty-attempt log checks, each refused with the log unchanged: status
    `error`; a header-only read; another solver (a plain run of the task);
    another task name; scorer names that differ, are reordered, or are
    empty.
  - Verdict rule, each cause named and the log unchanged: an errored or
    limited empty-attempt sample; a missing target; a scorer returning
    `None`; `{"x": 0}` and `[0, 1]`; `Score.unscored(reason="grader_failed")`;
    a verdict with a non-empty `scanner_references` list (an empty list is
    accepted); a solver-written score on the target. Two failing targets are
    named in one error.
  - An integer id is refused.
  - Zeroing twice appends a second history entry and reports nothing
    `unchanged`.
- `tests/_cli/`: one test per command, `inspect log exclude` and `inspect log
  zero --from`, each parsing `--sample`, `--epoch`, `--reason` and
  `--author`, writing in place, and printing the per-sample lines and the
  `--json` envelope.
- Schema drift: the OpenAPI and TypeScript drift checks pass after the
  regeneration.

## Implementation plan

1. **Vocabulary and epoch reduction.** The two reasons and
   `score_is_excluded()` in `src/inspect_ai/scorer/_metric.py`; dropping
   excluded epochs in `reduce_scores()` (`src/inspect_ai/_eval/task/results.py`);
   the reasons in `docs/scoring-policy.qmd` and the rule under "Reducing
   Epochs" in `docs/metrics.qmd`; the OpenAPI and ts-mono regeneration with
   the land-ts-mono procedure. Tests: the reducer tests.
2. **Exclude.** `SampleSelector`, `DispositionResult` and `exclude_samples`
   in `src/inspect_ai/log/_disposition.py`, exported from
   `src/inspect_ai/log/__init__.py`; `inspect log exclude` in
   `src/inspect_ai/_cli/log.py`, with the default author helper moved to
   `src/inspect_ai/_cli/util.py`; a "Zeroing and Excluding Samples" section
   in `docs/eval-logs.qmd` covering retry, later rescoring, recorded
   reducers, the import advice, and for a running eval `inspect ctl sample
   cancel --action cancel` followed by these commands once the log lands.
   Tests: the exclude and exclude CLI tests.
3. **Zero.** `empty_attempt()` in `src/inspect_ai/solver/_empty.py`, exported
   from `inspect_ai.solver`; `zero_samples` in `_disposition.py`; `inspect
   log zero --from`; the docs section extended with the empty-attempt recipe
   and its advice. Tests: the zero and zero CLI tests.

## Open questions

None.

## Future improvements

Left out of this design (decision: Ransom, 2026-11-04) and possible later:

- **Scorer-declared zero values**: a scorer declares its verdict for an
  empty attempt. Cheap where safe, but a second path to keep in step, and
  wrong for sandbox and model-graded scorers.
- **Caller-supplied scorers for zero**, as `inspect score --scorer` does. It
  changes what a zero means and needs naming rules for new scores.
- **Live exclusion and live zero** (`inspect ctl sample cancel --action
  exclude|zero`) for a sample of a running eval.
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
- Two recomputation defects that affect any score edit today: two
  dict-valued scorers of the same name can both report the first one's data
  after a recompute (`src/inspect_ai/log/_metric.py:113`,
  `src/inspect_ai/_eval/task/results.py:161`), and glob metric keys collapse
  to a `*` row once every score of the scorer is `NaN` (`results.py:500`).
