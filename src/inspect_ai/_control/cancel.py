"""Cancel and drain directives for the control channel (phase 3).

The destructive state-mutating directives — all idempotent and dry-runnable
per the phase-3 agent-shape constraints:

- :func:`cancel_task` — task-keyed (stable across retries, like ``config`` /
  ``log-flush``). ``action`` selects how the task's samples are resolved:

  - ``"cancel"`` (the default) fires the latest attempt's registered
    ``TaskCancel`` with ``"abort"``, the same user-cancel path the in-process
    task display's cancel dialog drives. In-flight samples are interrupted
    (their transcripts so far are preserved in the log as cancelled samples),
    completed samples are kept, partial results are computed, and the log is
    finalized with an error status noting the cancel; an eval-set does not
    retry an aborted task.
  - ``"score"`` / ``"error"`` resolve the task gracefully: the resolution is
    stamped on the ``TaskCancel`` handle (so still-queued samples abandon as
    they leave the queue, samples mid-initialization resolve as they start,
    and an eval-set does not retry), each in-flight sample is interrupted with
    the matching ``ActiveSample.interrupt`` action, and the task runs to
    natural completion — completed and resolved samples are scored/recorded
    and the log finishes with its ordinary terminal status. This is what lets
    an agent abandon a task's last few samples while still bringing the eval
    to a completed state.

- :func:`drain_task` — the graceful cancel machinery minus the interrupt
  sweep (``POST /tasks/<task-id>/drain`` / ``inspect ctl task drain``; see
  ``design/ctl/task-drain.md``): the ``"drain"`` type is stamped on the
  handle and nothing is interrupted. Queued samples abandon exactly as under
  score/error; in-flight samples never see the directive and finish
  naturally — on their own clock, unbounded; the task completes with an
  ordinary terminal log when the last one does. Escalation is spelled with
  the existing verbs (the ladder ``drain < score/error < cancel (abort)``):
  ``--action score`` is "stop waiting, resolve in-flight work now" and a
  plain ``cancel`` is force.

- :func:`cancel_sample` — attempt-keyed like the other per-sample operations:
  interrupts one *running* sample via ``ActiveSample.interrupt``, the same
  primitive the in-process TUI and ACP's ``inspect/cancel_sample`` use.
  ``action`` selects the outcome — ``"score"`` completes the sample and runs
  the scorer on the work done so far; ``"error"`` marks it errored (rejected
  when the sample is configured to fail on errors, mirroring the TUI/ACP
  gate, since the auto-fail would race it); ``"cancel"`` records it as
  cancelled — transcript preserved, no scoring, not counted as an error.

All run on the eval's own loop (the control server is embedded), so firing
a cancel scope from a route handler is safe. Results are dicts: ``None``
means the target isn't in this process (the route 404s); ``{"ok": False,
"error": ...}`` is a rejection (the route maps it to a 409); otherwise the
result carries ``changed`` — ``False`` is the idempotent already-in-that-state
no-op (task already finished / cancel already requested / sample already
terminal), so an agent retrying on confusion gets a clean answer rather than
an error.

A task *between attempts* (its last attempt errored and an eval-set retry is
queued but not started — ``EvalState.retry_pending``) is handled per
``design/ctl/task-drain.md``: a plain cancel or a drain *abandons* the
pending retry (the task ends with its last attempt's error log — exactly the
shape an exhausted retry budget produces), while score/error stay a
rejection (there are no samples for a resolution to apply to). The same
abandonment applies when the attempt has *requested* a retry and is still
tearing down (a pending ``"retry"`` stamp with retry budget remaining).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample, SampleCancelAction

TaskCancelAction = Literal["cancel", "score", "error"]
"""How a task cancel resolves its samples (see :func:`cancel_task`).

The sample-level counterpart, ``SampleCancelAction``, lives in
``inspect_ai.log._samples`` beside the ``ActiveSample.interrupt``
primitive it types. Deliberately a distinct type despite the identical
values: task ``"cancel"`` aborts the attempt (it does *not* map to the
sample-level ``"cancel"`` interrupt), the task set may diverge (e.g. a
future graceful-drain action), and this CLI-light module is importable
at ``inspect_ai._cli.ctl`` startup where ``log._samples`` is not.
"""


# The escalation ladder, ordered by invasiveness: a request strictly
# *stronger* than the pending resolution applies (the stamp is overwritten
# and, for score/error, the interrupt sweep runs; for abort, the scope
# fires); anything equal or weaker is the idempotent no-op. Score and error
# are unordered peers. See design/ctl/task-drain.md "Escalation ladder and
# idempotence" (generalizes the original abort-over-score/error rule —
# teardown must always remain reachable, e.g. a draining task stalled on a
# hung sample, and score/error is drain's "stop waiting" relief valve).
_ESCALATION_LADDER: dict[str, int] = {"drain": 0, "score": 1, "error": 1, "abort": 2}


def cancel_task(
    task_id: str,
    *,
    action: TaskCancelAction = "cancel",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Cancel a running task (``POST /tasks/<task-id>/cancel``).

    Resolves the task's latest attempt and cancels it per ``action``
    (unless ``dry_run``): ``"cancel"`` fires its ``TaskCancel`` with
    ``"abort"``; ``"score"`` / ``"error"`` stamp the resolution on the handle,
    interrupt each in-flight sample with the matching action (first resolution
    wins — a sample already interrupted, or whose limit has already fired,
    keeps its outcome), abandon queued samples, and let the task complete
    naturally (see the module docstring).

    Returns ``None`` when the task isn't in this process; a ``changed: False``
    no-op when it has already finished or an equal-or-stronger cancel is
    already in flight (the reason names the pending cancel's type; a strictly
    weaker pending resolution — per the escalation ladder ``drain <
    score/error < abort`` — is *escalated over*: the graceful path can stall
    on a hung scorer or a slow drain tail, and the operator must keep a way
    to resolve or tear the task down). A task *between attempts* (or one
    whose attempt requested a retry and is still tearing down, with budget
    remaining) is resolved by a plain ``cancel`` as a retry-abandon —
    ``changed: True`` with ``retry_abandoned`` set, the task ending with its
    last attempt's error log. ``{"ok": False, "error": ...}`` when
    ``action="error"`` targets samples configured to fail on errors
    (mirroring the sample-level gate — the auto-fail would race it; a sample
    mid-materialization is invisible to this gate, so its self-interrupt
    downgrades an ``error`` resolution to ``score`` instead), when the
    attempt has no cancel handle (defensive — a running attempt registered
    without one, which no production registration produces; reused/synthetic
    evals register finished and take the no-op branch instead) or when
    ``action="score"|"error"`` targets a task between attempts (there are no
    samples for a resolution to apply to — the rejection points at a plain
    cancel or drain).
    """
    stamp: CancelStamp = "abort" if action == "cancel" else action
    return _task_cancel_directive(task_id, stamp=stamp, action=action, dry_run=dry_run)


def drain_task(task_id: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Drain a running task (``POST /tasks/<task-id>/drain``).

    Stamps the ``"drain"`` type on the task's latest attempt's ``TaskCancel``
    handle (unless ``dry_run``) and interrupts nothing: still-queued samples
    abandon as they leave the queue (terminal ``cancelled`` in the counters,
    absent from the log), in-flight samples finish naturally — on their own
    clock, unbounded — and the task completes with an ordinary terminal log
    when the last one does. See ``design/ctl/task-drain.md``.

    Same result contract as :func:`cancel_task` (``None`` → 404; ``ok:
    False`` → 409; idempotent ``changed: False`` no-ops), plus ``queued`` —
    the count of samples that will be abandoned (the split an operator
    weighs: how much finishes naturally vs how much is given up). A drain of
    a task with any pending resolution (including another drain) is the
    no-op — drain is the weakest rung of the escalation ladder; a task
    between attempts (or tearing down with a retry requested) is the same
    retry-abandon a plain cancel performs.
    """
    return _task_cancel_directive(task_id, stamp="drain", action=None, dry_run=dry_run)


# what a task directive stamps on the handle: the internal CancelType
# vocabulary minus "retry" (requested only by the task itself) — note the
# wire vocabulary (TaskCancelAction) deliberately does not grow "drain",
# which is its own verb/route (see design/ctl/task-drain.md)
CancelStamp = Literal["abort", "score", "error", "drain"]


def _task_cancel_directive(
    task_id: str,
    *,
    stamp: CancelStamp,
    action: TaskCancelAction | None,
    dry_run: bool,
) -> dict[str, Any] | None:
    """Shared skeleton of :func:`cancel_task` / :func:`drain_task`.

    ``stamp`` is what lands on the ``TaskCancel`` handle; ``action`` is the
    cancel directive's wire vocabulary (``None`` for drain, which has no
    action axis).
    """
    from inspect_ai._control.eval_state import (
        abandon_task_retry,
        latest_eval_for_task,
        mark_task_gracefully_resolved,
        task_retry_abandoned,
    )

    state = latest_eval_for_task(task_id)
    if state is None:
        return None

    active = _active_eval_samples(state.eval_id)
    in_flight = [sample for sample in active if sample.started is not None]
    result: dict[str, Any] = {
        "ok": True,
        "task_id": state.task_id,
        "task": state.task,
        "eval_id": state.eval_id,
        "dry_run": dry_run,
        "in_flight": len(in_flight),
    }
    if action is not None:
        result["action"] = action
    else:
        # drain reports the other half of the split too: queued samples are
        # what a drain abandons (derived the same way the task rows derive it)
        result["queued"] = max(
            0,
            state.total
            - state.completed
            - state.errored
            - state.cancelled
            - len(in_flight),
        )
    if state.completed_at is not None:
        # consulted before the finished no-op so a repeat lands on the honest
        # reason: the registry stamp, not the pending state, marks the
        # abandonment as already applied
        if task_retry_abandoned(state.task_id):
            return {
                **result,
                "changed": False,
                "reason": "pending retry already abandoned",
            }
        if state.retry_pending:
            if stamp in ("score", "error"):
                return {
                    "ok": False,
                    "error": (
                        f"task {task_id} is between attempts — the last "
                        "attempt errored and a retry is queued but has not "
                        "started, so there are no samples for a resolution "
                        "to apply to; use a plain cancel (or drain) to "
                        "abandon the pending retry"
                    ),
                }
            # abandon the pending retry: the task ends with its last
            # attempt's error log (exactly what an exhausted retry budget
            # produces) — see design/ctl/task-drain.md "Tasks between
            # attempts"
            if not dry_run:
                abandon_task_retry(state.task_id)
            return {**result, "changed": True, "retry_abandoned": True}
        return {**result, "changed": False, "reason": "task already finished"}
    if state.task_cancel is None:
        return {
            "ok": False,
            "error": (
                f"task {task_id} is not cancellable in this process "
                "(no running attempt to cancel)"
            ),
        }
    pending = state.task_cancel.cancel_type
    if pending == "retry":
        # the attempt requested a re-run and is still tearing down (before
        # the dispatcher queues the retry). Score/error stay the no-op (the
        # attempt's samples are already resolved, mirroring their
        # between-attempts rejection); drain/plain cancel abandon the
        # requested retry so the intent sticks — inheriting the no-op here
        # would silently drop it and the retry would dispatch the whole task
        # fresh. The tearing-down attempt itself is untouched (its scope has
        # already fired; there is nothing further to interrupt or overwrite).
        if stamp in ("score", "error"):
            return {
                **result,
                "changed": False,
                "reason": f"cancel already requested ({pending})",
            }
        if task_retry_abandoned(state.task_id):
            return {
                **result,
                "changed": False,
                "reason": "pending retry already abandoned",
            }
        if not state.task_cancel.can_retry:
            # the retry request will not be honored (no budget remaining —
            # the dispatcher gates on retries_remaining, mirrored by
            # can_retry): no retry is coming, so there is nothing to abandon
            return {
                **result,
                "changed": False,
                "reason": ("task already ending — retry request will not be honored"),
            }
        if not dry_run:
            abandon_task_retry(state.task_id)
        return {**result, "changed": True, "retry_abandoned": True}
    if pending is not None and _ESCALATION_LADDER[stamp] <= _ESCALATION_LADDER[pending]:
        return {
            **result,
            "changed": False,
            "reason": f"cancel already requested ({pending})",
        }
    # a sample mid-materialization — past the queue check but not yet
    # registered in active_samples() — is invisible to this gate; its
    # self-interrupt (task/run.py) downgrades an "error" resolution to
    # "score" when it fails on error, so the auto-fail can't fire there
    if stamp == "error" and any(sample.fails_on_error for sample in active):
        return {
            "ok": False,
            "error": (
                "action 'error' is not permitted when the task's samples "
                "are configured to fail on errors (they will surface errors "
                "of their own accord) — use the 'score' action or a "
                "plain cancel instead"
            ),
        }

    if not dry_run:
        # every stamped type but "retry" suppresses the eval-set's in-run
        # retry, so cancelled samples must read terminal rather than
        # `pending` on the read surface (see design/ctl/task-drain.md
        # "Read-surface additions")
        state.will_retry = False
        if stamp == "abort":
            state.task_cancel.cancel_task("abort")
        elif stamp == "drain":
            # a graceful resolution finishes with a success log deliberately
            # holding fewer samples than planned — record the task so
            # eval-set's completeness check honors the resolution for the
            # life of the run (see task_gracefully_resolved)
            mark_task_gracefully_resolved(state.task_id)
            # the stamp alone: queued samples check it as they leave the
            # queue, initializing samples as they start; in-flight samples
            # are never touched and finish naturally
            state.task_cancel.cancel_task("drain")
        else:
            # graceful like drain — record for the completeness check
            mark_task_gracefully_resolved(state.task_id)
            # stamp the resolution first (queued samples check it as they
            # leave the queue, initializing samples as they start), then
            # interrupt the samples already running. First resolution wins:
            # a sample already interrupted — e.g. a per-sample 'cancel',
            # now inside its logging window (`completed` is stamped only at
            # context exit) — keeps its resolution; overwriting would flip
            # a not-yet-handled 'cancel' to this score/error disposition
            # (the runner reads the live interrupt_action as it handles the
            # interrupt) and re-fire on_interrupt hooks on a sample already
            # being resolved. A fired-but-not-yet-handled limit likewise
            # keeps its disposition: the runner checks interrupt_action
            # before limit_exceeded_error, so interrupting such a sample
            # would hijack the limit outcome (and re-fire on_interrupt on
            # top of the limit's own firing).
            state.task_cancel.cancel_task(stamp)
            for sample in in_flight:
                if (
                    sample.interrupt_action is None
                    and sample.limit_exceeded_error is None
                ):
                    sample.interrupt(stamp)
    return {**result, "changed": True}


async def cancel_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    action: SampleCancelAction = "score",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Cancel one running sample (``POST /evals/<id>/sample/cancel``).

    Interrupts the sample via ``ActiveSample.interrupt(action)`` (unless
    ``dry_run``): ``"score"`` completes it and runs the scorer on the work
    done so far, ``"error"`` marks it errored, ``"cancel"`` records it as
    cancelled (transcript preserved, no scoring, not counted as an error).
    Returns ``None`` when the sample is in neither the live set
    nor the eval's readable samples (the route 404s); a ``changed: False``
    no-op when it has already reached a terminal outcome; ``{"ok": False,
    "error": ...}`` when it can't be interrupted — still queued (no task
    group to cancel yet), or ``action="error"`` on a sample configured to
    fail on errors.
    """
    from inspect_ai._control.state import find_active_sample

    sample = find_active_sample(eval_id, sample_id, epoch)
    if sample is not None and sample.completed is None:
        if sample.started is None:
            return {
                "ok": False,
                "error": (
                    f"sample {sample_id} (epoch {epoch}) is still queued — "
                    "only a running sample can be cancelled"
                ),
            }
        if action == "error" and sample.fails_on_error:
            return {
                "ok": False,
                "error": (
                    "action 'error' is not permitted when the sample is "
                    "configured to fail on errors (it will surface an error "
                    "of its own accord) — use the 'score' or 'cancel' "
                    "action instead"
                ),
            }
        if not dry_run:
            sample.interrupt(action)
        return {
            "ok": True,
            "sample_id": sample.sample.id,
            "epoch": sample.epoch,
            "action": action,
            "dry_run": dry_run,
            "changed": True,
        }

    # Not running: a readable terminal sample is the idempotent no-op;
    # a sample in neither source is unknown (the route 404s).
    from inspect_ai._control.state import sample_error_detail

    detail = await sample_error_detail(eval_id, sample_id, epoch)
    if detail is None:
        return None
    return {
        "ok": True,
        "sample_id": detail.get("sample_id"),
        "epoch": detail.get("epoch"),
        "action": action,
        "dry_run": dry_run,
        "changed": False,
        "status": detail.get("status"),
        "reason": "sample already finished",
    }


def _active_eval_samples(eval_id: str) -> "list[ActiveSample]":
    """The eval's not-yet-terminal active samples (running or initializing)."""
    from inspect_ai.log._samples import active_samples

    return [
        sample
        for sample in active_samples()
        if sample.eval_id == eval_id and sample.completed is None
    ]
