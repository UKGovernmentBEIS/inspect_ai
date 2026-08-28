"""Directive machinery shared by more than one noun.

Scope targeting for directives with an optional TASK, the uniform
``--json`` mutation envelope, pause confirmation prose, and the
route-missing messages shared across nouns.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from inspect_ai._control.discovery import DiscoveredControlServer

from ._failure import _fail
from ._fetch import (
    _exit_ambiguous,
    _model_qualifier,
    _narrow_by_model,
    _resolve_target_eval,
)
from ._render import _task_header


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
    model: str | None = None,
) -> _DirectiveScope | None:
    """Resolve the task-or-process scope a directive command targets.

    The one resolution rule for directives with an optional ``TASK`` (config
    and task log-flush today; task cancel/drain are expected to reuse it): an
    explicit ``TASK`` targets that task; no ``TASK`` defaults to the sole
    process — a single-active-task process resolves to that task (completed
    eval-set siblings don't count), a multi-task process resolves to the
    process-level scope. ``model`` composes with both paths — an explicit
    ``TASK``'s matches are filtered to tasks running a matching model (see
    ``_resolve_target_eval``), and the no-``TASK`` defaults resolve over the
    model-narrowed rows (see ``_narrow_by_model``) — so one task run
    against several models resolves by name plus ``--model``. Sibling counts
    stay on the full summaries: the blast radius of a process-scoped knob is
    unaffected by a narrowed view. ``per_task_option`` names the option or
    command
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
        target = _resolve_target_eval(summaries, task, model=model)
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

    visible = _narrow_by_model(summaries, model) if model is not None else summaries
    qualifier = _model_qualifier(model)
    sockets = sorted({str(s.get("socket_path")) for s in visible})
    if len(sockets) > 1:
        # multiple processes: can't default to one — passing a task id
        # disambiguates the process too
        _exit_ambiguous(
            visible,
            "Multiple processes are running"
            + (f" tasks{qualifier}" if model is not None else ""),
        )
    socket_path = sockets[0]
    tasks_in_proc = [s for s in visible if str(s.get("socket_path")) == socket_path]
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
            f"running {count} task{'s' if count != 1 else ''}{qualifier}",
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
