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

- Any change to what the merge does, checks or writes, with one
  exception: an id selection is recorded in `eval.dataset.sample_ids` in
  its given order with the held samples' typed ids, and an id no shard
  holds as given ("The command", `--sample-id`). The command's
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
write an incomplete merged log." (`_api.py:507`). The merge raises
`FileNotFoundError` in two cases: neither the merged log nor any shard
attempt exists (`_api.py:325`), or an attempt the merge listed is removed
before it is read (`_read_attempts` and `_read_attempt`, `_api.py:527-545`,
propagate it), which happens when a worker's retry cleanup removes a
superseded attempt (`_eval/evalset.py:2035-2053`) while the newer attempt
remains.

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
constructed then and needs its credentials (`openai/gpt-4o` with no key
raises `PrerequisiteError`; `mockllm/model` and `none` need none). The
run later applies an eval-level epochs override to the task
(`_eval/run.py:311-325`): the count replaces the task's, and a bare count
keeps the task's reducer. `resolve_task_epochs(task, epochs)`
(`_eval/task/task.py:619`) computes the same merge for callers outside the
run, and `task_with(task, epochs=...)` applies it, which is the recipe the
Sharding docs give for the API.

`eval_resolve_tasks` resolves a file holding two tasks to both of them,
`file.py@name` to one, a missing file to `FileNotFoundError` and an unknown
name to `PrerequisiteError`; the factory sees the active model and the
task args. Outside `eval()`, a factory that calls `get_model()` with no
active model and no `INSPECT_EVAL_MODEL` raises `ValueError` ("No model
specified"); after `eval_init(model=None)` it gets the `none` model. A
merge of shards run with `--epochs-reducer max`, given a task without
that reducer, is refused (`ShardSetError`, epoch reducers).

**Model specs and run configs.** `inspect eval` also takes the model as
`--model-spec` (`INSPECT_EVAL_MODEL_SPEC`; model, base URL, model args and
generate config in one value, `docs/models.qmd`) and a whole run as
`--run-config` (`INSPECT_EVAL_RUN_CONFIG`; task, task args, model, model
args, roles, generate config, solver and eval config, `docs/tasks.qmd`,
"Run Config"). `eval_exec` resolves both before any task is built
(`parse_run_config`, `merge_run_config_params` and `resolve_model_spec`,
`_cli/eval.py:1842-1948`, called at `_cli/eval.py:2046-2061`). A spec from
the environment yields to a single-model option typed on the command line
(`--model`, `--model-base-url`, `--model-config`, `-M`) and otherwise
replaces the model; a run config supplies the fields it holds.

**Environment bindings.** The `inspect` group runs with
`auto_envvar_prefix="INSPECT"` (`_cli/main.py:62`), so an option without
an explicit `envvar` also reads `INSPECT_<COMMAND>_<OPTION>`: for
`inspect eval` that is `INSPECT_EVAL_...`, for `inspect eval-set`
`INSPECT_EVAL_SET_...`, and for a `log` subcommand
`INSPECT_LOG_<SUBCOMMAND>_...`. Of the options this design shares, all but
`--model-base-url` (`_cli/eval.py:290`) name their `INSPECT_EVAL_*`
variable explicitly; `--model-base-url` reads `INSPECT_EVAL_MODEL_BASE_URL`
under `inspect eval` and `INSPECT_EVAL_SET_MODEL_BASE_URL` under
`inspect eval-set` through the prefix alone. Providers fall back to
`INSPECT_EVAL_MODEL_BASE_URL` only after their own variables such as
`OPENAI_BASE_URL` (`model_base_url`,
`model/_providers/util/util.py:38-50`), so an unbound option does not keep
eval's precedence. A named `envvar` does not turn the automatic lookup
off: click reads the named variable first and, when it is unset or empty,
the automatic one (`Option.resolve_envvar_value`, click 8.4.2), so
`inspect eval-set --model` reads `INSPECT_EVAL_MODEL` and then
`INSPECT_EVAL_SET_MODEL`. Only `allow_from_autoenv=False` removes the
fallback (`--notification`, `_cli/eval.py:416`; ctl's `--log-dir`,
`_cli/ctl/_group.py:240`). The common options all name their variables
(`INSPECT_LOG_DIR`, `INSPECT_LOG_LEVEL`, `INSPECT_DISPLAY`, ...) and keep
the same fallback.

**The construction context in real tasks.** Of the 252 `@task` functions
in inspect_evals, six call `get_model` or `active_model` in the factory
body and none calls `active_generate_config`: `browse_comp` (the default grader is the evaluated model),
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
  `INSPECT_EVAL_*` environment variables as under `inspect eval`, with
  click's automatic fallback ("Environment bindings" below), and a
  launcher passes the values it gave its workers. Pass `--model`,
  `--model-role` and `-M` when the task reads them while it is built; they also set the model context the
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
  task is built. The ids arrive as text (`parse_sample_id`), but the merged
  log records the shards' typed ids: `build_header` (`_plan.py`) maps each
  id of an id selection to the id of the merged sample with the same text,
  as it already does for a count or no selection, and keeps an id no shard
  holds (an `--allow-incomplete` merge) as given until a later merge holds
  it. A dataset with integer ids therefore records `eval.dataset.sample_ids`
  as `[1, 2]`, as a native run and an API merge given `[1, 2]` do, not
  `["1", "2"]`, so typed readers (the `dataset_sample_ids` dataframe
  column, `KnownKey.sample_id` in `_control/log_dir/select.py`) see the
  same type. The change is in the API, so a Python caller that passes text
  ids gets the same header. `--sample-count N`: the intended selection as a number of
  samples. Neither reads an environment variable (below):
  `INSPECT_EVAL_SAMPLE_ID` is a worker's own selection, not the run's. Both
  given, or a count below 1, is refused by the API's own check (below).
- `--allow-incomplete`: the API's `allow_incomplete`.
- `--json`: one JSON object on stdout ("Output").
- `@common_options`, as `recover` takes them: `--log-level`, `--env`,
  `--display`, `--traceback-locals`, `--debug`, `--debug-errors`. Its
  `--log-dir` has no meaning here: given on the command line it is refused
  (`invalid_arguments`, "pass the merged log or its shards directory as
  LOG"); from the environment (`INSPECT_LOG_DIR`, or the automatic
  `INSPECT_LOG_MERGE_SHARDS_LOG_DIR`) it is ignored, as `inspect log
  recover` ignores `INSPECT_LOG_DIR` when given a log. "On the command
  line" is `ctx.get_parameter_source("log_dir") ==
  ParameterSource.COMMANDLINE`, the test `resolve_model_spec` uses.

Options `inspect eval` has and this command does not (solver, sandbox,
limits, approval, `--limit`, `--sample-shuffle`, ...) are not accepted, so
passing one is click's "no such option" error. That includes the generate
config options (`--generate-config` and the individual generation flags):
the task is built with a fresh `GenerateConfig()` (decision: Ransom,
2026-11-05). No surveyed task factory reads the active generate config
when built; `--generate-config FILE` can be added, and passed to
`eval_init` and `eval_resolve_tasks`, if one turns up. Generate config
environment variables (`INSPECT_EVAL_GENERATE_CONFIG`, `INSPECT_EVAL_MAX_TOKENS`,
...) are not read.

**Model specs and run configs** are not accepted either: `--model-spec`
and `--run-config` are "no such option". A run launched with them merges
with the equivalent flags: a spec's `model`, `base_url` and model args as
`--model`, `--model-base-url` and `-M` (its generate config is not
needed, above); a run config's `task` and its arguments, `model` with
its arguments and base URL, `model_roles`, and the `epochs` and
`epochs_reducer` of its `eval_config` as `--task`, `-T`, `--model`, `-M`,
`--model-base-url`, `--model-role`, `--epochs` and `--epochs-reducer`.
A run config overrides epochs only when its `eval_config` holds an
`epochs` count: `RunConfigInput.to_params()` drops `epochs_reducer`
without one (`_cli/eval.py:1804-1811`), so such a config translates to
neither `--epochs` nor `--epochs-reducer`, and the task's own epochs and
reducer stand. With a count, a non-empty `epochs_reducer` is `--epochs N
--epochs-reducer R`, and an empty one (`[]`, reduction disabled) is
`--epochs N --no-epochs-reducer`: `--epochs-reducer` takes reducer names,
an empty value is not one, and leaving the flag out keeps the task's own
reducer. The values are the ones the launcher gave its workers, taken from its own
command line or the original spec or run config, including the model
roles it passed. `inspect log export-config` of a shard log is not a
substitute: it exports the model, arguments and roles recorded after
task resolution applied the task's own model and role defaults
(`log/_config.py:46-77`, `_eval/loader.py:110-125`), so a factory built
under `--model mockllm/incoming` that returns a task on
`mockllm/execution` exports the latter, and rebuilding from it can build
a different metric under the same name, which the names-only check
accepts. Their environment
variables would change the task `inspect eval` builds, so the command
refuses them rather than ignore them (`invalid_arguments`, before the task
is built, naming the variable and the flags to use instead):
`INSPECT_EVAL_RUN_CONFIG` whenever it is set and non-empty, and
`INSPECT_EVAL_MODEL_SPEC` when it is set and non-empty and no single-model
option (`--model`, `--model-base-url`, `--model-config`, `-M`) is typed on
the command line, the case where `inspect eval` would let the spec replace
the model.

**Environment bindings.** The five options only this command has are
command-line only; the shared and common options keep click's normal
lookup, as they have under `inspect eval` and `inspect eval-set`:

- `--task`, `--sample-id`, `--sample-count`, `--allow-incomplete` and
  `--json` set `allow_from_autoenv=False` and name no variable, so no
  environment variable, named or automatic, supplies the task, the
  selection or the output form.
- The shared task options read the variable `inspect eval` reads and,
  when it is unset or empty, click's automatic
  `INSPECT_LOG_MERGE_SHARDS_<OPTION>` (`INSPECT_LOG_MERGE_SHARDS_MODEL`,
  `INSPECT_LOG_MERGE_SHARDS_T` for `-T`, ...), as eval-set's read
  `INSPECT_EVAL_SET_<OPTION>` after their `INSPECT_EVAL_*` name. The named
  variable wins when both are set. For `--model-base-url`, the shared
  decorator takes the envvar as a parameter: `eval_options` passes none, keeping the prefix bindings
  `INSPECT_EVAL_MODEL_BASE_URL` (eval) and
  `INSPECT_EVAL_SET_MODEL_BASE_URL` (eval-set) unchanged, and the merge
  command passes `INSPECT_EVAL_MODEL_BASE_URL`, so the option, not the
  provider's fallback, supplies it and it wins over `OPENAI_BASE_URL` as
  under `inspect eval`.
- The common options keep their named variables and the same automatic
  fallback (`INSPECT_LOG_MERGE_SHARDS_LOG_LEVEL`, ...).

The decorators are not changed to turn the fallback off: that would
change `inspect eval` and `inspect eval-set`, whose users can set the
automatic names today, and those names are as much the user's as the
named ones. What the command must not do is take the task or the
selection from the environment, and the five command-line-only options
ensure it.

### Sharing the options with `inspect eval`

The shared options are defined once. `_cli/eval.py` gains four decorators,
`model_options` (`--model`, `--model-base-url`, `-M`, `--model-config`),
`model_role_option` (`--model-role`), `task_args_options` (`-T`,
`--task-config`) and `epochs_options` (`--epochs`, `--epochs-reducer`,
`--no-epochs-reducer`), each holding the existing `click.option` calls
unchanged except that `model_options` takes
`model_base_url_envvar: str | None = None` for `--model-base-url`
("Environment bindings" above). `eval_options` applies them, with no
envvar, where those options stand today, so `inspect eval`,
`inspect eval-set` and every other user of `eval_options` keep the same
options, help text, order and environment variables.

The epochs block of `eval_exec` moves into
`parse_epochs_options(epochs, epochs_reducer, no_epochs_reducer) ->
Epochs | None` in `_cli/eval.py`, which `eval_exec` calls in its place, so
the command reads these options exactly as `inspect eval` does, including
ignoring `--epochs-reducer` without `--epochs`.

### Building the task

After the common options are processed and `platform_init()` has run (as
in `recover`; it loads hooks, such as one that supplies API keys), both
inside the `--json` boundary ("Output"):

1. **Check the merge arguments first.** The first checks of
   `merge_eval_log_shards_async` after the `TypeError` check (`merge_paths`,
   `given_selection`, `check_s3_location` on both paths) move into
   `check_merge_arguments(log, sample_ids, sample_count) ->
   MergeArguments` in `_api.py` (a `NamedTuple` of the `MergePaths` and
   the given `Selection`), which the API calls in their place and uses the
   result of, and the command calls before building the task. A bad `LOG`
   or selection is then refused before any task code is imported or any
   model constructed, by the same code that would refuse it later. The
   environment refusals for `INSPECT_EVAL_RUN_CONFIG` and
   `INSPECT_EVAL_MODEL_SPEC` ("The command") run here too.
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
   and reducers in; `run_coroutine` copies the context into its event
   loop, so a coroutine run through it sees the model `init_active_model`
   set, on asyncio and on Trio.

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
returned header; `written` and `shards` are the merge's.

Under `--json` the first statement of the command body enters
`_stdout_owned_for_json` from `_cli/eval.py`, and `_merge_failures`
("Errors") inside it, so everything after click has parsed the command
line runs in one boundary: `process_common_options`, `platform_init()`,
the task import, the factory, model construction and the merge. Inside
it a `print`, a warning or a subprocess writes to stderr, and the object
or the envelope is written to the saved stdout. `platform_init()` must be
inside: `init_hooks()` prints its `inspect_ai vX` / `hooks enabled: N`
banner through Rich's `print` to stdout whenever a registry or legacy
hook is enabled (`hooks/_startup.py:31-37`), and the display type does
not quiet Rich at that point (`init_display_type` only records it).
Before `process_common_options` runs, the command sets `display` to
`none` and `no_ansi` to `None` in the common options, as `inspect eval
--json` does (`_cli/eval.py:1257-1260`). Without `--json` the command
body runs in `_merge_failures` alone and stdout is not redirected.

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
| `setup` | the command's setup before step 1, `process_common_options` and `platform_init()`: an `--env` value that cannot be parsed, a debugger that cannot listen, a hook that fails to load | |
| `invalid_arguments` | `check_merge_arguments` (`ValueError`), an empty `--sample-id` entry, `--log-dir` on the command line, `INSPECT_EVAL_RUN_CONFIG` or `INSPECT_EVAL_MODEL_SPEC` in the environment | |
| `task` | steps 2 to 5: an unreadable `--task-config` or `--model-config`, a task spec not found, a factory that raises, a model or role that cannot be constructed (a missing API key's `PrerequisiteError`), no task, several tasks, several models, a `TaskSource` | |
| `not_found` | the merge's `FileNotFoundError`: a file the merge needed was missing. Either neither the merged log nor any shard attempt exists, or an attempt the merge listed was removed before it was read (a worker's retry cleanup removing a superseded attempt); the message says which. In the second case running the merge again, once the workers have exited, reads the attempt that replaced it | |
| `incomplete` | `ShardSetIncomplete` | `incomplete`: `status`, `missing` (`null` for a count or no selection), `running`, `failed` |
| `outside_selection` | `ShardSelectionError` | `outside` (`null` for a count) |
| `refused` | any other `ShardSetError`, including a task that does not match the shards | |
| `conflict` | `WriteConflictError`: another merge holds the lock or published first. A live merge's lock, or a lost S3 conditional upload, clears: re-run once the other merge has finished. A lock left by a local merge that crashed does not, and every re-run is refused until it is removed: the message names the host and process that held it; check that process has stopped, delete the lock file and re-run (`docs/sharding.qmd`, "Merging") | |
| `storage_error` | any other `OSError`, or a botocore error, from the merge | |
| `internal` | anything else from the merge (a metric or reducer that raises); its traceback goes to stderr | |

Click's own errors (an unknown option, a missing `--task`, a non-integer
`--sample-count`) exit 2 with click's usage message and no envelope, as in
`inspect ctl`. Ctrl-C passes through with no report and no envelope,
and the merge's own cancellation handling releases its lock. What it
leaves depends on when it lands. Before publication, the merged log is
unchanged. During publication the outcome is the merge API's, unchanged
here: a local replacement runs in an owned worker that finishes before
the cancellation propagates (`run_owned`, `_shards/_publish.py:164-168`),
so the merged log may be replaced; an S3 conditional upload cancelled
after its final request was sent may or may not have been written
(`AsyncFilesystem.write_file_conditional`). An interrupted command
therefore does not show that nothing was published: inspect the merged
log, or run the merge again, which is idempotent and reports
"No changes" when the interrupted run did publish.

The incomplete message the API raises names the Python argument; it
becomes "Pass allow_incomplete (--allow-incomplete on the command line) to
write an incomplete merged log." so the same text serves both callers.

The whole command body, from before `process_common_options`, runs
inside one context manager, `_merge_failures(json_output, stdout)` (with
`stdout` the saved stdout under `--json`, `sys.stdout` otherwise), that
does the classification and printing,
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
patterns; that the model options (`--model`, `--model-base-url`, `-M`,
`--model-config`, `--model-role`) are needed when the task reads them when
built or when a metric or reducer reads the model when the merge runs it
(the merge runs them in the command's model context), that passing the
workers' values is the safe default, and that they need credentials; how to translate a run
launched with `--model-spec` or `--run-config` into flags, and that the
command refuses their environment variables; that generate config options
are not taken; the exit codes; and the `--json` object and envelope with
its kinds, including that `not_found` can mean an attempt vanished
mid-merge and is worth a re-run. The sentence "A shell
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
- **Accept `--model-spec` and `--run-config`** and resolve them with
  `resolve_model_spec`, `parse_run_config` and `merge_run_config_params`
  as `eval_exec` does. A run launched with them would merge with the same
  arguments, but a run config carries far more than the task (solver,
  generate config, eval config) and its merge with the command line is
  defined against eval's whole option set, and a model spec's main content
  beside the model is generate config, which the command does not take.
  The flags cover what builds the task; refusing the environment variables
  keeps an ambient one from changing it silently.
- **Turn off the automatic lookup on every option of the command**
  (`allow_from_autoenv=False` on the shared and common options as well).
  No `INSPECT_LOG_MERGE_SHARDS_*` variable would be read at all, but the
  shared decorators would need a second parameter per option and a copy
  of `common_options`, for variables the user sets and that name the same
  options `inspect eval` reads. The task and the selection, the values
  that must not come from the environment, are already command-line only.
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
  An id selection given as text for samples whose ids are integers is now
  recorded in `eval.dataset.sample_ids` with the shards' integer ids
  (before, as given); matching and the stored selection's comparison, both
  by text, are unchanged. A merged log already written keeps its text ids
  until a merge next writes it.
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
- **Environment.** The shared and common options read the variables
  `inspect eval` reads and, when those are unset, click's automatic
  `INSPECT_LOG_MERGE_SHARDS_*` names; the user sets both. The task, the
  selection and `--json` come only from the command line, and the
  run-config and model-spec variables are refused rather than ignored.

## Testing

In `tests/log/test_shards.py`, beside the API's merge tests, through
`click.testing.CliRunner` on the `inspect` group, with `mockllm/model`. No
network, Docker or provider keys. Each test writes a task file to
`tmp_path` and runs the workers with `eval("<tmp>/t.py@name", ...)` into
`<name>.shards/<k>/`, then runs the command.

- **The command equals the API.** Two shards of a sample-id selection:
  the command's merged results and reductions equal a native unsharded
  run's, and equal the API's merge of the same shards with the same task;
  a second run prints "No changes" with `written: false`. The dataset has
  integer ids, and the command's `eval.dataset.sample_ids` equals the API
  merge's given the same ids as integers, in the same order, and holds the
  native run's ids with their types. An API merge given the ids as text
  records integers too; with `allow_incomplete` and one id no shard holds,
  that id stays as given.
- **The construction context reaches the factory.** A factory that picks
  its metric by `get_model().name` merges with `--model mockllm/model`
  and is refused (`refused`, metric names) without it; one that reads
  `get_model(role="grader")` merges with `--model-role
  grader=mockllm/model`; one whose scorer name depends on a `-T` argument
  merges with it and is refused without it. A factory that calls
  `get_model()` with no `--model` and no `INSPECT_EVAL_MODEL` gets the
  `none` model.
- **Environment variables**, invoked with the production prefix
  (`CliRunner.invoke(inspect, ..., auto_envvar_prefix="INSPECT")`):
  `INSPECT_EVAL_TASK_ARGS` and `INSPECT_EVAL_EPOCHS` build the same task
  as the flags; `INSPECT_EVAL_SAMPLE_ID` does not become the selection;
  `INSPECT_LOG_MERGE_SHARDS_TASK`, `..._SAMPLE_ID`, `..._SAMPLE_COUNT`,
  `..._ALLOW_INCOMPLETE` and `..._JSON` are not read. The shared and
  common options keep the fallback: `INSPECT_LOG_MERGE_SHARDS_MODEL`
  supplies the model with `INSPECT_EVAL_MODEL` unset and loses to it when
  both are set, `INSPECT_LOG_MERGE_SHARDS_T` builds the same task as
  `-T`, and `INSPECT_LOG_MERGE_SHARDS_LOG_DIR`, like `INSPECT_LOG_DIR`,
  is ignored rather than refused. With both
  `INSPECT_EVAL_MODEL_BASE_URL` and `OPENAI_BASE_URL` set, the model the
  command builds for `--model openai/<name>` (a dummy key; nothing is
  called) has the base URL `inspect eval` gives it, the former; the same
  test pins `inspect eval`'s and `inspect eval-set`'s `--model-base-url`
  bindings (`INSPECT_EVAL_MODEL_BASE_URL`,
  `INSPECT_EVAL_SET_MODEL_BASE_URL`).
- **Model specs and run configs.** `INSPECT_EVAL_RUN_CONFIG` set is
  `invalid_arguments`; `INSPECT_EVAL_MODEL_SPEC` set is
  `invalid_arguments` without `--model` and ignored with it; in each
  refusal the task file's import marker is absent. `--model-spec` and
  `--run-config` on the command line are click's "no such option", as is
  `--generate-config`.
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
- **Setup errors.** A patched `platform_init` that prints to stdout and
  then raises, and `INSPECT_API_KEY_OVERRIDE` naming a module that does
  not exist (with `_override_api_key` reset as below), are each `setup`,
  with exactly one JSON object on stdout under `--json` (the print on
  stderr) and the task file not imported.
- **Task errors.** A file with two tasks, a spec with no task, a missing
  file, a factory that raises, `--model a,b`, and `--model openai/gpt-4o`
  with no `OPENAI_API_KEY` are each `task`, with every file in the log
  directory byte-identical.
- **Merge errors.** A held lock file is `conflict`; no merged log and no
  shards is `not_found`, and so is an attempt removed between the merge's
  listing and its read (a patched read that deletes it first), with a
  re-run then merging its replacement; a recovered-log `LOG` is `invalid_arguments`
  before the task file is imported; `--log-dir` on the command line is
  `invalid_arguments`; a metric that raises is `internal` with its
  traceback on stderr.
- **Interruption.** A command whose merge is cancelled before
  publication (a patched shard read that cancels) prints no report and no
  envelope, leaves the merged log byte-identical and removes its lock;
  one cancelled after the local publication worker started (the
  `_replace_local` pause of
  `test_a_cancelled_publish_finishes_before_a_later_merge`) prints no
  report and no envelope, and a re-run reports "No changes" with
  `written: false`. The publication boundary itself stays covered by that
  API test on asyncio; the S3 path's unknown outcome is the existing
  `write_file_conditional` contract and is not re-tested here.
- **`--json` owns stdout.** With a hook that prints its startup banner
  (`INSPECT_API_KEY_OVERRIDE` naming a function in a test module, and
  `hooks._legacy._override_api_key` reset with `monkeypatch` so
  `init_hooks` loads it again), a factory that prints and a metric that
  logs a warning, stdout parses as exactly one JSON object, on success and
  on each error kind above, `setup` included; stderr holds the banner,
  the print and the warning. Without `--json` the banner is on stdout,
  which shows the hook was enabled.
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

1. **Shared pieces and typed ids.** `model_options`,
   `model_role_option`, `task_args_options`, `epochs_options` and
   `parse_epochs_options` in `src/inspect_ai/_cli/eval.py`, used by
   `eval_options` and `eval_exec`; `check_merge_arguments` in
   `src/inspect_ai/log/_shards/_api.py`, used by
   `merge_eval_log_shards_async`; the incomplete message names
   `--allow-incomplete`; `build_header` in
   `src/inspect_ai/log/_shards/_plan.py` records an id selection with the
   merged samples' typed ids. Files: those three, `tests/log/test_shards.py`
   (the typed-id assertions; the message assertion, if one matches it).
2. **The command.** `src/inspect_ai/_cli/log_merge_shards.py`
   (`merge_shards_command`, `_merge_failures`), registered in
   `src/inspect_ai/_cli/log.py`; the tests above in
   `tests/log/test_shards.py`.
3. **Docs.** `docs/sharding.qmd`.

## Open questions

None. Resolved by Ransom on 2026-11-05: the command takes no generate
config options ("The command").

## Not this design

- Expanding `inspect eval`'s sample selectors (`--limit` ranges,
  `--sample-id` patterns, `task:` prefixes, with `--sample-shuffle`)
  against the task's dataset for the merge's selection. PR 6 computes
  `eval_set()`'s selection from the task's dataset; the command could
  share that helper later.
- A directory-wide merge (`inspect log merge-shards --log-dir`).
- A `--delete-shards` option: shard deletion is PR 9.
- Accepting `--model-spec` and `--run-config` in the merge command.
- Sanitizing control characters in log-derived names that `inspect log`
  commands print.
