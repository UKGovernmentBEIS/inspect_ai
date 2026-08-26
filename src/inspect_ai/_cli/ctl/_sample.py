"""``inspect ctl sample`` commands and the sample mutation runners.

The read runners live in ``_sample_read``.
"""

from __future__ import annotations

import json as json_lib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import click

from inspect_ai._control.state import DEFAULT_SAMPLE_LIST_LIMIT, SAMPLE_STATUSES

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _http
from ._failure import _CtlFailure, _envelope_failures, _fail, _structured_failures
from ._fetch import _fetch_sample_summaries, _resolve_target_eval
from ._group import (
    _MUTATION_ENVELOPE_HELP,
    _echo_no_running_evals,
    _forward_group_options,
    _json_option,
    _mirror_list_options,
    _model_option,
    _NounGroup,
    _terse_line,
    _terse_option,
    _use_terse,
    ctl_command,
)
from ._http import _failure_prefix
from ._mutate import _CANCEL_ROUTE_MISSING, _mutation_envelope, _mutation_outcome
from ._render import _echo, _echo_raw, _sanitize_line, _task_header
from ._sample_read import (
    _DEFAULT_EVENTS_TAIL,
    _DEFAULT_MESSAGES_TAIL,
    _exit_removed_since,
    _list_sample_rows,
    _run_sample_errors,
    _run_sample_events,
    _run_sample_list,
    _run_sample_messages,
    _run_sample_show,
    _run_sample_store,
)

if TYPE_CHECKING:
    # TYPE_CHECKING to keep the CLI import-light: `inspect_ai.log._samples`
    # pulls in a chunk of the core package this thin HTTP client never needs.
    from inspect_ai.log._samples import SampleCancelAction


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
@_model_option()
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
    model: str | None,
    active_since: float | None,
    limit: int | None,
    all_samples: bool,
    status: str | None,
    content: bool,
    as_json: bool,
) -> None:
    """List the samples (running and completed) of running evals.

    TASK is a task id (or unique prefix) or task name, matched at the start
    or after a `/`; omitted, the listing spans all running tasks. `--model`
    narrows to tasks running a matching model — disambiguating a TASK name
    that runs against several models, or scoping a TASK-less listing. To
    poll for what changed, pass `--active-since` the `as_of` from the prior
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
        model=model,
    )


_mirror_list_options(sample_group, sample_list_command)


@sample_group.command("errors")
@click.argument("task", required=False)
@_model_option()
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
def sample_errors_command(
    task: str | None, model: str | None, content: bool, as_json: bool
) -> None:
    """List the samples of running evals that errored or were retried.

    One row per sample; pass `--content` for the latest error message. An
    omitted TASK spans all running tasks; `--model` narrows to tasks running
    a matching model. Drill into one sample with `inspect ctl sample show`.
    """
    _run_sample_errors(task, as_json, content=content, model=model)


@sample_group.command("show")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@_model_option()
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
    model: str | None,
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
        task,
        sample_id,
        epoch,
        content or show_traceback,
        show_traceback,
        as_json,
        model=model,
    )


@sample_group.command("events")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@_model_option()
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
    model: str | None,
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
        model=model,
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
@_model_option()
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
    model: str | None,
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
        model=model,
        tail=tail,
        show_all=show_all,
        content=content,
        full=full,
        as_json=as_json,
    )


@sample_group.command("store")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=1)
@click.option(
    "--key",
    "keys",
    multiple=True,
    help=(
        "Only these keys (repeatable), selected server-side so one large "
        "key doesn't drag the whole store over the wire. An exact name, or "
        "a trailing-* prefix (e.g. 'AgentState:*' for one StoreModel's "
        "fields; a bare '*' matches every key). Unknown exact keys land in "
        "`missing` (not an error)."
    ),
)
@click.option(
    "--content",
    is_flag=True,
    default=False,
    help=(
        "Include a truncated single-line preview of each value "
        "(agent-controlled text, withheld by default) in the compact "
        "summary."
    ),
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help=(
        "Return raw values instead of the compact summary. Unbounded — "
        "combine with --key to keep the response bounded."
    ),
)
@_json_option(
    "the `{task_id, sample_id, epoch, as_of, status, count, store}` envelope, "
    "plus `missing` when --key was given"
)
def sample_store_command(
    task: str,
    sample_id: str,
    epoch: int,
    keys: tuple[str, ...],
    content: bool,
    full: bool,
    as_json: bool,
) -> None:
    """Read one sample's current store (a snapshot).

    Returns the sample's `Store` — the shared state solvers, tools, and
    agents coordinate through — as it looks right now: read from the live
    task state while the sample runs, and from the log once it finishes. A
    snapshot, not a stream: the store is rewritable, so there is no resume
    cursor; poll, or follow `inspect ctl sample events --type store` for the
    change stream. The default is metadata-only rows per key (JSON type,
    serialized size in UTF-8 bytes — for spotting the big keys, it differs from
    in-memory size — and a length hint); pass `--content` for truncated
    value previews, `--full` for raw values, and `--key` (repeatable; exact
    name or trailing-* prefix) to select keys server-side. EPOCH defaults
    to 1 (the response echoes the resolved epoch).

    Example: inspect ctl sample store my-task sample-1 --key phase --content
    """
    _run_sample_store(
        task,
        sample_id,
        epoch,
        keys=keys,
        content=content,
        full=full,
        as_json=as_json,
    )


@sample_group.command("cancel")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=None)
@_model_option()
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
    model: str | None,
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
        model=model,
    )


@sample_group.command("cancel-tool-call")
@click.argument("task")
@click.argument("sample_id")
@click.argument("epoch", required=False, type=int, default=None)
@click.option(
    "--tool-call-id",
    default=None,
    help=(
        "Id of the tool call to cancel (from the pending-calls list in "
        "`sample list --json` activity, or `sample messages --json`). "
        "Omitted, the sample's sole pending tool call is the target; two "
        "or more pending is an error enumerating them."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Report what would be cancelled without doing it (without "
        "--tool-call-id this doubles as listing the pending tool calls)."
    ),
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def sample_cancel_tool_call_command(
    task: str,
    sample_id: str,
    epoch: int | None,
    tool_call_id: str | None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
) -> None:
    """Cancel one in-flight tool call and let the sample continue.

    The surgical alternative to `sample cancel` when a sample is stuck on a
    hung tool call: the call's own cancel scope is fired, the model sees an
    ordinary tool timeout, and the sample continues — parallel sibling calls
    and the rest of the task are undisturbed. Idempotent — repeating a
    cancel, targeting a call that is no longer pending, or targeting a
    finished sample is a clean no-op. EPOCH defaults to 1 but is required
    whenever the task runs more than one epoch (a defaulted epoch would
    silently target a different attempt).

    The cancel is delivered to the call's cancel scope, which is not a
    guarantee the tool stops: a truly wedged call (sync code in a thread,
    shielded teardown) may never unwind — a repeat then reports "cancel
    already requested", and the escalation is `sample cancel`.
    """
    _run_sample_cancel_tool_call(
        task,
        sample_id,
        epoch,
        tool_call_id=tool_call_id,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
    )


@sample_group.command("requeue")
@click.argument("task")
@click.argument(
    "targets", nargs=-1, metavar="[SAMPLE_ID [EPOCH] | SAMPLE_ID EPOCH ...]"
)
@_model_option()
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
    model: str | None,
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
        _run_sample_requeue_errored(
            task, dry_run=dry_run, as_json=as_json, terse=terse, model=model
        )
        return
    if not targets:
        raise click.UsageError(
            "Pass SAMPLE_ID [EPOCH] (or several SAMPLE_ID EPOCH pairs), or "
            "--errored to requeue every currently-errored sample."
        )
    if len(targets) == 1:
        _run_sample_requeue(
            task,
            targets[0],
            None,
            dry_run=dry_run,
            as_json=as_json,
            terse=terse,
            model=model,
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
            model=model,
        )
    else:
        _run_sample_requeue_bulk(
            task, pairs, dry_run=dry_run, as_json=as_json, terse=terse, model=model
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
    model: str | None = None,
) -> None:
    """Shared scaffold for the sample mutations (cancel, cancel-tool-call, requeue).

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

    target = _resolve_target_eval(
        summaries, task, busy_pids=fetched.busy_pids, model=model
    )

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
                "pass EPOCH explicitly (a defaulted epoch would silently "
                f"apply the {verb} to the epoch-1 attempt).",
            )
        epoch = 1

    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        **extra_params,
    }
    if dry_run:
        params["dry_run"] = True
    result = _http._request_json(
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
    model: str | None = None,
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
        model=model,
    )


_CANCEL_TOOL_CALL_ROUTE_MISSING = (
    "This process is running an older inspect without the tool-call cancel "
    "endpoint; restart the eval to pick up the current version."
)


@_envelope_failures
def _run_sample_cancel_tool_call(
    task: str,
    sample_id: str,
    epoch: int | None,
    *,
    tool_call_id: str | None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    def call_label(result: dict[str, Any]) -> str:
        # tool-call ids and function names are model-generated tokens —
        # sanitize before they enter a message line
        tcid = result.get("tool_call_id") or tool_call_id or "?"
        function = result.get("function")
        suffix = f" ({function})" if function else ""
        return _sanitize_line(f"{tcid}{suffix}")

    def pending_clause(result: dict[str, Any]) -> str:
        pending = result.get("pending") or []
        if not pending:
            return ""
        calls = ", ".join(f"{p.get('id')} ({p.get('function')})" for p in pending)
        return f" Pending: {_sanitize_line(calls)}."

    def activity_clause(result: dict[str, Any]) -> str:
        # the zero-pending no-op carries the sample's current activity so the
        # operator learns where it is actually stuck without a --json retry;
        # `detail` (a model name or tool function) is model-influenceable
        activity = result.get("activity")
        if not activity:
            return ""
        detail = activity.get("detail")
        where = (
            f"{activity.get('type')} ({detail})"
            if detail
            else str(activity.get("type"))
        )
        return f" Sample activity: {_sanitize_line(where)}."

    def changed_message(label: str, result: dict[str, Any]) -> str:
        if dry_run:
            return f"Would cancel tool call {call_label(result)} of {label}."
        return (
            f"Cancel requested for tool call {call_label(result)} of {label} "
            "— the model will see a tool timeout and the sample will continue."
        )

    def noop_message(label: str, result: dict[str, Any]) -> str:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        return f"Nothing to do — {reason}.{pending_clause(result)}{activity_clause(result)}"

    def terse_changed(result: dict[str, Any]) -> str:
        if dry_run:
            return f"dry-run — would cancel tool call {call_label(result)}"
        return f"requested — tool call {call_label(result)} will time out"

    def terse_noop(result: dict[str, Any]) -> str:
        return f"no-op — {result.get('reason') or 'already in that state'}"

    extra_params: dict[str, Any] = {}
    if tool_call_id is not None:
        extra_params["tool_call_id"] = tool_call_id
    _run_sample_mutation(
        task,
        sample_id,
        epoch,
        verb="cancel-tool-call",
        extra_params=extra_params,
        route_missing=_CANCEL_TOOL_CALL_ROUTE_MISSING,
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
    model: str | None = None,
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
        model=model,
    )


@_envelope_failures
def _run_sample_requeue_bulk(
    task: str,
    pairs: list[tuple[str, int]],
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
    model: str | None = None,
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
    target = _resolve_target_eval(
        summaries, task, busy_pids=fetched.busy_pids, model=model
    )
    _requeue_pairs(target, pairs, dry_run=dry_run, as_json=as_json, terse=terse)


@_envelope_failures
def _run_sample_requeue_errored(
    task: str,
    *,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
    model: str | None = None,
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
        task, None, statuses=frozenset({"error"}), all_samples=True, model=model
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
            result = _http._request_json(
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
