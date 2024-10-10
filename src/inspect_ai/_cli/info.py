from json import dumps

import click

from inspect_ai import __version__
from inspect_ai._util.constants import PKG_PATH
from inspect_ai._view.server import resolve_header_only
from inspect_ai.log._file import eval_log_json, read_eval_log

from .log import headers, schema, types


@click.group("info")
def info_command() -> None:
    """Read configuration and log info."""
    return None


@info_command.command("version")
@click.option(
    "--json",
    type=bool,
    is_flag=True,
    default=False,
    help="Output version and path info as JSON",
)
def version(json: bool) -> None:
    if json:
        print(dumps(dict(version=__version__, path=PKG_PATH.as_posix()), indent=2))
    else:
        print(f"version: {__version__}")
        print(f"path: {PKG_PATH.as_posix()}")


@info_command.command("log-file", hidden=True)
@click.argument("path")
@click.option(
    "--header-only",
    type=int,
    is_flag=False,
    flag_value=0,
    help="Read and print only the header of the log file (i.e. no samples).",
)
def log(path: str, header_only: int) -> None:
    """Print log file contents as JSON."""
    header_only = resolve_header_only(path, header_only)

    log = read_eval_log(path, header_only=header_only)
    print(eval_log_json(log))


@info_command.command("log-file-headers", hidden=True)
@click.argument("files", nargs=-1)
def log_file_headers(files: tuple[str]) -> None:
    """Read and print a JSON list of log file headers."""
    headers(files)


@info_command.command("log-schema", hidden=True)
def log_schema() -> None:
    """Print JSON schema for log files."""
    schema()


@info_command.command("log-types", hidden=True)
def log_types() -> None:
    """Print TS declarations for log files."""
    types()
