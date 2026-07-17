"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts the commands that operate on a *running* Inspect
eval via the per-process control server's HTTP endpoints. See
``design/control-channel.md`` for the design.

Commands are grouped by **resource noun**, mirroring the HTTP API's object
model (see "CLI command hierarchy: noun groups" in the design doc):

- ``task`` — a logical task in a running process (stable across retries):
  ``list`` (implied by the bare noun), ``log-flush``, ``cancel``; ``add`` /
  ``drain`` are planned.
- ``sample`` — one sample (``TASK SAMPLE_ID [EPOCH]``) or a task's samples:
  ``list`` (implied by the bare noun), ``show``, ``errors``, ``events``,
  ``cancel``; ``requeue`` is planned.
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

import copy
import functools
import inspect
import json as json_lib
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    NoReturn,
    ParamSpec,
    Protocol,
    cast,
)

import click
import httpx
from click.core import ParameterSource

from inspect_ai._control.cancel import TaskCancelAction
from inspect_ai._control.discovery import (
    DiscoveredControlServer,
    discovery_dir,
    list_discovered_servers,
)
from inspect_ai._control.state import (
    DEFAULT_SAMPLE_LIST_LIMIT,
    SAMPLE_STATUSES,
    effective_sample_limit,
    parse_status_filter,
)
from inspect_ai._util.name_match import match_name_prefix

if TYPE_CHECKING:
    # TYPE_CHECKING to keep the CLI import-light: `inspect_ai.log._samples`
    # pulls in a chunk of the core package this thin HTTP client never needs.
    from inspect_ai.log._samples import SampleCancelAction

# Events shown on an unseeded `sample events` read (no --cursor / --tail /
# --since-time / --until / --from-start): a recent tail rather than the full
# backlog — the first call must never be empty or a context-flooding dump
# (see the agent output contract in design/control-channel.md).
_DEFAULT_EVENTS_TAIL = 20

# One source of truth for each retunable config knob's scope. The `ctl config`
# option help tags, the composed JSON view's per-knob "scope" labels, and the
# human rendering's [task]/[process] labels all derive from this table, so a
# knob's advertised blast radius can't drift between the three surfaces.
_KNOB_SCOPE: dict[str, str] = {
    "max_samples": "task",
    "max_sandboxes": "process",
    "max_subprocesses": "process",
    "max_connections": "process",
    "key": "process",
    "log_buffer": "task",
    "log_shared": "task",
    "timeout": "process",
    "attempt_timeout": "process",
    "max_retries": "process",
}

# Minimum control-API version each knob requires of the *server* process (the
# `CONTROL_API_VERSION` from `inspect_ai._control` that its inspect embedded
# at launch). Parallel to `_KNOB_SCOPE`: every knob needs an entry (key-set
# parity is asserted in `_exec_limits` and pinned by a test). Since-0 knobs
# are never gated — and every *new* knob is since-0: strict servers
# (version >= 3, the only ones left in the field) reject unknown mutation
# params with a 400, so no pre-send gate is needed (see the skew-policy
# comment in `inspect_ai._control`). The nonzero entries predate strict
# mutations, when an older server's PATCH handler would silently ignore an
# unknown knob while applying the rest; `_gate_knob_support` hard-errors
# those against a pre-strict process before sending, and retires with
# issue #67.
_KNOB_SINCE: dict[str, int] = {
    "max_samples": 0,
    "max_sandboxes": 0,
    "max_subprocesses": 1,
    "max_connections": 0,
    "key": 2,
    "log_buffer": 0,
    "log_shared": 0,
    "timeout": 4,
    "attempt_timeout": 4,
    "max_retries": 4,
}

# Minimum control-API version for the config provenance params (`author` /
# `reason`, recorded into `EvalLog.config_updates`). Not a knob — the params
# change nothing — but the CLI sends a *defaulted* author the user never
# typed, and a strict older server would 400 the whole mutation for it, so
# the default is included only against servers advertising >= this version
# (an explicit --author/--reason against an older server hard-errors before
# sending, like the legacy knob gates). See `_gate_provenance_support`.
_PROVENANCE_SINCE = 5


class _IntOrClearType(click.ParamType):
    """Non-negative integer, or the keyword ``clear`` (restore launch config).

    The retry-override knobs' value domain: every integer >= 0 (up to the
    server-shared ``MAX_GENERATE_CONFIG_OVERRIDE`` bound) is a real value
    (``--max-retries 0`` means fail after the first attempt), so clearing an
    override needs an out-of-band spelling — the literal ``clear``, passed
    through to the server verbatim.
    """

    name = "integer or 'clear'"

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> int | Literal["clear"]:
        from inspect_ai.model._generate_overrides import (
            MAX_GENERATE_CONFIG_OVERRIDE,
        )

        if isinstance(value, int):
            parsed = value
        elif value.strip().lower() == "clear":
            return "clear"
        else:
            try:
                parsed = int(value)
            except ValueError:
                self.fail(f"{value!r} is not an integer or 'clear'.", param, ctx)
        if parsed < 0:
            self.fail(
                f"{parsed} is negative (pass 'clear' to restore launch config).",
                param,
                ctx,
            )
        if parsed > MAX_GENERATE_CONFIG_OVERRIDE:
            self.fail(
                f"{parsed} is larger than the maximum override value "
                f"({MAX_GENERATE_CONFIG_OVERRIDE}).",
                param,
                ctx,
            )
        return parsed


_INT_OR_CLEAR = _IntOrClearType()

# Rendered for a task-scoped knob that a process-level view can't show.
_PER_TASK_PLACEHOLDER = "per task (pass a task to view/set)"

# Display truncation for task ids (`task list` shows this many characters).
# Also the id-prefix length a busy-skipped resolution trusts (see
# `_resolve_target_eval` for the rationale).
_SHORT_ID_LEN = 12


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
    # merge into (not over) any pre-existing defaults for the verb
    existing = dict((ctx.default_map or {}).get(ctx.invoked_subcommand) or {})
    ctx.default_map = {
        **(ctx.default_map or {}),
        ctx.invoked_subcommand: {
            **existing,
            **{name: value for name, (value, _) in given.items()},
        },
    }


def _mirror_list_options(group: click.Group, list_command: click.Command) -> None:
    """Mirror ``list``'s options onto its group for the bare-noun default.

    Deriving the mirror from the verb's own params keeps the two surfaces
    from drifting: an option added to ``list`` is mirrored automatically,
    where a hand-maintained copy would let bare ``ctl sample --new-opt``
    break while ``ctl sample list --new-opt`` works. Only options are
    mirrored — ``list``'s positional TASK would land in the verb slot
    (see ``_NounGroup``).
    """
    for param in list_command.params:
        if isinstance(param, click.Option):
            mirrored = copy.copy(param)
            mirrored.help = "Mirrored from `list` for the bare-noun default."
            group.params.append(mirrored)


def _json_option(what: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--json`` flag every command carries, with per-command envelope help."""
    return click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help=f"Output as JSON ({what}).",
    )


@click.group("ctl")
def ctl_command() -> None:
    """Read and direct running evals and manage kept-alive processes.

    Commands are grouped by resource noun (listed below); `list` verbs are
    implied by the bare noun (`inspect ctl task` ≡ `inspect ctl task list`).
    All commands accept `--json`; a failed `--json` invocation emits an
    `{"error": {kind, exception, message, status}}` envelope on stdout
    (exit code stays non-zero; click usage errors — unknown option,
    missing argument — still exit 2 without one).

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


def _busy_pids_label(busy_pids: list[int]) -> str:
    """Name the busy-skipped processes for an error message."""
    pids = ", ".join(str(p) for p in busy_pids)
    return f"pid{'s' if len(busy_pids) != 1 else ''} {pids}"


def _busy_note(busy_pids: list[int]) -> str:
    """Advise on busy-skipped processes in an error message."""
    return f"{_busy_pids_label(busy_pids)} busy — try again shortly"


def _exit_all_busy(busy_pids: list[int]) -> NoReturn:
    """Exit non-zero when no task summaries were collected and busy processes remain.

    The honest sibling of :func:`_echo_no_running_evals`: at least one alive
    process didn't answer (any responsive ones reported no tasks yet — a
    control endpoint binds before its first task registers), so the 'nothing
    running' message (and an empty ``--json`` envelope with exit 0) would be
    a false claim about the busy pids.
    """
    _fail("busy", f"No tasks visible: {_busy_note(busy_pids)}.")


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
@click.pass_context
def task_group(ctx: click.Context, /, **mirrored: Any) -> None:
    """Operate on the tasks of running evals (bare `task` lists them).

    Task ids are stable across retries and are the TASK selector other
    commands take. `add` / `drain` are planned but not yet available.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(task_list_command, **mirrored)
    else:
        _forward_group_options(ctx)


assert isinstance(task_group, _NounGroup)
task_group.hint = lambda token: (
    f"No such command '{token}'. To list running tasks: "
    "`inspect ctl task list` (or the bare `inspect ctl task`)."
)


@task_group.command("list")
@_json_option("an `{as_of, tasks}` envelope")
def task_list_command(as_json: bool) -> None:
    """List running tasks across all live Inspect processes.

    Each `--json` row carries the selectors other commands take (`task_id`,
    `pid`) plus `log_location`, where results are being written. A task is
    finished exactly when `completed_at` is non-null — do not infer
    completion from sample counts (a cancelled or errored eval finishes
    with `completed < total`).
    """
    _run_task_list(as_json)


_mirror_list_options(task_group, task_list_command)


@task_group.command("log-flush")
@click.argument("task", required=False)
@_json_option("the mutation result envelope")
def task_log_flush_command(task: str | None, as_json: bool) -> None:
    """Flush a running task's buffered samples to its log now.

    Completed samples are written to the (possibly remote) log only when
    the buffer fills; this forces the write immediately. Safe to repeat.
    Tune the buffering policy itself with `inspect ctl config --log-buffer`
    / `--log-shared`. TASK (a task-id prefix or name) is required when
    several tasks run.
    """
    _run_log_flush(task, as_json)


@task_group.command("cancel")
@click.argument("task")
@click.option(
    "--action",
    type=click.Choice(["cancel", "score", "error"]),
    default="cancel",
    show_default=True,
    help=(
        "How in-flight samples are resolved: 'cancel' interrupts them and "
        "finalizes the log with an error status; 'score' scores them on the "
        "work done so far; 'error' marks them errored. With score/error, "
        "queued samples are abandoned and the task completes normally."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be cancelled without doing it.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the mutation result envelope).",
)
def task_cancel_command(task: str, action: str, dry_run: bool, as_json: bool) -> None:
    """Cancel a running task.

    In-flight samples are resolved per `--action`; completed samples are
    always kept, and an eval-set will not retry a cancelled task.
    Idempotent — cancelling a finished or already-cancelling task is a
    clean no-op (a plain cancel does escalate over a pending score/error
    resolution, so a stalled graceful cancel can still be torn down). A
    task between attempts (last attempt errored, retry queued but not
    started) is rejected — re-issue once the retry starts. To cancel a
    single sample, use `inspect ctl sample cancel`. TASK (a task-id prefix
    or name) is always required.
    """
    _run_task_cancel(
        task,
        action=cast(TaskCancelAction, action),
        dry_run=dry_run,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# sample group
# ---------------------------------------------------------------------------


@ctl_command.group(
    "sample",
    cls=_NounGroup,
    invoke_without_command=True,
)
@click.pass_context
def sample_group(ctx: click.Context, /, **mirrored: Any) -> None:
    """Operate on samples of running evals (bare `sample` lists them).

    An omitted TASK on `list` / `errors` reads across all running tasks.
    `requeue` is planned but not yet available.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(sample_list_command, **mirrored)
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
        "the `as_of` from the prior response's envelope. If the delta comes "
        "back truncated, re-poll with the same value plus `--all` before "
        "advancing to the new `as_of` — the dropped rows are typically "
        "terminal ones (running rows sort first and survive the cap) that "
        "will never match a later delta."
    ),
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help=(
        f"Cap the listing at this many rows per task (default: "
        f"{DEFAULT_SAMPLE_LIST_LIMIT}). Running samples sort first, so the "
        "cap keeps the most relevant rows; `counts` stays complete and "
        "`truncated` reports a hit cap."
    ),
)
@click.option(
    "--all",
    "all_samples",
    is_flag=True,
    default=False,
    help="List every sample row (no cap).",
)
@click.option(
    "--status",
    default=None,
    help=(
        "Only samples with these statuses (comma-separated: "
        f"{', '.join(SAMPLE_STATUSES)})."
    ),
)
@_json_option("an `{as_of, counts, samples, truncated}` envelope")
def sample_list_command(
    task: str | None,
    active_since: float | None,
    limit: int | None,
    all_samples: bool,
    status: str | None,
    as_json: bool,
) -> None:
    """List the samples (running and completed) of running evals.

    TASK is a task id (or unique prefix) or task name, matched at the start
    or after a `/`; omitted, the listing spans all running tasks. To poll
    for what changed, pass `--active-since` the `as_of` from the prior
    response's envelope.

    The listing is capped (running samples first); `counts` in the envelope
    is the complete status histogram regardless, and `truncated` reports
    whether rows were dropped. Widen with `--limit N` or `--all`, or narrow
    with `--status`.
    """
    _run_sample_list(
        task,
        active_since,
        as_json,
        status=status,
        limit=limit,
        all_samples=all_samples,
    )


_mirror_list_options(sample_group, sample_list_command)


@sample_group.command("errors")
@click.argument("task", required=False)
@_json_option("an `{as_of, counts, samples, truncated}` envelope")
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
@_json_option("the sample's summary + error detail")
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
        "read (no --cursor, no --from-start, and no --since-time/--until window)."
    ),
)
@click.option(
    "--from-start",
    is_flag=True,
    default=False,
    help=(
        "Start from the first event instead of the recent tail, then page "
        "through the full backlog via `next`/--cursor. Cannot be combined "
        "with --cursor, --tail, or --since-time."
    ),
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help=(
        "Max events per page (server default 500); page through the rest via "
        "`next`/--cursor. Counted before the --type filter, so a filtered "
        "page may return fewer. Combines with any window seed."
    ),
)
@click.option(
    "--type",
    "types",
    default=None,
    help=(
        "Comma-separated event types to include (e.g. `model,tool,error`); "
        "`all` for all. Default: the high-signal set."
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
@_json_option("the `{events, next, done}` envelope")
def sample_events_command(
    task: str,
    sample_id: str,
    epoch: int,
    cursor: str | None,
    legacy_since: str | None,
    tail: int | None,
    from_start: bool,
    limit: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    """Read one running sample's transcript events (cursored pull).

    The first call returns a recent tail (or the beginning, with
    `--from-start`); each page ends with a `next` cursor — pass it back via
    `--cursor` to read only what's new. `done: true` means the sample has
    terminated and no more events will come.
    """
    if legacy_since is not None:
        with _structured_failures(as_json):
            _exit_removed_since(legacy_since)
    _run_sample_events(
        task,
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        from_start=from_start,
        limit=limit,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
        as_json=as_json,
    )


@sample_group.command("cancel")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=None)
@click.option(
    "--action",
    type=click.Choice(["score", "error", "cancel"]),
    default="score",
    show_default=True,
    help=(
        "Outcome for the sample: 'score' runs the scorer on the work done "
        "so far; 'error' marks it errored; 'cancel' records it as cancelled "
        "(no scoring, not counted as an error)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be cancelled without doing it.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (the mutation result envelope).",
)
def sample_cancel_command(
    task: str,
    sample_id: str,
    epoch: int | None,
    action: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Cancel one running sample.

    The sample is resolved per `--action`; the rest of the task is
    unaffected. Idempotent — cancelling a sample that has already finished
    is a clean no-op. EPOCH defaults to 1 but is required whenever the
    task runs more than one epoch (a defaulted epoch would silently cancel
    a different attempt).
    """
    _run_sample_cancel(
        task,
        sample_id,
        epoch,
        action=cast("SampleCancelAction", action),
        dry_run=dry_run,
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
        f"[{_KNOB_SCOPE['max_samples']}] Max samples to run concurrently (under "
        "adaptive connections, sample concurrency tracks the controller instead)."
    ),
)
@click.option(
    "--max-sandboxes",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['max_sandboxes']}] Max sandboxes per provider.",
)
@click.option(
    "--max-subprocesses",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['max_subprocesses']}] Max concurrent subprocesses.",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_connections']}] Adaptive-connections scaling "
        "ceiling — the controllers' max."
    ),
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
    "--key",
    "key",
    type=(str, click.IntRange(min=1)),
    default=None,
    metavar="NAME LIMIT",
    help=(
        f"[{_KNOB_SCOPE['key']}] Set the named `concurrency()` limit NAME to "
        "LIMIT — any limit tools or task code register by name (the output's "
        "`concurrency keys` section lists them, exactly as addressable here). "
        "An unknown NAME errors, listing the available keys."
    ),
)
@click.option(
    "--log-buffer",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['log_buffer']}] Completed samples buffered before a "
        "log write — the retune side of `inspect ctl task log-flush` (lower "
        "it to write to S3 more often)."
    ),
)
@click.option(
    "--log-shared",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['log_shared']}] Shared-log event sync interval, in seconds.",
)
@click.option(
    "--timeout",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['timeout']}] Override the total retry budget per "
        "generate call, in seconds ('clear' restores launch config)."
    ),
)
@click.option(
    "--attempt-timeout",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['attempt_timeout']}] Override the per-attempt API "
        "timeout, in seconds ('clear' restores launch config)."
    ),
)
@click.option(
    "--max-retries",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_retries']}] Override the max retries per "
        "generate call (0 fails after the first attempt; 'clear' restores "
        "launch config)."
    ),
)
@click.option(
    "--reason",
    default=None,
    help=(
        "Why this change is being made (with a set option) — recorded with "
        "the change in each affected eval log."
    ),
)
@click.option(
    "--author",
    default=None,
    help=(
        "Author recorded with the change in each affected eval log (with a "
        "set option). Defaults to your git identity, then your OS username."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would change without applying it (with a set option).",
)
@_json_option("the config view, every knob labeled with its scope")
def config_command(
    task: str | None,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None,
    log_buffer: int | None,
    log_shared: int | None,
    timeout: int | Literal["clear"] | None,
    attempt_timeout: int | Literal["clear"] | None,
    max_retries: int | Literal["clear"] | None,
    reason: str | None,
    author: str | None,
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

    Beyond the named flags, any limit registered by name through the
    `concurrency()` API — by tools (e.g. web search providers) or task code —
    is settable with `--key NAME LIMIT`; the output lists the registered
    keys. Lowering a concurrency limit never interrupts running samples —
    new work waits until in-flight holders drain. `--log-buffer` /
    `--log-shared` are the retune side of `inspect ctl task log-flush`: they
    set the buffering policy for future writes, while log-flush writes
    what's already buffered now. `--timeout` / `--attempt-timeout` /
    `--max-retries` set live overrides read by the model retry loop, so a
    change reaches even generate calls already retrying (in-flight API
    requests still drain first); pass `clear` to remove an override. Applied
    changes are recorded in each affected eval log (who / when / old → new);
    `--reason` annotates the record with why. TASK
    is required only for setting a task-scoped knob when several tasks run.
    """
    _run_config(
        task,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        log_buffer=log_buffer,
        log_shared=log_shared,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        reason=reason,
        author=author,
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
@click.pass_context
def process_group(ctx: click.Context, /, **mirrored: Any) -> None:
    """Operate on running Inspect processes (bare `process` lists them).

    The selector is a positional PID, optional when a single process is
    running.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(process_list_command, **mirrored)
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
@_json_option("an `{as_of, processes}` envelope")
def process_list_command(as_json: bool) -> None:
    """List running Inspect processes (pids, keep-alive, hosted tasks).

    The PID shown is the selector `process keep` / `process release` take.
    """
    _run_process_list(as_json)


_mirror_list_options(process_group, process_list_command)


@process_group.command("keep")
@click.argument("pid", required=False, type=int)
@_json_option("the mutation result envelope")
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
@_json_option("the mutation result envelope")
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
        from_start=False,
        limit=None,
        types=types,
        full=full,
        since_time=since_time,
        until=until,
        as_json=as_json,
    )


# The aliases keep the old `--pid` option but also accept the positional PID
# the new spelling (and the shared ambiguity error) teaches.
@ctl_command.command("keep", hidden=True)
@click.argument("pid_arg", required=False, type=int, metavar="[PID]")
@click.option("--pid", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def keep_alias(pid_arg: int | None, pid: int | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl process keep`."""
    _deprecation_note("keep", "process keep")
    _run_keep_alive(pid_arg if pid_arg is not None else pid, keep=True, as_json=as_json)


@ctl_command.command("release", hidden=True)
@click.argument("pid_arg", required=False, type=int, metavar="[PID]")
@click.option("--pid", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def release_alias(pid_arg: int | None, pid: int | None, as_json: bool) -> None:
    """Deprecated alias for `inspect ctl process release`."""
    _deprecation_note("release", "process release")
    _run_keep_alive(
        pid_arg if pid_arg is not None else pid, keep=False, as_json=as_json
    )


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
        max_subprocesses=None,
        max_connections=None,
        model=None,
        key=None,
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
@click.option("--key", "key", type=(str, click.IntRange(min=1)), default=None)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--json", "as_json", is_flag=True, default=False)
def limits_alias(
    task: str | None,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Deprecated alias for `inspect ctl config`."""
    _deprecation_note("limits", "config")
    _run_config(
        task,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_subprocesses=None,
        max_connections=max_connections,
        model=model,
        key=key,
        log_buffer=None,
        log_shared=None,
        dry_run=dry_run,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# --json error envelope
# ---------------------------------------------------------------------------
#
# The error-path half of the agent output contract (see "Agent output
# contract" in design/control-channel.md): the success path is enveloped
# (`{as_of, ...}` reads, `{target, applied, ...}` mutations), so a failure
# surfacing stderr prose or a traceback on a --json invocation would send
# agents straight back to the string-scraping the JSON-first rule exists to
# prevent. On --json, every terminal failure emits
# `{"error": {kind, exception, message, status}}` on stdout, with the exit
# code still non-zero; human (non---json) output is unchanged.


# The envelope's closed `kind` vocabulary (the field agents branch on).
# Typed as a Literal so mypy rejects a typo'd kind at a raise site rather
# than shipping it as a new vocabulary entry.
_ErrorKind = Literal[
    "busy",
    "connect_timeout",
    "read_timeout",
    "connect_error",
    "not_found",
    "ambiguous",
    "http_error",
    "invalid_request",
    "invalid_response",
    "internal",
]


class _CtlFailure(click.exceptions.Exit):
    """A terminal ctl failure carrying the ``--json`` error envelope fields.

    Subclasses :class:`click.exceptions.Exit` (code 1) so a path that never
    passes through :func:`_structured_failures` still exits non-zero exactly
    as before. Raisers echo their human prose to stderr first (unchanged in
    both output modes — stderr stays narration); ``message`` must therefore
    be self-contained, since the envelope is all a ``--json`` consumer reads
    (e.g. the ambiguity error folds its candidate ids into it rather than
    pointing at the stderr table).
    """

    def __init__(
        self,
        kind: _ErrorKind,
        message: str,
        *,
        exception: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(1)
        self.kind = kind
        self.message = message
        self.exception = exception
        self.status = status
        self._emitted = False

    @classmethod
    def from_exception(cls, message: str, exc: BaseException) -> "_CtlFailure":
        """Build a failure whose kind/status derive from ``exc``."""
        kind, status = _classify(exc)
        return cls(kind, message, exception=_exception_name(exc), status=status)

    def emit(self) -> None:
        """Print the stdout envelope (idempotent — nested wrappers can't double-print)."""
        if self._emitted:
            return
        self._emitted = True
        envelope = {
            "error": {
                "kind": self.kind,
                "exception": self.exception,
                "message": self.message,
                "status": self.status,
            }
        }
        click.echo(json_lib.dumps(envelope, indent=2))


def _fail(
    kind: _ErrorKind,
    message: str,
    *,
    exception: str | None = None,
    status: int | None = None,
) -> NoReturn:
    """Echo ``message`` to stderr and raise the matching :class:`_CtlFailure`.

    The standard shape for a terminal error site: the same self-contained
    message serves as both the human stderr prose and the envelope
    ``message``. Sites that interleave extra stderr output between the echo
    and the raise (warnings, a candidates table) or derive the failure from
    an exception (``raise ... from exc``) construct :class:`_CtlFailure`
    directly instead.
    """
    click.echo(message, err=True)
    raise _CtlFailure(kind, message, exception=exception, status=status)


class _FailureKind(NamedTuple):
    """Result of :func:`_classify` (envelope ``kind`` + HTTP status when applicable)."""

    kind: _ErrorKind
    status: int | None


def _classify(exc: BaseException) -> _FailureKind:
    """Coarse machine-branchable envelope ``kind`` for a transport exception.

    The vocabulary is deliberately small — an agent branches on ``kind``
    rather than regexing ``exception``/``message``: ``connect_timeout`` /
    ``read_timeout`` (single-shot timeouts; retry-exhausted timeouts are
    ``busy`` — see :func:`_unreachable_failure`), ``connect_error``
    (refused/reset — the process is likely gone), ``not_found`` /
    ``http_error`` (non-2xx, ``status`` carries the code),
    ``invalid_response`` (undecodable body), ``internal`` (anything else).
    Timeouts test before :class:`httpx.TransportError`, which subsumes them.
    """
    if isinstance(exc, httpx.ConnectTimeout):
        return _FailureKind("connect_timeout", None)
    if isinstance(exc, httpx.TimeoutException):
        return _FailureKind("read_timeout", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return _FailureKind("not_found" if status == 404 else "http_error", status)
    if isinstance(exc, (httpx.TransportError, OSError)):
        return _FailureKind("connect_error", None)
    if isinstance(exc, ValueError):
        return _FailureKind("invalid_response", None)
    return _FailureKind("internal", None)


def _exception_name(exc: BaseException) -> str:
    """Exception class for the envelope, package-qualified (``httpx.ReadTimeout``).

    The top-level package (not the defining module) qualifies the name — a
    ``httpx._exceptions.ReadTimeout`` spelling would leak a private module
    path that agents would then match on.
    """
    cls = type(exc)
    package = cls.__module__.partition(".")[0]
    if package == "builtins":
        return cls.__qualname__
    return f"{package}.{cls.__qualname__}"


@contextmanager
def _structured_failures(as_json: bool) -> Iterator[None]:
    """Emit the ``--json`` error envelope for any terminal failure inside.

    Error sites raise :class:`_CtlFailure` (after echoing their stderr
    prose) to carry the structured fields here; an unexpected exception
    still gets an envelope (kind ``internal``), with its traceback preserved
    on stderr for debugging. Other click control-flow exceptions (a plain
    ``Exit``, usage errors, Ctrl+C) pass through untouched.
    """
    if not as_json:
        yield
        return
    try:
        yield
    except _CtlFailure as exc:
        exc.emit()
        raise
    except (click.exceptions.Exit, click.ClickException, click.exceptions.Abort):
        raise
    except Exception as exc:
        click.echo(traceback.format_exc(), err=True, nl=False)
        _CtlFailure(
            "internal",
            str(exc) or _exception_name(exc),
            exception=_exception_name(exc),
        ).emit()
        raise click.exceptions.Exit(code=1) from exc


_P = ParamSpec("_P")


def _envelope_failures(fn: Callable[_P, None]) -> Callable[_P, None]:
    """Wrap a command runner in :func:`_structured_failures`.

    Reads the runner's ``as_json`` argument off the bound call, so the
    wrapper needs no per-runner plumbing and the aliases are covered through
    their delegation. Every runner must take an ``as_json`` parameter —
    enforced at decoration time so a missing/renamed parameter fails at
    import rather than silently reverting that command to unstructured
    failures.
    """
    signature = inspect.signature(fn)
    if "as_json" not in signature.parameters:
        raise TypeError(
            f"{fn.__name__} must take an as_json parameter to use @_envelope_failures"
        )

    @functools.wraps(fn)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        as_json = bool(bound.arguments["as_json"])
        with _structured_failures(as_json):
            fn(*args, **kwargs)

    return wrapper


def _unreachable_failure(message: str, exc: "_ServerUnreachable") -> _CtlFailure:
    """The envelope failure for a terminal unreachable-server error.

    Busy (retry-exhausted timeouts) is its own kind — it means "alive but
    starved; retry shortly" where the transport kinds mean "gone" — carrying
    the last attempt's timeout class; other failures classify by their
    transport ``__cause__``.
    """
    if isinstance(exc, _ServerBusy):
        last = exc.last_timeout
        return _CtlFailure(
            "busy", message, exception=_exception_name(last) if last else None
        )
    cause = exc.__cause__
    return _CtlFailure.from_exception(
        message, cause if isinstance(cause, Exception) else exc
    )


# ---------------------------------------------------------------------------
# command runners (shared by the canonical commands and the aliases)
# ---------------------------------------------------------------------------


@_envelope_failures
def _run_task_list(as_json: bool) -> None:
    # Stamp as_of BEFORE the reads: anything that changes during them has a
    # timestamp >= as_of and is caught by the next poll rather than missed.
    as_of = time.time()
    summaries = _fetch_summaries(list_discovered_servers()).summaries

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
    ``counts`` is the status histogram summed over the evals actually read —
    complete over each eval's samples even when its rows were filtered or
    capped, except against an older (histogram-less) server on an
    ``active_since`` delta poll, where only the delta's rows exist to count;
    ``truncated`` whether any eval's rows hit the cap.
    """

    as_of: float
    targets: list[dict[str, Any]]
    read: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    counts: dict[str, int]
    truncated: bool


def _list_sample_rows(
    task: str | None,
    active_since: float | None,
    *,
    sample_filter: Literal["errors"] | None = None,
    statuses: frozenset[str] | None = None,
    limit: int | None = None,
    all_samples: bool = False,
) -> _SampleRows:
    """Fetch sample rows for one task (``task`` given) or all running tasks.

    ``statuses`` is the already-parsed ``--status`` member set (``None`` =
    no filter) — parsing lives with the caller so one parse serves the
    request, the fallback filter, and the truncation footer.
    """
    fallback_as_of = time.time()
    # Loop-invariant across targets: the filter's wire form and the
    # older-server fallback's row cap.
    status_param = ",".join(sorted(statuses)) if statuses is not None else None
    cap = effective_sample_limit(limit, all_samples)
    counts = dict.fromkeys(SAMPLE_STATUSES, 0)
    truncated = False
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        return _SampleRows(
            as_of=fallback_as_of,
            targets=[],
            read=[],
            rows=[],
            counts=counts,
            truncated=False,
        )

    if task is not None:
        targets = [_resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)]
    else:
        targets = summaries

    as_of_values: list[float] = []
    read: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for target in targets:
        # Query by the task's current eval id (resolved fresh each invocation,
        # so this still works after a retry minted a new one).
        try:
            page = _fetch_samples(
                target["socket_path"],
                target["eval_id"],
                active_since,
                sample_filter=sample_filter,
                status=status_param,
                limit=limit,
                all_samples=all_samples,
                # a scoped read fails the command on busy, so it keeps the
                # full budget; the unscoped fan-out skips on the default
                attempts=_REQUEST_ATTEMPTS if task is not None else None,
            )
        except _ServerUnreachable as exc:
            if task is not None:
                _exit_samples_unreachable(target["eval_id"], exc)
            # An unscoped read spans whatever evals happen to be running; one
            # process exiting — or staying busy through the retries — between
            # discovery and this read shouldn't fail the invocation (even if
            # it was the only eval).
            hint = (
                "try again shortly"
                if isinstance(exc, _ServerBusy)
                else "it may have just exited"
            )
            click.echo(
                f"Skipping eval {target['eval_id']}: its samples could not be "
                f"read ({_unreachable_detail(exc)}) — {hint}.",
                err=True,
            )
            continue
        as_of_values.append(page.as_of)
        read.append(target)
        truncated = truncated or page.truncated
        # An older server's envelope carries no histogram — and such a server
        # ignored the `status`/`limit` params (though it did honor
        # `active_since`): derive counts from its rows, then apply the filter
        # and cap client-side so the flags' contract holds across version
        # skew. On an `active_since` delta poll only the delta's rows exist
        # to count, so the derived counts cover the delta, not the whole
        # eval — a whole-eval histogram is unobtainable from an old server
        # in a single delta read.
        page_counts = page.counts
        samples = page.samples
        if page_counts is None:
            page_counts = {}
            for sample in samples:
                page_status = str(sample.get("status") or "")
                page_counts[page_status] = page_counts.get(page_status, 0) + 1
            if statuses is not None:
                samples = [s for s in samples if s.get("status") in statuses]
            if cap is not None and len(samples) > cap:
                samples = samples[:cap]
                truncated = True
        for key, value in page_counts.items():
            counts[key] = counts.get(key, 0) + int(value)
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
        counts=counts,
        truncated=truncated,
    )


class _RowsPrinter(Protocol):
    """Prints a sample-rows table (``show_task`` adds the task column)."""

    def __call__(
        self, samples: list[dict[str, Any]], show_task: bool = False
    ) -> None: ...


def _run_sample_list(
    task: str | None,
    active_since: float | None,
    as_json: bool,
    *,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
) -> None:
    if all_samples and limit is not None:
        raise click.UsageError("--all and --limit are mutually exclusive.")
    _run_sample_listing(
        task,
        active_since,
        as_json,
        empty_read="(no samples started yet)",
        printer=_print_samples_table,
        statuses=_parse_statuses(status),
        limit=limit,
        all_samples=all_samples,
    )


def _parse_statuses(status: str | None) -> frozenset[str] | None:
    """Parse ``--status``, rejecting an empty or unknown value up front.

    The server 400s on these too, but an unscoped listing fans out over
    several evals — failing fast keeps a typo from producing a per-eval
    warn-and-skip cascade instead of one clear usage error.
    """
    statuses, error = parse_status_filter(status, param="--status")
    if error is not None:
        raise click.UsageError(f"{error}.")
    return statuses


def _run_sample_errors(task: str | None, as_json: bool) -> None:
    _run_sample_listing(
        task,
        None,
        as_json,
        sample_filter="errors",
        empty_read="(no errors or retries)",
        printer=_print_errors_table,
        # The triage view must see every errored/retried row — the default
        # cap would silently hide errors beyond it (the server's errors
        # filter narrows the rows, but capped-filtered is still capped).
        all_samples=True,
    )


@_envelope_failures
def _run_sample_listing(
    task: str | None,
    active_since: float | None,
    as_json: bool,
    *,
    sample_filter: Literal["errors"] | None = None,
    empty_read: str,
    printer: "_RowsPrinter",
    statuses: frozenset[str] | None = None,
    limit: int | None = None,
    all_samples: bool = False,
) -> None:
    """The shared body of `sample list` / `sample errors`.

    One home for the listing contract: the ``{as_of, counts, samples,
    truncated}`` envelope, the no-targets message, the single-vs-multi-target
    header/table shape, the truncation footer (a capped listing must say so —
    no silent truncation), and the honesty rule that ``empty_read`` (a
    positive "(none)" claim) is made only for targets whose samples were
    actually read — a target warn-and-skipped as unreachable gets "(samples
    unavailable)" instead, and an empty ``--status``-filtered or
    ``--active-since`` delta listing gets a filter-scoped message (samples
    may exist that simply didn't match). ``statuses`` is the already-parsed
    ``--status`` member set (``None`` = no filter).
    """
    listing = _list_sample_rows(
        task,
        active_since,
        sample_filter=sample_filter,
        statuses=statuses,
        limit=limit,
        all_samples=all_samples,
    )
    rows = listing.rows

    if as_json:
        click.echo(
            json_lib.dumps(
                {
                    "as_of": listing.as_of,
                    "counts": listing.counts,
                    "samples": rows,
                    "truncated": listing.truncated,
                },
                indent=2,
            )
        )
        return

    if not listing.targets:
        _echo_no_running_evals()
        return

    if not listing.read:
        empty = "(samples unavailable)"
    elif statuses is not None:
        empty = f"(no matching samples: 0 of {sum(listing.counts.values())})"
    elif active_since is not None:
        empty = "(no samples active since the given timestamp)"
    else:
        empty = empty_read
    if len(listing.targets) == 1:
        click.echo(_task_header(listing.targets[0]))
        if not rows:
            click.echo(empty)
            return
        click.echo()
        printer(rows)
    else:
        if not rows:
            click.echo(empty)
            return
        printer(rows, show_task=True)
    if listing.truncated:
        _echo_truncation_footer(
            len(rows),
            listing.counts,
            statuses=statuses,
            delta=active_since is not None,
        )


def _echo_truncation_footer(
    shown: int,
    counts: dict[str, int],
    *,
    statuses: frozenset[str] | None = None,
    delta: bool = False,
) -> None:
    """Say a capped listing was capped (the no-silent-truncation rule).

    ``counts`` is the whole-task histogram, so when ``--status`` or an
    ``--active-since`` delta narrowed the listing, "of {sum(counts)}" would
    overstate how many rows ``--all`` returns. A status filter's matching
    total is recoverable from the histogram; a delta's is not knowable
    client-side, so the footer claims only the totals it has.
    """
    total = sum(counts.values())
    histogram = " · ".join(
        f"{counts[status]} {status}" for status in SAMPLE_STATUSES if counts[status]
    )
    if delta:
        showing = (
            f"showing first {shown} matching sample{'' if shown == 1 else 's'} "
            f"({total} total: {histogram})"
        )
    elif statuses is not None:
        matching = sum(counts.get(status, 0) for status in statuses)
        showing = (
            f"showing {shown} of {matching} matching samples "
            f"({total} total: {histogram})"
        )
    else:
        showing = f"showing {shown} of {total} samples ({histogram})"
    hint = "pass --all (or --limit N) for more"
    if statuses is None:
        hint += ", --status to filter"
    click.echo()
    click.echo(f"listing capped: {showing} — {hint}")


@_envelope_failures
def _run_sample_show(
    task: str, sample_id: str, epoch: int, show_traceback: bool, as_json: bool
) -> None:
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    # One atomic read: the detail carries the summary fields (timing / tokens
    # / messages) alongside the error history, so there is no supplemental
    # listing fetch (and no torn view if the sample retries between reads).
    detail = _fetch_sample_detail(
        target["socket_path"], target["eval_id"], sample_id, epoch
    )
    row = (
        _fetch_sample_row_from_listing(target, detail)
        if "message_count" not in detail
        else None
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


def _fetch_sample_row_from_listing(
    target: dict[str, Any], detail: dict[str, Any]
) -> dict[str, Any] | None:
    """The sample's listing row — `sample show`'s old-server fallback.

    A current control server's detail response carries the summary fields
    (timing / tokens / messages), so their *absence* — keyed on
    ``message_count``, present even when null — marks a server from before
    they were added (``ctl`` attaches to already-running processes, so the
    CLI can be newer than the server). Only then is the eval's listing
    fetched to fold in the sample's row, restoring the fields the old
    two-read flow reported; a failed fallback read degrades to the detail
    alone with a stderr caveat rather than discarding the answer in hand.
    Not a strict version test: a current server also omits the keys on its
    terminal path's degrade case (its own summary-row lookup missed), where
    this fallback fires harmlessly as a second chance at the row.
    """
    try:
        # all_samples: this lookup needs the target sample's row, which the
        # default cap could drop.
        samples = _fetch_samples(
            target["socket_path"],
            target["eval_id"],
            all_samples=True,
        ).samples
    except _ServerUnreachable as exc:
        hint = " — try again shortly" if isinstance(exc, _ServerBusy) else ""
        click.echo(
            f"Could not read the samples listing for eval {target['eval_id']} "
            f"({_unreachable_detail(exc)}); showing the sample without its "
            f"summary fields (timing / tokens / messages){hint}.",
            err=True,
        )
        return None
    return next(
        (
            s
            for s in samples
            if str(s.get("sample_id")) == str(detail.get("sample_id"))
            and s.get("epoch") == detail.get("epoch")
        ),
        None,
    )


@_envelope_failures
def _run_sample_events(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    cursor: str | None,
    tail: int | None,
    from_start: bool,
    limit: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    _validate_from_start(from_start, cursor=cursor, tail=tail, since_time=since_time)
    _validate_cursor(cursor)
    if limit is not None and limit < 1:
        _fail("invalid_request", "--limit must be at least 1.")
    types = _normalized_types(types)

    # The unseeded default is a recent tail — never an empty page, never the
    # full backlog. A cursor, an explicit window, or --from-start disables it
    # (an unseeded, tail-less read starts at event 0 — exactly "from start").
    if (
        not from_start
        and cursor is None
        and tail is None
        and since_time is None
        and until is None
    ):
        tail = _DEFAULT_EVENTS_TAIL

    # the all-busy exit inside the fetch matters doubly here: the done:true
    # empty page below would falsely end a polling loop for an eval whose
    # events may live on the busy pid
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
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

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    page = _fetch_sample_events(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        limit=limit,
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


def _looks_like_timestamp(value: str) -> bool:
    """Whether a would-be cursor value reads as a unix timestamp.

    Real cursors are opaque base64 tokens and never parse as a number, so a
    numeric value is almost certainly a timestamp meant for ``--since-time``.
    The one classification behind both cursor-mistake errors
    (:func:`_exit_removed_since`, :func:`_validate_cursor`).
    """
    try:
        float(value)
        return True
    except ValueError:
        return False


def _exit_removed_since(value: str) -> NoReturn:
    """Teach the `--since` split instead of click's stock no-such-option error.

    The old flag was the cursor; click's own suggestion ("did you mean
    --since-time?") points cursor-holders the wrong way, so the command keeps
    a hidden `--since` whose only job is this error — routed by the same
    timestamp heuristic `--cursor` validation uses.
    """
    hint = (
        "this value looks like a timestamp — use --since-time"
        if _looks_like_timestamp(value)
        else "pass it to --cursor (the `next` value from a prior page)"
    )
    _fail(
        "invalid_request",
        f"--since was split into --cursor (opaque resume cursor) and "
        f"--since-time (wall-clock window): {hint}.",
    )


def _validate_from_start(
    from_start: bool,
    *,
    cursor: str | None,
    tail: int | None,
    since_time: float | None,
) -> None:
    """Reject ``--from-start`` combined with another window seed.

    A resume cursor contradicts "from the beginning", and ``--tail`` /
    ``--since-time`` each seed a different window start. ``--until`` is
    deliberately allowed — bounding a from-the-start read by wall clock is
    coherent.
    """
    if not from_start:
        return
    conflicting = [
        flag
        for flag, value in (
            ("--cursor", cursor),
            ("--tail", tail),
            ("--since-time", since_time),
        )
        if value is not None
    ]
    if conflicting:
        _fail(
            "invalid_request",
            f"--from-start reads from the first event and cannot be combined "
            f"with {' / '.join(conflicting)}.",
        )


def _normalized_types(types: str | None) -> str | None:
    """Map the blessed ``all`` spelling onto the wire's ``*``.

    ``--type '*'`` must be quoted (bare ``*`` glob-expands in bash and errors
    in zsh), so ``all`` is the documented spelling — safe as a magic value
    since no event type is named ``all``. Translated client-side so it also
    works against a running server that predates the synonym.
    """
    if types is None:
        return None
    return ",".join(
        "*" if member == "all" else member
        for member in (part.strip() for part in types.split(","))
    )


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
    hint = (
        " — this looks like a timestamp; did you mean --since-time?"
        if _looks_like_timestamp(cursor)
        else " — pass the `next` value from a prior page."
    )
    _fail("invalid_request", f"Invalid --cursor value '{cursor}'{hint}")


@_envelope_failures
def _run_keep_alive(pid: int | None, *, keep: bool, as_json: bool) -> None:
    """Latch keep-alive on (``keep``) or off (``release``) for one process."""
    verb = "keep" if keep else "release"
    target = _resolve_target_server(pid)
    body = _request_json(
        str(target.socket_path),
        f"/{verb}",
        what=f"keep-alive for pid {target.pid}",
        not_found=(
            f"Pid {target.pid} does not support keep/release (older inspect version?)."
        ),
        mutate="post",
        retry_mutation=True,
    )

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


@_envelope_failures
def _run_log_flush(task: str | None, as_json: bool) -> None:
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries
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


def _mutation_envelope(
    target: dict[str, Any], result: dict[str, Any], *, dry_run: bool
) -> dict[str, Any]:
    """The uniform ``--json`` mutation result envelope for the cancel verbs.

    ``applied`` reports whether the mutation actually landed — false on a
    dry run and on the idempotent already-in-that-state no-op (the server's
    ``changed: false``) — so an agent branches on one field. The server's
    response rides along as ``detail`` (minus the transport-level ``ok``).
    """
    return {
        "target": target,
        "applied": bool(result.get("changed")) and not dry_run,
        "dry_run": dry_run,
        "detail": {k: v for k, v in result.items() if k != "ok"},
    }


_CANCEL_ROUTE_MISSING = (
    "This process is running an older inspect without the cancel "
    "endpoint; restart the eval to pick up the current version."
)


@_envelope_failures
def _run_task_cancel(
    task: str,
    *,
    action: TaskCancelAction = "cancel",
    dry_run: bool,
    as_json: bool,
) -> None:
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries
    scope = _resolve_scope(servers, summaries, task, per_task_option="task cancel")
    if scope is None:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return
    assert scope.task_id is not None

    params: dict[str, Any] = {}
    if action != "cancel":
        # omit the param when it's the default: a strict server that
        # predates `action` 400s on unknown mutation params, and a plain
        # cancel must keep working against any server with the route
        # (abort is what those servers do anyway). An explicit
        # score/error against such a server *should* fail loudly.
        params["action"] = action
    if dry_run:
        params["dry_run"] = True
    # idempotent (a repeat cancel is a clean no-op), so it may ride the
    # narrated busy-retry policy like keep/release
    result = _request_json(
        scope.socket_path,
        f"/tasks/{scope.task_id}/cancel",
        params=params,
        what=f"cancel of task {scope.task_id}",
        not_found=(
            f"Task '{scope.task_id}' not found in this process (it may have finished)."
        ),
        not_found_missing_route=_CANCEL_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
    )

    if as_json:
        target = {"task_id": scope.task_id, "task": scope.task}
        click.echo(
            json_lib.dumps(
                _mutation_envelope(target, result, dry_run=dry_run), indent=2
            )
        )
        return

    click.echo(scope.header)
    click.echo()
    if result.get("changed"):
        in_flight = int(result.get("in_flight", 0) or 0)
        outcome = {
            "cancel": "interrupted",
            "score": "scored on the work done so far",
            "error": "marked as errored",
        }[action]
        interrupted = (
            f"{in_flight} in-flight sample{'' if in_flight == 1 else 's'} "
            f"{'would be' if dry_run else 'will be'} {outcome}"
        )
        suffix = (
            "completed samples are kept"
            if action == "cancel"
            else (
                "queued samples would be abandoned and the task would complete"
                if dry_run
                else "queued samples are abandoned and the task will complete"
            )
        )
        if dry_run:
            click.echo(f"Would cancel — {interrupted}; {suffix}.")
        else:
            click.echo(f"Cancel requested — {interrupted}; {suffix}.")
    else:
        reason = str(result.get("reason") or "already in that state")
        click.echo(f"Nothing to do: {reason}.")


@_envelope_failures
def _run_sample_cancel(
    task: str,
    sample_id: str,
    epoch: int | None,
    *,
    action: SampleCancelAction,
    dry_run: bool,
    as_json: bool,
) -> None:
    fetched = _fetch_sample_summaries()
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            click.echo("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)

    # Mutation selector rule: a defaulted epoch doesn't error — it resolves
    # to a *different sample* — so EPOCH is required whenever the task runs
    # more than one epoch. (An older server doesn't report `epochs`; the
    # epoch-1 default then stands, as it did before the field existed.)
    if epoch is None:
        epochs = int(target.get("epochs") or 1)
        if epochs > 1:
            _fail(
                "ambiguous",
                f"Task '{target.get('task') or '?'}' runs {epochs} epochs — "
                "pass EPOCH explicitly (a defaulted epoch would cancel the "
                "epoch-1 attempt).",
            )
        epoch = 1

    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "action": action,
    }
    if dry_run:
        params["dry_run"] = True
    result = _request_json(
        str(target["socket_path"]),
        f"/evals/{target['eval_id']}/sample/cancel",
        params=params,
        what=f"cancel of sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found in task "
            f"'{target.get('task') or '?'}'."
        ),
        not_found_missing_route=_CANCEL_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
    )

    if as_json:
        # echo the resolved identifiers so a defaulted epoch is visible and
        # the target round-trips into other commands' selectors
        envelope_target = {
            "task_id": target.get("task_id"),
            "task": target.get("task"),
            "sample_id": result.get("sample_id", sample_id),
            "epoch": result.get("epoch", epoch),
        }
        click.echo(
            json_lib.dumps(
                _mutation_envelope(envelope_target, result, dry_run=dry_run), indent=2
            )
        )
        return

    click.echo(_task_header(target))
    click.echo()
    label = f"sample {result.get('sample_id', sample_id)} (epoch {result.get('epoch', epoch)})"
    if result.get("changed"):
        outcome = {
            "score": "scored on the work done so far",
            "error": "marked as errored",
            "cancel": "recorded as cancelled",
        }[action]
        if dry_run:
            click.echo(f"Would cancel {label} — it would be {outcome}.")
        else:
            click.echo(f"Cancel requested for {label} — it will be {outcome}.")
    else:
        status = result.get("status")
        suffix = f" (status: {status})" if status else ""
        click.echo(f"Nothing to do — {label} has already finished{suffix}.")


@_envelope_failures
def _run_process_list(as_json: bool) -> None:
    as_of = time.time()
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries if servers else []

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


def _applied_knob_names(
    limits_view: dict[str, Any],
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    key: tuple[str, int] | None,
    timeout: int | Literal["clear"] | None,
    attempt_timeout: int | Literal["clear"] | None,
    max_retries: int | Literal["clear"] | None,
) -> list[str]:
    """Names of the requested knobs the server reported as adjustable.

    Serves the no-live-buffer hard-error path so its "other knobs were still
    applied" tail names only knobs that actually landed — a requested knob
    the server reported as not adjustable did NOT apply. The buffer knobs
    self-exclude: their adjustability check (no ``buffer`` view) is exactly
    the condition that put the caller on the error path. The retry overrides
    are always adjustable: the override layer exists regardless of any
    task's launch config, and `_gate_knob_support` has already excluded
    older servers.
    """
    return [
        name
        for name, value, adjustable in (
            (
                "--max-samples",
                max_samples,
                bool((limits_view.get("max_samples") or {}).get("adjustable")),
            ),
            (
                "--max-sandboxes",
                max_sandboxes,
                bool(limits_view.get("max_sandboxes")),
            ),
            (
                "--max-subprocesses",
                max_subprocesses,
                bool(limits_view.get("max_subprocesses")),
            ),
            (
                "--max-connections",
                max_connections,
                bool(limits_view.get("adaptive")),
            ),
            (
                "--key",
                key,
                key is not None
                and any(
                    row.get("name") == key[0] and row.get("adjustable")
                    for row in limits_view.get("concurrency") or []
                ),
            ),
            ("--timeout", timeout, True),
            ("--attempt-timeout", attempt_timeout, True),
            ("--max-retries", max_retries, True),
        )
        if value is not None and adjustable
    ]


@_envelope_failures
def _run_config(
    task: str | None,
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None,
    log_buffer: int | None,
    log_shared: int | None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    reason: str | None = None,
    author: str | None = None,
    dry_run: bool,
    as_json: bool,
) -> None:
    # `set_buffer` gates the no-live-buffer hard error below; whether the
    # request as a whole is a mutation is derived once, in _exec_limits
    # (returned as `mutated`), so the two can't skew for a future knob.
    set_buffer = log_buffer is not None or log_shared is not None

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
    summaries = _fetch_summaries(servers).summaries

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

    knob_values: dict[str, int | Literal["clear"] | None] = {
        "max_samples": max_samples,
        "max_sandboxes": max_sandboxes,
        "max_subprocesses": max_subprocesses,
        "max_connections": max_connections,
        "key": key[1] if key is not None else None,
        "log_buffer": log_buffer,
        "log_shared": log_shared,
        "timeout": timeout,
        "attempt_timeout": attempt_timeout,
        "max_retries": max_retries,
    }
    # a knob missing here would be silently exempt from the version gate —
    # the exact silent-skew failure `_gate_knob_support` exists to close
    assert knob_values.keys() == _KNOB_SCOPE.keys()
    requested_knobs = [knob for knob, value in knob_values.items() if value is not None]
    _gate_knob_support(servers, scope.socket_path, requested_knobs)

    # provenance rides mutations only (a read records nothing); the author
    # default is resolved client-side — the server has no view of who invoked
    # the CLI — and gated on the server supporting the params
    if requested_knobs:
        author, reason = _gate_provenance_support(
            servers, scope.socket_path, author=author, reason=reason
        )

    limits_view, mutated = _exec_limits(
        scope.socket_path,
        scope.task_id,
        max_samples=max_samples,
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        log_buffer=log_buffer,
        log_shared=log_shared,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        author=author,
        reason=reason,
        dry_run=dry_run,
    )

    # The buffer knobs ride the task config view (`buffer` key); a task with
    # no live sample buffer (e.g. a reused log, or a superseded retry attempt)
    # reports it as None. On a view that's just a knob with nothing to adjust,
    # reported as a warning like the limits knobs. Only an explicit
    # --log-buffer/--log-shared is an error (there's nothing to apply it to) —
    # and since any limits set has already landed in the same PATCH, the
    # error must say which of those knobs actually applied (a requested knob
    # the server reported as not adjustable did NOT), and surface the
    # server's warnings that this exit would otherwise swallow.
    buffer_warnings: list[str] = []
    if scope.task_id is not None and limits_view.get("buffer") is None:
        if set_buffer:
            applied_names = _applied_knob_names(
                limits_view,
                max_samples=max_samples,
                max_sandboxes=max_sandboxes,
                max_subprocesses=max_subprocesses,
                max_connections=max_connections,
                key=key,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                max_retries=max_retries,
            )
            message = (
                f"Task '{scope.task_id}' has no sample buffer in this "
                "process (e.g. a reused log, or a retry attempt that's "
                "been superseded) — --log-buffer/--log-shared cannot be "
                "set for this task."
                + (
                    f" The other requested knobs ({', '.join(applied_names)}) "
                    "were still applied."
                    if applied_names and not dry_run
                    else ""
                )
            )
            click.echo(message, err=True)
            for warning in limits_view.get("warnings") or []:
                # the buffer warning restates the headline error; skip it
                if not warning.startswith("log_buffer"):
                    click.echo(f"! {warning}", err=True)
            raise _CtlFailure("invalid_request", message)
        buffer_warnings.append(
            "log_buffer/log_shared are not adjustable for this task "
            "(no live sample buffer — e.g. a reused log)"
        )

    # The process-scoped knobs reach every task in the process — surface that
    # blast radius structurally when a set (or dry-run) used one. Derived from
    # `_KNOB_SCOPE` (via the assert-tied `knob_values`) so a future
    # process-scoped knob can't silently miss the note.
    global_knobs = [
        f"--{knob.replace('_', '-')}"
        for knob, value in knob_values.items()
        if value is not None and _KNOB_SCOPE[knob] == "process"
    ]
    notes = []
    note = _process_scope_note(global_knobs, scope.siblings)
    if note:
        notes.append(note)

    config = _compose_config(
        scope,
        limits_view,
        dry_run=dry_run,
        set_values=mutated,
        notes=notes,
        extra_warnings=buffer_warnings,
    )

    if as_json:
        click.echo(json_lib.dumps(config, indent=2))
        return

    click.echo(scope.header)
    click.echo()
    _print_config(config, changed=mutated)


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
        knobs["max_samples"] = {
            "scope": _KNOB_SCOPE["max_samples"],
            **limits_view["max_samples"],
        }
    knobs["max_sandboxes"] = {
        "scope": _KNOB_SCOPE["max_sandboxes"],
        "providers": limits_view.get("max_sandboxes") or [],
    }
    # `limit` absent means the limiter doesn't exist yet (no subprocess has
    # run in the process) — rendered as inactive rather than claiming a value
    knobs["max_subprocesses"] = {
        "scope": _KNOB_SCOPE["max_subprocesses"],
        **(limits_view.get("max_subprocesses") or {}),
    }
    knobs["max_connections"] = {
        "scope": _KNOB_SCOPE["max_connections"],
        "adaptive": limits_view.get("adaptive") or [],
    }
    # The retry-override knobs (absent from an older server's view). `override`
    # is the live process-wide override, None = launch config applies per call.
    retry_view = limits_view.get("retry")
    if retry_view is not None:
        from inspect_ai.model._generate_overrides import (
            GENERATE_CONFIG_OVERRIDE_FIELDS,
        )

        for knob in GENERATE_CONFIG_OVERRIDE_FIELDS:
            knobs[knob] = {
                "scope": _KNOB_SCOPE[knob],
                "override": retry_view.get(knob),
            }
    # `keys: None` (vs an empty list) means the server predates the
    # concurrency view — rendered as unreported rather than empty
    knobs["concurrency"] = {
        "scope": _KNOB_SCOPE["key"],
        "keys": limits_view.get("concurrency"),
    }
    buffer_view = limits_view.get("buffer")
    if buffer_view is not None:
        knobs["log_buffer"] = {
            "scope": _KNOB_SCOPE["log_buffer"],
            "value": buffer_view.get("log_buffer"),
            "pending": buffer_view.get("pending"),
        }
        knobs["log_shared"] = {
            "scope": _KNOB_SCOPE["log_shared"],
            "value": buffer_view.get("log_shared"),
        }

    # applied but unrecorded knobs surface as a warning (the change itself
    # landed; only its eval-log record didn't — e.g. no live log to record
    # in, or a fan-out that failed for some of the affected logs)
    persisted = limits_view.get("persisted")
    unrecorded_warnings = (
        [
            f"{', '.join(knob for knob, ok in persisted.items() if not ok)} "
            "applied but not recorded in one or more affected eval logs "
            "(a log without the record will not reflect this change)."
        ]
        if isinstance(persisted, dict) and not all(persisted.values())
        else []
    )

    return {
        "target": {
            "scope": "task" if scope.task_id else "process",
            "task_id": scope.task_id,
            "task": scope.task,
        },
        "knobs": knobs,
        "warnings": [
            *(limits_view.get("warnings") or []),
            *(extra_warnings or []),
            *unrecorded_warnings,
        ],
        "notes": notes,
        "applied": bool(set_values and not dry_run),
        "dry_run": dry_run,
        # per applied knob, whether the change was recorded in the affected
        # eval log(s); None when nothing was applied (or the server predates
        # config-change persistence)
        "persisted": persisted,
        "requested": limits_view.get("requested") or None,
    }


class _DirectiveScope(NamedTuple):
    """A directive command's resolved target (see :func:`_resolve_scope`)."""

    socket_path: str
    task_id: str | None
    """``None`` targets the process-level scope."""
    task: str | None
    """The task's name (``None`` for the process-level scope)."""
    header: str
    siblings: int
    """Blast-radius count for :func:`_process_scope_note`.

    The target process's active (running/pending) tasks, plus the explicitly
    named target when it is completed — a finished task can't absorb a
    retune, but counting it keeps the note from being suppressed while a
    *different* active task would. 0 when resolved before registration.
    """


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
            _fail(
                "invalid_request",
                f"Task '{target.get('task') or '?'}' predates task ids (an "
                "older reused log) — it can't be targeted by task-keyed "
                "directives." + (f" {no_task_id_advice}" if no_task_id_advice else ""),
            )
        # the named target counts toward the blast radius even when it is
        # completed — the process-scope note must not be suppressed as
        # "process-wide is exactly the named task" while a *different*
        # (active) task would absorb the retune
        siblings = _active_siblings(summaries, socket_path)
        if not _is_active(target):
            siblings += 1
        return _DirectiveScope(
            socket_path=socket_path,
            task_id=task_id,
            task=str(target.get("task") or "") or None,
            header=_task_header(target),
            siblings=siblings,
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
    active = [s for s in tasks_in_proc if _is_active(s)]
    candidates = active or tasks_in_proc
    if len(candidates) == 1 and str(candidates[0].get("task_id") or ""):
        target = candidates[0]
        return _DirectiveScope(
            socket_path=socket_path,
            task_id=str(target["task_id"]),
            task=str(target.get("task") or "") or None,
            header=_task_header(target),
            siblings=_active_siblings(summaries, socket_path),
        )
    if per_task_option is not None:
        addressable = [c for c in candidates if str(c.get("task_id") or "")]
        if not addressable:
            # no candidate carries a task id, so "pass a task id" would be
            # impossible advice — either a just-starting attempt whose
            # registration hasn't landed yet (status running/pending), or
            # pre-task-id reused logs (completed)
            starting = any(_is_active(c) for c in candidates)
            reason = (
                "the running task hasn't finished registering yet — retry in a moment"
                if starting
                else "this process's tasks predate task ids (older reused "
                "logs) and can't be targeted by task-keyed directives"
            )
            _fail(
                "invalid_request", f"{per_task_option} needs a task id, but {reason}."
            )
        count = len(candidates)
        _exit_ambiguous(
            candidates,
            f"{per_task_option} targets a single task, but this process is "
            f"running {count} task{'s' if count != 1 else ''}",
        )
    total = len(tasks_in_proc)
    header = f"process · {total} task{'s' if total != 1 else ''}" + (
        f" ({len(active)} active)" if len(active) != total else ""
    )
    return _DirectiveScope(
        socket_path=socket_path,
        task_id=None,  # process-global scope
        task=None,
        header=header,
        siblings=_active_siblings(summaries, socket_path),
    )


def _is_active(summary: dict[str, Any]) -> bool:
    """Whether a task summary is still running or pending.

    The one predicate behind scope resolution's sole-task default, the
    orphan-vs-reused-log routing, and the blast-radius sibling count — kept
    single so a new active-like status can't desynchronize them.
    """
    return summary.get("status") in ("running", "pending")


def _active_siblings(summaries: list[dict[str, Any]], socket_path: str) -> int:
    """Count the running/pending tasks sharing a process.

    The blast-radius denominator for process-scoped knobs: completed eval-set
    siblings share the socket but can't be affected by a retune, so counting
    them would overstate the note (and defeat its single-task suppression).
    """
    return sum(
        1
        for s in summaries
        if str(s.get("socket_path")) == socket_path and _is_active(s)
    )


def _process_scope_note(global_knobs: list[str], siblings: int) -> str | None:
    """Note that process-scoped config knobs reach every task in the process.

    ``global_knobs`` is the set (``--max-connections`` / ``--max-sandboxes``
    / ``--max-subprocesses`` / the retry overrides) supplied on this
    invocation; ``siblings`` counts the tasks the retune can
    reach (the process's active tasks, plus the named target when it is
    completed). Returns ``None`` when there's nothing to flag — no such knob
    was set, or the target task is the only one the change can reach, so
    "process-wide" is invisible.
    """
    if not global_knobs or siblings <= 1:
        return None
    verb = "applies" if len(global_knobs) == 1 else "apply"
    if len(global_knobs) == 1:
        names = global_knobs[0]
    else:
        names = f"{', '.join(global_knobs[:-1])} and {global_knobs[-1]}"
    return (
        f"{names} {verb} process-wide — every active task in this process is affected."
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
        _fail("not_found", "No running inspect processes found.")

    if pid is not None:
        matching = [s for s in servers if s.pid == pid]
        if not matching:
            _fail("not_found", f"No running inspect process with pid {pid}.")
        return matching[0]
    if len(servers) == 1:
        return servers[0]

    pids = ", ".join(str(s.pid) for s in servers)
    _fail(
        "ambiguous",
        f"Multiple inspect processes are running (pids: {pids}). "
        "Pass a PID to disambiguate (see `inspect ctl process`).",
    )


# The control server is embedded in the eval process and shares its event
# loop, which a busy eval can monopolize for several seconds at a time
# (large-transcript serialization, log flushes — see
# https://github.com/meridianlabs-ai/inspect_ai/issues/14). A perfectly
# healthy server can therefore miss a short read window, so reads use a
# generous timeout and retry a timeout several times before giving up, rather
# than silently reporting the eval as gone.
_REQUEST_TIMEOUT = 15.0
_REQUEST_ATTEMPTS = 8

# Default attempt budget for ``raise_on_busy`` reads (the pairing is resolved
# in `_get_response_with_retry`): enough to ride out a momentary stall without
# a fan-out spending the full `_REQUEST_ATTEMPTS * _REQUEST_TIMEOUT` (2 min)
# per eval hosted by one wedged process. A raise_on_busy caller that fails
# rather than degrades (the scoped samples read) overrides ``attempts``, as
# does the sole-server summaries fetch (one server is no fan-out).
_DEGRADED_READ_ATTEMPTS = 2

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


class _ServerBusy(_ServerUnreachable):
    """A read exhausted its busy retries (opt-in — see ``raise_on_busy``).

    A subclass, so a caller's existing ``except _ServerUnreachable``
    warn-and-skip covers it; carries its message as the detail (there is no
    transport ``__cause__`` — every attempt timed out). ``last_timeout``
    records the final attempt's timeout for the ``--json`` error envelope's
    ``exception`` field (an attribute rather than ``__cause__``, whose
    presence would swap the human detail from the busy narration to the
    bare timeout string).
    """

    def __init__(
        self, message: str, last_timeout: httpx.TimeoutException | None = None
    ) -> None:
        super().__init__(message)
        self.last_timeout = last_timeout


def _get_response_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    method: Literal["get", "post", "patch"] = "get",
    raise_on_busy: bool = False,
    attempts: int | None = None,
) -> httpx.Response:
    """Request ``path`` over the UDS, retrying a read timeout.

    Retries a read timeout up to ``attempts`` times, printing a status to the
    console (stderr, so ``--json`` stdout stays clean) on each — the eval is
    most likely just busy. On exhaustion, raises :class:`_ServerBusy` when
    ``raise_on_busy`` is set — handing the caller the terminal outcome (a
    fan-out warns and skips the busy eval, a supplemental read degrades in
    place, a scoped read exits with a targeted error), along with its
    narration — otherwise prints an error and exits non-zero.
    Raises :class:`_ServerUnreachable` for a non-timeout transport error
    (eg. a refused/reset connection) so the caller can skip or fail as
    appropriate.

    ``attempts`` defaults from ``raise_on_busy``: degradable reads get the
    smaller :data:`_DEGRADED_READ_ATTEMPTS` budget, exit-on-busy reads the
    full :data:`_REQUEST_ATTEMPTS`. Pass it explicitly to override — the
    scoped samples read raises on busy but keeps the full budget.

    ``method`` extends the retry policy to **idempotent** mutations only
    (keep/release's last-write-wins latches); a non-idempotent mutation must
    not be retried and takes the single-shot path in :func:`_request_json`.

    Returns the raw response without inspecting its status, so callers that need
    to handle a meaningful status (eg. a 404) can; :func:`_get_with_retry` is the
    JSON-decoding wrapper for the common case.
    """
    if attempts is None:
        attempts = _DEGRADED_READ_ATTEMPTS if raise_on_busy else _REQUEST_ATTEMPTS
    transport = httpx.HTTPTransport(uds=str(socket_path))
    last_timeout: httpx.TimeoutException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=_REQUEST_TIMEOUT,
            ) as client:
                return client.request(method, path, params=params or {})
        except httpx.TimeoutException as exc:
            last_timeout = exc
            retrying = "; retrying…" if attempt < attempts else "."
            click.echo(
                f"{what}: no response after {_REQUEST_TIMEOUT:.0f}s "
                f"(attempt {attempt}/{attempts}) — the eval may be busy"
                f"{retrying}",
                err=True,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise _ServerUnreachable() from exc
    if raise_on_busy:
        raise _ServerBusy(
            f"no response after {attempts} attempts — the eval's event loop is busy",
            last_timeout=last_timeout,
        )
    _fail(
        "busy",
        f"{what}: gave up after {attempts} attempts of "
        f"{_REQUEST_TIMEOUT:.0f}s each — the eval's event loop is busy; "
        "try again shortly.",
        exception=_exception_name(last_timeout) if last_timeout else None,
    )


def _get_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    raise_on_busy: bool = False,
    attempts: int | None = None,
) -> Any:
    """GET ``path`` and return its decoded JSON, retrying a busy eval on timeout.

    Wraps :func:`_get_response_with_retry` (``raise_on_busy`` and ``attempts``
    ride through, including the attempts-from-raise_on_busy default); a
    non-2xx status or undecodable body raises :class:`_ServerUnreachable`
    (a server-side ``500`` or malformed response is not retryable). For
    endpoints with a meaningful 4xx, call :func:`_get_response_with_retry`
    directly and inspect the status.
    """
    response = _get_response_with_retry(
        socket_path,
        path,
        params=params,
        what=what,
        raise_on_busy=raise_on_busy,
        attempts=attempts,
    )
    try:
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _ServerUnreachable() from exc


class _FetchedSummaries(NamedTuple):
    """Result of :func:`_fetch_summaries`.

    ``busy_pids`` names the processes warned-and-skipped as busy (only
    populated under ``raise_on_busy``) so callers can report them instead of
    claiming nothing is running — an alive-but-busy eval must never be
    indistinguishable from no eval at all.
    """

    summaries: list[dict[str, Any]]
    busy_pids: list[int]


def _fetch_summaries(
    servers: list[DiscoveredControlServer],
    *,
    raise_on_busy: bool = False,
    stop_on_task_id: str | None = None,
) -> _FetchedSummaries:
    """Query each discovered control server for its eval summary.

    Each read retries on timeout; a server that stays busy through the retries
    fails the command by default (``task list`` is the discovery surface — an
    alive eval silently absent from its ``--json`` output has no in-band
    caveat channel), but with ``raise_on_busy`` it is warned-and-skipped like
    an unreachable one, on the smaller degraded budget, and recorded in
    ``busy_pids`` — for the sample commands, where the other processes' rows
    are still worth showing and the skip must surface in any terminal error.
    A sole discovered server rides the full budget even then: the degraded
    budget protects a fan-out from an unrelated wedged process, and a single
    server is no fan-out.
    A server that can't be reached for a non-timeout reason raises
    :class:`_ServerUnreachable`; we warn and skip it (rather than fail the
    whole listing) but the warning is surfaced rather than swallowed: the most
    common cause is a process that just exited between discovery and connect,
    but the same path also catches a server-side ``500`` or a malformed
    response, which the user should see.

    ``stop_on_task_id`` short-circuits the fan-out: once a server's rows
    contain that exact task id, the remaining servers are not contacted.
    Safe only for an exact *full* id — it wins resolution outright (see
    :func:`_resolve_target_eval`), so the skipped servers could neither add
    candidates nor create ambiguity; a prefix or name query never equals a
    full id, so it still sees every server. Discovery is newest-first, so
    only siblings started before the target are skipped, and the
    duplicate-id corner (an old kept-alive attempt a newer process is
    retrying) resolves to the newest attempt.
    """
    summaries: list[dict[str, Any]] = []
    busy_pids: list[int] = []
    for server in servers:
        try:
            rows = _get_with_retry(
                server.socket_path,
                "/tasks",
                what=f"Reading tasks from pid {server.pid}",
                raise_on_busy=raise_on_busy,
                # a sole server is no fan-out — there's no wedged sibling to
                # protect against, so ride out a stall on the full budget
                attempts=_REQUEST_ATTEMPTS if len(servers) == 1 else None,
            )
        except _ServerUnreachable as exc:
            # a 404 means the process is serving a control API without this
            # route — version skew between the CLI and the eval process —
            # where transport errors mean the process is gone
            cause = exc.__cause__
            if isinstance(exc, _ServerBusy):
                busy_pids.append(server.pid)
                hint = "try again shortly"
            elif (
                isinstance(cause, httpx.HTTPStatusError)
                and cause.response.status_code == 404
            ):
                hint = "it may be running a different inspect version than this CLI"
            else:
                hint = "it may have just exited"
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
            if stop_on_task_id is not None and any(
                row.get("task_id") == stop_on_task_id for row in rows
            ):
                break
    return _FetchedSummaries(summaries=summaries, busy_pids=busy_pids)


def _fetch_sample_summaries(task_query: str | None = None) -> _FetchedSummaries:
    """Fetch the discovered summaries for a sample command.

    Busy processes are warned-and-skipped (``raise_on_busy``) so one wedged
    sibling can't kill the read — but if that leaves *nothing* (every
    process alive yet busy), exit non-zero via :func:`_exit_all_busy`: an
    alive-but-busy eval must never be indistinguishable from no eval at all.
    ``busy_pids`` rides the return for scoped resolution's caveats.

    ``task_query`` is the command's TASK selector; an exact full task id
    stops the fan-out at the server holding it (see ``stop_on_task_id`` on
    :func:`_fetch_summaries`).
    """
    fetched = _fetch_summaries(
        list_discovered_servers(),
        raise_on_busy=True,
        stop_on_task_id=task_query,
    )
    if not fetched.summaries and fetched.busy_pids:
        _exit_all_busy(fetched.busy_pids)
    return fetched


def _resolve_target_eval(
    summaries: list[dict[str, Any]],
    query: str,
    *,
    busy_pids: list[int] | None = None,
) -> dict[str, Any]:
    """Pick the task a per-eval command targets, or exit with an error.

    ``query`` matches a task id first (full, then unique prefix — ``task
    list`` shows truncated ids; ids are stable across retries), then falls
    back to the task name (see :func:`_match_by_task_name`). ``busy_pids``
    (from the summaries fetch) qualifies the resolution against partial
    discovery: a not-found error and the ambiguity table note that the busy
    process may hold further candidates, and a successful match carries a
    stderr caveat that it was matched among responsive processes only —
    unless it is an exact id or a prefix of at least the truncated display
    length (:data:`_SHORT_ID_LEN`), which cannot name a different task.
    Name matches always caveat: same-named tasks across processes are the
    norm (one task, several models), and a shorter hand-typed id prefix
    could collide with a task on the busy process.
    """
    exact = [s for s in summaries if s.get("task_id") == query]
    id_matches = exact or [
        s for s in summaries if str(s.get("task_id", "")).startswith(query)
    ]
    matches = id_matches or _match_by_task_name(summaries, query)
    if not matches:
        busy = (
            f" among responsive processes; {_busy_note(busy_pids)}" if busy_pids else ""
        )
        _fail("not_found", f"No running task matching '{query}'{busy}.")
    if len(matches) > 1:
        if busy_pids:
            click.echo(
                f"note: {_busy_pids_label(busy_pids)} busy-skipped — candidates "
                "drawn from responsive processes only.",
                err=True,
            )
        _exit_ambiguous(matches, f"'{query}' matches multiple tasks")
    match = matches[0]
    # exact ids are unique; a >= _SHORT_ID_LEN prefix is the truncated
    # task-list paste (see the docstring for the caveat rationale)
    provably_unique = bool(exact) or (bool(id_matches) and len(query) >= _SHORT_ID_LEN)
    if busy_pids and not provably_unique:
        click.echo(
            f"note: {_busy_pids_label(busy_pids)} busy-skipped — matched "
            f"'{query}' among responsive processes only.",
            err=True,
        )
    return match


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
    task against several models, or one model across solvers) are still
    tellable apart — an inline `id (name)` listing can't disambiguate those.
    The solver column appears only when a candidate carries one (mirroring
    the task list), and a pid column only when the candidates span more than
    one process (the common case is one). The envelope failure folds the
    candidate ids into its message instead — the table is stderr-only.
    """
    click.echo(f"{prefix} — pass a task id to choose one:\n", err=True)
    multi_process = len({s.get("pid") for s in matches}) > 1
    any_solver = any(s.get("solver") for s in matches)
    headers = (
        ("task id", "task", "model")
        + (("solver",) if any_solver else ())
        + ("status",)
        + (("pid",) if multi_process else ())
    )
    rows = [
        (
            _short_id(str(s.get("task_id") or "")),
            str(s.get("task") or "?"),
            str(s.get("model") or ""),
        )
        + ((str(s.get("solver") or ""),) if any_solver else ())
        + (str(s.get("status") or ""),)
        + ((str(s.get("pid") or ""),) if multi_process else ())
        for s in matches
    ]
    _render_table(headers, rows, err=True)
    ids = ", ".join(_short_id(str(s.get("task_id") or "")) for s in matches)
    raise _CtlFailure(
        "ambiguous",
        f"{prefix} — pass a task id to choose one (candidates: {ids}).",
    )


def _unreachable_detail(exc: _ServerUnreachable) -> str:
    """Human-readable cause of an unreachable-server error."""
    cause = exc.__cause__
    return _error_detail(cause) if isinstance(cause, Exception) else str(exc)


def _exit_samples_unreachable(eval_id: str, exc: _ServerUnreachable) -> NoReturn:
    """Echo a samples-read failure for ``eval_id`` and exit non-zero."""
    # the period rides the hint: a non-busy detail is a raw transport error
    # string (multi-line, may end in a URL) that punctuation would corrupt
    hint = "; try again shortly." if isinstance(exc, _ServerBusy) else ""
    message = (
        f"Failed to read samples for eval {eval_id}: {_unreachable_detail(exc)}{hint}"
    )
    click.echo(message, err=True)
    raise _unreachable_failure(message, exc) from exc


class _SamplesPage(NamedTuple):
    """One eval's samples read (see :func:`_fetch_samples`).

    ``counts`` is the eval's status histogram (complete even when the rows
    are filtered or capped); ``None`` from an older server whose envelope
    doesn't carry it. ``truncated`` reports whether the server's row cap
    dropped rows.
    """

    as_of: float
    samples: list[dict[str, Any]]
    counts: dict[str, int] | None = None
    truncated: bool = False


def _fetch_samples(
    socket_path: str,
    eval_id: str,
    active_since: float | None = None,
    *,
    sample_filter: Literal["errors"] | None = None,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    attempts: int | None = None,
) -> _SamplesPage:
    """Query one control server for an eval's samples.

    Returns the server's ``{as_of, counts, samples, truncated}`` envelope —
    ``as_of`` is stamped server-side before the listing is built, so feeding
    it back as the next ``active_since`` can't miss changes that landed
    during the read; ``counts`` is the whole eval's status histogram and
    ``truncated`` reports a hit row cap. With ``active_since`` (unix ts),
    restricts to samples started or updated since then — the recency delta.
    ``status`` (comma-separated) filters by status; the rows are capped
    server-side (at ``limit`` when given, the server default otherwise)
    unless ``all_samples`` asks for the full listing. Tolerates an older
    server's bare array or histogram-less envelope (stamping ``as_of``
    client-side, pre-request, and leaving ``counts`` to the caller).

    ``sample_filter="errors"`` (sent as ``filter=errors`` on the wire) asks
    the server to return only errored/retried samples (skipping its
    pending-row synthesis — the whole dataset × epochs grid on a large
    eval). The result is trusted as-filtered — no client-side fallback.
    Skew with a server from an older install is not defended (the server
    runs locally from the same install as the CLI in all but
    upgraded-mid-eval cases).

    Raises :class:`_ServerUnreachable` on a non-retryable read failure and
    :class:`_ServerBusy` when the eval stays busy through ``attempts``
    retries (defaulting to the degraded budget — see
    :func:`_get_response_with_retry`); the caller owns the outcome:
    warn-and-skip (an unscoped fan-out over many evals), fail the command
    (a single targeted read, which passes the full budget), or degrade in
    place (``sample show``'s old-server fallback listing read, which keeps
    the default budget and drops only the summary fields).
    """
    fallback_as_of = time.time()
    params: dict[str, Any] = {}
    if active_since is not None:
        params["active_since"] = active_since
    if sample_filter is not None:
        params["filter"] = sample_filter
    if status is not None:
        params["status"] = status
    if all_samples:
        params["all"] = True
    elif limit is not None:
        params["limit"] = limit
    page = _get_with_retry(
        socket_path,
        f"/evals/{eval_id}/samples",
        params=params,
        what=f"Reading samples for eval {eval_id}",
        raise_on_busy=True,
        attempts=attempts,
    )
    if isinstance(page, dict):
        samples = page.get("samples")
        as_of = page.get("as_of")
        counts = page.get("counts")
        return _SamplesPage(
            as_of=float(as_of) if isinstance(as_of, (int, float)) else fallback_as_of,
            samples=samples if isinstance(samples, list) else [],
            counts=counts if isinstance(counts, dict) else None,
            truncated=bool(page.get("truncated", False)),
        )
    return _SamplesPage(
        as_of=fallback_as_of, samples=page if isinstance(page, list) else []
    )


def _fetch_sample_detail(
    socket_path: str, eval_id: str, sample_id: str, epoch: int
) -> dict[str, Any]:
    """Query one control server for a single sample's summary + error detail.

    The one read behind ``sample show`` — the response carries the summary
    fields (timing / tokens / messages) alongside the error history, so no
    supplemental listing fetch is needed. It rides the full narrated
    busy-retry policy rather than failing on a momentary event-loop stall.
    """
    # sample_id goes in the query string (httpx URL-encodes it) so ids
    # containing `/`, `?`, `#`, etc. address correctly — they can't be
    # carried as a path segment.
    return _request_json(
        socket_path,
        f"/evals/{eval_id}/sample",
        params={"sample_id": sample_id, "epoch": epoch},
        what=f"sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "still be running or not yet written to the log."
        ),
    )


def _fetch_sample_events(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    cursor: str | None,
    tail: int | None,
    limit: int | None,
    types: str | None,
    full: bool,
    since_time: float | None,
    until: float | None,
) -> dict[str, Any]:
    """Query one control server for a page of a sample's transcript events.

    The authoritative read behind ``sample events``: like the sample detail
    read, it rides the full narrated busy-retry policy rather than failing on
    a momentary event-loop stall.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply. The
    # wire parameter for the cursor is `since` (the CLI flag is --cursor).
    params: dict[str, Any] = {"sample_id": sample_id, "epoch": epoch, "full": full}
    if cursor is not None:
        params["since"] = cursor
    if tail is not None:
        params["tail"] = tail
    if limit is not None:
        params["limit"] = limit
    if types is not None:
        params["type"] = types
    if since_time is not None:
        params["since_time"] = since_time
    if until is not None:
        params["until"] = until
    return _request_json(
        socket_path,
        f"/evals/{eval_id}/sample/events",
        params=params,
        what=f"events for sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "not have started or not yet been written to the log."
        ),
    )


def _request_json(
    socket_path: str,
    path: str,
    *,
    what: str,
    not_found: str,
    not_found_missing_route: str | None = None,
    params: dict[str, Any] | None = None,
    mutate: Literal["post", "patch"] | None = None,
    retry_mutation: bool = False,
) -> dict[str, Any]:
    """GET (retrying a busy process) or mutate ``path``; return its JSON dict.

    The shared transport / error policy for the per-eval and per-task ctl
    commands. A read goes through :func:`_get_response_with_retry`; a mutation
    isn't idempotent across transport failures, so it gets a single attempt
    with the full mutation budget (see :data:`_MUTATION_TIMEOUT` — eg. a
    remote S3 log flush can take a while) — EXCEPT when the caller marks it
    ``retry_mutation`` (an idempotent last-write-wins latch like
    keep/release), which rides the narrated retrying policy instead of one
    silent long wait. A 404 prints ``not_found`` and exits non-zero; a 400
    surfaces the server's ``{"error": ...}`` body; transport errors exit
    with ``what`` as context.

    ``not_found_missing_route`` splits the 404 by origin (see
    :func:`_handler_404`): a router 404 — the endpoint doesn't exist, so the
    process is running an older inspect — prints it instead of ``not_found``,
    which then only ever means the endpoint answered "entity not found".
    Without it every 404 prints ``not_found``, which must therefore hedge
    both meanings; new endpoints should pass it rather than hedge.
    """
    verb = "update" if mutate else "read"
    try:
        if mutate is not None and retry_mutation:
            response = _get_response_with_retry(
                socket_path,
                path,
                params=params,
                what=f"Updating {what}",
                method=mutate,
            )
        elif mutate is not None:
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
            if not_found_missing_route is not None and not _handler_404(response):
                _fail("not_found", not_found_missing_route, status=404)
            _fail("not_found", not_found, status=404)
        if response.status_code == 400:
            _fail(
                "invalid_request",
                f"Invalid request: {_error_detail_from_response(response)}",
                status=400,
            )
        response.raise_for_status()
        result = response.json()
    except _ServerUnreachable as exc:
        message = f"Failed to {verb} {what}: {_unreachable_detail(exc)}"
        click.echo(message, err=True)
        raise _unreachable_failure(message, exc) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        message = f"Failed to {verb} {what}: {_error_detail(exc)}"
        click.echo(message, err=True)
        raise _CtlFailure.from_exception(message, exc) from exc
    return result if isinstance(result, dict) else {}


def _handler_404(response: httpx.Response) -> bool:
    """Whether a 404 came from an endpoint handler rather than the router.

    Handler 404s ("entity not found") always carry an ``{"error": ...}`` JSON
    body — a control-server convention pinned by a test — while the router's
    404 for a path with no route (a process running an older inspect without
    the endpoint) is FastAPI's stock ``{"detail": "Not Found"}``. Reading the
    distinction off the response beats gating on a version table: it needs no
    per-endpoint bookkeeping and is accurate against servers that predate
    version reporting entirely. Unparseable bodies count as router 404s —
    misreporting a weird handler 404 as version skew still names a true
    remedy (restart on current inspect), whereas the opposite error would
    tell the user their task finished when it didn't.
    """
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "error" in body


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


def _gate_knob_support(
    servers: list[DiscoveredControlServer],
    socket_path: str,
    requested_knobs: list[str],
) -> None:
    """Hard-error before a config mutation the server is too old to apply.

    ``requested_knobs`` are the knob names set on this invocation. Any knob
    whose :data:`_KNOB_SINCE` entry exceeds the target process's advertised
    control-API version fails the command here, *before* the PATCH is sent:
    an older server's handler silently ignores unknown query params while
    applying the knobs it does recognize, so a post-hoc warning would arrive
    after a partial apply. A process with no advertised version (a discovery
    file that predates the field) is version 0. The version integer is
    meaningless to users, so the error names the flags and the remedy, not
    the number. Applies to dry runs too — a dry-run PATCH on an older server
    would report a success-shaped view that omits the unknown knobs.
    """
    gated = [knob for knob in requested_knobs if _KNOB_SINCE[knob] > 0]
    if not gated:
        return
    server = next((s for s in servers if str(s.socket_path) == socket_path), None)
    api_version = server.api_version if server is not None else 0
    unsupported = [knob for knob in gated if _KNOB_SINCE[knob] > api_version]
    if not unsupported:
        return
    flags = ", ".join("--" + knob.replace("_", "-") for knob in unsupported)
    target = f"pid {server.pid}" if server is not None else "the target process"
    click.echo(
        f"{flags} not supported — {target} is running an older inspect; "
        "restart the eval to pick up the current version. No changes were "
        "applied.",
        err=True,
    )
    raise click.exceptions.Exit(code=1)


def _default_provenance_author() -> str:
    """Default provenance author: the git identity, else the OS username.

    Follows the convention inspect_flow's tag/metadata steps use for
    `log_updates` provenance — `git config user.name` + `user.email`
    rendered `Name <email>` (the bare name when there is no email).
    Resolved client-side: the server process has no view of who invoked
    the CLI.
    """
    import getpass
    import subprocess

    def git_config(key: str) -> str:
        try:
            result = subprocess.run(
                ["git", "config", key],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    name = git_config("user.name")
    email = git_config("user.email")
    if name and email:
        return f"{name} <{email}>"
    if name:
        return name
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _gate_provenance_support(
    servers: list[DiscoveredControlServer],
    socket_path: str,
    *,
    author: str | None,
    reason: str | None,
) -> tuple[str | None, str | None]:
    """Resolve the provenance params (`author` / `reason`) for a config mutation.

    Against a server that records config changes (api version >=
    :data:`_PROVENANCE_SINCE`) the author defaults to the client-side git
    identity / OS user, so every recorded retune says who made it. An older
    strict server 400s the whole mutation on the unknown params, so there a
    *defaulted* author is silently dropped (a param the user never typed
    must not fail their retune) while an explicit ``--author`` / ``--reason``
    hard-errors before sending, matching the legacy knob gates.
    """
    server = next((s for s in servers if str(s.socket_path) == socket_path), None)
    api_version = server.api_version if server is not None else 0
    if api_version >= _PROVENANCE_SINCE:
        return (author or _default_provenance_author(), reason)
    if author is not None or reason is not None:
        flags = ", ".join(
            flag
            for flag, value in (("--author", author), ("--reason", reason))
            if value is not None
        )
        target = f"pid {server.pid}" if server is not None else "the target process"
        click.echo(
            f"{flags} not supported — {target} is running an older inspect; "
            "restart the eval to pick up the current version. No changes "
            "were applied.",
            err=True,
        )
        raise click.exceptions.Exit(code=1)
    return (None, None)


def _exec_limits(
    socket_path: str,
    task_id: str | None,
    *,
    max_samples: int | None,
    max_sandboxes: int | None,
    max_subprocesses: int | None = None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None = None,
    log_buffer: int | None = None,
    log_shared: int | None = None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    author: str | None = None,
    reason: str | None = None,
    dry_run: bool,
) -> "_ConfigResult":
    """Read (no set knobs) or retune (any set knob) a scope's config.

    With ``task_id`` set this targets that task's ``/tasks/<id>/config`` (the
    per-task view, including ``max_samples`` and the ``log_buffer`` /
    ``log_shared`` buffer params; task ids are stable across retry attempts);
    with ``task_id=None`` it targets the process-level ``/config``
    (``max_sandboxes`` / ``max_subprocesses`` / ``max_connections`` / the
    retry overrides / named-key knob). ``model`` filters the adaptive
    controllers (a read param, applies to both); ``key`` is the ``(name,
    limit)`` pair for a named ``concurrency()`` registry entry, carried on
    the wire as ``key`` / ``key_limit``. The retry overrides (``timeout`` /
    ``attempt_timeout`` / ``max_retries``) accept the keyword ``clear`` to
    remove an override (``0`` is a real value for them). Any settable knob
    that is not ``None`` makes this a mutation: a single-shot PATCH given the
    full mutation budget (see :data:`_MUTATION_TIMEOUT`) — derived here, not
    caller-supplied, so a knob can never ride a GET as an ignored query
    param. A pure read is a GET that retries a busy process on timeout.
    ``dry_run`` only applies to a set.
    """
    knob_values: dict[str, int | Literal["clear"] | None] = {
        "max_samples": max_samples,
        "max_sandboxes": max_sandboxes,
        "max_subprocesses": max_subprocesses,
        "max_connections": max_connections,
        "key": key[1] if key is not None else None,
        "log_buffer": log_buffer,
        "log_shared": log_shared,
        "timeout": timeout,
        "attempt_timeout": attempt_timeout,
        "max_retries": max_retries,
    }
    # the settable knobs are exactly the scope and since tables' — a knob
    # added to one without the others fails loudly here rather than silently
    # no-opping (or riding past the version gate ungated)
    assert knob_values.keys() == _KNOB_SCOPE.keys() == _KNOB_SINCE.keys()
    set_values = any(value is not None for value in knob_values.values())
    # the key knob rides the wire as two params (key=<name>, key_limit=<n>),
    # so it's excluded from the value passthrough and added explicitly
    params: dict[str, Any] = {
        knob: value
        for knob, value in knob_values.items()
        if knob != "key" and value is not None
    }
    if key is not None:
        params["key"] = key[0]
        params["key_limit"] = key[1]
    if model is not None:
        params["model"] = model
    # provenance rides mutations only (recorded with the change in each
    # affected eval log); the caller has already version-gated the params
    if set_values:
        if author is not None:
            params["author"] = author
        if reason is not None:
            params["reason"] = reason
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
    view = _request_json(
        socket_path,
        f"/tasks/{task_id}/config" if task_id is not None else "/config",
        what=f"config for {scope}",
        not_found=not_found,
        params=params,
        mutate="patch" if set_values else None,
    )
    return _ConfigResult(view=view, mutated=set_values)


class _ConfigResult(NamedTuple):
    """A config read/retune: the server view + whether a PATCH was sent.

    ``mutated`` is the single source for "was this a mutation" — callers
    (the `applied` flag, `changed=` rendering) must not re-derive it from
    their own knob lists, which would skew for a future knob.
    """

    view: dict[str, Any]
    mutated: bool


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


def _knob_label(display: str, knob: str) -> str:
    """Aligned human config label carrying the knob's scope from ``_KNOB_SCOPE``."""
    # width fits the longest label ("max subprocesses [process]:") plus a
    # space — widen it if a longer knob label is ever added
    return f"  {display} [{_KNOB_SCOPE[knob]}]:".ljust(30)


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
        click.echo(_knob_label("max samples", "max_samples") + _PER_TASK_PLACEHOLDER)
    else:
        max_samples = knobs.get("max_samples") or {}
        if max_samples.get("adjustable"):
            limit = _target(max_samples.get("limit"), "max_samples")
            in_use = max_samples.get("in_use")
            label = _knob_label("max samples", "max_samples")
            click.echo(f"{label}{limit} ({in_use} in use)")
        elif max_samples.get("tracks_adaptive"):
            # sample concurrency tracks this task's adaptive controller, so
            # there's no user setpoint to show — point at where the numbers are
            click.echo(
                _knob_label("max samples", "max_samples")
                + "tracks adaptive connections (see below)"
            )
        else:
            # no live sample limiter for this task (e.g. a reused log) — the
            # adaptive block below, if any, belongs to other tasks' models
            click.echo(
                _knob_label("max samples", "max_samples")
                + "not adjustable (no live sample limiter)"
            )

    sandboxes = (knobs.get("max_sandboxes") or {}).get("providers") or []
    if sandboxes:
        rendered = ", ".join(
            f"{s.get('type')} {_target(s.get('limit'), 'max_sandboxes')} ({s.get('in_use')} in use)"
            for s in sandboxes
        )
        click.echo(f"{_knob_label('max sandboxes', 'max_sandboxes')}{rendered}")
    else:
        click.echo(_knob_label("max sandboxes", "max_sandboxes") + "none in effect")

    subprocesses = knobs.get("max_subprocesses") or {}
    if subprocesses.get("limit") is not None:
        limit = _target(subprocesses.get("limit"), "max_subprocesses")
        click.echo(
            f"{_knob_label('max subprocesses', 'max_subprocesses')}{limit} "
            f"({subprocesses.get('in_use')} in use)"
        )
    else:
        click.echo(
            _knob_label("max subprocesses", "max_subprocesses")
            + "inactive (no adjustable subprocess limiter yet)"
        )

    adaptive = (knobs.get("max_connections") or {}).get("adaptive") or []
    if adaptive:
        click.echo(f"  adaptive connections [{_KNOB_SCOPE['max_connections']}]:")
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

    # The retry-override knobs. Absent entirely from an older server's view
    # (which has no override layer) — skipped then rather than shown as a
    # value claim. A knob's current value is the live override or "launch
    # config" (no override — each generate call's own config applies); on a
    # dry-run the requested value renders as an arrow, with `clear` shown as
    # its meaning (back to launch config).
    def _render_retry_knob(knob: str, display: str, unit: str) -> None:
        view = knobs.get(knob)
        if view is None:
            return

        def fmt(value: Any) -> str:
            return "launch config" if value in (None, "clear") else f"{value}{unit}"

        current = view.get("override")
        rendered = fmt(current) if current is None else f"{fmt(current)} (override)"
        proposed = requested.get(knob)
        if proposed is not None and fmt(proposed) != fmt(current):
            rendered += f" → {fmt(proposed)}"
        click.echo(_knob_label(display, knob) + rendered)

    _render_retry_knob("timeout", "timeout", "s")
    _render_retry_knob("attempt_timeout", "attempt timeout", "s")
    _render_retry_knob("max_retries", "max retries", "")

    # The named concurrency() registry entries, addressable via `--key` by the
    # exact name shown. Entries appear lazily on first use, so an empty
    # registry gets a placeholder (like the sibling knobs) that keeps the
    # knob discoverable and distinguishes it from an older server whose view
    # omits the section (`keys` is None).
    keys = (knobs.get("concurrency") or {}).get("keys")
    if keys:
        click.echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]:")
        for row in keys:
            # on a dry-run set, `_target` renders the requested key's limit as
            # `current → requested` (the request rides `concurrency:<name>`)
            limit = _target(row.get("limit"), f"concurrency:{row.get('name')}")
            line = f"    {row.get('name')}: {limit} ({row.get('in_use')} in use)"
            if not row.get("adjustable"):
                line += " — not adjustable"
            click.echo(line)
    else:
        empty = (
            "none registered yet (named limits appear on first use)"
            if keys is not None
            else "not reported (older server)"
        )
        click.echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]: {empty}")

    # The process-level view carries no buffer knobs (they're per-task, read
    # off one task's live logger): mirror the max_samples placeholder so the
    # knobs' existence — and how to see them — stays visible. A *task* view
    # missing them (no live buffer) is reported via warnings instead.
    process_scope = (config.get("target") or {}).get("scope") == "process"
    if "log_buffer" in knobs:
        log_buffer = knobs.get("log_buffer") or {}
        value = _target(log_buffer.get("value"), "log_buffer")
        click.echo(
            f"{_knob_label('log buffer', 'log_buffer')}{value} samples "
            f"({log_buffer.get('pending')} pending)"
        )
    elif process_scope:
        click.echo(_knob_label("log buffer", "log_buffer") + _PER_TASK_PLACEHOLDER)
    if "log_shared" in knobs:
        shared = (knobs.get("log_shared") or {}).get("value")
        rendered_shared = _target(shared, "log_shared") if shared is not None else None
        click.echo(
            _knob_label("shared sync", "log_shared")
            + f"{f'{rendered_shared}s' if rendered_shared is not None else 'off'}"
        )
    elif process_scope:
        click.echo(_knob_label("shared sync", "log_shared") + _PER_TASK_PLACEHOLDER)

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
        bits = [str(e.get("source") or ""), str(e.get("data") or "")]
        return _truncate(" · ".join(b for b in bits if b), 80)
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
        tb = error.get("traceback_ansi") or error.get("traceback") or ""
        for line in tb.rstrip("\n").splitlines():
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
    # (no errors, no retries) uncluttered. The solver column is identity
    # (like model) but hidden when no row carries it — an older server
    # doesn't report it, and an all-blank column is just clutter.
    any_errors = any((s.get("samples") or {}).get("errored", 0) > 0 for s in summaries)
    any_retries = any(int(s.get("attempts", 1) or 1) > 1 for s in summaries)
    any_solver = any(s.get("solver") for s in summaries)

    rows = []
    for s in summaries:
        samples = s.get("samples") or {}
        # task_id (not eval_id): stable across retries, and the handle
        # `inspect ctl sample list` takes.
        cells = [
            _short_id(s.get("task_id", "")),
            s.get("task", "?") or "?",
            s.get("model", "") or "",
        ]
        if any_solver:
            cells.append(s.get("solver", "") or "")
        cells.append(_format_samples(samples))
        if any_errors:
            cells.append(str(samples.get("errored", 0)))
        cells.append(_format_started(s.get("started_at", 0)))
        if any_retries:
            cells.append(str(int(s.get("attempts", 1) or 1)))
        rows.append(tuple(cells))

    headers_list = ["task_id", "task", "model"]
    if any_solver:
        headers_list.append("solver")
    headers_list.append("samples")
    if any_errors:
        headers_list.append("errors")
    headers_list.append("started")
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
    Several columns are conditional, shown only when relevant (keeping the
    common case uncluttered):
    - ``retries`` — when some sample was retried on error. Per-sample
      (sample-level ``retry_on_error``); blank for samples with none.
    - ``score`` — when the samples have exactly one scorer (multi-scorer
      rendering is a later refinement). Running samples aren't scored yet,
      so their cell is blank.
    - ``idle`` — when some sample is running: time since its last transcript
      event (``now - last_activity_at``). A high idle time on a long-running
      sample is the cheap "is it stalled?" cue. Blank for non-running rows.
    - ``limit usage`` / ``limit total`` — when some sample has a token limit
      configured. ``limit usage`` is the metered value for that limit
      (respecting its type — ``all``/``output``/formula) and ``limit total``
      the configured ceiling. Blank for rows without either.
    """
    any_retries = any((s.get("retries") or 0) > 0 for s in samples)
    scorers = sorted({name for s in samples for name in (s.get("scores") or {})})
    score_col = scorers[0] if len(scorers) == 1 else None
    any_running = any(s.get("status") == "running" for s in samples)
    any_token_limit = any(s.get("token_limit_total") is not None for s in samples)
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
        # blank (not 0) when the turn count is unknown: pending rows and
        # samples logged before turn counting existed carry None
        turn_count = s.get("turn_count")
        cells = [
            _format_duration(s.get("total_time")),
            str(s.get("total_tokens", 0)),
            str(s.get("message_count") or 0),
            str(turn_count) if turn_count is not None else "",
        ]
        if any_running:
            last = s.get("last_activity_at")
            idle = (
                _format_duration(now - last)
                if s.get("status") == "running" and last is not None
                else ""
            )
            cells.insert(1, idle)  # after time, before tokens
        if any_token_limit:
            usage = s.get("token_limit_usage")
            total = s.get("token_limit_total")
            cells.append(str(usage) if usage is not None else "")
            cells.append(str(total) if total is not None else "")
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
    headers.extend(["tokens", "messages", "turns"])
    if any_token_limit:
        headers.extend(["limit usage", "limit total"])
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
    if len(identifier) <= _SHORT_ID_LEN:
        return identifier
    return identifier[:_SHORT_ID_LEN]


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
