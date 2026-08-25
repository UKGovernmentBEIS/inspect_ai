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

- :func:`cancel_tool_call` — attempt-keyed like :func:`cancel_sample`, but
  surgical: fires one in-flight tool call's per-call cancel scope (the same
  ``ToolEvent._cancel()`` primitive ACP's ``inspect/cancel_tool_call`` and
  the in-process TUI's timeout button drive), so the model sees an ordinary
  tool timeout and the sample *continues* rather than ending. See
  design/ctl/tool-call-cancel.md for the full semantics.

All run on the eval's own loop (the control server is embedded), so firing
a cancel scope from a route handler is safe. Results are ``TypedDict``
unions, one variant per outcome (the ``requeue.py`` convention): ``None``
means the target isn't in this process (the route 404s); ``{"ok": False,
"error": ...}`` is a rejection (the route maps it to a 409); otherwise the
result carries ``changed`` — ``False`` is the idempotent already-in-that-state
no-op (task already finished / cancel already requested / sample already
terminal), so an agent retrying on confusion gets a clean answer rather than
an error.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from typing_extensions import NotRequired, TypedDict

if TYPE_CHECKING:
    from inspect_ai.event._tool import ToolEvent
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

SAMPLE_ALREADY_FINISHED_REASON = "sample already finished"
"""``reason`` on the already-terminal cancel no-op row.

Shared with the CLI renderer, which matches this literal to swap in a
status-suffixed message — a constant keeps the coupling explicit so a
rewording here can't silently degrade the rendering.
"""


class CancelTaskRejected(TypedDict):
    """A rejection from the decision table (the route maps it to a 409)."""

    ok: Literal[False]
    error: str


class _CancelTaskResult(TypedDict):
    """Fields shared by every accepted ``cancel_task`` response."""

    ok: Literal[True]
    task_id: str
    task: str
    eval_id: str
    action: TaskCancelAction
    dry_run: bool
    in_flight: int


class CancelTaskNoop(_CancelTaskResult):
    """The idempotent no-op: already finished, or cancel already requested."""

    changed: Literal[False]
    reason: str


class CancelTaskChanged(_CancelTaskResult):
    """The cancel was delivered (or, under ``dry_run``, would be)."""

    changed: Literal[True]


CancelTaskResult = CancelTaskRejected | CancelTaskNoop | CancelTaskChanged


def cancel_task(
    task_id: str,
    *,
    action: TaskCancelAction = "cancel",
    dry_run: bool = False,
) -> CancelTaskResult | None:
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
    result: _CancelTaskResult = {
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


class CancelSampleRejected(TypedDict):
    """A rejection (409): still queued, or ``error`` on a fail-on-error sample."""

    ok: Literal[False]
    error: str


class CancelSampleChanged(TypedDict):
    """The interrupt was delivered (or, under ``dry_run``, would be)."""

    ok: Literal[True]
    sample_id: str | int | None
    epoch: int
    action: SampleCancelAction
    dry_run: bool
    changed: Literal[True]


class CancelSampleFinished(TypedDict):
    """The already-terminal no-op (fields echo ``sample_error_detail``)."""

    ok: Literal[True]
    sample_id: str | int | None
    epoch: int | None
    action: SampleCancelAction
    dry_run: bool
    changed: Literal[False]
    status: str | None
    reason: str


class CancelSampleQueued(TypedDict):
    """An accepted queued-row cancel (``design/ctl/queued-sample-cancel.md``).

    ``status`` is the prior terminal status for an un-requeue, or
    ``"cancelled"`` for a cancel-before-start. ``reason`` reports what
    happened — in conditional tense under ``dry_run``, so the CLI's
    "Would cancel …" rendering doesn't embed a past-tense mutation.
    """

    ok: Literal[True]
    sample_id: str | int
    epoch: int
    action: SampleCancelAction
    dry_run: bool
    changed: Literal[True]
    status: str
    reason: str


CancelSampleResult = (
    CancelSampleRejected
    | CancelSampleChanged
    | CancelSampleQueued
    | CancelSampleFinished
)


async def cancel_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    action: SampleCancelAction = "score",
    dry_run: bool = False,
) -> CancelSampleResult | None:
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
        "reason": SAMPLE_ALREADY_FINISHED_REASON,
    }


def _cancel_queued_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    action: "SampleCancelAction",
    dry_run: bool,
) -> CancelSampleResult | None:
    """Resolve the queued-flavor cancel rows; ``None`` when not queued.

    Synchronous end to end (validation, task-level gates, and the mutating
    accept run with no await point on the eval's loop), so an accept can't
    race the parked coroutine leaving the queue — the same argument as
    requeue's ``accept``. The handle mutators (``cancel_queued``,
    ``cancel_before_start``) assert what this resolver validated rather than
    re-branching — a second validation layer here would be unreachable.
    See ``design/ctl/queued-sample-cancel.md``.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai._control.requeue import _task_level_reject

    state = get_eval_state(eval_id)
    handle = state.sample_requeue if state is not None else None
    if state is None or handle is None:
        return None
    typed_id = handle.typed_sample_id(sample_id, epoch)

    def accepted(status: str, reason: str) -> CancelSampleQueued:
        return {
            "ok": True,
            "sample_id": typed_id,
            "epoch": epoch,
            "action": action,
            "dry_run": dry_run,
            "changed": True,
            "status": status,
            "reason": reason,
        }

    def not_cancellable() -> CancelSampleRejected:
        return {
            "ok": False,
            "error": (
                f"sample {sample_id} (epoch {epoch}) has not started — "
                "there is no work to score and no error to record; use "
                "`--action cancel` to cancel it before it starts"
            ),
        }

    # a queued re-run: withdraw the pending requeue (un-requeue) — the prior
    # terminal record stands, and the sample is requeueable again
    prior_status = handle.pending_prior_status(sample_id, epoch)
    if prior_status is not None:
        gated = _task_level_reject(state)
        if gated is not None:
            return {"ok": False, "error": gated["error"]}
        # the departed blind window refuses every action (the run is
        # mid-materialization and will terminal-record on its own), so it
        # answers before the action gate: not_cancellable()'s "use
        # `--action cancel`" advice would immediately 409 here
        if handle.pending_departed(sample_id, epoch):
            return {
                "ok": False,
                "error": (
                    f"sample {sample_id} (epoch {epoch})'s re-run has left "
                    "the queue and is initializing — retry once it is "
                    "running"
                ),
            }
        if action != "cancel":
            return not_cancellable()
        row = accepted(
            prior_status,
            "the requeue would be withdrawn — the prior terminal record stands"
            if dry_run
            else "requeue withdrawn — the prior terminal record stands",
        )
        if not dry_run:
            handle.cancel_queued(sample_id, epoch)
        return row

    # already cancelled (before start, or drain-abandoned while queued): the
    # idempotent repeat no-op
    if handle.cancelled_state(sample_id, epoch) is not None:
        if action != "cancel":
            # not not_cancellable(): its "use `--action cancel`" hint would
            # point at the no-op row below
            return {
                "ok": False,
                "error": (
                    f"sample {sample_id} (epoch {epoch}) was cancelled "
                    "before it started — there is no work to score and "
                    "no error to record"
                ),
            }
        return {
            "ok": True,
            "sample_id": typed_id,
            "epoch": epoch,
            "action": action,
            "dry_run": dry_run,
            "changed": False,
            "status": "cancelled",
            "reason": "already cancelled",
        }

    # never started (or a retry_on_error re-park), parked at the queue
    if handle.queue_state(sample_id, epoch) == "arrived":
        gated = _task_level_reject(state)
        if gated is not None:
            return {"ok": False, "error": gated["error"]}
        if action != "cancel":
            return not_cancellable()
        row = accepted(
            "cancelled",
            "the sample would be cancelled before it starts and removed from the queue"
            if dry_run
            else "cancelled before start — removed from the queue",
        )
        if not dry_run:
            handle.cancel_before_start(sample_id, epoch)
        return row

    return None


def _planned_but_unqueued(
    eval_id: str, sample_id: str, epoch: int
) -> CancelSampleRejected | None:
    """The truthful 409s for a planned sample with no record and no queue stamp.

    The task-level gates answer first: once the task has finished (or a
    cancel is in flight) the retry advice below would have no exit — e.g. a
    sample that completed under ``log_samples=False`` keeps its departed
    stamp and never gains a readable record, and a drain-abandoned queued
    sample resolves only through the cancelled-keys stamp. Past the gates, a
    departed stamp is the blind window between queue exit and
    ``ActiveSample`` registration (initializing); no stamp means the sample
    never reached the queue — on a retry attempt its prior result may be
    mid-reuse, so the rejection is retryable. ``None`` for an unknown
    identity (the route 404s). Upgrades today's 404 for planned samples.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai._control.requeue import _is_planned, _task_level_reject

    state = get_eval_state(eval_id)
    if state is None or not _is_planned(state, sample_id, epoch):
        return None
    gated = _task_level_reject(state)
    if gated is not None:
        return {"ok": False, "error": gated["error"]}
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


def _initializing_reject(sample_id: str, epoch: int) -> CancelSampleRejected:
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


class PendingToolCall(TypedDict):
    """One pending tool call's row (see :func:`_pending_tool_call`)."""

    id: str
    function: str
    started_at: float
    cancel_requested: bool


class CancelToolCallRejected(TypedDict):
    """A rejection from the decision table (the route maps it to a 409).

    Either an ambiguous target (``pending`` enumerates the candidates) or a
    pending match with no cancel hook installed.
    """

    ok: Literal[False]
    error: str
    pending: NotRequired[list[PendingToolCall]]


class _CancelToolCallResult(TypedDict):
    """Fields shared by every accepted live-sample response."""

    ok: Literal[True]
    sample_id: str | int | None
    epoch: int
    dry_run: bool


class CancelToolCallUnmatched(_CancelToolCallResult):
    """No pending match for an explicit id (``pending`` lists the candidates).

    The ``reason`` strings on these no-op variants are ``Literal`` — each is
    the variant's discriminant, so consumers can narrow the union on it.
    """

    changed: Literal[False]
    reason: Literal["no pending tool call with that id"]
    pending: list[PendingToolCall]


class CancelToolCallNoPending(_CancelToolCallResult):
    """No pending tool calls at all (``activity`` names the actual stall)."""

    changed: Literal[False]
    reason: Literal["no pending tool calls"]
    activity: dict[str, Any] | None


class _CancelToolCallEcho(TypedDict):
    """Echo of the targeted call."""

    tool_call_id: str
    function: str
    started_at: float
    running_time: float


class CancelToolCallAlreadyRequested(_CancelToolCallResult, _CancelToolCallEcho):
    """The repeat no-op: a cancel was already delivered to this call."""

    changed: Literal[False]
    reason: Literal["cancel already requested"]


class CancelToolCallChanged(_CancelToolCallResult, _CancelToolCallEcho):
    """The cancel was delivered to the cancel scope (or would be, under ``dry_run``)."""

    changed: Literal[True]


class CancelToolCallFinished(TypedDict):
    """The already-terminal no-op (fields echo ``sample_error_detail``)."""

    ok: Literal[True]
    sample_id: str | int | None
    epoch: int | None
    dry_run: bool
    changed: Literal[False]
    status: str | None
    reason: Literal["sample already finished"]


CancelToolCallResult = (
    CancelToolCallRejected
    | CancelToolCallUnmatched
    | CancelToolCallNoPending
    | CancelToolCallAlreadyRequested
    | CancelToolCallChanged
    | CancelToolCallFinished
)


async def cancel_tool_call(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    tool_call_id: str | None = None,
    dry_run: bool = False,
) -> CancelToolCallResult | None:
    """Cancel one in-flight tool call (``POST /evals/<id>/sample/cancel-tool-call``).

    Scans the sample's pending events for a pending ``ToolEvent`` — the same
    rule as ACP's ``inspect/cancel_tool_call``: pending events are never
    evicted from a bounded transcript, and nested sub-agent tool calls
    (``task`` dispatch / ``as_tool`` / ``handoff``) record into the same
    sample transcript, so they are reachable; scanning full history would
    materialize evicted events for calls that can no longer be cancelled —
    and fires the match's per-call cancel scope via ``ToolEvent._cancel()``
    (unless ``dry_run``). The model then sees an ordinary tool timeout
    (``ToolCallError("timeout")`` — the established operator-cancel contract
    shared with the ACP/TUI paths) and the sample continues.

    ``tool_call_id`` is optional with a fail-closed fallback: exactly one
    pending tool call is an unambiguous target; two or more is a rejection
    enumerating them (``pending`` in the result) — a mutation must not guess
    among targets, and per the control channel's no-fan-out convention must
    not cancel them all. ``dry_run`` without an id therefore doubles as
    "show me the pending tool calls".

    ``changed: true`` means the cancel was *delivered* to the call's cancel
    scope, not that the tool has stopped — anyio cancellation is cooperative,
    so a call wedged in sync-in-thread code or shielded teardown may never
    unwind (the event then stays pending with ``cancelled`` set, and a repeat
    reports the "cancel already requested" no-op).

    Returns ``None`` when the sample is in neither the live set nor the
    eval's readable samples (the route 404s); ``{"ok": False, "error": ...}``
    on the ambiguity rejection above or a pending match with no cancel hook
    installed (defensive — production dispatch always installs one before the
    event reaches the transcript; an honest error beats a success-shaped
    no-op); otherwise ``changed: false`` no-ops for the already-holds states:
    cancel already requested, no pending match for an explicit id (completed,
    or never existed — the response lists the currently-pending calls so a
    typo'd id is visible), no pending tool calls at all (the response carries
    the sample's current activity, redirecting the operator to the real
    stall), or a sample that already finished.

    There is no await between the pending scan and ``_cancel()`` and
    everything runs on the eval's single loop, so there is no scan-to-fire
    race (the same argument as :func:`cancel_sample`'s check-then-interrupt).
    """
    from inspect_ai._control.state import find_active_sample
    from inspect_ai.event._tool import ToolEvent

    sample = find_active_sample(eval_id, sample_id, epoch)
    if sample is not None and sample.completed is None:
        pending = [
            event
            for event in sample.transcript.pending_events
            if isinstance(event, ToolEvent) and event.pending
        ]
        result: _CancelToolCallResult = {
            "ok": True,
            "sample_id": sample.sample.id,
            "epoch": sample.epoch,
            "dry_run": dry_run,
        }
        target: ToolEvent
        if tool_call_id is not None:
            match = next((e for e in pending if e.id == tool_call_id), None)
            if match is None:
                return {
                    **result,
                    "changed": False,
                    "reason": "no pending tool call with that id",
                    "pending": [_pending_tool_call(e) for e in pending],
                }
            target = match
        elif len(pending) == 0:
            from inspect_ai._control.state import _sample_activity

            # a still-queued sample falls out here too (it can have no
            # pending tools); the activity names where the sample actually
            # is (a pending generate, a retry wait, or nothing yet)
            return {
                **result,
                "changed": False,
                "reason": "no pending tool calls",
                "activity": _sample_activity(sample),
            }
        elif len(pending) > 1:
            calls = [_pending_tool_call(e) for e in pending]
            listing = ", ".join(
                f"{_flatten_token(c['id'])} ({_flatten_token(c['function'])})"
                for c in calls
            )
            return {
                "ok": False,
                "error": (
                    f"sample {sample_id} (epoch {epoch}) has {len(pending)} "
                    "pending tool calls — pass an explicit tool_call_id to "
                    f"pick one: {listing}"
                ),
                "pending": calls,
            }
        else:
            target = pending[0]

        started_at = target.timestamp.timestamp()
        echo: _CancelToolCallEcho = {
            "tool_call_id": target.id,
            "function": target.function,
            "started_at": started_at,
            "running_time": max(0.0, time.time() - started_at),
        }
        # checked BEFORE calling _cancel() so the response distinguishes
        # "this request cancelled it" from "already cancelled" (which ACP's
        # post-state-only return cannot)
        if target.cancelled:
            return {
                **result,
                **echo,
                "changed": False,
                "reason": "cancel already requested",
            }
        if target._cancel_fn is None:
            return {
                "ok": False,
                "error": (
                    f"tool call {_flatten_token(target.id)} "
                    f"({_flatten_token(target.function)}) cannot be "
                    "cancelled — no cancel hook is installed on it"
                ),
            }
        if not dry_run:
            target._cancel()
        return {**result, **echo, "changed": True}

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
        "dry_run": dry_run,
        "changed": False,
        "status": detail.get("status"),
        "reason": "sample already finished",
    }


def _flatten_token(value: str) -> str:
    """Flatten control characters in a model-influenceable token.

    Tool-call ids and function names originate with the model/provider, and
    the rejection messages above embed them in strings the CLI prints
    verbatim (its transport sanitizer deliberately preserves newlines) — so
    a newline-bearing token could forge extra terminal lines. Structured
    fields need no flattening (JSON encoding escapes them); only the human
    message strings do.
    """
    return "".join(ch if ch.isprintable() else " " for ch in value)


def _pending_tool_call(event: "ToolEvent") -> PendingToolCall:
    """One pending tool call's row in enumeration responses.

    Also the ``calls`` row shape on the sample listing's tool activity —
    ``_sample_activity`` builds its rows with this function, so the ambiguity
    rejection and the read surface can't drift apart. ``cancel_requested``
    surfaces a delivered-but-unheeded cancel (a wedged call that no scope
    can stop).
    """
    return {
        "id": event.id,
        "function": event.function,
        "started_at": event.timestamp.timestamp(),
        "cancel_requested": event.cancelled,
    }


def _active_eval_samples(eval_id: str) -> "list[ActiveSample]":
    """The eval's not-yet-terminal active samples (running or initializing)."""
    from inspect_ai.log._samples import active_samples

    return [
        sample
        for sample in active_samples()
        if sample.eval_id == eval_id and sample.completed is None
    ]
