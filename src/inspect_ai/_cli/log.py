import functools
import os
import sys
from contextlib import nullcontext
from json import dumps
from typing import Any, Callable, Literal, NoReturn, TextIO, cast
from urllib.parse import urlparse

import click
from fsspec.core import split_protocol  # type: ignore
from pydantic_core import to_jsonable_python
from typing_extensions import Unpack

from inspect_ai._cli.common import CommonOptions, common_options, process_common_options
from inspect_ai._cli.util import int_or_bool_flag_callback
from inspect_ai._util.constants import PKG_PATH
from inspect_ai.log import EvalStatus, IncompleteAction, list_eval_logs
from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._file import (
    eval_log_json_str,
    read_eval_log,
    read_eval_log_headers,
)


@click.group("log")
def log_command() -> None:
    """Query, read, and convert logs.

    Inspect supports two log formats: 'eval' which is a compact, high performance binary format and 'json' which represents logs as JSON.

    The default format is 'eval'. You can change this by setting the INSPECT_LOG_FORMAT environment variable or using the --log-format command line option.

    The 'log' commands enable you to read Inspect logs uniformly as JSON no matter their physical storage format, and also enable you to read only the headers (everything but the samples) from log files, which is useful for very large logs.

    Learn more about managing log files at https://inspect.aisi.org.uk/eval-logs.html.
    """
    return None


def list_logs_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--status",
        type=click.Choice(
            ["started", "success", "cancelled", "error"], case_sensitive=False
        ),
        help="List only log files with the indicated status.",
    )
    @click.option(
        "--absolute",
        type=bool,
        is_flag=True,
        default=False,
        help="List absolute paths to log files (defaults to relative to the cwd).",
    )
    @click.option(
        "--json",
        type=bool,
        is_flag=True,
        default=False,
        help="Output listing as JSON",
    )
    @click.option(
        "--no-recursive",
        type=bool,
        is_flag=True,
        help="List log files recursively (defaults to True).",
    )
    @common_options
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def log_list(
    status: EvalStatus | None,
    absolute: bool,
    json: bool,
    no_recursive: bool | None,
    **common: Unpack[CommonOptions],
) -> None:
    process_common_options(common)

    # list the logs
    logs = list_eval_logs(
        log_dir=common["log_dir"],
        filter=(lambda log: log.status == status) if status else None,
        recursive=no_recursive is not True,
    )

    # convert file names
    for log in logs:
        if urlparse(log.name).scheme == "file":
            _, path = split_protocol(log.name)
            log.name = path
            if not absolute:
                log.name = os.path.relpath(log.name, os.path.curdir)

    if json:
        logs_dicts = [log.model_dump() for log in logs]
        print(dumps(logs_dicts, indent=2))

    else:
        for log in logs:
            print(log.name)


def resolve_attachments_callback(
    ctx: click.Context, param: click.Parameter, value: str
) -> bool | Literal["full", "core"]:
    source = ctx.get_parameter_source(param.name) if param.name else ""
    if source == click.core.ParameterSource.DEFAULT:
        return False

    if value is None:
        return False
    elif value == "full":
        return "full"
    elif value == "core":
        return "core"
    else:
        raise click.BadParameter(f"Expected 'full', or 'core'. Got: {value}")


@log_command.command("list")
@list_logs_options
def list_command(
    status: EvalStatus | None,
    absolute: bool,
    json: bool,
    no_recursive: bool | None,
    **common: Unpack[CommonOptions],
) -> None:
    """List all logs in the log directory."""
    log_list(status, absolute, json, no_recursive, **common)


@log_command.command("dump")
@click.argument("path")
@click.option(
    "--header-only",
    type=bool,
    is_flag=True,
    default=False,
    help="Read and print only the header of the log file (i.e. no samples).",
)
@click.option(
    "--resolve-attachments",
    type=click.Choice(["full", "core"]),
    flag_value="core",
    is_flag=False,
    default=None,
    callback=resolve_attachments_callback,
    help="Resolve attachments (duplicated content blocks) to their full content.",
)
def dump_command(
    path: str, header_only: bool, resolve_attachments: bool | Literal["full", "core"]
) -> None:
    """Print log file contents as JSON."""
    log = read_eval_log(
        path, header_only=header_only, resolve_attachments=resolve_attachments
    )
    print(eval_log_json_str(log))


@log_command.command("convert")
@click.argument("path")
@click.option(
    "--to",
    type=click.Choice(["eval", "json"], case_sensitive=False),
    required=True,
    help="Target format to convert to.",
)
@click.option(
    "--output-dir",
    required=True,
    help="Directory to write converted log files to.",
)
@click.option(
    "--overwrite",
    type=bool,
    is_flag=True,
    default=False,
    help="Overwrite files in the output directory.",
)
@click.option(
    "--resolve-attachments",
    type=click.Choice(["full", "core"]),
    flag_value="core",
    is_flag=False,
    default=None,
    callback=resolve_attachments_callback,
    help="Resolve attachments (duplicated content blocks) to their full content.",
)
@click.option(
    "--stream",
    flag_value="true",
    type=str,
    is_flag=False,
    default=False,
    callback=int_or_bool_flag_callback(True, false_value=False, is_one_true=False),
    help="Stream the samples through the conversion process instead of reading the entire log into memory. Useful for large logs. Set to an integer to limit the number of concurrent samples being converted.",
)
def convert_command(
    path: str,
    to: Literal["eval", "json"],
    output_dir: str,
    overwrite: bool,
    resolve_attachments: bool | Literal["full", "core"],
    stream: int | bool = False,
) -> None:
    """Convert between log file formats."""
    convert_eval_logs(
        path,
        to,
        output_dir,
        overwrite,
        resolve_attachments=resolve_attachments,
        stream=stream,
    )


@log_command.command("convert-chunked", hidden=True)
@click.argument("path")
@click.option(
    "--output-dir",
    required=True,
    help="Directory to write converted .eval log files to.",
)
@click.option(
    "--overwrite",
    type=bool,
    is_flag=True,
    default=False,
    help="Overwrite files in the output directory.",
)
def convert_chunked_command(
    path: str,
    output_dir: str,
    overwrite: bool,
) -> None:
    """Convert .eval log file(s) to .eval files with chunked samples (internal)."""
    from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked

    convert_eval_logs_to_chunked(
        path,
        output_dir,
        overwrite=overwrite,
    )


@log_command.command("headers", hidden=True)
@click.argument("files", nargs=-1)
def headers_command(files: tuple[str, ...]) -> None:
    """Print log file headers as JSON."""
    headers(files)


def headers(files: tuple[str, ...]) -> None:
    """Print log file headers as JSON."""
    headers = read_eval_log_headers(list(files))
    print(dumps(to_jsonable_python(headers, exclude_none=True), indent=2))


@log_command.command("schema")
def schema_command() -> None:
    """Print JSON schema for log files."""
    schema()


def schema() -> None:
    resource = PKG_PATH / "_view" / "inspect-openapi.json"
    with open(resource, "r", encoding="utf-8") as f:
        print(f.read())


@log_command.command("types", hidden=True)
def types_command() -> None:
    """Print TS declarations for log files."""
    types()


def types() -> None:
    print(view_type_resource("generated.ts"))


@log_command.command("export-config")
@click.argument("log_file")
@click.option(
    "--output",
    type=str,
    default=None,
    help="Write output to this file instead of stdout.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["yaml", "json"], case_sensitive=False),
    default="yaml",
    show_default=True,
    help="Output format.",
)
def export_config_command(log_file: str, output: str | None, fmt: str) -> None:
    """Export the run configuration from a log file.

    Reads LOG_FILE and writes a YAML (or JSON) file that can be passed directly
    to 'inspect eval --run-config' to reproduce the run.

    Example:
        inspect log export-config logs/my_run.eval > run.yaml

        inspect eval --run-config run.yaml
    """
    import yaml

    from inspect_ai.log._config import eval_log_to_run_config_dict
    from inspect_ai.log._file import read_eval_log

    log = read_eval_log(log_file, header_only=True)
    d = eval_log_to_run_config_dict(log)

    if fmt == "json":
        from json import dumps

        text = dumps(d, indent=2)
    else:
        text = yaml.dump(
            d, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text, end="")


@log_command.command("recover")
@click.argument("log_file", required=False)
@click.option(
    "--output",
    type=str,
    default=None,
    help="Output path for the recovered log file.",
)
@click.option(
    "--overwrite",
    type=bool,
    is_flag=True,
    default=False,
    help="Overwrite the crashed log file in-place instead of creating a new file.",
)
@click.option(
    "--no-cleanup",
    type=bool,
    is_flag=True,
    default=False,
    help="Don't remove the sample buffer database after recovery.",
)
@click.option(
    "--no-events",
    type=bool,
    is_flag=True,
    default=False,
    help="Exclude event transcript from recovered samples (reduces output size).",
)
@click.option(
    "--incomplete-action",
    type=click.Choice(["retry", "error"]),
    default="retry",
    help="Disposition for samples that were in progress at crash: 'retry' "
    "(default) marks them as cancelled errors that a later eval-retry re-runs; "
    "'error' resolves them as operator terminations, finalizing the recovered "
    "log with status 'success' when every expected sample is final (nothing "
    "will retry it).",
)
@click.option(
    "--incomplete-max",
    type=click.FloatRange(min=0),
    default=None,
    help="Safety threshold for --incomplete-action error (count if >= 1, or "
    "proportion of expected samples if strictly less than 1): refuse to recover "
    "when more than this many samples are in progress. Has no effect (a warning "
    "is logged) with --incomplete-action retry.",
)
@click.option(
    "--list",
    "list_mode",
    type=bool,
    is_flag=True,
    default=False,
    help="List recoverable logs instead of recovering.",
)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    help="Output listing as JSON (only with --list).",
)
@common_options
def recover_command(
    log_file: str | None,
    output: str | None,
    overwrite: bool,
    no_cleanup: bool,
    no_events: bool,
    incomplete_action: IncompleteAction,
    incomplete_max: float | None,
    list_mode: bool,
    json_output: bool,
    **common: Unpack[CommonOptions],
) -> None:
    """Recover crashed eval logs from sample buffer databases."""
    from json import dumps as json_dumps

    from inspect_ai._util.platform import platform_init
    from inspect_ai.log._recover import (
        recover_eval_log,
        recoverable_eval_logs,
    )

    process_common_options(common)
    platform_init()

    if list_mode:
        logs = recoverable_eval_logs(log_dir=common["log_dir"])

        if not logs:
            print("No recoverable logs found.")
            return

        if json_output:
            print(
                json_dumps(
                    [
                        {
                            "name": r.log.name,
                            "task": r.log.task,
                            "total_samples": r.total_samples,
                            "flushed_samples": r.flushed_samples,
                            "completed_samples": r.completed_samples,
                            "in_progress_samples": r.in_progress_samples,
                            "source": r.source,
                        }
                        for r in logs
                    ],
                    indent=2,
                )
            )
        else:
            import rich

            from inspect_ai._util.path import pretty_path

            console = rich.get_console()
            for r in logs:
                print()
                console.print(
                    f"[bold]log:[/bold] {pretty_path(r.log.name)}", highlight=False
                )
                console.print(f"  [dim]source:[/dim] {r.source}", highlight=False)
                print(
                    f"  ({r.total_samples} total, "
                    f"{r.flushed_samples} flushed, "
                    f"{r.completed_samples} completed, "
                    f"{r.in_progress_samples} in-progress)"
                )
            print()

    else:
        if log_file is None:
            raise click.UsageError("LOG_FILE is required when not using --list.")

        from inspect_ai.log._recover import (
            RecoveryNotAvailable,
            RecoveryStats,
            RecoveryThresholdExceeded,
        )

        stats = RecoveryStats()
        try:
            log = recover_eval_log(
                log_file,
                output=output,
                overwrite=overwrite,
                cleanup=not no_cleanup,
                no_events=no_events,
                incomplete_action=incomplete_action,
                incomplete_max=incomplete_max,
                _stats=stats,
            )
        except RecoveryNotAvailable as e:
            raise click.UsageError(str(e))
        except RecoveryThresholdExceeded as e:
            raise click.ClickException(str(e))
        output_path = log.location or output
        # keep the historical success line intact (scripts may anchor on its
        # shape); report the status on its own line
        print(f"Recovered {stats.sample_count} samples to {output_path}")
        print(f"  status: {log.status}")
        if incomplete_action == "error" and stats.in_progress_count > 0:
            print(
                f"  {stats.in_progress_count} in-progress samples resolved "
                f"as errors (stalled at crash)"
            )
        if stats.not_finalized_reason is not None:
            print(f"  not finalized: {stats.not_finalized_reason}")

        if stats.failed_count > 0 and log.status == "error":
            print(f"\nTo re-run the {stats.failed_count} failed/cancelled samples:")
            print(f"  inspect eval-retry {output_path}")


@log_command.command("merge-shards")
@click.argument("log", type=str)
@click.option(
    "--sample-id",
    type=str,
    default=None,
    help="Intended selection as comma-separated sample ids.",
)
@click.option(
    "--sample-count",
    type=int,
    default=None,
    help="Intended selection as a number of samples.",
)
@click.option(
    "--allow-incomplete",
    type=bool,
    is_flag=True,
    default=False,
    help="Write a 'started' or 'error' merged log when the shards are incomplete.",
)
@click.option(
    "--delete-shards",
    type=bool,
    is_flag=True,
    default=False,
    help="Delete the shards directory after a complete merge. Every worker must "
    "have exited.",
)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    help="Print one JSON object: the merged log on success, or "
    '{"error": {"type", "message", ...}} on failure (exit 1).',
)
@common_options
def merge_shards_command(
    log: str,
    sample_id: str | None,
    sample_count: int | None,
    allow_incomplete: bool,
    delete_shards: bool,
    json_output: bool,
    **common: Unpack[CommonOptions],
) -> None:
    """Merge the shard logs of a sharded run into one eval log.

    LOG is the merged log (<name>.eval) or its shards directory (<name>.shards).
    """
    from inspect_ai._cli.eval import _stdout_owned_for_json
    from inspect_ai._util._async import run_coroutine
    from inspect_ai._util.error import WriteConflictError
    from inspect_ai._util.platform import platform_init
    from inspect_ai._util.samples import parse_sample_id
    from inspect_ai.log import ShardSetError, ShardSetIncomplete
    from inspect_ai.log._shards._api import merge_shards

    process_common_options(common)
    platform_init()

    def notice(task_file: str) -> None:
        click.echo(
            f"Notice: importing {task_file} to resolve metrics and epoch reducers.",
            err=True,
        )

    # with --json, stdout carries only the result or error object: output
    # from task-file, metric and reducer code goes to stderr
    owned = _stdout_owned_for_json() if json_output else nullcontext(sys.stdout)
    with owned as stdout:
        if sample_id is not None and sample_count is not None:
            _merge_failure(
                json_output,
                click.UsageError("Pass at most one of --sample-id and --sample-count."),
                stdout,
            )
        try:
            outcome = run_coroutine(
                merge_shards(
                    log,
                    sample_ids=parse_sample_id(sample_id),
                    sample_count=sample_count,
                    allow_incomplete=allow_incomplete,
                    delete_shards=delete_shards,
                    on_task_file_import=notice,
                )
            )
        except (
            ShardSetError,
            ShardSetIncomplete,
            WriteConflictError,
            FileNotFoundError,
            ValueError,
        ) as ex:
            _merge_failure(json_output, ex, stdout)

        header = outcome.result.log
        ledger = header.eval.shards.ledger if header.eval.shards else []
        samples = sum(entry.samples for entry in ledger)
        status = outcome.status
        if json_output:
            result = {
                "log": header.location,
                "status": header.status,
                "written": outcome.result.written,
                "shards": len(ledger),
                "samples": samples,
                "new_samples": outcome.new_samples,
                "missing": status.missing,
                "running": status.running,
                "failed": status.failed,
                "shards_deleted": outcome.result.shards_deleted,
                "task_file_imported": outcome.task_file_imported,
            }
            click.echo(dumps(result, indent=2), file=stdout)
            return
    line = (
        f"{header.location}: {header.status}, {samples} samples "
        f"({outcome.new_samples} new) from {len(ledger)} shards"
    )
    if not outcome.result.written:
        line += ", unchanged"
    if header.status != "success":
        if status.missing:
            line += f", {len(status.missing)} missing"
        if status.running:
            line += f", running: {', '.join(status.running)}"
        if status.failed:
            line += f", failed: {', '.join(status.failed)}"
    if outcome.result.shards_deleted:
        line += ", shards deleted"
    click.echo(line)


def _merge_failure(json_output: bool, ex: Exception, stdout: TextIO) -> NoReturn:
    """End `merge-shards` with `ex`: an error object on `stdout` with `--json`.

    Without `--json`, a usage error exits 2 and any other error exits 1 with
    its message on stderr. With it, every failure prints
    `{"error": {"type", "message"}}` on stdout and exits 1; an incomplete
    set adds its `status`, `missing`, `running` and `failed`.
    """
    from inspect_ai.log import ShardSetIncomplete

    if not json_output:
        if isinstance(ex, click.ClickException):
            raise ex
        raise click.ClickException(str(ex)) from ex
    message = ex.format_message() if isinstance(ex, click.ClickException) else str(ex)
    error: dict[str, Any] = {"type": type(ex).__name__, "message": message}
    if isinstance(ex, ShardSetIncomplete):
        error.update(
            status=ex.status, missing=ex.missing, running=ex.running, failed=ex.failed
        )
    click.echo(dumps({"error": error}, indent=2), file=stdout)
    raise SystemExit(1)


_TS_MONO_APP = PKG_PATH / "_view" / "ts-mono" / "apps" / "inspect"

_SUBMODULE_MSG = (
    "ts-mono submodule not initialized. Run 'git submodule update --init' to set it up."
)


def _require_submodule() -> None:
    if not (_TS_MONO_APP / "src").exists():
        raise RuntimeError(_SUBMODULE_MSG)


def view_resource(file: str) -> str:
    _require_submodule()
    resource = _TS_MONO_APP / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()


_TS_MONO_INSPECT_COMMON = PKG_PATH / "_view" / "ts-mono" / "packages" / "inspect-common"


def view_type_resource(file: str) -> str:
    _require_submodule()
    resource = _TS_MONO_INSPECT_COMMON / "src" / "types" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()
