# Code execution from a malicious eval log

Status: proposed, 2026-10-06. Issue: none (task from Ransom Richardson). Author: agent (Claude), reviewed by Codex; see the PR.

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
  task file, and for a retry the recorded solver file), and say which files
  and endpoints they are about to use before using them.
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
| `inspect score`, `resolve_scorers()` | scorer names and options from the log; model and model roles from the log | run operation (`src/inspect_ai/_cli/score.py:206`, `score.py:263-275`) |

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
the log describes: `eval_retry()` / `inspect eval-retry`, and `inspect score`
/ `resolve_scorers()` when scorers come from the log. Running one on a log
means trusting the log's task code. Everything else is a **read operation**:
viewing, listing, converting, analysis, `recompute_metrics()`,
`edit_score()`, `recover_eval_log()` / `inspect log recover`, and `eval_set()`
(whose tasks come from the user's command line; the logs only supply
completed samples).

| Operation | Python files the log can make Inspect import, after this design |
|---|---|
| read operations | none, unless the caller passes `trust_log=True` (`inspect log recover --trust-log`) to recompute or recover, which imports the recorded task file |
| `inspect score` with the log's scorers | the recorded task file, and only when a recorded scorer name is not registered |
| `eval-retry` | the recorded task file and the recorded solver file |

In both classes, registry names may load installed packages' entry points and
call their registered factories (see "Registry names" below).

Run operations, and read operations whose caller passes `trust_log=True`,
rebuild a log's metric definitions as today. Other read operations rebuild
them under the restrictions of step 3.

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

`resolve_scorers_info()` and `metrics_from_log_header()` /
`metric_from_log()` (`score.py:562`, `:590`, `:648`) gain one keyword:

```python
def resolve_scorers_info(log: EvalLog, *, trust_log: bool = False) -> list[ScorerInfo]: ...
def metrics_from_log_header(log: EvalLog, *, trust_log: bool = False) -> ...: ...
def metric_from_log(metric: EvalMetricDefinition, *, trust_log: bool = False) -> Metric: ...
```

`trust_log=True` means the caller trusts the log's code-selecting fields. It
does exactly what happens today, in two places:

- The first metric name in `eval.scorers[*].metrics` that is not registered
  triggers `load_file_tasks(Path(task_file).absolute())`, once per call,
  resolved against the working directory, with the `@task`/`@task_source`
  filter.
- Metric options are rebuilt by `metric_create()` with no restriction, so a
  custom metric whose options hold a model or another registry object is
  rebuilt as it is today.

With `trust_log=False`:

- No import. An unregistered metric name raises `LookupError` (the type
  raised today when a metric cannot be found, so callers that catch it keep
  working) with a message that says what to do:

  ```
  Metric 'my_metric' used by scorer 'my_scorer' is not registered. If it is
  defined in the task file ('evals/task.py'), import that module before
  recomputing, or pass trust_log=True (inspect log recover: --trust-log) to
  import the log's task file. This runs the file's code; do it only for logs
  you trust.
  ```

- Metric options pass the check in step 3 before `metric_create()`.

One keyword covers both because both answer the same question, whether the
log may choose code, and a user who trusts a log for one has no reason to
distrust it for the other. It is threaded through every public caller,
keyword-only and defaulting to `False`:

- `recompute_metrics(log, *, trust_log: bool = False)`
  (`src/inspect_ai/log/_metric.py`), to both `metrics_from_log_header()` and
  `resolve_scorers_info()`.
- `edit_score(..., *, trust_log: bool = False)`
  (`src/inspect_ai/log/_score.py`), passed to `recompute_metrics()`.
- `recover_eval_log(..., trust_log: bool = False)` and
  `recover_eval_log_async(...)` (`src/inspect_ai/log/_recover/_api.py`),
  passed to `write_recovered_eval_log()` (`_write.py:89`) and on to both
  functions (`_write.py:273-274`).
- `inspect log recover --trust-log` (`src/inspect_ai/_cli/log.py`,
  `recover_command`). Its help text says it imports the task file and runs
  its code.

Recovery keeps its current error handling: a `LookupError` or `ValueError`
from metric resolution is logged as the existing warning ("Unable to recompute
metrics for recovered log: ...", `_write.py:287`), now carrying the messages
above, and the recovered log has no results, as today when resolution fails.
Without results a resolving recovery (`incomplete_action` other than
`"retry"`) does not finalize (`_write.py:314`): the log stays retryable and
its in-progress samples are re-run instead of resolved.

Callers inside Inspect:

- `eval_retry_async()` passes `trust_log=True` to both recovery calls
  (`eval.py:1701` and the threshold fallback at `:1712`). The retry imports
  the same task file and runs the task moments later, so this changes
  nothing a retry can do, and keeps the recovered log's metrics and
  finalization identical.
- `score_async()` passes `trust_log=True` to `metrics_from_log_header()`
  (`score.py:348`, used by `inspect score --action overwrite`): rescoring is a
  run operation.
- eval-set recovery (`_recover_crashed_log()`, `evalset.py:1522`, reached
  from `as_previous_tasks()`, `list_latest_eval_logs()` and `_resumed_task()`)
  uses the default `False`. The paired task file has already been loaded to
  build the task (see Current behaviour), so metrics defined in or imported
  by it are registered and recovery results do not change for them. The one
  difference: a metric whose recorded options hold a model or a non-metric
  registry object fails the step 3 check, recovery of that log has no
  results, and with a resolving `incomplete_action` its in-progress samples
  re-run rather than being resolved, which is what the default `"retry"`
  disposition does anyway. No built-in metric takes such options, and
  eval-set does not take the log's word for them because metric definitions
  are not bound by the task identifier.

### 3. Untrusted metric options cannot construct models or non-metric objects (fixes C)

With `trust_log=False`, `metric_from_log()` checks the options before calling
`metric_create()`:

```python
def check_log_metric_options(name: str, options: dict[str, Any]) -> None:
    """Reject metric options that would construct anything but metrics.

    Raises:
        ValueError: If an option value (at any depth) is a model dict, or a
            registry dict whose type is not "metric" or "score_reducer".
    """
```

It walks dicts and lists, using `is_model_dict()` and `is_registry_dict()`
(`registry.py:720`, `:647`), and recurses into the `params` of allowed
registry dicts. Nested metric registry dicts stay allowed because built-in
metrics take metrics as parameters: `grouped(accuracy(), "category")` records
its options as `{"metric": {"type": "metric", "name": "accuracy", "params":
{}}, "group_key": "category"}` (checked by running `registry_params()`).
The error names the metric and the offending option key. The check covers
both sources of metric definitions, `eval.metrics` and
`eval.scorers[*].metrics`, including nested lists and dict groups.

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

### 5. `model_info()` does not construct providers (fixes E)

`model_info()` (`src/inspect_ai/analysis/_prepare/model_info.py:68`) calls
`_get_model_info_direct()` (`src/inspect_ai/model/_model_info.py:319`)
instead of `get_model_info()`. It still checks the caller's `model_info`
mapping, models registered with `set_model_info()`, and the model database
with its aliases; it skips the provider-instantiation fallback. The public
`get_model_info()` is unchanged.

### 6. `inspect score` loads only the recorded task file (narrows a run operation)

Scorer names that come from the log are registry names. `resolve_scorers()`
(`score.py:598`) keeps calling `scorer_from_spec()` for an explicit `scorer`
argument (`--scorer`, the user's command line, which may be `path.py@name`),
and for names from `log.eval.scorers` or `log.results.scores` calls a new
function:

```python
# src/inspect_ai/_eval/loader.py
def scorer_from_log(
    name: str, task_path: Path | None, loaded: set[Path], /, **kwargs: Any
) -> Scorer:
    """Create a scorer named in a log: registered, or defined in the task file.

    Never parses `name` as a file path or `path@name` spec. If `name` is not
    registered and `task_path` exists, imports it once with load_file_tasks()
    (tracked in `loaded`) and tries the registry again. `task_path` must be
    absolute.

    Raises:
        PrerequisiteError: If the scorer cannot be resolved; the message
            suggests --scorer, as today.
    """
```

The control parameters are positional-only so that recorded scorer options
named `name`, `task_path` or `loaded` reach the factory, as they do through
`scorer_from_spec(..., **kwargs)` today (the registry bridge preserves such
names, `src/inspect_ai/_util/registry.py:452`).

`resolve_scorers()` computes `task_path = Path(log.eval.task_file).absolute()`
once (today it passes the recorded, usually relative, path, `score.py:613`).
The absolute path is what `load_file_tasks()` needs, because it changes into
the file's directory before opening its argument (`loader.py:548`): a
relative `evals/task.py` would be looked up as `evals/evals/task.py`. The same
absolute path goes into the `loaded` set and the step 7 notice.

Changes from today, for log-sourced names only:

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
- The task file is imported at most once per `resolve_scorers()` call (today
  `load_module()` runs once per unresolved scorer).

This does not stop a log from naming an arbitrary task file: rescoring with
the log's scorers imports the task file by design. It makes the task file the
only file a log can make `inspect score` import, which is what step 7 reports.

### 7. Run operations say what they will load before loading it

Two CLI notices, printed with `display().print()` before the first import:

- `inspect score` (`src/inspect_ai/_cli/score.py`), when `scorer_from_log()`
  is about to import the task file:
  `Importing task file /abs/path/evals/task.py (recorded in the log) to load scorer 'my_scorer'.`
  When the log's model is used (no `--model`) and the log records a
  `model_base_url`, also: `Scoring model openai/gpt-4o from the log, base URL https://...`.
- `inspect eval-retry` (`eval_retry_async()`, before recovery, one block per
  log): the task file (absolute path) and task name, the solver file if
  `eval.solver` is a file spec, the model and its base URL if recorded, the
  sandbox type and its config file (or "inline config"), and the ACP server
  binding if `eval.config.acp_server` is set.

Paths are printed resolved, so a relative `task_file` that resolves to an
unexpected file in the working directory is visible. The notices do not wait
for confirmation (see Open questions). `score()`/`eval_retry()` called from
Python log the same lines at `INFO`.

### Path resolution

Unchanged: relative paths keep resolving against the working directory. The
recorded `task_file` and `--solver` paths are working-directory relative by
construction, and a retry or rescore is run from the original project
directory. Resolving against the log's location would break every log kept
in a `logs/` subdirectory; requiring a match against a user-supplied path
adds a flag to every retry for no gain once the read operations import
nothing. The notices make the resolved path visible.

### Registry names

Unchanged in both classes. A `pkg/name` reference loads an installed
package's entry point, the module that package publishes for Inspect to
import, and calls its registered factories with arguments from the log.
`inspect eval` does the same, and the attacker cannot add packages. Step 3
limits what metric options in read operations can make those factories
build.

## Alternatives considered

- **Keep importing the task file in read operations and warn.** A warning
  after the import does not stop the import. A deprecation period that keeps
  the import for a release leaves the problem in place for that release.
  Recompute and recover users get an actionable error instead (Open question 1).
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
- **Requiring confirmation before a run operation imports.** It would break
  scripted `inspect score` and `eval-retry`, and running the log's code is the
  purpose of those commands. A notice informs without blocking (Open question 3).
- **Confining `eval-retry`'s solver file to the task file's directory.**
  Legitimate logs record `--solver` paths anywhere the user typed; a log
  that can name an arbitrary task file gains nothing from also naming a
  solver file, so confining it adds breakage without removing a capability.
- **Hashing the sandbox into the eval-set task identifier** instead of step 4.
  It would stop a log with a different sandbox from being paired, but it
  changes every existing identifier (logs from older runs would stop
  resuming) and still lets the log's sandbox win when the identifiers match.
- **Lazy model construction in `inspect score`.** Building the log's model
  only when a scorer asks for one would avoid constructing it for rule-based
  scorers. It changes how `score_async()` binds the task context, and the
  model is part of the run being scored; left under "Not this design".

## Compatibility and migration

No stored format, schema or generated TypeScript type changes. Existing logs
read, view, convert and resume as before.

Public API (additive, keyword-only, default preserves safety rather than old
behaviour):

- `recompute_metrics(..., trust_log=False)`,
  `edit_score(..., trust_log=False)`,
  `recover_eval_log(..., trust_log=False)`,
  `recover_eval_log_async(..., trust_log=False)`.
- CLI: `inspect log recover --trust-log`.

Behaviour changes, by user:

- **`recompute_metrics()` / `edit_score()` users relying on #3981** (custom
  metrics defined in a task file, recomputed in a fresh process): the call
  raises `LookupError` with the message in step 2 instead of importing. Fix:
  import the module that defines the metric before the call, or pass
  `trust_log=True`. Users who recompute in the process that ran the
  eval, or whose metrics live in installed packages, see no change.
- **`inspect log recover` users with task-file metrics**: the recovered log
  has no results and the warning names `--trust-log`. With a resolving
  `--incomplete-action`, such a log also does not finalize, so its
  in-progress samples are left for a retry. Rerun with the flag.
- **`eval-retry`**: no change apart from the notice; its recovery passes
  `trust_log=True`, so it imports the task file and rebuilds metric options
  as today, and recovered results and finalization are unchanged.
- **`inspect score`**: rebuilding `eval.metrics` for `--action overwrite`
  passes `trust_log=True`; unchanged.
- **`eval_set()` resume**: recovered metrics unchanged for metrics defined in
  or imported by the task file, which eval-set has already loaded. A metric
  whose recorded options hold a model or non-metric registry object is no
  longer rebuilt during eval-set recovery (step 2): that log is recovered
  without results, and with a resolving `incomplete_action` its in-progress
  samples are re-run instead of resolved. Resumed tasks now use the sandbox their task definition
  and `--sandbox` resolve to, rather than the one recorded in the previous
  log. These differ only if the user changed the task's sandbox or the
  `--sandbox` override between runs; the new samples then run in the
  sandbox the user asked for. Previous samples are reused as before.
- **`inspect score`**: logs written by Inspect are unaffected. A scorer that
  was found only by `load_module()` on a task file without a `@task` function
  is no longer found; the error suggests `--scorer`. Task files that import
  sibling modules now load.
- **Score keys that name files** get default metrics instead of an import.
  Inspect never writes such keys.
- **Custom metrics taking models or non-metric registry objects as options**:
  rebuilt only with `trust_log=True` (or by run operations); otherwise they
  raise a `ValueError` naming the option.
- **Scorers that need arguments, recorded only as score keys** (for example
  a solver-written `pattern` score): unchanged, they keep the default metrics
  (step 1).
- **`inspect_ai.analysis.model_info()`**: model names that only resolve by
  instantiating their provider (not in the database or its aliases) get no
  metadata; supply it with the `model_info` argument or `set_model_info()`
  (Open question 2).
- **Viewer and VS Code**: no change today (they do not edit scores). The
  planned score-edit endpoint (`design/viewer_log_editing.md`, Phase 3)
  must call `edit_score()` without `trust_log`, since the viewer
  serves logs it did not write; a task-file metric then returns the step 2
  error to the client.

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
  unless the caller passes `trust_log=True`.
- eval-set resume no longer lets a log choose the sandbox type or config of a
  task the user chose (step 4), including inline compose configs, which would
  otherwise run the log's images with the log's mounts.
- `inspect score` imports at most the recorded task file (step 6).
- What remains in read operations is installed code chosen by name: entry
  points of installed packages, their registered metric and reducer
  factories called with log arguments, registered scorer factories called
  with no arguments by `ScorerInfo.from_name()`, and sandbox plugins'
  `config_deserialize()` on log data during parsing. These run code the
  victim installed, the same code `inspect eval` loads. Step 3 limits what
  Inspect's own argument reconstruction builds; it does not audit what an
  installed factory does with ordinary string options (a plugin that treats
  an option as a path or model name is trusted installed code).
- What remains in run operations is the purpose of the operation: the task
  file, the solver file (retry), the model and its base URL, the sandbox,
  approval and review policies, and the ACP binding. Step 7 shows them; the
  credential and network items are under "Not this design".

The `@task` decorator filter in `load_file_tasks()` is not a security
boundary (any file can contain a decorated function); it only avoids
importing files that are not task files.

## Testing

All of these run in the default test job: no network, Docker or model
provider. The malicious-log fixtures use a marker module that records its
import (it appends to a file under `tmp_path`), and a spy that fails the test
if `inspect_ai.model._model.get_model` is called.

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
   a `@task` function and a scorer whose metric is defined only there.
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
  metrics for the hostile keys; fixture 2 raises `LookupError` with the step 2
  message; fixture 3 raises `ValueError` naming the option.
- `recover_eval_log()` and `recover_eval_log_async()` on a `started` copy of
  each fixture, once with a database sample buffer and once with a filestore
  buffer (the two sources in `_recover/_api.py:110`, built the way
  `tests/log/test_recover_write.py` and `test_recover_filestore.py` build
  them): fixture 1 recovers with results; fixtures 2 and 3 recover without
  results and log the warning. With a resolving `incomplete_action`, assert
  fixtures 2 and 3 do not finalize. The same through `inspect log recover`
  via `CliRunner`.
- `evals_df()` plus `prepare(model_info())` over a directory of logs with an
  unknown model name.
- `read_eval_log()`, `read_eval_log_headers()`, `inspect log dump`,
  `inspect info`, and the view server's `/logs/{log}` and `/log-headers`
  endpoints (with the FastAPI test client used by the existing view tests).

The fixture 1 and fixture 3 tests fail on `main` today (a marker is written,
`get_model` is called), so they are regression tests for steps 1 and 3.

Legitimate flows:

- `tests/scorer/test_score_editing.py`:
  `test_resolve_scorers_info_loads_task_file_metrics_once` passes
  `trust_log=True` and keeps asserting one import; add a
  `recompute_metrics(log, trust_log=True)` test with fixture 2's task-file
  metric, a test that a module imported by the caller first makes the default
  path work, a `grouped(accuracy(), ...)` recompute that passes step 3, and a
  registered custom metric taking a model (`mockllm/model`) that recomputes
  with `trust_log=True`.
- `tests/log/test_recover_api.py`: recovery with `trust_log=True` (and
  `--trust-log`) computes the task-file metric and the model-option metric,
  and a resolving recovery of such a log finalizes.
- `tests/test_eval_set.py`: an eval set with a task-file custom metric,
  interrupted so a `started` log with a buffer remains, resumes with the
  metric computed (proves eval-set needs no opt-in). A unit test on
  `resolve_previous_tasks()`: a `Task` declaring `sandbox="docker"` paired
  with fixture 4's logs resolves to `docker`, an explicit eval-level
  `sandbox="local"` is honoured, and a `str` task keeps the log's sandbox
  (resolution only, no Docker daemon).
- `tests/test_retry.py`: retry of a crashed log with a task-file metric
  recovers its metrics through both recovery calls (the threshold fallback
  included); retry with a `--solver path.py@name` log still loads the solver;
  the notice lists the task file, solver file and base URL.
- `tests/_eval/test_score.py`: a log scorer name of the form `<path>@<name>`
  is not imported and fails with the `--scorer` suggestion; an unregistered
  log scorer defined in the recorded task file loads when the task file is
  recorded cwd-relative in a subdirectory (`evals/task.py`) and imports a
  sibling module; a recorded scorer with an option named `name` (as in
  `test_scorer_from_spec_preserves_scorer_name_argument`) still reaches the
  factory, through both `eval.scorers` and the `results.scores` fallback;
  `--scorer path.py@name` still loads that file; the import notice is printed
  once with the absolute path; `--action overwrite` on a log whose
  `eval.metrics` holds a model-option metric still computes it.
- `tests/scorer/test_scorer.py` (or the file holding `eval_results` tests):
  `ScorerInfo.from_name()` returns the defaults for an unregistered name, the
  scorer's own metrics for a registered no-argument scorer (`match`,
  `includes`), and the defaults, without raising, for each core scorer that
  needs arguments (`pattern`, `answer`, `multi_scorer`, `precomputed_scores`,
  `_model_graded_qa_single`); and `eval_results()` with a solver-written
  `pattern` score key still computes.
- `tests/analysis/test_prepare.py`: `model_info()` still fills metadata for a
  database model, a `set_model_info()` model and a `model_info=` mapping.

Async tests (recovery, retry) run under both backends with `--runtrio` before
the PRs open, as the repo requires.

## Implementation plan

1. **Read paths import nothing by default** (steps 1, 2, 3). Files:
   `src/inspect_ai/_eval/loader.py` (`scorer_from_registry()`),
   `src/inspect_ai/_eval/task/results.py` (`from_name()`),
   `src/inspect_ai/_eval/score.py` (`resolve_scorers_info()`,
   `metrics_from_log_header()`, `metric_from_log()`,
   `check_log_metric_options()`; `score_async()` passes `trust_log=True`),
   `src/inspect_ai/log/_metric.py`, `src/inspect_ai/log/_score.py`,
   `src/inspect_ai/log/_recover/_api.py`, `src/inspect_ai/log/_recover/_write.py`,
   `src/inspect_ai/_cli/log.py`, `src/inspect_ai/_eval/eval.py` (both retry
   recovery calls pass `trust_log=True`), `docs/eval-logs.qmd` (the recompute example and a short
   "Logs from others" note), `CHANGELOG.md`, and the tests above for these
   paths, including `tests/log/test_untrusted_logs.py`.
2. **eval-set resume sandbox** (step 4). `src/inspect_ai/_eval/loader.py`,
   `tests/test_eval_set.py`, `CHANGELOG.md`.
3. **`inspect score` narrowing and run-operation notices** (steps 6, 7).
   `src/inspect_ai/_eval/loader.py` (`scorer_from_log()`),
   `src/inspect_ai/_eval/score.py` (`resolve_scorers()`),
   `src/inspect_ai/_cli/score.py`, `src/inspect_ai/_eval/eval.py`,
   `docs/scoring-workflow.qmd`, `tests/_eval/test_score.py`,
   `tests/test_retry.py`, `CHANGELOG.md`.
4. **`model_info()` direct lookup** (step 5).
   `src/inspect_ai/analysis/_prepare/model_info.py`,
   `tests/analysis/test_prepare.py`, the analysis tests in
   `tests/log/test_untrusted_logs.py`, `CHANGELOG.md`.

Steps 1 and 2 close the read-operation paths and should land first; 3 and 4
are independent of each other.

## Open questions

1. **Break now or deprecate first?** Step 2 makes recompute and recover raise
   (or warn, for recover) instead of importing the task file or rebuilding
   model-valued metric options, in the release that ships it.
   The alternative is one release that still imports but warns, then the
   change. Recommendation: break now with the actionable error; a
   warn-then-break release keeps the import it warns about, and the fix for
   affected users is one keyword.
2. **`model_info()` without provider resolution.** Recommendation: direct
   lookup only (step 5); the database covers common provider name formats,
   and the `model_info` argument covers the rest. The alternative keeps
   provider resolution for providers known not to download or start
   anything, a list that would need maintaining.
3. **Notice or confirmation for run operations.** Recommendation: notice only
   (step 7), since running the log's code is what the user asked for and
   confirmation breaks scripts. A confirmation (skipped with `--yes` or when
   stdin is not a TTY) would be the next step if notices prove too easy to
   miss.

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
