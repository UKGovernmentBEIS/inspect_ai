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
at ``ctl.py`` startup where ``log._samples`` is not.
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
