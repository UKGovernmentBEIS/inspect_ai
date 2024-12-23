from json import dumps
from pathlib import Path

import click
from pydantic_core import to_json

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.trace import inspect_trace_dir, read_trace_file


@click.group("trace")
def trace_command() -> None:
    """List and read execution traces.

    Inspect includes a TRACE log-level which is right below the HTTP and INFO log levels (so not written to the console by default). However, TRACE logs are always recorded to a separate file, and the last 10 TRACE logs are preserved. The 'trace' command provides ways to list and read these traces.
    """
    return None


@trace_command.command("list")
@click.option(
    "--json",
    type=bool,
    is_flag=True,
    default=False,
    help="Output listing as JSON",
)
def list_command(json: bool) -> None:
    """List all trace files."""
    trace_dir = inspect_trace_dir()
    trace_files = [f.absolute().as_posix() for f in trace_dir.iterdir() if f.is_file()]
    if json:
        print(dumps(trace_files, indent=2))
    else:
        print("\n".join(trace_files))


@trace_command.command("read")
@click.argument("trace-file", type=str, required=True)
def read_command(trace_file: str) -> None:
    """Read a trace file as a JSON array of log records."""
    trace_file_path = resolve_trace_file_path(trace_file)

    traces = read_trace_file(trace_file_path)
    print(
        to_json(traces, indent=2, exclude_none=True, fallback=lambda _: None).decode()
    )


@trace_command.command("anomolies")
@click.argument("trace-file", type=str, required=True)
def anomolies_command(trace_file: str) -> None:
    """Look for anomolies in a trace file (never completed or cancelled actions)."""


def resolve_trace_file_path(trace_file: str) -> Path:
    trace_file_path = Path(trace_file)
    if not trace_file_path.is_absolute():
        trace_file_path = inspect_trace_dir() / trace_file_path

    if not trace_file_path.exists():
        raise PrerequisiteError(
            f"The specified trace file '{trace_file_path}' does not exist."
        )

    return trace_file_path
