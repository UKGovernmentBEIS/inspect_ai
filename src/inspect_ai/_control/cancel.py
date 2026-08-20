"""Cancel directives for the control channel (phase 3).

The first destructive state-mutating directives — both idempotent and
dry-runnable per the phase-3 agent-shape constraints:

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

- :func:`cancel_sample` — attempt-keyed like the other per-sample operations:
  interrupts one *running* sample via ``ActiveSample.interrupt``, the same
  primitive the in-process TUI and ACP's ``inspect/cancel_sample`` use.
  ``action`` selects the outcome — ``"score"`` completes the sample and runs
  the scorer on the work done so far; ``"error"`` marks it errored (rejected
  when the sample is configured to fail on errors, mirroring the TUI/ACP
  gate, since the auto-fail would race it); ``"cancel"`` records it as
  cancelled — transcript preserved, no scoring, not counted as an error.
  ``"cancel"`` additionally acts on samples that haven't started: it
  withdraws a queued re-run's pending requeue (un-requeue) and cancels a
  never-started sample before it starts (see
  ``design/ctl/queued-sample-cancel.md``).

Both run on the eval's own loop (the control server is embedded), so firing
a cancel scope from a route handler is safe. Results are dicts: ``None``
means the target isn't in this process (the route 404s); ``{"ok": False,
"error": ...}`` is a rejection (the route maps it to a 409); otherwise the
result carries ``changed`` — ``False`` is the idempotent already-in-that-state
no-op (task already finished / cancel already requested / sample already
terminal), so an agent retrying on confusion gets a clean answer rather than
an error.
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
    no-op when it has already finished or a cancel is already in flight (the
    reason names the pending cancel's type — a pending ``retry`` cancel means
    the task will be re-queued, so an abort-intending caller knows to re-issue
    once the retry starts; the one exception is a ``"cancel"`` request
    against a pending score/error resolution, which *escalates* to an abort —
    the graceful path can stall on a hung scorer, and the operator must keep a
    way to tear the task down); ``{"ok": False, "error": ...}`` when
    ``action="error"`` targets samples configured to fail on errors
    (mirroring the sample-level gate — the auto-fail would race it; a sample
    mid-materialization is invisible to this gate, so its self-interrupt
    downgrades an ``error`` resolution to ``score`` instead), when the
    attempt has no cancel handle (defensive — a running attempt registered
    without one, which no production registration produces; reused/synthetic
    evals register finished and take the no-op branch instead) or the task is
    *between attempts* — the latest attempt errored and a retry is queued but
    hasn't started (``EvalState.retry_pending``), so there is nothing to fire
    yet but "already finished" would be a lie the retry then contradicts; the
    rejection tells the caller to re-issue once the retry starts.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

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
        "action": action,
        "dry_run": dry_run,
        "in_flight": len(in_flight),
    }
    if state.completed_at is not None:
        if state.retry_pending:
            return {
                "ok": False,
                "error": (
                    f"task {task_id} is between attempts — the last attempt "
                    "errored and a retry is queued but has not started; "
                    "re-issue the cancel once the retry is running"
                ),
            }
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
    if pending is not None:
        # a "cancel" (abort) request may escalate over a pending
        # score/error resolution; any other combination is the idempotent
        # repeat no-op
        if not (action == "cancel" and pending in ("score", "error")):
            return {
                **result,
                "changed": False,
                "reason": f"cancel already requested ({pending})",
            }
    # a sample mid-materialization — past the queue check but not yet
    # registered in active_samples() — is invisible to this gate; its
    # self-interrupt (task/run.py) downgrades an "error" resolution to
    # "score" when it fails on error, so the auto-fail can't fire there
    if action == "error" and any(sample.fails_on_error for sample in active):
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
        if action == "cancel":
            state.task_cancel.cancel_task("abort")
        else:
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
            state.task_cancel.cancel_task(action)
            for sample in in_flight:
                if (
                    sample.interrupt_action is None
                    and sample.limit_exceeded_error is None
                ):
                    sample.interrupt(action)
    return {**result, "changed": True}


async def cancel_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    action: SampleCancelAction = "score",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Cancel one sample (``POST /evals/<id>/sample/cancel``).

    A *running* sample is interrupted via ``ActiveSample.interrupt(action)``
    (unless ``dry_run``): ``"score"`` completes it and runs the scorer on the
    work done so far, ``"error"`` marks it errored, ``"cancel"`` records it
    as cancelled (transcript preserved, no scoring, not counted as an error).

    ``action="cancel"`` also acts on a sample that hasn't started
    (``design/ctl/queued-sample-cancel.md``): a queued re-run's pending
    requeue is withdrawn (un-requeue — the prior terminal record stands),
    and a never-started sample parked at the sample queue (including a
    ``retry_on_error`` re-park) is cancelled before start — removed from the
    queue, counted ``cancelled``, absent from the log.

    Returns ``None`` when the sample is unknown to this process (the route
    404s); a ``changed: False`` no-op when it has already reached a terminal
    outcome (or was already cancelled before start); ``{"ok": False,
    "error": ...}`` when it can't be cancelled — initializing (past the
    queue but not yet running), not yet at the queue (a retry attempt may
    reuse it from the prior attempt), ``action="score"|"error"`` on a queued
    sample (nothing to score, no error to record), ``action="error"`` on a
    running sample configured to fail on errors, or a task-level gate
    (finished / between attempts / task cancel in flight) closing a queued
    row.
    """
    from inspect_ai._control.state import find_active_sample

    sample = find_active_sample(eval_id, sample_id, epoch)
    if sample is not None and sample.completed is None:
        if sample.started is None:
            return _initializing_reject(sample_id, epoch)
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

    # Not running: the queued flavors resolve synchronously (no await between
    # validation and mutation — design/ctl/queued-sample-cancel.md).
    queued = _cancel_queued_sample(eval_id, sample_id, epoch, action, dry_run)
    if queued is not None:
        return queued

    # Not running and not queued: a readable terminal sample is the
    # idempotent no-op; a planned-but-unqueued sample gets a truthful 409;
    # anything else is unknown (the route 404s).
    from inspect_ai._control.state import sample_error_detail

    detail = await sample_error_detail(eval_id, sample_id, epoch)
    # the await above can span a requeue accept (or a seed arriving at the
    # queue); re-resolve the queued rows so the answer reflects it
    queued = _cancel_queued_sample(eval_id, sample_id, epoch, action, dry_run)
    if queued is not None:
        return queued
    if detail is None:
        return _planned_but_unqueued(eval_id, sample_id, epoch)
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


def _cancel_queued_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    action: "SampleCancelAction",
    dry_run: bool,
) -> dict[str, Any] | None:
    """Resolve the queued-flavor cancel rows; ``None`` when not queued.

    Synchronous end to end (validation, task-level gates, and the mutating
    accept run with no await point on the eval's loop), so an accept can't
    race the parked coroutine leaving the queue — the same argument as
    requeue's ``accept``. See ``design/ctl/queued-sample-cancel.md``.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai._control.requeue import _task_level_reject

    state = get_eval_state(eval_id)
    handle = state.sample_requeue if state is not None else None
    if state is None or handle is None:
        return None

    def result(changed: bool, status: str, reason: str) -> dict[str, Any]:
        return {
            "ok": True,
            "sample_id": sample_id,
            "epoch": epoch,
            "action": action,
            "dry_run": dry_run,
            "changed": changed,
            "status": status,
            "reason": reason,
        }

    def not_cancellable() -> dict[str, Any]:
        return {
            "ok": False,
            "error": (
                f"sample {sample_id} (epoch {epoch}) has not started — "
                "there is no work to score and no error to record; use "
                "`--action cancel` to cancel it before it starts"
            ),
        }

    def departed_reject() -> dict[str, Any]:
        return {
            "ok": False,
            "error": (
                f"sample {sample_id} (epoch {epoch})'s re-run has left "
                "the queue and is initializing — retry once it is "
                "running"
            ),
        }

    # a queued re-run: withdraw the pending requeue (un-requeue) — the prior
    # terminal record stands, and the sample is requeueable again
    prior_status = handle.pending_prior_status(sample_id, epoch)
    if prior_status is not None:
        gated = _task_level_reject(state)
        if gated is not None:
            return {"ok": False, "error": gated["error"]}
        if action != "cancel":
            return not_cancellable()
        # read-only departed check ahead of the dry-run return, so a dry_run
        # probe reports the same 409 the real accept below would
        if handle.pending_departed(sample_id, epoch):
            return departed_reject()
        accepted = result(
            True,
            prior_status,
            "requeue withdrawn — the prior terminal record stands",
        )
        if dry_run:
            return accepted
        outcome = handle.cancel_queued(sample_id, epoch)
        if outcome == "accepted":
            return accepted
        if outcome == "departed":
            return departed_reject()
        return None  # not_pending: fall through and re-resolve

    # already cancelled before start: the idempotent repeat no-op
    if handle.cancelled_state(sample_id, epoch) is not None:
        if action != "cancel":
            return not_cancellable()
        return result(False, "cancelled", "already cancelled")

    # never started (or a retry_on_error re-park), parked at the queue
    if handle.queue_state(sample_id, epoch) == "arrived":
        gated = _task_level_reject(state)
        if gated is not None:
            return {"ok": False, "error": gated["error"]}
        if action != "cancel":
            return not_cancellable()
        accepted = result(
            True, "cancelled", "cancelled before start — removed from the queue"
        )
        if dry_run:
            return accepted
        if handle.cancel_before_start(sample_id, epoch) == "accepted":
            return accepted
        return None  # the queue state moved: fall through and re-resolve

    return None


def _planned_but_unqueued(
    eval_id: str, sample_id: str, epoch: int
) -> dict[str, Any] | None:
    """The truthful 409s for a planned sample with no record and no queue stamp.

    A departed stamp is the blind window between queue exit and
    ``ActiveSample`` registration (initializing); no stamp means the sample
    never reached the queue — on a retry attempt its prior result may be
    mid-reuse, so the rejection is retryable. ``None`` for an unknown
    identity (the route 404s). Upgrades today's 404 for planned samples.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai._control.requeue import _is_planned

    state = get_eval_state(eval_id)
    if state is None or not _is_planned(state, sample_id, epoch):
        return None
    handle = state.sample_requeue
    if handle is not None and handle.queue_state(sample_id, epoch) == "departed":
        return _initializing_reject(sample_id, epoch)
    return {
        "ok": False,
        "error": (
            f"sample {sample_id} (epoch {epoch}) is not at the queue yet "
            "(on a retry attempt it may be reused from the prior attempt "
            "rather than run) — retry"
        ),
    }


def _initializing_reject(sample_id: str, epoch: int) -> dict[str, Any]:
    """The 409 for a sample past the queue but not yet running.

    Mid-materialization (sandbox init may be in flight): there is no task
    group to interrupt and the queue-exit check has already passed, so the
    window is uncancellable — but short and self-resolving.
    """
    return {
        "ok": False,
        "error": (
            f"sample {sample_id} (epoch {epoch}) is initializing (it has "
            "left the queue but is not yet running) — retry once it is "
            "running"
        ),
    }


def _active_eval_samples(eval_id: str) -> "list[ActiveSample]":
    """The eval's not-yet-terminal active samples (running or initializing)."""
    from inspect_ai.log._samples import active_samples

    return [
        sample
        for sample in active_samples()
        if sample.eval_id == eval_id and sample.completed is None
    ]
