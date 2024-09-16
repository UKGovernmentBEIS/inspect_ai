from json import dumps

import click
from pydantic_core import to_jsonable_python

from inspect_ai import __version__
from inspect_ai._util.constants import PKG_PATH
from inspect_ai._view.view import resolve_header_only
from inspect_ai.log._file import eval_log_json, read_eval_log, read_eval_log_headers


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


@info_command.command("log-file")
@click.argument("path")
@click.option(
    "--header-only",
    type=int,
    is_flag=False,
    flag_value=0,
    help="Read and print only the header of the log file (i.e. no samples).",
)
def log(path: str, header_only: int) -> None:
    """Print log file contents."""
    # Resolve the header only to a boolean
    header_only = resolve_header_only(path, header_only)

    log = read_eval_log(path, header_only=header_only)
    print(eval_log_json(log))


@info_command.command("log-file-headers")
@click.argument("files", nargs=-1)
def log_file_headers(files: tuple[str]) -> None:
    """Read and print a JSON list of log file headers."""
    headers = read_eval_log_headers(list(files))
    print(dumps(to_jsonable_python(headers, exclude_none=True), indent=2))


@info_command.command("log-schema")
def log_schema() -> None:
    """Print JSON schema for log files."""
    print(view_resource("log-schema.json"))


@info_command.command("log-types")
def log_types() -> None:
    """Print TS declarations for log files."""
    print(view_type_resource("log.d.ts"))


def view_resource(file: str) -> str:
    resource = PKG_PATH / "_view" / "www" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()


def view_type_resource(file: str) -> str:
    resource = PKG_PATH / "_view" / "www" / "src" / "types" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()
