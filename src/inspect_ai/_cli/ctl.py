"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts every command that operates on a *running*
Inspect eval (list, status, cancel, drain, requeue, events, ...). See
``design/control-channel.md`` for the design.

Current scope: ``ls`` (enumerate live evals), ``samples`` (list a
task's samples), and ``shutdown`` (release a ``--keep-alive``
process). Each talks to the per-process control server's HTTP endpoints.
"""

from __future__ import annotations

import json as json_lib
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, NoReturn

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

    A process exits when its eval finishes; launch with ``inspect eval
    --keep-alive`` to keep it inspectable (and its results readable) here
    until you run ``inspect ctl shutdown``.
    """
    return None


def _echo_no_running_evals() -> None:
    """Print the 'nothing to show' message shared by the read commands.

    Surfaces ``--keep-alive`` here because this fires exactly when a user
    is confused that a just-finished eval isn't listed — its process has
    already exited unless it was launched to park.
    """
    click.echo(
        f"No running evals found in {discovery_dir()}.\n"
        "Start an eval with `inspect eval <task>` — add `--keep-alive` to keep "
        "the process inspectable after the eval finishes."
    )


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
        _echo_no_running_evals()
        return

    _print_human_table(summaries)


@ctl_command.command("samples")
@click.argument("task", required=False)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (one array of sample summaries).",
)
def samples_command(task: str | None, as_json: bool) -> None:
    """List the samples (running and completed) of a running eval.

    TASK selects the task (as shown by `inspect ctl ls`): a task id (or
    unique prefix), or a task name. A task id is stable across retries —
    unlike a per-attempt eval id, it still resolves after a task errors
    and is retried. A name matches at the start of the task name or after
    a `/` (so `gpqa` matches `inspect_evals/gpqa_diamond`). If omitted and
    exactly one task is running, that task is used.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("[]")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    # Query by the task's current eval id (resolved fresh each invocation,
    # so this still works after a retry minted a new one).
    samples = _fetch_samples(target["socket_path"], target["eval_id"])

    if as_json:
        click.echo(json_lib.dumps(samples, indent=2))
        return

    click.echo(_task_header(target))
    if not samples:
        click.echo("(no samples started yet)")
        return
    click.echo()
    _print_samples_table(samples)


@ctl_command.command("errors")
@click.argument("task", required=False)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (one array of errored/retried samples).",
)
def errors_command(task: str | None, as_json: bool) -> None:
    """List the samples of a running eval that errored or were retried.

    A triage overview: one row per sample with a current error or any
    retries, showing the latest error message. Drill into a single sample's
    full error history (including prior attempts) with `inspect ctl sample`.

    TASK selects the task as in `inspect ctl samples`.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("[]")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    samples = _fetch_samples(target["socket_path"], target["eval_id"])
    errored = [s for s in samples if s.get("error") or (s.get("retries") or 0) > 0]

    if as_json:
        click.echo(json_lib.dumps(errored, indent=2))
        return

    click.echo(_task_header(target))
    if not errored:
        click.echo("(no errors or retries)")
        return
    click.echo()
    _print_errors_table(errored)


@ctl_command.command("sample")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--traceback",
    "-t",
    "show_traceback",
    is_flag=True,
    default=False,
    help="Show the full traceback for each error (default: message only).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the sample's full error detail).",
)
def sample_command(
    task: str, sample_id: str, epoch: int, show_traceback: bool, as_json: bool
) -> None:
    """Show one sample's error detail, including errors from prior attempts.

    TASK selects the task as in `inspect ctl samples`; SAMPLE_ID is the
    sample's id (as shown by `inspect ctl samples`); EPOCH defaults to 1.

    Surfaces the current error (if the sample failed) and the error from each
    prior attempt (task-level retries and sample-level `retry_on_error`). Pass
    `--traceback` to expand full tracebacks.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    detail = _fetch_sample_detail(
        target["socket_path"], target["eval_id"], sample_id, epoch
    )

    if as_json:
        click.echo(json_lib.dumps(detail, indent=2))
        return

    _print_sample_detail(detail, show_traceback)


@ctl_command.command("shutdown")
@click.option(
    "--pid",
    type=int,
    default=None,
    help=(
        "PID of the inspect process to shut down. Required if more than one "
        "process is currently lingering."
    ),
)
def shutdown_command(pid: int | None) -> None:
    """Release a lingering inspect process (started with --keep-alive).

    Posts to the process's control endpoint /shutdown route. The eval
    has already completed; this just lets the process exit. No-op if
    the process isn't actually parked (it'll exit on its own anyway).
    """
    servers = list_discovered_servers()
    if not servers:
        click.echo("No running inspect processes found.", err=True)
        raise click.exceptions.Exit(code=1)

    if pid is not None:
        matching = [s for s in servers if s.pid == pid]
        if not matching:
            click.echo(f"No running inspect process with pid {pid}.", err=True)
            raise click.exceptions.Exit(code=1)
        target = matching[0]
    elif len(servers) == 1:
        target = servers[0]
    else:
        pids = ", ".join(str(s.pid) for s in servers)
        click.echo(
            f"Multiple inspect processes are running (pids: {pids}). "
            "Pass --pid to disambiguate.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)

    try:
        transport = httpx.HTTPTransport(uds=str(target.socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.post("/shutdown")
            response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        click.echo(f"Failed to shut down pid {target.pid}: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    click.echo(f"Shutdown requested for pid {target.pid}.")


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


def _resolve_target_eval(
    summaries: list[dict[str, Any]], query: str | None
) -> dict[str, Any]:
    """Pick the task a per-eval command targets, or exit with an error.

    ``query`` matches a task id first (full, then unique prefix — ``ls``
    shows truncated ids; ids are stable across retries), then falls back
    to the task name (see :func:`_match_by_task_name`). Without a query,
    default to the sole running task.
    """
    if query is not None:
        matches = (
            [s for s in summaries if s.get("task_id") == query]
            or [s for s in summaries if str(s.get("task_id", "")).startswith(query)]
            or _match_by_task_name(summaries, query)
        )
        if not matches:
            click.echo(f"No running task matching '{query}'.", err=True)
            raise click.exceptions.Exit(code=1)
        if len(matches) > 1:
            _exit_ambiguous(matches, f"'{query}' matches multiple tasks")
        return matches[0]

    if len(summaries) == 1:
        return summaries[0]

    _exit_ambiguous(summaries, "Multiple tasks are running")


def _match_by_task_name(
    summaries: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Match summaries by task name, anchored at the name start or after a ``/``.

    So ``gpqa`` matches ``inspect_evals/gpqa_diamond`` (leaf prefix) but
    not ``failing_gpqa_diamond`` (mid-name). An exact name/leaf match wins
    over prefix matches, so ``gpqa`` resolves cleanly even when both
    ``gpqa`` and ``gpqa_diamond`` are running.
    """

    def leaf(name: str) -> str:
        return name.rsplit("/", 1)[-1]

    prefix = [
        s
        for s in summaries
        if str(s.get("task", "")).startswith(query)
        or leaf(str(s.get("task", ""))).startswith(query)
    ]
    exact = [
        s
        for s in prefix
        if str(s.get("task", "")) == query or leaf(str(s.get("task", ""))) == query
    ]
    return exact or prefix


def _exit_ambiguous(matches: list[dict[str, Any]], prefix: str) -> NoReturn:
    """Echo an ambiguity error listing ``task_id (name)`` and exit."""
    listing = ", ".join(
        f"{_short_id(s.get('task_id', ''))} ({s.get('task') or '?'})" for s in matches
    )
    click.echo(f"{prefix} ({listing}). Pass a task id to choose one.", err=True)
    raise click.exceptions.Exit(code=1)


def _fetch_samples(socket_path: str, eval_id: str) -> list[dict[str, Any]]:
    """Query one control server for an eval's in-flight samples."""
    try:
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get(f"/evals/{eval_id}/samples")
            response.raise_for_status()
            rows = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(
            f"Failed to read samples for eval {eval_id}: {_error_detail(exc)}",
            err=True,
        )
        raise click.exceptions.Exit(code=1) from exc
    return rows if isinstance(rows, list) else []


def _fetch_sample_detail(
    socket_path: str, eval_id: str, sample_id: str, epoch: int
) -> dict[str, Any]:
    """Query one control server for a single sample's full error detail."""
    try:
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            # sample_id goes in the query string (httpx URL-encodes it) so
            # ids containing `/`, `?`, `#`, etc. address correctly — they
            # can't be carried as a path segment.
            response = client.get(
                f"/evals/{eval_id}/sample",
                params={"sample_id": sample_id, "epoch": epoch},
            )
            if response.status_code == 404:
                click.echo(
                    f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
                    "still be running or not yet written to the log.",
                    err=True,
                )
                raise click.exceptions.Exit(code=1)
            response.raise_for_status()
            detail = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(f"Failed to read sample: {_error_detail(exc)}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    return detail if isinstance(detail, dict) else {}


def _print_errors_table(samples: list[dict[str, Any]]) -> None:
    """Render errored/retried samples as a triage table on stdout."""
    rows: list[tuple[str, ...]] = []
    for s in samples:
        rows.append(
            (
                str(s["sample_id"]) if s.get("sample_id") is not None else "?",
                str(s.get("epoch", "")),
                s.get("status", "") or "",
                str(s["retries"]) if s.get("retries") else "",
                _truncate(s.get("error") or "", 64),
            )
        )
    _render_table(("sample", "epoch", "status", "retries", "error"), rows)


def _print_sample_detail(detail: dict[str, Any], show_traceback: bool) -> None:
    """Render one sample's error history (prior attempts, then final error)."""
    parts = [
        f"sample {detail.get('sample_id')}",
        f"epoch {detail.get('epoch')}",
        detail.get("status") or "",
    ]
    if detail.get("retries"):
        parts.append(f"{detail['retries']} retries")
    scores = detail.get("scores") or {}
    if scores:
        parts.append(
            "score " + ", ".join(f"{k}={_format_score(v)}" for k, v in scores.items())
        )
    click.echo("  ·  ".join(p for p in parts if p))

    error = detail.get("error")
    retries = detail.get("error_retries") or []
    if not error and not retries:
        click.echo("\n(no errors)")
        return

    if retries:
        click.echo("\nprior attempts:")
        for i, retry_error in enumerate(retries, start=1):
            _echo_error(f"attempt {i}:", retry_error, show_traceback)
    if error:
        click.echo("\nfinal error:")
        _echo_error("", error, show_traceback)


def _echo_error(label: str, error: dict[str, Any], show_traceback: bool) -> None:
    """Echo one error: ``label  message`` plus an indented traceback if asked."""
    message = error.get("message") or ""
    click.echo(f"  {label} {message}".rstrip() if label else f"  {message}")
    if show_traceback:
        traceback = error.get("traceback_ansi") or error.get("traceback") or ""
        for line in traceback.rstrip("\n").splitlines():
            click.echo(f"    {line}")


def _truncate(text: str, width: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def _error_detail(exc: Exception) -> str:
    """Prefer the server's ``{"error": ...}`` body over the bare HTTP error."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    return str(exc)


def _print_human_table(summaries: list[dict[str, Any]]) -> None:
    """Render eval summaries as a simple aligned table on stdout."""
    # Show errors / attempts columns only when at least one row has
    # something interesting to report there — keeps the common case
    # (no errors, no retries) uncluttered.
    any_errors = any((s.get("samples") or {}).get("errored", 0) > 0 for s in summaries)
    any_retries = any(int(s.get("attempts", 1) or 1) > 1 for s in summaries)

    rows = []
    for s in summaries:
        samples = s.get("samples") or {}
        # task_id (not eval_id): stable across retries, and the handle
        # `inspect ctl samples` takes.
        cells = [
            _short_id(s.get("task_id", "")),
            s.get("task", "?") or "?",
            _format_samples(samples),
            _format_started(s.get("started_at", 0)),
        ]
        if any_errors:
            cells.insert(3, str(samples.get("errored", 0)))
        if any_retries:
            cells.append(str(int(s.get("attempts", 1) or 1)))
        rows.append(tuple(cells))

    headers_list = ["task_id", "task", "samples", "started"]
    if any_errors:
        headers_list.insert(3, "errors")
    if any_retries:
        headers_list.append("attempts")

    _render_table(tuple(headers_list), rows)


def _task_header(target: dict[str, Any]) -> str:
    """One-line summary of the task above its sample table.

    e.g. ``inspect_evals/gpqa_diamond (ZByxJpK4bKSz)  ·  openai/gpt-5-nano
    ·  running  ·  12/40 (3 running)``.
    """
    name = target.get("task") or "?"
    short = _short_id(str(target.get("task_id", "")))
    parts = [f"{name} ({short})" if short else name]
    if target.get("model"):
        parts.append(str(target["model"]))
    if target.get("status"):
        parts.append(str(target["status"]))
    parts.append(_format_samples(target.get("samples") or {}))
    attempts = int(target.get("attempts", 1) or 1)
    if attempts > 1:
        parts.append(f"{attempts} attempts")
    return "  ·  ".join(parts)


def _print_samples_table(samples: list[dict[str, Any]]) -> None:
    """Render per-sample summaries as a simple aligned table on stdout.

    Two columns are conditional, shown only when relevant (keeping the
    common case uncluttered):
    - ``retries`` — when some sample was retried on error. Per-sample
      (sample-level ``retry_on_error``); blank for samples with none.
    - ``score`` — when the samples have exactly one scorer (multi-scorer
      rendering is a later refinement). Running samples aren't scored yet,
      so their cell is blank.
    """
    any_retries = any((s.get("retries") or 0) > 0 for s in samples)
    scorers = sorted({name for s in samples for name in (s.get("scores") or {})})
    score_col = scorers[0] if len(scorers) == 1 else None

    rows: list[tuple[str, ...]] = []
    for s in samples:
        row = [
            str(s["sample_id"]) if s.get("sample_id") is not None else "?",
            str(s.get("epoch", "")),
            s.get("status", "") or "",
        ]
        if any_retries:
            row.append(str(s["retries"]) if s.get("retries") else "")
        if score_col is not None:
            row.append(_format_score((s.get("scores") or {}).get(score_col)))
        row.extend(
            [
                _format_duration(s.get("total_time")),
                str(s.get("total_tokens", 0)),
                str(s.get("message_count") or 0),
            ]
        )
        rows.append(tuple(row))

    headers = ["sample", "epoch", "status"]
    if any_retries:
        headers.append("retries")
    if score_col is not None:
        headers.append("score")
    headers.extend(["time", "tokens", "messages"])
    _render_table(tuple(headers), rows)


def _render_table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> None:
    """Print an aligned, dashed-underline table to stdout."""
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

    ``done`` = ``completed + errored + cancelled`` (terminal counts).
    """
    total = int(samples.get("total", 0) or 0)
    completed = int(samples.get("completed", 0) or 0)
    errored = int(samples.get("errored", 0) or 0)
    cancelled = int(samples.get("cancelled", 0) or 0)
    in_flight = int(samples.get("in_flight", 0) or 0)
    queued = int(samples.get("queued", 0) or 0)

    done = completed + errored + cancelled
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


def _format_duration(seconds: float | None) -> str:
    """Compact elapsed time: ``M:SS`` (under an hour) or ``H:MM:SS``."""
    if not seconds or seconds < 0:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_score(value: Any) -> str:
    """Compact score-value cell (floats trimmed; other values stringified)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
