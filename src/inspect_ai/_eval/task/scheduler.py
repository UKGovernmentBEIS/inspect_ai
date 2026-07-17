"""Live sample fanout for one task attempt (the injectable sample scheduler).

Replaces the one-shot ``tg_collect`` fanout in ``task_run`` so samples can be
re-added while the task runs (see ``design/sample-requeue.md``): all planned
``(sample_index, epoch)`` coroutines start up front (unchanged behaviour), and
a dispatcher loop inside the same task group drains re-run entries accepted by
the control channel's sample-requeue directive, starting each re-run inside
the group — a route handler must not ``start_soon`` into a nursery it isn't
inside. Results collect into a dict keyed by ``(sample_index, epoch)`` so a
re-run's fresh score replaces the prior attempt's entry (metrics follow the
log, which supersedes by the same key), returned in plan order like the
``tg_collect`` list it replaces. The fanout closes when no sample is
outstanding and nothing is pending; a requeue after that is rejected.

:class:`SampleScheduler` is the generic fanout (the shared enabler the
dynamic-sample work also needs); :class:`SampleRequeue` is the requeue-policy
capability registered on the process-global ``EvalState`` — it resolves
sample ids to fanout indexes, owns the pending-requeue set that makes a
double requeue idempotent, and performs the counter reconciliation the
directive's accept path requires.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, TypeVar

import anyio

from inspect_ai._util._async import Wake

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

if TYPE_CHECKING:
    from inspect_ai._eval.task.error import SampleErrorHandler
    from inspect_ai.log._log import EvalSample

T = TypeVar("T")

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


@dataclass
class _ScheduledRerun:
    """One accepted re-run, queued for the dispatcher."""

    sample_index: int
    epoch: int
    prior: "EvalSample"
    """The prior terminal record the re-run seeds from (retry history /
    checkpoint resume — see ``run_sample``'s requeue path in ``run.py``)."""
    on_terminal: Callable[[], None]
    """Invoked when the re-run reaches a terminal outcome (clears the
    pending-requeue key, making the sample requeueable again)."""


class SampleScheduler:
    """The task's live sample fanout: initial samples plus accepted re-runs.

    Single-loop discipline is what makes it race-free: :meth:`requeue` is
    synchronous (no await between the open-check and the enqueue), so a
    dispatcher woken by the last outstanding sample's decrement observes any
    increment that preceded it, and two concurrent directives can't both
    enqueue the same entry.
    """

    def __init__(self) -> None:
        self._outstanding = 0
        self._pending: list[_ScheduledRerun] = []
        self._running = False
        self._wake = Wake()

    @property
    def open(self) -> bool:
        """Whether the fanout can still accept a re-run.

        Pending entries are counted in ``outstanding`` from the moment they
        are accepted, so ``outstanding == 0`` means the dispatcher is exiting
        (or has exited) and the task is finishing — accepting then would be
        a lie (the re-run could never start).
        """
        return self._running and self._outstanding > 0

    def requeue(self, rerun: _ScheduledRerun) -> bool:
        """Enqueue a re-run; False when the fanout has drained (or not begun)."""
        if not self.open:
            return False
        self._outstanding += 1
        self._pending.append(rerun)
        self._wake.set()
        return True

    async def run(
        self,
        plan: list[tuple[int, int]],
        run_sample: Callable[[int, int, "EvalSample | None"], Awaitable[T]],
    ) -> dict[tuple[int, int], T]:
        """Run every planned ``(sample_index, epoch)`` plus accepted re-runs.

        Exception semantics match ``tg_collect`` (which this replaces): the
        first inner exception propagates (tearing the group down), so a
        sample error under strict ``fail_on_error`` still aborts the task
        exactly as before. Results also come back in **plan order**, matching
        ``tg_collect``: insertion order is completion order, which would make
        epoch-reducer inputs (``mode`` tie-breaks by first occurrence) and
        the logged reductions nondeterministic run to run.
        """
        results: dict[tuple[int, int], T] = {}
        # count the full plan before the first await so `open` (which the
        # accept path checks) is accurate from the moment the requeue handle
        # becomes visible
        self._outstanding = len(plan)
        self._running = True
        try:
            async with anyio.create_task_group() as tg:

                async def run_one(
                    sample_index: int, epoch: int, rerun: _ScheduledRerun | None
                ) -> None:
                    try:
                        results[(sample_index, epoch)] = await run_sample(
                            sample_index, epoch, rerun.prior if rerun else None
                        )
                    finally:
                        if rerun is not None:
                            rerun.on_terminal()
                        self._outstanding -= 1
                        self._wake.set()

                for sample_index, epoch in plan:
                    tg.start_soon(run_one, sample_index, epoch, None)

                # dispatcher: start accepted re-runs until nothing is
                # outstanding (pending entries count toward outstanding, so
                # outstanding == 0 implies the pending list is empty too)
                while self._outstanding > 0:
                    if self._pending:
                        rerun = self._pending.pop(0)
                        tg.start_soon(run_one, rerun.sample_index, rerun.epoch, rerun)
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
                self._pending.pop().on_terminal()
        # re-runs replace at the same key, so the plan covers every key
        return {key: results[key] for key in plan if key in results}


class SampleRequeue:
    """Attempt-scoped requeue capability (``design/sample-requeue.md``).

    Registered on the process-global ``EvalState`` by ``task_run`` when the
    sample fanout starts (mirroring ``TaskCancel``) and invoked by the
    control channel's requeue resolver (``_control/requeue.py``) on the
    eval's own loop. Detached when a task retry supersedes the attempt, like
    ``EvalState.live``.
    """

    def __init__(
        self,
        *,
        eval_id: str,
        scheduler: SampleScheduler,
        sample_error: "SampleErrorHandler",
        sample_indexes: dict[str, int],
        checkpoints_dir: str | None,
        on_accept: Callable[[str | int, int], None],
    ) -> None:
        self._eval_id = eval_id
        self._scheduler = scheduler
        self._sample_error = sample_error
        self._sample_indexes = sample_indexes
        self._checkpoints_dir = checkpoints_dir
        self._on_accept = on_accept
        # keys accepted but not yet re-terminal — the idempotent double-queue
        # guard, covering the whole window from accept until the re-run
        # records its terminal outcome (including the park at the sample
        # semaphore, where the re-run has no ActiveSample yet)
        self._pending: set[tuple[str, int]] = set()
        # uuids of prior records already accepted once: a directive whose
        # reads straddled a full accept → re-run → terminal cycle arrives
        # with a stale `prior` after the pending key has cleared, and
        # accepting it would re-run a possibly-completed sample (and
        # double-decrement the counters). A legitimate re-requeue after a
        # second failure carries the re-run's fresh uuid, so it still passes.
        self._accepted_uuids: set[str] = set()

    @property
    def open(self) -> bool:
        """Whether the attempt's fanout can still accept a re-run."""
        return self._scheduler.open

    def is_pending(self, sample_id: str, epoch: int) -> bool:
        """Whether a requeue for this key is accepted but not yet re-terminal."""
        return (sample_id, epoch) in self._pending

    def pending_keys(self) -> frozenset[tuple[str, int]]:
        """The pending ``(sample_id, epoch)`` keys, for the status derivation.

        The samples listing renders these ``queued`` until the re-run's
        ``ActiveSample`` appears, so a re-run parked behind the sample
        semaphore surfaces in the head sort tiers rather than as its prior
        terminal record.
        """
        return frozenset(self._pending)

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
        progress and score.
        """
        from inspect_ai._control.eval_state import record_sample_requeued

        key = (str(prior.id), prior.epoch)
        if key in self._pending:
            return "already_pending"
        if prior.uuid is not None and prior.uuid in self._accepted_uuids:
            return "stale"
        sample_index = self._sample_indexes.get(str(prior.id))
        if sample_index is None:
            return "unknown"
        self._pending.add(key)
        accepted = self._scheduler.requeue(
            _ScheduledRerun(
                sample_index=sample_index,
                epoch=prior.epoch,
                prior=prior,
                on_terminal=lambda: self._pending.discard(key),
            )
        )
        if not accepted:
            self._pending.discard(key)
            return "closed"
        if prior.uuid is not None:
            self._accepted_uuids.add(prior.uuid)
        record_sample_requeued(self._eval_id, prior_status)
        if prior_status == "error":
            self._sample_error.error_count -= 1
        self._on_accept(prior.id, prior.epoch)
        return "accepted"
