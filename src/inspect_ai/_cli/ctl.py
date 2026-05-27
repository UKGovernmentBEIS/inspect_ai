"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts every command that operates on a *running*
Inspect eval (list, status, cancel, drain, requeue, events, ...). See
``design/control-channel.md`` for the design.

MVP scope: a single ``ls`` subcommand that enumerates live evals by
querying each discovered control server's ``GET /evals`` endpoint.
"""

from __future__ import annotations

import json as json_lib
from datetime import datetime, timezone
from typing import Any

import click
import httpx

from inspect_ai._control.discovery import (
    DiscoveredControlServer,
    discovery_dir,
    list_discovered_servers,
)


@click.group("ctl")
def ctl_command() -> None:
    """Manage running evals (list, cancel, drain, modify limits, ...).

    Each command operates on a live Inspect eval via the control
    channel — the HTTP server every running ``inspect eval`` process
    binds by default.
    """
    return None


@ctl_command.command("ls")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (one array of eval summaries).",
)
def ls_command(as_json: bool) -> None:
    """List running evals across all live Inspect processes."""
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers)

    if as_json:
        click.echo(json_lib.dumps(summaries, indent=2))
        return

    if not summaries:
        click.echo(
            f"No running evals found in {discovery_dir()}.\n"
            "Start an eval with `inspect eval <task>` and try again."
        )
        return

    _print_human_table(summaries)


def _fetch_summaries(
    servers: list[DiscoveredControlServer],
) -> list[dict[str, Any]]:
    """Query each discovered control server for its eval summary."""
    summaries: list[dict[str, Any]] = []
    for server in servers:
        try:
            transport = httpx.HTTPTransport(uds=str(server.socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                response = client.get("/evals")
                response.raise_for_status()
                rows = response.json()
                if isinstance(rows, list):
                    # Decorate each row with discovery-side info the
                    # server doesn't see (pid, socket_path).
                    for row in rows:
                        row["pid"] = server.pid
                        row["socket_path"] = str(server.socket_path)
                    summaries.extend(rows)
        except (httpx.HTTPError, OSError, ValueError):
            # Skip unreachable / malformed servers — they may have just
            # exited between discovery and connect.
            continue
    return summaries


def _print_human_table(summaries: list[dict[str, Any]]) -> None:
    """Render summaries as a simple aligned table on stdout."""
    # Build all rows first so we can decide whether to show the
    # errors column (only when at least one eval has errors > 0).
    any_errors = any((s.get("samples") or {}).get("errored", 0) > 0 for s in summaries)

    rows = []
    for s in summaries:
        samples = s.get("samples") or {}
        errors_cell = str(samples.get("errored", 0)) if any_errors else None
        cells = [
            _short_id(s.get("eval_id", "")),
            s.get("task", "?") or "?",
            _format_samples(samples),
            _format_started(s.get("started_at", 0)),
        ]
        if errors_cell is not None:
            cells.insert(3, errors_cell)
        rows.append(tuple(cells))

    headers_list = ["eval_id", "task", "samples", "started"]
    if any_errors:
        headers_list.insert(3, "errors")
    headers = tuple(headers_list)

    widths = [
        max(len(h), max((len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]

    def _fmt_row(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    click.echo(_fmt_row(headers))
    click.echo(_fmt_row(tuple("-" * w for w in widths)))
    for row in rows:
        click.echo(_fmt_row(row))


def _format_samples(samples: dict[str, Any]) -> str:
    """Compact one-cell representation of sample progress.

    Shape:
    - ``done/total (N running)`` when samples are in flight
    - ``done/total (complete)`` when total > 0 and nothing in flight + nothing queued
    - ``0/total (queued)`` when no samples started yet
    - ``done/total`` as the bland fallback

    ``done`` = ``completed + errored`` (terminal counts).
    """
    total = int(samples.get("total", 0) or 0)
    completed = int(samples.get("completed", 0) or 0)
    errored = int(samples.get("errored", 0) or 0)
    in_flight = int(samples.get("in_flight", 0) or 0)
    queued = int(samples.get("queued", 0) or 0)

    done = completed + errored
    if total == 0:
        # No total recorded — show in_flight as a single number so
        # the user sees something useful pre-EvalState registration.
        return f"{in_flight} running" if in_flight else "starting"

    if in_flight > 0:
        return f"{done}/{total} ({in_flight} running)"
    if done >= total:
        return f"{done}/{total} (complete)"
    if queued == total:
        return f"0/{total} (queued)"
    return f"{done}/{total}"


def _short_id(identifier: str) -> str:
    """Trim a long uuid for display — full id is in --json output."""
    if len(identifier) <= 12:
        return identifier
    return identifier[:12]


def _format_started(started_at: float) -> str:
    if not started_at:
        return ""
    try:
        return datetime.fromtimestamp(float(started_at), tz=timezone.utc).strftime(
            "%H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return ""
