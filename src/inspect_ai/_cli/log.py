import functools
import os
from json import dumps
from typing import Any, Callable, Literal, cast
from urllib.parse import urlparse

import click
from fsspec.core import split_protocol  # type: ignore
from pydantic_core import to_jsonable_python
from typing_extensions import Unpack

from inspect_ai._cli.common import CommonOptions, common_options, process_common_options
from inspect_ai._cli.util import int_or_bool_flag_callback
from inspect_ai._util.constants import PKG_PATH
from inspect_ai.log import EvalStatus, list_eval_logs
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


@log_command.command("recover")
@click.argument("log_file", required=False)
@click.option(
    "--output",
    type=str,
    default=None,
    help="Output path for the recovered log file.",
)
@click.option(
    "--no-cleanup",
    type=bool,
    is_flag=True,
    default=False,
    help="Don't remove the sample buffer database after recovery.",
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
    no_cleanup: bool,
    list_mode: bool,
    json_output: bool,
    **common: Unpack[CommonOptions],
) -> None:
    """Recover crashed eval logs from sample buffer databases."""
    from json import dumps as json_dumps

    import anyio
    import rich
    from rich.table import Table

    from inspect_ai._util._async import configured_async_backend
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
                        }
                        for r in logs
                    ],
                    indent=2,
                )
            )
        else:
            table = Table(title="Recoverable Logs")
            table.add_column("Log File")
            table.add_column("Task")
            table.add_column("Total", justify="right")
            table.add_column("Flushed", justify="right")
            table.add_column("Completed", justify="right")
            table.add_column("In Progress", justify="right")

            for r in logs:
                table.add_row(
                    r.log.name,
                    r.log.task,
                    str(r.total_samples),
                    str(r.flushed_samples),
                    str(r.completed_samples),
                    str(r.in_progress_samples),
                )

            console = rich.get_console()
            console.print(table)

    else:
        if log_file is None:
            raise click.UsageError("LOG_FILE is required when not using --list.")

        async def run_recover() -> None:
            log = await recover_eval_log(
                log_file,
                output=output,
                cleanup=not no_cleanup,
            )
            sample_count = len(log.samples) if log.samples else 0
            output_path = log.location or output
            print(f"Recovered {sample_count} samples to {output_path}")

            failed_count = sum(1 for s in (log.samples or []) if s.error is not None)
            if failed_count > 0:
                print(f"\nTo re-run the {failed_count} failed/cancelled samples:")
                print(f"  inspect eval-retry {output_path}")

        anyio.run(run_recover, backend=configured_async_backend())


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
