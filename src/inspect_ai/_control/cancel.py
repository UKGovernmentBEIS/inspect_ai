"""Cancel directives for the control channel (phase 3).

The first destructive state-mutating directives — both idempotent and
dry-runnable per the phase-3 agent-shape constraints:

- :func:`cancel_task` — task-keyed (stable across retries, like ``config`` /
  ``log-flush``): fires the latest attempt's registered ``TaskCancel`` with
  ``"abort"``, the same user-cancel path the in-process task display's cancel
  dialog drives. In-flight samples are interrupted (their transcripts so far
  are preserved in the log as cancelled samples), completed samples are kept,
  partial results are computed, and the log is finalized with an error status
  noting the cancel; an eval-set does not retry an aborted task.
- :func:`cancel_sample` — attempt-keyed like the other per-sample operations:
  interrupts one *running* sample via ``ActiveSample.interrupt``, the same
  primitive the in-process TUI and ACP's ``inspect/cancel_sample`` use.
  ``action`` selects the outcome — ``"score"`` completes the sample and runs
  the scorer on the work done so far; ``"error"`` marks it errored (rejected
  when the sample is configured to fail on errors, mirroring the TUI/ACP
  gate, since the auto-fail would race it).

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

from typing import Any, Literal


def cancel_task(task_id: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Cancel a running task (``POST /tasks/<task-id>/cancel``).

    Resolves the task's latest attempt and fires its ``TaskCancel`` with
    ``"abort"`` (unless ``dry_run``). Returns ``None`` when the task isn't in
    this process; a ``changed: False`` no-op when it has already finished or
    a cancel is already in flight (the reason names the pending cancel's
    type — a pending ``retry`` cancel means the task will be re-queued, so
    an abort-intending caller knows to re-issue once the retry starts);
    ``{"ok": False, "error": ...}`` when the attempt has no cancel handle
    (defensive — a running attempt registered without one, which no
    production registration produces; reused/synthetic evals register
    finished and take the no-op branch instead) or the task is *between
    attempts* — the latest attempt errored and
    a retry is queued but hasn't started (``EvalState.retry_pending``), so
    there is nothing to fire yet but "already finished" would be a lie the
    retry then contradicts; the rejection tells the caller to re-issue once
    the retry starts.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None

    result: dict[str, Any] = {
        "ok": True,
        "task_id": state.task_id,
        "task": state.task,
        "eval_id": state.eval_id,
        "dry_run": dry_run,
        "in_flight": _in_flight_count(state.eval_id),
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
    if state.task_cancel.cancel_type is not None:
        return {
            **result,
            "changed": False,
            "reason": f"cancel already requested ({state.task_cancel.cancel_type})",
        }

    if not dry_run:
        state.task_cancel.cancel_task("abort")
    return {**result, "changed": True}


async def cancel_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    action: Literal["score", "error"] = "score",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Cancel one running sample (``POST /evals/<id>/sample/cancel``).

    Interrupts the sample via ``ActiveSample.interrupt(action)`` (unless
    ``dry_run``). Returns ``None`` when the sample is in neither the live set
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
                    "of its own accord) — use the default 'score' action"
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


def _in_flight_count(eval_id: str) -> int:
    """How many of the eval's samples are currently running (started, not done)."""
    from inspect_ai.log._samples import active_samples

    return sum(
        1
        for sample in active_samples()
        if sample.eval_id == eval_id
        and sample.started is not None
        and sample.completed is None
    )
