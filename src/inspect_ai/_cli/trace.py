import os
import shutil
import subprocess
import time
from datetime import datetime
from json import dumps
from pathlib import Path
from typing import Callable

import click
from pydantic_core import to_json
from rich.console import Console, RenderableType

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
    trace_files = [f.absolute().as_posix() for f in trace_dir.iterdir() if f.is_file()]
    if json:
        print(dumps(trace_files, indent=2))
    else:
        print("\n".join(trace_files))


@trace_command.command("dump")
@click.argument("trace-file", type=str, required=True)
def read_command(trace_file: str) -> None:
    """Dump a trace file to stdout (as a JSON array of log records)."""
    trace_file_path = resolve_trace_file_path(trace_file)

    traces = read_trace_file(trace_file_path)
    print(
        to_json(traces, indent=2, exclude_none=True, fallback=lambda _: None).decode()
    )


@trace_command.command("anomalies")
@click.argument("trace-file", type=str, required=False, default=TRACE_FILE_NAME)
def anomolies_command(trace_file: str) -> None:
    """Look for anomalies in a trace file (never completed or cancelled actions)."""
    trace_file_path = resolve_trace_file_path(trace_file)
    traces = read_trace_file(trace_file_path)

    # Track started actions
    running_actions: dict[str, ActionTraceRecord] = {}
    error_actions: dict[str, ActionTraceRecord] = {}
    canceled_actions: dict[str, ActionTraceRecord] = {}

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
        error_actions[start_trace.trace_id] = trace

    def action_canceled(trace: ActionTraceRecord) -> None:
        canceled_actions[start_trace.trace_id] = trace

    for trace in traces:
        if isinstance(trace, ActionTraceRecord):
            match trace.event:
                case "enter":
                    action_started(trace)
                case "exit":
                    action_completed(trace)
                case "cancel":
                    # Complete with a cancellation
                    start_trace = action_completed(trace)

                    # add duration
                    trace.start_time = start_trace.start_time

                    action_canceled(trace)
                case "error":
                    # Capture error events
                    start_trace = action_completed(trace)

                    # add start time
                    trace.start_time = start_trace.start_time

                    action_failed(trace)
                    continue
                case _:
                    print(f"Unknown event type: {trace.event}")

    with open(os.devnull, "w") as f:
        # generate output
        console = Console(record=True, file=f)

        def print_fn(o: RenderableType) -> None:
            console.print(o, highlight=False)

        _print_bucket(print_fn, "Running Actions", running_actions)
        _print_bucket(print_fn, "Canceled Actions", canceled_actions)
        _print_bucket(print_fn, "Error Actions", error_actions)

        # display with 'less' if possible
        less = shutil.which("less")
        if less:
            subprocess.run(
                [less, "-R"], input=console.export_text(styles=True).encode()
            )
        else:
            print(console.export_text(styles=False))


def _print_bucket(
    print_fn: Callable[[str], None], label: str, bucket: dict[str, ActionTraceRecord]
) -> None:
    if len(bucket) > 0:
        # Sort the items in chronological order of when
        # they finished so the first finished item is at the top
        sorted_actions = sorted(
            bucket.values(),
            key=lambda record: (record.start_time or 0) + (record.duration or 0),
            reverse=True,
        )

        print_fn(f"[bold]{label}[/bold]")
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
            if action.event == "error":
                # print errors
                print_fn(
                    f"{start_time} ({round(duration, 2)}s): {action.message} {action.error}"
                )
            else:
                # print the action
                print_fn(f"{start_time} ({round(duration, 2)}s): {action.message}")
        print_fn("")


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
    # ISO format with timezone
    dt = datetime.fromtimestamp(timestamp)
    return dt.isoformat()
