"""`inspect log merge-shards`: merge a sharded run's shard logs."""

import functools
import json
import os
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any, Literal, TextIO

import click
from click.core import ParameterSource
from typing_extensions import Unpack

from inspect_ai._cli.common import CommonOptions, common_options, process_common_options
from inspect_ai._cli.ctl._failure import _exception_name
from inspect_ai._cli.eval import (
    _stdout_owned_for_json,
    epochs_options,
    model_options,
    model_role_option,
    parse_epochs_options,
    task_args_options,
)
from inspect_ai._util.error import PrerequisiteError

if TYPE_CHECKING:
    from inspect_ai._eval.task.task import Task
    from inspect_ai.log import ShardMergeResult

_Kind = Literal[
    "setup",
    "invalid_arguments",
    "task",
    "not_found",
    "incomplete",
    "outside_selection",
    "refused",
    "conflict",
    "storage_error",
    "internal",
]

_SINGLE_MODEL_OPTIONS = {
    "model": "--model",
    "model_base_url": "--model-base-url",
    "model_config": "--model-config",
    "m": "-M",
}


class _MergeFailure(Exception):
    """A failure of the command, classified for its report."""

    def __init__(
        self,
        kind: _Kind,
        error: BaseException,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind: _Kind = kind
        self.error = error
        self.message = message
        self.extra = extra or {}


@click.command("merge-shards")
@click.argument("log", type=str)
@click.option(
    "--task",
    "task",
    type=str,
    required=True,
    allow_from_autoenv=False,
    help="The task the shards ran, as for `inspect eval` (file.py, file.py@name, a registered name or a directory).",
)
@task_args_options
@model_options(model_base_url_envvar="INSPECT_EVAL_MODEL_BASE_URL")
@model_role_option
@epochs_options
@click.option(
    "--sample-id",
    type=str,
    allow_from_autoenv=False,
    help="Intended selection as exact sample ids, comma separated. Not patterns; no 'task:' prefix.",
)
@click.option(
    "--sample-count",
    type=int,
    allow_from_autoenv=False,
    help="Intended selection as a number of samples (exclusive with --sample-id).",
)
@click.option(
    "--allow-incomplete",
    type=bool,
    is_flag=True,
    default=False,
    allow_from_autoenv=False,
    help="Write a 'started' or 'error' merged log when the shard set is incomplete.",
)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    allow_from_autoenv=False,
    help="Print one JSON object on stdout: the merged log's location, status and whether it was written, or an error envelope.",
)
@common_options
@click.pass_context
def merge_shards_command(
    ctx: click.Context,
    log: str,
    task: str,
    t: tuple[str, ...],
    task_config: str | None,
    model: str | None,
    model_base_url: str | None,
    m: tuple[str, ...],
    model_config: str | None,
    model_role: tuple[str, ...],
    epochs: int | None,
    epochs_reducer: str | None,
    no_epochs_reducer: bool | None,
    sample_id: str | None,
    sample_count: int | None,
    allow_incomplete: bool,
    json_output: bool,
    **common: Unpack[CommonOptions],
) -> None:
    """Merge the shard logs of a sharded run into its merged log.

    LOG is the merged log (`<name>.eval`) or its shards directory
    (`<name>.shards`). Pass the task options the workers were given
    (`-T`, `--model`, `--model-role`, `--epochs`, ...); they mean what they
    mean to `inspect eval`. Exits 1 on any failure.

    Learn more at https://inspect.aisi.org.uk/sharding.html.
    """
    if json_output:
        common["display"] = "none"
        common["no_ansi"] = None
    with _merge_failures(json_output) as stdout:
        with _phase("setup"):
            process_common_options(common)

            from inspect_ai._util.platform import platform_init

            platform_init()

        with _phase("invalid_arguments"):
            _check_command_line(ctx)
            ids = _parse_sample_ids(sample_id)
            from inspect_ai.log._shards._api import check_merge_arguments

            paths, _ = check_merge_arguments(log, ids, sample_count)

        with _phase("task"):
            built = _build_task(
                task,
                t=t,
                task_config=task_config,
                model=model,
                model_base_url=model_base_url,
                m=m,
                model_config=model_config,
                model_role=model_role,
                epochs=epochs,
                epochs_reducer=epochs_reducer,
                no_epochs_reducer=no_epochs_reducer,
                log_level=common["log_level"],
            )

        with _merge_phase(paths.shards_dir):
            from inspect_ai._util._async import run_main
            from inspect_ai.log import merge_eval_log_shards_async

            # run_main, unlike the sync API's event loop, turns Ctrl-C under
            # trio into a cancellation and then a plain KeyboardInterrupt
            result = run_main(
                functools.partial(
                    merge_eval_log_shards_async,
                    log,
                    built,
                    sample_ids=ids,
                    sample_count=sample_count,
                    allow_incomplete=allow_incomplete,
                )
            )

        _print_result(result, json_output, stdout)


def _check_command_line(ctx: click.Context) -> None:
    """Refuse `--log-dir`, a run config or a model spec.

    Raises:
        ValueError: One of them is given.
    """
    if ctx.get_parameter_source("log_dir") == ParameterSource.COMMANDLINE:
        raise ValueError(
            "--log-dir is not used by inspect log merge-shards: pass the merged "
            "log or its shards directory as LOG."
        )
    if os.environ.get("INSPECT_EVAL_RUN_CONFIG"):
        raise ValueError(
            "INSPECT_EVAL_RUN_CONFIG is set, but inspect log merge-shards does not "
            "take a run config. Unset it and pass the run config's task, task "
            "args, model, model args, base URL, model roles and epochs as --task, "
            "-T, --model, -M, --model-base-url, --model-role, --epochs and "
            "--epochs-reducer (--no-epochs-reducer for an empty epochs_reducer)."
        )
    typed = any(
        ctx.get_parameter_source(name) == ParameterSource.COMMANDLINE
        for name in _SINGLE_MODEL_OPTIONS
    )
    if os.environ.get("INSPECT_EVAL_MODEL_SPEC") and not typed:
        raise ValueError(
            "INSPECT_EVAL_MODEL_SPEC is set, but inspect log merge-shards does not "
            "take a model spec. Unset it, or pass the spec's model, base URL and "
            "model args as --model, --model-base-url and -M."
        )


def _parse_sample_ids(sample_id: str | None) -> list[str] | None:
    """The `--sample-id` ids.

    Raises:
        ValueError: An id is empty.
    """
    from inspect_ai._util.samples import parse_sample_id

    ids = parse_sample_id(sample_id)
    if ids is not None and any(id == "" for id in ids):
        raise ValueError(f"--sample-id holds an empty id: {sample_id!r}.")
    return ids


def _build_task(
    task: str,
    *,
    t: tuple[str, ...],
    task_config: str | None,
    model: str | None,
    model_base_url: str | None,
    m: tuple[str, ...],
    model_config: str | None,
    model_role: tuple[str, ...],
    epochs: int | None,
    epochs_reducer: str | None,
    no_epochs_reducer: bool | None,
    log_level: str,
) -> "Task":
    """Build the task as `inspect eval` builds it from the same options.

    The model and roles stay active for the merge.

    Raises:
        PrerequisiteError: The options give several models, or the spec
            resolves to no task or several.
    """
    from inspect_ai._cli.util import parse_cli_config, parse_model_role_cli_args
    from inspect_ai._eval.eval import eval_init, eval_resolve_tasks
    from inspect_ai._eval.task.task import resolve_task_epochs, task_with
    from inspect_ai.model import GenerateConfig

    task_args = parse_cli_config(t, task_config)
    model_args = parse_cli_config(m, model_config)
    model_roles = parse_model_role_cli_args(model_role)
    epochs_override = parse_epochs_options(epochs, epochs_reducer, no_epochs_reducer)

    models = eval_init(
        model=model,
        model_base_url=model_base_url,
        model_args=model_args,
        log_level=log_level,
    )
    if len(models) > 1:
        raise PrerequisiteError(
            f"A merge has one task, so it takes one model, not {len(models)}: "
            f"{', '.join(str(each) for each in models)}."
        )
    resolved, _, _ = eval_resolve_tasks(
        task, task_args, models, model_roles, GenerateConfig(), None, None, None
    )
    if len(resolved) == 0:
        raise PrerequisiteError(f"No task found at {task}.")
    if len(resolved) > 1:
        names = ", ".join(r.task.name for r in resolved)
        raise PrerequisiteError(
            f"{task} holds several tasks ({names}). Name one, as file.py@name."
        )
    built = resolved[0].task
    if epochs_override is not None:
        built = task_with(built, epochs=resolve_task_epochs(built, epochs_override))
    return built


def _print_result(
    result: "ShardMergeResult", json_output: bool, stdout: TextIO
) -> None:
    header = result.log
    shards = len(header.eval.shards.ledger) if header.eval.shards is not None else 0
    if json_output:
        record = {
            "location": header.location,
            "status": header.status,
            "written": result.written,
            "task": header.eval.task,
            "task_id": header.eval.task_id,
            "eval_id": header.eval.eval_id,
            "shards": shards,
        }
        print(json.dumps(record), file=stdout, flush=True)
    else:
        if result.written:
            print(f"Merged {shards} shards into {header.location}", file=stdout)
        else:
            print(f"No changes since the last merge: {header.location}", file=stdout)
        print(f"  status: {header.status}", file=stdout, flush=True)


@contextmanager
def _merge_failures(json_output: bool) -> Iterator[TextIO]:
    """Report every failure of the command and exit 1.

    The message goes to stderr; with `--json` stdout is owned for the whole
    command (factory prints and subprocess output go to stderr) and carries
    one result object or one error envelope. Click's own errors, Ctrl-C and
    cancellation pass through unreported.

    Yields:
        The stream for the command's result.
    """
    owner = _stdout_owned_for_json() if json_output else nullcontext(sys.stdout)
    with owner as stdout:
        try:
            yield stdout
        except (click.exceptions.Exit, click.ClickException, click.exceptions.Abort):
            raise
        except Exception as ex:
            failure = (
                ex
                if isinstance(ex, _MergeFailure)
                else _MergeFailure("internal", ex, _message(ex))
            )
            if failure.kind == "internal":
                click.echo(
                    "".join(traceback.format_exception(failure.error)),
                    err=True,
                    nl=False,
                )
            click.echo(failure.message, err=True)
            if json_output:
                error = {
                    "kind": failure.kind,
                    "exception": _exception_name(failure.error),
                    "message": failure.message,
                    **failure.extra,
                }
                print(json.dumps({"error": error}), file=stdout, flush=True)
            raise click.exceptions.Exit(1) from ex


@contextmanager
def _phase(kind: Literal["setup", "invalid_arguments", "task"]) -> Iterator[None]:
    """Classify a failure of a phase before the merge.

    In the argument checks only a `ValueError` is `invalid_arguments`;
    anything else there is `internal`. Any failure of setup (common
    options, platform init and its hooks) is `setup`, and any failure
    building the task is `task`, so an error from the task's own code never
    reads as a merge refusal.
    """
    try:
        yield
    except ValueError as ex:
        raise _MergeFailure(kind, ex, _message(ex)) from ex
    except Exception as ex:
        if kind != "invalid_arguments":
            raise _MergeFailure(kind, ex, _message(ex)) from ex
        raise


@contextmanager
def _merge_phase(shards_dir: str) -> Iterator[None]:
    """Classify a failure of the merge by its type."""
    from botocore.exceptions import BotoCoreError, ClientError

    from inspect_ai._util.error import WriteConflictError
    from inspect_ai._util.file import dirname
    from inspect_ai.log import ShardSelectionError, ShardSetError, ShardSetIncomplete

    try:
        yield
    except ShardSetIncomplete as ex:
        incomplete = {
            "status": ex.status,
            "missing": ex.missing,
            "running": ex.running,
            "failed": ex.failed,
        }
        raise _MergeFailure(
            "incomplete", ex, _message(ex), {"incomplete": incomplete}
        ) from ex
    except ShardSelectionError as ex:
        raise _MergeFailure(
            "outside_selection", ex, _message(ex), {"outside": ex.outside}
        ) from ex
    except ShardSetError as ex:
        raise _MergeFailure("refused", ex, _message(ex)) from ex
    except WriteConflictError as ex:
        raise _MergeFailure("conflict", ex, _message(ex)) from ex
    except FileNotFoundError as ex:
        message = _message(ex)
        if ex.filename is not None and _in_shard_set(
            dirname(shards_dir), str(ex.filename)
        ):
            message += (
                ". A shard attempt the merge listed was removed before it was "
                "read, as a worker's retry cleanup removes an older attempt. Run "
                "the merge again once the workers have exited."
            )
        raise _MergeFailure("not_found", ex, message) from ex
    except (OSError, BotoCoreError, ClientError) as ex:
        raise _MergeFailure("storage_error", ex, _message(ex)) from ex


def _in_shard_set(root: str, path: str) -> bool:
    from inspect_ai.log._shards._walk import is_shard_path

    try:
        return is_shard_path(root, path)
    except ValueError:
        return False


def _message(ex: BaseException) -> str:
    if isinstance(ex, PrerequisiteError):
        return str(ex.message)
    return str(ex) or _exception_name(ex)
