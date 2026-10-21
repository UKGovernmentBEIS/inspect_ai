# Code execution from a malicious eval log

Status: proposed, 2026-10-06. Issue: none (task from Ransom Richardson). Author: agent (Claude), reviewed by Codex; see the PR.

## Overview

Reading an eval log someone else wrote should not run their code. Today
several "read" operations can: recomputing metrics after a score edit,
recovering a crashed log, and resuming an eval set can import a Python file
the log names, build a model provider from values in the log, or (on
eval-set resume) let the log pick the sandbox. This design splits Inspect's
operations into two kinds. Run operations (`eval-retry`, and `inspect score`
with the log's own scorers) exist to run the log's task, so they
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
| `eval_retry()`, `inspect eval-retry` | A, B, C via recovery; then the task file, solver file, model, sandbox, approval, review, sentinel and ACP settings from the log | run operation (`src/inspect_ai/_eval/eval.py:1684-1960`) |
| `inspect score`, `score()`, `resolve_scorers()` | scorer names and options from the log (without `--scorer`), with the scorer fallback that imports the recorded task file whenever building a recorded scorer or bare `--scorer` name from the registry raises `ValueError` (not registered, or a registered factory rejecting its options), in either action (`loader.py:833-856`); C for `--action overwrite`; model and model roles from the log | run operation with the log's scorers (`src/inspect_ai/_cli/score.py:206`, `score.py:263-275`, `:347-349`) |

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
`scorer_from_spec()`. The names cannot be file specs: `HFSolver.name` and
`HFScorer.name` are `Literal` allowlists of built-in solvers and scorers
(`hf.py:25`, `:39`), validated by `HFTask.model_validate()` (`hf.py:132`)
before either loader sees them. Both loaders still pass the name through
`parse_spec_str()` before the registry (`loader.py:649`, `:789`), which
treats any existing path as a file (`loader.py:969-971`), resolving
symlinks. So a path in the working directory named exactly like an
allowlisted solver or scorer (`generate`, `match`, ...) shadows the
built-in. The names have no extension, so an ordinary file or directory
with that name only makes the load fail: `load_module()` raises
`ModuleNotFoundError` for any suffix other than `.py` or `.ipynb` before
opening it (`_util/module.py:23-54`). A symlink with that name that
resolves to a `.py` or `.ipynb` file is imported instead of the built-in.
The repo chooses only the name; the path has to be in the user's working
directory already. This is the same rule that applies to a name the user
types, and this design leaves it unchanged. The arguments are not restricted, so a model
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
the log's own scorers (`inspect score` without `--scorer`). Running one on a
log means
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
| `inspect score` without `--scorer` | the recorded task file, only when a recorded scorer cannot be built from the registry (today's fallback, recorded by step 7) |
| `inspect score --scorer NAME`, `score(log, scorers)` | none for metrics. The recorded task file only when `--scorer` is a bare name the registry cannot build: today's fallback, kept and recorded (decision: Ransom, 2026-10-14; step 6) |
| `eval-retry` | the recorded task file and the recorded solver file. A log with no `task_file` and an `hf/` task name instead makes the retry fetch that Hugging Face repo's `eval.yaml`, which names no file (only allowlisted built-in solvers and scorers, though an existing working-directory path with the same name shadows one, as for any spec) but chooses the dataset and the arguments of the solvers and scorers it names |

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
recompute, recovery or rescore. It lives in `src/inspect_ai/_eval/score.py`,
next to the metric resolvers that use it:

```python
class LogTaskFileImport:
    """The trust decision and task-file import for one recompute, recovery
    or rescore.

    Shared by the metric resolvers of one operation (scorer metrics and
    task-level metrics), so the task file is imported at most once per
    recompute or recovery and reported once.
    """

    def __init__(
        self,
        log: EvalLog,
        *,
        trust_log: bool,
        import_task_file: bool = True,
        opt_in: str = TRUST_LOG_OPT_IN,
    ) -> None:
        """`import_task_file=False` is for rescoring with the log's own
        scorers (step 6): options are trusted, but a missing metric fails
        as today instead of importing the task file. `opt_in` is the
        closing advice of both untrusted-log errors (the LookupError below
        and step 3's DisallowedRegistryArg), so each caller names an option
        it actually has."""

    trust_log: bool
    task_path: Path | None  # Path(log.eval.task_file).absolute(), or None
    imported: bool

    def import_metrics_file(self, name: str) -> bool:
        """Import the task file for metric `name` if trusted, allowed, not
        yet done, and `task_path` exists, with load_file_tasks(); log the
        record line (below) once. Returns whether it has been imported."""
```

The metric resolvers (`score.py:562`, `:590`, `:648`) take it instead of a
flag. They are internal (their only callers are `score.py`,
`log/_metric.py` and `log/_recover/_write.py`):

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
advice text from `task_import.opt_in`. Each resolver makes the metric
definitions it consumes resolvable before building anything, through one
shared implementation:

```python
def ensure_metrics_registered(
    definitions: Iterable[tuple[EvalMetricDefinition, str]],
    task_import: LogTaskFileImport,
) -> None:
    """Make every metric in `definitions` resolvable, or raise.

    Each definition comes with the label used in the error ("used by scorer
    'my_scorer'" or "a task-level metric"). Walks nested metric registry
    dicts inside options too. If any metric is not registered, calls
    task_import.import_metrics_file(name); then raises the shared
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
recompute or recovery. A custom task-level metric defined in the task file
is covered as well as a scorer metric. Today, in recompute and recovery,
only scorer metrics trigger the import (`score.py:657-666`), and because
task-level metrics are resolved first, an unregistered task-level metric
fails with the registry's generic "not found" `LookupError`.

When the trusted import runs, the tracker logs
`Imported task file /abs/path/evals/task.py (recorded in the log) to load metric 'my_metric'.`
at `INFO`, once per tracker. Nothing prints it: the tracker is local to
metric resolution and returns nothing to its callers, and the user who
passes `trust_log=True` or `--trust-log` asked for the import (step 7's
printed records are for run operations, where the log chooses what runs).
`inspect log recover --log-level info` shows it.

`trust_log=True` means the caller trusts the log's code-selecting fields. It
does what happens today for scorer metrics, extended to task-level metrics:

- The first unregistered metric name in a source a resolver consumes
  triggers `load_file_tasks(Path(task_file).absolute())`, once per
  `LogTaskFileImport`, resolved against the working directory, with the
  `@task`/`@task_source` filter (the loader `resolve_scorers_info()` uses
  today).
- Metric options are rebuilt by `metric_create()` with no restriction, so a
  custom metric whose options hold a model or another registry object is
  rebuilt as it is today.

With `trust_log=False`:

- No import. An unregistered metric name, in whichever source the resolver
  consumes, raises `LookupError` (the type raised today when a metric
  cannot be found, so callers that catch it keep working) with one shared
  message that says what to do:

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
    rescore with its own scorers instead (inspect score without --scorer)."

  With `trust_log=True` the same message, without the opt-in sentence, is
  raised for a metric the task file does not define either (or, with
  `import_task_file=False`, for any unregistered metric).

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
  `recover_eval_log_async(..., trust_log: bool = False)`
  (`src/inspect_ai/log/_recover/_api.py`), which resolve metrics before
  they write (below). Both also take the private keyword-only
  `_untrusted_metrics: Literal["raise", "warn"] = "raise"` (eval-set,
  below). The sync wrapper passes an explicit keyword list to the async
  function (`_api.py:163-173`), so it forwards `trust_log` and
  `_untrusted_metrics` as it forwards `_stats`; the CLI and eval-set call
  the sync function.
- `inspect log recover --trust-log` (`src/inspect_ai/_cli/log.py`,
  `recover_command`). Its help text says it imports the task file and runs
  its code.

**`edit_score()` and recovery resolve before they change anything.** Both
apply their change first today and resolve metrics afterwards, so a
resolution failure under the new default would leave a half-done result
that the suggested retry with `trust_log=True` cannot repair. So
`recompute_metrics()` is split into its two phases
(`src/inspect_ai/log/_metric.py`):

```python
class LogMetrics(NamedTuple):
    reducers: list[ScoreReducer] | None
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None
    scorers: list[ScorerInfo]

def resolve_log_metrics(
    log: EvalLog, *, trust_log: bool = False, reducer_advice: str | None = None
) -> LogMetrics:
    """Rebuild the log's reducers and metrics. Reads only the header; may
    import the task file (trust_log=True); raises LookupError or
    DisallowedRegistryArg. A reducer the registry cannot find raises
    LookupError with REDUCER_MISSING, then reducer_advice if given."""

def compute_log_metrics(log: EvalLog, resolved: LogMetrics) -> None:
    """eval_results() over the samples' scores; sets results and reductions."""

def recompute_metrics(log: EvalLog, *, trust_log: bool = False) -> None:
    compute_log_metrics(log, resolve_log_metrics(log, trust_log=trust_log))
```

Resolution reads only header fields (`eval.metrics`, `eval.scorers`,
`eval.config.epochs_reducer`), which neither an edit nor recovery changes,
so resolving first gives the same metrics.

Reducers are never imported from the task file, today or with
`trust_log=True`, and the registry's own error names only the reducer
(`my_reducer was not found in the registry`). So `resolve_log_metrics()`
builds each recorded reducer name with `create_reducers()` and re-raises
its `LookupError` (`from` the original) with this text, leaving the general
reducer constructor unchanged:

```
Epoch reducer 'my_reducer' (the log's epochs_reducer) is not registered.
Install the package that defines it, or import the module that defines it,
first; the log's task file is not imported for reducers.
```

`recompute_metrics()` and `edit_score()` pass no `reducer_advice`, because
`trust_log=True` does not help them. Untrusted recovery passes
`RECOVER_REDUCER_ADVICE`: "Nothing was written; the crashed log and its
buffer are unchanged. To recover it without results instead, pass
trust_log=True (inspect log recover: --trust-log); this imports the log's
task file and runs its code, so do it only for logs you trust." Trusted
recovery passes none, since it warns instead of raising (below).

- **`edit_score()`.** Today it sets the score, appends to `score.history`
  and inserts a `ScoreEditEvent`, then calls `recompute_metrics()`
  (`log/_score.py:71-147`). It now finds the sample as today (`:44-69`),
  then, when `recompute_metrics=True`, calls `resolve_log_metrics()` before
  its first mutation (the `sample.scores = {}` initialisation at `:72`),
  applies the edit as today, and calls `compute_log_metrics()`. A missing
  metric or a forbidden option raises with the log unchanged, and a retry
  with `trust_log=True` applies the edit once.
- **Recovery.** Today `write_recovered_eval_log()` resolves and computes
  metrics after it has written every sample, inside one `except Exception`
  that logs "Unable to recompute metrics for recovered log: ..."
  (`_write.py:271-287`); `recover_eval_log_async()` then removes the buffer
  under the default `cleanup=True` (`_api.py:325-329`), and with
  `overwrite=True` replaces the crashed log (`:318-322`) with a file that
  recovery rejects as input (`_read.py:72-75`). Under the new default the
  suggested rerun with `--trust-log` would then have nothing to recover.
  Instead, `recover_eval_log_async()` calls `resolve_log_metrics()` on the
  crashed log's header after its existing guards, which write nothing, and
  before `write_recovered_eval_log()`, and passes the resolved
  `LogMetrics` to the writer:
  - Untrusted resolution fails (`trust_log=False`): any metric that is not
    registered, whether the task file defines it, an extension package that
    is not installed does, or nothing does any more; an epoch reducer that
    is not registered; or a forbidden option. The resolver cannot tell
    these apart without importing the task file. A missing metric raises
    the step 2 `LookupError`, a missing reducer the reducer `LookupError`
    above with `RECOVER_REDUCER_ADVICE`. `recover_eval_log()`,
    `recover_eval_log_async()` and `inspect log recover` raise it, with the
    `--trust-log` advice it carries, before anything is written or cleaned
    up. The crashed log and its buffer are untouched, so the rerun with the
    flag works. The CLI reports it with `click.ClickException`, as it does
    `RecoveryThresholdExceeded` (`_cli/log.py:495-496`).
  - Trusted resolution fails (`trust_log=True`: a metric the task file
    does not define, a missing reducer): as today, the writer gets no
    metrics, writes the log without results and logs the existing warning.
    So the warn-and-write fallback for an unavailable dependency is now
    reached only with trust, or through eval-set's `"warn"` (below).
  - A metric function that raises while computing keeps today's handling:
    the writer's `except Exception` now wraps only `eval_results()`.

  Without results a resolving recovery (`incomplete_action` other than
  `"retry"`) does not finalize (`_write.py:314`), as today.

Callers inside Inspect:

- `eval_retry_async()` passes `trust_log=True` to both recovery calls
  (`eval.py:1728` and the threshold fallback at `:1739`). The retry imports
  the same task file and runs the task moments later, so this changes
  nothing a retry can do, and keeps the recovered log's metrics and
  finalization identical; a trusted failure warns and continues as today.
- eval-set recovery (`_recover_crashed_log()`, `evalset.py:1575-1586`,
  reached from `as_previous_tasks()`, `list_latest_eval_logs()` and
  `_resumed_task()`) uses the default `trust_log=False` and keeps today's
  warn-and-continue behaviour: it passes the private
  `_untrusted_metrics="warn"` on both of its `recover_eval_log()` calls
  (the resolving call and the `RecoveryThresholdExceeded` fallback,
  `evalset.py:1575`, `:1586`), so an untrusted resolution failure is
  written without results and warned about, as trusted failures are. Both
  calls sit inside `_recover_crashed_log()`'s outer `except`, which would
  otherwise keep the crashed log silently if the keyword were rejected, so
  the eval-set tests assert the recovered log, not just a completed
  eval set. The paired task file has already been loaded to
  build the task (see Current behaviour), so metrics defined in or imported
  by it are registered and recovery results do not change for them. The one
  difference: a metric whose recorded options hold a model or a non-metric
  registry object is refused by step 3, recovery of that log has no
  results, and with a resolving `incomplete_action` its in-progress samples
  re-run rather than being resolved, which is what the default `"retry"`
  disposition does anyway. No built-in metric takes such options, and
  eval-set does not take the log's word for them because metric definitions
  are not bound by the task identifier.
- `score_async()` resolves the log's metrics for `--action overwrite`
  trusted or untrusted according to where the scorers came from (step 6).

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
  rescoring a trusted log with its own scorers, and never a `trust_log`
  argument it does not accept.

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

The internal `PreviousTask` carries the sandbox to resume in, set by the code
that builds it, and `resolve_previous_task()` uses it as given:

- eval-set (`as_previous_tasks()`, `evalset.py:1508`, which scanner resume
  also uses, and `_resumed_task()`, `:1735`): copy `ResolvedTask.sandbox`.
  That is the resolution a fresh run of the task gets (`resolve_task_sandbox()`,
  `loader.py:412`, called from `as_resolved_tasks()`, `loader.py:120`), and it
  keeps an override a caller already resolved onto a `ResolvedTask` passed to
  `eval_set()` without repeating it. Resolving again from the underlying
  `Task` would lose that override.
- eval-retry (`eval.py:1927`): keep
  `resolve_task_file_sandbox(log.eval.task_file, log.eval.sandbox)`. A retry
  replays the original run's sandbox, including a `--sandbox` override that
  only the log remembers, with relative config paths resolved against the
  recorded task file.

No other field changes.

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

### 6. `inspect score`: recorded scorer names are registry names, and the log's metrics resolve before scoring

Decision: Ransom, 2026-10-16. Step 6 changes only what the log's own
fields can select and when the log's metrics are checked. Scorer resolution
stays in the CLI (`_cli/score.py:206`, before `score_async()`), the
fallback loader is unchanged, and `score()` / `score_async()` keep their
public signatures.

**Recorded scorer names are registry names.** For the names `inspect score`
takes from the log (`log.eval.scorers[*].name`, or `log.results.scores[*].name`
for logs without `eval.scorers`), `resolve_scorers()` (`score.py:598`) no
longer calls `scorer_from_spec()`, which parses `<path>@<name>` or an
existing path as a file (`loader.py:789`). It calls a small function in
`loader.py`, `scorer_from_log_name()`, which is the bare-name branch of
`scorer_from_spec()` (`loader.py:828-862`) moved out: the registry
(`scorer_from_registry()`, step 1), and when that raises `ValueError`,
today's fallback unchanged, `load_module(task_path)` on the recorded task
file and the registry again, with the same return-annotation check and
`PrerequisiteError` messages. The catch stays as broad as today's
(`loader.py:833-835`): it covers a name that is not registered and also a
registered scorer or scanner factory that raises `ValueError` for the
recorded options (for example `precomputed_scores` with an invalid
`on_missing`), so the fallback triggers in exactly the cases it does
today. Below, "the registry cannot build it" means either case. `scorer_from_spec()` calls it for bare names,
so a bare `--scorer NAME` keeps exactly today's fallback to the recorded
task file (decision: Ransom, 2026-10-14). A recorded name containing `@`,
or one that happens to be an existing path, is looked up in the registry
like any other name and is never imported; Inspect never writes such names
(Current behaviour), so no log Inspect produced is affected.

**The fallback import is recorded.** When `scorer_from_log_name()` imports
the task file, it reports the import itself, just before `load_module()`:
it prints
`Imported task file /abs/path/evals/task.py (recorded in the log) to load scorer 'my_scorer'.`
with `display().print()` (`inspect_ai._display`, imported inside the
function as `loader.py` already does for `inspect_scout`) and logs the
same line at `INFO`. The path is `task_path.absolute()`, computed when the
line is built, because `resolve_scorers()` passes the recorded relative
path (`Path(log.eval.task_file)`, `score.py:613`). Nothing is returned to
or threaded through `resolve_scorers()` (decision: Ransom, 2026-10-21,
keeping the 2026-10-16 decision of no tracker): `resolve_scorers()` is the
only caller that passes a `task_path` (`results.py:76` and `hf.py:196`
pass `None`), so the line is printed only by `inspect score`, as part of
its step 7 record. This covers both a recorded scorer and a bare
`--scorer NAME`. Like today's fallback, it runs once per scorer the
registry cannot build, and each import prints its line.

**The log's metrics resolve before scoring, trusted only with the log's
scorers.** `score_async()` calls `metrics_from_log_header()` (used when
`metrics` is `None` and the action is `"overwrite"`) before the scoring
loop (`tg_collect`, `score.py:336`) instead of after it (`:347-349`), with
the `action` default (`:302`) moved up with it. The call reads only
`eval.metrics`, which scoring does not change, so the result is the same,
but a missing metric or a forbidden option now fails before any scorer
runs. Under `--stream` the CLI has already called `log_init()` and
`log_start()` on the output, as it does today before any failure, but no
sample is read, scored or written.

The tracker it passes depends on where the scorers came from, which only
the CLI knows, so `score_async()` gains a private keyword-only
`_log_scorers: bool = False`, which `_cli/score.py` sets to `scorer is
None`:

- `_log_scorers=True` (`inspect score` without `--scorer`, a run
  operation): `LogTaskFileImport(log, trust_log=True,
  import_task_file=False)`. Metric options are rebuilt without restriction
  and no task file is imported for a metric, as today; an unregistered
  task-level metric still fails with `LookupError`, as today, unless the
  scorer fallback has already imported the task file and registered it.
- `_log_scorers=False` (`--scorer`, and every `score(log, scorers)` call
  from Python): `LogTaskFileImport(log, trust_log=False,
  opt_in=SCORE_OPT_IN)`. No import, step 3's restrictions, and the step 2
  message advising `metrics=` (`--metric`). Today this path rebuilds any
  model or registry object in the metric options.

After step 6 the only file a log can make `inspect score` import is its
recorded task file, through the scorer fallback, which is what step 7
reports. This does not stop a log from naming an arbitrary task file:
rescoring with the log's scorers imports it by design, and a bare
`--scorer NAME` the registry cannot build does too, because the user named a scorer they
expect to find there, it is the same file, and `inspect score --help` says
to use the command only on trusted logs (step 7).

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
  the CLI section and the `score()` section), the `score()` /
  `score_async()` docstrings, and the
  eval-retry section of the docs, next to the "Logs from others" note in
  `docs/eval-logs.qmd` (step 2), which says that reading, viewing,
  recomputing and recovering a log do not run its code unless `trust_log` is
  passed.

The CLI also prints a record of what it loaded, with `display().print()`. It
is a record for the user to check afterwards, not a mitigation; nothing
waits on it:

- `inspect score`, when the scorer fallback imports the task file (step 6),
  one line per import, naming the scorer and printed by
  `scorer_from_log_name()` in `loader.py` at the import:
  `Imported task file /abs/path/evals/task.py (recorded in the log) to load scorer 'my_scorer'.`
  When the log's model is used (no `--model`) and the log records a
  `model_base_url`: `Scoring model openai/gpt-4o from the log, base URL https://...`.
- `inspect eval-retry` (`eval_retry_async()`, one block per log, before
  recovery): the task file (absolute path) and task name, or for a log with
  no task file and an `hf/` task name, the Hugging Face repo and revision
  whose `eval.yaml` will define the task; the solver file if `eval.solver`
  is a file spec; the model and its base URL if recorded; the sandbox type
  and its config file (or "inline config"); the sentinel monitors and
  protocols (their registry names) if `eval.config.sentinel` is set, which
  the retry forwards to `eval_async()` (`eval.py:1831`, `:1975`) and
  `resolve_sentinel_spec()` builds from installed `inspect_sentinel`
  factories with their recorded parameters (`eval.py:856-858`,
  `_sentinel/_config.py:120-129`); and the ACP server binding if
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
  (one rule for the command), but a log the user only scores with their own
  scorer could then build models and other registry objects from its metric
  options. Rejected (decision: Ransom, 2026-10-14): trust follows the
  scorers' source (step 6).
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
- CLI: `inspect log recover --trust-log`.
- `score()` / `score_async()` keep their public signatures; `score_async()`
  gains only the private `_log_scorers` (step 6), and `recover_eval_log()`
  and `recover_eval_log_async()` the private `_untrusted_metrics` (step 2),
  which the sync wrapper forwards with `trust_log`.

Behaviour changes, by user:

- **`recompute_metrics()` / `edit_score()` users relying on #3981** (custom
  metrics defined in a task file, recomputed in a fresh process): the call
  raises `LookupError` with the message in step 2 instead of importing. Fix:
  import the module that defines the metric before the call, or pass
  `trust_log=True`. Users who recompute in the process that ran the eval,
  or whose metrics live in installed packages, see no change. `edit_score()`
  raises before it edits, so the log is unchanged and the call can be
  repeated with `trust_log=True`.
- **`inspect log recover` / `recover_eval_log()` users whose log's metrics
  or reducers cannot be resolved untrusted**: recovery now raises before
  writing anything, where today it imports the task file for a scorer
  metric and otherwise recovers without results and warns. This covers a
  metric defined in the task file, a metric or reducer from an extension
  package that is not installed or no longer defines it, and model-valued
  or other forbidden metric options. The crashed log and buffer are
  untouched, so each fix is a rerun:
  - Install the package that defines a missing metric or reducer (a
    `package/name` lookup loads installed packages' entry points), or from
    Python import the module that defines it before the call. This needs
    no trust in the log.
  - Rerun with `--trust-log` (`trust_log=True`), only for a log you trust:
    it imports the task file and rebuilds options as today, and anything
    still unresolved is recovered without results with today's warning.
  An untrusted log whose metric no installed code defines cannot be
  recovered directly without `--trust-log`; that is the cost of raising
  rather than writing a result-less log (decision: Ransom, 2026-10-16),
  and eval-set recovery keeps warning instead. A metric that raises while
  computing is handled as today (recovered without results, with a
  warning).
- **`eval-retry`**: no change apart from the printed record and help text;
  its recovery passes `trust_log=True`, so it imports the task file and
  rebuilds metric options as today.
- **`inspect score` without `--scorer`** (the log's scorers): unchanged
  apart from the record line and the earlier failure below. Metric options
  are rebuilt as today, and an unregistered task-level metric still fails
  with `LookupError`.
- **`inspect score --scorer ... --action overwrite` and `score(log, scorers,
  action="overwrite")`**: the log's `eval.metrics` are rebuilt untrusted. A
  task-level metric that is not registered fails with the step 2
  `LookupError` instead of the registry's generic one, and a metric whose
  options hold a model or a non-metric registry object now raises
  `DisallowedRegistryArg` instead of being rebuilt. Fix: pass `metrics=`
  (`--metric`), or rescore with the log's scorers. Append, and logs whose
  metrics are registered and take no such options, are unchanged.
- **`inspect score --action overwrite`, either mode**: a log whose metrics
  cannot be resolved now fails before any sample is scored, rather than
  after scoring every sample (and, under `--stream`, writing them).
- **Recorded scorer names that are paths** (`<path>@<name>`, or an existing
  path) are treated like any other unregistered name (the task-file
  fallback, then today's `PrerequisiteError` suggesting `--scorer`)
  instead of importing the path. Inspect never writes such names.
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
- **Score keys that name files** get default metrics instead of an import.
  Inspect never writes such keys.
- **Custom metrics taking models or non-metric registry objects as options**:
  rebuilt only with `trust_log=True` or when rescoring with the log's
  scorers; otherwise they raise a `ValueError` naming the option.
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
- `inspect score` imports at most the recorded task file (step 6), through
  today's scorer fallback, and records each import (step 7). Recorded
  scorer names are never parsed as paths. With the log's scorers its
  metric options are rebuilt without restriction, as today. With the user's
  scorers (`--scorer`, or `score(log, scorers)`) the log's metrics import
  nothing and their options are restricted by step 3; only a bare
  `--scorer` name the registry cannot build still falls back to the recorded
  task file (decision: Ransom, 2026-10-14). Metric resolution happens before
  any scorer runs. The log's model and model roles are still built (under
  "Not this design").
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
  approval and review policies, the sentinel configuration (installed
  monitor and protocol factories, built with the log's parameters), and the
  ACP binding. The docs and `--help`
  say these commands should only be run on trusted logs; step 7's printed
  record shows what was used but is not a safeguard. The credential and
  network items are under "Not this design".

The `@task` decorator filter in `load_file_tasks()` is not a security
boundary (any file can contain a decorated function); it only avoids
importing files that are not task files.

## Testing

All of these run in the default test job: no network, Docker or model
provider. The malicious-log tests use a marker module that records each
import of it in a file under `tmp_path`, and a spy on `get_model` that fails
the test if it is called with the fixtures' distinctive model name or base
URL. The four fixtures below record `eval.model` as `mockllm/model` and no
`eval.model_base_url` or `eval.model_roles`, so the distinctive values
appear only in their metric options; the `evals_df()` with `model_info()`
test reads a separate log whose `eval.model` is a distinctive name missing
from the model database. The spy must also patch the module-level bindings `score.py` and
`_model_config.py` import (`score.py:54`), or it misses `score_async()`.

New file `tests/log/test_untrusted_logs.py` (no existing file covers
operations across modules; it follows
`test_cli_never_resolves_scorers_or_imports_task_code` in
`tests/_control/test_log_dir.py`). Each fixture isolates one protection, so
one check cannot stop an operation before another is reached:

1. **Hostile score key**: registered metrics only, and sample score keys
   naming a marker module as `<path>@<name>` and as a bare existing path.
2. **Missing task-file metric**: `task_file` pointing at a marker module
   that defines a scorer metric and a task-level metric. Three variants:
   2s uses only the scorer metric (in `eval.scorers[*].metrics`; every
   `eval.metrics` entry registered), 2t only the task-level metric, and 2b
   both. Today the task-level resolver runs first (`log/_metric.py:40-41`,
   `_write.py:273-274`) and a failure there stops the operation before the
   scorer resolver, so only 2s reaches the scorer-metric path; 2b is for
   the trusted single-import test.
3. **Forbidden metric options**: a model dict and a non-metric registry dict
   in registered metrics' options, at the top level and nested. Two
   variants for the same reason: 3s puts them only in
   `eval.scorers[*].metrics`, 3t only in `eval.metrics`.
4. **Hostile sandbox**: a header sandbox that differs from the task's,
   including an inline compose config.

What the tests must prove:

- **Read operations import and construct nothing.** For every read
  operation each fixture applies to (`recompute_metrics()`,
  `edit_score()`, `recover_eval_log()` and its async form and CLI, eval-set
  resume on both recovery paths, `evals_df()` with `model_info()`,
  `read_eval_log()`, `inspect log dump`, `inspect info`, and the view
  server's log endpoints): no marker, no spy hit. Fixture 1 gets default
  metrics. For recompute, edit and direct recovery, each of 2s and 2t
  raises the step 2 `LookupError` and each of 3s and 3t
  `DisallowedRegistryArg`, each naming the metric (and option path) and
  ending with the `trust_log` advice; a missing extension metric
  (`somepkg/nope`) raises the same `LookupError`. A missing epoch reducer
  raises `LookupError` whose message names the reducer and says to install
  or import it; from direct recovery it also says nothing was written and
  names `--trust-log` / `trust_log=True` as the way to recover without
  results, and from recompute and edit it does not mention `trust_log`.
  Eval-set resume applies only to fixtures 1, 3s, 3t and 4: a fixture 2
  log names the marker task file, which pairs only with a task loaded from
  that file (`evalset.py:2073-2085`), and loading it registers the marker's
  metrics, so fixture 2 is the legitimate case below. On both recovery
  paths, 3s and 3t log the warning with the `DisallowedRegistryArg`
  message, recover the log without results and complete the eval set
  (step 2's `_untrusted_metrics="warn"`); 1 recovers with default metrics
  and 4 is the sandbox case. Fixtures 1, 2s, 3s and 3t fail on `main` today
  (2s imports the marker; 3s and 3t rebuild the options), so they are the
  regression tests for steps 1, 2 and 3; 2t fails there on the message.
- **A failed edit or recovery changes nothing.** `edit_score()` on
  fixtures 2s, 2t, 3s and 3t leaves the log unchanged; the retry with
  `trust_log=True` applies the edit once (one history entry for the edit,
  one `ScoreEditEvent`). `recover_eval_log()` and `inspect log recover` on
  fixtures 2s, 2t, 3s and 3t, with a database and with a filestore buffer, raise
  before writing: no output file, the crashed log and buffer intact,
  including with `overwrite=True`; the rerun with `trust_log=True` /
  `--trust-log` recovers with results and, under a resolving
  `incomplete_action`, finalizes.
- **Trust restores today's behaviour, importing once.**
  `recompute_metrics(trust_log=True)` and trusted recovery on fixture 2b
  compute both metrics with one marker import and one `INFO` record (caplog;
  nothing is printed); eval-retry of a crashed fixture 2b log recovers its
  metrics, and eval-set
  resume of a fixture 2b log, paired with the task loaded from its marker
  file, recovers with both metrics and no opt-in. A registered
  custom metric taking a model recomputes with `trust_log=True`, and
  `grouped(accuracy(), ...)` passes step 3 untrusted.
- **Rescoring trust follows the scorers' source.** With `--scorer` (and
  `score(log, [match()])`), `--action overwrite` and an explicit
  `--model mockllm/model` (`model="mockllm/model"`), fixtures 2t and 3t raise
  with the `SCORE_OPT_IN` advice before any sample is scored (a counting
  scorer is never called), with no marker and no spy hit. The explicit
  model, and fixtures that keep the distinctive model and base URL out of
  `eval.model` and `eval.model_roles`, let the spy see only the metric
  options: `score_async()` builds the log's model when no model is passed
  and always builds the log's model roles (`score.py:263-275`), before
  metric resolution, which is a "Not this design" item; `--metric`
  instead succeeds; fixtures 2s and 3s (the old `eval.scorers` naming an
  unavailable metric or forbidden options) do not block the overwrite. Without `--scorer`, a model-option metric still
  computes and an unregistered task-level metric still raises
  `LookupError`.
- **Recorded scorer names are registry names.** A recorded scorer name of
  the form `<path>@<name>` is not imported; an unregistered recorded scorer
  and a bare unregistered `--scorer` both load from the recorded task file
  as today and print the record line, and so does a registered scorer whose
  factory raises `ValueError` for the recorded options (the fallback's
  trigger is unchanged); `--scorer path.py@name` still loads
  that file; a recorded option named `name` still reaches the factory.
- **Legitimate flows keep working.** `ScorerInfo.from_name()` returns the
  defaults for unregistered names and for core scorers that need arguments
  (`pattern`, `answer`, ...), so a solver-written `pattern` score still
  computes; `create_registry_object()` with `allowed_types` refuses
  forbidden values at every depth before the outer factory runs, while
  `allowed_types=None` and `registry_kwargs(**params)` behave as today;
  eval-set resume uses the task's sandbox (fixture 4), an explicit
  `--sandbox` wins, and eval-retry keeps the log's; `model_info()` still
  fills metadata from the database, `set_model_info()` and `model_info=`;
  `inspect score --help` and `inspect eval-retry --help` carry the
  trusted-logs sentence, and the retry record lists what it loads,
  including the sentinel entries of a log that records
  `eval.config.sentinel` (with `resolve_sentinel_spec()` mocked, so the
  test needs no `inspect_sentinel`).

Tests go next to the existing ones for each area (`tests/scorer/`,
`tests/log/test_recover_*.py`, `tests/test_retry.py`,
`tests/test_eval_set.py`, `tests/_eval/test_score.py`,
`tests/util/test_registry.py`, `tests/analysis/test_prepare.py`). Async
tests (recovery, retry) run under both backends with `--runtrio` before the
PRs open, as the repo requires.

## Implementation plan

1. **Read paths import nothing by default** (steps 1, 2, 3). Files:
   `src/inspect_ai/_util/registry.py` (`allowed_types` on
   `create_registry_object()`, `_instantiate_registry_object()`,
   `registry_arg()`; `_resolve_registry_args()` behind `registry_kwargs()`;
   `DisallowedRegistryArg`), `src/inspect_ai/_eval/loader.py`
   (`scorer_from_registry()`), `src/inspect_ai/_eval/task/results.py`
   (`from_name()`), `src/inspect_ai/_eval/score.py` (`LogTaskFileImport`,
   `resolve_scorers_info()`, `metrics_from_log_header()`,
   `metric_from_log()`, `ensure_metrics_registered()`; in `score_async()`,
   `_log_scorers` and the metric resolution moved before scoring),
   `src/inspect_ai/_cli/score.py` (passes `_log_scorers`),
   `src/inspect_ai/log/_metric.py` (`resolve_log_metrics()`,
   `compute_log_metrics()`), `src/inspect_ai/log/_score.py` (resolve before
   editing), `src/inspect_ai/log/_recover/_api.py` and `_write.py`
   (`trust_log` and `_untrusted_metrics` on both recovery functions,
   forwarded by the sync wrapper; resolve before writing),
   `src/inspect_ai/_cli/log.py` (`--trust-log`, the error),
   `src/inspect_ai/_eval/eval.py` (both retry recovery calls pass
   `trust_log=True`), `src/inspect_ai/_eval/evalset.py` (`_untrusted_metrics="warn"` on both
   `recover_eval_log()` calls),
   `docs/eval-logs.qmd` (the recompute example and a short "Logs from
   others" note), `docs/scoring-workflow.qmd` (how the log's metrics are
   treated with the user's scorers), and the tests for these paths,
   including `tests/log/test_untrusted_logs.py`. The rescoring trust split
   belongs in this step: otherwise `inspect score` without `--scorer` would
   rebuild metrics untrusted.
2. **eval-set resume sandbox** (step 4). `src/inspect_ai/_eval/task/task.py`
   (`PreviousTask.sandbox`), `src/inspect_ai/_eval/loader.py`,
   `src/inspect_ai/_eval/evalset.py`, `src/inspect_ai/_eval/eval.py`,
   `tests/test_eval_set.py`, `tests/test_retry.py`.
3. **Recorded scorer names, run-operation help text and records** (steps 6,
   7). `src/inspect_ai/_eval/loader.py` (`scorer_from_log_name()`, the
   record line), `src/inspect_ai/_eval/score.py` (`resolve_scorers()`),
   `src/inspect_ai/_cli/score.py` (help, record),
   `src/inspect_ai/_cli/eval.py` (`eval_retry_command` help),
   `src/inspect_ai/_eval/eval.py` (retry record),
   `docs/scoring-workflow.qmd` and the eval-retry docs,
   `tests/_eval/test_score.py`, `tests/test_retry.py`.
4. **`model_info()` direct lookup** (step 5).
   `src/inspect_ai/analysis/_prepare/model_info.py`,
   `tests/analysis/test_prepare.py`, the analysis tests in
   `tests/log/test_untrusted_logs.py`.

Steps 1 and 2 close the read-operation paths and should land first; 3 and 4
are independent of each other. No step edits `CHANGELOG.md`: Release Please
writes it from the PR titles, and step 1 is breaking (`fix!:` with a
`BREAKING CHANGE:` paragraph naming the `trust_log` opt-in and the
rescoring metric change).

## Open questions

None open. Ransom settled the three earlier questions on 2026-10-06: break
now (Alternatives considered), `model_info()` direct lookup only (step 5),
and a printed record plus a plain statement in the docs and `--help` rather
than a confirmation (step 7). He settled rescoring trust on 2026-10-14: the
log is trusted only when its own scorers are used. Also on 2026-10-14 he
kept the bare unregistered `--scorer NAME` fallback to the recorded task
file (step 6). On 2026-10-16 he cut step 6 to its essentials and chose
resolve-first recovery over keeping recovery inputs after a failure.

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
