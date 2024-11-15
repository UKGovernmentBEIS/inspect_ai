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
from inspect_ai._util.constants import PKG_PATH
from inspect_ai.log import list_eval_logs
from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._file import (
    eval_log_json,
    read_eval_log,
    read_eval_log_headers,
)


@click.group("log")
def log_command() -> None:
    """Query, read, and convert logs.

    Inspect supports two log formats: 'eval' which is a compact, high performance binary format and 'json' which represents logs as JSON.

    The default format is 'eval'. You can change this by setting the INSPECT_LOG_FORMAT environment variable or using the --log-format command line option.

    The 'log' commands enable you to read Inspect logs uniformly as JSON no matter their physical storage format, and also enable you to read only the headers (everything but the samples) from log files, which is useful for very large logs.
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
    status: Literal["started", "success", "cancelled", "error"] | None,
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


@log_command.command("list")
@list_logs_options
def list_command(
    status: Literal["started", "success", "cancelled", "error"] | None,
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
def dump_command(path: str, header_only: bool) -> None:
    """Print log file contents as JSON."""
    log = read_eval_log(path, header_only=header_only)
    print(eval_log_json(log))


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
def convert_command(
    path: str, to: Literal["eval", "json"], output_dir: str, overwrite: bool
) -> None:
    """Convert between log file formats."""
    convert_eval_logs(path, to, output_dir, overwrite)


@log_command.command("headers", hidden=True)
@click.argument("files", nargs=-1)
def headers_command(files: tuple[str]) -> None:
    """Print log file headers as JSON."""
    headers(files)


def headers(files: tuple[str]) -> None:
    """Print log file headers as JSON."""
    headers = read_eval_log_headers(list(files))
    print(dumps(to_jsonable_python(headers, exclude_none=True), indent=2))


@log_command.command("schema")
def schema_command() -> None:
    """Print JSON schema for log files."""
    schema()


def schema() -> None:
    print(view_resource("log-schema.json"))


@log_command.command("types", hidden=True)
def types_command() -> None:
    """Print TS declarations for log files."""
    types()


def types() -> None:
    print(view_type_resource("log.d.ts"))


def view_resource(file: str) -> str:
    resource = PKG_PATH / "_view" / "www" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()


def view_type_resource(file: str) -> str:
    resource = PKG_PATH / "_view" / "www" / "src" / "types" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()
