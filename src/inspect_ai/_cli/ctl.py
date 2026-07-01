"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts the commands that operate on a *running* Inspect
eval via the per-process control server's HTTP endpoints. See
``design/control-channel.md`` for the design.

Implemented (read surface + keep-alive): ``tasks`` (enumerate running
tasks, with a keep-alive status footer), ``samples`` (a task's samples),
``sample`` (one sample's error detail), ``errors`` (errored / retried samples),
``events`` (a sample's transcript events), ``keep`` (make a running process
park after its eval finishes), and ``release`` (let a kept-alive process exit).
The buffer directives ``flush`` (write buffered samples to the log now) and
``buffer`` (view / change the sample-buffer params) are also available, as is
``limits`` (view / change the ``max_samples`` / ``max_sandboxes`` /
``max_connections`` concurrency limits mid-flight). The remaining state-mutating
directives (cancel / drain /
requeue) are planned but not yet available.
"""

from __future__ import annotations

import json as json_lib
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
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
    """Read the state of running evals and manage kept-alive processes.

    Commands: ``tasks`` (running tasks + keep-alive status), ``samples`` /
    ``sample`` / ``errors`` (an eval's samples), ``events`` (a sample's
    transcript), ``keep`` (park a process after its eval finishes), ``release``
    (let a kept-alive process exit), ``flush`` (write an eval's buffered samples
    to the log now), ``buffer`` (view / change the sample-buffer params),
    ``limits`` (view / change the ``max_samples`` / ``max_sandboxes`` /
    ``max_connections`` concurrency limits). All are read-only except ``keep`` /
    ``release`` / ``flush`` /
    ``buffer`` / ``limits`` — further state-mutating directives (cancel, drain)
    are planned but not yet available.

    Each command operates on a live Inspect eval via the control
    channel — the HTTP server every running ``inspect eval`` process
    binds by default.

    A process exits when its eval finishes; launch with ``inspect eval
    --ctl-server=keep`` to keep it inspectable (and its results
    readable) here until you run ``inspect ctl release``.
    """
    return None


def _echo_no_running_evals() -> None:
    """Print the 'nothing to show' message shared by the read commands.

    Surfaces ``--ctl-server=keep`` here because this fires exactly
    when a user is confused that a just-finished eval isn't listed — its
    process has already exited unless it was launched to park.
    """
    click.echo(
        f"No running evals found in {discovery_dir()}.\n"
        "Start an eval with `inspect eval <task>` — add `--ctl-server=keep` "
        "to keep the process inspectable after the eval finishes."
    )


@ctl_command.command("tasks")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (one array of task summaries).",
)
def tasks_command(as_json: bool) -> None:
    """List running tasks across all live Inspect processes."""
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers)

    if as_json:
        click.echo(json_lib.dumps(summaries, indent=2))
        return

    if not summaries:
        _echo_no_running_evals()
        return

    _print_human_table(summaries)
    _print_keep_alive_footer(summaries)


@ctl_command.command("samples")
@click.argument("task", required=False)
@click.option(
    "--active-since",
    type=float,
    default=None,
    help=(
        "Only samples that started or were updated at/after this unix "
        "timestamp — the 'what changed since I last looked' delta."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (one array of sample summaries).",
)
def samples_command(
    task: str | None, active_since: float | None, as_json: bool
) -> None:
    """List the samples (running and completed) of a running eval.

    TASK selects the task (as shown by `inspect ctl tasks`): a task id (or
    unique prefix), or a task name. A task id is stable across retries —
    unlike a per-attempt eval id, it still resolves after a task errors
    and is retried. A name matches at the start of the task name or after
    a `/` (so `gpqa` matches `inspect_evals/gpqa_diamond`). If omitted and
    exactly one task is running, that task is used.

    Pass `--active-since <ts>` to get only the samples that changed since a
    prior poll (started or last active at/after that time).
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
    samples = _fetch_samples(target["socket_path"], target["eval_id"], active_since)

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

    TASK selects which running eval to target — a task-id prefix or task name
    (as listed by `inspect ctl tasks`); omit it when only one eval is running.
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

    TASK selects which running eval to target (a task-id prefix or task name,
    as listed by `inspect ctl tasks`); SAMPLE_ID is the
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


@ctl_command.command("events")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--since",
    default=None,
    help="Resume after this cursor (the `next` from a prior call).",
)
@click.option(
    "--tail",
    type=int,
    default=None,
    help="Start this many events from the end (when --since is not given).",
)
@click.option(
    "--type",
    "types",
    default=None,
    help=(
        "Comma-separated event types to include (e.g. `model,tool,error`); "
        "`*` for all. Default: the high-signal set."
    ),
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Return raw events instead of the compact summary.",
)
@click.option(
    "--since-time",
    type=float,
    default=None,
    help="Only events at/after this unix timestamp.",
)
@click.option(
    "--until",
    type=float,
    default=None,
    help="Only events at/before this unix timestamp.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the `{events, next, done}` envelope).",
)
def events_command(
    task: str,
    sample_id: str,
    epoch: int,
    since: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    """Read one running sample's transcript events (cursored pull).

    TASK selects which running eval to target (a task-id prefix or task name,
    as listed by `inspect ctl tasks`); SAMPLE_ID is the
    sample's id; EPOCH defaults to 1.

    Returns a page of events plus a `next` cursor — pass it back via `--since`
    to get only what's new, without re-reading what you've seen. Filter with
    `--type`, take the tail with `--tail`, expand raw events with `--full`.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo('{"events": [], "next": null, "done": true}')
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    page = _fetch_sample_events(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        since=since,
        tail=tail,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
    )

    if as_json:
        click.echo(json_lib.dumps(page, indent=2))
        return

    _print_events(page)


@ctl_command.command("keep")
@click.option(
    "--pid",
    type=int,
    default=None,
    help=(
        "PID of the inspect process to keep alive. Required if more than one "
        "process is currently running."
    ),
)
def keep_command(pid: int | None) -> None:
    """Keep a running inspect process alive after its eval finishes.

    Posts to the process's control endpoint /keep route, latching keep-alive:
    the process parks after the eval finishes (until `inspect ctl release` or
    Ctrl+C) instead of exiting. The inverse of `release`. Use it to make a
    process you launched WITHOUT `--ctl-server=keep` inspectable — its
    state readable, its log final — after the eval completes.

    Issued while the eval is still running, it takes effect when the eval
    finishes; the keep-alive status shown by `inspect ctl tasks` flips to on.
    `keep` and `release` are last-write-wins, so a `keep` issued after a
    `release` (while the eval is still running) is the last word and restores
    the park.
    """
    target = _resolve_target_server(pid)
    try:
        _post_to_server(target.socket_path, "/keep")
    except (httpx.HTTPError, OSError) as exc:
        click.echo(f"Failed to set keep-alive for pid {target.pid}: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    click.echo(f"Keep-alive requested for pid {target.pid}.")


@ctl_command.command("release")
@click.option(
    "--pid",
    type=int,
    default=None,
    help=(
        "PID of the inspect process to release. Required if more than one "
        "process is currently lingering."
    ),
)
def release_command(pid: int | None) -> None:
    """Release a lingering --ctl-server=keep process so it can exit.

    Posts to the process's control endpoint /release route, letting a parked
    process exit. Issued while the eval is still running it means "exit when
    done" — the process skips the keep-alive park and exits as soon as the
    eval finishes — unless a later `keep` overrides it (`keep` and `release`
    are last-write-wins).

    Does NOT cancel a running eval — it has no effect on in-flight samples
    (cancelling a running eval is a later-phase directive, not yet available).
    """
    target = _resolve_target_server(pid)
    try:
        _post_to_server(target.socket_path, "/release")
    except (httpx.HTTPError, OSError) as exc:
        click.echo(f"Failed to release pid {target.pid}: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    click.echo(f"Release requested for pid {target.pid}.")


@ctl_command.command("flush")
@click.argument("task", required=False)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the `{flushed}` result).",
)
def flush_command(task: str | None, as_json: bool) -> None:
    """Flush a running eval's buffered samples to the log now.

    Completed samples are buffered and written to the (possibly remote, eg. S3)
    log only once the flush buffer fills. This forces that write immediately, so
    the samples become readable / analyzable in the log without waiting. Safe to
    repeat — a flush with nothing pending writes nothing.

    TASK selects which running eval to target — a task-id prefix or task name
    (as listed by `inspect ctl tasks`); omit it when only one eval is running.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    result = _post_flush(target["socket_path"], target["eval_id"])

    if as_json:
        click.echo(json_lib.dumps(result, indent=2))
        return

    flushed = int(result.get("flushed", 0) or 0)
    click.echo(_task_header(target))
    if flushed:
        click.echo(
            f"\nFlushed {flushed} sample{'' if flushed == 1 else 's'} to the log."
        )
    else:
        click.echo("\nNo buffered samples to flush.")


@ctl_command.command("buffer")
@click.argument("task", required=False)
@click.option(
    "--samples",
    "log_buffer",
    type=int,
    default=None,
    help=(
        "Set the number of completed samples to buffer before writing to the "
        "log (lower it to write to S3 more often)."
    ),
)
@click.option(
    "--shared",
    "log_shared",
    type=int,
    default=None,
    help="Set the shared-log event sync interval, in seconds.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the buffer config).",
)
def buffer_command(
    task: str | None,
    log_buffer: int | None,
    log_shared: int | None,
    as_json: bool,
) -> None:
    """View or change a running eval's sample-buffer parameters.

    With no options, shows the current config. Pass `--samples N` to change how
    many completed samples buffer before a write to the log, and/or `--shared S`
    to retune the shared-log event sync interval in seconds.

    `--samples` changes the threshold for future writes only — it does not flush
    samples already buffered. Lowering it takes effect from the next completed
    sample; to write what's already pending now, run `inspect ctl flush`.

    TASK selects which running eval to target — a task-id prefix or task name
    (as listed by `inspect ctl tasks`); omit it when only one eval is running.
    """
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    changing = log_buffer is not None or log_shared is not None
    config = _exec_buffer_config(
        target["socket_path"],
        target["eval_id"],
        log_buffer=log_buffer,
        log_shared=log_shared,
        set_values=changing,
    )

    if as_json:
        click.echo(json_lib.dumps(config, indent=2))
        return

    click.echo(_task_header(target))
    click.echo()
    _print_buffer_config(config, changed=changing)


@ctl_command.command("limits")
@click.argument("task", required=False)
@click.option(
    "--max-samples",
    type=int,
    default=None,
    help="Set the max samples to run concurrently (for this task).",
)
@click.option(
    "--max-sandboxes",
    type=int,
    default=None,
    help="Set the max sandboxes per provider (process-wide, across all tasks).",
)
@click.option(
    "--max-connections",
    type=int,
    default=None,
    help=(
        "Set the adaptive-connections scaling ceiling — the controller's max "
        "(process-wide, across all tasks)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would change without applying it (with a set option).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the limits view).",
)
def limits_command(
    task: str | None,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """View or change a running eval's concurrency limits.

    With no set options, shows the current limits. Pass `--max-samples N` to
    change how many samples run concurrently, and/or `--max-sandboxes N` to
    change the per-provider sandbox concurrency. Under adaptive connections,
    `--max-connections N` retunes the controllers' scaling ceiling instead (sample
    concurrency then follows it). Lowering a limit below what's currently in use
    blocks new work until in-flight holders drain — it never interrupts running
    samples; raising it lets more start immediately.

    Pass `--dry-run` with a set option to see what would change without applying
    it. A knob with no adjustable limiter for this eval (`--max-samples` under
    adaptive connections, `--max-sandboxes` with no sandbox limit, or
    `--max-connections` when not using adaptive connections) is reported with a
    warning rather than an error.

    TASK selects which running eval to target — a task-id prefix or task name
    (as listed by `inspect ctl tasks`); omit it when only one eval is running.
    Note that `--max-samples` is scoped to the named task, while
    `--max-sandboxes` and `--max-connections` are process-wide: in an eval-set
    (many tasks in one process) they affect every task, not just the one named.
    """
    if max_samples is not None and max_samples < 1:
        raise click.BadParameter("--max-samples must be >= 1")
    if max_sandboxes is not None and max_sandboxes < 1:
        raise click.BadParameter("--max-sandboxes must be >= 1")
    if max_connections is not None and max_connections < 1:
        raise click.BadParameter("--max-connections must be >= 1")

    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    set_values = (
        max_samples is not None
        or max_sandboxes is not None
        or max_connections is not None
    )
    config = _exec_limits(
        target["socket_path"],
        target["eval_id"],
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        dry_run=dry_run,
        set_values=set_values,
    )

    if as_json:
        click.echo(json_lib.dumps(config, indent=2))
        return

    click.echo(_task_header(target))
    click.echo()
    _print_limits(config, changed=set_values)

    # The process-global knobs apply to every eval in the target process, so in a
    # multi-eval process (an eval-set) they reach beyond the named task. Surface
    # that where it can surprise — right after a set that used one of them.
    global_knobs = [
        name
        for name, value in (
            ("--max-connections", max_connections),
            ("--max-sandboxes", max_sandboxes),
        )
        if value is not None
    ]
    siblings = sum(
        1 for s in summaries if s.get("socket_path") == target.get("socket_path")
    )
    note = _process_scope_note(global_knobs, siblings)
    if note:
        click.echo(f"\n{note}")


def _process_scope_note(global_knobs: list[str], siblings: int) -> str | None:
    """Note that process-global limit knobs reach every task in the process.

    ``global_knobs`` is the set (``--max-connections`` / ``--max-sandboxes``)
    supplied on this invocation; ``siblings`` is the number of evals the target
    process hosts. Returns ``None`` when there's nothing to flag — no such knob
    was set, or the process hosts a single eval so "process-wide" is exactly the
    named task and the distinction is invisible.
    """
    if not global_knobs or siblings <= 1:
        return None
    verb = "applies" if len(global_knobs) == 1 else "apply"
    return (
        f"note: {' and '.join(global_knobs)} {verb} across all "
        f"{siblings} tasks sharing this process."
    )


def _resolve_target_server(pid: int | None) -> DiscoveredControlServer:
    """Pick the single process a ``keep`` / ``release`` targets, or exit.

    With ``--pid`` the matching process is used (error if none matches);
    without it, the sole running process is the default, and an ambiguous
    set (more than one) errors with the candidate pids.
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
        return matching[0]
    if len(servers) == 1:
        return servers[0]

    pids = ", ".join(str(s.pid) for s in servers)
    click.echo(
        f"Multiple inspect processes are running (pids: {pids}). "
        "Pass --pid to disambiguate.",
        err=True,
    )
    raise click.exceptions.Exit(code=1)


def _post_to_server(socket_path: Path, path: str) -> None:
    """POST to a control server's ``path`` over its AF_UNIX socket."""
    transport = httpx.HTTPTransport(uds=str(socket_path))
    with httpx.Client(
        transport=transport, base_url="http://localhost", timeout=5.0
    ) as client:
        response = client.post(path)
        response.raise_for_status()


# The control server is embedded in the eval process and shares its event
# loop, which a busy eval can monopolize for several seconds at a time
# (large-transcript serialization, log flushes — see
# https://github.com/meridianlabs-ai/inspect_ai/issues/14). A perfectly
# healthy server can therefore miss a short read window, so reads use a
# generous timeout and retry a timeout several times before giving up, rather
# than silently reporting the eval as gone.
_REQUEST_TIMEOUT = 15.0
_REQUEST_ATTEMPTS = 8

# A mutation (flush / buffer set) is issued once — it isn't idempotent, so it
# must not be retried — but it gets the same total wall-clock budget a retried
# read would consume (one attempt of `_REQUEST_ATTEMPTS * _REQUEST_TIMEOUT`, ie.
# 2 min) so a slow remote (eg. S3) write isn't cut short. That budget is the
# *read* leg; connect over the local UDS is effectively instant, so it's capped
# short rather than getting the full budget too.
_MUTATION_TIMEOUT = _REQUEST_ATTEMPTS * _REQUEST_TIMEOUT
_CONNECT_TIMEOUT = 10.0


class _ServerUnreachable(Exception):
    """A control read failed for a non-timeout reason.

    Distinct from a timeout — which means the server is present but its loop is
    busy, and is worth retrying. This covers the non-retryable failures: a
    connection refused (the process has exited or never came up), a server-side
    ``500``, or a malformed response. Carries the originating error as
    ``__cause__`` (so callers can surface its detail); the caller decides
    whether to warn-and-skip (enumerating many servers) or fail (a single
    targeted read).
    """


def _get_response_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
) -> httpx.Response:
    """GET ``path`` over the UDS, retrying a read timeout; return the response.

    Retries a read timeout up to ``_REQUEST_ATTEMPTS`` times, printing a status
    to the console (stderr, so ``--json`` stdout stays clean) on each — the eval
    is most likely just busy. On exhaustion, prints an error and exits non-zero.
    Raises :class:`_ServerUnreachable` for a non-timeout transport error (eg. a
    refused/reset connection) so the caller can skip or fail as appropriate.

    Returns the raw response without inspecting its status, so callers that need
    to handle a meaningful status (eg. a 404) can; :func:`_get_with_retry` is the
    JSON-decoding wrapper for the common case.
    """
    transport = httpx.HTTPTransport(uds=str(socket_path))
    for attempt in range(1, _REQUEST_ATTEMPTS + 1):
        try:
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=_REQUEST_TIMEOUT,
            ) as client:
                return client.get(path, params=params or {})
        except httpx.TimeoutException:
            click.echo(
                f"{what}: no response after {_REQUEST_TIMEOUT:.0f}s "
                f"(attempt {attempt}/{_REQUEST_ATTEMPTS}) — the eval may be busy; "
                "retrying…",
                err=True,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise _ServerUnreachable() from exc
    click.echo(
        f"{what}: gave up after {_REQUEST_ATTEMPTS} attempts of "
        f"{_REQUEST_TIMEOUT:.0f}s each — the eval is not responding.",
        err=True,
    )
    raise click.exceptions.Exit(code=1)


def _get_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
) -> Any:
    """GET ``path`` and return its decoded JSON, retrying a busy eval on timeout.

    Wraps :func:`_get_response_with_retry`; a non-2xx status or undecodable body
    raises :class:`_ServerUnreachable` (a server-side ``500`` or malformed
    response is not retryable). For endpoints with a meaningful 4xx, call
    :func:`_get_response_with_retry` directly and inspect the status.
    """
    response = _get_response_with_retry(socket_path, path, params=params, what=what)
    try:
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _ServerUnreachable() from exc


def _fetch_summaries(
    servers: list[DiscoveredControlServer],
) -> list[dict[str, Any]]:
    """Query each discovered control server for its eval summary.

    Each read retries on timeout (and ultimately fails the command if a server
    stays unresponsive — see :func:`_get_with_retry`). A server that can't be
    reached for a non-timeout reason raises :class:`_ServerUnreachable`; we warn
    and skip it (rather than fail the whole listing — the other evals are still
    worth showing) but the warning is surfaced rather than swallowed: the most
    common cause is a process that just exited between discovery and connect,
    but the same path also catches a server-side ``500`` or a malformed
    response, which the user should see.
    """
    summaries: list[dict[str, Any]] = []
    for server in servers:
        try:
            rows = _get_with_retry(
                server.socket_path,
                "/evals",
                what=f"Reading tasks from pid {server.pid}",
            )
        except _ServerUnreachable as exc:
            cause = exc.__cause__
            detail = _error_detail(cause) if isinstance(cause, Exception) else str(exc)
            click.echo(
                f"Skipping pid {server.pid}: its control endpoint could not be "
                f"read ({detail}) — it may have just exited.",
                err=True,
            )
            continue
        if isinstance(rows, list):
            # Decorate each row with discovery-side info the server doesn't
            # see (pid, socket_path).
            for row in rows:
                row["pid"] = server.pid
                row["socket_path"] = str(server.socket_path)
            summaries.extend(rows)
    return summaries


def _resolve_target_eval(
    summaries: list[dict[str, Any]], query: str | None
) -> dict[str, Any]:
    """Pick the task a per-eval command targets, or exit with an error.

    ``query`` matches a task id first (full, then unique prefix — ``tasks``
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


def _fetch_samples(
    socket_path: str, eval_id: str, active_since: float | None = None
) -> list[dict[str, Any]]:
    """Query one control server for an eval's samples.

    With ``active_since`` (unix ts), restricts to samples started or updated
    since then — the recency delta.
    """
    params = {} if active_since is None else {"active_since": active_since}
    try:
        rows = _get_with_retry(
            socket_path,
            f"/evals/{eval_id}/samples",
            params=params,
            what=f"Reading samples for eval {eval_id}",
        )
    except _ServerUnreachable as exc:
        cause = exc.__cause__
        detail = _error_detail(cause) if isinstance(cause, Exception) else str(exc)
        click.echo(
            f"Failed to read samples for eval {eval_id}: {detail}",
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


def _fetch_sample_events(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    since: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
) -> dict[str, Any]:
    """Query one control server for a page of a sample's transcript events."""
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply.
    params: dict[str, Any] = {"sample_id": sample_id, "epoch": epoch, "full": full}
    if since is not None:
        params["since"] = since
    if tail is not None:
        params["tail"] = tail
    if types is not None:
        params["type"] = types
    if since_time is not None:
        params["since_time"] = since_time
    if until is not None:
        params["until"] = until
    try:
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get(f"/evals/{eval_id}/sample/events", params=params)
            if response.status_code == 404:
                click.echo(
                    f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
                    "not have started or not yet been written to the log.",
                    err=True,
                )
                raise click.exceptions.Exit(code=1)
            response.raise_for_status()
            page = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(f"Failed to read events: {_error_detail(exc)}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    return page if isinstance(page, dict) else {}


def _post_flush(socket_path: str, eval_id: str) -> dict[str, Any]:
    """Ask one control server to flush an eval's buffered samples to the log."""
    try:
        transport = httpx.HTTPTransport(uds=str(socket_path))
        # A remote (eg. S3) log write can take a while; a mutation isn't retried,
        # so give the single attempt the full mutation budget (see
        # `_MUTATION_TIMEOUT`).
        with httpx.Client(
            transport=transport,
            base_url="http://localhost",
            timeout=httpx.Timeout(_MUTATION_TIMEOUT, connect=_CONNECT_TIMEOUT),
        ) as client:
            response = client.post(f"/evals/{eval_id}/flush")
            if response.status_code == 404:
                click.echo(
                    f"Eval '{eval_id}' is not flushable — it has no live sample "
                    "buffer in this process (e.g. a reused log, or a retry "
                    "attempt that's been superseded).",
                    err=True,
                )
                raise click.exceptions.Exit(code=1)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(f"Failed to flush eval {eval_id}: {_error_detail(exc)}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    return result if isinstance(result, dict) else {}


def _exec_buffer_config(
    socket_path: str,
    eval_id: str,
    *,
    log_buffer: int | None,
    log_shared: int | None,
    set_values: bool,
) -> dict[str, Any]:
    """Read (``set_values=False``) or update an eval's sample-buffer config.

    The read is a GET that retries a busy eval on timeout (like the other
    reads). The update is a single-shot POST — a mutation isn't idempotent, so
    it must not be retried — given the full mutation budget (see
    :data:`_MUTATION_TIMEOUT`).
    """
    params: dict[str, Any] = {}
    if log_buffer is not None:
        params["log_buffer"] = log_buffer
    if log_shared is not None:
        params["log_shared"] = log_shared
    path = f"/evals/{eval_id}/buffer"
    verb = "update" if set_values else "read"
    try:
        if set_values:
            transport = httpx.HTTPTransport(uds=str(socket_path))
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=httpx.Timeout(_MUTATION_TIMEOUT, connect=_CONNECT_TIMEOUT),
            ) as client:
                response = client.post(path, params=params)
        else:
            response = _get_response_with_retry(
                socket_path, path, what=f"Reading buffer config for eval {eval_id}"
            )
        if response.status_code == 404:
            click.echo(
                f"Eval '{eval_id}' has no sample buffer in this process "
                "(e.g. a reused log, or a retry attempt that's been "
                "superseded).",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        response.raise_for_status()
        config = response.json()
    except _ServerUnreachable as exc:
        detail = (
            _error_detail(exc.__cause__)
            if isinstance(exc.__cause__, Exception)
            else str(exc)
        )
        click.echo(
            f"Failed to {verb} buffer config for eval {eval_id}: {detail}", err=True
        )
        raise click.exceptions.Exit(code=1) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(
            f"Failed to {verb} buffer config for eval {eval_id}: {_error_detail(exc)}",
            err=True,
        )
        raise click.exceptions.Exit(code=1) from exc
    return config if isinstance(config, dict) else {}


def _exec_limits(
    socket_path: str,
    eval_id: str,
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    dry_run: bool,
    set_values: bool,
) -> dict[str, Any]:
    """Read (``set_values=False``) or retune an eval's concurrency limits.

    The read is a GET that retries a busy eval on timeout (like the other
    reads). The update is a single-shot PATCH — a mutation isn't retried — given
    the full mutation budget (see :data:`_MUTATION_TIMEOUT`). ``dry_run`` only
    applies to a set; a bare ``--dry-run`` (no set option) is a plain read.
    """
    params: dict[str, Any] = {}
    if max_samples is not None:
        params["max_samples"] = max_samples
    if max_sandboxes is not None:
        params["max_sandboxes"] = max_sandboxes
    if max_connections is not None:
        params["max_connections"] = max_connections
    if dry_run:
        params["dry_run"] = True
    path = f"/evals/{eval_id}/limits"
    verb = "update" if set_values else "read"
    try:
        if set_values:
            transport = httpx.HTTPTransport(uds=str(socket_path))
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=httpx.Timeout(_MUTATION_TIMEOUT, connect=_CONNECT_TIMEOUT),
            ) as client:
                response = client.patch(path, params=params)
        else:
            response = _get_response_with_retry(
                socket_path, path, what=f"Reading limits for eval {eval_id}"
            )
        if response.status_code == 404:
            click.echo(
                f"Eval '{eval_id}' has no adjustable limits in this process "
                "(e.g. a reused log, or a retry attempt that's been superseded).",
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        if response.status_code == 400:
            click.echo(
                f"Invalid limit: {_error_detail_from_response(response)}", err=True
            )
            raise click.exceptions.Exit(code=1)
        response.raise_for_status()
        config = response.json()
    except _ServerUnreachable as exc:
        detail = (
            _error_detail(exc.__cause__)
            if isinstance(exc.__cause__, Exception)
            else str(exc)
        )
        click.echo(f"Failed to {verb} limits for eval {eval_id}: {detail}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(
            f"Failed to {verb} limits for eval {eval_id}: {_error_detail(exc)}",
            err=True,
        )
        raise click.exceptions.Exit(code=1) from exc
    return config if isinstance(config, dict) else {}


def _error_detail_from_response(response: httpx.Response) -> str:
    """Prefer the server's ``{"error": ...}`` body over a bare status message."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return f"HTTP {response.status_code}"


def _print_limits(config: dict[str, Any], *, changed: bool) -> None:
    """Render an eval's concurrency limits as a short labelled block."""
    dry_run = bool(config.get("dry_run"))
    if changed:
        click.echo("would-be limits (dry run):" if dry_run else "updated limits:")
    else:
        click.echo("limits:")

    # On a dry-run the server reports the pre-change view (nothing was mutated);
    # the intended values live in `requested`. Render `current → would-be` so the
    # header's promise is met without losing the current value. On a real set the
    # view already reflects the applied change, so no arrow is needed.
    requested = config.get("requested") if dry_run else None
    requested = requested if isinstance(requested, dict) else {}

    def _target(current: Any, key: str) -> str:
        proposed = requested.get(key)
        return f"{current}{'' if proposed is None or proposed == current else f' → {proposed}'}"

    adaptive = config.get("adaptive") or []

    max_samples = config.get("max_samples") or {}
    if max_samples.get("adjustable"):
        limit = _target(max_samples.get("limit"), "max_samples")
        in_use = max_samples.get("in_use")
        click.echo(f"  max samples:   {limit} ({in_use} in use)")
    elif adaptive:
        # sample concurrency tracks the adaptive controller(s) below, so there's
        # no user setpoint to show here — point at where the live numbers are
        click.echo("  max samples:   tracks adaptive connections (see below)")
    else:
        click.echo("  max samples:   not adjustable (adaptive connections)")

    sandboxes = config.get("max_sandboxes") or []
    if sandboxes:
        rendered = ", ".join(
            f"{s.get('type')} {_target(s.get('limit'), 'max_sandboxes')} ({s.get('in_use')} in use)"
            for s in sandboxes
        )
        click.echo(f"  max sandboxes: {rendered}")
    else:
        click.echo("  max sandboxes: none in effect")

    if adaptive:
        click.echo("  adaptive connections:")
        for a in adaptive:
            # on a dry-run set, `_target` renders the ceiling as `max → requested`
            ceiling = _target(a.get("max"), "max_connections")
            line = (
                f"    {a.get('name')}: {a.get('limit')} ({a.get('in_use')} in use), "
                f"range {a.get('min')}–{ceiling}"
            )
            changes = a.get("recent_changes") or []
            if changes:
                last = changes[-1]
                line += (
                    f", last: {last.get('from')}→{last.get('to')} {last.get('reason')}"
                )
            click.echo(line)

    for warning in config.get("warnings") or []:
        click.echo(f"  ! {warning}")


def _print_buffer_config(config: dict[str, Any], *, changed: bool) -> None:
    """Render an eval's sample-buffer config as a short labelled block."""
    click.echo("updated buffer config:" if changed else "buffer config:")
    click.echo(f"  log buffer:   {config.get('log_buffer')} samples")
    click.echo(f"  pending:      {config.get('pending')} buffered (not yet written)")
    log_shared = config.get("log_shared")
    click.echo(
        f"  shared sync:  {f'{log_shared}s' if log_shared is not None else 'off'}"
    )


def _print_events(page: dict[str, Any]) -> None:
    """Render a page of transcript events (table) plus a cursor footer."""
    events = page.get("events") or []
    if not events:
        click.echo("(no events)")
    else:
        rows: list[tuple[str, ...]] = []
        for e in events:
            ts = e.get("timestamp")
            rows.append(
                (
                    _format_started(ts) if isinstance(ts, (int, float)) else "",
                    str(e.get("event", "") or ""),
                    _event_summary(e),
                )
            )
        _render_table(("time", "event", "summary"), rows)

    parts = [f"{len(events)} event" + ("" if len(events) == 1 else "s")]
    parts.append("done" if page.get("done") else "more")
    click.echo()
    click.echo("  ·  ".join(parts))
    nxt = page.get("next")
    if nxt and not page.get("done"):
        click.echo(f"next: {nxt}")


def _event_summary(e: dict[str, Any]) -> str:
    """One-line summary for an event row (best-effort over compact fields)."""
    t = e.get("event")
    if t == "model":
        bits = [str(e.get("model") or "")]
        if e.get("tokens") is not None:
            bits.append(f"{e['tokens']} tok")
        if e.get("stop_reason"):
            bits.append(str(e["stop_reason"]))
        if e.get("completion"):
            bits.append(str(e["completion"]))
        if e.get("error"):
            bits.append(f"error: {e['error']}")
        return _truncate(" · ".join(b for b in bits if b), 80)
    if t == "tool":
        s = f"{e.get('function') or '?'}({_truncate(str(e.get('arguments') or ''), 30)})"
        if e.get("error"):
            s += f" → error: {e['error']}"
        elif e.get("result"):
            s += f" → {_truncate(str(e['result']), 40)}"
        return _truncate(s, 80)
    if t == "error":
        return _truncate(str(e.get("error") or ""), 80)
    if t == "info":
        return str(e.get("source") or "")
    return ""


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


def _print_keep_alive_footer(summaries: list[dict[str, Any]]) -> None:
    """Print a one-line keep-alive status footer below the tasks table.

    Keep-alive is a per-process property — every task a process hosts shares
    it — so across all running tasks it's ``on`` (all park after their eval),
    ``off`` (none do), or ``mixed``. When it's off everywhere, hint at
    ``inspect ctl keep``, which turns it on for a running process.
    """
    flags = [bool(s.get("keep_alive")) for s in summaries]
    click.echo()
    if all(flags):
        click.echo("keep-alive: on")
    elif not any(flags):
        click.echo("keep-alive: off  ·  set with `inspect ctl keep`")
    else:
        on = sum(flags)
        click.echo(f"keep-alive: mixed ({on}/{len(flags)} on)")


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

    Three columns are conditional, shown only when relevant (keeping the
    common case uncluttered):
    - ``retries`` — when some sample was retried on error. Per-sample
      (sample-level ``retry_on_error``); blank for samples with none.
    - ``score`` — when the samples have exactly one scorer (multi-scorer
      rendering is a later refinement). Running samples aren't scored yet,
      so their cell is blank.
    - ``idle`` — when some sample is running: time since its last transcript
      event (``now - last_activity_at``). A high idle time on a long-running
      sample is the cheap "is it stalled?" cue. Blank for non-running rows.
    """
    any_retries = any((s.get("retries") or 0) > 0 for s in samples)
    scorers = sorted({name for s in samples for name in (s.get("scores") or {})})
    score_col = scorers[0] if len(scorers) == 1 else None
    any_running = any(s.get("status") == "running" for s in samples)
    now = datetime.now(timezone.utc).timestamp()

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
        cells = [
            _format_duration(s.get("total_time")),
            str(s.get("total_tokens", 0)),
            str(s.get("message_count") or 0),
        ]
        if any_running:
            last = s.get("last_activity_at")
            idle = (
                _format_duration(now - last)
                if s.get("status") == "running" and last is not None
                else ""
            )
            cells.insert(1, idle)  # after time, before tokens
        row.extend(cells)
        rows.append(tuple(row))

    headers = ["sample", "epoch", "status"]
    if any_retries:
        headers.append("retries")
    if score_col is not None:
        headers.append("score")
    headers.append("time")
    if any_running:
        headers.append("idle")
    headers.extend(["tokens", "messages"])
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
