import os
import shlex
import time
from datetime import datetime
from json import dumps
from pathlib import Path
from typing import Callable, cast

import click
from pydantic_core import to_json
from rich import print as r_print
from rich.console import Console, RenderableType
from rich.table import Column, Table

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import TRACE_FILE_NAME
from inspect_ai._util.trace import ActionTraceRecord, inspect_trace_dir, read_trace_file


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
    trace_files: list[dict[str, float | str]] = [
        {"mtime": f.lstat().st_mtime, "file": f.absolute().as_posix()}
        for f in trace_dir.iterdir()
        if f.is_file()
    ]
    trace_files.sort(key=lambda f: cast(float, f["mtime"]), reverse=True)
    if json:
        print(dumps(trace_files, indent=2))
    else:
        table = Table(box=None, show_header=True, pad_edge=False)
        table.add_column("Time")
        table.add_column("Trace File")
        for file in trace_files:
            mtime = datetime.fromtimestamp(cast(float, file["mtime"])).astimezone()
            table.add_row(
                mtime.strftime("%d-%b %H:%M:%S %Z"), shlex.quote(str(file["file"]))
            )
        r_print(table)


@trace_command.command("dump")
@click.argument("trace-file", type=str, required=False, default=TRACE_FILE_NAME)
def read_command(trace_file: str) -> None:
    """Dump a trace file to stdout (as a JSON array of log records)."""
    trace_file_path = resolve_trace_file_path(trace_file)

    traces = read_trace_file(trace_file_path)
    print(
        to_json(traces, indent=2, exclude_none=True, fallback=lambda _: None).decode()
    )


@trace_command.command("anomalies")
@click.argument("trace-file", type=str, required=False, default=TRACE_FILE_NAME)
@click.option(
    "--all",
    is_flag=True,
    default=False,
    help="Show all anomolies including errors and timeouts (by default only still running and cancelled actions are shown).",
)
def anomolies_command(trace_file: str, all: bool) -> None:
    """Look for anomalies in a trace file (never completed or cancelled actions)."""
    trace_file_path = resolve_trace_file_path(trace_file)
    traces = read_trace_file(trace_file_path)

    # Track started actions
    running_actions: dict[str, ActionTraceRecord] = {}
    canceled_actions: dict[str, ActionTraceRecord] = {}
    error_actions: dict[str, ActionTraceRecord] = {}
    timeout_actions: dict[str, ActionTraceRecord] = {}

    def action_started(trace: ActionTraceRecord) -> None:
        running_actions[trace.trace_id] = trace

    def action_completed(trace: ActionTraceRecord) -> ActionTraceRecord:
        start_trace = running_actions.get(trace.trace_id)
        if start_trace:
            del running_actions[trace.trace_id]
            return start_trace
        else:
            raise RuntimeError(f"Expected {trace.trace_id} in action dictionary.")

    def action_failed(trace: ActionTraceRecord) -> None:
        if all:
            error_actions[start_trace.trace_id] = trace

    def action_canceled(trace: ActionTraceRecord) -> None:
        canceled_actions[start_trace.trace_id] = trace

    def action_timeout(trace: ActionTraceRecord) -> None:
        if all:
            timeout_actions[start_trace.trace_id] = trace

    for trace in traces:
        if isinstance(trace, ActionTraceRecord):
            match trace.event:
                case "enter":
                    action_started(trace)
                case "exit":
                    action_completed(trace)
                case "cancel":
                    start_trace = action_completed(trace)
                    trace.start_time = start_trace.start_time
                    action_canceled(trace)
                case "error":
                    start_trace = action_completed(trace)
                    trace.start_time = start_trace.start_time
                    action_failed(trace)
                case "timeout":
                    start_trace = action_completed(trace)
                    trace.start_time = start_trace.start_time
                    action_timeout(trace)
                case _:
                    print(f"Unknown event type: {trace.event}")

    # do we have any traces?
    if (
        len(running_actions)
        + len(canceled_actions)
        + len(error_actions)
        + len(timeout_actions)
        == 0
    ):
        print(f"TRACE: {shlex.quote(trace_file_path.as_posix())}\n")
        if all:
            print("No anomalies found in trace log.")
        else:
            print(
                "No running or cancelled actions found in trace log (pass --all to see errors and timeouts)."
            )
        return

    with open(os.devnull, "w") as f:
        # generate output
        console = Console(record=True, file=f)

        def print_fn(o: RenderableType) -> None:
            console.print(o, highlight=False)

        print_fn(f"[bold]TRACE: {shlex.quote(trace_file_path.as_posix())}[bold]")

        _print_bucket(print_fn, "Running Actions", running_actions)
        _print_bucket(print_fn, "Cancelled Actions", canceled_actions)
        _print_bucket(print_fn, "Error Actions", error_actions)
        _print_bucket(print_fn, "Timeout Actions", timeout_actions)

        # print
        print(console.export_text(styles=True).strip())


def _print_bucket(
    print_fn: Callable[[RenderableType], None],
    label: str,
    bucket: dict[str, ActionTraceRecord],
) -> None:
    if len(bucket) > 0:
        # Sort the items in chronological order of when
        # they finished so the first finished item is at the top
        sorted_actions = sorted(
            bucket.values(),
            key=lambda record: (record.start_time or 0) + (record.duration or 0),
            reverse=True,
        )

        # create table
        table = Table(
            Column(""),
            Column("", justify="right"),
            Column(""),
            Column("", width=22),
            box=None,
            title=label,
            title_justify="left",
            title_style="bold",
            pad_edge=False,
            padding=(0, 1),
        )

        for action in sorted_actions:
            # Compute duration (use the event duration or time since started)
            duration = (
                action.duration
                if action.duration is not None
                else time.time() - action.start_time
                if action.start_time is not None
                else 0.0
            )

            # The event start time
            start_time = formatTime(action.start_time) if action.start_time else "None"

            # Event detail
            detail = (
                f"{action.detail or action.message} {action.error}"
                if action.event == "error"
                else (action.detail or action.message)
            )

            table.add_row(
                action.action,
                f"{round(duration, 2):.2f}s".rjust(8),
                f" {detail}",
                start_time,
            )

        print_fn("")
        print_fn(table)


def resolve_trace_file_path(trace_file: str) -> Path:
    trace_file_path = Path(trace_file)
    if not trace_file_path.is_absolute():
        trace_file_path = inspect_trace_dir() / trace_file_path

    if not trace_file_path.exists():
        raise PrerequisiteError(
            f"The specified trace file '{trace_file_path}' does not exist."
        )

    return trace_file_path


def formatTime(timestamp: float) -> str:
    dt = datetime.fromtimestamp(timestamp).astimezone()
    return dt.strftime("%H:%M:%S %Z")
