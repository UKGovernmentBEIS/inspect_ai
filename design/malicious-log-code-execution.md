# Code execution from a malicious eval log

## Overview

Reading an eval log someone else wrote does not run their code. Inspect
splits the operations that take a log into two kinds. Run operations
(`eval-retry`, and `inspect score` with the log's own scorers) exist to run
the log's task, so they import the files and use the settings the log
records, and their docs and `--help` say to use them only on logs you trust.
Read operations (viewing, listing, converting, analysis, recomputing metrics,
editing scores, recovering a crashed log, resuming an eval set) import no file
a log names, construct no model provider from log values, and do not let the
log choose the sandbox of a task the user is running.

A caller who trusts a log can pass `trust_log=True` (`--trust-log` for
`inspect log recover`) to recompute, edit or recover with the log's task file
imported for metrics that are not registered and its metric options rebuilt
as recorded. Rescoring with scorers the user supplies treats the log's
metrics the way a read operation does. `inspect score` prints a record of the
task file it imports and of the model base URL it takes from the log.

The rules live in the metric resolvers of
[`_eval/score.py`](../src/inspect_ai/_eval/score.py), the registry allow-list
in [`_util/registry.py`](../src/inspect_ai/_util/registry.py), the scorer
loaders in [`_eval/loader.py`](../src/inspect_ai/_eval/loader.py), and the
callers in [`log/_metric.py`](../src/inspect_ai/log/_metric.py),
[`log/_score.py`](../src/inspect_ai/log/_score.py) and
[`log/_recover/_api.py`](../src/inspect_ai/log/_recover/_api.py). The user
docs are [Logs from Others](../docs/eval-logs.qmd#logs-from-others),
[Scoring Workflow](../docs/scoring-workflow.qmd) and the recovery section of
[Handling Errors](../docs/handling-errors.qmd).

## Threat

An eval log is data, but Inspect can turn its fields into Python imports,
registry object construction, model provider construction and sandbox
configuration. A log is often not written by the person who opens it: logs
are shared for analysis, a collaborator hands over a log directory to resume,
results bundles are published. Whoever writes the log controls every field in
it (`eval.task_file`, `eval.scorers`, `eval.metrics`, sample score keys,
model name, args and base URL, sandbox spec, and so on), and the sample buffer
next to it. They do not control the reader's installed packages or command
line.

Three mechanisms turn a string into an import, and the rules below keep log
values away from each of them outside run operations:

- `parse_spec_str()` treats `<path>@<name>`, or any string that is an existing
  path, as a file, and the spec loaders (`scorer_from_spec()`,
  `solver_from_spec()`, `metric_from_spec()`) import it with `load_module()`.
- The scorer fallback imports the log's task file when the registry cannot
  build a bare scorer name.
- `load_file_tasks()` imports a task file whose source has a function
  decorated `@task` or `@task_source`. The decorator filter is not a security
  boundary; it only avoids importing files that are not task files.

Relative paths resolve against the working directory. `task_file` is recorded
relative to the working directory when the task is under it, and absolute
otherwise, which is what lets a retry or rescore run from the project
directory.

## Trust model

An operation is a **run operation** when its purpose is to execute the task
the log describes: `eval_retry()` / `inspect eval-retry`, and rescoring with
the log's own scorers (`inspect score` without `--scorer`). Running one on a
log means trusting the log's task code (decision: Ransom, 2026-09-21).
Everything else is a **read operation**: `inspect view` and its server
endpoints, `inspect log` listing, dumping and conversion, `inspect info`,
`inspect ctl` (including `--log-dir` mode), dataframes and
`inspect_ai.analysis`, `recompute_metrics()`, `edit_score()`,
`recover_eval_log()` / `inspect log recover`, and `eval_set()`, whose tasks
come from the user's command line while the logs only supply completed
samples.

Rescoring with scorers the user supplies (`inspect score --scorer`, or
`score()` / `score_async()` from Python) sits between the two. It runs the
user's scorers in a task context built from the log's model, model roles and
samples, so its docs and `--help` carry the trusted-logs statement. The log's
metric definitions, which `--action overwrite` rebuilds, are resolved as in a
read operation.

| Operation | Python files the log can make Inspect import |
|---|---|
| read operations | none; with `trust_log=True` (recompute, edit, recover) the recorded task file |
| `inspect score` without `--scorer` | the recorded task file, when the registry cannot build a recorded scorer |
| `inspect score --scorer NAME`, `score(log, scorers)` | none for metrics; the recorded task file when a bare `--scorer` name cannot be built from the registry |
| `eval-retry` | the recorded task file and solver file; for a log with no `task_file` and an `hf/` task name, the Hugging Face repo's `eval.yaml` instead |

In every class, registry names may load installed packages' entry points and
call their registered factories (see [Registry names](#registry-names)).

Run operations, and read operations whose caller passes `trust_log=True`,
rebuild a log's metric options without restriction. Other read operations,
and rescoring with the user's scorers, rebuild them under the
[allow-list](#untrusted-metric-options-construct-only-metrics-and-reducers).

## Read operations

### Score keys are registry names

`eval_results()` builds a `ScorerInfo` for every sample score key that no
known scorer produced, which in recompute and recovery is every key, since
those build their `SampleScore`s without `scorer=`. `ScorerInfo.from_name()`
resolves the key only through `scorer_from_registry()` in `loader.py`
(a registered `@scorer` or `@scanner` by name; no path parsing, no file
loading). Any exception from it gives the default metrics (`accuracy`,
`stderr`). The catch is broad on purpose: live final, cancellation and display
aggregation and the control server's interim scoring also reach it, and a
solver-written score keyed by a registered scorer that needs arguments
(`pattern`, `answer`, `multi_scorer`, ...) raises `TypeError` when built
without them and must keep getting the defaults.

A score key that names a file gets the default metrics like any other
unregistered key. Inspect never writes such keys.

### Metric reconstruction and `trust_log`

`LogTaskFileImport` in `_eval/score.py` carries the trust decision for one
recompute, recovery or rescore, and is shared by the two metric resolvers so
the task file is imported at most once per operation:

- `metrics_from_log_header()` rebuilds task-level metrics (`eval.metrics`).
- `resolve_scorers_info()` rebuilds each scorer's metrics
  (`eval.scorers[*].metrics`).

Each resolver checks only the source it builds, because a caller can discard
the other: `inspect score --scorer ... --action overwrite` uses the task-level
metrics and replaces `eval.scorers`, so it must succeed when the old scorers
name a metric that is no longer available. `metric_from_log()` builds each
definition, including nested lists and dict groups.

The tracker's fields:

- `trust_log`: whether the log may choose code.
- `import_task_file`: with `trust_log`, whether a missing metric imports the
  task file. `False` is for rescoring with the log's own scorers, which trusts
  options but fails on a missing metric as it always has.
- `opt_in`: the closing advice of untrusted-log errors, naming an option the
  caller actually has (`None` for no advice).
- `dependency_advice`: advice appended to the error for an unregistered object
  nested in metric options.

With `trust_log=True` and `import_task_file`:

- `ensure_metrics_registered()` runs before anything is built. If any metric
  name, including metric registry dicts nested in options, is not registered,
  it imports `Path(task_file).absolute()` with `load_file_tasks()` (if the
  file exists), once per tracker, and logs at `INFO`:
  `Imported task file /abs/path/evals/task.py (recorded in the log) to load metric 'my_metric'.`
  Nothing prints it; the caller asked for the import.
- A metric still missing raises the missing-metric error below, without the
  opt-in sentence.
- Metric options are rebuilt with no restriction.

Otherwise nothing is imported, metrics are found missing as they are built,
in order, and options are rebuilt under the allow-list. A missing metric
raises `RegistryNameNotFound` (a `LookupError`, so callers that catch the
registry's error keep working):

```
Metric 'my_metric' (used by scorer 'my_scorer') is not registered. If it is
defined in the task file ('evals/task.py'), import that module first.
To trust the log, pass trust_log=True (inspect log recover: --trust-log);
this imports the log's task file and runs its code, so do it only for logs
you trust.
```

For a task-level metric the parenthesis reads "(a task-level metric)". With no
task file the middle sentence reads "Install or import the module that
defines it first." The last sentence is the tracker's `opt_in`:

- `TRUST_LOG_OPT_IN` (above) for `recompute_metrics()`, `edit_score()` and
  direct recovery.
- `SCORE_OPT_IN` for rescoring with the caller's scorers, which has no
  `trust_log`: "To score without the log's metrics, pass metrics= (inspect
  score: --metric). If you trust the log, rescore with its own scorers instead
  (inspect score without --scorer)."
- None for eval-set's recovery, which warns instead of raising.

An unregistered object nested in a metric's options that is not itself a
metric (a reducer, say) raises "Metric 'x' needs an object that is not
registered (...). Install the package that defines it, or import the module
that defines it, first.", followed by `dependency_advice` when set. The task
file is never imported for these.

One keyword covers both the task-file import and the option restriction,
because both answer whether the log may choose code. It is keyword-only and
defaults to `False` on `recompute_metrics()`, `edit_score()`,
`recover_eval_log()` and `recover_eval_log_async()`, and is
`inspect log recover --trust-log`, whose help says it runs the task file's
code.

### Untrusted metric options construct only metrics and reducers

`create_registry_object()` takes a keyword-only `allowed_types`, threaded
through `_instantiate_registry_object()`, `_resolve_registry_args()` and
`registry_arg()` at every depth. With `allowed_types=None` (the default)
nothing is restricted: scorer, solver and approver reconstruction and every
other caller behave as before. With an allow-list, `registry_arg()` raises
`DisallowedRegistryArg` (a `ValueError`) on a model dict, or on a registry
dict whose type is not in the list, instead of constructing it. Every argument
is resolved before the outer factory is called, so a forbidden nested value
raises before the metric's factory runs.

`metric_from_log()` passes `LOG_METRIC_OPTION_TYPES` (`metric` and
`score_reducer`) unless its tracker trusts the log. Nested metrics stay
allowed because built-in metrics take metrics as parameters:
`grouped(accuracy(), "category")` records
`{"metric": {"type": "metric", "name": "accuracy", "params": {}}, "group_key": "category"}`.

The error names the outermost object and the option path, and
`metric_from_log()` sets the tracker's `opt_in` as its advice:

```
Metric 'grouped' option 'metric.params.model': a model cannot be created
from metric options in an untrusted log. To trust the log, pass
trust_log=True (inspect log recover: --trust-log); this imports the log's
task file and runs its code, so do it only for logs you trust.
```

The restriction is enforced where objects are constructed, not by a separate
walker over the options, so there is no recogniser that could disagree with
what `registry_arg()` builds (decision: Ransom, 2026-10-06). The public
`registry_kwargs(**kwargs)` keeps its signature and resolves without
restriction; an allow-list keyword on it would collide with an option of that
name, and `inspect_scout` and `inspect_flow` call it as
`registry_kwargs(**params)`. The public `metric_create()` is unchanged.

Scorer options are not restricted: they are rebuilt only by run operations,
and model-graded scorers record their grader model as a model dict that
rescoring must rebuild.

### Epoch reducers

Reducers are never imported from the task file, with or without trust.
`resolve_log_metrics()` builds each recorded `eval.config.epochs_reducer` name
with `create_reducers()` and re-raises a `RegistryNameNotFound` as:

```
Epoch reducer 'my_reducer' (the log's epochs_reducer) could not be built:
my_reducer was not found in the registry. Install the package that defines
the missing object, or import the module that defines it, first; the log's
task file is not imported for reducers.
```

The embedded error names whichever object is missing, the reducer or one it
depends on. Direct untrusted recovery appends `RECOVER_REDUCER_ADVICE`
(below), as it does to a missing object nested in metric options;
recompute and edit append nothing, since `trust_log` does not help them.

### `edit_score()` and recovery resolve before they change anything

`recompute_metrics()` is two phases in `log/_metric.py`:
`resolve_log_metrics()` rebuilds the reducers and metrics from header fields
only (`eval.metrics`, `eval.scorers`, `eval.config.epochs_reducer`) and
returns a `LogMetrics`; `compute_log_metrics()` runs `eval_results()` over the
samples' scores and sets `results` and `reductions`. Neither an edit nor
recovery changes those header fields, so resolving first gives the same
metrics, and a failure leaves nothing half done for the suggested retry with
`trust_log=True` to trip over.

- **`edit_score()`** finds the sample, resolves (when
  `recompute_metrics=True`), then applies the edit and computes. A missing
  metric or forbidden option raises with the log unchanged, and a retry with
  `trust_log=True` applies the edit once.
- **`recover_eval_log_async()`** resolves on the crashed log's header after
  its guards (which write nothing) and before `write_recovered_eval_log()`,
  passing the `LogMetrics` (or `None`) to the writer. Resolution stops at the
  first failure, and that failure decides the outcome (decision: Ransom,
  2026-10-22):
  - Direct untrusted recovery (`trust_log=False`, the default
    `_untrusted_metrics="raise"`): a `RegistryNameNotFound` or
    `DisallowedRegistryArg` is raised before anything is written or cleaned
    up, so the crashed log and its buffer are untouched and a rerun with
    `--trust-log` works. Missing reducers and missing nested objects carry
    `RECOVER_REDUCER_ADVICE`: "Nothing was written; the crashed log and its
    buffer are unchanged. To recover it without results instead, pass
    trust_log=True (inspect log recover: --trust-log); this imports the log's
    task file and runs its code, so do it only for logs you trust."
    `inspect log recover` reports these with `click.ClickException`.
  - Any other exception, such as a registered metric factory raising before a
    missing name or forbidden option is reached, and every failure under
    trust or `_untrusted_metrics="warn"`: the log is written without results
    and the warning "Unable to recompute metrics for recovered log: ..." is
    logged. Untrusted, nothing forbidden is built and no file is imported.
  - A metric function that raises while computing is handled by the writer
    the same way.

  Without results a resolving recovery (`incomplete_action` other than
  `"retry"`) does not finalize.

The sync `recover_eval_log()` forwards `trust_log` and the private
`_untrusted_metrics` to the async function.

### Callers inside Inspect

- `eval_retry_async()` passes `trust_log=True` to both of its recovery calls
  (the resolving call and the `RecoveryThresholdExceeded` fallback). The
  retry imports the same task file and runs the task moments later, so this
  adds nothing a retry cannot already do, and keeps recovered metrics and
  finalization as they were.
- eval-set's `_recover_crashed_log()` uses the default `trust_log=False` and
  passes `_untrusted_metrics="warn"` on both of its recovery calls, so a
  resolution failure recovers the log without results and warns rather than
  stopping the eval set. The paired task file has already been loaded to
  build the task (a log pairs with a task only when its task identifier,
  which starts with `task_file`, matches), so metrics defined in or imported
  by it are registered. The difference trust would make is a metric whose
  recorded options hold a model or a non-metric registry object: eval-set
  refuses it, recovers that log without results, and with a resolving
  `incomplete_action` re-runs its in-progress samples rather than resolving
  them. Metric definitions are not part of the task identifier, so eval-set
  does not take the log's word for them.
- `score_async()` resolves the log's metrics for `--action overwrite`
  trusted or untrusted according to where the scorers came from
  ([below](#inspect-score)).

### eval-set resume uses the sandbox of the user's task

The internal `PreviousTask` carries the sandbox to resume in, and
`resolve_previous_task()` uses it as given:

- eval-set (`as_previous_tasks()`, also used by scanner resume, and
  `_resumed_task()`) copies `ResolvedTask.sandbox`: the resolution a fresh
  run of the task gets from its definition and `--sandbox`, including an
  override a caller already resolved onto a `ResolvedTask`.
- eval-retry keeps `resolve_task_file_sandbox(log.eval.task_file,
  log.eval.sandbox)`. A retry replays the original run's sandbox, including a
  `--sandbox` override only the log remembers, with relative config paths
  resolved against the recorded task file.

The sandbox stays out of `task_identifier` (decision: Ransom, 2026-10-06), so
a user can resume on different infrastructure (Docker to Kubernetes, or
adding `--sandbox`). A resumed log can then hold samples completed in the old
sandbox and samples run in the new one, and its header records the new
sandbox, as for the other fields the identifier excludes.

### `model_info()` does not construct providers

`inspect_ai.analysis.model_info()` looks names up with
`_get_model_info_direct()`: the caller's `model_info` mapping, models
registered with `set_model_info()`, and the model database with its aliases.
It never falls back to constructing the provider, as `get_model_info()` does
(decision: Ransom, 2026-10-06, "direct lookup only"). Names that resolve only
through provider canonicalization get no metadata unless the caller supplies
it. The public `get_model_info()` is unchanged.

## Run operations

### `inspect score`

Scorer resolution stays in the CLI, before `score_async()`, and `score()` /
`score_async()` keep their public signatures (decision: Ransom, 2026-10-16).

**Recorded scorer names are registry names.** For the names taken from the
log (`eval.scorers[*].name`, or `results.scores[*].name` for logs without
`eval.scorers`), `resolve_scorers()` calls `scorer_from_log_name()`, never
`scorer_from_spec()`. A recorded name containing `@`, or one that happens to
be an existing path, is looked up in the registry like any other name and is
never imported. Inspect writes scorer names from the registry's unqualified
name, so no log Inspect produced is affected. `--scorer` goes through
`scorer_from_spec()`, so `--scorer path.py@name` loads that file, and a bare
`--scorer NAME` reaches `scorer_from_log_name()` (decision: Ransom,
2026-10-14).

`scorer_from_log_name()` tries `scorer_from_registry()`; when that raises
`ValueError` (not registered, or a registered factory rejecting the recorded
options) it imports the recorded task file with `load_module()` and tries the
registry again, with the return-annotation check and `PrerequisiteError`
messages of the spec loader.

**The fallback import is recorded.** Just before the import,
`scorer_from_log_name()` prints with `print_record()` and logs at `INFO`:
`Imported task file /abs/path/evals/task.py (recorded in the log) to load scorer 'my_scorer'.`
`print_record()` prints through the display only once a display type has been
chosen (as the CLI does at startup) and not under `--display none`; it never
creates the display early, so a library caller's later choice of display
still applies. Nothing is returned to or threaded through `resolve_scorers()`
(decision: Ransom, 2026-10-21): other callers of `resolve_scorers()`, such as
inspect-action's sample editor, get the `INFO` line, and the printed line only
if they have chosen a display. Each import prints its line.

When the log's model is used (no `--model`) and the log records a
`model_base_url`, the CLI prints
`Scoring model openai/gpt-4o from the log, base URL https://example.com/v1.`
with `print_record()`, and `score_async()` logs the same line at `INFO`. The
task file is printed as an absolute path, so a relative `task_file` that
resolves to an unexpected file in the working directory shows up. Control
characters in values taken from the log are escaped (`\r`, `\x1b`), so a log
cannot erase or rewrite the line. The records are for the user to check
afterwards, not a mitigation; nothing waits on them.

**The log's metrics resolve before scoring.** `score_async()` calls
`metrics_from_log_header()` (when `metrics` is `None` and the action is
`"overwrite"`) before the scoring loop, so a missing metric or forbidden option
fails before any scorer runs. Under `--stream` the CLI has already called
`log_init()` and `log_start()` on the output, but no sample is read, scored or
written. The tracker depends on where the scorers came from, which only the
CLI knows, through the private keyword-only `_log_scorers` that
`_cli/score.py` sets to `scorer is None`:

- `_log_scorers=True` (`inspect score` without `--scorer`):
  `LogTaskFileImport(log, trust_log=True, import_task_file=False)`. Options
  are rebuilt without restriction and no task file is imported for a metric;
  an unregistered task-level metric fails with `LookupError` unless the
  scorer fallback has already imported the task file and registered it.
- `_log_scorers=False` (`--scorer`, and every `score(log, scorers)` call from
  Python): `LogTaskFileImport(log, trust_log=False, opt_in=SCORE_OPT_IN)`.

`score_async()` still builds the log's model (unless one is passed) and always
builds the log's model roles (see [Not this design](#not-this-design)).

### `eval-retry`

A retry imports the recorded task file and solver file and uses the model,
base URL, model args, sandbox, approval, review, sentinel and ACP settings
from the log, which is its purpose. Its recovery passes `trust_log=True`
([above](#callers-inside-inspect)). It prints no record: the retry's new log
stores the task file, solver, model and base URL, sandbox, sentinel and ACP
settings it used (decision: Ransom, 2026-10-27).

A log with no `task_file` whose task name starts with `hf/` is retried by
downloading `eval.yaml` from the Hugging Face dataset repo the name selects.
That file chooses the dataset (loaded with `trust=False`, so no dataset script
runs) and the arguments of the solvers and scorers it names. The names are
`Literal` allowlists of built-in solvers and scorers, validated before either
loader sees them, but the loaders still pass them through `parse_spec_str()`,
so a path in the working directory named exactly like an allowlisted solver or
scorer shadows it; the repo chooses only the name. The arguments are not
restricted, so a model dict among them builds a model with a base URL the repo
chooses.

### What the docs say

`inspect score --help`, `inspect eval-retry --help`, the `score()` /
`score_async()` docstrings, [Scoring Workflow](../docs/scoring-workflow.qmd)
and [Logs from Others](../docs/eval-logs.qmd#logs-from-others) say that these
commands run code named by the log and use the model endpoint, sandbox and
other settings recorded in it, and to run them only on logs you trust.
`inspect score --help` adds that with `--scorer` the log's metrics are rebuilt
without importing its task file, while the log's model and model roles are
still used. The protection for run operations is the user's choice of log,
stated plainly, not a confirmation prompt (decision: Ransom, 2026-10-06).

## Path resolution

Relative paths resolve against the working directory. Recorded `task_file`
and `--solver` paths are working-directory relative by construction, and a
retry or rescore runs from the original project directory. Resolving against
the log's location would break every log kept in a `logs/` subdirectory, and
requiring a user-supplied match adds a flag to every retry for no gain once
read operations import nothing. Paths are not confined to a project root
(decision: Ransom, 2026-10-06; see Alternatives considered).

## Registry names

A `pkg/name` reference makes `registry_lookup()` load that installed
package's `inspect_ai` entry point, and a miss in `registry_find()` loads all
installed entry points; reading any log can do this, since a non-empty
sandbox config dict makes `SandboxEnvironmentSpec`'s validator call the
sandbox plugin's `config_deserialize()`. Both classes of operation keep this:
it runs only code the reader installed, the same code `inspect eval` loads,
and the log cannot add packages. `ensure_entry_points()` stays in
`registry_lookup()`. The allow-list limits what Inspect's own argument
reconstruction builds for metric options; it does not audit what an installed
factory does with ordinary string options.

## Decisions

- 2026-09-21: retrying and rescoring a log run the task's code by design; a
  user who does not trust a log should not retry or rescore it.
- 2026-10-06: break now. The safe defaults ship without a deprecation period,
  with an actionable error naming the opt-in; this accepts that eval-set
  recovery of a log whose metric options hold a model or non-metric object
  has no results.
- 2026-10-06: the metric-option restriction is enforced where registry
  objects are constructed, not by a separate check that walks the options.
- 2026-10-06: `model_info()` uses direct lookup only.
- 2026-10-06: run operations get a plain statement in the docs and `--help`
  and a printed record, not a confirmation prompt.
- 2026-10-06: loaded files are not confined to the working directory or a
  project root.
- 2026-10-06: the sandbox stays out of the eval-set task identifier; no
  `TASK_IDENTIFIER_VERSION` bump.
- 2026-10-14: rescoring trusts the log's metric definitions only when the
  log's own scorers are used.
- 2026-10-14: a bare `--scorer NAME` the registry cannot build keeps falling
  back to the recorded task file.
- 2026-10-16: scorer resolution stays in the CLI and `score()` keeps its
  signature. Recovery resolves metrics before writing anything rather than
  keeping its inputs after a failure; an untrusted log whose metric no
  installed code defines cannot be recovered directly without `--trust-log`,
  while eval-set recovery warns instead.
- 2026-10-21: the scorer-fallback record is printed where the import happens,
  with nothing threaded back through `resolve_scorers()`.
- 2026-10-22: in recovery the first metric or reducer failure decides: a
  registered factory that fails before a missing name or forbidden option is
  reached makes recovery warn and write without results.
- 2026-10-27: the printed record is limited to `inspect score`; `eval-retry`
  prints none.

## Alternatives considered

- **Keep importing the task file in read operations and warn, or deprecate
  first.** A warning after the import does not stop it, and a deprecation
  release leaves the problem in place for that release.
- **A separate walker over metric options before construction.** It would
  have to recognise exactly the shapes `registry_arg()` constructs; if the two
  ever disagreed the check would pass and the construction still happen.
- **A user-supplied task path instead of a boolean.** Safer in principle, but
  the file is almost always the one the log records, and scripts recomputing
  many logs would need a mapping.
- **Two keywords** (task-file import and model-valued options). Both decide
  whether the log may choose code; two flags double the surface for no gain.
- **Removing model-valued metric options from reconstruction entirely.**
  Retry recovery and `inspect score --action overwrite` would lose results
  of registered custom metrics that take a model.
- **One global trust switch** (an environment variable). It would stay set
  after the user forgot why, and re-enable imports in the viewer once it
  edits scores. Per-call opt-in keeps the decision next to the log.
- **Confirmation before a run operation imports, or a prominent panel.** A
  confirmation breaks scripted `inspect score` and `eval-retry`, whose
  purpose is running the log's code; a panel is easy to miss and suggests
  reading it is the protection.
- **Confining loaded files to the working directory or a project root.** Read
  operations import nothing by default, importing any project file runs its
  top-level code, logs unpacked into the project bring their files inside the
  boundary, absolute recorded paths would break, and the log would still
  choose model args, roles, sandbox and ACP binding, making an untrusted retry
  look safer than it is. Confining the retry solver file to the task file's
  directory likewise adds breakage without removing a capability.
- **Hashing the sandbox into the eval-set task identifier.** Resuming on
  different infrastructure would stop pairing logs, every identifier would
  change, spec equality is fragile (a config path says nothing about the
  file's contents), and on its own it would still let the log's sandbox win
  when identifiers match.
- **Treating every `score()` call as a run operation.** A log the user scores
  only with their own scorer could then build models and other registry
  objects from its metric options.
- **Resolving `--scorer` only through the registry or an explicit path.** The
  user named the scorer, the file is the one rescoring with the log's scorers
  imports, and `inspect score` is documented for trusted logs only.
- **Lazy model construction in `inspect score`.** Changes how `score_async()`
  binds the task context; left under Not this design.

## Compatibility

No stored format, schema or generated TypeScript type is involved. What users
see, by caller (the user docs linked in the Overview cover the fixes):

- `recompute_metrics()` / `edit_score()` with a custom metric defined in the
  task file, in a fresh process: `LookupError` naming the metric. Import the
  module that defines it first, or pass `trust_log=True` for a trusted log.
  `edit_score()` raises before it edits.
- `inspect log recover` / `recover_eval_log()` whose metrics or reducers do
  not resolve untrusted (a task-file metric, an extension that is not
  installed, a forbidden option): an error before anything is written. Install
  or import the definition, or rerun with `--trust-log` for a trusted log.
- `inspect score --scorer ... --action overwrite` and
  `score(log, scorers, action="overwrite")`: the log's `eval.metrics` are
  rebuilt untrusted. Pass `metrics=` (`--metric`), or rescore with the log's
  own scorers. In either mode a log whose metrics cannot be resolved fails
  before any sample is scored.
- `eval_set()` resume: resumed tasks run in the sandbox their definition and
  `--sandbox` resolve to, not the one the previous log records. Eval-set
  recovery of a log whose metric options hold a model or non-metric object has
  no results.
- `inspect_ai.analysis.model_info()`: names that resolve only by instantiating
  their provider get no metadata; supply it with `model_info=` or
  `set_model_info()`.
- Custom metrics taking a model or non-metric registry object as an option
  rebuild only with `trust_log=True` or when rescoring with the log's scorers.
- Recorded scorer names and score keys that are paths are treated as
  unregistered names. Inspect never writes such names.

A score-edit endpoint in the viewer
([viewer log editing](viewer_log_editing.md), Phase 3) must call
`edit_score()` without `trust_log`, since the viewer serves logs it did not
write. A task-file metric or forbidden metric option then raises before the
edit is applied, and the endpoint returns it as HTTP 400 without writing the
log.

## Security

Untrusted input: every field of an eval log header and sample (`.eval` or
`.json`), the sample buffer next to a log, and every file in a log directory
an eval set resumes from.

- Read operations import no file named by a log: score keys resolve through
  the registry only, the task file needs `trust_log=True`, and eval-set's
  recovery, whose task file is the user's own and already loaded, imports
  nothing.
- Read operations construct no model provider from log values and no registry
  object outside the metric and reducer registries, unless the caller passes
  `trust_log=True`. The allow-list is enforced in `registry_arg()`, the code
  that constructs.
- eval-set resume does not let a log choose the sandbox type or config of a
  task the user chose, including inline compose configs, which would
  otherwise run the log's images with the log's mounts.
- `inspect score` imports at most the recorded task file, through the scorer
  fallback, and records each import. Recorded scorer names are never parsed
  as paths. With the user's scorers the log's metrics import nothing and their
  options are restricted, and metric resolution happens before any scorer
  runs.
- What remains in read operations is installed code chosen by name: entry
  points of installed packages, their registered metric and reducer factories
  called with log arguments, registered scorer factories called with no
  arguments by `ScorerInfo.from_name()`, and sandbox plugins'
  `config_deserialize()` during parsing. A plugin that treats a string option
  as a path or model name is trusted installed code.
- What remains in run operations is their purpose: the task file, the solver
  file (retry), the Hugging Face repo and its `eval.yaml` (retry of an `hf/`
  task), the model and its base URL and args, the model roles, the sandbox,
  approval and review policies, the sentinel configuration (installed monitor
  and protocol factories built with the log's parameters), and the ACP
  binding. The printed records show some of these but are not a safeguard.

The viewer's rendering of log content is a separate threat (content, not
code) and is not covered here.

## Not this design

- **Credentials to a log-chosen endpoint.** `eval-retry` builds the model with
  `eval.model_base_url` and `eval.model_args`, and `inspect score` does the
  same unless `--model` is given, so the user's provider key is sent to the
  base URL the log names. `inspect score` also always builds the log's model
  roles, with their base URLs and args, even when `--model` is passed or no
  scorer uses a model, and model args can enable provider behaviour such as
  Hugging Face `trust_remote_code` or a vLLM server launch.
- **ACP server replay.** `eval-retry` reuses `eval.config.acp_server`, which
  may bind a TCP port on any interface (`0.0.0.0:<port>`).
- **Retry sandbox from the log.** A retry keeps the log's sandbox type and
  config, including inline compose configs. Intended under the trust model,
  but a retry of an untrusted log then runs the log's containers with the
  log's mounts; the docs and `--help` only warn about it.
- **Parse-time plugin code.** Reading any log calls the sandbox plugin named
  by a sandbox type with a non-empty config dict, and may load every installed
  entry point.
- **Dataframe column bug.** `EvalColumn("model_args", path="eval.model_base_url")`
  in `analysis/_dataframe/evals/columns.py` maps `model_args` to the base URL.
