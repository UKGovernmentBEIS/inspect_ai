"""Live sample fanout for one task attempt (the injectable sample scheduler).

Replaces the one-shot ``tg_collect`` fanout in ``task_run`` so samples can be
added while the task runs: all planned ``(sample_index, epoch)`` coroutines
start up front (unchanged behaviour), and a dispatcher loop inside the same
task group drains entries injected while the fanout is live, starting each
inside the group — a route handler must not ``start_soon`` into a nursery it
isn't inside. Two kinds of entry arrive mid-run: re-runs accepted by the
control channel's sample-requeue directive (see
``design/ctl/sample-requeue.md``) and fresh samples a ``SampleSource`` adds
(``task_run``'s dynamic path runs its source-consuming feeder inside the
fanout via :meth:`SampleScheduler.run`'s ``feeder`` argument, spawning through
:meth:`SampleScheduler.add`). Results collect into a dict keyed by
``(sample_index, epoch)`` so a re-run's fresh score replaces the prior
attempt's entry (metrics follow the log, which supersedes by the same key),
returned in plan order like the ``tg_collect`` list it replaces. The fanout
closes when no sample is outstanding, nothing is pending, and no feeder hold
remains; a requeue after that is rejected.

:class:`SampleScheduler` is the generic fanout; :class:`SampleRequeue` is the
requeue-policy capability registered on the process-global ``EvalState`` — it
resolves sample ids to fanout indexes, owns the pending-requeue set that makes
a double requeue idempotent, and performs the counter reconciliation the
directive's accept path requires.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Literal,
    NamedTuple,
    Protocol,
    TypeVar,
)

import anyio

from inspect_ai._util._async import Wake

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

if TYPE_CHECKING:
    from inspect_ai._eval.task.error import SampleErrorHandler
    from inspect_ai.log._log import EvalSample
    from inspect_ai.scorer._metric import SampleScore

T = TypeVar("T")


class Discarded:
    """Type of the :data:`DISCARDED` sentinel (for return annotations)."""

    def __repr__(self) -> str:
        return "DISCARDED"


DISCARDED = Discarded()
"""Sentinel result for a discarded sample run.

Returned instead of a real result when a run is abandoned without recording
anything (a queued-sample cancel's deferred discard, or a task-cancel drain
abandoning a still-queued sample — see ``design/ctl/queued-sample-cancel.md``).
``run_one`` skips the results write for it: writing (even ``None``) would
clobber a prior attempt's keyed result — e.g. a ``score_on_error`` prior's
score dict — and desync metrics from the log.
"""

RequeueOutcome = Literal["accepted", "already_pending", "stale", "closed", "unknown"]
"""Result of :meth:`SampleRequeue.accept`.

``already_pending`` is the idempotent double-queue guard (a requeue for this
key was already accepted and its re-run hasn't reached a terminal outcome);
``stale`` means this exact terminal record was accepted once before — the
caller's reads straddled a full accept → re-run → terminal cycle, so its
``prior`` no longer describes the sample's current state; ``closed`` means
the fanout has drained (nothing outstanding to keep the task open);
``unknown`` means the sample id isn't part of this attempt's plan.
"""


class SampleKey(NamedTuple):
    """A string-normalized ``(sample_id, epoch)`` bookkeeping key.

    ``sample_id`` is always the ``str()`` form of the dataset id — the
    control channel routes on strings, so an int-id dataset must land on the
    same key (:class:`SampleQueueView`'s ``typed_id`` recovers the dataset
    type for read surfaces). The NamedTuple keeps this key space nominally
    distinct from the two it is easily confused with: the dataset-typed
    ``SampleIdEpoch`` (``run.py``) and the fanout's positional
    ``(sample_index, epoch)`` plan keys — a bare ``tuple[str, int]`` is
    assignable to both.
    """

    sample_id: str
    epoch: int


class RequeueAccept(Protocol):
    """Runner-side reconciliation for an accepted requeue.

    Invoked synchronously by :meth:`SampleRequeue.accept`: retracts the prior
    terminal outcome's progress tick and superseded score for
    ``(sample_id, epoch)`` from the live results, returning the retracted
    score (``None`` when the prior was unscored) so ``accept`` can stash it
    for a possible withdraw.
    """

    def __call__(
        self, sample_id: str | int, epoch: int
    ) -> dict[str, SampleScore] | None: ...


class RequeueWithdraw(Protocol):
    """Inverse of :class:`RequeueAccept`, for a withdrawn (un-requeued) entry.

    Invoked synchronously by :meth:`SampleRequeue.cancel_queued`: the
    withdrawn re-run never runs, so the prior outcome's progress tick and
    ``popped_score`` (the score :class:`RequeueAccept` retracted, when the
    prior scored) stand again.
    """

    def __call__(
        self,
        sample_id: str | int,
        epoch: int,
        popped_score: dict[str, SampleScore] | None,
    ) -> None: ...


@dataclass
class _SampleRun:
    """One sample-run coroutine's identity and queue lifecycle.

    Every run gets one — initial seeds, requeued re-runs, and source adds
    alike — created where the coroutine is spawned. The queue-lifecycle
    flags live *only* here, never in a keyed map: stamping the run object
    can't alias another coroutine for the same key (after an un-requeue plus
    a fresh requeue, a re-run key belongs to the fresh coroutine).
    :class:`SampleRequeue` keeps a ``current_run`` map from each key to
    whichever run currently owns it, for the read surface
    (see ``design/ctl/queued-sample-cancel.md``).
    """

    sample_index: int
    epoch: int
    prior: "EvalSample | None" = None
    """For a re-run, the prior terminal record it seeds from (retry history /
    checkpoint resume — see ``run_sample``'s requeue path in ``run.py``);
    ``None`` for an initial seed or a fresh (source-added) entry."""
    on_terminal: Callable[[], None] | None = None
    """Invoked when a re-run reaches a terminal outcome (clears the
    pending-requeue key, making the sample requeueable again, and reverts
    the key's owning run to the one the requeue superseded). Disarmed
    (set ``None``) when the entry is withdrawn by an un-requeue: the key may
    by then belong to a fresh requeue, which the withdrawn zombie must not
    un-mark (see ``design/ctl/queued-sample-cancel.md``)."""
    cancelled: bool = False
    """The run is cancelled and discards at its next check point without
    seeding, recording, or writing a result. Set by an un-requeue accept
    (a withdrawn re-run), a cancel-before-start accept (a parked key-based
    run — ``"parked"`` until it departs, then ``"discarded"``), or a
    task-cancel drain abandoning a key-based run. Always read off the run
    object itself, never via a key lookup — see the class docstring."""
    arrived: bool = False
    """Whether this run has reached the sample queue (stamped immediately
    before the semaphore park). Never true for a run whose result is reused
    from a prior attempt — the cancel-before-start accept requires exactly
    arrived-and-not-departed, so an unarrived key fails closed."""
    departed: bool = False
    """Whether this run has left the sample queue (stamped at the queue-exit
    check; re-cleared when a ``retry_on_error`` re-park re-arrives). A
    departed run is invisible until its ``ActiveSample`` registers, so the
    cancel accepts refuse it rather than half-cancelling a run that will
    also terminal-record on its own."""
    typed_id: str | int | None = None
    """The dataset-typed sample id, captured at queue arrival: the queued
    read surfaces have no record to read a typed id from, and the planned-id
    recovery dies with ``EvalState.sample_ids`` at ``completed_at`` — the
    run object survives, so a cancelled row's id can't flip int → str."""


class SampleScheduler:
    """The task's live sample fanout: initial samples plus mid-run entries.

    Single-loop discipline is what makes it race-free: :meth:`requeue` and
    :meth:`add` are synchronous (no await between the open-check and the
    enqueue), so a dispatcher woken by the last outstanding sample's
    decrement observes any increment that preceded it, and two concurrent
    directives can't both enqueue the same entry.
    """

    def __init__(self) -> None:
        self._plan: list[tuple[int, int]] = []
        self._outstanding = 0
        self._holds = 0
        self._pending: list[_SampleRun] = []
        self._running = False
        self._wake = Wake()

    @property
    def open(self) -> bool:
        """Whether the fanout can still accept a re-run.

        Pending entries are counted in ``outstanding`` from the moment they
        are accepted, so ``outstanding == 0`` (with no feeder hold) means the
        dispatcher is exiting (or has exited) and the task is finishing —
        accepting then would be a lie (the re-run could never start). A live
        feeder holds the fanout open even when nothing is running (the
        source may yet produce more), so a requeue arriving while the run
        idles on ``next_samples()`` is accepted and starts immediately.
        """
        return self._running and (self._outstanding > 0 or self._holds > 0)

    @property
    def outstanding(self) -> int:
        """Sample runs in flight or pending (excludes feeder holds)."""
        return self._outstanding

    def requeue(self, rerun: _SampleRun) -> bool:
        """Enqueue a re-run; False when the fanout has drained (or not begun)."""
        if not self.open:
            return False
        self._outstanding += 1
        self._pending.append(rerun)
        self._wake.set()
        return True

    def add(self, entries: list[tuple[int, int]]) -> None:
        """Enqueue fresh ``(sample_index, epoch)`` entries (source additions).

        Called by the feeder (which runs inside :meth:`run`'s task group, so
        the fanout is necessarily live). Entries extend the plan, preserving
        arrival order in the returned results.
        """
        self._plan.extend(entries)
        self._outstanding += len(entries)
        self._pending.extend(
            _SampleRun(sample_index=index, epoch=epoch) for index, epoch in entries
        )
        self._wake.set()

    async def run(
        self,
        plan: list[tuple[int, int]],
        run_sample: Callable[[int, int, "_SampleRun"], Awaitable[T]],
        *,
        feeder: Callable[[], Awaitable[None]] | None = None,
        on_settle: Callable[[], None] | None = None,
    ) -> dict[tuple[int, int], T]:
        """Run every planned ``(sample_index, epoch)`` plus mid-run entries.

        ``feeder`` (the dynamic path's source consumer) runs inside the same
        task group and holds the fanout open until it returns — so the run
        doesn't finish while the source may still produce, and exceptions it
        raises (duplicate ids, sandbox startup failures) tear the task down
        like a sample's would. ``on_settle`` is invoked (synchronously) after
        each run reaches a terminal outcome, letting the feeder wake and
        re-check whether the run has gone idle.

        Exception semantics match ``tg_collect`` (which this replaces): the
        first inner exception propagates (tearing the group down), so a
        sample error under strict ``fail_on_error`` still aborts the task
        exactly as before. Results also come back in **plan order**, matching
        ``tg_collect``: insertion order is completion order, which would make
        epoch-reducer inputs (``mode`` tie-breaks by first occurrence) and
        the logged reductions nondeterministic run to run.
        """
        results: dict[tuple[int, int], T] = {}
        # count the full plan (and the feeder hold) before the first await so
        # `open` (which the accept path checks) is accurate from the moment
        # the requeue handle becomes visible
        self._plan = list(plan)
        self._outstanding = len(plan)
        self._running = True
        if feeder is not None:
            self._holds += 1
        try:
            async with anyio.create_task_group() as tg:

                async def run_feeder(feeder: Callable[[], Awaitable[None]]) -> None:
                    try:
                        await feeder()
                    finally:
                        self._holds -= 1
                        self._wake.set()

                if feeder is not None:
                    tg.start_soon(run_feeder, feeder)

                async def run_one(
                    sample_index: int, epoch: int, entry: _SampleRun
                ) -> None:
                    try:
                        result = await run_sample(sample_index, epoch, entry)
                        # a discard never writes: even a None write would
                        # clobber a prior attempt's keyed result (see
                        # DISCARDED)
                        if result is not DISCARDED:
                            results[(sample_index, epoch)] = result
                    finally:
                        if entry.on_terminal is not None:
                            entry.on_terminal()
                        self._outstanding -= 1
                        self._wake.set()
                        if on_settle is not None:
                            on_settle()

                for sample_index, epoch in plan:
                    tg.start_soon(
                        run_one,
                        sample_index,
                        epoch,
                        _SampleRun(sample_index=sample_index, epoch=epoch),
                    )

                # dispatcher: start mid-run entries until nothing is
                # outstanding and no feeder hold remains (pending entries
                # count toward outstanding, so outstanding == 0 implies the
                # pending list is empty too)
                while self._outstanding > 0 or self._holds > 0:
                    if self._pending:
                        entry = self._pending.pop(0)
                        tg.start_soon(run_one, entry.sample_index, entry.epoch, entry)
                        continue
                    await self._wake.wait()
        except ExceptionGroup as ex:
            raise ex.exceptions[0] from None
        finally:
            self._running = False
            # A teardown (fail_on_error threshold, task cancel) can leave
            # accepted re-runs the dispatcher never started; fire their
            # terminal callbacks so pending-requeue keys don't outlive the
            # task (a leaked key renders the sample `queued` forever).
            while self._pending:
                entry = self._pending.pop()
                if entry.on_terminal is not None:
                    entry.on_terminal()
        # re-runs replace at the same key, so the plan covers every key
        return {key: results[key] for key in self._plan if key in results}


@dataclass
class _PendingRequeue:
    """Bookkeeping for one accepted, not-yet-terminal requeue.

    Kept per pending key so an un-requeue (``cancel_queued``) can find the
    live entry to flag and perform the full inverse of ``accept``'s
    reconciliation (see ``design/ctl/queued-sample-cancel.md``).
    """

    entry: _SampleRun
    sample_id: str | int
    """The prior record's dataset-typed id (progress/score restore keys on it)."""
    prior_status: Literal["error", "cancelled"]
    """The bucket ``accept`` decremented — restored verbatim on withdraw,
    never re-classified."""
    prior_uuid: str | None
    popped_score: dict[str, SampleScore] | None
    """The superseded score ``on_accept`` retracted (``None`` when the prior
    was unscored), re-inserted on withdraw."""
    superseded_run: _SampleRun | None
    """The run that owned the key when the requeue was accepted (usually the
    departed seed; ``None`` when no run ever reached the queue). Key
    ownership reverts to it when the re-run goes terminal or is withdrawn —
    leaving a terminal re-run as owner would misread in the teardown window
    (a parked re-run reaped by the task group would leave the key
    "arrived")."""


class SampleQueueView(NamedTuple):
    """One key's queue/requeue lifecycle, snapshotted synchronously.

    The single read surface the control-channel resolvers
    (``_control/cancel.py``, ``_control/requeue.py``) and the listing
    synthesis (``_control/state.py``) consume, instead of stitching per-facet
    accessors together. Built with no await point, so a resolver that takes
    a view and mutates in the same synchronous block acts on current state.
    """

    pending: bool
    """A requeue for the key is accepted and its re-run not yet re-terminal."""
    prior_status: Literal["error", "cancelled"] | None
    """The pending requeue's prior terminal status (``None`` when not pending)."""
    pending_departed: bool
    """The pending re-run has left the queue — the departed blind window
    between queue exit and ``ActiveSample`` registration, where the cancel
    resolver refuses the un-requeue (real and ``dry_run`` alike)."""
    queue: Literal["arrived", "departed"] | None
    """The owning run's queue-lifecycle stamp (``None`` = never reached the
    queue; cycles back to ``"arrived"`` across ``retry_on_error`` re-parks).
    The cancel-before-start accept requires exactly ``"arrived"``: absence
    fails closed (a reuse-bound key on a retry attempt never queues), and
    ``"departed"`` is the blind window before the run's ``ActiveSample``
    registers."""
    cancelled: Literal["parked", "discarded"] | None
    """Cancelled-before-start state: ``"parked"`` until the zombie coroutine
    drains at the queue-exit check, then ``"discarded"``. The distinction
    matters to the requeue resolver — a parked key can be un-cancelled (the
    same coroutine still serves), a discarded one cannot."""
    typed_id: str | int
    """The dataset-typed id for the route-string key (str passthrough for a
    key never captured — defensive; every pending or arrived key was)."""


class SampleRequeue:
    """Attempt-scoped requeue capability (``design/ctl/sample-requeue.md``).

    Registered on the process-global ``EvalState`` by ``task_run`` when the
    sample fanout starts (mirroring ``TaskCancel``) and invoked by the
    control channel's requeue resolver (``_control/requeue.py``) on the
    eval's own loop. Detached when a task retry supersedes the attempt, like
    ``EvalState.live``.

    Also owns the queued-sample cancel state
    (``design/ctl/queued-sample-cancel.md``): the ``current_run`` map from
    each key to the run whose lifecycle stamps the cancel resolver's
    at-the-queue gate reads (including the cancelled-before-start outcomes,
    which outlive their coroutines), and the withdraw (un-requeue) /
    un-cancel accepts — it has exactly the right lifecycle (registered when
    the fanout starts, detached on retry).
    """

    def __init__(
        self,
        *,
        eval_id: str,
        scheduler: SampleScheduler,
        sample_error: "SampleErrorHandler",
        sample_indexes: dict[str, int],
        checkpoints_dir: str | None,
        on_accept: RequeueAccept,
        on_withdraw: RequeueWithdraw,
    ) -> None:
        self._eval_id = eval_id
        self._scheduler = scheduler
        self._sample_error = sample_error
        self._sample_indexes = sample_indexes
        self._checkpoints_dir = checkpoints_dir
        self._on_accept = on_accept
        self._on_withdraw = on_withdraw
        # keys accepted but not yet re-terminal — the idempotent double-queue
        # guard, covering the whole window from accept until the re-run
        # records its terminal outcome (including the park at the sample
        # semaphore, where the re-run has no ActiveSample yet). The value is
        # the bookkeeping an un-requeue needs to withdraw the entry.
        self._pending: dict[SampleKey, _PendingRequeue] = {}
        # uuids of prior records already accepted once: a directive whose
        # reads straddled a full accept → re-run → terminal cycle arrives
        # with a stale `prior` after the pending key has cleared, and
        # accepting it would re-run a possibly-completed sample (and
        # double-decrement the counters). A legitimate re-requeue after a
        # second failure carries the re-run's fresh uuid, so it still passes.
        self._accepted_uuids: set[str] = set()
        # whichever run currently owns each key, for the read surface: the
        # lifecycle flags live on the run objects themselves (stamped by the
        # queue hooks — never keyed, so a stamp can't alias another
        # coroutine for the same key). A key-based run (initial seed or
        # source add) owns its key from queue arrival on — and keeps it
        # forever, so a cancelled-before-start outcome outlives its
        # coroutine (there is, and will be, no log record to read it from,
        # including after `sample_ids` clears). A re-run owns the key from
        # its arrival until it goes terminal or is withdrawn, when ownership
        # reverts to the superseded run.
        self._current_run: dict[SampleKey, _SampleRun] = {}

    @property
    def open(self) -> bool:
        """Whether the attempt's fanout can still accept a re-run."""
        return self._scheduler.open

    def sample_view(self, sample_id: str, epoch: int) -> SampleQueueView:
        """One key's queue/requeue lifecycle, snapshotted synchronously.

        The single read surface for the queued rows: no await point, so a
        resolver that takes a view and mutates in the same synchronous block
        (all on the eval's loop) acts on current state. See
        :class:`SampleQueueView` for the field semantics.
        """
        key = SampleKey(sample_id, epoch)
        pending = self._pending.get(key)
        run = self._current_run.get(key)
        queue: Literal["arrived", "departed"] | None = None
        cancelled: Literal["parked", "discarded"] | None = None
        if run is not None and run.arrived:
            queue = "departed" if run.departed else "arrived"
        # cancelled-before-start is a key-based-run outcome: a withdrawn
        # re-run is also flagged cancelled but never owns the key (the
        # un-requeue reverts ownership before the resolver returns)
        if run is not None and run.cancelled and run.prior is None:
            cancelled = "discarded" if run.departed else "parked"
        typed_id: str | int
        if pending is not None:
            typed_id = pending.sample_id
        elif run is not None and run.typed_id is not None:
            typed_id = run.typed_id
        else:
            typed_id = sample_id
        return SampleQueueView(
            pending=pending is not None,
            prior_status=pending.prior_status if pending is not None else None,
            pending_departed=pending is not None and pending.entry.departed,
            queue=queue,
            cancelled=cancelled,
            typed_id=typed_id,
        )

    def pending_keys(self) -> frozenset[SampleKey]:
        """The pending ``(sample_id, epoch)`` keys, for the status derivation.

        The samples listing renders these ``queued`` until the re-run's
        ``ActiveSample`` appears, so a re-run parked behind the sample
        semaphore surfaces in the head sort tiers rather than as its prior
        terminal record.
        """
        return frozenset(self._pending)

    def cancelled_keys(self) -> frozenset[SampleKey]:
        """The cancelled-before-start keys, for the status derivation.

        The samples listing renders these ``cancelled`` (synthesized row —
        the sample has, and will have, no log record).
        """
        return frozenset(
            key
            for key, run in self._current_run.items()
            if run.cancelled and run.prior is None
        )

    async def checkpoint_available(self, sample_id: str | int, epoch: int) -> bool:
        """Whether the re-run would resume from an on-disk checkpoint."""
        if self._checkpoints_dir is None:
            return False
        from inspect_ai.util._checkpoint._layout import has_sample_checkpoint

        return await has_sample_checkpoint(self._checkpoints_dir, sample_id, epoch)

    def accept(
        self, prior: "EvalSample", prior_status: Literal["error", "cancelled"]
    ) -> RequeueOutcome:
        """Accept one re-run of ``prior``'s ``(id, epoch)``.

        Synchronous end to end — pending-set check, enqueue, and counter
        reconciliation run with no await point, so a double requeue (two
        directives racing past the resolver's async reads) resolves here
        atomically. A ``prior`` whose uuid was accepted once already is
        refused as ``stale`` — it enforces the invariant that each requeue
        requires the previous re-run to have reached a terminal outcome
        *and been re-read* first. Reconciliation: the prior terminal bucket is decremented
        (usage is kept — the prior spend was real; the re-run bumps a bucket
        again at its own terminal outcome), an errored prior's
        ``SampleErrorHandler.error_count`` is un-counted so end-of-task
        ``fail_on_error`` reflects final outcomes, and ``on_accept`` receives
        the prior's ``(id, epoch)`` so the runner can retract its superseded
        progress and score (returning the retracted score, stashed here for
        a possible withdraw — see :meth:`cancel_queued`).
        """
        from inspect_ai._control.eval_state import record_sample_requeued

        key = SampleKey(str(prior.id), prior.epoch)
        if key in self._pending:
            return "already_pending"
        if prior.uuid is not None and prior.uuid in self._accepted_uuids:
            return "stale"
        sample_index = self._sample_indexes.get(str(prior.id))
        if sample_index is None:
            return "unknown"

        superseded = self._current_run.get(key)

        def discard_pending() -> None:
            self._pending.pop(key, None)
            self._restore_owner(key, superseded)

        entry = _SampleRun(
            sample_index=sample_index,
            epoch=prior.epoch,
            prior=prior,
            on_terminal=discard_pending,
        )
        pending = _PendingRequeue(
            entry=entry,
            sample_id=prior.id,
            prior_status=prior_status,
            prior_uuid=prior.uuid,
            popped_score=None,
            superseded_run=superseded,
        )
        self._pending[key] = pending
        if not self._scheduler.requeue(entry):
            self._pending.pop(key, None)
            return "closed"
        if prior.uuid is not None:
            self._accepted_uuids.add(prior.uuid)
        record_sample_requeued(self._eval_id, prior_status)
        if prior_status == "error":
            self._sample_error.error_count -= 1
        pending.popped_score = self._on_accept(prior.id, prior.epoch)
        return "accepted"

    def cancel_queued(self, sample_id: str, epoch: int) -> None:
        """Withdraw a pending requeue (un-requeue) — the inverse of :meth:`accept`.

        The caller (the cancel resolver) validates the row — pending, not
        departed — and calls this with no await in between, all on the eval's
        loop, so the preconditions can't move: they are asserted here rather
        than re-branched (a second validation layer would be unreachable).
        The withdrawn entry's ``on_terminal`` is disarmed (the key may come
        to belong to a fresh requeue, which the zombie's terminal must not
        un-mark) and the key's ownership reverts to the superseded run, the
        prior record's uuid leaves the staleness guard (its re-run never
        happened, so the record is back to being current and
        re-requeueable), the prior terminal bucket / fail-on-error tally are
        restored, and ``on_withdraw`` re-inserts the retracted progress and
        score. See ``design/ctl/queued-sample-cancel.md``.
        """
        from inspect_ai._control.eval_state import record_sample_unrequeued

        key = SampleKey(sample_id, epoch)
        pending = self._pending.get(key)
        assert pending is not None, f"no requeue pending for {key}"
        assert not pending.entry.departed, f"re-run for {key} has left the queue"
        pending.entry.cancelled = True
        pending.entry.on_terminal = None
        del self._pending[key]
        self._restore_owner(key, pending.superseded_run)
        if pending.prior_uuid is not None:
            self._accepted_uuids.discard(pending.prior_uuid)
        record_sample_unrequeued(self._eval_id, pending.prior_status)
        if pending.prior_status == "error":
            self._sample_error.error_count += 1
        self._on_withdraw(pending.sample_id, epoch, pending.popped_score)

    def _restore_owner(self, key: SampleKey, superseded: _SampleRun | None) -> None:
        """Revert the key's owning run when its re-run ends or is withdrawn.

        Idempotent (the re-run may never have arrived, leaving the
        superseded run in place). Leaving a finished re-run as owner would
        misread in the teardown window: a parked re-run reaped by the task
        group (its ``on_terminal`` fires from ``run_one``'s ``finally``)
        would leave the key ``"arrived"``, letting a cancel-before-start
        accept target a sample with a standing terminal record.
        """
        if superseded is not None:
            self._current_run[key] = superseded
        else:
            self._current_run.pop(key, None)

    def queue_arrive(self, sample_id: str | int, epoch: int, run: _SampleRun) -> None:
        """Stamp a run's arrival at the sample queue (immediately pre-park).

        Stamps the run object — never the key — so the stamp can't alias
        another coroutine for the same key, and points the key's ownership
        at the run for the read surface. Arrival overwrites a prior
        departure (a ``retry_on_error`` re-park cycles the state back) and
        captures the dataset-typed id.

        A run arriving already cancelled is a withdrawn re-run resuming from
        its seeding awaits (``run_sample`` checks the flag at its top, but a
        re-run awaits the prior's log removal and checkpoint read before this
        stamp — the un-requeue can be accepted in between). It takes no stamp
        and no ownership: owning the key would make it read as a
        never-started row (``arrived``, not ``cancelled`` — a
        cancel-before-start accept would then target a run with a standing
        prior record), and could steal the key from a fresh requeue. Only
        this path arrives cancelled — a cancelled key-based run discards at
        its queue exit and never re-parks — and it still discards at the
        queue-exit check as usual.
        """
        if run.cancelled:
            return
        run.arrived = True
        run.departed = False
        run.typed_id = sample_id
        self._current_run[SampleKey(str(sample_id), epoch)] = run

    def queue_depart(self, run: _SampleRun) -> bool:
        """Stamp a run's queue exit; ``True`` when it was cancelled while parked.

        Called for every run that parks, cancelled or not — the accept-side
        at-the-queue gate reads the stamp, so it must cover uncancelled runs
        too. Departure flips a cancelled key-based run's read from
        ``"parked"`` to ``"discarded"`` (the requeue resolver's un-cancel
        window closes with the coroutine).
        """
        run.departed = True
        return run.cancelled

    def queue_abandoned(self, run: _SampleRun) -> None:
        """Mark a key-based run a task-cancel drain abandoned as cancelled.

        The drain records the cancel in the counters but writes no record,
        so without this stamp no read surface ever sees the outcome: the
        listing keeps rendering the key ``pending`` and the cancel
        resolver's departed branch advises "retry once it is running"
        forever. ``departed`` is set alongside so the run reads
        ``"discarded"`` directly — the coroutine is returning, so there is
        no parked window to un-cancel. Re-runs take no stamp: clearing their
        pending key (``on_terminal``) reverts them to their prior terminal
        record.
        """
        if run.prior is not None:
            return
        run.cancelled = True
        run.departed = True

    def cancel_before_start(self, sample_id: str, epoch: int) -> None:
        """Cancel a never-started (or retry-re-parked) sample parked at the queue.

        The caller (the cancel resolver) validates that the key is exactly
        *at the queue* (arrived, not departed) and calls this with no await
        in between, on the eval's loop, so the precondition can't move: it
        is asserted rather than re-branched. A departed run would be
        mid-materialization and terminal-record on its own; an unarrived key
        may be reuse-bound on a retry attempt and never queue at all. On
        accept the sample is terminally cancelled in the counters
        immediately; the parked coroutine discards later, at the queue-exit
        check, without recording again. See
        ``design/ctl/queued-sample-cancel.md``.
        """
        from inspect_ai._control.eval_state import record_sample_cancelled

        key = SampleKey(sample_id, epoch)
        run = self._current_run.get(key)
        assert (
            run is not None and run.prior is None and run.arrived and not run.departed
        ), f"{key} is not at the queue"
        assert not run.cancelled, f"{key} is already cancelled"
        run.cancelled = True
        record_sample_cancelled(self._eval_id)

    def uncancel(self, sample_id: str, epoch: int) -> None:
        """Withdraw a cancel-before-start while its coroutine is still parked.

        The caller (the requeue resolver) validates that the key is
        ``"parked"`` and calls this with no await in between, on the eval's
        loop, so the precondition can't move: it is asserted rather than
        re-branched. The same parked coroutine serves as the re-run — no new
        entry is created, so there is nothing to double-queue; the sample
        simply runs when it gets a slot, exactly as if never cancelled.
        """
        from inspect_ai._control.eval_state import record_sample_requeued

        key = SampleKey(sample_id, epoch)
        run = self._current_run.get(key)
        assert run is not None and run.cancelled and not run.departed, (
            f"{key} is not parked-cancelled"
        )
        run.cancelled = False
        record_sample_requeued(self._eval_id, "cancelled", op="un-cancel")


@dataclass
class SampleQueueHooks:
    """The queue-lifecycle stamp points for one sample-run coroutine.

    Bundles the three hooks ``task_run_sample`` fires — they all close over
    the same ``(requeue, sample_id, epoch, run)``, so one pre-bound object
    replaces a closure triple. Built in ``run_sample`` (where the
    dataset-typed id is known) and forwarded through the ``retry_on_error``
    recursion, so a re-parked sample re-stamps arrival and reads as
    at-the-queue (cancellable) rather than permanently departed
    (``design/ctl/queued-sample-cancel.md``).
    """

    requeue: SampleRequeue
    sample_id: str | int
    epoch: int
    run: _SampleRun

    def enter(self) -> None:
        """Stamp arrival at the sample queue (immediately pre-park)."""
        self.requeue.queue_arrive(self.sample_id, self.epoch, self.run)

    def exit(self) -> bool:
        """Stamp queue exit; ``True`` when the run was cancelled while parked."""
        return self.requeue.queue_depart(self.run)

    def abandon(self) -> None:
        """Mark the run cancelled when a task-cancel drain abandons it."""
        self.requeue.queue_abandoned(self.run)
