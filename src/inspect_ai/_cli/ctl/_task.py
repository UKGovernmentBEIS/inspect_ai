"""``inspect ctl task`` commands and their runners."""

from __future__ import annotations

import json as json_lib
import time
from typing import Any, Literal, cast

import click

from inspect_ai._control.cancel import TaskCancelAction

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _fetch, _http
from ._failure import _envelope_failures
from ._group import (
    _MUTATION_ENVELOPE_HELP,
    _echo_no_running_evals,
    _forward_group_options,
    _json_option,
    _mirror_list_options,
    _model_option,
    _NounGroup,
    _now_option,
    _terse_line,
    _terse_option,
    _use_terse,
    ctl_command,
)
from ._mutate import (
    _CANCEL_ROUTE_MISSING,
    _HELD_CAVEAT,
    _PAUSE_ROUTE_MISSING,
    _DirectiveScope,
    _mutation_envelope,
    _pause_confirmation,
    _resolve_scope,
    _terse_held_suffix,
)
from ._render import (
    _echo,
    _echo_raw,
    _paused_sources,
    _print_errored_samples_footer,
    _print_human_table,
    _print_keep_alive_footer,
    _sanitize_line,
)


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
@_model_option()
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_log_flush_command(
    task: str | None, model: str | None, as_json: bool, terse: bool | None
) -> None:
    """Flush a running task's buffered samples to its log now.

    Completed samples are written to the (possibly remote) log only when
    the buffer fills; this forces the write immediately. Safe to repeat.
    Tune the buffering policy itself with `inspect ctl config --log-buffer`
    / `--log-shared`. TASK (a task-id prefix or name) is required when
    several tasks run; pass `--model` to disambiguate when one task runs
    against several models.
    """
    _run_log_flush(task, as_json, terse=terse, model=model)


@task_group.command("cancel")
@click.argument("task")
@_model_option()
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
    task: str,
    model: str | None,
    action: str,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
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
    or name) is always required; pass `--model` to disambiguate when one
    task runs against several models.
    """
    _run_task_cancel(
        task,
        action=cast(TaskCancelAction, action),
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
        model=model,
    )


@task_group.command("score")
@click.argument("task", required=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be scored (counts by disposition) without scoring.",
)
@click.option(
    "--completed-only",
    is_flag=True,
    default=False,
    help=(
        "Skip in-flight samples entirely — interim metrics over completed "
        "samples' existing final scores, with zero holds and zero scorer "
        "model calls. The free spelling for recurring polling."
    ),
)
@click.option(
    "--no-wait",
    is_flag=True,
    default=False,
    help=(
        "Return the started-pass envelope immediately instead of polling to "
        "completion (follow up with --status)."
    ),
)
@click.option(
    "--status",
    is_flag=True,
    default=False,
    help=(
        "Report the current (or most recent) pass without starting one — the "
        "follow-up spelling after --no-wait. Polls a still-running pass to "
        "completion; with --no-wait, returns a single status snapshot."
    ),
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_score_command(
    task: str | None,
    dry_run: bool,
    completed_only: bool,
    no_wait: bool,
    status: bool,
    as_json: bool,
    terse: bool | None,
) -> None:
    """Score a running task's samples now and report interim metrics.

    Non-destructive: runs the task's own scorers over in-flight samples —
    each is briefly held at its next model call, scored on its stable
    work-so-far, and released (its interim score is recorded on its
    transcript; the sample keeps running). A sample that neither parks nor
    completes within the hold timeout is skipped and reported. Completed
    samples are never re-scored: already-scored ones fold their final
    scores into the interim metrics, and unscored ones (a scorer that
    errored) are reported skipped — score them post-run with
    `inspect score`. Note the wall clock keeps running for a held sample,
    and scorer model calls share the process's connection limits with the
    running eval. One pass per task at a time — a repeat while one runs
    reports the running pass, and --status reports the current (or most
    recent) pass without starting one. TASK (a task-id prefix or name) is
    required when several tasks run.
    """
    _run_task_score(
        task,
        dry_run=dry_run,
        completed_only=completed_only,
        no_wait=no_wait,
        status=status,
        as_json=as_json,
        terse=terse,
    )


@task_group.command("pause")
@click.argument("task", required=False)
@_model_option()
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
    task: str | None,
    model: str | None,
    now: bool,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
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
    task-id prefix or name) is required when several tasks run; pass
    `--model` to disambiguate when one task runs against several models.
    """
    _run_task_pause_resume(
        task,
        verb="pause",
        now=now,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
        model=model,
    )


@task_group.command("resume")
@click.argument("task", required=False)
@_model_option()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
@_terse_option()
def task_resume_command(
    task: str | None,
    model: str | None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
) -> None:
    """Resume a paused task (the inverse of `inspect ctl task pause`).

    Queued samples dispatch again exactly as they would have before the
    pause. Does not clear a process-level pause — a task also held by
    `inspect ctl process pause` stays held until `inspect ctl process
    resume`. Idempotent and last-write-wins. TASK (a task-id prefix or name)
    is required when several tasks run; pass `--model` to disambiguate when
    one task runs against several models.
    """
    _run_task_pause_resume(
        task, verb="resume", dry_run=dry_run, as_json=as_json, terse=terse, model=model
    )


@_envelope_failures
def _run_task_list(as_json: bool) -> None:
    # Stamp as_of BEFORE the reads: anything that changes during them has a
    # timestamp >= as_of and is caught by the next poll rather than missed.
    as_of = time.time()
    summaries = _fetch._fetch_summaries(_http.list_discovered_servers()).summaries

    if as_json:
        _echo_raw(json_lib.dumps({"as_of": as_of, "tasks": summaries}, indent=2))
        return

    if not summaries:
        _echo_no_running_evals()
        return

    _print_human_table(summaries)
    _print_keep_alive_footer(summaries)
    _print_errored_samples_footer(summaries)


@_envelope_failures
def _run_log_flush(
    task: str | None,
    as_json: bool,
    terse: bool | None = None,
    model: str | None = None,
) -> None:
    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries
    scope = _resolve_scope(
        servers, summaries, task, per_task_option="task log-flush", model=model
    )
    if scope is None:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    # per_task_option forbids the process-scope fallbacks, so the resolved
    # scope always carries a task
    assert scope.task_id is not None
    result = _fetch._post_flush(scope.socket_path, scope.task_id, pid=scope.pid)

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


@_envelope_failures
def _run_task_cancel(
    task: str,
    *,
    action: TaskCancelAction = "cancel",
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
    model: str | None = None,
) -> None:
    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries
    scope = _resolve_scope(
        servers, summaries, task, per_task_option="task cancel", model=model
    )
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
    result = _http._request_json(
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


_SCORE_ROUTE_MISSING = (
    "This process is running an older inspect without the interim-scoring "
    "endpoint; restart the eval to pick up the current version."
)

_SCORE_POLL_INTERVAL = 1.0


@_envelope_failures
def _run_task_score(
    task: str | None,
    *,
    dry_run: bool,
    completed_only: bool,
    no_wait: bool,
    status: bool = False,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    """Start an interim scoring pass and (by default) poll it to completion.

    Wraps the start + poll endpoint pair (``POST``/``GET
    /tasks/<task-id>/score``). Follows the mutation selector rule with the
    sole-running-task default — non-destructive, so it sits with `log-flush`
    on the selector-optional side. The start is idempotent (a repeat while a
    pass runs joins it), so it may ride the narrated busy-retry policy.

    ``status`` never POSTs: it reads the current (or most recent) pass — the
    follow-up spelling after ``--no-wait`` (a repeat *start* would spawn a
    fresh pass once the first finished, re-holding in-flight samples and
    re-spending grader calls).
    """
    if status and (dry_run or completed_only):
        raise click.UsageError(
            "--status reports an existing pass; it cannot be combined with "
            "--dry-run or --completed-only."
        )

    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries
    scope = _resolve_scope(servers, summaries, task, per_task_option="task score")
    if scope is None:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return
    assert scope.task_id is not None

    if status:
        _run_task_score_status(scope, no_wait=no_wait, as_json=as_json, terse=terse)
        return

    params: dict[str, Any] = {}
    if dry_run:
        params["dry_run"] = True
    if completed_only:
        params["completed_only"] = True
    result = _http._request_json(
        scope.socket_path,
        f"/tasks/{scope.task_id}/score",
        params=params,
        what=f"interim scoring of task {scope.task_id}",
        not_found=(
            f"Task '{scope.task_id}' not found in this process (it may have finished)."
        ),
        not_found_missing_route=_SCORE_ROUTE_MISSING,
        mutate="post",
        # idempotent only against a still-running pass: if the response
        # outlives the read timeout and the pass finishes before the retry
        # lands, the retry starts a second pass. Accepted as narrow — the
        # same event-loop starvation that delays the response also slows
        # the pass itself.
        retry_mutation=True,
        pid=scope.pid,
    )

    target = {"task_id": scope.task_id, "task": scope.task}
    terse_mode = _use_terse(terse)
    target_label = scope.task or scope.task_id
    targeted = result.get("targeted") or {}

    if dry_run or no_wait:
        if as_json:
            _echo_raw(
                json_lib.dumps(
                    _mutation_envelope(target, result, dry_run=dry_run), indent=2
                )
            )
            return
        if not terse_mode:
            _echo(scope.header)
            _echo()
        # the no-op envelope (a pass already running) carries no `targeted`,
        # so check `changed` before any rendering that reads it — otherwise
        # a dry run against a running pass prints misleading all-zeros
        if not result.get("changed"):
            reason = _sanitize_line(str(result.get("reason") or "already running"))
            if terse_mode:
                _echo(_terse_line("score", target_label, f"no-op — {reason}"))
            else:
                _echo(f"Nothing to do: {reason}.")
        elif dry_run:
            body = _score_targeted_summary(targeted)
            if terse_mode:
                _echo(_terse_line("score", target_label, f"dry-run — {body}"))
            else:
                _echo(f"Would score — {body}.")
        else:
            note = f"pass {result.get('pass_id')} started — {_score_targeted_summary(targeted)}"
            if terse_mode:
                _echo(_terse_line("score", target_label, note))
            else:
                _echo(
                    f"Scoring pass started ({_score_targeted_summary(targeted)}). "
                    "Poll it with `inspect ctl task score --status`."
                )
        return

    # poll the pass to completion (the started one, or the one already
    # running that the start idempotently joined)
    if not terse_mode and not as_json:
        _echo(scope.header)
        _echo()
    # a silent join would misreport what's being watched — loudest when the
    # flags differ (a --completed-only request joining a full pass is
    # watching holds it asked to avoid); JSON callers see `applied: false`
    if not result.get("changed") and not as_json:
        note = f"joined already-running pass {result.get('pass_id')}"
        if bool(result.get("completed_only")) != completed_only:
            note += (
                " (a full pass — it holds in-flight samples, unlike the "
                "requested --completed-only)"
                if completed_only
                else " (started with --completed-only, so in-flight samples "
                "are not scored)"
            )
        note = _sanitize_line(note)
        if terse_mode:
            _echo(_terse_line("score", target_label, note))
        else:
            _echo(f"Note: {note}.")
    final = _poll_score_pass(scope, echo_progress=not terse_mode and not as_json)

    if as_json:
        envelope = {
            "target": target,
            "applied": bool(result.get("changed")),
            "dry_run": False,
            "detail": {k: v for k, v in final.items() if k != "ok"},
        }
        _echo_raw(json_lib.dumps(envelope, indent=2))
        return

    _render_score_result(final, terse_mode=terse_mode, target_label=target_label)


def _run_task_score_status(
    scope: _DirectiveScope, *, no_wait: bool, as_json: bool, terse: bool | None
) -> None:
    """Report the current (or most recent) pass (``--status`` — no POST).

    Polls a still-running pass to completion like the default flow; with
    ``--no-wait``, a single status snapshot. ``--json`` emits the poll
    endpoint's response as-is (a read, so no mutation envelope).
    """
    terse_mode = _use_terse(terse)
    target_label = scope.task or scope.task_id or ""
    if not terse_mode and not as_json:
        _echo(scope.header)
        _echo()
    if no_wait:
        result = _get_score_status(scope)
    else:
        result = _poll_score_pass(scope, echo_progress=not terse_mode and not as_json)
    if as_json:
        _echo_raw(json_lib.dumps(result, indent=2))
        return
    if result.get("running"):
        body = f"running — {_score_progress_summary(result.get('progress') or {})}"
        if terse_mode:
            _echo(_terse_line("score", target_label, body))
        else:
            _echo(f"Scoring pass {body}.")
        return
    _render_score_result(result, terse_mode=terse_mode, target_label=target_label)


def _score_targeted_summary(targeted: dict[str, Any]) -> str:
    return (
        f"{int(targeted.get('in_flight', 0) or 0)} in-flight (held while "
        f"scored), {int(targeted.get('completed_scored', 0) or 0)} already "
        f"scored (metrics only), {int(targeted.get('completed_unscored', 0) or 0)} "
        f"completed unscored (post-run `inspect score`), "
        f"{int(targeted.get('skipped', 0) or 0)} skipped"
    )


def _score_progress_summary(progress: dict[str, Any]) -> str:
    """Render a pass's progress counters (unscored shown only when nonzero).

    ``unscored`` counts in-flight samples the pass never attempted (they
    completed on their own mid-hold, or never parked) or that every scorer
    declined to score — kept apart from ``failed`` so the headline never
    reads scorer failures into them.
    """
    parts = [
        f"{int(progress.get('scored', 0) or 0)} scored",
        f"{int(progress.get('failed', 0) or 0)} failed",
    ]
    unscored = int(progress.get("unscored", 0) or 0)
    if unscored:
        parts.append(f"{unscored} unscored")
    return f"{', '.join(parts)} of {int(progress.get('total', 0) or 0)}"


def _get_score_status(scope: _DirectiveScope) -> dict[str, Any]:
    """One ``GET /tasks/<task-id>/score`` (the poll endpoint)."""
    return _http._request_json(
        scope.socket_path,
        f"/tasks/{scope.task_id}/score",
        what=f"interim scoring status of task {scope.task_id}",
        not_found=(
            f"No scoring pass found for task '{scope.task_id}' (none has "
            "been started, or the process restarted)."
        ),
        not_found_missing_route=_SCORE_ROUTE_MISSING,
        pid=scope.pid,
    )


def _poll_score_pass(scope: _DirectiveScope, *, echo_progress: bool) -> dict[str, Any]:
    """Poll ``GET /tasks/<task-id>/score`` until the pass finishes."""
    last: str | None = None
    while True:
        status = _get_score_status(scope)
        progress = status.get("progress") or {}
        summary = _score_progress_summary(progress)
        if echo_progress and status.get("running") and summary != last:
            _echo(f"scoring — {summary}")
            last = summary
        if not status.get("running"):
            return status
        time.sleep(_SCORE_POLL_INTERVAL)


def _render_score_result(
    status: dict[str, Any], *, terse_mode: bool, target_label: str
) -> None:
    progress = status.get("progress") or {}
    result = status.get("result") or {}
    counts = result.get("counts") or {}
    summary = f"{_score_progress_summary(progress)} targeted"
    if terse_mode:
        suffix = ""
        if status.get("interrupted"):
            suffix = f"; interrupted — {_sanitize_line(str(status['interrupted']))}"
        elif status.get("error"):
            suffix = f"; error — {_sanitize_line(str(status['error']))}"
        _echo(_terse_line("score", target_label, f"complete — {summary}{suffix}"))
        return
    _echo(f"Interim scoring pass complete — {summary}.")
    if counts:
        _echo(f"Dispositions: {_score_targeted_summary(counts)}.")
    metrics = result.get("metrics") or []
    if metrics:
        _echo(
            "Interim metrics (epochs may be incomplete; in-flight scores "
            "describe a held moment):"
        )
        for entry in metrics:
            pairs = ", ".join(
                f"{key}={value}" for key, value in (entry.get("metrics") or {}).items()
            )
            reducer = f"/{entry['reducer']}" if entry.get("reducer") else ""
            _echo(_sanitize_line(f"  {entry.get('scorer')}{reducer}: {pairs}"))
    if status.get("interrupted"):
        _echo(f"Note: pass interrupted — {_sanitize_line(str(status['interrupted']))}.")
    if status.get("error"):
        _echo(f"Pass error: {_sanitize_line(str(status['error']))}.")


def _still_held_note(held: list[str]) -> str:
    """Point at the broader latch(es) still holding a task after `task resume`."""
    latches = []
    if "process" in held:
        latches.append("the process is paused (`inspect ctl process resume`)")
    if "model" in held:
        latches.append("its model is paused (`inspect ctl model resume`)")
    return f"Note: {' and '.join(latches)} — samples stay held until resumed."


@_envelope_failures
def _run_task_pause_resume(
    task: str | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
    model: str | None = None,
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
    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries
    scope = _resolve_scope(
        servers, summaries, task, per_task_option=f"task {verb}", model=model
    )
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
    result = _http._request_json(
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
