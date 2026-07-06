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
from threading import Lock
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
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
        ``next_samples()``.
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

        Returns:
            A ``SampleSource`` that delegates to the provided seed and callbacks.
        """
        return _CallableSampleSource(initial_samples, next_samples, sample_complete)


class _CallableSampleSource(SampleSource):
    """A :class:`SampleSource` backed by a fixed seed and optional callables."""

    def __init__(
        self,
        initial_samples: list["Sample"],
        next_samples: Callable[[], Awaitable[list["Sample"] | None]] | None,
        sample_complete: Callable[["EvalSample"], Awaitable[list["Sample"] | None]]
        | None,
    ) -> None:
        self._initial_samples = list(initial_samples)
        self._next_samples = next_samples
        self._sample_complete = sample_complete

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


@dataclass
class SampleEnqueuer:
    """Buffers samples added to one running task and hands them to its loop.

    Owned by ``task_run`` for the task's lifetime (only when the task has a
    :class:`SampleSource`). ``enqueue`` buffers; ``drain`` is the non-blocking
    pull the task's dispatch loop does between cycles.
    """

    _pending: list["Sample"] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)
    on_enqueue: Callable[[], None] | None = None
    """Fired after samples are buffered — used to wake the task's dispatcher."""

    def enqueue(self, samples: list["Sample"]) -> None:
        """Queue ``samples`` to run in the task."""
        with self._lock:
            self._pending.extend(samples)
        if self.on_enqueue is not None:
            self.on_enqueue()

    def drain(self) -> list["Sample"]:
        """Remove and return all currently-buffered samples (empty if none)."""
        with self._lock:
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


def enqueue_sample(samples: "Sample | list[Sample]") -> None:
    """Add one or more samples to the running task.

    The samples run in the current task as soon as there is free capacity
    (bounded by ``max_samples``), each for the task's configured number of
    epochs. Samples without an ``id`` are assigned one automatically.

    Only available inside a task driven by a :class:`SampleSource` (i.e. a
    ``Task`` whose ``dataset`` is a ``SampleSource``) — a plain task's sample
    set is fixed, so there is no loop to run additions. Callable from any code
    running within such a task: a solver, a scorer, a tool.

    When the eval was run with ``--limit``, samples beyond the limit are
    ignored (with a warning); with ``--sample-id``, only samples matching the
    filter run.

    Args:
        samples: A ``Sample`` (or list of samples) to add to the running task.

    Raises:
        RuntimeError: If the current task is not driven by a ``SampleSource``
            (or no task is running in this context).
    """
    from inspect_ai.dataset import Sample

    enqueuer = get_sample_enqueuer()
    if enqueuer is None:
        raise RuntimeError(
            "enqueue_sample() can only be called from within a running task "
            "whose dataset is a SampleSource."
        )
    enqueuer.enqueue([samples] if isinstance(samples, Sample) else list(samples))
