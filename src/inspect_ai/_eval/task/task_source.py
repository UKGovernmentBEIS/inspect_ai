"""A dynamic source of tasks for a running eval.

Pass a :class:`TaskSource` instance as the ``tasks`` argument to ``eval()`` to
drive the run from code rather than a fixed task list. The run starts with
``initial_tasks()`` and, after each batch of tasks completes, calls
``next_tasks()`` for the next batch — until it returns ``None``.

The simplest sources spawn follow-up work straight from results: override
``sample_complete`` / ``task_complete`` and **return** the tasks to run next
(e.g. an RL loop that spawns tasks from scores). A returned list is added to the
run exactly as ``enqueue_task`` would — it runs after the current batch, before
the next ``next_tasks()`` — so a source can be driven entirely by these
callbacks, with ``next_tasks()`` reserved for the blocking / explicit-pull case.

``next_tasks()`` is async and may block — awaiting external input or more
results — and returns ``None`` to end the run, so an open-ended "keep producing
until told to stop" loop is expressible. ``initial_tasks()`` is synchronous and
returns immediately (it's the seed the run sets up and starts from, not subject
to that blocking), which is how the run computes concurrency / validates before
execution begins.

For the common case where subclassing is more than you need, :func:`task_source`
builds a ``TaskSource`` from a seed plus optional callbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalLog, EvalSample

    from .task import Task


class TaskSource:
    """Drives a running eval from code: a seed plus result-driven follow-ups.

    Subclass and override the methods you need. The default implementations are
    no-ops / empty, so a bare ``TaskSource`` runs nothing — override at least
    ``initial_tasks`` and ``next_tasks``.
    """

    def initial_tasks(self) -> list["Task"]:
        """Tasks to run first (the seed).

        Called once, synchronously, before the run starts — so it must return
        immediately (no awaiting / blocking). The returned tasks drive the
        run's up-front setup (concurrency, validation) and are the first batch.
        """
        return []

    async def next_tasks(self) -> list["Task"] | None:
        """The next batch of tasks to run, or ``None`` when the run is complete.

        Called after each batch finishes (after that batch's ``sample_complete``
        / ``task_complete`` notifications). May ``await`` — for more results or
        external input — and may block indefinitely; return ``None`` to end the
        run.
        """
        return None

    async def sample_complete(self, sample: "EvalSample") -> list["Task"] | None:
        """A sample finished — observe it and optionally return follow-up tasks.

        Return a list of tasks to add to the run (equivalent to calling
        ``enqueue_task`` with them): they run after the current batch, before the
        next ``next_tasks()``. Return ``None`` (the default) to add nothing.
        """
        return None

    async def task_complete(self, log: "EvalLog") -> list["Task"] | None:
        """A task finished — observe its log and optionally return follow-up tasks.

        Return a list of tasks to add to the run (like ``enqueue_task``): they run
        after the current batch. Return ``None`` (the default) to add nothing.
        """
        return None


def task_source(
    initial_tasks: list["Task"],
    *,
    next_tasks: Callable[[], Awaitable[list["Task"] | None]] | None = None,
    sample_complete: Callable[["EvalSample"], Awaitable[list["Task"] | None]]
    | None = None,
    task_complete: Callable[["EvalLog"], Awaitable[list["Task"] | None]] | None = None,
) -> TaskSource:
    """Create a :class:`TaskSource` from a seed plus optional callbacks.

    A convenience for when subclassing :class:`TaskSource` is more than you need:
    provide the initial tasks directly and, optionally, callbacks that react to
    results. The ``sample_complete`` / ``task_complete`` callbacks may **return**
    a list of follow-up tasks to add to the run (see those methods on
    :class:`TaskSource`); ``next_tasks`` is the blocking / explicit-pull
    alternative. Callbacks typically close over shared state (e.g. accumulated
    scores) to decide what to run next.

    Args:
        initial_tasks: The seed tasks to run first (see
            :meth:`TaskSource.initial_tasks`). Required, and resolved up front.
        next_tasks: Optional async callback returning the next batch, or ``None``
            to end the run (see :meth:`TaskSource.next_tasks`). If omitted (and no
            callback returns tasks), the run stops after the seed — equivalent to
            passing ``initial_tasks`` directly to ``eval()``.
        sample_complete: Optional async callback invoked as each sample finishes;
            may return follow-up tasks to add to the run.
        task_complete: Optional async callback invoked as each task finishes; may
            return follow-up tasks to add to the run.

    Returns:
        A ``TaskSource`` that delegates to the provided seed and callbacks.
    """
    return _CallableTaskSource(
        initial_tasks, next_tasks, sample_complete, task_complete
    )


class _CallableTaskSource(TaskSource):
    """A :class:`TaskSource` backed by a fixed seed and optional callables."""

    def __init__(
        self,
        initial_tasks: list["Task"],
        next_tasks: Callable[[], Awaitable[list["Task"] | None]] | None,
        sample_complete: Callable[["EvalSample"], Awaitable[list["Task"] | None]]
        | None,
        task_complete: Callable[["EvalLog"], Awaitable[list["Task"] | None]] | None,
    ) -> None:
        self._initial_tasks = list(initial_tasks)
        self._next_tasks = next_tasks
        self._sample_complete = sample_complete
        self._task_complete = task_complete

    def initial_tasks(self) -> list["Task"]:
        return self._initial_tasks

    async def next_tasks(self) -> list["Task"] | None:
        if self._next_tasks is not None:
            return await self._next_tasks()
        return None

    async def sample_complete(self, sample: "EvalSample") -> list["Task"] | None:
        if self._sample_complete is not None:
            return await self._sample_complete(sample)
        return None

    async def task_complete(self, log: "EvalLog") -> list["Task"] | None:
        if self._task_complete is not None:
            return await self._task_complete(log)
        return None
