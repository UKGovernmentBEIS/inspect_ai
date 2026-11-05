# Eval sharding: the merge command

## Overview

`inspect log merge-shards LOG --task TASK` merges a sharded run's shard
logs into its merged log from the command line, so a shell launcher needs
no Python step. It is a thin layer over `merge_eval_log_shards()`: it
builds the task the way `inspect eval` builds it, from the same task
options (`TASK`, `-T`, `--model`, `--model-role`, `--epochs`, ...), parsed
by the same code and resolved through `eval()`'s own task resolution,
then passes that `Task` and the selection options (`--sample-id`,
`--sample-count`, `--allow-incomplete`) to the merge. The task is always
the one named on the command line; nothing is rebuilt from what the logs
record. Output is a short report, or with `--json` one JSON object on
stdout: the merged log's location, status and whether anything was
written, or an error envelope whose `kind` a launcher can branch on
(an incomplete set carries its missing ids and running and failed shards).

## Why

The merge exists only as a Python API that takes a built `Task`
([implementation plan, "Python API"](eval-sharding-implementation.md#python-api)).
A launcher written in shell has to run a Python step to merge, and a user
merging by hand writes one too. The parent design promises a CLI command
beside the API ([`eval-sharding.md`](eval-sharding.md), "The merge"), and
step 5b of the implementation plan leaves one problem for this design:
how the command gets its task. A task factory runs inside a construction
context (the active model, generate config and model roles, set before
the task's own `model`, `config` and `model_roles` apply), and the logs
record only the state after those overrides, so the command cannot rebuild
the task from the logs. It must get the context from the user.

## Goals and non-goals

Goals:

- One command, `inspect log merge-shards`, taking one `LOG` (the merged log
  or its shards directory) and `--json` (decisions: Ransom, 2026-10-21).
- The task built exactly as `inspect eval` builds it from the same
  options, by calling the code `inspect eval` calls, so a launcher can pass
  the merge the task options it gave its workers.
- Every parameter of the API on the command line: the selection as ids or
  a count, and writing an incomplete merged log.
- A machine-readable result and error envelope for launchers.

Non-goals:

- Any change to what the merge does, checks or writes. The command's
  guarantees are the API's: it compares the task's names with the shards,
  not its options ([implementation plan, "Matching the task"](eval-sharding-implementation.md#matching-the-task)).
- Rebuilding the task, its model or its roles from a log (decision:
  Ransom, 2026-11-04; see "Security").
- Resolving `inspect eval`'s sample selectors (`--limit`, `--sample-id`
  patterns) against the task's dataset. The command's selection options
  are the API's: exact ids or a count ("Not this design").
- Merging every shards directory under a log directory. The command takes
  one `LOG`, as the API does.
- Shard deletion (PR 9 of the implementation plan).

## Current behaviour

Verified by reading the code at `d5fac2c683` and by a throwaway spike (two
`inspect eval` workers on a two-task file with `mockllm/model`, then
`eval_init`, `eval_resolve_tasks`, `resolve_task_epochs` and
`merge_eval_log_shards` from a script, as the Design below calls them).

**The merge API** (`src/inspect_ai/log/_shards/_api.py`).
`merge_eval_log_shards_async` (`_api.py:156`) raises `TypeError` unless
`task` is a `Task`, then validates its arguments before any I/O:
`merge_paths(log)` (`_api.py:226`, `ValueError` for an unsupported or
recovered-log location), `given_selection(sample_ids, sample_count)`
(`_plan.py:113`, `ValueError` for both, an empty or string `sample_ids`,
or a count below 1) and `check_s3_location` on both paths (`_walk.py:44`,
`ValueError`). It then merges under the guard and returns a
`ShardMergeResult(log, written)`. Of the task it reads only `name`,
`scorer`, `metrics`, `epochs`, `epochs_reducer` and `headline_metric`
(`_write.py`), not the dataset. `ShardSetIncomplete` carries `status`,
`missing`, `running` and `failed`; `ShardSelectionError` (a
`ShardSetError`) carries `outside` (`_errors.py`). A task whose names
differ from the shards' raises plain `ShardSetError` (`check_task_matches`,
`_write.py:64`). The incomplete message ends "Pass allow_incomplete to
write an incomplete merged log." (`_api.py:507`).

**How `inspect eval` builds a task.** `eval_exec` (`_cli/eval.py:1952`)
parses `-T`/`--task-config` and `-M`/`--model-config` with
`parse_cli_config` (`_cli/util.py:172`), `--model-role` with
`parse_model_role_cli_args` (`_cli/util.py:186`), and the epochs options
inline (`_cli/eval.py:2114`): `Epochs(N, [] if --no-epochs-reducer else
create_reducers(...))` when `--epochs` is given, otherwise `None`, so
`--epochs-reducer` without `--epochs` is ignored. `eval_async` then calls
`eval_init` (`_eval/eval.py:2073`; logging and runtime context, model args
from `INSPECT_EVAL_MODEL_ARGS`, `resolve_models`) and `eval_resolve_tasks`
(`_eval/eval.py:2105`), which resolves and binds the model roles
(`init_model_roles`), makes each model active (`init_active_model(m,
config)`) and calls `resolve_tasks` (`_eval/loader.py:77`) to load the spec
and call the factory with the task args. `resolve_models` turns no model
into the `none` model (`model/_model.py:2626`); a provider model is
constructed then and needs its credentials (a spike: `openai/gpt-4o` with
no key raises `PrerequisiteError`; `mockllm/model` and `none` do not). The
run later applies an eval-level epochs override to the task
(`_eval/run.py:311-325`): the count replaces the task's, and a bare count
keeps the task's reducer. `resolve_task_epochs(task, epochs)`
(`_eval/task/task.py:619`) computes the same merge for callers outside the
run, and `task_with(task, epochs=...)` applies it, which is the recipe the
Sharding docs give for the API.

Spike results: `eval_resolve_tasks` resolves `two.py` to both tasks,
`two.py@alpha` to one, a missing file to `FileNotFoundError` and an unknown
name to `PrerequisiteError`; the factory sees the active model and the
task args. The script's merge wrote a `success` log, a second run wrote
nothing, and a run without the workers' `--epochs-reducer max` was refused
(`ShardSetError`, epoch reducers). Outside `eval()`, a factory that calls
`get_model()` with no active model and no `INSPECT_EVAL_MODEL` raises
`ValueError` ("No model specified"); after `eval_init(model=None)` it gets
the `none` model.

**The construction context in real tasks.** An AST survey of the 252
`@task` functions in inspect_evals (`~/git/inspect_evals/src`) for calls to
`get_model`, `active_model` or `active_generate_config` in the factory body
finds six that read the active model when built and none that read the
generate config: `browse_comp` (the default grader is the evaluated model),
`niah` (the tokenizer follows the model name), `instrumentaleval` and three
`gdm_stealth` tasks (graders built by name). None changes a scorer name or
a metric with the model. The merge reads no dataset, so a dataset that
depends on the model (`niah`) does not matter to it.

**The `inspect log` group** (`_cli/log.py`) holds `recover`, the other
command that writes a log; it takes `@common_options`, calls
`platform_init()` (hooks, exception hook) and prints its result with
builtin `print`. `inspect eval --json` redirects file descriptor 1 to
stderr for the run and writes its records to the saved stdout
(`_stdout_owned_for_json`, `_cli/eval.py:2366`). `inspect ctl` has a
`--json` error envelope `{"error": {kind, exception, message, status}}`
(`_cli/ctl/_failure.py`) whose kinds and classification are shaped for HTTP
transport errors. The CLI reference page `docs/reference/inspect_log.qmd`
is generated from the click commands.

## Design

### The command

```
inspect log merge-shards LOG --task TASK
    [-T arg=value ...] [--task-config FILE]
    [--model MODEL] [--model-base-url URL] [-M arg=value ...] [--model-config FILE]
    [--model-role role=model ...]
    [--epochs N] [--epochs-reducer NAMES] [--no-epochs-reducer]
    [--sample-id IDS | --sample-count N] [--allow-incomplete]
    [--json] [common options]
```

In `src/inspect_ai/_cli/log_merge_shards.py`, as `merge_shards_command`,
registered on the `log` group in `_cli/log.py` with
`log_command.add_command`. Its imports of the eval and merge machinery are
inside the command function, as in `recover`.

- `LOG`: passed to the merge unchanged; the API's forms and refusals apply
  (`<name>.eval` or `<name>.shards`; local path, `file://` URI or `s3://`
  URL).
- `--task TASK`, required: a task spec in `inspect eval`'s forms
  (`file.py`, `file.py@name`, a registered name, a directory). It is an
  option, not a second positional argument, so `LOG` and the task cannot
  be swapped by accident. There is no default: the command never takes the
  task from the logs (`eval.task_file`).
- The task options, shared with `inspect eval` (below): `-T`,
  `--task-config`, `--model`, `--model-base-url`, `-M`, `--model-config`,
  `--model-role`, `--epochs`, `--epochs-reducer`, `--no-epochs-reducer`.
  They mean what they mean to `inspect eval`, read the same
  `INSPECT_EVAL_*` environment variables, and a launcher passes the values
  it gave its workers. Pass `--model`, `--model-role` and `-M` when the
  task reads them while it is built; they also set the model context the
  merge's metrics and reducers run in. A model given here is constructed,
  as `inspect eval` constructs it, and needs its provider's credentials.
  Without `--model` (and without `INSPECT_EVAL_MODEL`) the task is built
  with the `none` model active, as `inspect eval` would build it.
- `--sample-id IDS`: the intended selection as exact sample ids, comma
  separated (`parse_sample_id`), compared with the shards' ids as text.
  Unlike `inspect eval --sample-id` these are not patterns and take no
  `task:` prefix; a pattern is merged as a literal id, so the merge refuses
  it (the shards hold ids outside the selection, or the selection's id is
  missing). An empty id (`1,,2`, or an empty value) is refused before the
  task is built. `--sample-count N`: the intended selection as a number of
  samples. Neither reads an environment variable: `INSPECT_EVAL_SAMPLE_ID`
  is a worker's own selection, not the run's. Both given, or a count below
  1, is refused by the API's own check (below).
- `--allow-incomplete`: the API's `allow_incomplete`.
- `--json`: one JSON object on stdout ("Output").
- `@common_options`, as `recover` takes them: `--log-level`, `--env`,
  `--display`, `--traceback-locals`, `--debug`, `--debug-errors`. Its
  `--log-dir` has no meaning here: given on the command line it is refused
  (`invalid_arguments`, "pass the merged log or its shards directory as
  LOG"); from `INSPECT_LOG_DIR` it is ignored, as `inspect log recover`
  ignores it when given a log.

Options `inspect eval` has and this command does not (solver, sandbox,
limits, approval, generate config, `--limit`, `--sample-shuffle`, ...) are
not accepted, so passing one is click's "no such option" error.

### Sharing the options with `inspect eval`

The shared options are defined once. `_cli/eval.py` gains four decorators,
`model_options` (`--model`, `--model-base-url`, `-M`, `--model-config`),
`model_role_option` (`--model-role`), `task_args_options` (`-T`,
`--task-config`) and `epochs_options` (`--epochs`, `--epochs-reducer`,
`--no-epochs-reducer`), each holding the existing `click.option` calls
unchanged. `eval_options` applies them where those options stand today, so
`inspect eval`, `inspect eval-set` and every other user of `eval_options`
keep the same options, help text, order and environment variables.

The epochs block of `eval_exec` moves into
`parse_epochs_options(epochs, epochs_reducer, no_epochs_reducer) ->
Epochs | None` in `_cli/eval.py`, which `eval_exec` calls in its place, so
the command reads these options exactly as `inspect eval` does, including
ignoring `--epochs-reducer` without `--epochs`.

### Building the task

After the common options are processed and `platform_init()` has run (as
in `recover`; it loads hooks, such as one that supplies API keys):

1. **Check the merge arguments first.** The first checks of
   `merge_eval_log_shards_async` after the `TypeError` check (`merge_paths`,
   `given_selection`, `check_s3_location` on both paths) move into
   `check_merge_arguments(log, sample_ids, sample_count) ->
   MergeArguments` in `_api.py` (a `NamedTuple` of the `MergePaths` and
   the given `Selection`), which the API calls in their place and uses the
   result of, and the command calls before building the task. A bad `LOG` or selection is then refused
   before any task code is imported or any model constructed, by the same
   code that would refuse it later.
2. **Parse the task options** as `eval_exec` does: `parse_cli_config(t,
   task_config)`, `parse_cli_config(m, model_config)`,
   `parse_model_role_cli_args(model_role)`, `parse_epochs_options(...)`.
3. **Resolve the model and the task through `eval()`'s path.**
   `eval_init(model=model, model_base_url=model_base_url,
   model_args=model_args, log_level=log_level)`, then
   `eval_resolve_tasks(task, task_args, models, model_roles,
   GenerateConfig(), None, None, None)` (approval, sandbox and shuffle
   unset). This binds the roles and makes the model active before the
   factory runs, exactly as for `inspect eval`, and warns about `-T`
   arguments the factory does not take.
4. **Refuse what is not one task.** More than one model (`--model a,b`)
   is refused before `eval_resolve_tasks`: a merge has one task. A spec
   that resolves to no task, or to several (`file.py` with two `@task`
   functions), is refused naming them and asking for `file.py@name`. A
   `TaskSource` spec is refused by `resolve_tasks` itself.
5. **Apply the epochs override** as the run does: when
   `parse_epochs_options` returned an `Epochs`, `task = task_with(task,
   epochs=resolve_task_epochs(task, epochs))`, so `--epochs N` alone keeps
   the task's reducer, `--epochs-reducer` replaces it and
   `--no-epochs-reducer` disables reduction. This is the recipe the
   Sharding docs give API callers.
6. **Merge**: `merge_eval_log_shards(LOG, task, sample_ids=...,
   sample_count=..., allow_incomplete=...)`. The model and roles made
   active in step 3 are the caller's model context the merge runs metrics
   and reducers in; `run_coroutine` copies the context into its event loop
   (verified on asyncio and Trio: a coroutine run through it sees the
   model `init_active_model` set).

The task's own `model`, `config` and `model_roles` are not made active for
the merge, as they are for a native run's scoring: no surveyed metric or
reducer reads the model, and the API's context rule ("caller's model
context") is kept as is.

Building the task can be slow (a factory that downloads its dataset) and
happens before the merge reads anything, so a missing shards directory or
a held lock is reported after it. Checking for them first would duplicate
the merge's own reads, under no lock.

### Output

Without `--json`, on stdout, with builtin `print` (no Rich markup, so a
bracket in a log-derived name prints as written):

```
Merged 3 shards into /work/logs/2026-10-16T10-00-00-00-00_mytask_RLGk3vGh7Az.eval
  status: success
```

or, when nothing was written, `No changes since the last merge:
<location>` and the same status line. The shard count is the length of the
merged header's ledger (`eval.shards.ledger`). Exit code 0, including for a
`started` or `error` log written with `--allow-incomplete`.

With `--json`, one JSON object on stdout and nothing else:

```json
{"location": "/work/logs/<name>.eval", "status": "success", "written": true,
 "task": "mytask", "task_id": "RLGk3vGh7Az", "eval_id": "...", "shards": 3}
```

`location`, `status`, `task`, `task_id` and `eval_id` are the fields of a
log entry in `inspect eval --json`'s `done` record, taken from the
returned header; `written` and `shards` are the merge's. The command runs
everything (task import, factory, model construction, merge) inside
`_stdout_owned_for_json` from `_cli/eval.py`, so a factory's `print`, a
warning or a subprocess writes to stderr, and the object is written to
the saved stdout. The display is set to `none`, as `inspect eval --json`
sets it.

### Errors

Every failure after click has parsed the command line exits 1. Without
`--json` the message goes to stderr (`click.echo(..., err=True)`); with
`--json` it also goes to stderr and stdout carries the envelope:

```json
{"error": {"kind": "incomplete",
           "exception": "inspect_ai.ShardSetIncomplete",
           "message": "The shards of ... are incomplete (1 selected samples not held). ...",
           "incomplete": {"status": "started", "missing": ["7"], "running": [], "failed": ["2"]}}}
```

The shape follows ctl's envelope (`kind`, `exception`, `message`; ctl's
`status` is an HTTP status and is left out), with `exception` named as
ctl names it (`_exception_name`, imported from `_cli/ctl/_failure.py`).
The kinds are classified by the phase that failed and the exception type,
so an error from the task's own code never reads as a merge refusal:

| `kind` | Raised by | Extra field |
|---|---|---|
| `invalid_arguments` | `check_merge_arguments` (`ValueError`), an empty `--sample-id` entry, `--log-dir` on the command line | |
| `task` | steps 2 to 5: an unreadable `--task-config` or `--model-config`, a task spec not found, a factory that raises, a model or role that cannot be constructed (a missing API key's `PrerequisiteError`), no task, several tasks, several models, a `TaskSource` | |
| `not_found` | the merge's `FileNotFoundError`: neither the merged log nor any shard exists | |
| `incomplete` | `ShardSetIncomplete` | `incomplete`: `status`, `missing` (`null` for a count or no selection), `running`, `failed` |
| `outside_selection` | `ShardSelectionError` | `outside` (`null` for a count) |
| `refused` | any other `ShardSetError`, including a task that does not match the shards | |
| `conflict` | `WriteConflictError`: another merge holds the lock or published first; re-run later | |
| `storage_error` | any other `OSError`, or a botocore error, from the merge | |
| `internal` | anything else from the merge (a metric or reducer that raises); its traceback goes to stderr | |

Click's own errors (an unknown option, a missing `--task`, a non-integer
`--sample-count`) exit 2 with click's usage message and no envelope, as in
`inspect ctl`. Ctrl-C passes through: the merge's own cancellation handling
releases its lock and writes nothing, and no envelope is printed.

The incomplete message the API raises names the Python argument; it
becomes "Pass allow_incomplete (--allow-incomplete on the command line) to
write an incomplete merged log." so the same text serves both callers.

The whole command body runs inside one context manager,
`_merge_failures(json_output)`, that does the classification and printing,
and the module raises no `click.exceptions.Exit`, `ClickException` or
`SystemExit` of its own; a test pins that (as
`test_no_bare_click_exit_in_ctl_error_sites` does for ctl).

### Documentation

`docs/sharding.qmd`, "Merging", gains the command beside the Python
example: a shell launcher runs `inspect log merge-shards
logs/<name>.eval --task mytask.py -T ...` with the task options it gave
its workers, minus each worker's `--sample-id` or `--limit` and
`--log-dir`. The page says which options are accepted and that they mean
what they mean to `inspect eval`; that `--sample-id` takes exact ids, not
patterns; that `--model` and `--model-role` are needed only if the task
reads them when built, and need credentials; the exit codes; and the
`--json` object and envelope with its kinds. The sentence "A shell
launcher runs this as a short Python step" is replaced by the command. The
`--help` text of the command carries the option descriptions; the CLI
reference page picks the command up from click.

## Alternatives considered

- **Rebuild the task from the logs** (the recorded `task_file`,
  `task_args`, model and roles, as `eval_retry` does, or through
  `inspect log export-config`'s run config). Needs no task options, but
  the construction context before the task's own overrides is not in the
  logs, so a rebuilt factory can build other metrics under the same names;
  and it imports a file a log names and builds a model from log values,
  which the merge, a read operation in
  [`malicious-log-code-execution.md`](malicious-log-code-execution.md),
  never does. Rejected (decision: Ransom, 2026-11-04).
- **Accept all of `inspect eval`'s options and pair by `task_identifier`**,
  as `eval_set()` pairs a task with its logs. The strongest check (task
  args, model, solver, generate config and limits all compared), but the
  user must repeat the workers' whole command line, including options
  the merge never uses, and each worker's own `--sample-id`, `--limit` and
  `--log-dir` would have to be told apart from the run's. The command
  would accept dozens of options with no effect, and the check goes beyond
  the API's names-only contract. Rejected for the subset that builds the
  task.
- **Copy the option definitions** into the new module instead of sharing
  decorators. No change to `_cli/eval.py`, but two definitions of each
  option drift (help, environment variables, parsing); sharing is the
  reuse the Design asks for.
- **Expand eval-style selectors against the task's dataset** (`--limit
  10-20`, `--sample-id` patterns and `task:` prefixes, through
  `slice_dataset`). The selection would mean what it meant to the workers,
  but it brings `--sample-shuffle` and the dataset into the command and
  gives the same option two meanings depending on the shards. Launchers
  already hold the exact ids. Deferred ("Not this design").
- **TASK as a second positional argument** (`merge-shards LOG TASK`,
  closer to `inspect eval TASK`). Shorter, but two path-like positional
  arguments are easy to swap; `inspect score LOG --scorer` sets the
  precedent for an option.
- **Distinct exit codes** (for example 3 for an incomplete set), so a shell
  loop can wait for workers without parsing JSON. Not taken: `--json`
  gives the reason, and a polling loop is the launcher's job, which the
  docs describe with `--allow-incomplete` or the envelope's `kind`.
- **Reuse ctl's `_structured_failures`.** Its kind vocabulary and
  `_classify` are for HTTP transport errors (an `OSError` is
  `connect_error`); the merge's failures are not. Only the envelope's shape
  and `_exception_name` are shared.

## Compatibility and migration

No migration required.

- New command `inspect log merge-shards`; nothing else in the `log` group
  changes.
- `inspect eval` and `inspect eval-set`: no change in options, help, order,
  environment variables or parsing. The options move into decorators and
  the epochs parsing into a helper, both called from where the inline code
  was.
- `merge_eval_log_shards()`: same signature, checks and errors; its
  argument checks run through `check_merge_arguments`, in the same order.
  The incomplete message's last sentence names `--allow-incomplete` too.
- No stored format, schema or viewer type changes.

## Security

- **The task comes from the command line only.** `--task` is required and
  has no default; the command never reads `eval.task_file`, `task_args`,
  the model, its arguments or its roles from a shard or merged log. It
  imports the file the user names, as `inspect eval` does, and constructs
  only the models the user names. Hooks load through `platform_init()` as
  for `inspect eval` and `inspect log recover`.
- **Shard logs are untrusted input, handled by the API.** The command adds
  no read of them; validation, the guards and the metric trust rules are
  the merge's ([implementation plan, "Security"](eval-sharding-implementation.md#security)).
- **Log-derived text in the output.** The location, task name and error
  messages (which name shard files) are printed with builtin `print` and
  `click.echo`, never through Rich markup, and encoded with `json.dumps`
  under `--json`. Control characters in a local shard file name reach the
  terminal unchanged, as they do from `inspect log list` ("Not this
  design").
- **Environment.** The shared options read `INSPECT_EVAL_*` variables,
  which the user controls, as for `inspect eval`.

## Testing

In `tests/log/test_shards.py`, beside the API's merge tests, through
`click.testing.CliRunner` on the `inspect` group, with `mockllm/model`. No
network, Docker or provider keys. Each test writes a task file to
`tmp_path` and runs the workers with `eval("<tmp>/t.py@name", ...)` into
`<name>.shards/<k>/`, then runs the command.

- **The command equals the API.** Two shards of a sample-id selection:
  the command's merged results and reductions equal a native unsharded
  run's, and equal the API's merge of the same shards with the same task;
  a second run prints "No changes" with `written: false`.
- **The construction context reaches the factory.** A factory that picks
  its metric by `get_model().name` merges with `--model mockllm/model`
  and is refused (`refused`, metric names) without it; one that reads
  `get_model(role="grader")` merges with `--model-role
  grader=mockllm/model`; one whose scorer name depends on a `-T` argument
  merges with it and is refused without it. A factory that calls
  `get_model()` with no `--model` and no `INSPECT_EVAL_MODEL` gets the
  `none` model.
- **Environment variables.** `INSPECT_EVAL_TASK_ARGS` and
  `INSPECT_EVAL_EPOCHS` set in the environment build the same task as the
  flags; `INSPECT_EVAL_SAMPLE_ID` set in the environment does not become
  the selection.
- **Epochs.** Workers run with `--epochs 2`, `--epochs 2 --epochs-reducer
  max` and `--epochs 2 --no-epochs-reducer` over a task with its own
  reducer merge with the same flags to the native results, and each is
  refused with the flags of another (`refused`, epoch reducers).
- **Selection and incomplete sets.** `--sample-id` and `--sample-count`
  merge as the API's `sample_ids` and `sample_count`; both together, a
  count of 0 and an empty id are `invalid_arguments`, with a marker the
  task file writes on import absent (the task was never built). A missing
  shard is `incomplete` with exit 1 and its `missing` ids; with
  `--allow-incomplete` the command writes a `started` log and exits 0. A
  pattern (`--sample-id 'a*'`) is refused as `outside_selection`.
- **Task errors.** A file with two tasks, a spec with no task, a missing
  file, a factory that raises, `--model a,b`, and `--model openai/gpt-4o`
  with no `OPENAI_API_KEY` are each `task`, with every file in the log
  directory byte-identical.
- **Merge errors.** A held lock file is `conflict`; no merged log and no
  shards is `not_found`; a recovered-log `LOG` is `invalid_arguments`
  before the task file is imported; `--log-dir` on the command line is
  `invalid_arguments`; a metric that raises is `internal` with its
  traceback on stderr.
- **`--json` owns stdout.** With a factory that prints and a metric that
  logs a warning, stdout parses as exactly one JSON object, on success and
  on each error kind above; stderr holds the print and the warning.
- **Storage.** One `s3://` merge through the `mock_s3` fixture (moto, no
  network).
- **Trio.** The equality test is parametrized over `INSPECT_ASYNC_BACKEND`
  (`asyncio`, `trio`, set with `monkeypatch`); the `[trio]` variant runs
  under `--runtrio` like the other trio variants.
- **Guards.** A test asserts that `log_merge_shards.py` raises no
  `click.exceptions.Exit`, `ClickException` or `SystemExit` outside
  `_merge_failures`. The existing `tests/_cli` suite covers `inspect eval`'s
  options after the refactor, and the implementation PR reports that
  `inspect eval --help` and `inspect eval-set --help` are unchanged.

## Implementation plan

One PR, after PR 5 and before PR 6 of the
[implementation plan](eval-sharding-implementation.md#implementation-plan),
titled as a `feat:` (the title is the changelog line; no CHANGELOG edit),
in three commits:

1. **Shared pieces, no behaviour change.** `model_options`,
   `model_role_option`, `task_args_options`, `epochs_options` and
   `parse_epochs_options` in `src/inspect_ai/_cli/eval.py`, used by
   `eval_options` and `eval_exec`; `check_merge_arguments` in
   `src/inspect_ai/log/_shards/_api.py`, used by
   `merge_eval_log_shards_async`; the incomplete message names
   `--allow-incomplete`. Files: those two, `tests/log/test_shards.py` (the
   message assertion, if one matches it).
2. **The command.** `src/inspect_ai/_cli/log_merge_shards.py`
   (`merge_shards_command`, `_merge_failures`), registered in
   `src/inspect_ai/_cli/log.py`; the tests above in
   `tests/log/test_shards.py`.
3. **Docs.** `docs/sharding.qmd`.

## Open questions

- **Should the command take `inspect eval`'s generate config options?**
  Recommendation: no. Step 5b names the generate config as part of the
  construction context, but no surveyed task factory reads it (the six
  that read the active model use its name, its API or none of it), and
  the generate options are about forty flags plus `--generate-config`. Not
  taking them keeps the command small, and passing one is a loud "no such
  option". If a task that reads them turns up, `--generate-config FILE`
  can be added and passed to `eval_init` and `eval_resolve_tasks`.
  Confidence: high

## Not this design

- Expanding `inspect eval`'s sample selectors (`--limit` ranges,
  `--sample-id` patterns, `task:` prefixes, with `--sample-shuffle`)
  against the task's dataset for the merge's selection. PR 6 computes
  `eval_set()`'s selection from the task's dataset; the command could
  share that helper later.
- A directory-wide merge (`inspect log merge-shards --log-dir`).
- A `--delete-shards` option: shard deletion is PR 9.
- Sanitizing control characters in log-derived names that `inspect log`
  commands print.
