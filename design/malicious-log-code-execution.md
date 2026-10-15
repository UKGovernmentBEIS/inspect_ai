# Code execution from a malicious eval log

Status: proposed, 2026-10-06. Issue: none (task from Ransom Richardson). Author: agent (Claude), reviewed by Codex; see the PR.

## Overview

Reading an eval log someone else wrote should not run their code. Today
several "read" operations can: recomputing metrics after a score edit,
recovering a crashed log, and resuming an eval set can import a Python file
the log names, build a model provider from values in the log, or (on
eval-set resume) let the log pick the sandbox. This design splits Inspect's
operations into two kinds. Run operations (`eval-retry`, and `inspect score` /
`score()` with the log's own scorers) exist to run the log's task, so they
keep doing that, and their docs and `--help` say to use them only on logs you
trust. Read operations stop doing any of the above. Rescoring with scorers
the user supplies treats the log's metric definitions the way a read
operation does. A caller who trusts a log can pass `trust_log=True` to get
today's behaviour back, which matters for custom metrics defined in a task
file.

Concretely: sample score keys are looked up only in the registry; the task
file is imported for unregistered metrics only with `trust_log=True`;
metric options from an untrusted log can build only metrics and reducers,
enforced where registry objects are constructed; a resumed eval set uses the
sandbox of the user's task; and dataframe `model_info()` stops instantiating
providers.

## Why

An eval log is data, but several Inspect operations turn fields of a log into
Python imports, registry object construction, model provider construction, or
sandbox configuration. A log is often not written by the person who opens it:
logs are shared for analysis, a collaborator hands over a log directory to
resume, results bundles are published. Whoever writes the log controls every
field in it (`eval.task_file`, `eval.scorers`, `eval.metrics`, sample score
keys, model name, args and base URL, sandbox spec, and so on). They do not
control the victim's installed packages or command line.

Some of these operations are meant to run the log's code. Retrying an eval
(`eval-retry`) or rescoring it (`inspect score`) runs the task's code by
design (decision: Ransom, 2026-09-21). Other operations only read the log:
recomputing metrics after an edit, recovering a crashed log, resuming an
eval set whose tasks come from the user's command line. Today several of
those read operations also import a Python file that the log names, without
the user asking for it. This design separates the two, removes the
log-selected imports and constructions from the read operations, and
narrows what the run operations can be made to load.

## Goals and non-goals

Goals:

- A stated trust model: which operations run code the log selects, and which
  only read the log.
- Read operations never import a Python file because a log names it, never
  construct a model provider from log values, and never let the log replace
  the sandbox of a task the user chose. Custom metrics that live in a task
  file keep working through an explicit opt-in.
- Run operations load only the files their purpose requires (the recorded
  task file, and for a retry the recorded solver file, or for a retry of an
  `hf/` task the Hugging Face repo the log names), and the docs and `--help`
  say plainly that they run code and use settings named by the log.
- Malicious-log tests that prove the read operations import nothing, and tests
  that keep the legitimate flows working.

Non-goals:

- Making `eval-retry` or `inspect score` safe on an untrusted log. They run
  the log's task code by design; a user who does not trust a log should not
  retry or rescore it.
- Removing registry lookups of installed packages (`pkg/name` references).
  The victim chose to install those packages, and `inspect eval` loads the
  same entry points routinely. See "Registry names" under Design.
- Credential and network exposure from the log's model base URL, ACP server
  binding and sandbox on a retry (listed under "Not this design").
- Hardening the viewer's rendering of log content, which is a separate
  threat (content, not code).

## Current behaviour

Verified against `main` at 00de28bd5 by reading the code and by running small
scripts against the worktree's install (a marker module that appends to a file
when imported, and a spy on `get_model`). Line numbers are from that commit.

### Where log values become imports

There are three ways a log value reaches `load_module()`
(`src/inspect_ai/_util/module.py:20`), which executes a `.py` file (or
`.ipynb` notebook) with `SourceFileLoader`:

- **`parse_spec_str()`** (`src/inspect_ai/_eval/loader.py:964`) turns
  `<path>@<name>` into a resolved path and a name, and also treats any string
  that is an existing path as a file. `scorer_from_spec()`
  (`loader.py:773`), `solver_from_spec()` (`loader.py:647`) and
  `metric_from_spec()` (`loader.py:900`) then call `load_module()` on that
  path with no filter (`loader.py:867`, `:693`, `:939`).
- **The scorer fallback**: `scorer_from_spec()` given a bare name that is not
  registered imports `task_path` with no filter (`loader.py:850`).
- **`load_file_tasks()`** (`loader.py:548`) imports a task file, gated only on
  the source containing a function decorated `@task` or `@task_source`
  (`loader.py:597`, `:631`). Decorated functions are registered, not called;
  module top-level code runs.

Relative paths resolve against the process working directory
(`Path(...).resolve()` / `.absolute()`). `task_file` is recorded relative to
the working directory when the task is under it and absolute otherwise
(`task_file(task, relative=True)`, `loader.py:118`;
`cwd_relative_path()`, `src/inspect_ai/_util/path.py:91`), so resolving
against the working directory is what lets a retry run from the original
project directory.

### Read operations that import or construct today

**A. Sample score keys are parsed as scorer specs.** `eval_results()`
(`src/inspect_ai/_eval/task/results.py:137-141`) calls
`ScorerInfo.from_name(name)` for every score key whose `SampleScore.scorer`
is unset and that no known scorer produced. `from_name()` calls
`scorer_from_spec(ScorerSpec(scorer=name), task_path=None)`
(`results.py:76`), so a key of the form `<path>@<name>`, or a key that is an
existing path, is imported. The surrounding `try`/`except` only discards the
error after the module has run. `recompute_metrics()`
(`src/inspect_ai/log/_metric.py:34`) and recovery
(`src/inspect_ai/log/_recover/_write.py:165`, `:240`) build their
`SampleScore`s without `scorer=`, so every score key of every sample in the
log or in the sample buffer goes through this path. Confirmed by running
`recompute_metrics()` on a log whose only sample has such a key: the named
module was imported. During a normal eval the keys come from the task's own
code, and resumed samples carry `scorer=` (`src/inspect_ai/_eval/task/run.py:1426`).

**B. The task file is imported to find unregistered metrics.**
`resolve_scorers_info()` (`src/inspect_ai/_eval/score.py:648`) calls
`load_file_tasks(Path(log.eval.task_file).absolute())` the first time a scorer
metric name is not registered (`score.py:660-665`), added by #3981 so custom
metrics defined in task files resolve. Confirmed by running
`recompute_metrics()` on a log naming a task file and an unregistered metric:
the task file was imported, and recompute then still failed with
`LookupError` because the metric was not in that file.

**C. Metric options can construct models and other registry objects.**
`metric_from_log()` (`score.py:590`) calls `metric_create(name, **options)`,
which goes through `create_registry_object()` →
`_instantiate_registry_object()` → `registry_kwargs()`
(`src/inspect_ai/_util/registry.py:452`, `:473`, `:704`). `registry_arg()`
(`registry.py:689`) turns a nested dict shaped like
`{type, name, params}` into a registry object of any registry type, and a dict
shaped like `{model, config, base_url, model_args}` into
`get_model(model, base_url=..., **model_args)` (`registry.py:730`). Confirmed
with a spy: `recompute_metrics()` on a log whose metric options contain a
model dict called `get_model()` with the log's base URL before the metric
factory rejected the argument. Model provider construction can download and
run code: the Hugging Face provider passes `trust_remote_code` from
`model_args` to `from_pretrained()`
(`src/inspect_ai/model/_providers/hf.py:120-167`), and the vLLM provider
starts a server process (`src/inspect_ai/model/_providers/vllm.py:478`).

**D. eval-set resume takes the sandbox from the log.** For a resumed task
`resolve_previous_task()` sets
`sandbox=resolve_task_file_sandbox(log.eval.task_file, log.eval.sandbox)`
(`loader.py:358`), ignoring the sandbox of the task the user is running and
any `--sandbox` override (`resolve_previous_tasks()` is not passed the eval's
`sandbox`, `loader.py:139`). A task-level sandbox type overrides a sample's
(`src/inspect_ai/_eval/task/sandbox.py:287`). The task identifier that pairs
a log with a task does not hash the sandbox
(`src/inspect_ai/_eval/evalset.py:2111-2281`). `SandboxEnvironmentSpec`
accepts an inline config object, which for Docker-compatible types is parsed
into a `ComposeConfig` when the log is read
(`src/inspect_ai/util/_sandbox/environment.py:637-709`). Confirmed with
`resolve_previous_tasks()`: a task declaring `sandbox="docker"` paired with a
log recording `local` resolved to `local`. This behaviour predates eval-set;
it exists for `eval-retry`, which reloads the task and has only the log to say
what `--sandbox` the original run used.

**E. `inspect_ai.analysis.model_info()` constructs model providers.** For a
model name not in the model database, `get_model_info()` falls back to
`get_model(model, api_key=...)` (`src/inspect_ai/model/_model_info.py:388`),
called from `model_info()` (`src/inspect_ai/analysis/_prepare/model_info.py:68`)
with the `model` column taken from `eval.model`. No base URL or model args
reach it, but the log picks the provider and model name, and some providers
download weights or start servers on construction.

### Which operations reach these paths

| Operation | Reaches | Notes |
|---|---|---|
| `recompute_metrics()` | A, B, C | public (`inspect_ai.log`, `inspect_ai`) |
| `edit_score()` | A, B, C | calls `recompute_metrics()` by default (`src/inspect_ai/log/_score.py:146`) |
| `inspect log recover`, `recover_eval_log()` | A, B, C | `_write.py:271-287`; a failure is logged as a warning after the import has run |
| `eval_set()` resume of a `started` log | A, B, C, D | recovery through `_recover_crashed_log()` (`evalset.py:1522`), from `as_previous_tasks()` (`:1504`), from `list_latest_eval_logs()` with a resolving `incomplete_action` (`:1803`), and from selection-worker resume (`:1734`) |
| `eval_set()` resume of any other log | D | |
| `inspect_ai.analysis.model_info()` | E | only for names missing from the model database |
| `eval_retry()`, `inspect eval-retry` | A, B, C via recovery; then the task file, solver file, model, sandbox, approval, review and ACP settings from the log | run operation (`src/inspect_ai/_eval/eval.py:1684-1960`) |
| `inspect score`, `score()`, `resolve_scorers()` | scorer names and options from the log (without `--scorer`); B and C for `--action overwrite`; model and model roles from the log | run operation with the log's scorers (`src/inspect_ai/_cli/score.py:206`, `score.py:263-275`, `:347-349`) |

In eval-set, B only ever imports the user's own task file: a log is paired
with a task only when its task identifier, which starts with `task_file`,
equals the task's (`validate_eval_set_prerequisites()`, `evalset.py:2039`),
and that file has already been loaded to build the task. A, C and D are not
bound by the identifier: score keys, metric options and the sandbox are not
part of it.

For `inspect score` with the log's scorers (`resolve_scorers()`,
`score.py:598`), each `eval.scorers[*].name` (or `results.scores[*].name` for
logs without `eval.scorers`) goes through `scorer_from_spec()`, so a recorded
name of the form `<path>@<name>` imports that path and a bare unregistered
name imports the recorded task file with no decorator filter. Confirmed with
`inspect score --action overwrite` on two crafted logs: one imported the file
named in the scorer name, the other imported the task file relative to the
working directory. Inspect itself never records such a scorer name: scorer
names are written from `registry_unqualified_name()` through `as_scorer_spec()`
(`src/inspect_ai/scorer/_scorer.py:212`, called at `src/inspect_ai/_eval/run.py:285` and
`score.py:385`).
Solver specs are different: `--solver path.py@name` is recorded verbatim in
`eval.solver` (`src/inspect_ai/_cli/eval.py:2137`, `_eval/task/log.py:294`),
and `eval-retry` relies on it.

A log with no `task_file` whose task name starts with `hf/` is retried
without a registry check (`src/inspect_ai/_eval/eval.py:1746`):
`task_create_from_hf()` downloads `eval.yaml` from the Hugging Face dataset
repo the name selects and builds the task from it
(`src/inspect_ai/_eval/task/hf.py:83-200`). That file chooses the dataset
(loaded with `trust=False`, so no dataset script runs) and the arguments of
the solvers and scorers it names, which go through `solver_from_spec()` and
`scorer_from_spec()`. The names cannot select a file: `HFSolver.name` and
`HFScorer.name` are `Literal` allowlists of built-in solvers and scorers
(`hf.py:25`, `:39`), validated by `HFTask.model_validate()` (`hf.py:132`)
before either loader sees them. The arguments are not restricted, so a model
dict among them builds a model with a base URL the repo chooses
(`registry.py:689-739`).

`score_async()` also builds the log's model (`get_model(log.eval.model,
base_url=log.eval.model_base_url, **log.eval.model_args)`, `score.py:263`)
unless the caller passes one, and always builds the log's model roles
(`score.py:275`).

### Operations with no such path

Checked by tracing their calls:

- `inspect view` (`src/inspect_ai/_view/fastapi_server.py`): its endpoints
  read logs, headers, buffers and eval-set info. `/log-edit` handles only tag
  and metadata edits (`src/inspect_ai/log/_edit.py:33-58`) and recomputes
  tags and metadata, not metrics. There is no score-editing endpoint; the
  viewer client (`ts-mono`, `api-view-server.ts`) and the VS Code extension
  (`inspect-view-server.ts`) call only `/log-edit`. A score-edit endpoint is
  planned (`design/viewer_log_editing.md`, Phase 3) and would call
  `edit_score()`.
- `inspect log list/dump/convert/convert-chunked/headers/schema/types`,
  `inspect log recover --list`, `inspect info`, `list`, `trace`, `cache`,
  `sandbox`, `download`, `acp`, `ctl` (including `--log-dir` mode, which
  already has a tripwire test,
  `tests/_control/test_log_dir.py:1046`), and dataframes (`evals_df` and
  friends) apart from the `model_info()` operation above.
- `inspect log export-config` only serializes the header. Its output is a run
  config the user may later pass to `inspect eval --run-config`, which is the
  user's choice to run.

### Registry names

Every operation above resolves names through the registry. A name with a
package prefix (`pkg/name`) makes `registry_lookup()` load that installed
package's `inspect_ai` entry point (`registry.py:262-299`,
`src/inspect_ai/_util/entrypoints.py:7`); a miss in `registry_find()` loads
all installed entry points (`registry.py:309-329`). This happens on every log
parse: a non-empty sandbox config dict makes `SandboxEnvironmentSpec`'s
validator look up the sandbox type and call that plugin's
`config_deserialize()` (`environment.py:637-709`). Only installed code runs.

## Design

### Trust model

An operation is a **run operation** when its purpose is to execute the task
the log describes: `eval_retry()` / `inspect eval-retry`, and rescoring with
the log's own scorers (`inspect score` without `--scorer`, or `score()` /
`score_async()` with `scorers=None`, step 6). Running one on a log means
trusting the log's task code. Everything else is a **read operation**:
viewing, listing, converting, analysis, `recompute_metrics()`,
`edit_score()`, `recover_eval_log()` / `inspect log recover`, and `eval_set()`
(whose tasks come from the user's command line; the logs only supply
completed samples).

Rescoring with scorers the user supplies (`inspect score --scorer`, or
`score()` / `score_async()` given scorers) sits between the two. It still
runs scorers in a task context built from the log's model, model roles and
samples, as today (the credential exposure is under "Not this design"), so
its docs and `--help` carry the same trusted-logs statement as the run
operations. But nothing about it asks for the log's code: the log's metric
definitions, which `--action overwrite` rebuilds, are resolved as in a read
operation, with no task-file import and under step 3's restrictions.

| Operation | Python files the log can make Inspect import, after this design |
|---|---|
| read operations | none, unless the caller passes `trust_log=True` (`inspect log recover --trust-log`) to recompute or recover, which imports the recorded task file |
| `inspect score` without `--scorer`, `score(log, None)` | the recorded task file, and only when a recorded scorer or metric name is not registered |
| `inspect score --scorer NAME`, `score(log, scorers)` | none for metrics. The recorded task file only when `--scorer` is a bare name that is not registered: the existing fallback in `scorer_from_spec()` that finds a scorer the user named in their task file, kept, and now made through the tracker so it is imported once and recorded (decision: Ransom, 2026-10-14; step 6) |
| `eval-retry` | the recorded task file and the recorded solver file. A log with no `task_file` and an `hf/` task name instead makes the retry fetch that Hugging Face repo's `eval.yaml`, which imports no local file but chooses the dataset and the arguments of the built-in solvers and scorers it names |

In every class, registry names may load installed packages' entry points and
call their registered factories (see "Registry names" below).

Run operations, and read operations whose caller passes `trust_log=True`,
rebuild a log's metric definitions as today. Other read operations, and
rescoring with the user's scorers, rebuild them under the restrictions of
step 3.

### 1. Score keys are registry names (fixes A)

`ScorerInfo.from_name()` stops calling `scorer_from_spec()`. It resolves the
name only through the registry:

```python
# src/inspect_ai/_eval/loader.py
def scorer_from_registry(name: str, /, **kwargs: Any) -> Scorer:
    """Create a registered @scorer or @scanner by name.

    Raises:
        ValueError: If no scorer or scanner is registered under `name`.
    """
```

This is the existing nested `create_scorer()` (`loader.py:813-824`) moved to
module level, with `name` positional-only so a scorer option called `name`
still reaches the factory; `scorer_from_spec()` calls it instead of its local
copy. `from_name()` becomes:

```python
try:
    scorer = scorer_from_registry(name)
except Exception:
    scorer = None
```

followed by the existing default-metrics branch. The only change is the
function called: no path parsing, no file loading. The existing broad
`except` is kept on purpose. `eval_results()` reaches `from_name()` from live
final, cancellation and display aggregation (`src/inspect_ai/_eval/task/run.py:1947`,
`:2001`, `:2168`) and from the control server's interim scoring
(`src/inspect_ai/_control/scoring.py:864`), as well as from recompute and
recovery. A solver-written score keyed by a registered scorer that needs
arguments (`pattern`, `answer`, `multi_scorer`, `precomputed_scores`,
`_model_graded_qa_single`) raises `TypeError` when built without them, and
must keep falling back to the default metrics (`accuracy`, `stderr`) as it
does today.

A score key that names a file now gets the default metrics like any other
unregistered key. This is the same result as today for every key that is not
a path, which is every key Inspect writes.

### 2. Trusted metric reconstruction becomes opt-in (fixes B and C)

One object carries the trust decision and the task-file import for one
recompute, recovery or rescore. It lives in `src/inspect_ai/_eval/loader.py`,
next to `load_file_tasks()`, because step 6's `scorer_from_log()` (also in
`loader.py`) uses it and `score.py` already imports from `loader.py`:

```python
class LogTaskFileImport:
    """The trusted task-file import for one recompute, recovery or rescore.

    Shared by every resolver in one operation (log scorers, scorer metrics,
    task-level metrics), so the task file is imported at most once and
    reported once.
    """

    def __init__(
        self, log: EvalLog, *, trust_log: bool, opt_in: str = TRUST_LOG_OPT_IN
    ) -> None:
        """`opt_in` is the closing advice of both untrusted-log errors (the
        step 2 LookupError and step 3's DisallowedRegistryArg), so each
        caller names an option it actually has (below)."""

    trust_log: bool
    task_path: Path | None  # Path(log.eval.task_file).absolute(), or None
    imported: bool

    def import_for(self, kind: Literal["scorer", "metric"], name: str) -> bool:
        """Import the task file for `name` if trusted, not yet done, and
        `task_path` exists, with load_file_tasks(); log the record line
        (below) once. Returns whether the task file has been imported."""
```

The metric resolvers (`score.py:562`, `:590`, `:648`) take it instead of a
flag. They are internal (their only callers are `score.py`,
`log/_metric.py` and `log/_recover/_write.py`), and passing the tracker
rather than a boolean is what lets callers share one import:

```python
def resolve_scorers_info(
    log: EvalLog, *, task_import: LogTaskFileImport | None = None
) -> list[ScorerInfo]: ...
def metrics_from_log_header(
    log: EvalLog, *, task_import: LogTaskFileImport | None = None
) -> ...: ...
def metric_from_log(
    metric: EvalMetricDefinition, *, task_import: LogTaskFileImport | None = None
) -> Metric: ...
```

`task_import=None` means a fresh untrusted tracker. The resolvers build each
definition with `metric_from_log(..., task_import=task_import)`, which
selects step 3's restriction from `task_import.trust_log` and takes its
advice text from `task_import.opt_in`. Each resolver makes the
metric definitions it consumes resolvable before building anything, through
one shared implementation:

```python
def ensure_metrics_registered(
    definitions: Iterable[tuple[EvalMetricDefinition, str]],
    task_import: LogTaskFileImport,
) -> None:
    """Make every metric in `definitions` resolvable, or raise.

    Each definition comes with the label used in the error ("used by scorer
    'my_scorer'" or "a task-level metric"). Walks nested metric registry
    dicts inside options too. If any metric is not registered, calls
    task_import.import_for("metric", name); then raises the shared
    LookupError for any still missing.
    """
```

- `metrics_from_log_header()` checks only `eval.metrics` (task-level
  metrics, `_eval/task/log.py:278`, `:310`).
- `resolve_scorers_info()` checks only `eval.scorers[*].metrics`.

Each resolver checks only what it builds, because some callers discard the
other source. `inspect score --scorer ... --action overwrite`
(`docs/scoring-workflow.qmd:83`) calls `metrics_from_log_header()`
(`score.py:348`), uses the replacement scorer's metrics, and then replaces
`eval.scorers` (`score.py:385-401`). It must keep succeeding when the old
`eval.scorers` names a custom metric that is no longer available, without
importing the old task file.

`recompute_metrics()` and recovery consume both sources: they call
`metrics_from_log_header()` before `resolve_scorers_info()`
(`log/_metric.py:40-41`, `_write.py:273-274`) and pass both the same
`LogTaskFileImport`, so the task file is imported at most once per
recompute or recovery. Rescoring shares one tracker between its scorer
resolution and its metric resolution in the same way (step 6). A custom
task-level metric defined in the task file
is covered as well as a scorer metric. Today, in recompute and recovery,
only scorer metrics trigger the import (`score.py:657-666`), and because
task-level metrics are resolved first, an unregistered task-level metric
fails with the registry's generic "not found" `LookupError`. Rescoring
differs today; see the `score_async()` bullets below.

When the trusted import runs, `LogTaskFileImport.import_for()` logs
`Imported task file /abs/path/evals/task.py (recorded in the log) to load metric 'my_metric'.`
(or `scorer 'my_scorer'`, for the name that triggered it) at `INFO`, once
per tracker, and the CLI commands that can trigger it (`inspect score`,
`inspect log recover --trust-log`) print it as part of the step 7 record.

`trust_log=True` means the caller trusts the log's code-selecting fields. It
does what happens today for scorer metrics, extended to task-level metrics:

- The first unregistered metric name in a source a resolver consumes
  triggers `load_file_tasks(Path(task_file).absolute())`, once per
  `LogTaskFileImport`, resolved against the working directory, with the
  `@task`/`@task_source` filter.
- Metric options are rebuilt by `metric_create()` with no restriction, so a
  custom metric whose options hold a model or another registry object is
  rebuilt as it is today.

With `trust_log=False`:

- No import. An unregistered metric name, in whichever source the resolver
  consumes, raises
  `LookupError` (the type raised today when a metric cannot be found, so
  callers that catch it keep working) with one shared message that says
  what to do:

  ```
  Metric 'my_metric' (used by scorer 'my_scorer') is not registered. If it is
  defined in the task file ('evals/task.py'), import that module first.
  To trust the log, pass trust_log=True (inspect log recover: --trust-log);
  this imports the log's task file and runs its code, so do it only for logs
  you trust.
  ```

  For a task-level metric the parenthesis reads "(a task-level metric)".
  The last sentence is the tracker's `opt_in` text, which depends on the
  caller, because only some callers have `trust_log`:

  - `TRUST_LOG_OPT_IN`, the default (`recompute_metrics()`, `edit_score()`,
    recovery): the `trust_log` sentence above.
  - `SCORE_OPT_IN`, for rescoring with the caller's scorers (`score()` and
    `score_async()` have no `trust_log`): "To score without the log's
    metrics, pass metrics= (inspect score: --metric). If you trust the log,
    rescore with its own scorers instead (scorers=None; inspect score
    without --scorer), which imports its task file and runs its code."

  With `trust_log=True` the same message, without the opt-in sentence, is
  raised for a metric the task file does not define either.

- Metric options are rebuilt in the restricted mode of step 3.

One keyword covers both because both answer the same question, whether the
log may choose code, and a user who trusts a log for one has no reason to
distrust it for the other. It is threaded through every public caller,
keyword-only and defaulting to `False`:

- `recompute_metrics(log, *, trust_log: bool = False)`
  (`src/inspect_ai/log/_metric.py`), which creates one `LogTaskFileImport`
  and passes it to both `metrics_from_log_header()` and
  `resolve_scorers_info()`.
- `edit_score(..., *, trust_log: bool = False)`
  (`src/inspect_ai/log/_score.py`), which resolves metrics before it edits
  (below).
- `recover_eval_log(..., trust_log: bool = False)` and
  `recover_eval_log_async(...)` (`src/inspect_ai/log/_recover/_api.py`),
  passed to `write_recovered_eval_log()` (`_write.py:89`), which creates one
  tracker for both functions (`_write.py:273-274`).
- `inspect log recover --trust-log` (`src/inspect_ai/_cli/log.py`,
  `recover_command`). Its help text says it imports the task file and runs
  its code.

**`edit_score()` resolves metrics before it edits.** Today it sets the score,
appends to `score.history` and inserts a `ScoreEditEvent`, then calls
`recompute_metrics()` (`log/_score.py:71-147`). Under the new default a
fresh-process edit of a log with a task-file metric would raise after the
edit was applied, leaving edited scores with stale `results`, and the retry
the error suggests (`trust_log=True`) would add a second history entry and a
second event. So `recompute_metrics()` is split into its two phases
(`src/inspect_ai/log/_metric.py`):

```python
class LogMetrics(NamedTuple):
    reducers: list[ScoreReducer] | None
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None
    scorers: list[ScorerInfo]

def resolve_log_metrics(log: EvalLog, *, trust_log: bool = False) -> LogMetrics:
    """Rebuild the log's reducers and metrics. Reads only the header; may
    import the task file (trust_log=True); raises LookupError or
    DisallowedRegistryArg."""

def compute_log_metrics(log: EvalLog, resolved: LogMetrics) -> None:
    """eval_results() over the samples' scores; sets results and reductions."""

def recompute_metrics(log: EvalLog, *, trust_log: bool = False) -> None:
    compute_log_metrics(log, resolve_log_metrics(log, trust_log=trust_log))
```

`edit_score()` finds the sample as today (`log/_score.py:44-69`), then, when
`recompute_metrics=True`, calls `resolve_log_metrics()` before its first
mutation (the `sample.scores = {}` initialisation at `:72`), validates and
applies the edit as today, and calls `compute_log_metrics()`. The
resolution reads only header fields (`eval.metrics`, `eval.scorers`,
`eval.config.epochs_reducer`), which the edit does not touch, so resolving
first gives the same metrics. A missing
metric or a forbidden metric option now raises with the log unchanged, and
a retry with `trust_log=True` applies the edit once. An exception raised by a
metric function while computing over the edited scores still leaves the edit
applied, as today; that is not a trust question.

Recovery keeps its current error handling: it catches any exception from
metric resolution and computation (`except Exception`, `_write.py:286`) and
logs the existing warning ("Unable to recompute metrics for recovered log:
...", `:287`), now carrying the messages above, and the recovered log has no
results, as today when resolution fails.
Without results a resolving recovery (`incomplete_action` other than
`"retry"`) does not finalize (`_write.py:314`): the log stays retryable and
its in-progress samples are re-run instead of resolved.

**A recovery without metrics keeps its input, so it can be repeated.** The
remedy the messages give is to recover again with `trust_log=True`. Today
that second recovery is impossible under the defaults:
`recover_eval_log()` and `recover_eval_log_async()` default to
`cleanup=True` (`_recover/_api.py:118`, `:181`), which the CLI passes unless
`--no-cleanup` is given (`_cli/log.py:488`), and the buffer is removed
whatever the outcome (`_api.py:325-329`); a second recovery then raises
`RecoveryNotAvailable` (`:229-231`). With `overwrite=True` the crashed log is
also replaced by the recovered one (`:318-322`), which
`read_crashed_eval_log()` rejects as input because it has `header.json`
(`_recover/_read.py:72-75`). So, in `src/inspect_ai/log/_recover/`:

- `RecoveryStats` (`_write.py:39`) gains `metrics_error: str | None`, which
  `write_recovered_eval_log()` sets to the exception's message in its
  existing `except Exception` branch (`_write.py:286`). The rule covers
  every failure in that block, not only the trust refusals: whatever the
  cause (an untrusted log, a metric not installed, a metric that raised),
  a recovered log without results is incomplete, and keeping the input is
  what lets the user fix the cause and recover again.
  `recover_eval_log_async()` always passes a `RecoveryStats` to the writer,
  creating one when the caller's `_stats` is `None`.
- When `metrics_error` is set, `recover_eval_log_async()` does not remove
  the buffer, whatever `cleanup` says. Under `cleanup="finalized"` this is
  already so, because a log without results never finalizes; the change
  affects `cleanup=True`, the API and CLI default. `cleanup=False` is
  unchanged.
- When `metrics_error` is set and `overwrite=True`, the crashed log is not
  replaced: the recovered log stays at the temporary sibling path the
  overwrite writes first (`default_output_path(log)`, `<name>-recovered.eval`)
  and is returned from there, so `inspect log recover` prints that path.
- The writer's warning gains a second sentence: "The crashed log and its
  sample buffer were kept, so it can be recovered again." The opt-in
  advice is already in the error text it carries.

The second recovery takes the original crashed log as input, not the
`-recovered.eval` output, and writes the same output path again. The guard
against a newer file (`_api.py:207-226`) counts only `success` logs, and
the first output has status `error`, so it does not block the rerun. With
results, the second recovery removes the buffer as usual, finalizes under
a resolving `incomplete_action`, and with `overwrite=True` replaces the
crashed log.

Inspect's own callers keep their cleanup choices and are unaffected:
eval-retry uses `cleanup="finalized"` and then `cleanup=False` for the
threshold fallback (`eval.py:1728-1741`), eval-set the same
(`evalset.py:1575-1586`), and none of them pass `overwrite`.

Callers inside Inspect:

- `eval_retry_async()` passes `trust_log=True` to both recovery calls
  (`eval.py:1701` and the threshold fallback at `:1712`). The retry imports
  the same task file and runs the task moments later, so this changes
  nothing a retry can do, and keeps the recovered log's metrics and
  finalization identical.
- `score_async()` creates one `LogTaskFileImport` with
  `trust_log=scorers is None` and `opt_in=SCORE_OPT_IN`, and passes it to `resolve_scorers()` (step 6)
  and to `metrics_from_log_header()` (`score.py:348`, used by
  `--action overwrite`). Only rescoring with the log's own scorers is a run
  operation:
  - With `scorers=None` (`inspect score` without `--scorer`), log metric
    options are rebuilt without restriction, as today, and an unregistered
    task-level metric makes it import the recorded task file, the same file
    its scorer resolution may import, once for both. Today such a metric
    resolves only if some log scorer was unregistered: the CLI's
    `resolve_scorers()` then ran `load_module(task_path)`
    (`loader.py:850-856`) before `score_async()`, registering the file's
    metrics. When every log scorer is registered, it fails with the generic
    `LookupError`; the new import changes only that case.
  - With scorers the caller supplies (`--scorer`, or `score(log, scorers)`),
    the log's metrics are resolved on the safe default: no task-file import,
    and step 3's restrictions. Today metric resolution on this path imports
    nothing (an unregistered metric fails with the generic `LookupError`),
    unless a bare unregistered `--scorer NAME` has already imported the task
    file and so registered its metrics (step 6 keeps that fallback). It
    rebuilds any model or registry object in the metric options; after this
    design it refuses them. The caller can pass `metrics=` (`--metric`) to
    replace the log's metrics.
  - Either way, `score_async()` resolves these metrics before it builds a
    model or scores a sample (step 6, "Order in `score_async()`"), so a
    missing metric or a forbidden option fails before any scorer runs.
- eval-set recovery (`_recover_crashed_log()`, `evalset.py:1522`, reached
  from `as_previous_tasks()`, `list_latest_eval_logs()` and `_resumed_task()`)
  uses the default `False`. The paired task file has already been loaded to
  build the task (see Current behaviour), so metrics defined in or imported
  by it are registered and recovery results do not change for them. The one
  difference: a metric whose recorded options hold a model or a non-metric
  registry object is refused by step 3, recovery of that log has no
  results, and with a resolving `incomplete_action` its in-progress samples
  re-run rather than being resolved, which is what the default `"retry"`
  disposition does anyway. No built-in metric takes such options, and
  eval-set does not take the log's word for them because metric definitions
  are not bound by the task identifier.

### 3. Untrusted metric options cannot construct models or non-metric objects (fixes C)

Decision: Ransom, 2026-10-06. The restriction is enforced where the objects
are constructed, not by a separate check that walks the options first. A
separate walker would have to recognise exactly the shapes `registry_arg()`
constructs; if the two ever disagreed, the check would pass and the
construction would still happen.

`create_registry_object()` gains a keyword-only allow-list, threaded down to
the code that turns option values into objects
(`src/inspect_ai/_util/registry.py:452-473`, `:689-706`):

```python
LOG_METRIC_OPTION_TYPES: frozenset[RegistryType] = frozenset({"metric", "score_reducer"})

def create_registry_object(
    type: RegistryType,
    name: str,
    args: dict[str, Any],
    *,
    allowed_types: frozenset[RegistryType] | None = None,
) -> object: ...

def _instantiate_registry_object(
    obj: Callable[..., object],
    args: dict[str, Any],
    *,
    allowed_types: frozenset[RegistryType] | None = None,
) -> object:
    instance = obj(**_resolve_registry_args(args, allowed_types=allowed_types))
    ...

def _resolve_registry_args(
    args: dict[str, Any], /, *, allowed_types: frozenset[RegistryType] | None
) -> dict[str, Any]: ...

def registry_arg(
    arg: Any, /, *, allowed_types: frozenset[RegistryType] | None = None
) -> Any: ...
```

- With `allowed_types=None` (the default) nothing changes: scorer
  reconstruction for `inspect score` and retry, solver and approver
  reconstruction, and every other caller behave as today.
- With an allow-list, `registry_arg()` raises `DisallowedRegistryArg` (a
  `ValueError`) on a model dict, or on a registry dict whose type is not in
  the list, instead of constructing it. An allowed nested registry dict is
  constructed with `create_registry_object(..., allowed_types=allowed_types)`,
  so the restriction applies at every depth.
- `create_registry_object()` adds the object's type and name to the error,
  and the nested call sites add the option key path, so the message names
  the metric and the offending option, e.g.:

  ```
  Metric 'grouped' option 'metric.params.model': a model cannot be created
  from metric options in an untrusted log. To trust the log, pass
  trust_log=True (inspect log recover: --trust-log); this imports the log's
  task file and runs its code, so do it only for logs you trust.
  ```

  The registry layer raises the first sentence only; it knows nothing of
  callers. `metric_from_log()` catches `DisallowedRegistryArg` and re-raises
  it (`raise DisallowedRegistryArg(f"{e} {task_import.opt_in}") from e`) with
  the tracker's `opt_in` sentence, the same one step 2's `LookupError`
  ends with, so `score(log, scorers)` advises `metrics=` / `--metric`, or
  its own scorers for a trusted log, and never a `trust_log` argument it
  does not accept.

- `_resolve_registry_args()` resolves every argument before the outer
  factory is called (as `registry_kwargs()` does today), so a forbidden
  nested value raises before the metric's factory runs.
- The public `registry_kwargs(**kwargs)` keeps its signature and delegates to
  `_resolve_registry_args(kwargs, allowed_types=None)`. Taking the allow-list
  as a keyword of `registry_kwargs()` itself would collide with any option of
  that name, and `inspect_scout` and `inspect_flow` call it with
  `registry_kwargs(**params)`.

`metric_from_log()` (`score.py:590`) calls
`create_registry_object("metric", metric.name, metric.options or {},
allowed_types=None if task_import.trust_log else LOG_METRIC_OPTION_TYPES)`
directly. The
public `metric_create()` keeps its signature and behaviour.

Nested metric registry dicts stay allowed because built-in metrics take
metrics as parameters: `grouped(accuracy(), "category")` records its options
as `{"metric": {"type": "metric", "name": "accuracy", "params": {}},
"group_key": "category"}` (checked by running `registry_params()`). The
restriction covers both sources of metric definitions, `eval.metrics` and
`eval.scorers[*].metrics`, including nested lists and dict groups, since both
go through `metric_from_log()`.

A user recomputing a trusted log whose custom metric takes a model passes
`trust_log=True`. Scorer options are not affected: they are rebuilt only by
`inspect score` and retry, which are run operations, and model-graded scorers
record their grader model as a model dict that rescoring must rebuild.

### 4. eval-set resume uses the sandbox the user's task resolves to (fixes D)

`resolve_previous_tasks()` gains the eval's `sandbox` (passed from
`resolve_tasks()`, `loader.py:139`), and `resolve_previous_task()` chooses the
sandbox by where the task came from:

- `PreviousTask.task` is a `Task` (eval-set: `as_previous_tasks()`,
  `evalset.py:1508`, and `_resumed_task()`, `:1735`): use
  `resolve_task_sandbox(loaded_task, sandbox)` (`loader.py:412`), the same
  resolution a fresh run of that task gets in `as_resolved_tasks()`
  (`loader.py:120`).
- `PreviousTask.task` is a `str` (eval-retry, `eval.py:1927`): keep
  `resolve_task_file_sandbox(log.eval.task_file, log.eval.sandbox)`. A retry
  replays the original run's sandbox, including a `--sandbox` override that
  only the log remembers.

No other field changes. `PreviousTask` keeps its shape.

The sandbox stays out of `task_identifier` (decision: Ransom, 2026-10-06; no
`TASK_IDENTIFIER_VERSION` bump). This step already stops the log choosing the
sandbox on the eval-set path. Hashing it would stop logs pairing when a user
resumes on different infrastructure (Docker to Kubernetes, or adding
`--sandbox`), and comparing a resolved task's sandbox spec with a log's is
fragile: a config path says nothing about the file's contents.

A resumed log can therefore hold samples completed in the old sandbox and
samples resumed in the new one, and its header records the new sandbox. This
is the same as for the other fields the identifier excludes (for example
runtime generate options such as `max_connections`).

### 5. `model_info()` does not construct providers (fixes E)

Decision: Ransom, 2026-10-06 ("direct lookup only").

`model_info()` (`src/inspect_ai/analysis/_prepare/model_info.py:68`) calls
`_get_model_info_direct()` (`src/inspect_ai/model/_model_info.py:319`)
instead of `get_model_info()`. It still checks the caller's `model_info`
mapping, models registered with `set_model_info()`, and the model database
with its aliases; it skips the provider-instantiation fallback. Model names
that resolve only through provider canonicalization get no metadata; the
`model_info` argument and `set_model_info()` cover them. The public
`get_model_info()` is unchanged.

### 6. `inspect score` loads only the recorded task file (narrows a run operation)

Rescoring with the log's scorers becomes a mode of `score()` /
`score_async()` rather than something the CLI assembles first, so the trust
decision and the one task-file import live in one place:

- `score()` and `score_async()` (`score.py:81`, `:213`) accept
  `scorers: Scorers | None`. The parameter stays positional and required
  (omitting it is still a `TypeError`); `None` means "the scorers recorded in
  the log", resolved by `resolve_scorers(log, task_import=...)` with the
  tracker of step 2 created with `trust_log=True`. If none resolve,
  `score_async()` raises the `ValueError` the CLI raises today
  ("Unable to resolve any scorers for this log ...", `_cli/score.py:207-210`).
  The docstrings say that `None` runs code named by the log and is for
  trusted logs only, and that with the caller's own scorers the log's
  metric definitions are rebuilt as in `recompute_metrics()`.
- The CLI (`_cli/score.py:206`) passes `scorers=None` when `--scorer` is not
  given. With `--scorer` it builds that scorer before opening any output, as
  today, and passes it. It splits the spec with `parse_spec_str()` as
  `scorer_from_spec()` does:
  - A file spec (`path.py@name`, or an existing path) goes to
    `scorer_from_spec(spec, task_path=None, **scorer_args)`, unchanged: it
    loads the user's file, and `task_path` is used only by the bare-name
    branch.
  - A bare name goes to `scorer_from_log(name, task_import, **scorer_args)`
    with `task_import = LogTaskFileImport(log, trust_log=True)`. This is
    today's fallback to the recorded task file (`loader.py:833-862`), kept
    (decision: Ransom, 2026-10-14), now made through the tracker: the
    import uses `load_file_tasks()` on the absolute path, happens at most
    once, and prints the step 7 record line naming the scorer. It is a
    separate tracker from the one `score_async()` uses for the log's
    metrics in this mode, which is untrusted and never imports, so the task
    file is still imported at most once per `inspect score`. If the fallback
    import ran, the task file's metrics are registered, so the log's
    task-level metrics defined there resolve; their options are still
    restricted by step 3.
- `resolve_scorers()` (`score.py:598`, internal) loses its `scorer` and
  `scorer_args` parameters, now handled by the CLI, and takes the tracker:
  `resolve_scorers(log: EvalLog, *, task_import: LogTaskFileImport) -> list[Scorer]`.
  For names from `log.eval.scorers` or `log.results.scores` it calls a new
  function:

```python
# src/inspect_ai/_eval/loader.py
def scorer_from_log(
    name: str, task_import: LogTaskFileImport, /, **kwargs: Any
) -> Scorer:
    """Create a scorer from a bare name, named in a log or by a bare --scorer:
    registered, or defined in the log's task file.

    Never parses `name` as a file path or `path@name` spec. If `name` is not
    registered, calls task_import.import_for("scorer", name) and tries the
    registry again.

    Raises:
        PrerequisiteError: If the scorer cannot be resolved; the message
            suggests --scorer, as today.
    """
```

`scorer_from_log()` creates the scorer the way `scorer_from_spec()`'s
bare-name branch does today: the scorer registry, then the scanner registry,
and after the import the return-annotation check (`loader.py:806-826`).

The control parameters are positional-only so that recorded scorer options
named `name` or `task_import` reach the factory, as they do through
`scorer_from_spec(..., **kwargs)` today (the registry bridge preserves such
names, `src/inspect_ai/_util/registry.py:452`).

The tracker holds `task_path = Path(log.eval.task_file).absolute()` (today
`resolve_scorers()` passes the recorded, usually relative, path,
`score.py:613`). The absolute path is what `load_file_tasks()` needs, because
it changes into the file's directory before opening its argument
(`loader.py:548`): a relative `evals/task.py` would be looked up as
`evals/evals/task.py`. The same absolute path goes into the step 7 record.

**Order in `score_async()`.** It resolves its scorers and the log's metrics
before it builds a model or touches a sample. Today it builds the
log's model and roles first (`score.py:258-275`, with the log's base URL
and `model_args`), scores every sample in `tg_collect`, and only then calls
`metrics_from_log_header()` (`score.py:347-349`). The new order:

1. Scorers: `resolve_scorer(scorers)` for the caller's, or
   `resolve_scorers(log, task_import=...)` for `None`, raising the
   `ValueError` above if none resolve.
2. The log's metrics: with `action` defaulted to `"append"` first (moved up
   from `score.py:302`), when `metrics` is `None` and the action is not
   `"append"`, `metrics_from_log_header(log, task_import=...)`. The call
   moves up from after `tg_collect`; it reads only `eval.metrics`, which
   scoring does not change, so the result is the same.
3. The active model and roles (`score.py:258-275`), unchanged.
4. The deepcopy, scoring, `resolve_scorer_metrics()`, reducers and
   `eval_results()` with the metrics from 2, as today.

So a log whose scorers or metrics cannot be resolved, or whose metric
options are forbidden, fails before a provider is constructed with the
log's model, base URL and `model_args`, and before any scorer runs. Under `--stream` the CLI has already called
`log_init()` and `log_start()` on the output, as it does today before any
failure, but no sample is read, scored or written.

Because `score_async()` passes the same tracker to `resolve_scorers()` and to
`metrics_from_log_header()`, an overwrite with an unregistered log scorer and
a task-level metric that is still unregistered afterwards imports the task
file once, and prints one record line, naming the scorer that triggered it;
the metric then fails with the step 2 message. Without sharing, the second
resolver would import the file again (`load_module()` re-executes it through
`SourceFileLoader`, with no `sys.modules` caching) and print a second record.

Changes from today, for log-sourced names (the last bullet is the bare
`--scorer` fallback):

- A recorded name containing `@`, or one that happens to be an existing path,
  is looked up in the registry like any other name and is never imported.
  Inspect never writes such names (Current behaviour), so no log Inspect
  produced is affected.
- The fallback import goes through `load_file_tasks()` rather than a bare
  `load_module()`. That is the loader `eval` and `eval-retry` use for the
  same file: it applies the `@task` decorator filter and runs the import with
  the task's directory as working directory and on `sys.path`, so task files
  that import sibling modules now load in `inspect score` the way they do in
  `inspect eval`.
- The task file is imported at most once per `score()` call, across scorers
  and metrics (today `load_module()` runs once per unresolved scorer, and the
  metric resolvers import separately).
- A bare `--scorer NAME` that is not registered gets the same loader change
  (`load_file_tasks()` on the absolute path) and the step 7 record line.

This does not stop a log from naming an arbitrary task file: rescoring with
the log's scorers imports the task file by design. It makes the task file the
only file a log can make `inspect score` import, which is what step 7 reports.
An explicit bare `--scorer NAME` that is not registered keeps its fallback
to the recorded task file (`loader.py:833-862` today), through the tracker as
above. Decision: Ransom, 2026-10-14. The user named the scorer and expects to
find it there; the file is the same one that rescoring with the log's
scorers imports; and `inspect score --help` says to use the command only on
trusted logs (step 7).

### 7. Run operations record what they loaded, and the docs say they run the log's code

Decision: Ransom, 2026-10-06. The protection in this design is that read
operations no longer execute anything a log selects. For run operations the
protection is the user's choice of log, so the docs and `--help` say plainly
what those commands do:

- `inspect score --help` and `inspect eval-retry --help`
  (`src/inspect_ai/_cli/score.py`, `src/inspect_ai/_cli/eval.py`
  `eval_retry_command`) gain a sentence: "This runs code named by the log
  (its task file and scorers; for a retry also its solver, or for an `hf/`
  task the Hugging Face repo it names, whose `eval.yaml` chooses the dataset
  and the solver and scorer arguments) and uses the model endpoint, sandbox
  and other settings recorded in it. Only run it on logs you trust."
  `inspect score --help` adds: "With --scorer, the log's metrics are rebuilt
  without importing its task file; the log's model and model roles are still
  used."
- The same statement goes in `docs/scoring-workflow.qmd` (rescoring, both
  the CLI section and the `score()` section, which also documents
  `score(log, None)`), the `score()` / `score_async()` docstrings, and the
  eval-retry section of the docs, next to the "Logs from others" note in
  `docs/eval-logs.qmd` (step 2), which says that reading, viewing,
  recomputing and recovering a log do not run its code unless `trust_log` is
  passed.

The CLI also prints a record of what it loaded, with `display().print()`. It
is a record for the user to check afterwards, not a mitigation; nothing
waits on it:

- `inspect score` (`src/inspect_ai/_cli/score.py`), when a
  `LogTaskFileImport` imports the task file (without `--scorer`, the one
  `score_async()` shares across scorers and metrics; with a bare
  unregistered `--scorer NAME`, the CLI's fallback tracker of step 6): one
  line, naming the scorer or metric whose lookup triggered it, e.g.
  `Imported task file /abs/path/evals/task.py (recorded in the log) to load scorer 'my_scorer'.`
  or, for an overwrite with registered log scorers and an unregistered
  task-level metric,
  `Imported task file /abs/path/evals/task.py (recorded in the log) to load metric 'my_metric'.`
  When the log's model is used (no `--model`) and the log records a
  `model_base_url`: `Scoring model openai/gpt-4o from the log, base URL https://...`.
- `inspect eval-retry` (`eval_retry_async()`, one block per log, before
  recovery): the task file (absolute path) and task name, or for a log with
  no task file and an `hf/` task name, the Hugging Face repo and revision
  whose `eval.yaml` will define the task; the solver file if `eval.solver`
  is a file spec; the model and its base URL if recorded; the sandbox type
  and its config file (or "inline config"); and the ACP server binding if
  `eval.config.acp_server` is set.

Paths are printed resolved, so a relative `task_file` that resolved to an
unexpected file in the working directory shows up. `score()`/`eval_retry()`
called from Python log the same lines at `INFO`.

### Path resolution

Unchanged: relative paths keep resolving against the working directory. The
recorded `task_file` and `--solver` paths are working-directory relative by
construction, and a retry or rescore is run from the original project
directory. Resolving against the log's location would break every log kept
in a `logs/` subdirectory; requiring a match against a user-supplied path
adds a flag to every retry for no gain once the read operations import
nothing. The record in step 7 shows the resolved path. Confining paths was
considered and rejected (see Alternatives considered).

### Registry names

Unchanged in both classes. A `pkg/name` reference loads an installed
package's entry point, the module that package publishes for Inspect to
import, and calls its registered factories with arguments from the log.
`inspect eval` does the same, and the attacker cannot add packages.
`ensure_entry_points()` stays in `registry_lookup()` as is: it imports
installed extension packages, not code from the log. Step 3 limits what
metric options in read operations can make those factories build.

## Alternatives considered

- **Keep importing the task file in read operations and warn, or deprecate
  first.** A warning after the import does not stop the import, and a
  deprecation period that keeps the old behaviour for a release leaves the
  problem in place for that release. Decision: Ransom, 2026-10-06 ("break
  now"): the safe defaults ship in the release that carries the change, with
  the actionable error and no deprecation period. This accepts the eval-set
  edge in step 2 (restricted metric options give no recovery results, and
  the affected in-progress samples re-run).
- **A separate check that walks metric options before `metric_create()`**
  (the first draft's `check_log_metric_options()`). It would have to
  recognise exactly the shapes `registry_arg()` constructs; if the two ever
  disagreed (a new shape added to `registry_arg()`, a nuance of
  `is_registry_dict()`), the check would pass and the construction would
  still happen. Enforcing the allow-list inside construction (step 3) cannot
  drift that way (decision: Ransom, 2026-10-06).
- **A user-supplied task path for recompute and recover**
  (`recompute_metrics(log, task_file="evals/task.py")`) instead of a boolean.
  Safer in principle, since the user names the file, but the file is almost
  always the one the log records, and scripts that recompute many logs from
  several tasks would need a mapping. A boolean is simpler; a user who wants
  a different file can import it themselves.
- **Two keywords** (`import_task_file` for the task-file import and a second
  one for model-valued metric options) instead of `trust_log`. Both decide
  whether the log may choose code, and a caller who trusts the log for one
  has no reason to refuse the other; two flags double the surface on four
  APIs and the CLI for no gain.
- **Removing model-valued metric options from log reconstruction entirely**,
  for trusted callers too. Simpler, but a registered custom metric that takes
  a model reconstructs and computes today, and retry recovery and
  `inspect score --action overwrite` would lose its results; a retry's
  resolving recovery would then stop finalizing. `trust_log=True` keeps them.
- **One global trust switch** (an environment variable or
  `INSPECT_TRUST_LOGS`). One setting would cover every operation, but it would
  stay set in shells and CI after the user forgot why, and would silently
  re-enable imports in the viewer once it gains score editing. Per-call opt-in
  keeps the decision next to the log being trusted.
- **Requiring confirmation before a run operation imports**, or a prominent
  stderr panel listing what the log selects. A confirmation breaks scripted
  `inspect score` and `eval-retry`, and running the log's code is the
  purpose of those commands; a panel is still easy to miss and suggests that
  reading it is the protection. Rejected (decision: Ransom, 2026-10-06): the
  protection is that read operations run nothing from a log, and the docs
  and `--help` say plainly that run operations do (step 7).
- **Confining loaded files to the working directory or a project root**: the
  task file, solver file and file-based scorer or metric paths, either as a
  hard boundary or as an anomaly gate that errors unless a flag is passed.
  Rejected (decision: Ransom, 2026-10-06):
  - By default read operations import nothing, so confinement would only
    apply to `trust_log=True` and the run operations.
  - Importing any project file runs its top-level code, so confinement
    narrows which files load without making loading safe.
  - Logs unpacked or cloned into the project bring their files inside the
    boundary.
  - Logs record task files as absolute paths when they are outside the
    working directory (`cwd_relative_path()`), so retry or rescore from
    another directory would break.
  - A gate on paths and base URL still leaves the log choosing model args,
    model roles, sandbox config and ACP binding, which would make running an
    untrusted log look safer than it is.
- **Confining `eval-retry`'s solver file to the task file's directory.**
  Legitimate logs record `--solver` paths anywhere the user typed; a log
  that can name an arbitrary task file gains nothing from also naming a
  solver file, so confining it adds breakage without removing a capability.
- **Hashing the sandbox into the eval-set task identifier**, instead of or in
  addition to step 4. Rejected (decision: Ransom, 2026-10-06):
  - Step 4 already stops the log choosing the sandbox on the eval-set path.
  - Hashing it would stop logs pairing when a user resumes on different
    infrastructure (Docker to Kubernetes, or adding `--sandbox`), and would
    need a `TASK_IDENTIFIER_VERSION` bump that changes every existing
    identifier.
  - Spec equality between a resolved task and a log is fragile, and a config
    path says nothing about the file's contents.
  - On its own it would still let the log's sandbox win whenever the
    identifiers match.
- **Treating every `score()` call as a run operation**, so that rescoring
  with the user's scorers also trusts the log's metric definitions. Simpler
  (one rule for the command), but it would widen what a log can make Inspect
  load when the user supplies the scorer: an unregistered task-level metric
  would import the log's task file, where today that path imports it only
  through a bare unregistered `--scorer` name.
  Rejected (decision: Ransom, 2026-10-14): trust follows the scorers' source
  (step 2).
- **Lazy model construction in `inspect score`.** Building the log's model
  only when a scorer asks for one would avoid constructing it for rule-based
  scorers. It changes how `score_async()` binds the task context, and the
  model is part of the run being scored; left under "Not this design".
- **Resolving `--scorer` only through the registry or an explicit path**, so
  that rescoring with the user's scorer never imports a file the log names; a
  user whose scorer is in the task file would pass
  `--scorer evals/task.py@my_scorer`. Rejected (decision: Ransom,
  2026-10-14): the user named the scorer, the file is the one rescoring with
  the log's scorers imports, and `inspect score` is documented for trusted
  logs only (step 6).

## Compatibility and migration

No stored format, schema or generated TypeScript type changes. Existing logs
read, view, convert and resume as before.

These ship without a deprecation period (decision: Ransom, 2026-10-06,
"break now"). Public API (additive, keyword-only, default preserves safety
rather than old behaviour):

- `recompute_metrics(..., trust_log=False)`,
  `edit_score(..., trust_log=False)`,
  `recover_eval_log(..., trust_log=False)`,
  `recover_eval_log_async(..., trust_log=False)`.
- `score()` / `score_async()`: `scorers` also accepts `None` (the log's
  scorers). Existing calls pass scorers and keep working, with the metric
  change below.
- CLI: `inspect log recover --trust-log`.

Behaviour changes, by user:

- **`recompute_metrics()` / `edit_score()` users relying on #3981** (custom
  metrics defined in a task file, recomputed in a fresh process): the call
  raises `LookupError` with the message in step 2 instead of importing. Fix:
  import the module that defines the metric before the call, or pass
  `trust_log=True`. Users who recompute in the process that ran the
  eval, or whose metrics live in installed packages, see no change.
  `edit_score()` raises before it edits, so the log is unchanged and the
  call can be repeated with `trust_log=True`.
- **`inspect log recover` users with task-file metrics**: the recovered log
  has no results and the warning names `--trust-log`. With a resolving
  `--incomplete-action`, such a log also does not finalize, so its
  in-progress samples are left for a retry. The sample buffer is kept, and
  with `--overwrite` so is the crashed log (the output goes to
  `<name>-recovered.eval`), so rerunning the same command on the same
  crashed log with `--trust-log` computes the metrics, finalizes a resolving
  recovery and then removes the buffer.
- **Recovery callers whose metric computation fails for any reason** (with
  `cleanup=True`, the default): the buffer is now kept instead of removed,
  and an `overwrite=True` recovery leaves the crashed log in place and
  returns the log written at `<name>-recovered.eval`. A recovery whose
  metrics compute behaves as today. A kept buffer is removed by a later
  recovery that computes metrics, or by the existing startup sweep of stale
  buffers (`_recover/_api.py:138-139`).
- **`eval-retry`**: no change apart from the printed record and help text; its recovery passes
  `trust_log=True`, so it imports the task file and rebuilds metric options
  as today, and recovered results and finalization are unchanged.
- **`inspect score` without `--scorer`** (the log's scorers): rebuilding
  `eval.metrics` for `--action overwrite` is trusted, so it behaves as
  today, except that a task-level metric defined in the task file now
  resolves by importing that file instead of failing. The CLI now passes
  `scorers=None` to `score_async()`, which resolves the log's scorers itself.
  The task-file import for a task-level metric is new only when every log
  scorer is registered; when one is not, today's scorer fallback already
  imports the file and registers the metric.
- **`inspect score --scorer ... --action overwrite` and `score(log, scorers,
  action="overwrite")`**: the log's `eval.metrics` are rebuilt untrusted. A
  task-level metric that is not registered fails with the step 2
  `LookupError` instead of the registry's generic one (metric resolution
  imports nothing, before or after; a bare unregistered `--scorer` may
  already have imported the task file and registered it, as today);
  a metric whose options hold a model or a non-metric registry object now
  raises `DisallowedRegistryArg` instead of being rebuilt. Fix: pass
  `metrics=` (`--metric`), or rescore with the log's scorers. Append, and
  logs whose metrics are registered and take no such options, are
  unchanged.
- **`eval_set()` resume**: recovered metrics unchanged for metrics defined in
  or imported by the task file, which eval-set has already loaded. A metric
  whose recorded options hold a model or non-metric registry object is no
  longer rebuilt during eval-set recovery (step 2): that log is recovered
  without results, and with a resolving `incomplete_action` its in-progress
  samples are re-run instead of resolved. Resumed tasks now use the sandbox
  their task definition and `--sandbox` resolve to, rather than the one
  recorded in the previous log. These differ only if the user changed the
  task's sandbox or the `--sandbox` override between runs; the new samples
  then run in the sandbox the user asked for. Previous samples are reused as
  before, so the resumed log can hold samples completed in the old sandbox
  and samples run in the new one, and its header records the new sandbox.
  Task identifiers are unchanged.
- **`inspect score`**: logs written by Inspect are unaffected. A scorer that
  was found only by `load_module()` on a task file without a `@task` function
  is no longer found, whether named by the log or by a bare `--scorer`; the
  error suggests `--scorer path.py@name`. Task files that import sibling
  modules now load, on both paths. A log whose metrics cannot be resolved
  for `--action overwrite` now fails before the log's model is built and
  before any sample is scored, rather than after scoring every sample (and,
  under `--stream`, writing them).
- **Score keys that name files** get default metrics instead of an import.
  Inspect never writes such keys.
- **Custom metrics taking models or non-metric registry objects as options**:
  rebuilt only with `trust_log=True` (or by run operations, including
  rescoring with the log's scorers); otherwise they raise a `ValueError`
  naming the option.
- **Scorers that need arguments, recorded only as score keys** (for example
  a solver-written `pattern` score): unchanged, they keep the default metrics
  (step 1).
- **`inspect_ai.analysis.model_info()`**: model names that only resolve by
  instantiating their provider (not in the database or its aliases) get no
  metadata; supply it with the `model_info` argument or `set_model_info()`.
- **Viewer and VS Code**: no change today (they do not edit scores). The
  planned score-edit endpoint (`design/viewer_log_editing.md`, Phase 3)
  must call `edit_score()` without `trust_log`, since the viewer
  serves logs it did not write. A task-file metric or a forbidden metric
  option then raises from `edit_score()` before the edit is applied; the
  endpoint returns it as HTTP 400, alongside that design's other
  `ValueError` cases, and does not write the log, so the file on disk is
  unchanged.

## Security

Untrusted input: every field of an eval log header and sample (`.eval` or
`.json`), the sample buffer next to a log, and every file in a log directory
an eval set resumes from. After this design:

- Read operations import no file named by a log: score keys resolve through
  the registry only (step 1), the task file needs `trust_log=True`
  (step 2), and eval-set's recovery, whose only import was the user's own
  task file, makes none.
- Read operations construct no model provider from log values (steps 3 and 5)
  and no registry object outside the metric and reducer registries (step 3),
  unless the caller passes `trust_log=True`. The allow-list is enforced in
  `registry_arg()`, the code that does the constructing, so there is no
  separate recogniser that could disagree with it.
- eval-set resume no longer lets a log choose the sandbox type or config of a
  task the user chose (step 4), including inline compose configs, which would
  otherwise run the log's images with the log's mounts.
- `inspect score` imports at most the recorded task file (step 6), once.
  With the log's scorers that import may serve scorers and metrics, and log
  metric options are rebuilt without restriction, as today. With the user's
  scorers (`--scorer`, or `score(log, scorers)`) the log's metrics never
  trigger it and their options are restricted by step 3; only an explicit
  bare `--scorer` name that is not registered still falls back to the
  recorded task file (decision: Ransom, 2026-10-14; step 6), now through a
  tracker, so that import is also made once, with the eval loader, and
  recorded. In both modes `score_async()` resolves scorers and metrics
  before it builds the log's model and roles, so a log that fails to
  resolve constructs no provider; a log that resolves still has its model
  and model roles built (under "Not this design").
- What remains in read operations is installed code chosen by name: entry
  points of installed packages, their registered metric and reducer
  factories called with log arguments, registered scorer factories called
  with no arguments by `ScorerInfo.from_name()`, and sandbox plugins'
  `config_deserialize()` on log data during parsing. These run code the
  victim installed, the same code `inspect eval` loads.
  `ensure_entry_points()` stays in `registry_lookup()` unchanged: it imports
  installed extension packages by name, never code from the log. Step 3 limits what
  Inspect's own argument reconstruction builds; it does not audit what an
  installed factory does with ordinary string options (a plugin that treats
  an option as a path or model name is trusted installed code).
- What remains in run operations is the purpose of the operation: the task
  file, the solver file (retry), the Hugging Face repo and its `eval.yaml`
  (retry of an `hf/` task), the model and its base URL, the sandbox,
  approval and review policies, and the ACP binding. The docs and `--help`
  say these commands should only be run on trusted logs; step 7's printed
  record shows what was used but is not a safeguard. The credential and
  network items are under "Not this design".

The `@task` decorator filter in `load_file_tasks()` is not a security
boundary (any file can contain a decorated function); it only avoids
importing files that are not task files.

## Testing

All of these run in the default test job: no network, Docker or model
provider. The malicious-log fixtures use a marker module that records its
import (it appends to a file under `tmp_path`), and a spy on `get_model`
that fails the test if it is called with the fixtures' distinctive model
name or base URL (eval-set legitimately calls `get_model()` for its own
`mockllm` model). The spy is installed with `monkeypatch` on
`inspect_ai.model._model.get_model`, which covers metric options
(`registry.py:754` imports it inside the function), and on the two
module-level bindings on these paths, `inspect_ai._eval.score.get_model`
(`score.py:54`, the log's model in `score_async()`) and
`inspect_ai.model._model_config.get_model` (model roles); patching only the
first would miss `score_async()`.

New file `tests/log/test_untrusted_logs.py` (no existing file covers
operations across modules; it follows
`test_cli_never_resolves_scorers_or_imports_task_code` in
`tests/_control/test_log_dir.py`). Each protection gets its own fixture whose
other definitions resolve, so one check cannot stop the operation before
another protection is reached. Recompute and recovery resolve metric
definitions before `eval_results()` (`log/_metric.py:39-41`,
`_write.py:272-275`), so a combined fixture would never reach the score-key
path. Fixtures:

1. **Hostile score key**: registered header metrics only (`accuracy`), and a
   sample score key naming a marker module as `<path>@<name>`, plus one that
   is a bare existing path.
2. **Missing task-file metric**: `task_file` pointing at a marker module with
   a `@task` function, a scorer whose metric is defined only there, and a
   task-level metric in `eval.metrics` defined only there; plus one variant
   with only the scorer metric and one with only the task-level metric.
3. **Forbidden metric options on registered metrics**: a model dict, and a
   registry dict of a non-metric type (e.g. `solver`), each placed in
   `eval.metrics` (list form and dict-group form) and in
   `eval.scorers[*].metrics` (nested list and dict-group form), and inside the
   `params` of a permitted nested metric registry dict.
4. **Hostile sandbox**: a header sandbox of `local` and one with an inline
   compose config (for the eval-set test below).

Assertions, for every read operation applicable to each fixture: no marker was
written, and the `get_model` spy was not called.

- `recompute_metrics()` and `edit_score()`: fixture 1 succeeds with default
  metrics for the hostile keys; each fixture 2 variant raises `LookupError`
  with the shared step 2 message naming the right metric (scorer metric or
  task-level metric); fixture 3 raises `DisallowedRegistryArg` (a
  `ValueError`) naming the metric and the option key path. Both errors end
  with the `trust_log` advice. For
  `edit_score()` on fixtures 2 and 3, also assert the log is unchanged after
  the failure (`model_dump()` equal before and after: no edited value, no
  `score.history` entry, no `ScoreEditEvent`, same `results`).
- `score(log, [match()], action="overwrite", model="mockllm/model")` on
  fixture 2's task-level variant and fixture 3's `eval.metrics` placements:
  the step 2 `LookupError` and `DisallowedRegistryArg` respectively, each
  ending with the `SCORE_OPT_IN` advice and not mentioning `trust_log`, no
  marker, no spy hit (`model=` is passed so the spy sees only the fixtures'
  metric options, not `score_async()` building the log's model, which is a
  "Not this design" item). The scorer is a test scorer that counts its
  calls: it is never called, so both errors come before any sample is
  scored.
- `recover_eval_log()` and `recover_eval_log_async()` on a `started` copy of
  each fixture, once with a database sample buffer and once with a filestore
  buffer (the two sources in `_recover/_api.py:110`, built the way
  `tests/log/test_recover_write.py` and `test_recover_filestore.py` build
  them): fixture 1 recovers with results; fixtures 2 and 3 recover without
  results and log the warning. With a resolving `incomplete_action`, assert
  fixtures 2 and 3 do not finalize. The same through `inspect log recover`
  via `CliRunner`.
- `eval_set()` resume over a log directory holding a `started` log with a
  sample buffer, built by running the test's own task once with `eval_set()`
  and then rewriting the log so its task identifier still matches: once with
  fixture 1's score keys in the buffered samples and once with fixture 3's
  metric definitions in the header (the identifier hashes neither). Each runs
  on both recovery paths: the default `incomplete_action="retry"`, which
  recovers in `as_previous_tasks()` (`evalset.py:1504`), and a resolving
  `incomplete_action` (`"error"`), which recovers in `list_latest_eval_logs()`
  (`evalset.py:1803`). Assert no marker, no spy hit, and that the eval set
  completes. Fixture 3 is the one that catches a later change making
  `_recover_crashed_log()` pass `trust_log=True`: the model dict would then
  reach `get_model()`.
- `evals_df()` plus `prepare(model_info())` over a directory of logs with an
  unknown model name.
- `read_eval_log()`, `read_eval_log_headers()`, `inspect log dump`,
  `inspect info`, and the view server's `/logs/{log}` and `/log-headers`
  endpoints (with the FastAPI test client used by the existing view tests).

The fixture 1 and fixture 3 tests fail on `main` today (a marker is written,
`get_model` is called), so they are regression tests for steps 1 and 3.

Legitimate flows:

- `tests/scorer/test_score_editing.py`:
  `test_resolve_scorers_info_loads_task_file_metrics_once` passes a trusted
  `LogTaskFileImport` and keeps asserting one import; an `edit_score()` of a
  fixture 2 log fails with the log unchanged, then the same call with
  `trust_log=True` succeeds and applies the edit once, exactly as an edit
  that never failed: `score.history` holds the original-state snapshot
  (`log/_score.py:99-107`, added on a score's first edit) followed by one
  entry for this edit, the sample has one `ScoreEditEvent`, and the metric
  is computed; `edit_score(...,
  recompute_metrics=False)` on the same log edits without resolving; add
  `recompute_metrics(log, trust_log=True)` tests with fixture 2 that compute
  both the scorer metric and the task-level metric with a single import, one
  with each single-metric variant, and one where the task file lacks the
  metric (shared message); a test that a module imported by the caller first makes the default
  path work, a `grouped(accuracy(), ...)` recompute that passes step 3, and a
  registered custom metric taking a model (`mockllm/model`) that recomputes
  with `trust_log=True`.
- `tests/log/test_recover_api.py`: recovery with `trust_log=True` (and
  `--trust-log`) computes the task-file scorer metric, the task-level metric
  and the model-option metric,
  and a resolving recovery of such a log finalizes. On fixture 2 (scorer
  metric and task-level metric both defined only in the marker module) the
  marker records exactly one import and the record line is logged once
  (printed once by `inspect log recover --trust-log`), which fails if
  `write_recovered_eval_log()` gives the two resolvers separate trackers.
- `tests/log/test_recover_api.py` and `test_recover_filestore.py`, the
  default-then-trusted sequence, once with a database buffer and once with
  a filestore buffer, each under `incomplete_action="retry"` and `"error"`
  (built with the existing helpers `_create_buffer_db()`,
  `_write_crashed_eval()` and `_create_filestore_fixture()`). The first
  `recover_eval_log(log)` call uses the defaults (`cleanup=True`) on fixture
  2 and returns a log without results, with `RecoveryStats.metrics_error`
  set and the warning naming the kept buffer; the buffer still exists. A
  second `recover_eval_log(log, trust_log=True)` on the same crashed log
  computes both metrics and removes the buffer, and under `"error"` the log
  finalizes with status `success`.
  - The same with `overwrite=True`: after the first call the crashed log is
    unchanged (still accepted by `read_crashed_eval_log()`) and the returned
    log is at `<name>-recovered.eval`; the second call replaces the crashed
    log.
  - The same sequence through `inspect log recover` and then
    `inspect log recover --trust-log` with `CliRunner`.
  - A metric that is registered but raises when computed also keeps the
    buffer under `cleanup=True`, and a recovery whose metrics compute still
    removes it.
  These fail on the current code, where the first call removes the buffer
  and the second raises `RecoveryNotAvailable`.
- `tests/test_eval_set.py`: an eval set with a task-file custom metric,
  interrupted so a `started` log with a buffer remains, resumes with the
  metric computed (proves eval-set needs no opt-in). A unit test on
  `resolve_previous_tasks()`: a `Task` declaring `sandbox="docker"` paired
  with fixture 4's logs resolves to `docker`, an explicit eval-level
  `sandbox="local"` is honoured, and a `str` task keeps the log's sandbox
  (resolution only, no Docker daemon).
- `tests/test_retry.py`: retry of a crashed log with a task-file metric
  recovers its metrics through both recovery calls (the threshold fallback
  included). The task file is a marker module defining both a scorer metric
  and a task-level metric, and the retry also loads it to run the task, so
  the assertion is relative: the marker count after retrying the `started`
  log is exactly one more than after retrying the same log with status
  `error` (which skips recovery), on both paths. The threshold check raises
  before metric resolution (`_recover/_api.py:254`, before the write at
  `:304`), so the fallback path also resolves metrics once; retry with a `--solver path.py@name` log still loads the solver;
  the printed record lists the task file, solver file and base URL, and for
  an `hf/` log with no task file lists the repo and revision (tested on the
  function that builds the record, so no Hugging Face download is needed);
  `inspect eval-retry --help` carries the trusted-logs sentence.
- `tests/_eval/test_score.py`: a log scorer name of the form `<path>@<name>`
  is not imported and fails with the `--scorer` suggestion; an unregistered
  log scorer defined in the recorded task file loads when the task file is
  recorded cwd-relative in a subdirectory (`evals/task.py`) and imports a
  sibling module; a recorded scorer with an option named `name` (as in
  `test_scorer_from_spec_preserves_scorer_name_argument`) still reaches the
  factory, through both `eval.scorers` and the `results.scores` fallback;
  `--scorer path.py@name` still loads that file; a bare unregistered
  `--scorer` name still falls back to the recorded task file, now a marker
  module recorded cwd-relative in a subdirectory that imports a sibling
  module: it loads, the marker records one import, and the record line
  naming the scorer is printed once; with `--action overwrite` and a
  task-level metric defined in the same file, the metric resolves with no
  second import; a bare name the task file does not define raises the
  `PrerequisiteError` suggesting `--scorer path.py@name`;
  `inspect score --help` carries the trusted-logs sentence; the import record
  is printed once with the absolute path. Trust by scorer source:
  - Log's scorers (no `--scorer`, and `score(log, None)`): `--action
    overwrite` on a log whose `eval.metrics` holds a model-option metric
    still computes it; an overwrite whose log records a registered scorer and
    a task-level metric defined only in the task file imports the file and
    prints the metric record line; an overwrite whose log records an
    unregistered scorer and a task-level metric, both defined in the task
    file (a marker module), imports it once, prints one record line naming
    the scorer, and computes both; the same with a task-level metric the task
    file does not define imports once and raises the step 2 message before
    any sample is scored (the marker module's scorer counts its calls);
    `score(log, None)` on a log with no recorded scorers raises the
    `ValueError`, and on a log whose recorded scorer is neither registered
    nor in its task file raises the `PrerequisiteError`; in both cases the
    `get_model` spy is not called with the log's model or base URL (no
    `model=` is passed), which fails if scorer resolution comes after the
    model is built.
  - User's scorers (`--scorer <registered>`, and `score(log, [match()])`):
    `--action overwrite` on a log whose `eval.metrics` holds a task-level
    metric defined only in the task file raises the step 2 `LookupError` with
    the `SCORE_OPT_IN` advice and does not import the marker module; the
    same with a model-option metric, and with a non-metric registry option,
    raises `DisallowedRegistryArg` with the option path and the same
    `SCORE_OPT_IN` advice (no `trust_log`), and the `get_model` spy is not
    called with its model; with `--stream` and a registered test scorer that
    counts its calls as `--scorer`, the scorer is never called and the
    output holds no sample; passing `metrics=`
    (`--metric accuracy`) instead succeeds; and a regression test for
    `--scorer <registered> --action overwrite` on a log with no
    `eval.metrics` whose old `eval.scorers` names an unavailable custom
    metric, asserting the rescore succeeds and the old task file is not
    imported.
- `tests/scorer/test_scorer.py` (or the file holding `eval_results` tests):
  `ScorerInfo.from_name()` returns the defaults for an unregistered name, the
  scorer's own metrics for a registered no-argument scorer (`match`,
  `includes`), and the defaults, without raising, for each core scorer that
  needs arguments (`pattern`, `answer`, `multi_scorer`, `precomputed_scores`,
  `_model_graded_qa_single`); and `eval_results()` with a solver-written
  `pattern` score key still computes.
- `tests/util/test_registry.py` (next to `test_registry_kwargs`):
  `create_registry_object()` with `allowed_types` refuses a model dict and a
  non-allowed registry dict at the top level, inside lists and dicts, and
  inside the `params` of an allowed nested registry dict, and the outer
  factory (a test metric that records its calls) is never called; an allowed
  nested metric is constructed; the error names the type, name and option
  key path; `allowed_types=None` and `registry_kwargs(**params)` behave as
  today, including for an option literally named `allowed_types`.
- `tests/analysis/test_prepare.py`: `model_info()` still fills metadata for a
  database model, a `set_model_info()` model and a `model_info=` mapping.

Async tests (recovery, retry) run under both backends with `--runtrio` before
the PRs open, as the repo requires.

## Implementation plan

1. **Read paths import nothing by default** (steps 1, 2, 3). Files:
   `src/inspect_ai/_util/registry.py` (`allowed_types` on
   `create_registry_object()`, `_instantiate_registry_object()`,
   `registry_arg()`; `_resolve_registry_args()` behind `registry_kwargs()`;
   `DisallowedRegistryArg`), `tests/util/test_registry.py`,
   `src/inspect_ai/_eval/loader.py` (`scorer_from_registry()`,
   `LogTaskFileImport`),
   `src/inspect_ai/_eval/task/results.py` (`from_name()`),
   `src/inspect_ai/_eval/score.py` (`resolve_scorers_info()`,
   `metrics_from_log_header()`, `metric_from_log()`,
   `ensure_metrics_registered()`; `score()` / `score_async()` accept
   `scorers=None` and trust the log only then, and resolve scorers and the
   log's metrics before building the model or scoring, step 6's order, so
   the new metric errors come before any scorer runs; `resolve_scorers()` takes the
   tracker and drops its `scorer` parameters, still calling
   `scorer_from_spec()` for log names until step 3),
   `src/inspect_ai/_cli/score.py` (passes `scorers=None` without
   `--scorer`), `src/inspect_ai/log/_metric.py` (`resolve_log_metrics()`,
   `compute_log_metrics()`), `src/inspect_ai/log/_score.py` (resolve before
   editing),
   `src/inspect_ai/log/_recover/_api.py`, `src/inspect_ai/log/_recover/_write.py`
   (`trust_log`; `RecoveryStats.metrics_error`, and keeping the buffer and
   the crashed log when metrics fail),
   `src/inspect_ai/_cli/log.py`, `src/inspect_ai/_eval/eval.py` (both retry
   recovery calls pass `trust_log=True`), `docs/eval-logs.qmd` (the
   recompute example and a short "Logs from others" note),
   `docs/scoring-workflow.qmd` (`score(log, None)` and how the log's metrics
   are treated with the user's scorers), and the tests above for these
   paths, including `tests/log/test_untrusted_logs.py`. The rescoring trust
   split belongs in this step, not step 3: otherwise `inspect score` without
   `--scorer` would rebuild metrics untrusted between the two PRs.
2. **eval-set resume sandbox** (step 4). `src/inspect_ai/_eval/loader.py`,
   `tests/test_eval_set.py`.
3. **`inspect score` narrowing, run-operation help text and records**
   (steps 6, 7). `src/inspect_ai/_eval/loader.py` (`scorer_from_log()`),
   `src/inspect_ai/_eval/score.py` (`resolve_scorers()` resolves log names
   with `scorer_from_log()` and the shared tracker),
   `src/inspect_ai/_cli/score.py` (a bare `--scorer` name through
   `scorer_from_log()` with its own trusted tracker; the record lines),
   `src/inspect_ai/_cli/eval.py`
   (`eval_retry_command` help), `src/inspect_ai/_eval/eval.py`,
   `docs/scoring-workflow.qmd` and the eval-retry docs,
   `tests/_eval/test_score.py`,
   `tests/test_retry.py`.
4. **`model_info()` direct lookup** (step 5).
   `src/inspect_ai/analysis/_prepare/model_info.py`,
   `tests/analysis/test_prepare.py`, the analysis tests in
   `tests/log/test_untrusted_logs.py`.

Steps 1 and 2 close the read-operation paths and should land first; 3 and 4
are independent of each other. No step edits `CHANGELOG.md`: Release Please
writes it from the PR titles, and steps 1 and 3 are breaking (`fix!:` with a
`BREAKING CHANGE:` paragraph naming the `trust_log` opt-in and the rescoring
change).

## Open questions

None open. Ransom settled the three earlier questions on 2026-10-06: break
now (Alternatives considered), `model_info()` direct lookup only (step 5),
and a printed record plus a plain statement in the docs and `--help` rather
than a confirmation (step 7). He settled rescoring trust on 2026-10-14: the
log is trusted only when its own scorers are used. Also on 2026-10-14 he
kept the bare unregistered `--scorer NAME` fallback to the recorded task
file (step 6).

## Not this design

Noticed while tracing, left for separate issues:

- **Credentials to a log-chosen endpoint.** `eval-retry` builds the model with
  `eval.model_base_url` and `eval.model_args`, and `inspect score` does the
  same unless `--model` is given, so the user's provider key is sent to the
  base URL the log names. `inspect score` also always builds the log's model
  roles, with their base URLs and args, even when `--model` is passed or no
  scorer uses a model, and model args can enable provider behaviour such as
  Hugging Face `trust_remote_code` or a vLLM server launch.
- **ACP server replay.** `eval-retry` reuses `eval.config.acp_server`
  (`eval.py:1894`), which may bind a TCP port on any interface (`0.0.0.0:<port>`).
- **Retry sandbox from the log.** A retry keeps the log's sandbox type and
  config, including inline compose configs. Intended under the trust model,
  but a retry of an untrusted log then runs the log's containers with the
  log's mounts; step 7 only shows it.
- **Parse-time plugin code.** Reading any log calls the sandbox plugin named
  by a sandbox type with a non-empty config dict and may load every installed
  entry point (`environment.py:637-709`).
- **Dataframe column bug.** `EvalColumn("model_args", path="eval.model_base_url")`
  (`src/inspect_ai/analysis/_dataframe/evals/columns.py:98`) maps
  `model_args` to the base URL.
