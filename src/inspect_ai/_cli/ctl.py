"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts the commands that operate on a *running* Inspect
eval via the per-process control server's HTTP endpoints. See
``design/ctl/control-channel.md`` for the design.

Commands are grouped by **resource noun**, mirroring the HTTP API's object
model (see "CLI command hierarchy: noun groups" in the design doc):

- ``task`` — a logical task in a running process (stable across retries):
  ``list`` (implied by the bare noun), ``log-flush``, ``cancel``; ``add`` /
  ``drain`` are planned.
- ``sample`` — one sample (``TASK SAMPLE_ID [EPOCH]``) or a task's samples:
  ``list`` (implied by the bare noun), ``show``, ``errors``, ``events``,
  ``messages``, ``cancel``, ``requeue``.
- ``config`` — a top-level *command* (not a group): view / retune launch
  configuration mid-flight (concurrency limits, log buffering). Scope is a
  property of each knob (task vs process), labeled in the output.
- ``process`` — the running Inspect process itself: ``list`` (implied by the
  bare noun), ``anomalies``, ``keep``, ``release``.

The pre-reorg flat spellings (``tasks``, ``samples``, ``errors``, ``events``,
``keep``, ``release``, ``flush``, ``buffer``, ``limits``) survived as hidden,
deprecation-noted aliases for a transition window and have been removed; the
mapping table in the design doc records each replacement.
"""

from __future__ import annotations

import copy
import functools
import inspect
import json as json_lib
import re
import sys
import time
import traceback
from collections.abc import Awaitable, Callable, Iterator, Sequence
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
    TypeVar,
    cast,
)

import anyio
import click
import httpx
from click.core import ParameterSource
from rich.markup import escape as escape_markup

from inspect_ai._cli.trace import (
    TraceAnomalies,
    anomalies_options,
    anomaly_buckets_json,
    filter_traces,
    rendered_anomalies,
    trace_anomalies,
)
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
from inspect_ai._util._async import configured_async_backend, tg_collect
from inspect_ai._util.name_match import match_name_prefix
from inspect_ai._util.process import pid_alive
from inspect_ai._util.trace import (
    ActionTraceRecord,
    inspect_trace_dir,
    read_trace_file,
)

if TYPE_CHECKING:
    # TYPE_CHECKING to keep the CLI import-light: `inspect_ai.log._samples`
    # pulls in a chunk of the core package this thin HTTP client never needs.
    from inspect_ai.log._samples import SampleCancelAction

# Events shown on an unseeded `sample events` read (no --cursor / --tail /
# --since-time / --until / --from-start): a recent tail rather than the full
# backlog — the first call must never be empty or a context-flooding dump
# (see the agent output contract in design/ctl/control-channel.md). The
# server counts the tail in *matched* events (post --type filter), so this
# is 20 high-signal events by default, not 20 raw transcript entries.
_DEFAULT_EVENTS_TAIL = 20

# Messages shown on an unseeded `sample messages` read (no --tail / --all): a
# recent tail rather than the whole conversation, which for a long agentic run
# can exceed a watching agent's context. Same "never empty, never a flood"
# rationale as the events tail.
_DEFAULT_MESSAGES_TAIL = 20

# Idle seconds on a running sample before the human `sample list` rendering
# appends the `process anomalies` escalation pointer below the table. "Tens
# of minutes" per "Trace-log anomalies for stall diagnosis" in
# design/ctl/control-channel.md: long enough that an ordinarily slow model
# call rarely trips it, short enough to teach the escalation while the stall
# still matters.
_IDLE_POINTER_MIN_SECONDS = 10 * 60

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
    "time_limit": "task",
    "token_limit": "task",
    "message_limit": "task",
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
    "time_limit": 0,
    "token_limit": 0,
    "message_limit": 0,
}

# Minimum control-API version for the config provenance params (`author` /
# `reason`, recorded into `EvalLog.config_updates`). Not a knob — the params
# change nothing — but the CLI sends a *defaulted* author the user never
# typed, and a strict older server would 400 the whole mutation for it, so
# the default is included only against servers advertising >= this version
# (an explicit --author/--reason against an older server hard-errors before
# sending, like the legacy knob gates). See `_gate_provenance_support`.
_PROVENANCE_SINCE = 5


if TYPE_CHECKING:
    # click 8.4 made ParamType generic in its stubs, but subscripting it at
    # runtime raises on the older click versions the package still supports
    # (>=8.1.3), so the parametrized base is typing-only.
    _IntOrClearBase = click.ParamType[int | Literal["clear"]]
else:
    _IntOrClearBase = click.ParamType


class _IntOrClearType(_IntOrClearBase):
    """Non-negative integer, or the keyword ``clear`` (restore launch config).

    The override knobs' value domain (the retry overrides and the per-sample
    limit overrides alike): every integer >= 0 (up to the server-shared
    ``MAX_GENERATE_CONFIG_OVERRIDE`` bound, which ``MAX_SAMPLE_LIMIT_OVERRIDE``
    matches) is a real value (``--max-retries 0`` means fail after the first
    attempt), so clearing an override needs an out-of-band spelling — the
    literal ``clear``, passed through to the server verbatim.
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
            # keep the verb's own help (the payload sketch especially — the
            # bare noun is the spelling scripted consumers reach for first)
            mirrored.help = (
                f"{param.help or ''} Mirrored from `list` for the bare-noun default."
            ).strip()
            group.params.append(mirrored)


def _json_option(what: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--json`` flag every command carries, with per-command envelope help.

    ``what`` sketches the payload's top-level keys so a scripted consumer can
    orient the first parse from ``--help`` alone, without a discovery
    round-trip through the command itself.
    """
    return click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help=f"Output as JSON ({what}).",
    )


def _now_option(
    holds: str = "in-flight samples at their next model call",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--now`` (hard pause) flag the pause verbs carry.

    ``holds`` names what the scope's hard gate parks (the model scope holds
    calls *to* the model, role/grader calls included, rather than samples).
    """
    return click.option(
        "--now",
        is_flag=True,
        default=False,
        help=(
            f"Hard pause: additionally hold {holds} (outstanding calls "
            "finish; wall-clock time limits keep running while held)."
        ),
    )


def _terse_option(
    note: str = "",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--terse/--no-terse`` flag the task-scoped mutation verbs carry.

    Neither spelling given resolves by TTY (see :func:`_use_terse`).
    Deliberately not ``--quiet``: that spelling conventionally means *no*
    output, while this mode still reports each mutation's outcome — one
    scannable line per call (issue #160). ``note`` appends a per-command
    qualifier to the shared help text.
    """
    return click.option(
        "--terse/--no-terse",
        "terse",
        default=None,
        help=(
            "Report the outcome as one `verb target: outcome` line, without "
            "the task header — the default when stdout is not a TTY (pipes, "
            "captured output), so N repeated mutations read as N outcome lines. "
            "--no-terse forces the full rendering; --json takes precedence "
            "over both." + (f" {note}" if note else "")
        ),
    )


def _use_terse(terse: bool | None) -> bool:
    """Resolve the tri-state ``--terse/--no-terse`` flag (``None`` = by TTY).

    Piped or captured stdout — a script, an agent's Bash tool — gets the
    terse per-mutation line; an interactive terminal keeps the full
    task-header rendering, where the surrounding context earns its space.
    """
    if terse is not None:
        return terse
    # a detached/closed stdout (pythonw, a daemonized launcher) must not
    # crash the rendering path — it is certainly not an interactive terminal
    try:
        return not sys.stdout.isatty()
    except (AttributeError, ValueError):
        return True


def _terse_line(verb: str, target: str | None, outcome: str) -> str:
    """The one-line terse mutation grammar: ``verb target: outcome``.

    One composition site so the separator and shape can't drift per verb —
    scripts scan these lines (see the `--terse` help and the "Repeated
    Mutations" section of docs/control-channel.qmd). ``outcome`` starts with
    a status token (``requested`` / ``accepted`` / ``applied`` / ``dry-run``
    / ``no-op``), usually followed by `` — detail``.
    """
    return f"{verb} {target or '?'}: {outcome}"


# The payload sketch every mutation verb's `--json` help shows (pinned to
# `_mutation_envelope`'s keys by a test).
_MUTATION_ENVELOPE_HELP = "a `{target, applied, dry_run, detail}` mutation envelope"


@click.group("ctl")
def ctl_command() -> None:
    """Read and direct running evals and manage kept-alive processes.

    Commands are grouped by resource noun (listed below); `list` verbs are
    implied by the bare noun (`inspect ctl task` ≡ `inspect ctl task list`).
    All commands accept `--json`; a failed `--json` invocation emits an
    `{"error": {kind, exception, message, status}}` envelope on stdout
    (exit code stays non-zero; click usage errors — unknown option,
    missing argument — still exit 2 without one). With no running evals,
    commands that resolve a single task or sample target (and `config`)
    print `null`, except the paged reads (`sample events` / `sample
    messages`), which print an empty page (identifier echo with `task_id`
    null); list verbs print their usual envelope with empty rows.

    A process exits when its eval finishes; launch with `inspect eval
    --ctl-server=keep` to keep it inspectable here until you run
    `inspect ctl process release`.

    To launch an eval in the background — one that outlives your
    terminal and is driven entirely from here — use `inspect eval
    --detach` (see `inspect eval --help`).
    """
    return None


def _echo_no_running_evals() -> None:
    """Print the 'nothing to show' message shared by the read commands.

    Surfaces ``--ctl-server=keep`` here because this fires exactly
    when a user is confused that a just-finished eval isn't listed — its
    process has already exited unless it was launched to park.
    """
    _echo(
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


def _anomalies_pointer(pid: int | None = None) -> str:
    """The stall-site escalation pointer at `inspect ctl process anomalies`.

    Printed wherever the human surface already shows a stall (a long-idle
    sample listing, a busy-skip note): the verb reads the pid's trace file
    directly — nothing is asked of the process — so it is the one `ctl`
    read that works against a busy or hung process. Without ``pid`` the
    bare verb is suggested (it reads every running process). Stderr / human
    rendering only: on ``--json`` the hint is omitted (no teaching prose
    inside envelopes — JSON consumers learn the verb from ``--help``).
    """
    if pid is not None:
        return (
            f"`inspect ctl process anomalies {pid}` shows the process's "
            "in-flight actions"
        )
    return (
        "`inspect ctl process anomalies` shows each running process's in-flight actions"
    )


def _exit_all_busy(busy_pids: list[int]) -> NoReturn:
    """Exit non-zero when no task summaries were collected and busy processes remain.

    The honest sibling of :func:`_echo_no_running_evals`: at least one alive
    process didn't answer (any responsive ones reported no tasks yet — a
    control endpoint binds before its first task registers), so the 'nothing
    running' message (and an empty ``--json`` envelope with exit 0) would be
    a false claim about the busy pids. Each busy pid's skip note has already
    printed the :func:`_anomalies_pointer` escalation (see
    :func:`_fetch_summaries`), so this terminal message doesn't repeat it —
    and the envelope message stays hint-free.
    """
    _fail("busy", f"No tasks visible: {_busy_note(busy_pids)}.")


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

    Example: inspect ctl task list --json
    """
    _run_task_list(as_json)


_mirror_list_options(task_group, task_list_command)


@task_group.command("log-flush")
@click.argument("task", required=False)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_log_flush_command(task: str | None, as_json: bool, terse: bool | None) -> None:
    """Flush a running task's buffered samples to its log now.

    Completed samples are written to the (possibly remote) log only when
    the buffer fills; this forces the write immediately. Safe to repeat.
    Tune the buffering policy itself with `inspect ctl config --log-buffer`
    / `--log-shared`. TASK (a task-id prefix or name) is required when
    several tasks run.
    """
    _run_log_flush(task, as_json, terse=terse)


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
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_cancel_command(
    task: str, action: str, dry_run: bool, as_json: bool, terse: bool | None
) -> None:
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
        terse=terse,
    )


@task_group.command("pause")
@click.argument("task", required=False)
@_now_option()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be paused without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_pause_command(
    task: str | None, now: bool, dry_run: bool, as_json: bool, terse: bool | None
) -> None:
    """Pause a running task (stop dispatching new work; in-flight finishes).

    In-flight samples finish naturally (with scoring and log writes); queued
    samples and a queued retry attempt hold, unstarted — spending none of
    their time limits — until `inspect ctl task resume`. With `--now` (the
    hard pause), in-flight samples additionally hold at their next model
    call: outstanding model calls and batch waits complete, but no new call
    starts until resume. Note the wall clock keeps running for held samples
    — a sample held past its time_limit resolves as an ordinary time-limit
    outcome. Non-destructive, idempotent, and reversible (a plain pause
    after `--now` downgrades to the soft pause); cancel and config changes
    still work on a paused task. To pause a whole eval-set (every task plus
    its task/retry dispatch), use `inspect ctl process pause`. TASK (a
    task-id prefix or name) is required when several tasks run.
    """
    _run_task_pause_resume(
        task, verb="pause", now=now, dry_run=dry_run, as_json=as_json, terse=terse
    )


@task_group.command("resume")
@click.argument("task", required=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_resume_command(
    task: str | None, dry_run: bool, as_json: bool, terse: bool | None
) -> None:
    """Resume a paused task (the inverse of `inspect ctl task pause`).

    Queued samples dispatch again exactly as they would have before the
    pause. Does not clear a process-level pause — a task also held by
    `inspect ctl process pause` stays held until `inspect ctl process
    resume`. Idempotent and last-write-wins. TASK (a task-id prefix or name)
    is required when several tasks run.
    """
    _run_task_pause_resume(
        task, verb="resume", dry_run=dry_run, as_json=as_json, terse=terse
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
@click.option(
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include each errored row's error message in the `--json` rows "
        "(agent-influenced free text — withheld by default)."
    ),
)
@_json_option("an `{as_of, counts, samples, truncated}` envelope")
def sample_list_command(
    task: str | None,
    active_since: float | None,
    limit: int | None,
    all_samples: bool,
    status: str | None,
    content: bool,
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

    Example: inspect ctl sample list my-task --json
    """
    _run_sample_list(
        task,
        active_since,
        as_json,
        status=status,
        limit=limit,
        all_samples=all_samples,
        content=content,
    )


_mirror_list_options(sample_group, sample_list_command)


@sample_group.command("errors")
@click.argument("task", required=False)
@click.option(
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include each row's error message (agent-influenced free text — "
        "withheld by default)."
    ),
)
@_json_option("an `{as_of, counts, samples, truncated}` envelope")
def sample_errors_command(task: str | None, content: bool, as_json: bool) -> None:
    """List the samples of running evals that errored or were retried.

    One row per sample; pass `--content` for the latest error message. An
    omitted TASK spans all running tasks. Drill into one sample with
    `inspect ctl sample show`.
    """
    _run_sample_errors(task, as_json, content=content)


@sample_group.command("show")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include the error messages (agent-influenced free text — withheld "
        "by default; implied by --traceback)."
    ),
)
@click.option(
    "--traceback",
    "-t",
    "show_traceback",
    is_flag=True,
    default=False,
    help="Show the full traceback for each error (implies --content).",
)
@_json_option(
    "the sample's summary + error detail — a flat `{task_id, task, sample_id, "
    "epoch, status, ..., error, error_retries, scores}` object"
)
def sample_show_command(
    task: str,
    sample_id: str,
    epoch: int,
    content: bool,
    show_traceback: bool,
    as_json: bool,
) -> None:
    """Show one sample's summary and error history.

    Reports status / timing / token usage / score and the error presence
    from the current and each prior attempt; pass `--content` for the error
    messages (and `--traceback` for tracebacks). Use `inspect ctl sample
    events` for the transcript. EPOCH defaults to 1 (the response echoes
    the resolved epoch).
    """
    _run_sample_show(
        task, sample_id, epoch, content or show_traceback, show_traceback, as_json
    )


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
        "Show the last N events matching the --type/time filters (when "
        "--cursor is not given), scanning back at most --limit events. "
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
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include truncated free-text content (completions, tool arguments/"
        "results, error messages — agent-controlled text, withheld by "
        "default) in the compact summary."
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
@_json_option("the `{task_id, sample_id, epoch, events, next, done}` envelope")
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
    content: bool,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    """Read one running sample's transcript events (cursored pull).

    The first call returns a recent tail (or the beginning, with
    `--from-start`); each page ends with a `next` cursor — pass it back via
    `--cursor` to read only what's new. `done: true` means the sample has
    terminated and no more events will come. The default is metadata only
    (event types, timing, token counts, tool function names); pass
    `--content` for truncated free-text content or `--full` for raw events.

    Example: inspect ctl sample events my-task sample-1 --tail 20
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
        content=content,
        full=full,
        since_time=since_time,
        until=until,
        as_json=as_json,
    )


@sample_group.command("messages")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--tail",
    type=click.IntRange(min=1),
    default=None,
    help=(
        "Only the last N messages (default: the recent tail — "
        f"{_DEFAULT_MESSAGES_TAIL}). Use --all for the whole conversation."
    ),
)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show the whole conversation instead of a recent tail.",
)
@click.option(
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include truncated message text (and tool-call arguments / tool "
        "errors — agent-controlled text, withheld by default) in the "
        "compact summary."
    ),
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Return raw ChatMessage JSON instead of the compact summary.",
)
@_json_option(
    "the `{task_id, sample_id, epoch, as_of, status, count, messages}` envelope"
)
def sample_messages_command(
    task: str,
    sample_id: str,
    epoch: int,
    tail: int | None,
    show_all: bool,
    content: bool,
    full: bool,
    as_json: bool,
) -> None:
    """Read one sample's current conversation (a snapshot).

    Returns the sample's `TaskState.messages` as they look right now — a
    snapshot, not a stream: the message list is rewritable (compaction,
    solver edits), so there is no resume cursor. The default is a recent tail
    of metadata-only rows (index / role / tool-call function names); pass
    `--all` for the whole conversation or `--tail N` for a specific window,
    `--content` for truncated message text, and `--full` for raw
    `ChatMessage` JSON. For incremental, event-grain watching use `inspect
    ctl sample events`. EPOCH defaults to 1 (the response echoes the
    resolved epoch).
    """
    _run_sample_messages(
        task,
        sample_id,
        epoch,
        tail=tail,
        show_all=show_all,
        content=content,
        full=full,
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
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def sample_cancel_command(
    task: str,
    sample_id: str,
    epoch: int | None,
    action: str,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
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
        terse=terse,
    )


@sample_group.command("requeue")
@click.argument("task")
@click.argument(
    "targets", nargs=-1, metavar="[SAMPLE_ID [EPOCH] | SAMPLE_ID EPOCH ...]"
)
@click.option(
    "--errored",
    is_flag=True,
    default=False,
    help=(
        "Requeue every currently-errored sample of the task (resolved from "
        "the live listing, so each epoch is explicit — never a default). "
        "Mutually exclusive with SAMPLE_ID arguments."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be re-run without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def sample_requeue_command(
    task: str,
    targets: tuple[str, ...],
    errored: bool,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
) -> None:
    """Re-run errored/cancelled samples inside the live run.

    Each sample goes to the back of the sample queue and re-runs under the
    task's normal machinery (prior errors ride along as retry history, and a
    checkpointed sample resumes from its checkpoint); the run's final log
    and counters reflect the fresh outcome. Idempotent — requeuing a sample
    whose re-run is already pending, queued, or running is a clean no-op.
    Requeuing a completed sample is an error (re-running or re-scoring a
    success is out of scope).

    Target one sample (`SAMPLE_ID [EPOCH]`), several (`SAMPLE_ID EPOCH`
    pairs), or every currently-errored sample (`--errored`). A single
    sample's EPOCH defaults to 1 but is required whenever the task runs
    more than one epoch (a defaulted epoch would silently requeue a
    different attempt); with several samples every epoch must be explicit.
    A sweep reports each sample's result individually (requeued / no-op /
    rejected) and exits zero once every sample was attempted — branch on the
    results, not the exit code. Note for scripted sweeps: a single sample
    target keeps the single-sample `--json` envelope; `--errored` always
    returns the bulk envelope (even for one sample).

    Example: inspect ctl sample requeue my-task --errored
    """
    if errored and targets:
        raise click.UsageError(
            "--errored and SAMPLE_ID arguments are mutually exclusive."
        )
    if errored:
        _run_sample_requeue_errored(task, dry_run=dry_run, as_json=as_json, terse=terse)
        return
    if not targets:
        raise click.UsageError(
            "Pass SAMPLE_ID [EPOCH] (or several SAMPLE_ID EPOCH pairs), or "
            "--errored to requeue every currently-errored sample."
        )
    if len(targets) == 1:
        _run_sample_requeue(
            task, targets[0], None, dry_run=dry_run, as_json=as_json, terse=terse
        )
        return
    pairs = _parse_requeue_pairs(targets)
    if len(pairs) == 1:
        _run_sample_requeue(
            task,
            pairs[0][0],
            pairs[0][1],
            dry_run=dry_run,
            as_json=as_json,
            terse=terse,
        )
    else:
        _run_sample_requeue_bulk(
            task, pairs, dry_run=dry_run, as_json=as_json, terse=terse
        )


def _parse_requeue_pairs(targets: tuple[str, ...]) -> list[tuple[str, int]]:
    """Parse two or more requeue tokens as ``SAMPLE_ID EPOCH`` pairs.

    With several samples every epoch must be explicit — the fail-closed
    epoch rule (a defaulted epoch resolves to a *different sample*) leaves
    no safe reading of a bare id list — so an odd token count or a
    non-integer epoch slot is a usage error.
    """
    if len(targets) % 2 != 0:
        raise click.UsageError(
            "Requeue targets must be SAMPLE_ID EPOCH pairs — with several "
            "samples every epoch must be explicit (a defaulted epoch would "
            "silently requeue a different attempt)."
        )
    pairs: list[tuple[str, int]] = []
    for sample_id, epoch_token in zip(targets[::2], targets[1::2]):
        try:
            epoch = int(epoch_token)
        except ValueError:
            raise click.UsageError(
                f"'{epoch_token}' is not an integer EPOCH — pass SAMPLE_ID "
                "EPOCH pairs (with several samples every epoch must be "
                "explicit)."
            ) from None
        pairs.append((sample_id, epoch))
    return pairs


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
    "--time-limit",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['time_limit']}] Override the per-sample wall-clock "
        "time limit, in seconds — reaches in-flight samples too ('clear' "
        "restores launch config)."
    ),
)
@click.option(
    "--token-limit",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['token_limit']}] Override the per-sample token limit "
        "— applies at each sample's next token check, in-flight samples "
        "included ('clear' restores launch config)."
    ),
)
@click.option(
    "--message-limit",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['message_limit']}] Override the per-sample message "
        "limit — applies at each sample's next message check, in-flight "
        "samples included ('clear' restores launch config)."
    ),
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
@_json_option(
    "a `{target, knobs, warnings, notes, applied, dry_run, persisted, "
    "requested}` view, every knob labeled with its scope"
)
@_terse_option(note="Applies when setting a knob; a pure view always renders in full.")
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
    time_limit: int | Literal["clear"] | None,
    token_limit: int | Literal["clear"] | None,
    message_limit: int | Literal["clear"] | None,
    timeout: int | Literal["clear"] | None,
    attempt_timeout: int | Literal["clear"] | None,
    max_retries: int | Literal["clear"] | None,
    reason: str | None,
    author: str | None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
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
    requests still drain first); pass `clear` to remove an override.
    `--time-limit` / `--token-limit` / `--message-limit` likewise set live
    overrides on the task's per-sample limits, read where each sample's
    limits are checked — so a retune reaches in-flight samples (a lowered
    time limit cancels a sample already past it) as well as ones not yet
    started; pass `clear` to restore launch config. Applied
    changes are recorded in each affected eval log (who / when / old → new);
    `--reason` annotates the record with why. TASK
    is required only for setting a task-scoped knob when several tasks run.

    Example: inspect ctl config --max-connections 20 --dry-run
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
        time_limit=time_limit,
        token_limit=token_limit,
        message_limit=message_limit,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        reason=reason,
        author=author,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
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

    The selector is a positional PID: optional for `keep` / `release` when
    a single process is running, and for `anomalies`, where no PID reads
    every running process.
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
    f"`inspect ctl process release {token}`; for one's in-flight actions: "
    f"`inspect ctl process anomalies {token}`."
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
@_json_option(_MUTATION_ENVELOPE_HELP)
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
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_release_command(pid: int | None, as_json: bool) -> None:
    """Release a lingering --ctl-server=keep process so it can exit.

    Issued while the eval is still running it means "exit when done",
    unless a later `keep` overrides it (last-write-wins). Does NOT cancel
    the eval or affect in-flight samples.
    """
    _run_keep_alive(pid, keep=False, as_json=as_json)


@process_group.command("pause")
@click.argument("pid", required=False, type=int)
@_now_option()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be paused without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_pause_command(
    pid: int | None, now: bool, dry_run: bool, as_json: bool
) -> None:
    """Pause a whole running eval or eval-set (stop dispatching new work; in-flight finishes).

    One process-scoped latch: no new eval-set tasks dispatch, no task
    retries start, and no samples dispatch in any task; in-flight samples
    finish naturally. With `--now` (the hard pause), in-flight samples
    additionally hold at their next model call — model spend stops as soon
    as outstanding calls complete, at the price of the wall clock running
    for held samples (a sample held past its time_limit resolves as an
    ordinary time-limit outcome). The process, its queue, and this control
    surface stay alive — watch `inspect ctl task list` for `quiesced`
    (paused with nothing in flight), after which completed work is flushed
    and the process can be killed cleanly if needed (under `--now`, a
    nonzero `held` count means samples are mid-flight: killing then
    forfeits their in-sample progress). Resume with `inspect ctl process
    resume`. Idempotent and non-destructive.
    """
    _run_process_pause_resume(
        pid, verb="pause", now=now, dry_run=dry_run, as_json=as_json
    )


@process_group.command("resume")
@click.argument("pid", required=False, type=int)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_resume_command(pid: int | None, dry_run: bool, as_json: bool) -> None:
    """Resume a paused eval or eval-set (the inverse of `process pause`).

    Dispatch picks up exactly where it left off. Task-level pauses (from
    `inspect ctl task pause`) are deliberately left in place. Note the
    distinction with `process release`: resume re-opens a *paused* run;
    release ends a keep-alive *park* after the eval finishes.
    """
    _run_process_pause_resume(pid, verb="resume", dry_run=dry_run, as_json=as_json)


@process_group.command("anomalies")
@click.argument("pid", required=False, type=int)
@anomalies_options(
    "an `{as_of, processes}` envelope; each process entry carries `pid`, "
    "`trace_file`, its own `as_of` (the timestamp running durations are "
    "computed against), and the `running`/`cancelled`/`errors`/`timeouts` "
    "buckets"
)
def process_anomalies_command(
    pid: int | None, filter: str | None, all: bool, as_json: bool
) -> None:
    """Show in-flight and anomalous actions from a process's trace log.

    Reconstructs from the pid's trace file what is running right now
    (entered, never exited — with live durations) plus what was cancelled;
    `--all` adds errored and timed-out actions. This is the "why" behind a
    stalled sample: a single in-flight operation (model call, sandbox exec)
    emits no transcript event until it returns, but its trace action is
    visible here.

    The trace file is read directly (nothing is asked of the process), so
    this works against a busy or hung process — the escalation path when
    another read reports "busy" — and even post-mortem: a PID with no live
    process falls back to its trace file (`trace-<pid>.log`, or `.log.gz`
    after a clean exit) while one still exists, with running durations dated
    to the file's last write (approximately the time of death) rather than
    now. No PID reads every running process, one section per pid. The
    analysis is shared with `inspect trace anomalies`, which reads any trace
    file by path.
    """
    _run_process_anomalies(pid, filter=filter, all=all, as_json=as_json)


# ---------------------------------------------------------------------------
# model group
# ---------------------------------------------------------------------------


@ctl_command.group("model", cls=_NounGroup)
def model_group() -> None:
    """Operate on the models of running evals.

    MODEL is the exact model name as `inspect ctl task list` shows it
    (e.g. openai/gpt-5-nano). One latch per model: pausing holds every
    task whose primary model matches — including eval-set tasks that
    haven't started yet — while other models' work continues.
    """


assert isinstance(model_group, _NounGroup)
model_group.hint = lambda token: (
    f"No such command '{token}'. To pause or resume one model's dispatch: "
    f"`inspect ctl model pause {token}` / `inspect ctl model resume {token}`."
)


@model_group.command("pause")
@click.argument("model")
@click.argument("pid", required=False, type=int)
@_now_option(
    holds=(
        "generate calls to MODEL at their next attempt — including other "
        "tasks' role/grader calls to it"
    )
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be paused without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def model_pause_command(
    model: str, pid: int | None, now: bool, dry_run: bool, as_json: bool
) -> None:
    """Pause one model's dispatch (stop starting its tasks' work; in-flight finishes).

    Holds every task whose *primary* model is MODEL: no new samples or
    retry attempts start, and the eval-set scheduler does not start its
    not-yet-started tasks — which `inspect ctl task pause` cannot reach.
    Everything else keeps running, and in-flight samples (including other
    tasks' role/grader calls to this model) finish naturally. With `--now`
    (the hard pause), generate calls to MODEL — role/grader calls included
    — hold at their next attempt instead: the model's spend stops as soon
    as outstanding calls complete, while the wall clock keeps running for
    held samples. MODEL is the exact name shown by `inspect ctl task list`;
    an unknown name is an error. PID is required when several processes
    run. Idempotent; resume with `inspect ctl model resume`.
    """
    _run_model_pause_resume(
        model, pid, verb="pause", now=now, dry_run=dry_run, as_json=as_json
    )


@model_group.command("resume")
@click.argument("model")
@click.argument("pid", required=False, type=int)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def model_resume_command(
    model: str, pid: int | None, dry_run: bool, as_json: bool
) -> None:
    """Resume a paused model (the inverse of `inspect ctl model pause`).

    The model's held tasks dispatch again exactly as they would have before
    the pause. Task-level and process-level pauses are deliberately left in
    place (independent latches). Idempotent and last-write-wins. PID is
    required when several processes run.
    """
    _run_model_pause_resume(model, pid, verb="resume", dry_run=dry_run, as_json=as_json)


# ---------------------------------------------------------------------------
# --json error envelope
# ---------------------------------------------------------------------------
#
# The error-path half of the agent output contract (see "Agent output
# contract" in design/ctl/control-channel.md): the success path is enveloped
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
        missing_route: bool = False,
    ) -> None:
        super().__init__(1)
        self.kind = kind
        self.message = message
        self.exception = exception
        self.status = status
        # a router 404 (endpoint absent — older server) rather than an
        # entity 404; classification for callers that must tell the two
        # apart (e.g. the bulk-requeue sweep aborts on it), not an
        # envelope field
        self.missing_route = missing_route
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
        _echo_raw(json_lib.dumps(envelope, indent=2))


def _fail(
    kind: _ErrorKind,
    message: str,
    *,
    exception: str | None = None,
    status: int | None = None,
    missing_route: bool = False,
) -> NoReturn:
    """Echo ``message`` to stderr and raise the matching :class:`_CtlFailure`.

    The standard shape for a terminal error site: the same self-contained
    message serves as both the human stderr prose and the envelope
    ``message``. Sites that interleave extra stderr output between the echo
    and the raise (warnings, a candidates table) or derive the failure from
    an exception (``raise ... from exc``) construct :class:`_CtlFailure`
    directly instead.
    """
    _echo(message, err=True)
    raise _CtlFailure(
        kind, message, exception=exception, status=status, missing_route=missing_route
    )


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
        _echo(traceback.format_exc(), err=True, nl=False)
        _CtlFailure(
            "internal",
            str(exc) or _exception_name(exc),
            exception=_exception_name(exc),
        ).emit()
        raise click.exceptions.Exit(code=1) from exc


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _envelope_failures(fn: Callable[_P, None]) -> Callable[_P, None]:
    """Wrap a command runner in :func:`_structured_failures`.

    Reads the runner's ``as_json`` argument off the bound call, so the
    wrapper needs no per-runner plumbing. Every runner must take an
    ``as_json`` parameter —
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
# command runners
# ---------------------------------------------------------------------------


@_envelope_failures
def _run_task_list(as_json: bool) -> None:
    # Stamp as_of BEFORE the reads: anything that changes during them has a
    # timestamp >= as_of and is caught by the next poll rather than missed.
    as_of = time.time()
    summaries = _fetch_summaries(list_discovered_servers()).summaries

    if as_json:
        _echo_raw(json_lib.dumps({"as_of": as_of, "tasks": summaries}, indent=2))
        return

    if not summaries:
        _echo_no_running_evals()
        return

    _print_human_table(summaries)
    _print_keep_alive_footer(summaries)
    _print_errored_samples_footer(summaries)


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
    content: bool = False,
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

    reads = _run_async(
        functools.partial(
            _read_all_eval_samples,
            targets,
            active_since,
            sample_filter=sample_filter,
            status=status_param,
            limit=limit,
            all_samples=all_samples,
            content=content,
            # a scoped read fails the command on busy, so it keeps the
            # full budget; the unscoped fan-out skips on the default
            attempts=_REQUEST_ATTEMPTS if task is not None else None,
        )
    )

    as_of_values: list[float] = []
    read: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for target, page in reads:
        if isinstance(page, _ServerUnreachable):
            if task is not None:
                _exit_samples_unreachable(
                    target["eval_id"], page, pid=target.get("pid")
                )
            # An unscoped read spans whatever evals happen to be running; one
            # process exiting — or staying busy through the retries — between
            # discovery and this read shouldn't fail the invocation (even if
            # it was the only eval).
            hint = (
                f"try again shortly, or {_anomalies_pointer(target.get('pid'))}"
                if isinstance(page, _ServerBusy)
                else "it may have just exited"
            )
            _echo(
                f"Skipping eval {target['eval_id']}: its samples could not be "
                f"read ({_unreachable_detail(page)}) — {hint}.",
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


class _EvalSamplesRead(NamedTuple):
    """One target eval's samples read (see :func:`_read_all_eval_samples`).

    ``page`` is the eval's samples, or the :class:`_ServerUnreachable` that
    replaced it — captured rather than raised because the reads run
    concurrently, and an exception escaping into the task group would cancel
    its siblings where the policy is per-eval warn-and-skip.
    """

    target: dict[str, Any]
    page: _SamplesPage | _ServerUnreachable


async def _read_all_eval_samples(
    targets: list[dict[str, Any]],
    active_since: float | None,
    *,
    sample_filter: Literal["errors"] | None,
    status: str | None,
    limit: int | None,
    all_samples: bool,
    content: bool,
    attempts: int | None,
) -> list[_EvalSamplesRead]:
    """Read each target eval's samples concurrently, in target order.

    The reads go out together because their cost is round-trip and connection
    setup, not server work: one at a time, an unscoped listing over an eval
    set with many running tasks paid that round-trip per eval and looked
    hung, while each server answered in about a millisecond.
    """
    # concurrent reads stall in lockstep, so they share one narrator rather
    # than each reporting the same wedged process's every attempt
    narrator = (
        _BusyNarrator(f"Reading samples from {len(targets)} evals")
        if len(targets) > 1
        else None
    )

    async def read(target: dict[str, Any]) -> _EvalSamplesRead:
        # Query by the task's current eval id (resolved fresh each invocation,
        # so this still works after a retry minted a new one).
        try:
            page = await _fetch_samples_async(
                target["socket_path"],
                target["eval_id"],
                active_since,
                sample_filter=sample_filter,
                status=status,
                limit=limit,
                all_samples=all_samples,
                content=content,
                attempts=attempts,
                narrator=narrator,
            )
        except _ServerUnreachable as exc:
            return _EvalSamplesRead(target, exc)
        return _EvalSamplesRead(target, page)

    return await _collect_reads([functools.partial(read, target) for target in targets])


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
    content: bool = False,
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
        content=content,
        idle_pointer=True,
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


def _run_sample_errors(
    task: str | None, as_json: bool, *, content: bool = False
) -> None:
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
        content=content,
        # this is the error-focused view, so an empty error column needs
        # the pointer to the opt-in
        content_footer=None
        if content
        else "error messages withheld — pass --content to include them",
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
    content: bool = False,
    content_footer: str | None = None,
    idle_pointer: bool = False,
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
    ``--status`` member set (``None`` = no filter). ``content`` asks the
    server to include each row's error message (withheld by default —
    agent-influenced free text); ``content_footer`` is a human-rendering
    footer noting the withholding (echoed after a non-empty table, and
    suppressed when a row carries an error message anyway — a pre-v6 server
    ignores the ``content`` param, and the footer must not caption text
    printed right above it as withheld).
    ``idle_pointer`` opts the human rendering into the long-idle escalation
    footer (`sample list` — the listing whose idle column shows a stall; see
    :func:`_echo_idle_pointer`).
    """
    listing = _list_sample_rows(
        task,
        active_since,
        sample_filter=sample_filter,
        statuses=statuses,
        limit=limit,
        all_samples=all_samples,
        content=content,
    )
    rows = listing.rows

    if as_json:
        _echo_raw(
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
        _echo(_task_header(listing.targets[0]))
        if not rows:
            _echo(empty)
            return
        _echo()
        printer(rows)
    else:
        if not rows:
            _echo(empty)
            return
        printer(rows, show_task=True)
    if content_footer is not None and not any(
        row.get("error") is not None for row in rows
    ):
        _echo()
        _echo(content_footer)
    if listing.truncated:
        _echo_truncation_footer(
            len(rows),
            listing.counts,
            statuses=statuses,
            delta=active_since is not None,
        )
    if idle_pointer:
        _echo_idle_pointer(rows, listing.read)


def _echo_idle_pointer(rows: list[dict[str, Any]], read: list[dict[str, Any]]) -> None:
    """Print the stall-escalation footer below a long-idle sample listing.

    The idle column says a running sample has been silent, not why: a single
    in-flight operation (model call, sandbox exec) emits no transcript event
    until it returns, so a long idle reads identically whether the call is
    slow-but-healthy or hung. The trace file is the layer below, and where
    the table already shows the stall the surface teaches the escalation
    (see :func:`_anomalies_pointer`) rather than relying on the user knowing
    the trace subsystem exists. ``read`` (the targets whose samples were
    fetched) supplies the pid, keyed by ``task_id`` — the only target
    identity a row carries. A ``task_id`` is not unique across ``read`` (an
    old kept-alive attempt a newer process is retrying shares it — see
    ``stop_on_task_id`` on :func:`_fetch_summaries` — and pre-task-id
    servers report none), so a task read from several processes counts them
    all: naming one would risk pointing at the wrong process. Whenever the
    stalled rows resolve to anything but exactly one pid the bare verb is
    suggested, which reads every process. Human rendering only — the
    ``--json`` path returns before any table is printed.
    """
    now = datetime.now(timezone.utc).timestamp()
    pids_by_task: dict[Any, set[Any]] = {}
    for target in read:
        pids_by_task.setdefault(target.get("task_id"), set()).add(target.get("pid"))
    idles: list[float] = []
    pids: set[Any] = set()
    for sample in rows:
        last = sample.get("last_activity_at")
        if sample.get("status") != "running" or last is None:
            continue
        idle = now - float(last)
        if idle >= _IDLE_POINTER_MIN_SECONDS:
            idles.append(idle)
            pids.update(pids_by_task.get(sample.get("task_id")) or {None})
    if not idles:
        return
    only = next(iter(pids)) if len(pids) == 1 else None
    pid = int(only) if only is not None else None
    _echo()
    _echo(f"idle {_format_duration(max(idles))} — {_anomalies_pointer(pid)}")


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
    _echo()
    _echo(f"listing capped: {showing} — {hint}")


@_envelope_failures
def _run_sample_show(
    task: str,
    sample_id: str,
    epoch: int,
    content: bool,
    show_traceback: bool,
    as_json: bool,
) -> None:
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    # One atomic read: the detail carries the summary fields (timing / tokens
    # / messages) alongside the error history, so there is no supplemental
    # listing fetch (and no torn view if the sample retries between reads).
    detail = _fetch_sample_detail(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        content=content,
        pid=target.get("pid"),
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
        _echo_raw(json_lib.dumps(merged, indent=2))
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
        hint = (
            f" — try again shortly, or {_anomalies_pointer(target.get('pid'))}"
            if isinstance(exc, _ServerBusy)
            else ""
        )
        _echo(
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
    content: bool,
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
            _echo_raw(json_lib.dumps(empty_page, indent=2))
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
        content=content,
        full=full,
        since_time=since_time,
        until=until,
        pid=target.get("pid"),
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
        _echo_raw(json_lib.dumps(page, indent=2))
        return

    _print_events(page, content=content, full=full)


@_envelope_failures
def _run_sample_messages(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    tail: int | None,
    show_all: bool,
    content: bool,
    full: bool,
    as_json: bool,
) -> None:
    # `--all` and `--tail` are mutually exclusive ways to size the window;
    # an explicit --tail with --all is contradictory, so reject it rather
    # than silently letting one win.
    if show_all and tail is not None:
        _fail(
            "invalid_request",
            "--all and --tail are mutually exclusive (--all shows every "
            "message; --tail sizes a recent window).",
        )
    # The unseeded default is a recent tail — never an overwhelming first
    # page. --all disables it; an explicit --tail overrides it.
    if not show_all and tail is None:
        tail = _DEFAULT_MESSAGES_TAIL

    fetched = _fetch_sample_summaries()
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            # Uniform --json shape even on the empty page (task_id is
            # unresolvable with no running evals; as_of is None because no
            # server stamped a read time).
            empty_page: dict[str, Any] = {
                "task_id": None,
                "sample_id": sample_id,
                "epoch": epoch,
                "as_of": None,
                "status": None,
                "count": 0,
                "messages": [],
            }
            _echo_raw(json_lib.dumps(empty_page, indent=2))
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    page = _fetch_sample_messages(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        tail=tail,
        content=content,
        full=full,
        pid=target.get("pid"),
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
        _echo_raw(json_lib.dumps(page, indent=2))
        return

    _echo(_task_header(target))
    _echo()
    _print_messages(page, content=content, full=full)


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
        pid=target.pid,
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
        _echo_raw(json_lib.dumps(result, indent=2))
        return

    already = detail.get("changed") is False
    if keep:
        _echo(
            f"Keep-alive already on for pid {target.pid}."
            if already
            else f"Keep-alive requested for pid {target.pid}."
        )
    else:
        _echo(
            f"Keep-alive already off for pid {target.pid}."
            if already
            else f"Release requested for pid {target.pid}."
        )


@_envelope_failures
def _run_log_flush(task: str | None, as_json: bool, terse: bool | None = None) -> None:
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries
    scope = _resolve_scope(servers, summaries, task, per_task_option="task log-flush")
    if scope is None:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    # per_task_option forbids the process-scope fallbacks, so the resolved
    # scope always carries a task
    assert scope.task_id is not None
    result = _post_flush(scope.socket_path, scope.task_id, pid=scope.pid)

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
        _echo_raw(json_lib.dumps(envelope, indent=2))
        return

    flushed = int(result.get("flushed", 0) or 0)
    if _use_terse(terse):
        outcome = (
            f"applied — flushed {flushed} sample{'' if flushed == 1 else 's'}"
            if flushed
            else "no-op — no buffered samples"
        )
        _echo(_terse_line("log-flush", scope.task or scope.task_id, outcome))
        return
    _echo(scope.header)
    if flushed:
        _echo(f"\nFlushed {flushed} sample{'' if flushed == 1 else 's'} to the log.")
    else:
        _echo("\nNo buffered samples to flush.")


class _MutationOutcome(NamedTuple):
    applied: bool
    detail: dict[str, Any]


def _mutation_outcome(result: dict[str, Any], *, dry_run: bool) -> _MutationOutcome:
    """The ``applied``/``detail`` semantics every mutation result shape shares.

    ``applied`` reports whether the mutation actually landed — false on a
    dry run and on the idempotent already-in-that-state no-op (the server's
    ``changed: false``) — so an agent branches on one field. The server's
    response rides along as ``detail`` (minus the transport-level ``ok``).
    Both the single-sample envelope and the bulk-requeue per-sample results
    derive these fields here so the rule cannot drift between them.
    """
    return _MutationOutcome(
        applied=bool(result.get("changed")) and not dry_run,
        detail={k: v for k, v in result.items() if k != "ok"},
    )


def _mutation_envelope(
    target: dict[str, Any], result: dict[str, Any], *, dry_run: bool
) -> dict[str, Any]:
    """The uniform ``--json`` mutation result envelope for the cancel verbs."""
    outcome = _mutation_outcome(result, dry_run=dry_run)
    return {
        "target": target,
        "applied": outcome.applied,
        "dry_run": dry_run,
        "detail": outcome.detail,
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
    terse: bool | None = None,
) -> None:
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries
    scope = _resolve_scope(servers, summaries, task, per_task_option="task cancel")
    if scope is None:
        if as_json:
            _echo_raw("null")
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
        pid=scope.pid,
    )

    if as_json:
        target = {"task_id": scope.task_id, "task": scope.task}
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope(target, result, dry_run=dry_run), indent=2
            )
        )
        return

    terse_mode = _use_terse(terse)
    target_label = scope.task or scope.task_id
    if not terse_mode:
        _echo(scope.header)
        _echo()
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
        if terse_mode:
            status = "dry-run" if dry_run else "requested"
            _echo(
                _terse_line(
                    "cancel", target_label, f"{status} — {interrupted}; {suffix}"
                )
            )
        elif dry_run:
            _echo(f"Would cancel — {interrupted}; {suffix}.")
        else:
            _echo(f"Cancel requested — {interrupted}; {suffix}.")
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        if terse_mode:
            _echo(_terse_line("cancel", target_label, f"no-op — {reason}"))
        else:
            _echo(f"Nothing to do: {reason}.")


# the hard-pause caveat, shared by the three pause scopes' messages
_HELD_CAVEAT = (
    "outstanding calls finish; wall-clock time limits keep running while held"
)


def _pause_prefix(*, now: bool, dry_run: bool, target: str = "") -> str:
    """The leading clause of a pause confirmation, across scope/strength/dry-run."""
    if dry_run:
        return f"Would {'hard-pause' if now else 'pause'} {target}".rstrip()
    requested = "Hard pause requested" if now else "Pause requested"
    return f"{requested} for {target}" if target else requested


def _pause_confirmation(
    *,
    now: bool,
    dry_run: bool,
    target: str = "",
    body: str,
    no_new: str,
    hint_hard: str,
    hint_soft: str,
) -> str:
    """Assemble a pause confirmation from its scope-specific prose.

    Owns the skeleton shared by the three pause scopes (prefix — body;
    no new X start; trailing hint) so their structure can't drift.
    ``body`` may contain ``{will}`` placeholders, resolved to would/will
    here so callers don't need the tense. The hints are appended only
    for real mutations and carry their own leading punctuation (usually
    ``". "``; the model scope opens with a parenthetical instead).
    """
    will = "would" if dry_run else "will"
    message = (
        f"{_pause_prefix(now=now, dry_run=dry_run, target=target)} — "
        f"{body.format(will=will)}; no new {no_new} {will} start"
    )
    if dry_run:
        return message + "."
    return message + (hint_hard if now else hint_soft)


_PAUSE_ROUTE_MISSING = (
    "This process is running an older inspect without the pause/resume "
    "endpoints; restart the eval to pick up the current version."
)

_MODEL_PAUSE_ROUTE_MISSING = (
    "This process is running an older inspect without the model pause/resume "
    "endpoints; restart the eval to pick up the current version."
)


def _paused_sources(value: Any) -> list[str]:
    """Normalize a ``paused`` field to its list of holding latches.

    Current servers send the source list (``["task", "process", "model"]``
    in any combination); pre-model-latch servers (<= 0.3.250) sent a single
    string with ``"both"`` for task+process. ``None``/empty means not
    paused.
    """
    if not value:
        return []
    if isinstance(value, str):
        return ["task", "process"] if value == "both" else [value]
    return [str(v) for v in value]


def _still_held_note(held: list[str]) -> str:
    """Point at the broader latch(es) still holding a task after `task resume`."""
    latches = []
    if "process" in held:
        latches.append("the process is paused (`inspect ctl process resume`)")
    if "model" in held:
        latches.append("its model is paused (`inspect ctl model resume`)")
    return f"Note: {' and '.join(latches)} — samples stay held until resumed."


def _terse_held_suffix(held: list[str]) -> str:
    """The still-held latches folded into a terse `task resume` line.

    The terse mode's one-line budget can't carry :func:`_still_held_note`'s
    full prose, but silently dropping the fact would misreport a resume that
    leaves the task held — so the latch names ride as a parenthetical, with
    the clearing command kept: the terse default's non-TTY audience (an
    agent) is exactly who needs the next command spelled out.
    """
    latches = [latch for latch in ("process", "model") if latch in held]
    if not latches:
        return ""
    names = " and ".join(f"{latch} pause" for latch in latches)
    commands = " / ".join(f"`inspect ctl {latch} resume`" for latch in latches)
    return f" (still held by {names} — {commands})"


@_envelope_failures
def _run_task_pause_resume(
    task: str | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    """Pause or resume one task (``POST /tasks/<task-id>/pause|resume``).

    Follows the mutation selector rule with the sole-running-task default:
    pause is non-destructive and trivially reversible, so it does not join
    ``task cancel`` in the selector-always-required class (the same
    reasoning that gives ``process keep`` / ``release`` the sole-target
    default — the worst case of a wrongly targeted pause is a resume).
    ``now`` (the hard pause) needs no version gate: an older server rejects
    the unknown param with a 400 (strict mutations), so it fails loudly
    rather than silently soft-pausing.
    """
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries
    scope = _resolve_scope(servers, summaries, task, per_task_option=f"task {verb}")
    if scope is None:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    assert scope.task_id is not None

    params: dict[str, Any] = {}
    if now:
        params["now"] = True
    if dry_run:
        params["dry_run"] = True
    # idempotent last-write-wins latch, so it may ride the narrated
    # busy-retry policy like keep/release and cancel
    result = _request_json(
        scope.socket_path,
        f"/tasks/{scope.task_id}/{verb}",
        params=params,
        what=f"{verb} of task {scope.task_id}",
        not_found=(
            f"Task '{scope.task_id}' not found in this process (it may have finished)."
        ),
        not_found_missing_route=_PAUSE_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
        pid=scope.pid,
    )

    if as_json:
        target = {"task_id": scope.task_id, "task": scope.task}
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope(target, result, dry_run=dry_run), indent=2
            )
        )
        return

    terse_mode = _use_terse(terse)
    target_label = scope.task or scope.task_id
    if not terse_mode:
        _echo(scope.header)
        _echo()
    if result.get("changed"):
        if verb == "pause":
            # `dispatched` counts samples past the gate, including ones still
            # initializing their sandbox (which the listing shows as queued)
            dispatched = int(result.get("dispatched", 0) or 0)
            noun = f"{dispatched} dispatched sample{'' if dispatched == 1 else 's'}"
            if now:
                body = (
                    f"{noun} {{will}} hold at "
                    f"{'its' if dispatched == 1 else 'their'} next model call "
                    f"({_HELD_CAVEAT})"
                )
            else:
                body = f"{noun} {{will}} finish naturally"
            if terse_mode:
                will = "would" if dry_run else "will"
                _echo(
                    _terse_line(
                        "pause",
                        target_label,
                        f"{'dry-run' if dry_run else 'requested'} — "
                        f"{body.format(will=will)}; no new samples or retry "
                        f"attempts {will} start",
                    )
                )
            else:
                _echo(
                    _pause_confirmation(
                        now=now,
                        dry_run=dry_run,
                        body=body,
                        no_new="samples or retry attempts",
                        hint_hard=(
                            ". Watch `inspect ctl task list` for the held count;"
                            " resume with `inspect ctl task resume`."
                        ),
                        hint_soft=". Resume with `inspect ctl task resume`.",
                    )
                )
        elif terse_mode:
            # independent latches: a task resume does not clear a process
            # or model pause, so say when the task is still held
            held = [] if dry_run else _paused_sources(result.get("paused"))
            _echo(
                _terse_line(
                    "resume",
                    target_label,
                    f"{'dry-run' if dry_run else 'requested'} — queued samples "
                    f"{'would' if dry_run else 'will'} dispatch again"
                    f"{_terse_held_suffix(held)}",
                )
            )
        elif dry_run:
            _echo("Would resume — queued samples would dispatch again.")
        else:
            _echo("Resume requested — queued samples will dispatch again.")
            # independent latches: a task resume does not clear a process or
            # model pause, so say when the task is still held
            held = _paused_sources(result.get("paused"))
            if "process" in held or "model" in held:
                _echo(_still_held_note(held))
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        # "task is not paused" is technically right for a task held only by
        # the process or model latch, but the operator wants it moving —
        # point at the latch that actually holds it
        held = _paused_sources(result.get("paused"))
        note_held = verb == "resume" and ("process" in held or "model" in held)
        if terse_mode:
            suffix = _terse_held_suffix(held) if note_held else ""
            _echo(_terse_line(verb, target_label, f"no-op — {reason}{suffix}"))
        else:
            _echo(f"Nothing to do: {reason}.")
            if note_held:
                _echo(_still_held_note(held))


@_envelope_failures
def _run_process_pause_resume(
    pid: int | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Pause or resume a whole process (``POST /pause`` / ``POST /resume``).

    ``now`` (the hard pause) needs no version gate: an older server rejects
    the unknown param with a 400 (strict mutations), so it fails loudly
    rather than silently soft-pausing.
    """
    target = _resolve_target_server(pid)
    params: dict[str, Any] = {}
    if now:
        params["now"] = True
    if dry_run:
        params["dry_run"] = True
    result = _request_json(
        str(target.socket_path),
        f"/{verb}",
        params=params,
        what=f"{verb} for pid {target.pid}",
        not_found=_PAUSE_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
        pid=target.pid,
    )

    if as_json:
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope({"pid": target.pid}, result, dry_run=dry_run),
                indent=2,
            )
        )
        return

    if result.get("changed"):
        if verb == "pause":
            body = (
                f"in-flight samples {{will}} hold at their next model call "
                f"({_HELD_CAVEAT})"
                if now
                else "in-flight samples {will} finish"
            )
            _echo(
                _pause_confirmation(
                    now=now,
                    dry_run=dry_run,
                    target=f"pid {target.pid}",
                    body=body,
                    no_new="samples, task retries, or eval-set tasks",
                    hint_hard=(
                        ". Watch `inspect ctl task list` for the held count; "
                        "resume with `inspect ctl process resume`."
                    ),
                    hint_soft=(
                        ". Watch `inspect ctl task list` for quiesced; "
                        "resume with `inspect ctl process resume`."
                    ),
                )
            )
        elif dry_run:
            _echo(f"Would resume pid {target.pid}.")
        else:
            _echo(
                f"Resume requested for pid {target.pid} — dispatch picks up "
                "where it left off (task-level pauses, if any, stay in place)."
            )
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        _echo(f"Nothing to do: {reason} (pid {target.pid}).")


@_envelope_failures
def _run_model_pause_resume(
    model: str,
    pid: int | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Pause or resume one model's dispatch (``POST /models/pause|resume``).

    The process selector matches keep/release (sole-process default, PID to
    disambiguate); MODEL is an exact model name, validated *server-side*
    against the models the process could dispatch — a client-side resolve
    against the task summaries would wrongly reject a model whose tasks are
    all still queued (not-yet-started eval-set tasks have no summary row),
    which is precisely the model latch's reason to exist. ``now`` (the hard
    pause) needs no version gate: an older server rejects the unknown param
    with a 400 (strict mutations), so it fails loudly rather than silently
    soft-pausing.
    """
    target = _resolve_target_server(pid)
    params: dict[str, Any] = {"model": model}
    if now:
        params["now"] = True
    if dry_run:
        params["dry_run"] = True
    result = _request_json(
        str(target.socket_path),
        f"/models/{verb}",
        params=params,
        what=f"{verb} of model {model} (pid {target.pid})",
        not_found=(
            f"Model '{model}' not found in pid {target.pid} (pass the exact "
            "model name as shown by `inspect ctl task list`)."
        ),
        not_found_missing_route=_MODEL_PAUSE_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
    )

    if as_json:
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope(
                    {"model": model, "pid": target.pid}, result, dry_run=dry_run
                ),
                indent=2,
            )
        )
        return

    if result.get("changed"):
        if verb == "pause":
            # `tasks`/`dispatched` count only registered tasks — the latch
            # additionally holds this model's not-yet-started eval-set
            # tasks, which have no row to count
            tasks = int(result.get("tasks", 0) or 0)
            dispatched = int(result.get("dispatched", 0) or 0)
            counts = (
                f"{tasks} running task{'' if tasks == 1 else 's'}, "
                f"{dispatched} dispatched sample{'' if dispatched == 1 else 's'}"
            )
            if now:
                body = (
                    f"{counts}; generate calls to it (role/grader calls "
                    f"included) {{will}} hold at their next attempt "
                    f"({_HELD_CAVEAT})"
                )
            else:
                body = f"{counts} {{will}} finish naturally"
            _echo(
                _pause_confirmation(
                    now=now,
                    dry_run=dry_run,
                    target=model,
                    body=body,
                    no_new="samples, retry attempts, or eval-set tasks of this model",
                    hint_hard=(
                        " (other models keep running)."
                        " Watch `inspect ctl task list` for held counts;"
                        " resume with `inspect ctl model resume`."
                    ),
                    hint_soft=(
                        " (other models keep running)."
                        " Resume with `inspect ctl model resume`."
                    ),
                )
            )
        elif dry_run:
            _echo(f"Would resume {model} — its held work would dispatch again.")
        else:
            _echo(
                f"Resume requested for {model} — its held work dispatches "
                "again (task- and process-level pauses, if any, stay in place)."
            )
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        _echo(f"Nothing to do: {reason} ({model}).")


def _run_sample_mutation(
    task: str,
    sample_id: str,
    epoch: int | None,
    *,
    verb: str,
    extra_params: dict[str, Any],
    route_missing: str,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
    changed_message: Callable[[str, dict[str, Any]], str],
    noop_message: Callable[[str, dict[str, Any]], str],
    terse_changed: Callable[[dict[str, Any]], str],
    terse_noop: Callable[[dict[str, Any]], str],
) -> None:
    """Shared scaffold for the per-sample mutation verbs (cancel, requeue).

    Fetches summaries, resolves the target eval, applies the required-EPOCH
    gate, posts ``/evals/{eval_id}/sample/{verb}``, and renders the uniform
    ``--json`` mutation envelope, a terse ``verb task/sample (epoch n):
    outcome`` line (see :func:`_use_terse`), or the task header plus a
    message line. Only the verb, extra request params, missing-route text,
    and the applied/no-op message lines differ per mutation; the full-mode
    callbacks receive the rendered ``sample <id> (epoch <n>)`` label and the
    server's response, the terse callbacks just the response (the scaffold
    prefixes the target itself, so every terse line names it — the full
    no-op messages don't have to).
    """
    fetched = _fetch_sample_summaries()
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            _echo_raw("null")
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
                f"pass EPOCH explicitly (a defaulted epoch would {verb} the "
                "epoch-1 attempt).",
            )
        epoch = 1

    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        **extra_params,
    }
    if dry_run:
        params["dry_run"] = True
    result = _request_json(
        str(target["socket_path"]),
        f"/evals/{target['eval_id']}/sample/{verb}",
        params=params,
        what=f"{verb} of sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found in task "
            f"'{target.get('task') or '?'}'."
        ),
        not_found_missing_route=route_missing,
        mutate="post",
        retry_mutation=True,
        pid=target.get("pid"),
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
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope(envelope_target, result, dry_run=dry_run), indent=2
            )
        )
        return

    # the server echoes the resolved identifiers; fall back to what was sent
    resolved_id = result.get("sample_id", sample_id)
    resolved_epoch = result.get("epoch", epoch)

    if _use_terse(terse):
        target_label = _sanitize_line(
            f"{target.get('task') or '?'}/{resolved_id} (epoch {resolved_epoch})"
        )
        outcome = terse_changed(result) if result.get("changed") else terse_noop(result)
        _echo(_terse_line(verb, target_label, outcome))
        return

    _echo(_task_header(target))
    _echo()
    # the label is sanitized before the callbacks interpolate it (with other
    # wire fields — status, reason) so a swallow can't eat the message tail;
    # `_echo` sanitizes whatever the composed line still carries
    label = _sanitize_line(f"sample {resolved_id} (epoch {resolved_epoch})")
    if result.get("changed"):
        _echo(changed_message(label, result))
    else:
        _echo(noop_message(label, result))


@_envelope_failures
def _run_sample_cancel(
    task: str,
    sample_id: str,
    epoch: int | None,
    *,
    action: SampleCancelAction,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    outcome = {
        "score": "scored on the work done so far",
        "error": "marked as errored",
        "cancel": "recorded as cancelled",
    }[action]

    def changed_message(label: str, result: dict[str, Any]) -> str:
        if dry_run:
            return f"Would cancel {label} — it would be {outcome}."
        return f"Cancel requested for {label} — it will be {outcome}."

    def noop_message(label: str, result: dict[str, Any]) -> str:
        status = result.get("status")
        suffix = f" (status: {_sanitize_line(str(status))})" if status else ""
        return f"Nothing to do — {label} has already finished{suffix}."

    def terse_changed(result: dict[str, Any]) -> str:
        if dry_run:
            return f"dry-run — would be {outcome}"
        return f"requested — will be {outcome}"

    def terse_noop(result: dict[str, Any]) -> str:
        status = result.get("status")
        suffix = f" (status: {_sanitize_line(str(status))})" if status else ""
        return f"no-op — already finished{suffix}"

    _run_sample_mutation(
        task,
        sample_id,
        epoch,
        verb="cancel",
        extra_params={"action": action},
        route_missing=_CANCEL_ROUTE_MISSING,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
        changed_message=changed_message,
        noop_message=noop_message,
        terse_changed=terse_changed,
        terse_noop=terse_noop,
    )


_REQUEUE_ROUTE_MISSING = (
    "This process is running an older inspect without the requeue "
    "endpoint; restart the eval to pick up the current version."
)


def _requeue_resume_clause(result: dict[str, Any]) -> str:
    """How the requeued sample will re-run (checkpoint resume vs fresh)."""
    return (
        "resume from its checkpoint"
        if result.get("resume_from_checkpoint")
        else "re-run from the back of the sample queue"
    )


def _requeue_changed_message(
    label: str, result: dict[str, Any], *, dry_run: bool
) -> str:
    """The human line for an accepted (or would-be-accepted) requeue."""
    resume = _requeue_resume_clause(result)
    if dry_run:
        return f"Would requeue {label} — it would {resume}."
    return f"Requeue accepted for {label} — it will {resume}."


@_envelope_failures
def _run_sample_requeue(
    task: str,
    sample_id: str,
    epoch: int | None,
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    def changed_message(label: str, result: dict[str, Any]) -> str:
        return _requeue_changed_message(label, result, dry_run=dry_run)

    def noop_message(label: str, result: dict[str, Any]) -> str:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        return f"Nothing to do — {reason}."

    def terse_changed(result: dict[str, Any]) -> str:
        if dry_run:
            return f"dry-run — would {_requeue_resume_clause(result)}"
        return f"accepted — will {_requeue_resume_clause(result)}"

    def terse_noop(result: dict[str, Any]) -> str:
        return f"no-op — {result.get('reason') or 'already in that state'}"

    _run_sample_mutation(
        task,
        sample_id,
        epoch,
        verb="requeue",
        extra_params={},
        route_missing=_REQUEUE_ROUTE_MISSING,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
        changed_message=changed_message,
        noop_message=noop_message,
        terse_changed=terse_changed,
        terse_noop=terse_noop,
    )


@_envelope_failures
def _run_sample_requeue_bulk(
    task: str,
    pairs: list[tuple[str, int]],
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    """Requeue several explicitly-listed ``(sample_id, epoch)`` pairs."""
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    _requeue_pairs(target, pairs, dry_run=dry_run, as_json=as_json, terse=terse)


@_envelope_failures
def _run_sample_requeue_errored(
    task: str,
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    """Requeue every sample of the task whose *current* status is ``error``.

    Resolved from the same live listing `sample errors` reads, filtered to
    the errored status (a retried-and-now-running sample is not swept), so
    each requeue's epoch comes from the listing — the fail-closed epoch
    concern never arises. Racing the scheduler is safe: the endpoint's
    idempotence turns a sample that recovers between the listing and the
    post into a per-sample no-op.
    """
    listing = _list_sample_rows(
        task, None, statuses=frozenset({"error"}), all_samples=True
    )
    if not listing.targets:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    target = listing.targets[0]
    pairs: list[tuple[str, int]] = []
    for row in listing.rows:
        # a row without an epoch fails loudly rather than defaulting: the
        # sweep's whole safety claim is that no epoch is ever a default
        if row.get("epoch") is None:
            _fail(
                "invalid_response",
                f"Sample listing row for '{row.get('sample_id')}' carries no "
                "epoch — cannot requeue it fail-closed (requeue it "
                "individually with an explicit EPOCH).",
            )
        pairs.append((str(row["sample_id"]), int(row["epoch"])))
    _requeue_pairs(target, pairs, dry_run=dry_run, as_json=as_json, terse=terse)


def _requeue_pairs(
    target: dict[str, Any],
    pairs: list[tuple[str, int]],
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    """Post one requeue per pair and report each sample's result individually.

    The sweep is a client-side loop over the per-sample endpoint (see
    design/ctl/sample-requeue.md — bulk is deliberately not an endpoint
    semantic). A per-sample HTTP rejection (409 completed, entity 404, 400)
    is recorded in its result and the sweep continues; a failure that would
    fail every remaining post identically (unreachable/busy process, missing
    route on an older server) aborts the whole command — safe to re-run, the
    endpoint is idempotent. The command exits zero once every sample was
    attempted; per-sample outcomes live in the results. The posts run with
    ``echo_failures=False`` so a recorded rejection is reported exactly once,
    in the stdout report — otherwise every rejection would also appear as
    transport stderr narration, doubling the output. That makes this caller
    responsible for echoing the failures it re-raises (the abort path), since
    nothing downstream prints them in human mode.
    """

    def what(sample_id: str) -> str:
        return f"requeue of sample {sample_id}"

    results: list[dict[str, Any]] = []
    for sample_id, epoch in pairs:
        params: dict[str, Any] = {"sample_id": sample_id, "epoch": epoch}
        if dry_run:
            params["dry_run"] = True
        try:
            result = _request_json(
                str(target["socket_path"]),
                f"/evals/{target['eval_id']}/sample/requeue",
                params=params,
                what=what(sample_id),
                not_found=(
                    f"Sample '{sample_id}' (epoch {epoch}) not found in task "
                    f"'{target.get('task') or '?'}'."
                ),
                not_found_missing_route=_REQUEUE_ROUTE_MISSING,
                mutate="post",
                retry_mutation=True,
                pid=target.get("pid"),
                echo_failures=False,
            )
        except _CtlFailure as exc:
            if exc.missing_route or exc.kind not in (
                "not_found",
                "invalid_request",
                "http_error",
            ):
                _echo(exc.message, err=True)
                raise
            results.append(
                {
                    "sample_id": sample_id,
                    "epoch": epoch,
                    "applied": False,
                    # the full error-object shape (`{kind, exception, message,
                    # status}`), matching the top-level error envelope
                    "error": {
                        "kind": exc.kind,
                        "exception": exc.exception,
                        "message": exc.message,
                        "status": exc.status,
                    },
                }
            )
            continue
        outcome = _mutation_outcome(result, dry_run=dry_run)
        results.append(
            {
                "sample_id": result.get("sample_id", sample_id),
                "epoch": result.get("epoch", epoch),
                "applied": outcome.applied,
                "detail": outcome.detail,
            }
        )

    changed = sum(1 for r in results if (r.get("detail") or {}).get("changed"))
    rejected = sum(1 for r in results if "error" in r)
    noops = len(results) - changed - rejected

    if as_json:
        envelope = {
            "target": {
                "task_id": target.get("task_id"),
                "task": target.get("task"),
            },
            "dry_run": dry_run,
            "requested": len(pairs),
            "applied": sum(1 for r in results if r["applied"]),
            "results": results,
        }
        _echo_raw(json_lib.dumps(envelope, indent=2))
        return

    use_terse = _use_terse(terse)
    if not use_terse:
        _echo(_task_header(target))
        _echo()
    if not pairs:
        # only the errored sweep can arrive with no pairs — the explicit-pairs
        # caller always passes two or more
        _echo("(no errored samples to requeue)")
        return
    for entry in results:
        label = f"sample {entry['sample_id']} (epoch {entry['epoch']})"
        if "error" in entry:
            # the recorded message stays self-contained, but the transport
            # prefix restates the label — render just the server detail
            message = str(entry["error"]["message"])
            message = message.removeprefix(
                _failure_prefix("update", what(entry["sample_id"]))
            )
            if use_terse:
                _echo(_terse_line("requeue", label, f"rejected — {message}"))
            else:
                _echo(f"Rejected {label} — {message}")
        elif (entry.get("detail") or {}).get("changed"):
            if use_terse:
                terse_outcome = (
                    f"dry-run — would {_requeue_resume_clause(entry['detail'])}"
                    if dry_run
                    else f"accepted — will {_requeue_resume_clause(entry['detail'])}"
                )
                _echo(_terse_line("requeue", label, terse_outcome))
            else:
                _echo(_requeue_changed_message(label, entry["detail"], dry_run=dry_run))
        else:
            reason = str(
                (entry.get("detail") or {}).get("reason") or "already in that state"
            )
            if use_terse:
                _echo(_terse_line("requeue", label, f"no-op — {reason}"))
            else:
                _echo(f"Nothing to do for {label} — {reason}.")
    if use_terse:
        return
    _echo()
    verb = "Would requeue" if dry_run else "Requeued"
    notes: list[str] = []
    if noops:
        notes.append(f"{noops} no-op{'' if noops == 1 else 's'}")
    if rejected:
        notes.append(f"{rejected} rejected")
    suffix = f" ({', '.join(notes)})" if notes else ""
    _echo(
        f"{verb} {changed} of {len(pairs)} sample{'' if len(pairs) == 1 else 's'}{suffix}."
    )


@_envelope_failures
def _run_process_list(as_json: bool) -> None:
    as_of = time.time()
    servers = list_discovered_servers()
    summaries = _fetch_summaries(servers).summaries if servers else []

    rows: list[dict[str, Any]] = []
    for server in servers:
        hosted = [s for s in summaries if s.get("pid") == server.pid]
        # keep-alive is a process-level property every hosted task shares;
        # unknown (None) when no task has registered yet. The process pause
        # latch is likewise process-level (also None against an older server
        # that doesn't report it).
        keep_alive = bool(hosted[0].get("keep_alive")) if hosted else None
        paused = (
            bool(hosted[0].get("process_paused"))
            if hosted and hosted[0].get("process_paused") is not None
            else None
        )
        # the hard (`pause --now`) strength of the process latch; False
        # against an older server that doesn't report it (soft is the only
        # strength such a server can hold)
        paused_now = bool(hosted[0].get("process_paused_now")) if hosted else False
        rows.append(
            {
                "pid": server.pid,
                "socket_path": str(server.socket_path),
                "started_at": server.started_at,
                "keep_alive": keep_alive,
                "paused": paused,
                "paused_now": paused_now,
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
        _echo_raw(json_lib.dumps({"as_of": as_of, "processes": rows}, indent=2))
        return

    if not rows:
        _echo("No running inspect processes found.")
        return

    table_rows: list[tuple[str, ...]] = []
    for row in rows:
        keep = row["keep_alive"]
        paused = row["paused"]
        tasks = row["tasks"]
        table_rows.append(
            (
                str(row["pid"]),
                "?" if keep is None else ("on" if keep else "off"),
                _format_process_paused(paused, row["paused_now"]),
                ", ".join(str(t.get("task") or "?") for t in tasks) or "(starting)",
                _format_started(row["started_at"]),
            )
        )
    _render_table(("pid", "keep-alive", "paused", "tasks", "started"), table_rows)


def _format_process_paused(paused: bool | None, paused_now: bool) -> str:
    """The process latch cell: unknown / no / yes, with the hard strength marked."""
    if paused is None:
        return "?"
    if not paused:
        return "no"
    return "yes (now)" if paused_now else "yes"


class _PidAnomalies(NamedTuple):
    """One `process anomalies` section: a pid, its trace file, and the reconstruction.

    ``as_of`` is the timestamp the section's running durations are computed
    against: for a live pid, stamped just after its file is read (stamping
    before could date an ``enter`` record that lands mid-read to the future,
    i.e. a negative duration); for a dead pid's post-mortem read, the trace
    file's last write (a proxy for time of death).
    """

    pid: int
    trace_file: Path
    anomalies: TraceAnomalies
    as_of: float


def _trace_file_for_pid(pid: int) -> Path | None:
    """The pid's trace file: ``trace-<pid>.log``, or ``.log.gz`` after a clean exit.

    ``None`` when neither exists (swept by the keep-newest-10 rotation).
    Live and dead pids resolve the same way — the mapping is pure filename
    convention, which is what makes the post-mortem read possible.
    """
    for name in (f"trace-{pid}.log", f"trace-{pid}.log.gz"):
        path = inspect_trace_dir() / name
        if path.exists():
            return path
    return None


def _sanitized_anomalies(anomalies: TraceAnomalies) -> TraceAnomalies:
    """A copy of ``anomalies`` with its rendered text fields neutralized.

    The anomalies detail column embeds agent-controlled text verbatim — a
    stalled sandboxed ``bash`` call's shlex-joined command line preserves the
    agent's script bytes — and :func:`rendered_anomalies` (shared with
    `inspect trace anomalies`) renders through rich, which keeps escape bytes
    in ``export_text(styles=True)`` and parses cell strings as console markup
    (so e.g. ``[link=...]`` in agent text would export an OSC 8 hyperlink).
    Fields are therefore sanitized per record before they enter the table —
    not post-export, where one row's unterminated OSC would swallow the rows
    after it — with newlines flattened like the other table cells and markup
    escaped to render literally. The ``--json`` envelope keeps the raw bytes.
    """

    def clean(text: str) -> str:
        return escape_markup(_sanitize_line(text))

    def clean_record(record: ActionTraceRecord) -> ActionTraceRecord:
        return record.model_copy(
            update=dict(
                action=clean(record.action),
                message=clean(record.message),
                detail=clean(record.detail),
                error=None if record.error is None else clean(record.error),
            )
        )

    return TraceAnomalies(
        running=[clean_record(r) for r in anomalies.running],
        cancelled=[clean_record(r) for r in anomalies.cancelled],
        errors=[clean_record(r) for r in anomalies.errors],
        timeouts=[clean_record(r) for r in anomalies.timeouts],
    )


@_envelope_failures
def _run_process_anomalies(
    pid: int | None, *, filter: str | None, all: bool, as_json: bool
) -> None:
    """Anomalies from trace files: one section per targeted pid.

    Deliberately a client-side file read with no HTTP endpoint — the prime
    anomalies scenario is a wedged process, precisely when the control
    server (which shares the eval's loop) can't answer (see "Trace-log
    anomalies for stall diagnosis" in design/ctl/control-channel.md).
    """
    # Stamp the envelope as_of before the reads (same cursor rationale as the
    # other read envelopes: anything that changes during them has a timestamp
    # >= as_of and is caught by the next poll). Sections date their running
    # durations to their own as_of instead (see _PidAnomalies), where
    # stamp-after-read is the consistent choice — matching `inspect trace
    # anomalies`, which cannot produce negative durations.
    as_of = time.time()

    servers: list[DiscoveredControlServer] = []
    if pid is not None:
        # An explicit PID needs no discovery: the trace file is pid-keyed on
        # disk, so a dead process resolves exactly like a live one (the
        # post-mortem read).
        trace_file = _trace_file_for_pid(pid)
        if trace_file is None:
            looked_for = inspect_trace_dir() / f"trace-{pid}.log"
            _fail(
                "not_found",
                f"No trace file found for pid {pid} (looked for "
                f"{looked_for}[.gz]; rotation keeps only the newest 10 trace "
                "files). If you have a copy elsewhere, read it with "
                "`inspect trace anomalies <file>`.",
            )
        if pid_alive(pid):
            post_mortem_as_of: float | None = None
        else:
            # Post-mortem read: date running durations to the trace file's
            # last write — a proxy for the time of death — so an action in
            # flight when the process died doesn't accrue wall-clock time
            # since (an overnight death would otherwise show it "running"
            # for hours).
            post_mortem_as_of = trace_file.stat().st_mtime
            _echo(
                f"note: pid {pid} is not running — durations are as of the "
                "trace file's last write.",
                err=True,
            )
        targets = [(pid, trace_file, post_mortem_as_of)]
    else:
        servers = list_discovered_servers()
        targets = []
        for server in servers:
            server_trace = _trace_file_for_pid(server.pid)
            if server_trace is None:
                # same warn-and-skip as the unscoped fan-out reads: this
                # pid's section can't be read, the others' still can
                _echo(
                    f"note: no trace file found for pid {server.pid} — skipped.",
                    err=True,
                )
                continue
            # discovery only lists live pids, so durations date to the read
            targets.append((server.pid, server_trace, None))

    sections: list[_PidAnomalies] = []
    for target_pid, target_file, target_post_mortem_as_of in targets:
        try:
            records = read_trace_file(target_file)
        except Exception as ex:
            # catch Exception, not (OSError, ValueError): "unreadable file"
            # has no closed exception vocabulary — e.g. mid-stream gz
            # corruption raises zlib.error, which is neither
            if pid is not None:
                # explicit-pid reads fail loudly (the caller asked for
                # exactly this pid), with the same clean stderr-plus-envelope
                # contract as every other terminal ctl error
                message = (
                    f"Could not read trace file {target_file} for pid "
                    f"{target_pid}: {ex}"
                )
                _echo(message, err=True)
                raise _CtlFailure(
                    "internal", message, exception=_exception_name(ex)
                ) from ex
            # the widened fan-out warns-and-skips like the missing-trace-file
            # case, keeping the other sections readable
            _echo(
                f"note: could not read {target_file} for pid {target_pid} "
                f"({ex}) — skipped.",
                err=True,
            )
            continue
        anomalies = trace_anomalies(filter_traces(records, filter))
        sections.append(
            _PidAnomalies(
                pid=target_pid,
                trace_file=target_file,
                anomalies=anomalies,
                as_of=(
                    time.time()
                    if target_post_mortem_as_of is None
                    else target_post_mortem_as_of
                ),
            )
        )

    if as_json:
        envelope = {
            "as_of": as_of,
            "processes": [
                {
                    "pid": section.pid,
                    "trace_file": section.trace_file.as_posix(),
                    "as_of": section.as_of,
                    **anomaly_buckets_json(section.anomalies, section.as_of),
                }
                for section in sections
            ],
        }
        _echo_raw(json_lib.dumps(envelope, indent=2))
        return

    if not sections:
        if servers:
            _echo(
                "No readable trace files found for the running processes "
                "(see notes above)."
            )
        else:
            _echo(
                "No running inspect processes found. Pass a PID to read an "
                "exited process's trace file post-mortem (`inspect trace "
                "list` shows the trace files still on disk)."
            )
        return

    # _sanitize_keep_sgr as a backstop over the already-sanitized rendering:
    # rich's own styling exports as SGR (kept), so anything else that ever
    # leaks into the export is neutralized without trusting its internals.
    _echo_raw(
        "\n\n".join(
            _sanitize_keep_sgr(
                rendered_anomalies(
                    section.trace_file,
                    _sanitized_anomalies(section.anomalies),
                    all,
                    pid=section.pid,
                    as_of=section.as_of,
                )
            )
            for section in sections
        )
    )


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
    time_limit: int | Literal["clear"] | None,
    token_limit: int | Literal["clear"] | None,
    message_limit: int | Literal["clear"] | None,
) -> list[str]:
    """Names of the requested knobs the server reported as adjustable.

    Serves the no-live-buffer hard-error path so its "other knobs were still
    applied" tail names only knobs that actually landed — a requested knob
    the server reported as not adjustable did NOT apply. The buffer knobs
    self-exclude: their adjustability check (no ``buffer`` view) is exactly
    the condition that put the caller on the error path. The retry and
    per-sample limit overrides are always adjustable: the override layers
    exist regardless of any task's launch config, and `_gate_knob_support`
    has already excluded older servers.
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
            ("--time-limit", time_limit, True),
            ("--token-limit", token_limit, True),
            ("--message-limit", message_limit, True),
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
    time_limit: int | Literal["clear"] | None = None,
    token_limit: int | Literal["clear"] | None = None,
    message_limit: int | Literal["clear"] | None = None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    reason: str | None = None,
    author: str | None = None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
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
                ("--time-limit", time_limit),
                ("--token-limit", token_limit),
                ("--message-limit", message_limit),
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
            _echo_raw("null")
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
        "time_limit": time_limit,
        "token_limit": token_limit,
        "message_limit": message_limit,
    }
    # a knob missing here would be silently exempt from the version gate —
    # the exact silent-skew failure `_gate_knob_support` exists to close
    assert knob_values.keys() == _KNOB_SCOPE.keys()
    requested_knobs = [knob for knob, value in knob_values.items() if value is not None]
    _gate_knob_support(servers, scope.socket_path, requested_knobs)

    # provenance rides recorded mutations only — a read records nothing. The
    # author default is resolved client-side — the server has no view of who
    # invoked the CLI — and gated on the server supporting the params. On a
    # pure read an explicit --author/--reason has nothing to annotate:
    # hard-error (like --log-buffer with no buffer) rather than silently
    # dropping the values.
    if requested_knobs:
        author, reason = _gate_provenance_support(
            servers, scope.socket_path, author=author, reason=reason
        )
    elif author is not None or reason is not None:
        flags = " / ".join(
            flag
            for flag, value in (("--author", author), ("--reason", reason))
            if value is not None
        )
        _fail(
            "invalid_request",
            f"{flags} annotates a config change, but no set option was given "
            "— there is no record to attach it to. Add a set option "
            "(e.g. --max-samples) or drop the flag.",
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
        time_limit=time_limit,
        token_limit=token_limit,
        message_limit=message_limit,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        author=author,
        reason=reason,
        pid=scope.pid,
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
                time_limit=time_limit,
                token_limit=token_limit,
                message_limit=message_limit,
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
            _echo(message, err=True)
            for warning in limits_view.get("warnings") or []:
                # the buffer warning restates the headline error; skip it
                if not warning.startswith("log_buffer"):
                    _echo(f"! {warning}", err=True)
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
        _echo_raw(json_lib.dumps(config, indent=2))
        return

    # terse covers only a set — a pure view's requested output *is* the full
    # config block, so there is no header noise to shed
    if mutated and _use_terse(terse):
        target_label = (
            scope.task
            or scope.task_id
            or (f"pid {scope.pid}" if scope.pid is not None else "process")
        )
        settings = []
        for knob, value in knob_values.items():
            if value is None or knob == "key":
                continue
            rendered = f"{knob}={value}"
            # --model narrows the connections retune to matching controllers —
            # dropped from the line, a scripted log misrecords the blast radius
            if knob == "max_connections" and model is not None:
                rendered += f" (models matching '{model}')"
            settings.append(rendered)
        if key is not None:
            settings.append(f"concurrency:{key[0]}={key[1]}")
        _echo(
            _terse_line(
                "config",
                target_label,
                f"{'dry-run' if dry_run else 'applied'} — {', '.join(settings)}",
            )
        )
        # warnings and notes must survive terseness — "applied" above may be
        # qualified by a not-adjustable knob or a process-wide blast radius
        for warning in config.get("warnings") or []:
            _echo(f"! {warning}")
        for note in config.get("notes") or []:
            _echo(f"note: {note}")
        return

    _echo(scope.header)
    _echo()
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
    # The per-sample limit overrides (task views only — the knobs are
    # task-scoped; also absent from an older server's view). `override` is
    # the live task-wide override, None = launch config applies per sample.
    limits_view_overrides = limits_view.get("limits")
    if limits_view_overrides is not None:
        from inspect_ai.util._limit_overrides import SAMPLE_LIMIT_OVERRIDE_FIELDS

        for limit_knob in SAMPLE_LIMIT_OVERRIDE_FIELDS:
            knobs[limit_knob] = {
                "scope": _KNOB_SCOPE[limit_knob],
                "override": limits_view_overrides.get(limit_knob),
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
        # eval log(s); None when nothing was applied — no set option, or a
        # server that predates config-change persistence
        "persisted": persisted,
        "requested": limits_view.get("requested") or None,
    }


class _DirectiveScope(NamedTuple):
    """A directive command's resolved target (see :func:`_resolve_scope`)."""

    socket_path: str
    pid: int | None
    """The target process's pid (``None`` for a pre-pid discovery entry).

    Scopes the busy-retry exhaustion pointer to the resolved process (see
    ``pid`` on :func:`_request_json`) — the directive narration names one
    target, so its escalation must not suggest scanning every process.
    """
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
                pid=servers[0].pid,
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
            pid=target.get("pid"),
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
            pid=target.get("pid"),
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
        pid=tasks_in_proc[0].get("pid"),
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

# Ceiling on a fan-out's in-flight reads (see `_collect_reads`). The reads are
# cheap and their cost is round-trip, so a wave of this size already collapses
# the wall clock of any realistic eval set to a couple of round-trips; raising
# it buys no time, because the server answering them shares the eval's single
# event loop and handles them one at a time whatever the client does. What it
# would buy is a wider blast radius: a fan-out spans *every* task in the run
# (completed ones included), so an uncapped one opens a connection per task
# into the process it is inspecting — and a client-side fd exhaustion is an
# OSError, which this module reads as "the eval has gone away".
_MAX_CONCURRENT_READS = 32

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


class _BusyNarrator:
    """Narrates a fan-out's busy retries once per attempt, not once per target.

    A single read narrates each of its own timed-out attempts (progress
    feedback: the eval is busy, we're still trying). Concurrently that
    multiplies — the targets start together and every attempt costs the same
    timeout, so a wedged eval set produces one line per target per attempt.
    Sharing one narrator across a fan-out collapses each round to a single
    line, named for the fan-out (``what``) rather than for whichever target
    happened to get there first, which is not stable across backends.
    """

    def __init__(self, what: str) -> None:
        self._what = what
        self._narrated: set[int] = set()

    def narrate(self, attempt: int, attempts: int) -> None:
        if attempt in self._narrated:
            return
        self._narrated.add(attempt)
        _echo_busy_attempt(self._what, attempt, attempts)


def _echo_busy_attempt(what: str, attempt: int, attempts: int) -> None:
    """Report one timed-out attempt (stderr, so ``--json`` stdout stays clean)."""
    retrying = "; retrying…" if attempt < attempts else "."
    _echo(
        f"{what}: no response after {_REQUEST_TIMEOUT:.0f}s "
        f"(attempt {attempt}/{attempts}) — the eval may be busy{retrying}",
        err=True,
    )


async def _get_response_with_retry_async(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    method: Literal["get", "post", "patch"] = "get",
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
    narrator: _BusyNarrator | None = None,
) -> httpx.Response:
    """Request ``path`` over the UDS, retrying a read timeout.

    Retries a read timeout up to ``attempts`` times, printing a status to the
    console (stderr, so ``--json`` stdout stays clean) on each — the eval is
    most likely just busy. On exhaustion, raises :class:`_ServerBusy` when
    ``raise_on_busy`` is set — handing the caller the terminal outcome (a
    fan-out warns and skips the busy eval, a supplemental read degrades in
    place, a scoped read exits with a targeted error), along with its
    narration — otherwise prints an error and exits non-zero, with the
    :func:`_anomalies_pointer` escalation on stderr (scoped to ``pid`` when
    the caller knows the target process — pass it whenever it's at hand, so
    the pointer doesn't suggest scanning every process after a narration
    that named one).
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
    to handle a meaningful status (eg. a 404) can;
    :func:`_get_with_retry_async` is the JSON-decoding wrapper for the common
    case.

    Async so a fan-out over many evals can issue its reads concurrently (see
    :func:`_read_all_task_rows` / :func:`_read_all_eval_samples`); single-read
    call sites use the :func:`_get_response_with_retry` sync facade. A fan-out
    passes a shared ``narrator`` so the retry narration below reports each
    attempt once for the invocation rather than once per target (see
    :class:`_BusyNarrator`).
    """
    if attempts is None:
        attempts = _DEGRADED_READ_ATTEMPTS if raise_on_busy else _REQUEST_ATTEMPTS
    transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
    last_timeout: httpx.TimeoutException | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                timeout=_REQUEST_TIMEOUT,
            ) as client:
                return await client.request(method, path, params=params or {})
        except httpx.TimeoutException as exc:
            last_timeout = exc
            if narrator is not None:
                narrator.narrate(attempt, attempts)
            else:
                _echo_busy_attempt(what, attempt, attempts)
        except (httpx.HTTPError, OSError) as exc:
            raise _ServerUnreachable() from exc
    if raise_on_busy:
        raise _ServerBusy(
            f"no response after {attempts} attempts — the eval's event loop is busy",
            last_timeout=last_timeout,
        )
    _exit_busy(what, attempts, last_timeout=last_timeout, pid=pid)


def _exit_busy(
    what: str,
    attempts: int,
    *,
    last_timeout: httpx.TimeoutException | None,
    pid: int | None,
) -> NoReturn:
    """Narrate a read that stayed busy through its retries, and fail the command.

    The terminal half of the busy policy, split out so a fan-out can raise it
    **once** for the whole invocation: its per-target reads take the
    ``raise_on_busy`` path (which doesn't narrate), so a run where every
    process is wedged reports one failure naming one pid, rather than one per
    process — the reads are concurrent, so without this they would all reach
    their deadline together and each print its own terminal error.
    """
    message = (
        f"{what}: gave up after {attempts} attempts of "
        f"{_REQUEST_TIMEOUT:.0f}s each — the eval's event loop is busy; "
        "try again shortly."
    )
    _echo(message, err=True)
    _echo(f"{_anomalies_pointer(pid)}.", err=True)
    raise _CtlFailure(
        "busy",
        message,
        exception=_exception_name(last_timeout) if last_timeout else None,
    )


def _run_async(func: Callable[[], Awaitable[_T]]) -> _T:
    """Run one control-channel coroutine to completion from sync CLI code.

    The ctl commands are synchronous click callbacks, so every async read
    bottoms out here. Never call this (or the sync facades built on it) from
    async code — it starts its own event loop; a fan-out awaits the ``_async``
    form directly instead.
    """
    return anyio.run(func, backend=configured_async_backend())


async def _collect_reads(reads: list[Callable[[], Awaitable[_T]]]) -> list[_T]:
    """Run a fan-out's reads concurrently, in input order, capped in flight.

    The cap (:data:`_MAX_CONCURRENT_READS`) is what keeps "issue the reads
    together" from meaning "issue all of them at once" — see the constant for
    why the ceiling costs nothing and the absence of one does.
    """
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def limited(read: Callable[[], Awaitable[_T]]) -> _T:
        async with limiter:
            return await read()

    return await tg_collect([functools.partial(limited, read) for read in reads])


def _get_response_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    method: Literal["get", "post", "patch"] = "get",
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
) -> httpx.Response:
    """Sync facade over :func:`_get_response_with_retry_async` — see it for policy."""
    return _run_async(
        functools.partial(
            _get_response_with_retry_async,
            socket_path,
            path,
            params=params,
            what=what,
            method=method,
            raise_on_busy=raise_on_busy,
            attempts=attempts,
            pid=pid,
        )
    )


async def _get_with_retry_async(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
    narrator: _BusyNarrator | None = None,
) -> Any:
    """GET ``path`` and return its decoded JSON, retrying a busy eval on timeout.

    Wraps :func:`_get_response_with_retry_async` (``raise_on_busy``,
    ``attempts``, ``pid``, and ``narrator`` ride through, including the
    attempts-from-raise_on_busy default); a non-2xx status or undecodable body
    raises :class:`_ServerUnreachable` (a server-side ``500`` or malformed
    response is not retryable). For endpoints with a meaningful 4xx, call
    :func:`_get_response_with_retry_async` directly and inspect the status.
    """
    response = await _get_response_with_retry_async(
        socket_path,
        path,
        params=params,
        what=what,
        raise_on_busy=raise_on_busy,
        attempts=attempts,
        pid=pid,
        narrator=narrator,
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

    Without ``stop_on_task_id`` the reads run concurrently (see
    :func:`_read_all_task_rows`); rows, and the skip warnings below, still
    follow discovery order.
    """
    # Every read takes the raise_on_busy path so none of them narrates its own
    # terminal error; when the caller wanted exit-on-busy, the first busy
    # server in discovery order raises for the whole invocation below.
    attempts = (
        _REQUEST_ATTEMPTS
        # a sole server is no fan-out — there's no wedged sibling to protect
        # against, so ride out a stall on the full budget
        if not raise_on_busy or len(servers) == 1
        else _DEGRADED_READ_ATTEMPTS
    )
    reads = _run_async(
        functools.partial(
            _read_all_task_rows,
            servers,
            attempts=attempts,
            stop_on_task_id=stop_on_task_id,
        )
    )
    summaries: list[dict[str, Any]] = []
    busy_pids: list[int] = []
    for server, rows in reads:
        if isinstance(rows, _ServerUnreachable):
            # a 404 means the process is serving a control API without this
            # route — version skew between the CLI and the eval process —
            # where transport errors mean the process is gone
            cause = rows.__cause__
            if isinstance(rows, _ServerBusy):
                if not raise_on_busy:
                    _exit_busy(
                        f"Reading tasks from pid {server.pid}",
                        attempts,
                        last_timeout=rows.last_timeout,
                        pid=server.pid,
                    )
                busy_pids.append(server.pid)
                hint = f"try again shortly, or {_anomalies_pointer(server.pid)}"
            elif (
                isinstance(cause, httpx.HTTPStatusError)
                and cause.response.status_code == 404
            ):
                hint = "it may be running a different inspect version than this CLI"
            else:
                hint = "it may have just exited"
            _echo(
                f"Skipping pid {server.pid}: its control endpoint could not be "
                f"read ({_unreachable_detail(rows)}) — {hint}.",
                err=True,
            )
            continue
        # Decorate each row with discovery-side info the server doesn't see
        # (pid, socket_path).
        for row in rows:
            row["pid"] = server.pid
            row["socket_path"] = str(server.socket_path)
        summaries.extend(rows)
    return _FetchedSummaries(summaries=summaries, busy_pids=busy_pids)


class _ServerRead(NamedTuple):
    """One server's ``/tasks`` read outcome (see :func:`_read_task_rows`).

    ``rows`` is the decoded payload, or the :class:`_ServerUnreachable` that
    replaced it — captured rather than raised because the reads run
    concurrently, and an exception escaping into the task group would cancel
    its siblings where the policy is per-server warn-and-skip. A payload that
    isn't a list (a malformed server) is normalized to no rows, which is how
    it was already treated.
    """

    server: DiscoveredControlServer
    rows: list[dict[str, Any]] | _ServerUnreachable


async def _read_task_rows(
    server: DiscoveredControlServer,
    *,
    attempts: int,
    narrator: _BusyNarrator | None,
) -> _ServerRead:
    """Read one server's ``/tasks`` rows, capturing an unreachable/busy failure."""
    try:
        rows = await _get_with_retry_async(
            server.socket_path,
            "/tasks",
            what=f"Reading tasks from pid {server.pid}",
            raise_on_busy=True,
            attempts=attempts,
            pid=server.pid,
            narrator=narrator,
        )
    except _ServerUnreachable as exc:
        return _ServerRead(server, exc)
    return _ServerRead(server, rows if isinstance(rows, list) else [])


async def _read_all_task_rows(
    servers: list[DiscoveredControlServer],
    *,
    attempts: int,
    stop_on_task_id: str | None,
) -> list[_ServerRead]:
    """Read every discovered server's ``/tasks`` rows, in discovery order.

    Concurrently by default: the per-read cost is dominated by round-trip and
    connection setup rather than server work, so a serial loop cost that
    round-trip once per process and made an unscoped listing over a large
    eval set look wedged.
    """
    read = functools.partial(
        _read_task_rows,
        attempts=attempts,
        # concurrent reads stall in lockstep, so they share one narrator; the
        # serial branch below narrates per server, as a lone read does
        narrator=_BusyNarrator(f"Reading tasks from {len(servers)} processes")
        if stop_on_task_id is None and len(servers) > 1
        else None,
    )
    if stop_on_task_id is None:
        return await _collect_reads(
            [functools.partial(read, server) for server in servers]
        )
    # The short-circuit decides whether to contact the next server from the
    # last one's rows, so it stays serial. It runs for any scoped (single-task)
    # selector — whether a query is the exact id that can actually stop early
    # is only knowable from the rows — so a name or prefix selector pays the
    # serial cost for a stop that never comes. Kept because contacting the
    # servers an exact id skips could make that read *slower*, by waiting out
    # an unrelated wedged process's retry budget.
    reads: list[_ServerRead] = []
    for server in servers:
        result = await read(server)
        reads.append(result)
        if not isinstance(result.rows, _ServerUnreachable) and any(
            row.get("task_id") == stop_on_task_id for row in result.rows
        ):
            break
    return reads


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
            _echo(
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
        _echo(
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
    _echo(f"{prefix} — pass a task id to choose one:\n", err=True)
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


def _exit_samples_unreachable(
    eval_id: str, exc: _ServerUnreachable, *, pid: int | None = None
) -> NoReturn:
    """Echo a samples-read failure for ``eval_id`` and exit non-zero.

    A busy failure adds the :func:`_anomalies_pointer` escalation (``pid``
    names the busy process) on stderr only — the envelope message stays
    hint-free.
    """
    # the period rides the hint: a non-busy detail is a raw transport error
    # string (multi-line, may end in a URL) that punctuation would corrupt
    hint = "; try again shortly." if isinstance(exc, _ServerBusy) else ""
    message = (
        f"Failed to read samples for eval {eval_id}: {_unreachable_detail(exc)}{hint}"
    )
    _echo(message, err=True)
    if isinstance(exc, _ServerBusy):
        _echo(f"{_anomalies_pointer(pid)}.", err=True)
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


async def _fetch_samples_async(
    socket_path: str,
    eval_id: str,
    active_since: float | None = None,
    *,
    sample_filter: Literal["errors"] | None = None,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    attempts: int | None = None,
    narrator: _BusyNarrator | None = None,
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
    :func:`_get_response_with_retry_async`); the caller owns the outcome:
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
    if content:
        params["content"] = True
    page = await _get_with_retry_async(
        socket_path,
        f"/evals/{eval_id}/samples",
        params=params,
        what=f"Reading samples for eval {eval_id}",
        raise_on_busy=True,
        attempts=attempts,
        narrator=narrator,
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


def _fetch_samples(
    socket_path: str,
    eval_id: str,
    active_since: float | None = None,
    *,
    sample_filter: Literal["errors"] | None = None,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    attempts: int | None = None,
) -> _SamplesPage:
    """Sync facade over :func:`_fetch_samples_async` — see it for policy."""
    return _run_async(
        functools.partial(
            _fetch_samples_async,
            socket_path,
            eval_id,
            active_since,
            sample_filter=sample_filter,
            status=status,
            limit=limit,
            all_samples=all_samples,
            content=content,
            attempts=attempts,
        )
    )


def _fetch_sample_detail(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    content: bool = False,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a single sample's summary + error detail.

    The one read behind ``sample show`` — the response carries the summary
    fields (timing / tokens / messages) alongside the error history, so no
    supplemental listing fetch is needed. ``content`` opts into the error
    free text (withheld by default). It rides the full narrated
    busy-retry policy rather than failing on a momentary event-loop stall;
    ``pid`` scopes that policy's exhaustion pointer to the hosting process.
    """
    # sample_id goes in the query string (httpx URL-encodes it) so ids
    # containing `/`, `?`, `#`, etc. address correctly — they can't be
    # carried as a path segment.
    return _request_json(
        socket_path,
        f"/evals/{eval_id}/sample",
        params={"sample_id": sample_id, "epoch": epoch, "content": content},
        what=f"sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "still be running or not yet written to the log."
        ),
        pid=pid,
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
    content: bool,
    full: bool,
    since_time: float | None,
    until: float | None,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a page of a sample's transcript events.

    The authoritative read behind ``sample events``: like the sample detail
    read, it rides the full narrated busy-retry policy rather than failing on
    a momentary event-loop stall; ``pid`` scopes that policy's exhaustion
    pointer to the hosting process.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply. The
    # wire parameter for the cursor is `since` (the CLI flag is --cursor).
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "content": content,
        "full": full,
    }
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
        pid=pid,
    )


_MESSAGES_ROUTE_MISSING = (
    "This process is running an older inspect without the sample "
    "messages endpoint; restart the eval to pick up the current version."
)


def _fetch_sample_messages(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    tail: int | None,
    content: bool,
    full: bool,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a snapshot of a sample's conversation.

    The authoritative read behind ``sample messages``: like the sample detail
    and events reads, it rides the full narrated busy-retry policy rather than
    failing on a momentary event-loop stall; ``pid`` scopes that policy's
    exhaustion pointer to the hosting process.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply.
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "content": content,
        "full": full,
    }
    if tail is not None:
        params["tail"] = tail
    return _request_json(
        socket_path,
        f"/evals/{eval_id}/sample/messages",
        params=params,
        what=f"messages for sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "not have started or not yet been written to the log."
        ),
        not_found_missing_route=_MESSAGES_ROUTE_MISSING,
        pid=pid,
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
    pid: int | None = None,
    echo_failures: bool = True,
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

    ``pid`` scopes the retry-exhaustion escalation pointer to the target
    process (see :func:`_get_response_with_retry`) — pass it when the caller
    has already resolved one.

    ``echo_failures=False`` suppresses the stderr echo that normally precedes
    each raised :class:`_CtlFailure` — for callers that catch the failure and
    render it themselves (the bulk-requeue sweep records per-sample
    rejections in its stdout report; echoing here too would print every
    rejection twice). Such callers take over the raiser-echoes contract: any
    failure they re-raise instead of recording must be echoed first.
    """
    verb = "update" if mutate else "read"

    def fail(
        kind: _ErrorKind,
        message: str,
        *,
        status: int | None = None,
        missing_route: bool = False,
    ) -> NoReturn:
        if echo_failures:
            _echo(message, err=True)
        raise _CtlFailure(kind, message, status=status, missing_route=missing_route)

    try:
        if mutate is not None and retry_mutation:
            response = _get_response_with_retry(
                socket_path,
                path,
                params=params,
                what=f"Updating {what}",
                method=mutate,
                pid=pid,
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
                socket_path, path, params=params, what=f"Reading {what}", pid=pid
            )
        if response.status_code == 404:
            if not_found_missing_route is not None and not _handler_404(response):
                fail(
                    "not_found",
                    not_found_missing_route,
                    status=404,
                    missing_route=True,
                )
            fail("not_found", not_found, status=404)
        if response.status_code == 400:
            fail(
                "invalid_request",
                f"Invalid request: {_error_detail_from_response(response)}",
                status=400,
            )
        response.raise_for_status()
        result = response.json()
    except _ServerUnreachable as exc:
        message = f"{_failure_prefix(verb, what)}{_unreachable_detail(exc)}"
        if echo_failures:
            _echo(message, err=True)
        raise _unreachable_failure(message, exc) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        message = f"{_failure_prefix(verb, what)}{_error_detail(exc)}"
        if echo_failures:
            _echo(message, err=True)
        raise _CtlFailure.from_exception(message, exc) from exc
    return result if isinstance(result, dict) else {}


def _failure_prefix(verb: str, what: str) -> str:
    """The context prefix :func:`_request_json` puts on failure messages.

    The bulk-requeue human rendering strips this prefix from recorded
    per-sample errors (the label it restates is already on the line), so the
    format lives here rather than inline to keep the two sides in lockstep.
    """
    return f"Failed to {verb} {what}: "


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


def _post_flush(
    socket_path: str, task_id: str, *, pid: int | None = None
) -> dict[str, Any]:
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
        pid=pid,
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
    _echo(
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
        _echo(
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
    time_limit: int | Literal["clear"] | None = None,
    token_limit: int | Literal["clear"] | None = None,
    message_limit: int | Literal["clear"] | None = None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    author: str | None = None,
    reason: str | None = None,
    pid: int | None = None,
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
    ``attempt_timeout`` / ``max_retries``) and the per-sample limit
    overrides (``time_limit`` / ``token_limit`` / ``message_limit``,
    task-scoped) accept the keyword ``clear`` to
    remove an override (``0`` is a real value for them). Any settable knob
    that is not ``None`` makes this a mutation: a single-shot PATCH given the
    full mutation budget (see :data:`_MUTATION_TIMEOUT`) — derived here, not
    caller-supplied, so a knob can never ride a GET as an ignored query
    param. A pure read is a GET that retries a busy process on timeout;
    ``pid`` scopes that policy's exhaustion pointer to the target process.
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
        "time_limit": time_limit,
        "token_limit": token_limit,
        "message_limit": message_limit,
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
        pid=pid,
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
        _echo("would-be config (dry run):" if dry_run else "updated config:")
    else:
        _echo("config:")

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
        _echo(_knob_label("max samples", "max_samples") + _PER_TASK_PLACEHOLDER)
    else:
        max_samples = knobs.get("max_samples") or {}
        if max_samples.get("adjustable"):
            limit = _target(max_samples.get("limit"), "max_samples")
            in_use = max_samples.get("in_use")
            label = _knob_label("max samples", "max_samples")
            _echo(f"{label}{limit} ({in_use} in use)")
        elif max_samples.get("tracks_adaptive"):
            # sample concurrency tracks this task's adaptive controller, so
            # there's no user setpoint to show — point at where the numbers are
            _echo(
                _knob_label("max samples", "max_samples")
                + "tracks adaptive connections (see below)"
            )
        else:
            # no live sample limiter for this task (e.g. a reused log) — the
            # adaptive block below, if any, belongs to other tasks' models
            _echo(
                _knob_label("max samples", "max_samples")
                + "not adjustable (no live sample limiter)"
            )

    sandboxes = (knobs.get("max_sandboxes") or {}).get("providers") or []
    if sandboxes:
        rendered = ", ".join(
            f"{s.get('type')} {_target(s.get('limit'), 'max_sandboxes')} ({s.get('in_use')} in use)"
            for s in sandboxes
        )
        _echo(f"{_knob_label('max sandboxes', 'max_sandboxes')}{rendered}")
    else:
        _echo(_knob_label("max sandboxes", "max_sandboxes") + "none in effect")

    subprocesses = knobs.get("max_subprocesses") or {}
    if subprocesses.get("limit") is not None:
        limit = _target(subprocesses.get("limit"), "max_subprocesses")
        _echo(
            f"{_knob_label('max subprocesses', 'max_subprocesses')}{limit} "
            f"({subprocesses.get('in_use')} in use)"
        )
    else:
        _echo(
            _knob_label("max subprocesses", "max_subprocesses")
            + "inactive (no adjustable subprocess limiter yet)"
        )

    adaptive = (knobs.get("max_connections") or {}).get("adaptive") or []
    if adaptive:
        _echo(f"  adaptive connections [{_KNOB_SCOPE['max_connections']}]:")
        for a in adaptive:
            # on a dry-run set, `_target` renders the ceiling as `max → requested`
            ceiling = _target(a.get("max"), "max_connections")
            # sanitize the name before composing so a swallow in it can't
            # eat the line's data fields (`_echo` handles the rest)
            name = _sanitize_line(str(a.get("name") or ""))
            line = (
                f"    {name}: {a.get('limit')} ({a.get('in_use')} in use), "
                f"range {a.get('min')}–{ceiling}"
            )
            changes = a.get("recent_changes") or []
            if changes:
                last = changes[-1]
                line += (
                    f", last: {last.get('from')}→{last.get('to')} {last.get('reason')}"
                )
            _echo(line)

    # The retry-override knobs. Absent entirely from an older server's view
    # (which has no override layer) — skipped then rather than shown as a
    # value claim. A knob's current value is the live override or "launch
    # config" (no override — each generate call's own config applies); on a
    # dry-run the requested value renders as an arrow, with `clear` shown as
    # its meaning (back to launch config).
    def _render_override_knob(knob: str, display: str, unit: str) -> None:
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
        _echo(_knob_label(display, knob) + rendered)

    _render_override_knob("timeout", "timeout", "s")
    _render_override_knob("attempt_timeout", "attempt timeout", "s")
    _render_override_knob("max_retries", "max retries", "")

    # The per-sample limit overrides — task-scoped, so a process-level view
    # can't show them: mirror the max_samples placeholder there (keeping the
    # knobs discoverable), while a task view missing them means an older
    # server (skipped, like the retry knobs — no value claim to make).
    process_scope = (config.get("target") or {}).get("scope") == "process"
    for knob, display, unit in (
        ("time_limit", "time limit", "s"),
        ("token_limit", "token limit", ""),
        ("message_limit", "message limit", ""),
    ):
        if knob in knobs:
            _render_override_knob(knob, display, unit)
        elif process_scope:
            _echo(_knob_label(display, knob) + _PER_TASK_PLACEHOLDER)

    # The named concurrency() registry entries, addressable via `--key` by the
    # exact name shown. Entries appear lazily on first use, so an empty
    # registry gets a placeholder (like the sibling knobs) that keeps the
    # knob discoverable and distinguishes it from an older server whose view
    # omits the section (`keys` is None).
    keys = (knobs.get("concurrency") or {}).get("keys")
    if keys:
        _echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]:")
        for row in keys:
            # on a dry-run set, `_target` renders the requested key's limit as
            # `current → requested` (the request rides `concurrency:<name>`)
            limit = _target(row.get("limit"), f"concurrency:{row.get('name')}")
            # concurrency() names are arbitrary registry strings; sanitize
            # before composing so a swallow can't eat the line's data fields
            name = _sanitize_line(str(row.get("name") or ""))
            line = f"    {name}: {limit} ({row.get('in_use')} in use)"
            if not row.get("adjustable"):
                line += " — not adjustable"
            _echo(line)
    else:
        empty = (
            "none registered yet (named limits appear on first use)"
            if keys is not None
            else "not reported (older server)"
        )
        _echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]: {empty}")

    # The process-level view carries no buffer knobs (they're per-task, read
    # off one task's live logger): mirror the max_samples placeholder so the
    # knobs' existence — and how to see them — stays visible. A *task* view
    # missing them (no live buffer) is reported via warnings instead.
    if "log_buffer" in knobs:
        log_buffer = knobs.get("log_buffer") or {}
        value = _target(log_buffer.get("value"), "log_buffer")
        _echo(
            f"{_knob_label('log buffer', 'log_buffer')}{value} samples "
            f"({log_buffer.get('pending')} pending)"
        )
    elif process_scope:
        _echo(_knob_label("log buffer", "log_buffer") + _PER_TASK_PLACEHOLDER)
    if "log_shared" in knobs:
        shared = (knobs.get("log_shared") or {}).get("value")
        rendered_shared = _target(shared, "log_shared") if shared is not None else None
        _echo(
            _knob_label("shared sync", "log_shared")
            + f"{f'{rendered_shared}s' if rendered_shared is not None else 'off'}"
        )
    elif process_scope:
        _echo(_knob_label("shared sync", "log_shared") + _PER_TASK_PLACEHOLDER)

    for warning in config.get("warnings") or []:
        _echo(f"  ! {warning}")
    for note in config.get("notes") or []:
        _echo(f"  note: {note}")


def _events_carry_content(events: list[dict[str, Any]]) -> bool:
    """True when a compact events page came back with free-text fields.

    The withheld-content footers key on the response, not the request: a
    pre-v6 server ignores the unknown ``content`` query param and returns
    the old content-bearing projection, and a "metadata only" footer must
    not contradict text printed right above it. The listed keys are emitted
    by ``events._project`` only under ``content`` (v6+) and unconditionally
    on the typed branches before v6, so their presence means content came
    back; a page of header-only events has no signal, but then the footer
    claims nothing false either.
    """
    fields = ("completion", "arguments", "result", "error", "data")
    return any(field in event for event in events for field in fields)


def _print_events(page: dict[str, Any], *, content: bool, full: bool) -> None:
    """Render a page of transcript events (table) plus a cursor footer.

    The metadata-only footer is response-keyed (see
    :func:`_events_carry_content`).
    """
    events = page.get("events") or []
    if full:
        # Raw mode is for machine consumption; the human rendering is the
        # compact projection (whose flattened fields the table expects), so
        # just pretty-print the raw events.
        _echo_raw(json_lib.dumps(events, indent=2))
    elif not events:
        _echo("(no events)")
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
    if not full and not content and not _events_carry_content(events):
        parts.append("metadata only (pass --content for text)")
    _echo()
    _echo("  ·  ".join(parts))
    nxt = page.get("next")
    if nxt and not page.get("done"):
        _echo(f"next: {_sanitize_line(str(nxt))}  (resume with --cursor)")


def _print_messages(page: dict[str, Any], *, content: bool, full: bool) -> None:
    """Render a conversation snapshot (per-message rows) plus a count footer.

    The metadata-only footer is response-keyed, like the events one (see
    :func:`_events_carry_content`): a ``content`` key on any message means a
    pre-v6 server returned the old always-content projection, so the footer
    would contradict the table above it.
    """
    messages = page.get("messages") or []
    count = int(page.get("count") or 0)
    status = page.get("status")

    if full:
        # Raw mode is for machine consumption; the human rendering is the
        # compact projection, so just pretty-print the raw messages.
        _echo_raw(json_lib.dumps(messages, indent=2))
    elif not messages:
        _echo("(no messages)")
    else:
        rows: list[tuple[str, ...]] = []
        for m in messages:
            rows.append(
                (
                    str(m.get("index", "")),
                    str(m.get("role", "") or ""),
                    _message_summary(m),
                )
            )
        _render_table(("#", "role", "content"), rows)

    shown = len(messages)
    footer = f"{shown} of {count} message" + ("" if count == 1 else "s")
    if shown < count:
        footer += " (use --all for the whole conversation)"
    if status:
        footer += f"  ·  {_sanitize_line(str(status))}"
    if not full and not content and not any("content" in m for m in messages):
        footer += "  ·  metadata only (pass --content for text)"
    _echo()
    _echo(footer)


def _message_summary(m: dict[str, Any]) -> str:
    """One-line summary for a message row (best-effort over compact fields).

    Tolerates the metadata-only projection (no content / arguments / error
    text): tool calls render as bare function names, a tool message as its
    function, and a withheld error as a bare ``error`` marker.

    Every wire field is sanitized at its interpolation site (provenance is
    irrelevant — see ``_sanitize_control``) so an unterminated string
    sequence in one (e.g. the message content) can't swallow the parts
    appended after it — the tool-call list or the ``error:`` tag.
    """
    parts = [_sanitize_control(str(m.get("content") or ""))]
    if m.get("role") == "tool" and "content" not in m and m.get("function"):
        parts.append(f"[{_sanitize_control(str(m['function']))} output]")
    for call in m.get("tool_calls") or []:
        arguments = (
            _truncate(str(call["arguments"]), 30) if call.get("arguments") else ""
        )
        parts.append(
            f"→ {_sanitize_control(str(call.get('function') or '?'))}({arguments})"
        )
    if m.get("error"):
        parts.append(f"error: {_sanitize_control(str(m['error']))}")
    elif m.get("has_error"):
        parts.append("error")
    return _truncate("  ".join(p for p in parts if p), 100)


def _event_summary(e: dict[str, Any]) -> str:
    """One-line summary for an event row (best-effort over compact fields).

    A pending (in-flight) event renders its live state — ``generating M:SS``
    for a model call, ``running M:SS`` for a tool call — instead of the
    completion fields, whose placeholder values (zero tokens, a default stop
    reason) would read as "finished with nothing". Tolerates the
    metadata-only projection (no completion / arguments / result / error
    text): a withheld model/tool error renders as a bare ``error`` marker,
    while an ``error``-type event renders an empty summary (its type column
    already reads ``error``, so a marker would only duplicate it).

    Every wire field is sanitized at its interpolation site (provenance is
    irrelevant — see ``_sanitize_control``) so an unterminated string
    sequence in one can't swallow the fields appended after it within the
    summary.
    """
    t = e.get("event")
    if t == "model":
        bits = [_sanitize_control(str(e.get("model") or ""))]
        if e.get("pending"):
            bits.append(_format_pending("generating", e.get("timestamp")))
            return _truncate(" · ".join(b for b in bits if b), 80)
        if e.get("tokens") is not None:
            bits.append(f"{e['tokens']} tok")
        if e.get("stop_reason"):
            bits.append(_sanitize_control(str(e["stop_reason"])))
        if e.get("completion"):
            bits.append(_sanitize_control(str(e["completion"])))
        if e.get("error"):
            bits.append(f"error: {_sanitize_control(str(e['error']))}")
        elif e.get("has_error"):
            bits.append("error")
        return _truncate(" · ".join(b for b in bits if b), 80)
    if t == "tool":
        arguments = _truncate(str(e["arguments"]), 30) if e.get("arguments") else ""
        s = f"{_sanitize_control(str(e.get('function') or '?'))}({arguments})"
        if e.get("pending"):
            s += f" · {_format_pending('running', e.get('timestamp'))}"
        elif e.get("error"):
            s += f" → error: {_sanitize_control(str(e['error']))}"
        elif e.get("has_error"):
            s += " → error"
        elif e.get("result"):
            s += f" → {_truncate(str(e['result']), 40)}"
        return _truncate(s, 80)
    if t == "error":
        return _truncate(str(e.get("error") or ""), 80)
    if t == "info":
        bits = [
            _sanitize_control(str(e.get("source") or "")),
            _sanitize_control(str(e.get("data") or "")),
        ]
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
    activity = _format_activity(
        detail.get("activity"), datetime.now(timezone.utc).timestamp()
    )
    if activity:
        parts.append(activity)
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
        # sanitize each k=v pair before joining so an unterminated string
        # sequence in one score value can't swallow the scores after it
        parts.append(
            "score "
            + ", ".join(
                _sanitize_control(f"{k}={_format_score(v)}") for k, v in scores.items()
            )
        )
    # sanitize each part separately so an unterminated string sequence in one
    # can't swallow the fields joined after it, and flatten newlines so one
    # part can't forge a plausible header line of its own; filter on the
    # sanitized value so a part that was all control bytes doesn't leave a
    # dangling separator
    sanitized_parts = (_sanitize_line(p) for p in parts)
    _echo("  ·  ".join(p for p in sanitized_parts if p))

    # `is not None`, not truthiness: a metadata-only read (no --content)
    # carries a present-but-withheld error as an *empty* dict
    error = detail.get("error")
    retries = detail.get("error_retries") or []
    if error is None and not retries:
        _echo("\n(no errors)")
        return

    if retries:
        _echo("\nprior attempts:")
        for i, retry_error in enumerate(retries, start=1):
            _echo_error(f"attempt {i}:", retry_error, show_traceback)
    if error is not None:
        _echo("\nfinal error:")
        _echo_error("", error, show_traceback)


def _echo_error(label: str, error: dict[str, Any], show_traceback: bool) -> None:
    """Echo one error: ``label  message`` plus an indented traceback if asked.

    A metadata-only detail (no ``--content``) carries each error as an empty
    dict — no ``message`` key at all — rendered as an explicit withheld
    marker rather than a blank line a reader would take for an empty message.
    """
    # flatten newlines so a crafted message can't print continuation lines at
    # column 0 that mimic surrounding output (full text remains via --json)
    message = (
        _sanitize_line(error.get("message") or "")
        if "message" in error
        else "(message withheld — pass --content to include it)"
    )
    _echo(f"  {label} {message}".rstrip() if label else f"  {message}")
    if show_traceback:
        traceback_ansi = error.get("traceback_ansi")
        if traceback_ansi:
            tb = _sanitize_keep_sgr(traceback_ansi)
        else:
            tb = _sanitize_control(error.get("traceback") or "")
        for line in tb.rstrip("\n").splitlines():
            # raw: `_echo` would strip the SGR styling `_sanitize_keep_sgr` kept
            _echo_raw(f"    {line}")


def _format_pending(verb: str, timestamp: Any) -> str:
    """In-flight marker for a pending event's summary: ``generating M:SS``."""
    elapsed = (
        _format_duration(datetime.now(timezone.utc).timestamp() - timestamp)
        if isinstance(timestamp, (int, float))
        else ""
    )
    return f"{verb} {elapsed}".rstrip()


# Well-formed ANSI escape sequences, removed whole so their printable payload
# (e.g. the `0;title` of an OSC title write) doesn't survive as stray text:
# CSI (params + intermediates + final byte), the string sequences (OSC and
# DCS/SOS/PM/APC — BEL-, ST-, or raw-C1-ST-terminated, tolerating an
# unterminated tail), charset designations, then any other two-byte ESC
# sequence.
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[\]PX^_][^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"  # OSC/DCS/SOS/PM/APC
    r"|\x1b[()*+./-][0-~]"  # charset designations
    r"|\x1b."  # C1 aliases, keypad modes, etc.
)

# Remaining C0 controls (newline and tab excepted — handled by callers and
# `_sanitize_control` respectively), DEL, raw 8-bit C1 controls, and Unicode
# bidi controls (ALM, LRM/RLM, embeddings/overrides, isolates): on
# BiDi-aware terminals (VTE, mintty) an RLO in one table cell visually
# reorders the rest of the physical line, trusted columns included (cf.
# Trojan Source, CVE-2021-42574). Costs explicit direction marks in
# legitimate RTL output — the right trade for a triage CLI.
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f"
    r"\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


def _sanitize_control(text: str) -> str:
    """Neutralize terminal control bytes in display text.

    Tool results and model completions land verbatim in the transcript and
    flow out through the read commands' human renderings, so a sample under
    evaluation can emit ESC/CSI/OSC sequences, carriage returns, or
    backspaces that rewrite what the operator's terminal shows (spoofed
    results, title/clipboard writes). Rather than classify which fields an
    agent can influence — a provenance analysis that silently rots as
    fields are added — the human rendering paths sanitize *every* dynamic
    string at its formatting boundary (table cells, summary/label
    interpolations, joined header parts, echoed status lines). The function
    is a no-op on clean text and idempotent, so blanket application costs
    nothing; where several fields join into one line, each is sanitized
    before the join so an unterminated string sequence in one can't swallow
    the fields after it.

    Well-formed escape sequences are removed whole (payload included), tabs
    become single spaces (they'd break the tables' width math), and any
    remaining C0/C1 control byte or Unicode bidi control is dropped —
    newline excepted: single-line renderings flatten it via
    ``_sanitize_line``, multi-line ones (tracebacks) keep it. The
    ``--json`` / ``--full`` machine paths are deliberately not routed
    through here (``json.dumps`` escapes control bytes);
    ``traceback_ansi`` goes through ``_sanitize_keep_sgr``, which
    preserves SGR styling and routes everything else through this
    function.
    """
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _CONTROL_CHARS_RE.sub("", text.replace("\t", " "))


def _sanitize_line(text: str) -> str:
    """``_sanitize_control`` plus newline flattening, for one-line renderings.

    Any field interpolated into a single-line rendering — a table cell, a
    joined header part, a status/reason echo — flattens embedded newlines to
    spaces so the field can't print a forged line of its own at column 0.
    Multi-line renderings (tracebacks) use ``_sanitize_control`` directly.
    """
    return _sanitize_control(text).replace("\n", " ")


# SGR (color/style) sequences — the one escape class rich's own tracebacks
# legitimately contain, and inert on their own (they can restyle, never
# rewrite or exfiltrate).
_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def _sanitize_keep_sgr(text: str) -> str:
    """`_sanitize_control`, but preserving SGR color/style sequences.

    For ``traceback_ansi``: usually Inspect's own rich rendering (SGR-only
    styling worth keeping), but it falls back to raw, un-rendered text for
    oversized tracebacks and in recovered logs — and a traceback embeds
    agent-influenced exception text — so everything except SGR is
    neutralized rather than trusted wholesale. Kept styling is closed with
    a trailing reset: a raw fallback can end mid-style (even an SGR 8
    conceal), which would otherwise bleed into subsequent trusted output.
    """
    out: list[str] = []
    last = 0
    for m in _SGR_RE.finditer(text):
        out.append(_sanitize_control(text[last : m.start()]))
        out.append(m.group())
        last = m.end()
    out.append(_sanitize_control(text[last:]))
    result = "".join(out)
    if last:
        stripped = result.rstrip("\n")
        if not stripped.endswith("\x1b[0m"):
            result = stripped + "\x1b[0m" + result[len(stripped) :]
    return result


def _echo(message: str = "", *, err: bool = False, nl: bool = True) -> None:
    """``click.echo`` with ``_sanitize_control`` applied — the module default.

    Every echoed line leaves through here so rendering code is sanitized by
    construction (see ``_sanitize_control`` for the policy) even when a
    call site misses a per-field wrap; ``_echo_raw`` is the explicit
    opt-out. A test walks this module's AST to keep direct ``click.echo``
    calls out of everything but these two wrappers.
    """
    click.echo(_sanitize_control(message), err=err, nl=nl)


def _echo_raw(message: str = "", *, err: bool = False, nl: bool = True) -> None:
    """``click.echo`` without sanitization.

    For machine output — the ``--json`` paths, which are bytes-faithful by
    contract (``json.dumps`` escapes control bytes itself) — and for the
    keep-SGR renderings (``traceback_ansi``, the anomalies export), whose
    deliberately kept styling ``_echo`` would strip.
    """
    click.echo(message, err=err, nl=nl)


def _truncate(text: str, width: int) -> str:
    text = _sanitize_line(text)
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
    # Same "only when there is something to report" rule as errors/attempts. Zero
    # is the overwhelmingly common value for both, and a permanent pair of 0
    # columns would push the columns that always matter off a narrow terminal.
    # `or 0` also covers an older server, which reports neither key.
    any_refusals = any((s.get("refusals") or 0) > 0 for s in summaries)
    any_http_retries = any((s.get("http_retries") or 0) > 0 for s in summaries)
    # shown only when some task is paused (or holding samples — a hard model
    # pause can hold another task's grader calls without any latch source on
    # that row), so a paused run doesn't read as stalled (the cell names the
    # holding latch; `quiesced` = nothing left in flight — the safe-to-kill
    # signal)
    any_paused = any(s.get("paused") or s.get("held") for s in summaries)

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
        # Blank, not 0, when the key is absent — the same rule the samples table
        # uses for an unknown turn count. A row from an older server does not
        # report these, and printing 0 there would assert "none happened" about a
        # task that may well have had plenty. Only reachable in a mixed-version
        # fleet, which is exactly when a false zero would mislead.
        if any_refusals:
            cells.append(_format_count(s.get("refusals")))
        if any_http_retries:
            cells.append(_format_count(s.get("http_retries")))
        if any_paused:
            cells.append(_format_paused(s))
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
    if any_refusals:
        headers_list.append("refusals")
    if any_http_retries:
        # Spelled out rather than "retries": the `attempts` column is also a
        # retry count (of whole task attempts), and these are HTTP-level.
        headers_list.append("http_retries")
    if any_paused:
        headers_list.append("paused")
    headers_list.append("started")
    if any_retries:
        headers_list.append("attempts")

    _render_table(tuple(headers_list), rows)


def _format_count(value: Any) -> str:
    """A count cell: the number, or blank when the server didn't report it.

    ``None`` (key absent) and ``0`` (reported, nothing happened) are different
    claims and must not render the same way.
    """
    return "" if value is None else str(value)


def _format_paused(summary: dict[str, Any]) -> str:
    """The task's paused cell: the holding latch(es), plus quiesced when idle.

    Hard-holding latches (``pause --now``) render as ``task(now)``, and a
    nonzero held count (samples parked at their next model call) replaces
    the quiesced marker — the two can't co-occur (a held sample is still
    dispatched), and under a hard pause held, not quiesced, is the signal
    the operator acts on (a kill while ``held > 0`` forfeits in-sample
    progress). A row can be held with *no* latch sources of its own: the
    hard model gate keys on the model actually being called, so another
    task's ``model pause --now`` holds this task's grader/role calls to
    that model — render the held count alone rather than suppressing it.
    """
    held = int(summary.get("held") or 0)
    now = set(_paused_sources(summary.get("paused_now")))
    paused = "+".join(
        f"{source}(now)" if source in now else source
        for source in _paused_sources(summary.get("paused"))
    )
    if not paused:
        return f"({held} held)" if held else ""
    if held:
        return f"{paused} ({held} held)"
    return f"{paused} (quiesced)" if summary.get("quiesced") else paused


def _print_keep_alive_footer(summaries: list[dict[str, Any]]) -> None:
    """Print a one-line keep-alive status footer below the tasks table.

    Keep-alive is a per-process property — every task a process hosts shares
    it — so across all running tasks it's ``on`` (all park after their eval),
    ``off`` (none do), or ``mixed``. When it's off everywhere, hint at
    ``inspect ctl process keep``, which turns it on for a running process.
    """
    flags = [bool(s.get("keep_alive")) for s in summaries]
    _echo()
    if all(flags):
        _echo("keep-alive: on")
    elif not any(flags):
        _echo("keep-alive: off  ·  set with `inspect ctl process keep`")
    else:
        on = sum(flags)
        _echo(f"keep-alive: mixed ({on}/{len(flags)} on)")

    # flag paused work below the table (the per-row cell can scroll away and
    # a paused run must not read as stalled). A paused run never finishes —
    # either latch holds work the run awaits — so also surface the
    # exit-when-done contradiction when keep-alive is off for a paused row.
    paused = [s for s in summaries if s.get("paused")]
    # held (`--now`) samples counted across ALL rows, not just paused ones:
    # a hard model pause holds other tasks' grader calls to that model
    # without stamping a latch source on their rows
    held_samples = sum(int(s.get("held") or 0) for s in summaries)
    if paused:
        quiesced = sum(1 for s in paused if s.get("quiesced"))
        details = [
            part
            for part in (
                f"{quiesced} quiesced" if quiesced else "",
                f"{held_samples} held" if held_samples else "",
            )
            if part
        ]
        detail = f" ({', '.join(details)})" if details else ""
        # only the latches actually holding a paused task can resume it — a
        # task held solely by the model latch isn't freed by `task resume` or
        # `process resume`, so don't advertise them. Fixed order: task, model,
        # process.
        held = {src for s in paused for src in _paused_sources(s.get("paused"))}
        resumes = [
            f"`inspect ctl {latch} resume`"
            for latch in ("task", "model", "process")
            if latch in held
        ]
        _echo(
            f"paused: {len(paused)}/{len(summaries)} task"
            f"{'' if len(summaries) == 1 else 's'}{detail}  ·  resume with "
            f"{' / '.join(resumes)}"
        )
        if any(not s.get("keep_alive") for s in paused):
            _echo(
                "note: a paused run never finishes — it will not exit until "
                "resumed (or cancelled), despite keep-alive being off."
            )
    elif held_samples:
        # no paused rows, yet samples are parked at the generate gate (a
        # hard model pause whose primary tasks have no rows yet) — the
        # don't-kill-yet warning must still print
        _echo(
            f"held: {held_samples} sample{'' if held_samples == 1 else 's'} "
            "held at the next model call (`pause --now`) — killing now "
            "forfeits in-sample progress"
        )
    # latched models whose tasks are all still queued have no paused row
    # above (an unstarted task has no summary) — surface them from the
    # process-level stamp so the latch can't hold work invisibly
    paused_models = sorted(
        {m for s in summaries for m in (s.get("paused_models") or [])}
    )
    if paused_models:
        _echo(
            f"paused models: {', '.join(paused_models)}  ·  resume with "
            "`inspect ctl model resume`"
        )


def _print_errored_samples_footer(summaries: list[dict[str, Any]]) -> None:
    """Print a one-line errored-samples footer below the tasks table.

    Points at the triage command when any row reports errored samples.
    The count sums `samples.errored` across rows, which is deliberately
    narrower than the view it points at: `errored` counts latest-attempt
    errors only, while `sample errors` also lists retried samples — so the
    view may show more rows than the count here, never fewer, and the
    count must not be "fixed" to match the view's row count (see
    design/ctl/agent-discoverability.md §3b).
    """
    errored = sum((s.get("samples") or {}).get("errored", 0) for s in summaries)
    if errored > 0:
        noun = "sample" if errored == 1 else "samples"
        _echo(f"{errored} {noun} errored — see `inspect ctl sample errors`")


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
    # sanitize each part before the join and flatten newlines so no field
    # can swallow the parts after it or forge a plausible header line; filter
    # on the sanitized value so a part that was all control bytes doesn't
    # leave a dangling separator
    sanitized_parts = (_sanitize_line(p) for p in parts)
    return "  ·  ".join(p for p in sanitized_parts if p)


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
    - ``activity`` — when some running sample has an in-flight operation:
      what it is doing right now and for how long (``generating 7:12``,
      ``bash 0:41``, ``retrying in 0:45``), so a long model call reads as
      busy rather than stalled (see :func:`_format_activity`). Blank for
      rows with nothing pending.
    - ``limit usage`` / ``limit total`` — when some sample has a token limit
      configured. ``limit usage`` is the metered value for that limit
      (respecting its type — ``all``/``output``/formula) and ``limit total``
      the configured ceiling. Blank for rows without either.
    """
    any_retries = any((s.get("retries") or 0) > 0 for s in samples)
    scorers = sorted({name for s in samples for name in (s.get("scores") or {})})
    score_col = scorers[0] if len(scorers) == 1 else None
    any_running = any(s.get("status") == "running" for s in samples)
    any_activity = any(s.get("activity") for s in samples)
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
        if any_activity:
            # after idle (a running row always shows idle when it shows
            # activity — the server only sets activity on running rows)
            cells.insert(
                2 if any_running else 1, _format_activity(s.get("activity"), now)
            )
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
    if any_activity:
        headers.append("activity")
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
    """Print an aligned, dashed-underline table (to stderr when ``err``).

    Every cell is sanitized here (not only via `_truncate`) so no
    agent-controlled string reaches the terminal raw, the width math counts
    printable characters only, and an embedded newline can't forge rows.
    """
    headers = tuple(_sanitize_control(h) for h in headers)
    rows = [tuple(_sanitize_line(cell) for cell in row) for row in rows]
    widths = [
        max(len(h), max((len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]

    def _fmt_row(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    _echo(_fmt_row(headers), err=err)
    _echo(_fmt_row(tuple("-" * w for w in widths)), err=err)
    for row in rows:
        _echo(_fmt_row(row), err=err)


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


def _format_activity(activity: dict[str, Any] | None, now: float) -> str:
    """One-cell rendering of a running sample's in-flight operation.

    ``generating 7:12`` (with ``(N retries)`` for in-call provider retries
    and ``· 1.2k tok`` when streamed progress is reported), ``bash 0:41`` /
    ``2 tools 1:10`` for pending tool calls, and ``retrying in 0:45`` for a
    generate retry backoff (time until the next attempt; bare ``retrying``
    once the deadline passes). Elapsed is client-computed from
    ``started_at``, matching the idle column's convention. Empty for a
    null/absent activity; an unknown type from a newer server renders as
    its name rather than blank.
    """
    if not activity:
        return ""
    started = activity.get("started_at")
    elapsed = (
        _format_duration(now - started) if isinstance(started, (int, float)) else ""
    )
    activity_type = activity.get("type")
    if activity_type == "model":
        cell = "generating" + (f" {elapsed}" if elapsed else "")
        retries = activity.get("retries")
        if retries:
            suffix = "retry" if retries == 1 else "retries"
            cell += f" ({retries} {suffix})"
        tokens = activity.get("tokens")
        if tokens is not None:
            cell += f" · {_format_tokens(int(tokens))} tok"
        return cell
    if activity_type == "tool":
        count = int(activity.get("count") or 1)
        label = f"{count} tools" if count > 1 else str(activity.get("detail") or "tool")
        return label + (f" {elapsed}" if elapsed else "")
    if activity_type == "retry_wait":
        deadline = activity.get("deadline")
        remaining = (
            _format_duration(deadline - now)
            if isinstance(deadline, (int, float))
            else ""
        )
        cell = "retrying" + (f" in {remaining}" if remaining else "")
        # `count` is the attempt that just failed, so say "after attempt N" —
        # a bare "attempt N" reads as the upcoming attempt (which is N + 1).
        attempt = int(activity.get("count") or 0)
        if attempt > 1:
            cell += f" (after attempt {attempt})"
        return cell
    return str(activity_type or "")


def _format_tokens(tokens: int) -> str:
    """Compact token count: ``850``, ``1.2k``, ``3.4M``."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def _format_score(value: Any) -> str:
    """Compact score-value cell (floats trimmed; other values stringified)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
