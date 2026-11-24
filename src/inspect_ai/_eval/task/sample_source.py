"""A dynamic source of samples for a running task.

Pass a :class:`SampleSource` instance as the ``dataset`` argument to a ``Task``
to generate the task's samples from code rather than a fixed dataset — the
sample-level mirror of passing a :class:`~inspect_ai.TaskSource` as the
``tasks`` argument to ``eval()``. The task starts with ``initial_samples()``
and, whenever no samples remain in flight, calls ``next_samples()`` for more —
until it returns ``None``.

The simplest sources spawn follow-up work straight from results: override
``sample_complete`` and **return** the samples to run next (e.g. an RL loop
that spawns samples from scores, or an adaptive eval that branches on model
performance). A returned list is added to the task exactly as
``enqueue_sample`` would — it starts as soon as there is free capacity — so a
source can be driven entirely by this callback, with ``next_samples()``
reserved for the blocking / explicit-pull case.

``next_samples()`` is async and may block — awaiting external input or more
results — and returns ``None`` to end the task, so an open-ended "keep
producing until told to stop" loop is expressible. ``initial_samples()`` is
synchronous and returns immediately (it's the seed the task sets up and starts
from, not subject to that blocking); it may be empty, in which case the task
starts by calling ``next_samples()``.

For the common case where subclassing is more than you need,
:meth:`SampleSource.from_samples` builds a ``SampleSource`` from a seed plus
optional callbacks.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple

import anyio

from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._eval.task.enqueue import RunQueue, TaskRecord
    from inspect_ai.dataset import Sample
    from inspect_ai.log._log import EvalSample


class SampleSource:
    """Drives a running task from code: a seed plus result-driven follow-ups.

    Subclass and override the methods you need. The default implementations are
    no-ops / empty, so a bare ``SampleSource`` runs nothing — override at least
    ``initial_samples`` and ``next_samples``.
    """

    def initial_samples(self) -> list["Sample"]:
        """Samples to run first (the seed).

        Called once, synchronously, when the ``Task`` is created — so it must
        return immediately (no awaiting / blocking). The returned samples drive
        the task's up-front setup (validation, sandbox startup) and are the
        first batch. May be empty, in which case the task starts by calling
        ``next_samples()``. The seed isn't required for sandboxes: a sandbox
        config first seen in a later-added sample gets the same startup
        (image build/pull, validation, registered cleanup) before that sample
        runs.
        """
        return []

    async def next_samples(self) -> list["Sample"] | None:
        """More samples to run, or ``None`` when the task is complete.

        Called whenever no samples remain in flight or buffered (after those
        samples' ``sample_complete`` notifications). May ``await`` — for more
        results or external input — and may block indefinitely; return ``None``
        to end the task. (If samples were enqueued while a ``None`` return was
        in progress they still run, and this method may then be called again.)
        """
        return None

    async def sample_complete(self, sample: "EvalSample") -> list["Sample"] | None:
        """A sample finished — observe it and optionally return follow-up samples.

        Return a list of samples to add to the task (equivalent to calling
        ``enqueue_sample`` with them): they start as soon as there is free
        capacity. Return ``None`` (the default) to add nothing.

        Fires for every sample the task logs, including one cancelled
        individually by an operator (its ``error`` is then the cancellation,
        with no scores), but not for samples cancelled by the task itself
        unwinding (a task-level cancel or ^C), where any follow-ups could
        never run. A cancelled sample's ``error.message`` is the cancellation
        exception's repr (it starts with ``CancelledError(`` or
        ``Cancelled(``), which is how to tell it from a genuine error. A
        sample cancelled before it produced anything to log is reported via
        :meth:`sample_abandoned` instead.

        On a task retry this is also called for samples reused from the prior
        attempt, so a completion-driven source regenerates its follow-ups. A
        returned sample with an explicit id that matches the prior attempt is
        reused rather than re-run; one without an id gets a new generated id
        and runs again.
        """
        return None

    async def sample_abandoned(
        self, sample: "Sample", epoch: int
    ) -> list["Sample"] | None:
        """A sample was cancelled without ever being logged.

        ``sample`` is a copy of the sample as it was added to the task and
        ``epoch`` the epoch that was abandoned. Nothing about the run reached
        the log (no ``EvalSample`` exists), so unlike
        :meth:`sample_complete` there is no result to deliver. Return a list
        of samples to add to the task (equivalent to calling
        ``enqueue_sample`` with them) or ``None`` (the default) to add
        nothing.

        Fires when an operator cancels a sample still waiting in the queue
        (``inspect ctl sample cancel --action cancel``), when a cancel lands
        on an errored sample in the window before its ``retry_on_error``
        re-run, or when a graceful task cancel (``--action drain``,
        ``score``, ``error``) abandons a queued sample — in each case the
        task itself keeps running, so a source waiting on the sample must
        hear that it will never complete. Like :meth:`sample_complete` it
        does not fire for samples cancelled by the task itself unwinding (a
        task-level cancel or ^C), nor for a withdrawn requeue (the prior
        terminal outcome, already reported, stands). With ``epochs > 1`` it
        fires once per abandoned epoch, as ``sample_complete`` fires once per
        completed one.
        """
        return None

    @classmethod
    def from_samples(
        cls,
        initial_samples: list["Sample"],
        *,
        next_samples: Callable[[], Awaitable[list["Sample"] | None]] | None = None,
        sample_complete: Callable[["EvalSample"], Awaitable[list["Sample"] | None]]
        | None = None,
        sample_abandoned: Callable[["Sample", int], Awaitable[list["Sample"] | None]]
        | None = None,
    ) -> "SampleSource":
        """Create a :class:`SampleSource` from a seed plus optional callbacks.

        A convenience for when subclassing is more than you need: provide the
        initial samples directly and, optionally, callbacks that react to
        results. The ``sample_complete`` callback may **return** a list of
        follow-up samples to add to the task (see that method);
        ``next_samples`` is the blocking / explicit-pull alternative. Callbacks
        typically close over shared state (e.g. accumulated scores) to decide
        what to run next.

        Args:
            initial_samples: The seed samples to run first (see
                :meth:`initial_samples`).
            next_samples: Optional async callback returning more samples, or
                ``None`` to end the task (see :meth:`next_samples`). If omitted
                (and no callback returns samples), the task stops after the
                seed — equivalent to passing ``initial_samples`` directly as
                the dataset.
            sample_complete: Optional async callback invoked as each sample
                finishes; may return follow-up samples to add to the task.
            sample_abandoned: Optional async callback invoked when a sample is
                cancelled without being logged (see :meth:`sample_abandoned`);
                may return follow-up samples to add to the task.

        Returns:
            A ``SampleSource`` that delegates to the provided seed and callbacks.
        """
        return _CallableSampleSource(
            initial_samples, next_samples, sample_complete, sample_abandoned
        )


class _CallableSampleSource(SampleSource):
    """A :class:`SampleSource` backed by a fixed seed and optional callables."""

    def __init__(
        self,
        initial_samples: list["Sample"],
        next_samples: Callable[[], Awaitable[list["Sample"] | None]] | None,
        sample_complete: Callable[["EvalSample"], Awaitable[list["Sample"] | None]]
        | None,
        sample_abandoned: Callable[["Sample", int], Awaitable[list["Sample"] | None]]
        | None,
    ) -> None:
        self._initial_samples = list(initial_samples)
        self._next_samples = next_samples
        self._sample_complete = sample_complete
        self._sample_abandoned = sample_abandoned

    def initial_samples(self) -> list["Sample"]:
        return self._initial_samples

    async def next_samples(self) -> list["Sample"] | None:
        if self._next_samples is not None:
            return await self._next_samples()
        return None

    async def sample_complete(self, sample: "EvalSample") -> list["Sample"] | None:
        if self._sample_complete is not None:
            return await self._sample_complete(sample)
        return None

    async def sample_abandoned(
        self, sample: "Sample", epoch: int
    ) -> list["Sample"] | None:
        if self._sample_abandoned is not None:
            return await self._sample_abandoned(sample, epoch)
        return None


class EnqueuedSample(NamedTuple):
    """A sample added to a running task, with the epoch it runs as (if given)."""

    sample: "Sample"
    epoch: int | None
    """The single epoch to run, or ``None`` to run the task's configured epochs."""


@dataclass
class SampleEnqueuer:
    """Buffers samples added to one running task and hands them to its loop.

    Owned by ``task_run`` for the task's lifetime (only when the task has a
    :class:`SampleSource`). ``enqueue`` buffers; ``drain`` is the non-blocking
    pull the task's dispatch loop does between cycles.

    Not thread-safe: ``enqueue`` must be called from the task's event loop
    (the ``on_enqueue`` wake callback — ``anyio.Event.set`` — is not safe to
    fire from other threads). The buffer needs no lock under the event loop
    since neither method has a yield point.
    """

    _pending: list[EnqueuedSample] = field(default_factory=list)
    on_enqueue: Callable[[], None] | None = None
    """Fired after samples are buffered — used to wake the task's dispatcher."""
    handle_channel: bool = False
    """The task is fed through its handle: only the handle adds samples."""

    def enqueue(self, samples: list["Sample"], epoch: int | None = None) -> None:
        """Queue ``samples`` to run in the task (as ``epoch`` only, if given)."""
        self._pending.extend(EnqueuedSample(sample, epoch) for sample in samples)
        if self.on_enqueue is not None:
            self.on_enqueue()

    def drain(self) -> list[EnqueuedSample]:
        """Remove and return all currently-buffered samples (empty if none)."""
        batch, self._pending = self._pending, []
        return batch


# The running task's enqueuer, scoped to the task's async context (and
# propagated to its samples — solvers / scorers / tools). ``None`` when the
# current task is not driven by a SampleSource.
_sample_enqueuer: ContextVar[SampleEnqueuer | None] = ContextVar(
    "sample_enqueuer", default=None
)


def register_sample_enqueuer(enqueuer: SampleEnqueuer) -> Token[SampleEnqueuer | None]:
    """Install ``enqueuer`` as the active one; returns a token to restore with."""
    return _sample_enqueuer.set(enqueuer)


def get_sample_enqueuer() -> SampleEnqueuer | None:
    return _sample_enqueuer.get()


def clear_sample_enqueuer(token: Token[SampleEnqueuer | None]) -> None:
    """Restore the enqueuer in scope before the matching ``register`` call."""
    _sample_enqueuer.reset(token)


def enqueue_sample(
    samples: "Sample | list[Sample]", *, epoch: int | None = None
) -> None:
    """Add one or more samples to the running task.

    The samples run in the current task as soon as there is free capacity
    (bounded by ``max_samples``), each for the task's configured number of
    epochs. Each time a sample without an ``id`` is added, it runs under a
    new generated id such as ``dyn-t4ab9c-0003`` (the ``Sample`` you pass is
    not changed), so on a task retry it runs again; only samples with
    explicit ids are reused from the prior attempt. Generated ids sort in
    the order they were added, up to 9,999 per attempt; beyond that, and
    past a change in the token's width, they stay unique but no longer sort
    in order.

    Pass ``epoch`` to run each sample once, as that epoch, instead, so the
    same id can be run repeatedly. Samples added with ``epoch`` must have an
    explicit ``id``, since a sample without one gets a fresh id each time it
    is added. Each ``(id, epoch)`` may be added once (a
    sample added without ``epoch`` takes epochs 1 to the task's ``epochs``);
    a duplicate fails the task.

    Only available inside a task driven by a :class:`SampleSource` (i.e. a
    ``Task`` whose ``dataset`` is a ``SampleSource``) — a plain task's sample
    set is fixed, so there is no loop to run additions. Callable from any code
    running within such a task — a solver, a scorer, a tool — but it must be
    called from the task's event loop (where those all run), not from a
    worker thread.

    When the eval was run with ``--limit``, samples beyond the limit are
    ignored (with a warning); with ``--sample-id``, only samples matching the
    filter run.

    Args:
        samples: A ``Sample`` (or list of samples) to add to the running task.
        epoch: Run each sample once, as this epoch (1-based), rather than for
            the task's configured number of epochs.

    Raises:
        RuntimeError: If the current task is not driven by a ``SampleSource``
            (or no task is running in this context).
        ValueError: If ``epoch`` is not an integer of 1 or more, or is given
            for a sample without an ``id``.
    """
    from inspect_ai.dataset import Sample

    if epoch is not None and (
        isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1
    ):
        raise ValueError(
            f"enqueue_sample() epoch must be an integer of 1 or more (got {epoch!r})."
        )
    sample_list = [samples] if isinstance(samples, Sample) else list(samples)
    if epoch is not None and any(sample.id is None for sample in sample_list):
        raise ValueError(
            "enqueue_sample() with epoch requires each sample to have an id: "
            "a sample without an id gets a new id each time it is added, so "
            "its epochs would run as separate samples."
        )
    enqueuer = get_sample_enqueuer()
    if enqueuer is None:
        raise RuntimeError(
            "enqueue_sample() can only be called from within a running task "
            "whose dataset is a SampleSource."
        )
    if enqueuer.handle_channel:
        raise RuntimeError(
            "enqueue_sample() cannot add samples to a task fed through its "
            "handle; only the handle that added it sends samples."
        )
    enqueuer.enqueue(sample_list, epoch=epoch)


HANDLE_DATASET_NAME = "samples_from_handle"
"""The dataset name of every task fed through its handle, reserved for them."""


class _SampleFuture:
    """The outcome of one sent sample, settled once."""

    def __init__(self) -> None:
        self._event = anyio.Event()
        self._value: "EvalSample | None" = None
        self._error: BaseException | None = None

    @property
    def done(self) -> bool:
        return self._event.is_set()

    def set_result(self, value: "EvalSample") -> None:
        if not self.done:
            self._value = value
            self._event.set()

    def set_exception(self, error: BaseException) -> None:
        if not self.done:
            self._error = error
            self._event.set()

    async def wait(self) -> "EvalSample":
        await self._event.wait()
        if self._error is not None:
            raise self._error
        assert self._value is not None
        return self._value


@dataclass(eq=False)
class PortRequest:
    """One sample sent to a task through its handle, until its outcome settles."""

    sample: "Sample"
    """The channel's copy of the caller's sample, with its id."""
    future: _SampleFuture = field(default_factory=_SampleFuture)


class HandleChannel(SampleSource):
    """The sample source of a task fed through its handle.

    Created by :func:`samples_from_handle`. When the task is added to a run,
    the run's queue gives its record a fresh channel (:meth:`bind`), through
    which :class:`~inspect_ai.TaskHandle` sends samples and receives each
    one's logged run. The channel has no seed; it ends the task once it is
    closed and the samples sent have run.
    """

    def __init__(self) -> None:
        self.enqueuer: SampleEnqueuer | None = None
        """The running attempt's buffer, while it runs."""
        self.token = ""
        """The first 8 characters of the record's task id."""
        self.requests: dict[str, PortRequest] = {}
        """Every unsettled request, by sample id, in send order."""
        self.sent = 0
        """Samples accepted so far; the next id's counter."""
        self.closed = False
        self.pushed = Wake()
        self._queue: "RunQueue | None" = None
        self._record: "TaskRecord | None" = None

    def bind(self, queue: "RunQueue", record: "TaskRecord") -> None:
        """Attach the channel to the run's record of its task."""
        self._queue = queue
        self._record = record
        self.token = record.task_id[:8]

    @property
    def record(self) -> "TaskRecord":
        assert self._record is not None
        return self._record

    def send(self, sample: "Sample") -> PortRequest:
        """Accept ``sample`` as a new request and deliver it to the task.

        The caller has checked that the channel accepts samples. The sample
        runs as a copy under the id ``send-<token>-<n>``.
        """
        assert self._queue is not None and not self.closed
        self.sent += 1
        copy = sample.model_copy(update={"id": f"send-{self.token}-{self.sent:04d}"})
        request = PortRequest(copy)
        self.requests[str(copy.id)] = request
        if self.enqueuer is not None:
            self.enqueuer.enqueue([copy])
        self.pushed.set()
        self._queue.wake.set()
        return request

    def close(self) -> None:
        """Accept no more samples.

        A task still queued with no request ends at once with no log.
        """
        if self.closed:
            return
        self.closed = True
        self.pushed.set()
        record = self._record
        if (
            self._queue is not None
            and record is not None
            and record.phase == "queued"
            and not self.requests
        ):
            self._queue.end(record, None)

    def end(self, error: Callable[[], BaseException]) -> None:
        """Close the channel and fail every unsettled request.

        Each request gets its own exception from ``error``, so one sender's
        traceback never carries another's frames. Also drops any samples
        still buffered for the attempt, so an ended task holds none of its
        senders' samples.
        """
        self.closed = True
        self.pushed.set()
        if self.enqueuer is not None:
            self.enqueuer.drain()
            self.enqueuer = None
        requests, self.requests = self.requests, {}
        for request in requests.values():
            request.future.set_exception(error())

    def attach(self, enqueuer: SampleEnqueuer) -> None:
        """Deliver every request, and later sends, to the attempt's buffer."""
        enqueuer.handle_channel = True
        self.enqueuer = enqueuer
        if self.requests:
            enqueuer.enqueue([request.sample for request in self.requests.values()])

    def detach(self) -> None:
        """The attempt's buffer is gone: hold later sends."""
        self.enqueuer = None

    async def next_samples(self) -> list["Sample"] | None:
        if self.closed:
            return None
        await self.pushed.wait()
        return None if self.closed else []

    async def sample_complete(self, sample: "EvalSample") -> list["Sample"] | None:
        request = self.requests.pop(str(sample.id), None)
        if request is not None:
            request.future.set_result(sample)
        return None

    async def sample_abandoned(
        self, sample: "Sample", epoch: int
    ) -> list["Sample"] | None:
        from inspect_ai._eval.task.enqueue import SampleAbandonedError

        request = self.requests.pop(str(sample.id), None)
        if request is not None:
            request.future.set_exception(SampleAbandonedError(sample))
        return None


def samples_from_handle() -> SampleSource:
    """A dataset whose samples are sent through the task's handle.

    Pass it as a ``Task``'s ``dataset`` and add the task with
    :func:`~inspect_ai.enqueue_task` from code running inside a task. Each
    sample sent with :meth:`TaskHandle.enqueue_sample` runs once and the call
    returns its logged ``EvalSample``. The task ends once its handle is closed
    (or the task that added it ends) and the samples sent have run. It cannot
    run on its own with ``eval()``, ``eval_set()`` or ``eval_retry()``.
    """
    return HandleChannel()
