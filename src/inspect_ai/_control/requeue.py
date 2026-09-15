"""Requeue directive for the control channel (phase 3).

Re-adds one errored/cancelled sample to the live run: it goes to the back of
the sample queue and re-runs under the task's normal machinery (shaped like a
single-sample task-level retry — fresh sample uuid, prior errors seeded, a
fresh ``retry_on_error`` budget), and the run's final log and counters
reflect the fresh outcome. ``design/ctl/sample-requeue.md`` owns the semantics
this resolver implements, including the decision table.

Shaped like :mod:`inspect_ai._control.cancel` and runs on the eval's own
loop. Results: ``None`` means the target isn't in this process (the route
404s); :class:`RequeueRejected` is a rejection (the route maps it to a 409);
otherwise the result carries ``changed`` — :class:`RequeueScheduled`
(``False``) is the idempotent already-scheduled no-op (requeue pending /
already queued or running / never started), so a retrying agent gets a clean
answer rather than a double-queued sample, and :class:`RequeueAccepted`
(``True``) is the accepted requeue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai._eval.task.scheduler import SampleQueueView, SampleRequeue

# One string for both drained-fanout rejections (the fast path's handle
# check and ``accept``'s authoritative ``closed`` outcome) so they can't
# drift.
_FANOUT_DRAINED = (
    "task is no longer accepting samples (the sample fanout has "
    "drained) — re-run failures with `inspect eval-retry` (or "
    "re-invoke `inspect eval-set`)"
)


class RequeueRejected(TypedDict):
    """A rejection from the decision table (the route maps it to a 409)."""

    ok: Literal[False]
    error: str


class RequeueScheduled(TypedDict):
    """The idempotent no-op: this sample's (re-)run is already coming.

    ``status`` reports where it stands — ``queued`` (requeue pending or
    waiting for a slot), ``running``, or ``pending`` (planned, never
    started).
    """

    ok: Literal[True]
    sample_id: str | int
    epoch: int
    dry_run: bool
    changed: Literal[False]
    status: Literal["queued", "running", "pending"]
    reason: str


class RequeueAccepted(TypedDict):
    """An accepted requeue (or, under ``dry_run``, what would be re-run).

    ``status`` is the prior terminal outcome the re-run supersedes.
    """

    ok: Literal[True]
    sample_id: str | int
    epoch: int
    dry_run: bool
    changed: Literal[True]
    status: Literal["error", "cancelled"]
    prior_error: str
    retries: int
    attempt: int
    resume_from_checkpoint: bool


class RequeueUncancelled(TypedDict):
    """An accepted un-cancel of a cancelled-before-start sample.

    The cancel-before-start is withdrawn while its coroutine is still parked
    (``design/ctl/queued-sample-cancel.md``): the same parked coroutine
    serves as the run, so ``status`` reports it ``pending`` — it runs when
    it gets a slot, exactly as if never cancelled.
    """

    ok: Literal[True]
    sample_id: str | int
    epoch: int
    dry_run: bool
    changed: Literal[True]
    status: Literal["pending"]
    reason: str


RequeueResult = (
    RequeueRejected | RequeueScheduled | RequeueAccepted | RequeueUncancelled
)


async def requeue_sample(
    eval_id: str, sample_id: str, epoch: int, *, dry_run: bool = False
) -> RequeueResult | None:
    """Requeue one errored/cancelled sample (``POST /evals/<id>/sample/requeue``).

    The task-level checks run before the sample-status ones — necessarily,
    since between attempts (and after teardown) the attempt-scoped requeue
    handle is detached and there is no live sample state to consult. A
    cancelled sample with a task retry pending therefore gets the
    between-attempts rejection, not the terminal-cancelled accept.

    Idempotence: a repeat requeue lands in the already-queued/running rows
    or the pending-requeue set — in that order, so once the re-run is live
    the response reports its true status (``changed: False``). The set is checked
    again, synchronously, inside the handle's ``accept`` — the check here is
    a fast path, but two directives racing past this resolver's async reads
    still can't double-queue. After the re-run reaches a terminal outcome
    the set is clear and the sample is genuinely requeueable again — but
    only from a fresh read: ``accept`` refuses a prior record whose uuid it
    has accepted before (``stale`` → 409), so a directive whose reads
    straddled a full accept → re-run → terminal cycle can't re-run a
    now-completed sample.

    ``dry_run`` reports what would be re-run — the resolved target, its
    prior error and retry count, the attempt number the re-run would be,
    and whether a checkpoint resume is available — without mutating; every
    rejection above reports its error under ``dry_run`` too, so an agent
    can probe safely.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai._control.state import _full_sample, find_active_sample
    from inspect_ai._util.error import is_cancellation_message

    state = get_eval_state(eval_id)
    if state is None:
        return None

    rejected = _task_level_reject(state)
    if rejected is not None:
        return rejected
    handle = state.sample_requeue
    if handle is None or not handle.open:
        return _reject(_FANOUT_DRAINED)

    # already scheduled or in progress: the desired end state — "this sample
    # runs (again) to a fresh outcome" — is already coming. The active check
    # runs first: a pending-requeue key stays set until the re-run goes
    # terminal, so once the re-run is live only the ActiveSample knows
    # whether it is queued or running.
    active = find_active_sample(eval_id, sample_id, epoch)
    if active is not None and active.completed is None:
        status: Literal["queued", "running"] = (
            "running" if active.started is not None else "queued"
        )
        # report the dataset-typed id (int vs str); a dataset sample id is
        # assigned by resolution, so None can't occur here — but the field
        # allows it, and the query-param string is the right fallback
        resolved_id = active.sample.id if active.sample.id is not None else sample_id
        reason = f"sample is already {status}"
        # an initializing sample carrying a deferred `sample cancel` is not
        # un-cancellable the way a cancel-before-start is (the intent fires
        # as it starts — design/ctl/initializing-sample-cancel.md), so name
        # it rather than let "already queued" imply the sample will run
        if status == "queued" and active.interrupt_action is not None:
            reason = (
                f"sample is already {status} with a pending cancel "
                f"({active.interrupt_action}) that resolves as it starts — "
                "requeue it once it has"
            )
        return _scheduled(resolved_id, epoch, dry_run, status, reason)

    # one synchronous snapshot of the key's queue lifecycle
    # (design/ctl/queued-sample-cancel.md): no await separates it from the
    # un-cancel accept below, so the accept needs no re-check
    view = handle.sample_view(sample_id, epoch)
    if view.pending:
        return _scheduled(
            sample_id,
            epoch,
            dry_run,
            "queued",
            "a requeue of this sample is already pending",
        )

    cancelled_row = _resolve_cancelled_key(
        state, handle, view, sample_id, epoch, dry_run
    )
    if cancelled_row is not None:
        return cancelled_row

    # terminal read: the live recorder, then the on-disk log — the full
    # sample, since its events seed the re-run's retry history
    prior = await _full_sample(eval_id, sample_id, epoch)
    if prior is None:
        # the await above can span a cancel-before-start accept (or another
        # directive's requeue of a record this read pre-dated): re-snapshot
        # so the parked un-cancel and the discarded 409 aren't answered
        # "will run without help" by `_is_planned` below — the mirror of
        # `cancel_sample`'s post-await re-resolve
        view = handle.sample_view(sample_id, epoch)
        if view.pending:
            return _scheduled(
                sample_id,
                epoch,
                dry_run,
                "queued",
                "a requeue of this sample is already pending",
            )
        cancelled_row = _resolve_cancelled_key(
            state, handle, view, sample_id, epoch, dry_run
        )
        if cancelled_row is not None:
            return cancelled_row
        # planned but never started will run without help; an unknown
        # (sample_id, epoch) is a 404
        if _is_planned(state, sample_id, epoch):
            return _scheduled(
                sample_id, epoch, dry_run, "pending", "sample has not started yet"
            )
        return None

    if prior.error is None:
        return _reject(
            f"sample {prior.id} (epoch {epoch}) completed successfully — "
            "re-running or re-scoring a completed sample is not supported "
            "(use score invalidation and `inspect eval-retry` for post-hoc "
            "re-runs)"
        )

    prior_status: Literal["error", "cancelled"] = (
        "cancelled" if is_cancellation_message(prior.error.message) else "error"
    )
    retries = len(prior.error_retries or [])
    detail: RequeueAccepted = {
        "ok": True,
        "sample_id": prior.id,
        "epoch": epoch,
        "dry_run": dry_run,
        "changed": True,
        "status": prior_status,
        "prior_error": prior.error.message,
        "retries": retries,
        # the attempt number the re-run would be: prior retries, plus the
        # terminal error when it was genuine (a cancellation is skipped by
        # the seeding, per _seed_error_retries), plus the re-run itself
        "attempt": retries + (1 if prior_status == "error" else 0) + 1,
        "resume_from_checkpoint": await handle.checkpoint_available(prior.id, epoch),
    }
    if dry_run:
        return detail

    # Re-check the task-level gates synchronously before accepting: the
    # awaits above (`_full_sample`, `checkpoint_available`) can span the last
    # sibling's terminal recording, which stamps `completed_at` while the
    # fanout's `outstanding` count (and thus `handle.open`) hasn't caught up
    # — accepting then would start a re-run inside an eval that already
    # reads finished. No await separates this check from `accept`, and both
    # run on the eval's loop, so the gate can't move in between.
    rejected = _task_level_reject(state)
    if rejected is not None:
        return rejected

    outcome = handle.accept(prior, prior_status)
    if outcome == "already_pending":
        return _scheduled(
            sample_id,
            epoch,
            dry_run,
            "queued",
            "a requeue of this sample is already pending",
        )
    if outcome == "stale":
        return _reject(
            "the sample's state changed while this request was resolving "
            "(its prior outcome was already requeued and the re-run has "
            "since finished) — re-issue the requeue to act on its current "
            "status"
        )
    if outcome == "closed":
        return _reject(_FANOUT_DRAINED)
    if outcome == "unknown":
        return None
    return detail


def _reject(error: str) -> RequeueRejected:
    return {"ok": False, "error": error}


def _scheduled(
    sample_id: str | int,
    epoch: int,
    dry_run: bool,
    status: Literal["queued", "running", "pending"],
    reason: str,
) -> RequeueScheduled:
    return {
        "ok": True,
        "sample_id": sample_id,
        "epoch": epoch,
        "dry_run": dry_run,
        "changed": False,
        "status": status,
        "reason": reason,
    }


def _resolve_cancelled_key(
    state: "EvalState",
    handle: "SampleRequeue",
    view: "SampleQueueView",
    sample_id: str,
    epoch: int,
    dry_run: bool,
) -> RequeueResult | None:
    """Route a cancelled-before-start key; ``None`` when not cancelled.

    ``_is_planned`` would answer "will run without help" — a lie for a
    cancelled key. A parked key is un-cancelled (the same parked coroutine
    serves as the run); a discarded one is gone, with no prior record to
    seed a re-run from. ``view`` must be a fresh synchronous snapshot with
    no await before this call: the parked branch's ``uncancel`` accept
    relies on the snapshot still being current (there is no await in here
    either, so the caller's snapshot-then-route block stays synchronous).
    """
    if view.cancelled == "discarded":
        return _reject(
            f"sample {sample_id} (epoch {epoch}) was cancelled before it "
            "started and its run has been discarded — re-run it with "
            "`inspect eval-retry` (or re-invoke `inspect eval-set`)"
        )
    if view.cancelled == "parked":
        # Re-check the task-level gates synchronously before the un-cancel:
        # the caller's top-of-resolver check may pre-date an await (the
        # post-`_full_sample` reroute), and a gate closing during it must
        # win — a cancel-before-start that counted the last outstanding
        # sample stamps `completed_at`, and un-cancelling past that would
        # revive a run inside a finished eval that no directive can reach.
        # Mirrors the per-accepting-branch re-checks in cancel.py.
        rejected = _task_level_reject(state)
        if rejected is not None:
            return rejected
        # the reason is conditional-tense under dry_run so the CLI's "Would
        # requeue …" rendering doesn't embed a past-tense mutation
        uncancelled: RequeueUncancelled = {
            "ok": True,
            "sample_id": view.typed_id,
            "epoch": epoch,
            "dry_run": dry_run,
            "changed": True,
            "status": "pending",
            "reason": (
                "the cancel-before-start would be withdrawn — the sample "
                "would run when it gets a slot"
                if dry_run
                else "cancel-before-start withdrawn — the sample will run "
                "when it gets a slot"
            ),
        }
        if not dry_run:
            handle.uncancel(sample_id, epoch)
        return uncancelled
    return None


def _task_level_reject(state: "EvalState") -> RequeueRejected | None:
    """The task-level rejection rows (finished / between attempts / cancelling).

    Checked before the sample-status rows, and again — synchronously — right
    before ``accept``: the resolver awaits between the two, and a task-level
    gate closing during those awaits must win.
    """
    if state.completed_at is not None:
        if state.retry_pending:
            return _reject(
                "task is between attempts — the last attempt errored and a "
                "retry is queued, which will re-run its failed samples when "
                "it starts"
            )
        return _reject(
            "task already finished — re-run failures with `inspect "
            "eval-retry` (or re-invoke `inspect eval-set`)"
        )
    pending_cancel = (
        state.task_cancel.cancel_type if state.task_cancel is not None else None
    )
    if pending_cancel is not None:
        return _reject(
            f"a task cancel is in flight ({pending_cancel}) — the re-run "
            "would be abandoned as it left the queue"
        )
    return None


def _is_planned(state: "EvalState", sample_id: str, epoch: int) -> bool:
    """Whether ``(sample_id, epoch)`` is one of the eval's planned samples.

    Distinguishes a never-started sample (a clean no-op — it will run) from
    an unknown identity (a 404). ``sample_id`` arrives as a query-param
    string, so integer ids match on ``str`` like the other per-sample
    surfaces.
    """
    if epoch < 1 or epoch > max(1, state.epochs):
        return False
    return any(str(planned) == sample_id for planned in state.sample_ids)
