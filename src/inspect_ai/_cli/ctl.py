"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts the commands that operate on a *running* Inspect
eval via the per-process control server's HTTP endpoints. See
``design/control-channel.md`` for the design.

Commands are grouped by **resource noun**, mirroring the HTTP API's object
model (see "CLI command hierarchy: noun groups" in the design doc):

- ``task`` — a logical task in a running process (stable across retries):
  ``list`` (implied by the bare noun), ``log-flush``; ``add`` / ``cancel`` /
  ``drain`` are planned.
- ``sample`` — one sample (``TASK SAMPLE_ID [EPOCH]``) or a task's samples:
  ``list`` (implied by the bare noun), ``show``, ``errors``, ``events``;
  ``cancel`` / ``requeue`` are planned.
- ``config`` — a top-level *command* (not a group): view / retune launch
  configuration mid-flight (concurrency limits, log buffering). Scope is a
  property of each knob (task vs process), labeled in the output.
- ``process`` — the running Inspect process itself: ``list`` (implied by the
  bare noun), ``keep``, ``release``.

The old flat spellings (``tasks``, ``samples``, ``errors``, ``events``,
``keep``, ``release``, ``flush``, ``buffer``, ``limits``) survive as hidden,
deprecation-noted aliases for a transition window — thin delegations to the
new implementations (new behavior and JSON shapes included). The old
``sample`` command's name is claimed by the group and breaks immediately;
its error message points at ``sample show``.
"""

from __future__ import annotations

import json as json_lib
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, NamedTuple, NoReturn

import click
import httpx
from click.core import ParameterSource

from inspect_ai._control.discovery import (
    DiscoveredControlServer,
    discovery_dir,
    list_discovered_servers,
)
from inspect_ai._util.name_match import match_name_prefix

# Events shown on an unseeded `sample events` read (no --cursor / --tail /
# --since-time / --until): a recent tail rather than the full backlog — the
# first call must never be empty or a context-flooding dump (see the agent
# output contract in design/control-channel.md).
_DEFAULT_EVENTS_TAIL = 20


class _NounGroup(click.Group):
    """A resource-noun command group (``task`` / ``sample`` / ``process``).

    Bare invocation implies ``list`` (git precedent: bare ``git branch`` /
    ``git remote``) — implemented via ``invoke_without_command`` plus the
    ``list`` options mirrored onto the group, so ``ctl task --json`` works.
    The boundary is strict: the default never fires once a positional
    argument is present. A selector in the verb slot (``ctl sample my-task``)
    therefore fails — and the failure teaches the corrected spelling via
    ``hint`` rather than click's stock "No such command".
    """

    hint: Callable[[str], str] | None = None
    """Builds the unknown-command error message from the offending token."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        token = str(args[0])
        if (
            not token.startswith("-")
            and self.get_command(ctx, token) is None
            and self.hint is not None
        ):
            ctx.fail(self.hint(token))
        return super().resolve_command(ctx, args)


def _forward_group_options(ctx: click.Context) -> None:
    """Forward explicitly-given mirrored group options to the invoked verb.

    The ``list`` options are mirrored onto each noun group so the bare-noun
    default works (``ctl task --json``). When an explicit verb follows, those
    group-level values would otherwise be parsed and dropped — ``ctl task
    --json list`` silently emitting the human table, exactly the branch
    agents parse on. Forward them as defaults instead (the same option
    spelled after the verb still wins); a mirrored option the verb does not
    accept fails with the corrected spelling rather than being ignored.
    """
    if ctx.invoked_subcommand is None:
        return
    group = ctx.command
    assert isinstance(group, click.Group)
    given = {
        param.name: (ctx.params[param.name], param.opts[0])
        for param in group.params
        if param.name is not None
        and ctx.get_parameter_source(param.name) == ParameterSource.COMMANDLINE
    }
    if not given:
        return
    verb = group.get_command(ctx, ctx.invoked_subcommand)
    assert verb is not None
    verb_params = {param.name for param in verb.params}
    for name, (_, opt) in given.items():
        if name not in verb_params:
            ctx.fail(
                f"'{opt}' is a `list` option that `{group.name} "
                f"{ctx.invoked_subcommand}` does not accept. To use it, list "
                f"instead: `inspect ctl {group.name} list {opt} ...`."
            )
    ctx.default_map = {
        **(ctx.default_map or {}),
        ctx.invoked_subcommand: {name: value for name, (value, _) in given.items()},
    }


@click.group("ctl")
def ctl_command() -> None:
    """Read the state of running evals and manage kept-alive processes.

    Commands are grouped by resource noun (listed below); `list` verbs are
    implied by the bare noun (`inspect ctl task` ≡ `inspect ctl task list`).
    All commands accept `--json`.

    A process exits when its eval finishes; launch with `inspect eval
    --ctl-server=keep` to keep it inspectable here until you run
    `inspect ctl process release`.
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


def _deprecation_note(old: str, new: str) -> None:
    """Print (to stderr, keeping ``--json`` stdout parseable) an alias note."""
    click.echo(
        f"note: `inspect ctl {old}` is now `inspect ctl {new}` — this hidden "
        "alias will be removed in a future release.",
        err=True,
    )


# ---------------------------------------------------------------------------
# task group
# ---------------------------------------------------------------------------


@ctl_command.group(
    "task",
    cls=_NounGroup,
    invoke_without_command=True,
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (mirrored from `list` for the bare-noun default).",
)
@click.pass_context
def task_group(ctx: click.Context, as_json: bool) -> None:
    """Operate on the tasks of running evals (bare `task` lists them).

    Task ids are stable across retries and are the TASK selector other
    commands take. `add` / `cancel` / `drain` are planned but not yet
    available.
    """
    if ctx.invoked_subcommand is None:
        _run_task_list(as_json)
    else:
        _forward_group_options(ctx)


assert isinstance(task_group, _NounGroup)
task_group.hint = lambda token: (
    f"No such command '{token}'. To list running tasks: "
    "`inspect ctl task list` (or the bare `inspect ctl task`)."
)


@task_group.command("list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (an `{as_of, tasks}` envelope).",
)
def task_list_command(as_json: bool) -> None:
    """List running tasks across all live Inspect processes.

    Each `--json` row carries the selectors other commands take (`task_id`,
    `pid`) plus `log_location`, where results are being written. A task is
    finished exactly when `completed_at` is non-null — do not infer
    completion from sample counts (a cancelled or errored eval finishes
    with `completed < total`).
    """
    _run_task_list(as_json)


@task_group.command("log-flush")
@click.argument("task", required=False)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the mutation result envelope).",
)
def task_log_flush_command(task: str | None, as_json: bool) -> None:
    """Flush a running task's buffered samples to its log now.

    Completed samples are written to the (possibly remote) log only when
    the buffer fills; this forces the write immediately. Safe to repeat.
    Tune the buffering policy itself with `inspect ctl config --log-buffer`
    / `--log-shared`. TASK (a task-id prefix or name) is required when
    several tasks run.
    """
    _run_log_flush(task, as_json)


# ---------------------------------------------------------------------------
# sample group
# ---------------------------------------------------------------------------


@ctl_command.group(
    "sample",
    cls=_NounGroup,
    invoke_without_command=True,
)
@click.option(
    "--active-since",
    type=float,
    default=None,
    help="Mirrored from `list` for the bare-noun default.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (mirrored from `list` for the bare-noun default).",
)
@click.pass_context
def sample_group(ctx: click.Context, active_since: float | None, as_json: bool) -> None:
    """Operate on samples of running evals (bare `sample` lists them).

    An omitted TASK on `list` / `errors` reads across all running tasks.
    `cancel` / `requeue` are planned but not yet available.
    """
    if ctx.invoked_subcommand is None:
        _run_sample_list(None, active_since, as_json)
    else:
        _forward_group_options(ctx)


assert isinstance(sample_group, _NounGroup)
sample_group.hint = lambda token: (
    f"No such command '{token}'. `inspect ctl sample` is now a command "
    f"group. To list a task's samples: `inspect ctl sample list {token}`; "
    f"for one sample's detail (the old `inspect ctl sample`): "
    f"`inspect ctl sample show {token} SAMPLE_ID [EPOCH]`."
)


@sample_group.command("list")
@click.argument("task", required=False)
@click.option(
    "--active-since",
    type=float,
    default=None,
    help=(
        "Only samples that started or were updated at/after this unix "
        "timestamp — the 'what changed since I last looked' delta. Feed it "
        "the `as_of` from the prior response's envelope."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (an `{as_of, samples}` envelope).",
)
def sample_list_command(
    task: str | None, active_since: float | None, as_json: bool
) -> None:
    """List the samples (running and completed) of running evals.

    TASK is a task id (or unique prefix) or task name, matched at the start
    or after a `/`; omitted, the listing spans all running tasks. To poll
    for what changed, pass `--active-since` the `as_of` from the prior
    response's envelope.
    """
    _run_sample_list(task, active_since, as_json)


@sample_group.command("errors")
@click.argument("task", required=False)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (an `{as_of, samples}` envelope).",
)
def sample_errors_command(task: str | None, as_json: bool) -> None:
    """List the samples of running evals that errored or were retried.

    One row per sample with the latest error message; an omitted TASK spans
    all running tasks. Drill into one sample with `inspect ctl sample show`.
    """
    _run_sample_errors(task, as_json)


@sample_group.command("show")
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
    help="Output as JSON (the sample's summary + error detail).",
)
def sample_show_command(
    task: str, sample_id: str, epoch: int, show_traceback: bool, as_json: bool
) -> None:
    """Show one sample's summary and error history.

    Reports status / timing / token usage / score and the error from the
    current and each prior attempt; use `inspect ctl sample events` for the
    transcript. EPOCH defaults to 1 (the response echoes the resolved
    epoch).
    """
    _run_sample_show(task, sample_id, epoch, show_traceback, as_json)


@sample_group.command("events")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--cursor",
    default=None,
    help=(
        "Resume after this opaque cursor (the `next` from a prior page). "
        "Not a timestamp — for a wall-clock window use --since-time."
    ),
)
@click.option(
    "--since",
    "legacy_since",
    default=None,
    hidden=True,
    help="Removed — split into --cursor and --since-time.",
)
@click.option(
    "--tail",
    type=int,
    default=None,
    help=(
        "Start this many events from the end (when --cursor is not given). "
        f"Default: {_DEFAULT_EVENTS_TAIL}, applied only to a fully unseeded "
        "read (no --cursor and no --since-time/--until window)."
    ),
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
def sample_events_command(
    task: str,
    sample_id: str,
    epoch: int,
    cursor: str | None,
    legacy_since: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    """Read one running sample's transcript events (cursored pull).

    The first call returns a recent tail; each page ends with a `next`
    cursor — pass it back via `--cursor` to read only what's new. `done:
    true` means the sample has terminated and no more events will come.
    """
    if legacy_since is not None:
        _exit_removed_since(legacy_since)
    _run_sample_events(
        task,
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------


@ctl_command.command("config")
@click.argument("task", required=False)
@click.option(
    "--max-samples",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        "[task] Max samples to run concurrently (under adaptive connections, "
        "sample concurrency tracks the controller instead)."
    ),
)
@click.option(
    "--max-sandboxes",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help="[process] Max sandboxes per provider.",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help="[process] Adaptive-connections scaling ceiling — the controllers' max.",
)
@click.option(
    "--model",
    default=None,
    help=(
        "Restrict --max-connections (and the adaptive view) to models matching "
        "this — at the name start or after a '/' (e.g. 'gpt-4' matches "
        "'openai/gpt-4')."
    ),
)
@click.option(
    "--log-buffer",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        "[task] Completed samples buffered before a log write — the retune "
        "side of `inspect ctl task log-flush` (lower it to write to S3 more "
        "often)."
    ),
)
@click.option(
    "--log-shared",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help="[task] Shared-log event sync interval, in seconds.",
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
    help="Output as JSON (the config view, every knob labeled with its scope).",
)
def config_command(
    task: str | None,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    log_buffer: int | None,
    log_shared: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """View or retune a running eval's launch configuration mid-flight.

    Any `inspect eval` launch flag that can be retuned while the eval runs
    is settable here, under the same spelling; with no set options, shows
    the current configuration. Each option below is tagged with its scope —
    [task] targets the selected task, [process] every task in the process —
    and the output labels every knob likewise. Pass `--dry-run` to see what
    would change without applying it.

    Lowering a concurrency limit never interrupts running samples — new
    work waits until in-flight holders drain. `--log-buffer` / `--log-shared`
    are the retune side of `inspect ctl task log-flush`: they set the
    buffering policy for future writes, while log-flush writes what's
    already buffered now. TASK is required only for setting a task-scoped
    knob when several tasks run.
    """
    _run_config(
        task,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        log_buffer=log_buffer,
        log_shared=log_shared,
        dry_run=dry_run,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# process group
# ---------------------------------------------------------------------------


@ctl_command.group(
    "process",
    cls=_NounGroup,
    invoke_without_command=True,
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (mirrored from `list` for the bare-noun default).",
)
@click.pass_context
def process_group(ctx: click.Context, as_json: bool) -> None:
    """Operate on running Inspect processes (bare `process` lists them).

    The selector is a positional PID, optional when a single process is
    running.
    """
    if ctx.invoked_subcommand is None:
        _run_process_list(as_json)
    else:
        _forward_group_options(ctx)


assert isinstance(process_group, _NounGroup)
process_group.hint = lambda token: (
    f"No such command '{token}'. To list running processes: "
    "`inspect ctl process list` (or the bare `inspect ctl process`); to park "
    f"or release one: `inspect ctl process keep {token}` / "
    f"`inspect ctl process release {token}`."
)


@process_group.command("list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (an `{as_of, processes}` envelope).",
)
def process_list_command(as_json: bool) -> None:
    """List running Inspect processes (pids, keep-alive, hosted tasks).

    The PID shown is the selector `process keep` / `process release` take.
    """
    _run_process_list(as_json)


@process_group.command("keep")
@click.argument("pid", required=False, type=int)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the mutation result envelope).",
)
def process_keep_command(pid: int | None, as_json: bool) -> None:
    """Keep a running inspect process alive after its eval finishes.

    The process parks after the eval — state and results stay readable
    here — until `inspect ctl process release` or Ctrl+C. The runtime
    equivalent of launching with `--ctl-server=keep`; `keep` and `release`
    are last-write-wins while the eval is still running.
    """
    _run_keep_alive(pid, keep=True, as_json=as_json)


@process_group.command("release")
@click.argument("pid", required=False, type=int)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the mutation result envelope).",
)
def process_release_command(pid: int | None, as_json: bool) -> None:
    """Release a lingering --ctl-server=keep process so it can exit.

    Issued while the eval is still running it means "exit when done",
    unless a later `keep` overrides it (last-write-wins). Does NOT cancel
    the eval or affect in-flight samples.
    """
    _run_keep_alive(pid, keep=False, as_json=as_json)


# ---------------------------------------------------------------------------
# hidden deprecated aliases (the old flat spellings)
# ---------------------------------------------------------------------------
#
# Thin delegations to the new implementations: spellings are preserved,
# output is NOT (the new `{as_of, ...}` envelopes, unconditional task_id,
# widened unscoped reads all apply through the alias). Each prints a one-line
# stderr pointer at the new spelling. The old `sample` command is the one
# spelling that cannot alias — the name is claimed by the group — and its
# unknown-command error points at `sample show`.


@ctl_command.command("tasks", hidden=True)
@click.option("--json", "as_json", is_flag=True, default=False)
def tasks_alias(as_json: bool) -> None:
    """Deprecated alias for `inspect ctl task list`."""
    _deprecation_note("tasks", "task list")
    _run_task_list(as_json)


@ctl_command.command("samples", hidden=True)
@click.argument("task", required=False)
@click.option("--active-since", type=float, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def samples_alias(task: str | None, active_since: float | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl sample list`."""
    _deprecation_note("samples", "sample list")
    _run_sample_list(task, active_since, as_json)


@ctl_command.command("errors", hidden=True)
@click.argument("task", required=False)
@click.option("--json", "as_json", is_flag=True, default=False)
def errors_alias(task: str | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl sample errors`."""
    _deprecation_note("errors", "sample errors")
    _run_sample_errors(task, as_json)


@ctl_command.command("events", hidden=True)
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option("--since", "cursor", default=None)
@click.option("--tail", type=int, default=None)
@click.option("--type", "types", default=None)
@click.option("--full", is_flag=True, default=False)
@click.option("--since-time", type=float, default=None)
@click.option("--until", type=float, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def events_alias(
    task: str,
    sample_id: str,
    epoch: int,
    cursor: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    """Deprecated alias for `inspect ctl sample events` (--since is --cursor)."""
    _deprecation_note("events", "sample events")
    _run_sample_events(
        task,
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
        as_json=as_json,
    )


@ctl_command.command("keep", hidden=True)
@click.option("--pid", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def keep_alias(pid: int | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl process keep`."""
    _deprecation_note("keep", "process keep")
    _run_keep_alive(pid, keep=True, as_json=as_json)


@ctl_command.command("release", hidden=True)
@click.option("--pid", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def release_alias(pid: int | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl process release`."""
    _deprecation_note("release", "process release")
    _run_keep_alive(pid, keep=False, as_json=as_json)


@ctl_command.command("flush", hidden=True)
@click.argument("task", required=False)
@click.option("--json", "as_json", is_flag=True, default=False)
def flush_alias(task: str | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl task log-flush`."""
    _deprecation_note("flush", "task log-flush")
    _run_log_flush(task, as_json)


@ctl_command.command("buffer", hidden=True)
@click.argument("task", required=False)
@click.option("--samples", "log_buffer", type=int, default=None)
@click.option("--shared", "log_shared", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def buffer_alias(
    task: str | None,
    log_buffer: int | None,
    log_shared: int | None,
    as_json: bool,
) -> None:
    """Deprecated alias for `inspect ctl config --log-buffer / --log-shared`."""
    _deprecation_note("buffer", "config --log-buffer/--log-shared")
    _run_config(
        task,
        max_samples=None,
        max_sandboxes=None,
        max_connections=None,
        model=None,
        log_buffer=log_buffer,
        log_shared=log_shared,
        dry_run=False,
        as_json=as_json,
    )


@ctl_command.command("limits", hidden=True)
@click.argument("task", required=False)
@click.option("--max-samples", type=click.IntRange(min=1), default=None)
@click.option("--max-sandboxes", type=click.IntRange(min=1), default=None)
@click.option("--max-connections", type=click.IntRange(min=1), default=None)
@click.option("--model", default=None)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--json", "as_json", is_flag=True, default=False)
def limits_alias(
    task: str | None,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Deprecated alias for `inspect ctl config`."""
    _deprecation_note("limits", "config")
    _run_config(
        task,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        log_buffer=None,
        log_shared=None,
        dry_run=dry_run,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# command runners (shared by the canonical commands and the aliases)
# ---------------------------------------------------------------------------


def _run_task_list(as_json: bool) -> None:
    # Stamp as_of BEFORE the reads: anything that changes during them has a
    # timestamp >= as_of and is caught by the next poll rather than missed.
    as_of = time.time()
    summaries = _fetch_summaries(list_discovered_servers())

    if as_json:
        click.echo(json_lib.dumps({"as_of": as_of, "tasks": summaries}, indent=2))
        return

    if not summaries:
        _echo_no_running_evals()
        return

    _print_human_table(summaries)
    _print_keep_alive_footer(summaries)


class _SampleRows(NamedTuple):
    """Result of :func:`_list_sample_rows`.

    ``as_of`` is the envelope timestamp (the earliest of the per-server
    ``as_of`` values, so nothing between them is missed). ``targets`` are the
    resolved target summaries; ``read`` the subset whose samples read actually
    succeeded (an unscoped fan-out warn-and-skips unreachable evals, and the
    human output must not make positive claims about samples it never saw).
    Every row carries ``task_id`` / ``task`` unconditionally (outputs feed
    inputs: the row's identifiers are the selectors other commands take).
    """

    as_of: float
    targets: list[dict[str, Any]]
    read: list[dict[str, Any]]
    rows: list[dict[str, Any]]


def _list_sample_rows(task: str | None, active_since: float | None) -> _SampleRows:
    """Fetch sample rows for one task (``task`` given) or all running tasks."""
    fallback_as_of = time.time()
    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        return _SampleRows(as_of=fallback_as_of, targets=[], read=[], rows=[])

    if task is not None:
        targets = [_resolve_target_eval(summaries, task)]
    else:
        targets = summaries

    as_of_values: list[float] = []
    read: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for target in targets:
        # Query by the task's current eval id (resolved fresh each invocation,
        # so this still works after a retry minted a new one).
        try:
            target_as_of, samples = _fetch_samples(
                target["socket_path"], target["eval_id"], active_since
            )
        except _ServerUnreachable as exc:
            if task is not None:
                _exit_samples_unreachable(target["eval_id"], exc)
            # An unscoped read spans whatever evals happen to be running; one
            # process exiting between discovery and this read shouldn't fail
            # the invocation (even if it was the only eval).
            click.echo(
                f"Skipping eval {target['eval_id']}: its samples could not be "
                f"read ({_unreachable_detail(exc)}) — it may have just exited.",
                err=True,
            )
            continue
        as_of_values.append(target_as_of)
        read.append(target)
        for sample in samples:
            rows.append(
                {
                    "task_id": target.get("task_id"),
                    "task": target.get("task"),
                    **sample,
                }
            )
    return _SampleRows(
        as_of=min(as_of_values, default=fallback_as_of),
        targets=targets,
        read=read,
        rows=rows,
    )


def _run_sample_list(
    task: str | None, active_since: float | None, as_json: bool
) -> None:
    as_of, targets, read, rows = _list_sample_rows(task, active_since)

    if as_json:
        click.echo(json_lib.dumps({"as_of": as_of, "samples": rows}, indent=2))
        return

    if not targets:
        _echo_no_running_evals()
        return

    # "(no samples started yet)" is a positive claim; when every target was
    # warn-and-skipped as unreachable we never saw its samples, so say that.
    empty = "(no samples started yet)" if read else "(samples unavailable)"
    if len(targets) == 1:
        click.echo(_task_header(targets[0]))
        if not rows:
            click.echo(empty)
            return
        click.echo()
        _print_samples_table(rows)
    else:
        if not rows:
            click.echo(empty)
            return
        _print_samples_table(rows, show_task=True)


def _run_sample_errors(task: str | None, as_json: bool) -> None:
    as_of, targets, read, rows = _list_sample_rows(task, None)
    errored = [s for s in rows if s.get("error") or (s.get("retries") or 0) > 0]

    if as_json:
        click.echo(json_lib.dumps({"as_of": as_of, "samples": errored}, indent=2))
        return

    if not targets:
        _echo_no_running_evals()
        return

    # As in `_run_sample_list`: don't assert "(no errors or retries)" for
    # targets whose samples read was warn-and-skipped as unreachable.
    empty = "(no errors or retries)" if read else "(samples unavailable)"
    if len(targets) == 1:
        click.echo(_task_header(targets[0]))
        if not errored:
            click.echo(empty)
            return
        click.echo()
        _print_errors_table(errored)
    else:
        if not errored:
            click.echo(empty)
            return
        _print_errors_table(errored, show_task=True)


def _run_sample_show(
    task: str, sample_id: str, epoch: int, show_traceback: bool, as_json: bool
) -> None:
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

    # The error detail is the authoritative core; fold in the sample's listing
    # row for the summary fields (timing / tokens / messages) it doesn't carry.
    try:
        _as_of, samples = _fetch_samples(target["socket_path"], target["eval_id"])
    except _ServerUnreachable as exc:
        # The detail already in hand answers the question; the process exiting
        # between the two reads shouldn't discard it.
        click.echo(
            f"Could not read the samples listing for eval {target['eval_id']} "
            f"({_unreachable_detail(exc)}); showing the sample without its "
            "summary fields (timing / tokens / messages).",
            err=True,
        )
        samples = []
    row = next(
        (
            s
            for s in samples
            if str(s.get("sample_id")) == str(detail.get("sample_id"))
            and s.get("epoch") == detail.get("epoch")
        ),
        None,
    )
    merged: dict[str, Any] = {
        "task_id": target.get("task_id"),
        "task": target.get("task"),
        **(row or {}),
        **detail,
    }

    if as_json:
        click.echo(json_lib.dumps(merged, indent=2))
        return

    _print_sample_detail(merged, show_traceback)


def _run_sample_events(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    cursor: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    _validate_cursor(cursor)

    # The unseeded default is a recent tail — never an empty page, never the
    # full backlog. A cursor or an explicit window disables it.
    if cursor is None and tail is None and since_time is None and until is None:
        tail = _DEFAULT_EVENTS_TAIL

    summaries = _fetch_summaries(list_discovered_servers())
    if not summaries:
        if as_json:
            # Carry the identifier echo even on the empty page so every
            # --json page has a uniform shape (task_id is unresolvable
            # with no running evals).
            empty_page: dict[str, Any] = {
                "task_id": None,
                "sample_id": sample_id,
                "epoch": epoch,
                "events": [],
                "next": None,
                "done": True,
            }
            click.echo(json_lib.dumps(empty_page, indent=2))
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task)
    page = _fetch_sample_events(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
    )
    # Echo the resolved identifiers so a defaulted epoch is visible and the
    # row round-trips into other commands' selectors.
    page = {
        "task_id": target.get("task_id"),
        "sample_id": sample_id,
        "epoch": epoch,
        **page,
    }

    if as_json:
        click.echo(json_lib.dumps(page, indent=2))
        return

    _print_events(page)


def _exit_removed_since(value: str) -> NoReturn:
    """Teach the `--since` split instead of click's stock no-such-option error.

    The old flag was the cursor; click's own suggestion ("did you mean
    --since-time?") points cursor-holders the wrong way, so the command keeps
    a hidden `--since` whose only job is this error — routed by the same
    timestamp heuristic `--cursor` validation uses.
    """
    try:
        float(value)
        hint = "this value looks like a timestamp — use --since-time"
    except ValueError:
        hint = "pass it to --cursor (the `next` value from a prior page)"
    click.echo(
        f"--since was split into --cursor (opaque resume cursor) and "
        f"--since-time (wall-clock window): {hint}.",
        err=True,
    )
    raise click.exceptions.Exit(code=1)


def _validate_cursor(cursor: str | None) -> None:
    """Reject a ``--cursor`` value that isn't an opaque cursor token.

    The server treats a non-decodable cursor as "restart from the beginning";
    for an agent that passed a timestamp that silent restart hides the
    mistake, so the CLI errors instead — teaching ``--since-time`` when the
    value looks like a timestamp.
    """
    if cursor is None:
        return
    from inspect_ai._control.events import decode_cursor

    nonce, _offset = decode_cursor(cursor)
    if nonce is not None:
        return
    try:
        float(cursor)
        hint = " — this looks like a timestamp; did you mean --since-time?"
    except ValueError:
        hint = " — pass the `next` value from a prior page."
    click.echo(f"Invalid --cursor value '{cursor}'{hint}", err=True)
    raise click.exceptions.Exit(code=1)


def _run_keep_alive(pid: int | None, *, keep: bool, as_json: bool) -> None:
    """Latch keep-alive on (``keep``) or off (``release``) for one process."""
    verb = "keep" if keep else "release"
    target = _resolve_target_server(pid)
    try:
        body = _post_to_server(target.socket_path, f"/{verb}")
    except (httpx.HTTPError, OSError) as exc:
        what = "set keep-alive for" if keep else "release"
        click.echo(f"Failed to {what} pid {target.pid}: {exc}", err=True)
        raise click.exceptions.Exit(code=1) from exc

    # `changed` distinguishes applied from the idempotent already-in-that-state
    # no-op; an older server omits it (detail then just carries what it sent).
    detail = {k: v for k, v in body.items() if k != "ok"} if body else {}
    if as_json:
        result = {
            "target": {"pid": target.pid},
            "applied": True,
            "dry_run": False,
            "detail": detail,
        }
        click.echo(json_lib.dumps(result, indent=2))
        return

    already = detail.get("changed") is False
    if keep:
        click.echo(
            f"Keep-alive already on for pid {target.pid}."
            if already
            else f"Keep-alive requested for pid {target.pid}."
        )
    else:
        click.echo(
            f"Keep-alive already off for pid {target.pid}."
            if already
            else f"Release requested for pid {target.pid}."
        )


def _run_log_flush(task: str | None, as_json: bool) -> None:
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers)
    scope = _resolve_scope(servers, summaries, task, per_task_option="task log-flush")
    if scope is None:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return
    # per_task_option forbids the process-scope fallbacks, so the resolved
    # scope always carries a task
    assert scope.task_id is not None
    result = _post_flush(scope.socket_path, scope.task_id)

    if as_json:
        envelope = {
            "target": {
                "task_id": scope.task_id,
                "task": scope.task,
            },
            "applied": True,
            "dry_run": False,
            "detail": result,
        }
        click.echo(json_lib.dumps(envelope, indent=2))
        return

    flushed = int(result.get("flushed", 0) or 0)
    click.echo(scope.header)
    if flushed:
        click.echo(
            f"\nFlushed {flushed} sample{'' if flushed == 1 else 's'} to the log."
        )
    else:
        click.echo("\nNo buffered samples to flush.")


def _run_process_list(as_json: bool) -> None:
    as_of = time.time()
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers) if servers else []

    rows: list[dict[str, Any]] = []
    for server in servers:
        hosted = [s for s in summaries if s.get("pid") == server.pid]
        # keep-alive is a process-level property every hosted task shares;
        # unknown (None) when no task has registered yet.
        keep_alive = bool(hosted[0].get("keep_alive")) if hosted else None
        rows.append(
            {
                "pid": server.pid,
                "socket_path": str(server.socket_path),
                "started_at": server.started_at,
                "keep_alive": keep_alive,
                "tasks": [
                    {
                        "task_id": t.get("task_id"),
                        "task": t.get("task"),
                        "status": t.get("status"),
                    }
                    for t in hosted
                ],
            }
        )

    if as_json:
        click.echo(json_lib.dumps({"as_of": as_of, "processes": rows}, indent=2))
        return

    if not rows:
        click.echo("No running inspect processes found.")
        return

    table_rows: list[tuple[str, ...]] = []
    for row in rows:
        keep = row["keep_alive"]
        tasks = row["tasks"]
        table_rows.append(
            (
                str(row["pid"]),
                "?" if keep is None else ("on" if keep else "off"),
                ", ".join(str(t.get("task") or "?") for t in tasks) or "(starting)",
                _format_started(row["started_at"]),
            )
        )
    _render_table(("pid", "keep-alive", "tasks", "started"), table_rows)


def _run_config(
    task: str | None,
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    log_buffer: int | None,
    log_shared: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    set_limits = (
        max_samples is not None
        or max_sandboxes is not None
        or max_connections is not None
    )
    set_buffer = log_buffer is not None or log_shared is not None
    set_values = set_limits or set_buffer

    # Task-scoped knobs follow the mutation selector rule (sole running task
    # default, explicit TASK otherwise); process-scoped knobs need no selector.
    per_task_option = next(
        (
            name
            for name, value in (
                ("--max-samples", max_samples),
                ("--log-buffer", log_buffer),
                ("--log-shared", log_shared),
            )
            if value is not None
        ),
        None,
    )

    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers)

    scope = _resolve_scope(
        servers,
        summaries,
        task,
        per_task_option=per_task_option,
        no_task_id_advice="Run without TASK to view or set the process-wide config.",
    )
    if scope is None:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    limits_view = _exec_limits(
        scope.socket_path,
        scope.task_id,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        log_buffer=log_buffer,
        log_shared=log_shared,
        dry_run=dry_run,
        set_values=set_values,
    )

    # The buffer knobs ride the task config view (`buffer` key); a task with
    # no live sample buffer (e.g. a reused log, or a superseded retry attempt)
    # reports it as None. On a view that's just a knob with nothing to adjust,
    # reported as a warning like the limits knobs. Only an explicit
    # --log-buffer/--log-shared is an error (there's nothing to apply it to) —
    # and since any limits set has already landed in the same PATCH, the error
    # must not read as "nothing applied".
    buffer_warnings: list[str] = []
    if scope.task_id is not None and limits_view.get("buffer") is None:
        if set_buffer:
            click.echo(
                f"Task '{scope.task_id}' has no sample buffer in this "
                "process (e.g. a reused log, or a retry attempt that's "
                "been superseded) — --log-buffer/--log-shared cannot be "
                "set for this task."
                + (
                    " The other requested knobs were still applied."
                    if set_limits and not dry_run
                    else ""
                ),
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        buffer_warnings.append(
            "log_buffer/log_shared are not adjustable for this task "
            "(no live sample buffer — e.g. a reused log)"
        )

    # The process-scoped knobs reach every task in the process — surface that
    # blast radius structurally when a set (or dry-run) used one.
    global_knobs = [
        name
        for name, value in (
            ("--max-connections", max_connections),
            ("--max-sandboxes", max_sandboxes),
        )
        if value is not None
    ]
    notes = []
    note = _process_scope_note(global_knobs, scope.siblings)
    if note:
        notes.append(note)

    config = _compose_config(
        scope,
        limits_view,
        dry_run=dry_run,
        set_values=set_values,
        notes=notes,
        extra_warnings=buffer_warnings,
    )

    if as_json:
        click.echo(json_lib.dumps(config, indent=2))
        return

    click.echo(scope.header)
    click.echo()
    _print_config(config, changed=set_values)


def _compose_config(
    scope: _DirectiveScope,
    limits_view: dict[str, Any],
    *,
    dry_run: bool,
    set_values: bool,
    notes: list[str],
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Shape the server's config view into the scope-labeled CLI view.

    Every knob carries ``"scope": "task" | "process"`` — scope is a property
    of the knob, not of the command path, so the output (not the spelling)
    is where an agent reads a knob's blast radius.
    """
    knobs: dict[str, Any] = {}
    if "max_samples" in limits_view:
        knobs["max_samples"] = {"scope": "task", **limits_view["max_samples"]}
    knobs["max_sandboxes"] = {
        "scope": "process",
        "providers": limits_view.get("max_sandboxes") or [],
    }
    knobs["max_connections"] = {
        "scope": "process",
        "adaptive": limits_view.get("adaptive") or [],
    }
    buffer_view = limits_view.get("buffer")
    if buffer_view is not None:
        knobs["log_buffer"] = {
            "scope": "task",
            "value": buffer_view.get("log_buffer"),
            "pending": buffer_view.get("pending"),
        }
        knobs["log_shared"] = {
            "scope": "task",
            "value": buffer_view.get("log_shared"),
        }

    requested = dict(limits_view.get("requested") or {})

    return {
        "target": {
            "scope": "task" if scope.task_id else "process",
            "task_id": scope.task_id,
            "task": scope.task,
        },
        "knobs": knobs,
        "warnings": [*(limits_view.get("warnings") or []), *(extra_warnings or [])],
        "notes": notes,
        "applied": bool(set_values and not dry_run),
        "dry_run": dry_run,
        "requested": requested or None,
    }


class _DirectiveScope(NamedTuple):
    """A directive command's resolved target (see :func:`_resolve_scope`)."""

    socket_path: str
    task_id: str | None
    """``None`` targets the process-level scope."""
    eval_id: str | None
    """The task's current attempt (``None`` for the process-level scope)."""
    task: str | None
    """The task's name (``None`` for the process-level scope)."""
    header: str
    siblings: int
    """Tasks sharing the target process (0 when resolved before registration)."""


def _resolve_scope(
    servers: list[DiscoveredControlServer],
    summaries: list[dict[str, Any]],
    task: str | None,
    *,
    per_task_option: str | None = None,
    no_task_id_advice: str = "",
) -> _DirectiveScope | None:
    """Resolve the task-or-process scope a directive command targets.

    The one resolution rule for directives with an optional ``TASK`` (config
    and task log-flush today; task cancel/drain are expected to reuse it): an
    explicit ``TASK`` targets that task; no ``TASK`` defaults to the sole
    process — a single-active-task process resolves to that task (completed
    eval-set siblings don't count), a multi-task process resolves to the
    process-level scope. ``per_task_option`` names the option or command
    (e.g. ``--max-samples``, ``task log-flush``) that requires a single task
    and therefore forbids the process-scope fallbacks. ``no_task_id_advice``
    is an optional caller-specific sentence appended to the pre-task-id
    reused-log error (e.g. config's "run without TASK" pointer).

    Returns ``None`` when there is nothing to target (the caller prints the
    no-running-evals message) and exits directly on ambiguous or invalid
    selections.
    """
    if not summaries:
        # A process binds its control endpoint before its first task registers
        # (sandbox startup / image pulls can take minutes), so an empty task
        # list doesn't mean no process. With a sole process and no per-task
        # ask, target the process-level scope so a startup retune (e.g.
        # --max-sandboxes during a docker pull) lands instead of bailing.
        if len(servers) == 1 and task is None and per_task_option is None:
            return _DirectiveScope(
                socket_path=str(servers[0].socket_path),
                task_id=None,
                eval_id=None,
                task=None,
                header="process · starting",
                siblings=0,
            )
        return None

    if task is not None:
        target = _resolve_target_eval(summaries, task)
        socket_path = str(target["socket_path"])
        task_id = str(target["task_id"])
        if not task_id:
            # a reused log written before task ids existed — addressable only
            # by its (superseded) eval id, which the directive wire doesn't use
            click.echo(
                f"Task '{target.get('task') or '?'}' predates task ids (an "
                "older reused log) — it can't be targeted by task-keyed "
                "directives." + (f" {no_task_id_advice}" if no_task_id_advice else ""),
                err=True,
            )
            raise click.exceptions.Exit(code=1)
        return _DirectiveScope(
            socket_path=socket_path,
            task_id=task_id,
            eval_id=str(target.get("eval_id") or "") or None,
            task=str(target.get("task") or "") or None,
            header=_task_header(target),
            siblings=sum(
                1 for s in summaries if str(s.get("socket_path")) == socket_path
            ),
        )

    sockets = sorted({str(s.get("socket_path")) for s in summaries})
    if len(sockets) > 1:
        # multiple processes: can't default to one — passing a task id
        # disambiguates the process too
        _exit_ambiguous(summaries, "Multiple processes are running")
    socket_path = sockets[0]
    tasks_in_proc = [s for s in summaries if str(s.get("socket_path")) == socket_path]
    # a finished task's config is no longer meaningfully adjustable, so the
    # sole-task default keys on what is still active — an eval-set with one
    # running and N completed tasks resolves to the running one
    active = [s for s in tasks_in_proc if s.get("status") in ("running", "pending")]
    candidates = active or tasks_in_proc
    if len(candidates) == 1 and str(candidates[0].get("task_id") or ""):
        target = candidates[0]
        return _DirectiveScope(
            socket_path=socket_path,
            task_id=str(target["task_id"]),
            eval_id=str(target.get("eval_id") or "") or None,
            task=str(target.get("task") or "") or None,
            header=_task_header(target),
            siblings=len(tasks_in_proc),
        )
    if per_task_option is not None:
        _exit_ambiguous(
            candidates,
            f"{per_task_option} targets a single task, but this process is "
            f"running {len(candidates)} tasks",
        )
    return _DirectiveScope(
        socket_path=socket_path,
        task_id=None,  # process-global scope
        eval_id=None,
        task=None,
        header=f"process · {len(tasks_in_proc)} tasks",
        siblings=len(tasks_in_proc),
    )


def _process_scope_note(global_knobs: list[str], siblings: int) -> str | None:
    """Note that process-scoped config knobs reach every task in the process.

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
        f"{' and '.join(global_knobs)} {verb} across all "
        f"{siblings} tasks sharing this process."
    )


def _resolve_target_server(pid: int | None) -> DiscoveredControlServer:
    """Pick the single process a ``keep`` / ``release`` targets, or exit.

    With a ``PID`` the matching process is used (error if none matches);
    without it, the sole running process is the default, and an ambiguous
    set (more than one) errors with the candidate pids. (Keep / release are
    idempotent, last-write-wins lifecycle toggles, so they get the
    sole-target default rather than requiring the selector outright.)
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
        "Pass a PID to disambiguate (see `inspect ctl process`).",
        err=True,
    )
    raise click.exceptions.Exit(code=1)


def _post_to_server(socket_path: Path, path: str) -> dict[str, Any]:
    """POST to a control server's ``path`` over its AF_UNIX socket.

    Returns the response body (``{}`` when it isn't a JSON object) so
    callers can surface the mutation result detail.
    """
    transport = httpx.HTTPTransport(uds=str(socket_path))
    with httpx.Client(
        transport=transport, base_url="http://localhost", timeout=5.0
    ) as client:
        response = client.post(path)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}


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
                "/tasks",
                what=f"Reading tasks from pid {server.pid}",
            )
        except _ServerUnreachable as exc:
            # a 404 means the process is serving a control API without this
            # route — version skew between the CLI and the eval process —
            # where transport errors mean the process is gone
            cause = exc.__cause__
            hint = (
                "it may be running a different inspect version than this CLI"
                if isinstance(cause, httpx.HTTPStatusError)
                and cause.response.status_code == 404
                else "it may have just exited"
            )
            click.echo(
                f"Skipping pid {server.pid}: its control endpoint could not be "
                f"read ({_unreachable_detail(exc)}) — {hint}.",
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

    ``query`` matches a task id first (full, then unique prefix — ``task
    list`` shows truncated ids; ids are stable across retries), then falls
    back to the task name (see :func:`_match_by_task_name`). Without a query,
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
    ``gpqa`` and ``gpqa_diamond`` are running. (The same selector rule
    resolves model names in ``ctl config --model`` — see `match_name_prefix`.)
    """
    return match_name_prefix(summaries, query, lambda s: str(s.get("task", "")))


def _exit_ambiguous(matches: list[dict[str, Any]], prefix: str) -> NoReturn:
    """Echo an ambiguity error with a candidate table and exit.

    The same columns `ctl task list` leads with, so same-named tasks (one
    task against several models) are still tellable apart — an inline
    `id (name)` listing can't disambiguate those. A pid column appears only
    when the candidates span more than one process (the common case is one).
    """
    click.echo(f"{prefix} — pass a task id to choose one:\n", err=True)
    multi_process = len({s.get("pid") for s in matches}) > 1
    headers = ("task id", "task", "model", "status") + (
        ("pid",) if multi_process else ()
    )
    rows = [
        (
            _short_id(str(s.get("task_id") or "")),
            str(s.get("task") or "?"),
            str(s.get("model") or ""),
            str(s.get("status") or ""),
        )
        + ((str(s.get("pid") or ""),) if multi_process else ())
        for s in matches
    ]
    _render_table(headers, rows, err=True)
    raise click.exceptions.Exit(code=1)


def _unreachable_detail(exc: _ServerUnreachable) -> str:
    """Human-readable cause of an unreachable-server error."""
    cause = exc.__cause__
    return _error_detail(cause) if isinstance(cause, Exception) else str(exc)


def _exit_samples_unreachable(eval_id: str, exc: _ServerUnreachable) -> NoReturn:
    """Echo a samples-read failure for ``eval_id`` and exit non-zero."""
    click.echo(
        f"Failed to read samples for eval {eval_id}: {_unreachable_detail(exc)}",
        err=True,
    )
    raise click.exceptions.Exit(code=1) from exc


def _fetch_samples(
    socket_path: str, eval_id: str, active_since: float | None = None
) -> tuple[float, list[dict[str, Any]]]:
    """Query one control server for an eval's samples.

    Returns ``(as_of, samples)`` from the server's ``{as_of, samples}``
    envelope — ``as_of`` is stamped server-side before the listing is built,
    so feeding it back as the next ``active_since`` can't miss changes that
    landed during the read. With ``active_since`` (unix ts), restricts to
    samples started or updated since then — the recency delta. Tolerates an
    older server's bare array (stamping ``as_of`` client-side, pre-request).

    Raises :class:`_ServerUnreachable` on a non-retryable read failure; the
    caller decides whether to warn-and-skip (an unscoped fan-out over many
    evals) or fail the command (a single targeted read).
    """
    fallback_as_of = time.time()
    params = {} if active_since is None else {"active_since": active_since}
    page = _get_with_retry(
        socket_path,
        f"/evals/{eval_id}/samples",
        params=params,
        what=f"Reading samples for eval {eval_id}",
    )
    if isinstance(page, dict):
        samples = page.get("samples")
        as_of = page.get("as_of")
        return (
            float(as_of) if isinstance(as_of, (int, float)) else fallback_as_of,
            samples if isinstance(samples, list) else [],
        )
    return fallback_as_of, page if isinstance(page, list) else []


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
    cursor: str | None,
    tail: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
) -> dict[str, Any]:
    """Query one control server for a page of a sample's transcript events."""
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply. The
    # wire parameter for the cursor is `since` (the CLI flag is --cursor).
    params: dict[str, Any] = {"sample_id": sample_id, "epoch": epoch, "full": full}
    if cursor is not None:
        params["since"] = cursor
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


def _request_json(
    socket_path: str,
    path: str,
    *,
    what: str,
    not_found: str,
    params: dict[str, Any] | None = None,
    mutate: Literal["post", "patch"] | None = None,
) -> dict[str, Any]:
    """GET (retrying a busy process) or mutate ``path``; return its JSON dict.

    The shared transport / error policy for the per-eval and per-task ctl
    commands. A read goes through :func:`_get_response_with_retry`; a mutation
    isn't idempotent across transport failures, so it gets a single attempt
    with the full mutation budget (see :data:`_MUTATION_TIMEOUT` — eg. a
    remote S3 log flush can take a while). A 404 prints ``not_found`` and
    exits non-zero; a 400 surfaces the server's ``{"error": ...}`` body;
    transport errors exit with ``what`` as context.
    """
    verb = "update" if mutate else "read"
    try:
        if mutate is not None:
            transport = httpx.HTTPTransport(uds=str(socket_path))
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=httpx.Timeout(_MUTATION_TIMEOUT, connect=_CONNECT_TIMEOUT),
            ) as client:
                if mutate == "post":
                    response = client.post(path, params=params)
                else:
                    response = client.patch(path, params=params)
        else:
            response = _get_response_with_retry(
                socket_path, path, params=params, what=f"Reading {what}"
            )
        if response.status_code == 404:
            click.echo(not_found, err=True)
            raise click.exceptions.Exit(code=1)
        if response.status_code == 400:
            click.echo(
                f"Invalid request: {_error_detail_from_response(response)}", err=True
            )
            raise click.exceptions.Exit(code=1)
        response.raise_for_status()
        result = response.json()
    except _ServerUnreachable as exc:
        detail = (
            _error_detail(exc.__cause__)
            if isinstance(exc.__cause__, Exception)
            else str(exc)
        )
        click.echo(f"Failed to {verb} {what}: {detail}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        click.echo(f"Failed to {verb} {what}: {_error_detail(exc)}", err=True)
        raise click.exceptions.Exit(code=1) from exc
    return result if isinstance(result, dict) else {}


def _post_flush(socket_path: str, task_id: str) -> dict[str, Any]:
    """Ask one control server to flush a task's buffered samples to the log."""
    return _request_json(
        socket_path,
        f"/tasks/{task_id}/log-flush",
        what=f"log-flush of task {task_id}",
        not_found=(
            f"Task '{task_id}' is not flushable — it has no live sample "
            "buffer in this process (e.g. a reused log, or a retry "
            "attempt that's been superseded)."
        ),
        mutate="post",
    )


def _exec_limits(
    socket_path: str,
    task_id: str | None,
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    log_buffer: int | None = None,
    log_shared: int | None = None,
    dry_run: bool,
    set_values: bool,
) -> dict[str, Any]:
    """Read (``set_values=False``) or retune a scope's retunable config.

    With ``task_id`` set this targets that task's ``/tasks/<id>/config`` (the
    per-task view, including ``max_samples`` and the ``log_buffer`` /
    ``log_shared`` buffer params; task ids are stable across retry attempts);
    with ``task_id=None`` it targets the process-level ``/config``
    (``max_sandboxes`` / ``max_connections`` only). ``model`` filters the
    adaptive controllers (a read param, applies to both). The read is a GET
    that retries a busy process on timeout; the update is a single-shot PATCH
    given the full mutation budget (see :data:`_MUTATION_TIMEOUT`). ``dry_run``
    only applies to a set.
    """
    params: dict[str, Any] = {}
    if max_samples is not None:
        params["max_samples"] = max_samples
    if max_sandboxes is not None:
        params["max_sandboxes"] = max_sandboxes
    if max_connections is not None:
        params["max_connections"] = max_connections
    if model is not None:
        params["model"] = model
    if log_buffer is not None:
        params["log_buffer"] = log_buffer
    if log_shared is not None:
        params["log_shared"] = log_shared
    if dry_run:
        params["dry_run"] = True
    # the 404 messages distinguish "task unknown to the server" from version
    # skew: a process running an older inspect has neither route, and the
    # process-level path can only 404 for that reason
    if task_id is not None:
        not_found = (
            f"Task '{task_id}' not found in this process (it may have "
            "finished, or the process may be running an older inspect "
            "without the config endpoints)."
        )
    else:
        not_found = (
            "This process does not support the config endpoints (older "
            "inspect version?)."
        )
    scope = f"task {task_id}" if task_id is not None else "process"
    return _request_json(
        socket_path,
        f"/tasks/{task_id}/config" if task_id is not None else "/config",
        what=f"config for {scope}",
        not_found=not_found,
        params=params,
        mutate="patch" if set_values else None,
    )


def _error_body(response: httpx.Response) -> str | None:
    """The server's ``{"error": ...}`` body detail, or ``None`` when absent."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return None


def _error_detail_from_response(response: httpx.Response) -> str:
    """Prefer the server's ``{"error": ...}`` body over a bare status message."""
    return _error_body(response) or f"HTTP {response.status_code}"


def _print_config(config: dict[str, Any], *, changed: bool) -> None:
    """Render the composed config view as a short labeled block.

    Every knob line carries its scope (``task`` / ``process``) — the honest
    place to read a knob's blast radius, since the command path makes no
    scope claim.
    """
    dry_run = bool(config.get("dry_run"))
    if changed:
        click.echo("would-be config (dry run):" if dry_run else "updated config:")
    else:
        click.echo("config:")

    knobs = config.get("knobs") or {}

    # On a dry-run the server reports the pre-change view (nothing was mutated);
    # the intended values live in `requested`. Render `current → would-be` so the
    # header's promise is met without losing the current value. On a real set the
    # view already reflects the applied change, so no arrow is needed.
    requested = config.get("requested") if dry_run else None
    requested = requested if isinstance(requested, dict) else {}

    def _target(current: Any, key: str) -> str:
        proposed = requested.get(key)
        return f"{current}{'' if proposed is None or proposed == current else f' → {proposed}'}"

    # The process-level view carries no `max_samples` knob (it's per-task):
    # show it as per-task rather than claiming a value. Distinguish that from
    # a task view that carries an explicit `{"adjustable": false}`.
    if "max_samples" not in knobs:
        click.echo("  max samples [task]:      per task (pass a task to view/set)")
    else:
        max_samples = knobs.get("max_samples") or {}
        if max_samples.get("adjustable"):
            limit = _target(max_samples.get("limit"), "max_samples")
            in_use = max_samples.get("in_use")
            click.echo(f"  max samples [task]:      {limit} ({in_use} in use)")
        elif max_samples.get("tracks_adaptive"):
            # sample concurrency tracks this task's adaptive controller, so
            # there's no user setpoint to show — point at where the numbers are
            click.echo(
                "  max samples [task]:      tracks adaptive connections (see below)"
            )
        else:
            # no live sample limiter for this task (e.g. a reused log) — the
            # adaptive block below, if any, belongs to other tasks' models
            click.echo(
                "  max samples [task]:      not adjustable (no live sample limiter)"
            )

    sandboxes = (knobs.get("max_sandboxes") or {}).get("providers") or []
    if sandboxes:
        rendered = ", ".join(
            f"{s.get('type')} {_target(s.get('limit'), 'max_sandboxes')} ({s.get('in_use')} in use)"
            for s in sandboxes
        )
        click.echo(f"  max sandboxes [process]: {rendered}")
    else:
        click.echo("  max sandboxes [process]: none in effect")

    adaptive = (knobs.get("max_connections") or {}).get("adaptive") or []
    if adaptive:
        click.echo("  adaptive connections [process]:")
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

    if "log_buffer" in knobs:
        log_buffer = knobs.get("log_buffer") or {}
        value = _target(log_buffer.get("value"), "log_buffer")
        click.echo(
            f"  log buffer [task]:       {value} samples "
            f"({log_buffer.get('pending')} pending)"
        )
    if "log_shared" in knobs:
        shared = (knobs.get("log_shared") or {}).get("value")
        rendered_shared = _target(shared, "log_shared") if shared is not None else None
        click.echo(
            f"  shared sync [task]:      "
            f"{f'{rendered_shared}s' if rendered_shared is not None else 'off'}"
        )

    for warning in config.get("warnings") or []:
        click.echo(f"  ! {warning}")
    for note in config.get("notes") or []:
        click.echo(f"  note: {note}")


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
        click.echo(f"next: {nxt}  (resume with --cursor)")


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


def _print_errors_table(samples: list[dict[str, Any]], show_task: bool = False) -> None:
    """Render errored/retried samples as a triage table on stdout.

    ``show_task`` adds a leading task column — the rendering for a listing
    that spans tasks (the ``--json`` rows carry ``task_id`` regardless).
    """
    rows: list[tuple[str, ...]] = []
    for s in samples:
        row = [
            str(s["sample_id"]) if s.get("sample_id") is not None else "?",
            str(s.get("epoch", "")),
            s.get("status", "") or "",
            str(s["retries"]) if s.get("retries") else "",
            _truncate(s.get("error") or "", 64),
        ]
        if show_task:
            row.insert(0, str(s.get("task") or _short_id(str(s.get("task_id") or ""))))
        rows.append(tuple(row))
    headers = ["sample", "epoch", "status", "retries", "error"]
    if show_task:
        headers.insert(0, "task")
    _render_table(tuple(headers), rows)


def _print_sample_detail(detail: dict[str, Any], show_traceback: bool) -> None:
    """Render one sample's summary + error history (prior attempts, then final)."""
    parts = [
        f"sample {detail.get('sample_id')}",
        f"epoch {detail.get('epoch')}",
        detail.get("status") or "",
    ]
    if detail.get("total_time") is not None:
        parts.append(_format_duration(detail.get("total_time")))
    if detail.get("total_tokens"):
        parts.append(f"{detail['total_tokens']} tok")
    if detail.get("message_count"):
        parts.append(f"{detail['message_count']} msgs")
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
    if isinstance(response, httpx.Response):
        detail = _error_body(response)
        if detail is not None:
            return detail
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
        # `inspect ctl sample list` takes.
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
    ``inspect ctl process keep``, which turns it on for a running process.
    """
    flags = [bool(s.get("keep_alive")) for s in summaries]
    click.echo()
    if all(flags):
        click.echo("keep-alive: on")
    elif not any(flags):
        click.echo("keep-alive: off  ·  set with `inspect ctl process keep`")
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


def _print_samples_table(
    samples: list[dict[str, Any]], show_task: bool = False
) -> None:
    """Render per-sample summaries as a simple aligned table on stdout.

    ``show_task`` adds a leading task column — the rendering for a listing
    that spans tasks (the ``--json`` rows carry ``task_id`` regardless).
    Three more columns are conditional, shown only when relevant (keeping the
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
        if show_task:
            row.insert(0, str(s.get("task") or _short_id(str(s.get("task_id") or ""))))
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
    if show_task:
        headers.insert(0, "task")
    if any_retries:
        headers.append("retries")
    if score_col is not None:
        headers.append("score")
    headers.append("time")
    if any_running:
        headers.append("idle")
    headers.extend(["tokens", "messages"])
    _render_table(tuple(headers), rows)


def _render_table(
    headers: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
    *,
    err: bool = False,
) -> None:
    """Print an aligned, dashed-underline table (to stderr when ``err``)."""
    widths = [
        max(len(h), max((len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]

    def _fmt_row(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    click.echo(_fmt_row(headers), err=err)
    click.echo(_fmt_row(tuple("-" * w for w in widths)), err=err)
    for row in rows:
        click.echo(_fmt_row(row), err=err)


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
