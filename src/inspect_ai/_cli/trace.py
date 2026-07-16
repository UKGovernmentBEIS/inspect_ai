import os
import shlex
import time
from datetime import datetime
from json import dumps
from pathlib import Path
from typing import Callable, NamedTuple

import click
from pydantic import JsonValue
from pydantic_core import to_json
from rich import print as r_print
from rich.console import Console, RenderableType
from rich.table import Column, Table

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.trace import (
    ActionTraceRecord,
    TraceRecord,
    inspect_trace_dir,
    list_trace_files,
    read_trace_file,
)


@click.group("trace")
def trace_command() -> None:
    """List and read execution traces.

    Inspect includes a TRACE log-level which is right below the HTTP and INFO log levels (so not written to the console by default). However, TRACE logs are always recorded to a separate file, and the last 10 TRACE logs are preserved. The 'trace' command provides ways to list and read these traces.

    Learn more about execution traces at https://inspect.aisi.org.uk/tracing.html.
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
    list_command_impl(json)


def list_command_impl(json: bool, trace_dir: Path | None = None) -> None:
    """List all trace files."""
    trace_files = list_trace_files(trace_dir)
    if json:
        print(
            dumps(
                [dict(file=str(file.file), mtime=file.mtime) for file in trace_files],
                indent=2,
            )
        )
    else:
        table = Table(box=None, show_header=True, pad_edge=False)
        table.add_column("Time")
        table.add_column("Trace File")
        for file in trace_files:
            mtime = datetime.fromtimestamp(file.mtime).astimezone()
            table.add_row(
                mtime.strftime("%d-%b %H:%M:%S %Z"), shlex.quote(str(file.file))
            )
        r_print(table)


@trace_command.command("dump")
@click.argument("trace-file", type=str, required=False)
@click.option(
    "--filter",
    type=str,
    help="Filter (applied to trace message field).",
)
def dump_command(trace_file: str | None, filter: str | None) -> None:
    """Dump a trace file to stdout (as a JSON array of log records)."""
    dump_command_impl(trace_file, filter)


def dump_command_impl(
    trace_file: str | None, filter: str | None, trace_dir: Path | None = None
) -> None:
    """Dump a trace file to stdout (as a JSON array of log records)."""
    trace_file_path = _resolve_trace_file_path(trace_file, trace_dir)

    traces = read_trace_file(trace_file_path)

    if filter:
        filter = filter.lower()
        traces = [trace for trace in traces if filter in trace.message.lower()]

    print(
        to_json(traces, indent=2, exclude_none=True, fallback=lambda _: None).decode()
    )


@trace_command.command("http")
@click.argument("trace-file", type=str, required=False)
@click.option(
    "--filter",
    type=str,
    help="Filter (applied to trace message field).",
)
@click.option(
    "--failed",
    type=bool,
    is_flag=True,
    default=False,
    help="Show only failed HTTP requests (non-200 status)",
)
@click.option(
    "--json",
    type=bool,
    is_flag=True,
    default=False,
    help="Output as JSON (a `{trace_file, as_of, requests}` envelope).",
)
def http_command(
    trace_file: str | None, filter: str | None, failed: bool, json: bool
) -> None:
    """View all HTTP requests in the trace log."""
    http_command_impl(trace_file, filter, failed, json)


def http_command_impl(
    trace_file: str | None,
    filter: str | None,
    failed: bool,
    json: bool = False,
    trace_dir: Path | None = None,
) -> None:
    """View all HTTP requests in the trace log."""
    trace_file_path, traces = _read_traces(trace_file, "HTTP", filter, trace_dir)

    requests = [trace for trace in traces if not (failed and "200 OK" in trace.message)]

    if json:
        print(
            dumps(
                {
                    "trace_file": trace_file_path.as_posix(),
                    "as_of": time.time(),
                    "requests": [
                        {"timestamp": trace.timestamp, "message": trace.message}
                        for trace in requests
                    ],
                },
                indent=2,
            )
        )
        return

    last_timestamp = ""
    table = Table(Column(), Column(), box=None)
    for trace in requests:
        timestamp = trace.timestamp.split(".")[0]
        if timestamp == last_timestamp:
            timestamp = ""
        else:
            last_timestamp = timestamp
            timestamp = f"[{timestamp}]"
        table.add_row(timestamp, trace.message)

    if table.row_count > 0:
        r_print(table)


def anomalies_options(func: Callable[..., None]) -> Callable[..., None]:
    """Flags for anomaly-reading commands.

    Single home for the options of `inspect trace anomalies` and the planned
    `inspect ctl process anomalies` so the two entry points cannot drift as
    flags are added (see "Trace-log anomalies for stall diagnosis" in
    design/control-channel.md).
    """
    func = click.option(
        "--json",
        type=bool,
        is_flag=True,
        default=False,
        help="Output as JSON (a `{trace_file, as_of, running, cancelled, errors, timeouts}` envelope).",
    )(func)
    func = click.option(
        "--all",
        is_flag=True,
        default=False,
        help="Show all anomolies including errors and timeouts (by default only still running and cancelled actions are shown).",
    )(func)
    func = click.option(
        "--filter",
        type=str,
        help="Filter (applied to trace message field).",
    )(func)
    return func


@trace_command.command("anomalies")
@click.argument("trace-file", type=str, required=False)
@anomalies_options
def anomolies_command(
    trace_file: str | None, filter: str | None, all: bool, json: bool
) -> None:
    """Look for anomalies in a trace file (never completed or cancelled actions)."""
    anomolies_command_impl(trace_file, filter, all, json)


class TraceAnomalies(NamedTuple):
    """Anomalous actions from a trace file, bucketed by outcome.

    Buckets are sorted most recently finished first (running actions by start
    time). ``errors`` and ``timeouts`` are collected only when requested via
    ``all`` (they are empty lists otherwise).
    """

    running: list[ActionTraceRecord]
    cancelled: list[ActionTraceRecord]
    errors: list[ActionTraceRecord]
    timeouts: list[ActionTraceRecord]


def anomolies_command_impl(
    trace_file: str | None,
    filter: str | None,
    all: bool,
    json: bool = False,
    trace_dir: Path | None = None,
) -> None:
    """Look for anomalies in a trace file (never completed or cancelled actions)."""
    trace_file_path, traces = _read_traces(trace_file, None, filter, trace_dir)
    anomalies = _trace_anomalies(traces, all)

    if json:
        # stamp as_of once and compute running durations against it so the
        # envelope timestamp and the durations it dates are consistent
        as_of = time.time()
        print(
            dumps(
                {
                    "trace_file": trace_file_path.as_posix(),
                    "as_of": as_of,
                    "running": [_anomaly_row(a, as_of) for a in anomalies.running],
                    "cancelled": [_anomaly_row(a, as_of) for a in anomalies.cancelled],
                    "errors": [_anomaly_row(a, as_of) for a in anomalies.errors],
                    "timeouts": [_anomaly_row(a, as_of) for a in anomalies.timeouts],
                },
                indent=2,
            )
        )
        return

    # do we have any traces?
    if (
        len(anomalies.running)
        + len(anomalies.cancelled)
        + len(anomalies.errors)
        + len(anomalies.timeouts)
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

        print_fn(f"[bold]TRACE: {shlex.quote(trace_file_path.as_posix())}[/bold]")

        _print_bucket(print_fn, "Running Actions", anomalies.running)
        _print_bucket(print_fn, "Cancelled Actions", anomalies.cancelled)
        _print_bucket(print_fn, "Error Actions", anomalies.errors)
        _print_bucket(print_fn, "Timeout Actions", anomalies.timeouts)

        # print
        print(console.export_text(styles=True).strip())


def _trace_anomalies(traces: list[TraceRecord], all: bool) -> TraceAnomalies:
    """Reconstruct anomalous actions (never exited, cancelled, errored, timed out) from trace records.

    Shared by the human and JSON renderings of `inspect trace anomalies` (and,
    per the design, the planned `inspect ctl process anomalies`) so every entry
    point derives the same answer from the same records.
    """
    # Track started actions
    running_actions: dict[str, ActionTraceRecord] = {}
    canceled_actions: dict[str, ActionTraceRecord] = {}
    error_actions: dict[str, ActionTraceRecord] = {}
    timeout_actions: dict[str, ActionTraceRecord] = {}
    start_trace: ActionTraceRecord | None = None

    def action_started(trace: ActionTraceRecord) -> None:
        running_actions[trace.trace_id] = trace

    def action_completed(trace: ActionTraceRecord) -> ActionTraceRecord:
        nonlocal start_trace
        start_trace = running_actions.get(trace.trace_id)
        if start_trace:
            del running_actions[trace.trace_id]
            return start_trace
        else:
            raise RuntimeError(f"Expected {trace.trace_id} in action dictionary.")

    def action_failed(trace: ActionTraceRecord) -> None:
        nonlocal start_trace
        if all:
            assert start_trace
            error_actions[start_trace.trace_id] = trace

    def action_canceled(trace: ActionTraceRecord) -> None:
        nonlocal start_trace
        assert start_trace
        canceled_actions[start_trace.trace_id] = trace

    def action_timeout(trace: ActionTraceRecord) -> None:
        nonlocal start_trace
        if all:
            assert start_trace
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

    return TraceAnomalies(
        running=_sorted_actions(running_actions),
        cancelled=_sorted_actions(canceled_actions),
        errors=_sorted_actions(error_actions),
        timeouts=_sorted_actions(timeout_actions),
    )


def _sorted_actions(bucket: dict[str, ActionTraceRecord]) -> list[ActionTraceRecord]:
    # Sort the items in chronological order of when
    # they finished so the first finished item is at the top
    return sorted(
        bucket.values(),
        key=lambda record: (record.start_time or 0) + (record.duration or 0),
        reverse=True,
    )


def _action_duration(action: ActionTraceRecord, as_of: float) -> float:
    """Duration of the action: the recorded duration for finished actions, time since start (as of `as_of`) for still-running ones."""
    if action.duration is not None:
        return action.duration
    elif action.start_time is not None:
        return as_of - action.start_time
    else:
        return 0.0


def _anomaly_row(action: ActionTraceRecord, as_of: float) -> dict[str, JsonValue]:
    row: dict[str, JsonValue] = {
        "action": action.action,
        "detail": action.detail or action.message,
        "start_time": action.start_time,
        "duration": _action_duration(action, as_of),
    }
    if action.error is not None:
        row["error"] = action.error
    return row


def _read_traces(
    trace_file: str | None,
    level: str | None = None,
    filter: str | None = None,
    trace_dir: Path | None = None,
) -> tuple[Path, list[TraceRecord]]:
    trace_file_path = _resolve_trace_file_path(trace_file, trace_dir)
    traces = read_trace_file(trace_file_path)

    if level:
        traces = [trace for trace in traces if trace.level == level]

    if filter:
        filter = filter.lower()
        traces = [trace for trace in traces if filter in trace.message.lower()]

    return (trace_file_path, traces)


def _print_bucket(
    print_fn: Callable[[RenderableType], None],
    label: str,
    sorted_actions: list[ActionTraceRecord],
) -> None:
    if len(sorted_actions) > 0:
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

        now = time.time()
        for action in sorted_actions:
            # Compute duration (use the event duration or time since started)
            duration = _action_duration(action, now)

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


def _resolve_trace_file(trace_file: str | None, trace_dir: Path | None = None) -> str:
    if trace_file is None:
        trace_files = list_trace_files(trace_dir)
        if len(trace_files) == 0:
            raise PrerequisiteError("No trace files currently availalble.")
        trace_file = str(trace_files[0].file)
    return trace_file


def _resolve_trace_file_path(
    trace_file: str | None, trace_dir: Path | None = None
) -> Path:
    trace_dir = trace_dir or inspect_trace_dir()
    trace_file = _resolve_trace_file(trace_file, trace_dir)
    trace_file_path = Path(trace_file)
    if not trace_file_path.is_absolute():
        trace_file_path = trace_dir / trace_file_path

    if not trace_file_path.exists():
        raise PrerequisiteError(
            f"The specified trace file '{trace_file_path}' does not exist."
        )

    return trace_file_path


def formatTime(timestamp: float) -> str:
    dt = datetime.fromtimestamp(timestamp).astimezone()
    return dt.strftime("%H:%M:%S %Z")
