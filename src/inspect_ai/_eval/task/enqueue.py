"""Add tasks to a running eval.

A run can have tasks added to it while it is in progress, under the same
``run_id``. Every run has one task dispatcher; an added task joins its queue
either at once (``start="when_free"``: it starts as soon as there is free task
capacity) or once the dispatcher is idle (``start="after_batch"``: every task
already in the run, running or queued, has finished). This module is the
in-process primitive that makes that possible; higher layers (an RL driver, a
control-channel directive) build on it.

The eval runner creates one :class:`TaskEnqueuer` per run: the run's source of
added tasks, both those passed to :func:`enqueue_task` and those a
:class:`~inspect_ai.TaskSource` returns from ``next_tasks()``. It holds a
*resolve* closure (built by the runner, capturing the run's models / config /
sandbox) that turns submitted tasks into ``ResolvedTask`` objects, the buffers
of enqueued tasks, and the run's ``TaskSource`` (if any); the dispatcher takes
tasks from it through the ``AddedTasks`` protocol. The active enqueuer lives in
a ``ContextVar`` so it is scoped to the run's async context (and propagates to
its child tasks); :func:`enqueue_task` validates an optional ``run_id`` against
it so a stray/late caller can't enqueue into the wrong run, and the enqueuer
refuses additions once the run has finished dispatching.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.task_source import TaskSource
    from inspect_ai._eval.task.tasks import Tasks

# Resolve submitted tasks to concrete ``ResolvedTask``s against the run's
# models / config. Built by the eval runner (which holds that context) and
# handed to the enqueuer. Raises on tasks it can't resolve.
ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]

TaskStartPolicy = Literal["when_free", "after_batch"]
"""When an enqueued task starts (see :func:`enqueue_task`)."""


@dataclass
class TaskEnqueuer:
    """The source of tasks added to one run, for the run's dispatcher.

    Tasks come from :meth:`enqueue` (``enqueue_task()`` and a ``TaskSource``'s
    completion callbacks) and from the run's ``TaskSource``'s ``next_tasks()``.
    ``enqueue`` resolves and buffers (so a resolution error surfaces to the
    caller), one buffer per start policy. The dispatcher takes :meth:`ready` on
    every cycle and calls :meth:`when_idle` only once it is idle. When
    ``when_idle`` finds nothing more to run it closes the enqueuer (as the
    runner does when a run ends early); later enqueues raise, since nothing
    would run them.
    """

    run_id: str
    _resolve: ResolveTasksFn
    _source: "TaskSource | None"
    _pending: dict[TaskStartPolicy, list["ResolvedTask"]] = field(
        default_factory=lambda: {"when_free": [], "after_batch": []}
    )
    _lock: Lock = field(default_factory=Lock)
    _wake: Callable[[], None] | None = None
    _source_ended: bool = False
    _closed: bool = False

    @property
    def default_start(self) -> TaskStartPolicy:
        """The policy for ``enqueue(start=None)``: ``when_free`` in a ``TaskSource`` run."""
        return "when_free" if self._source is not None else "after_batch"

    def enqueue(
        self, tasks: "Tasks", *, start: TaskStartPolicy | None = None
    ) -> list["ResolvedTask"]:
        """Resolve ``tasks`` and queue them to run; returns the resolved tasks.

        Raises:
            RuntimeError: If the run has finished dispatching tasks.
        """
        if self._closed:
            raise RuntimeError(
                f"enqueue_task(): run '{self.run_id}' has finished dispatching "
                "tasks, so an added task would never run."
            )
        resolved = self._resolve(tasks)
        with self._lock:
            self._pending[start or self.default_start].extend(resolved)
        if self._wake is not None:
            self._wake()
        return resolved

    def set_wake(self, wake: Callable[[], None]) -> None:
        """Register the callback fired after tasks are buffered (wakes dispatch)."""
        self._wake = wake

    def ready(self) -> list["ResolvedTask"]:
        """Remove and return the buffered ``when_free`` tasks (empty if none)."""
        return self._drain("when_free")

    async def when_idle(self) -> list["ResolvedTask"] | None:
        """The next tasks to run once the dispatcher is idle, or ``None`` when the run is complete.

        In order: buffered ``after_batch`` tasks; else the ``TaskSource``'s
        ``next_tasks()``, until it first returns nothing (it is not called
        again after that); else any tasks enqueued meanwhile. If there are
        none, closes the enqueuer and returns ``None``.
        """
        after_batch = self._drain("after_batch")
        if after_batch:
            return after_batch
        if self._source is not None and not self._source_ended:
            more = await self._source.next_tasks()
            if more:
                return self._resolve(more)
            self._source_ended = True
        # next_tasks() may block, and the source (or code it started) may
        # enqueue meanwhile
        late = self._drain("when_free") + self._drain("after_batch")
        if late:
            return late
        # the dispatcher finishes without asking again, so a later enqueue
        # could never run
        self.close()
        return None

    def close(self) -> None:
        """Refuse further enqueues: the run has finished dispatching tasks."""
        self._closed = True

    def _drain(self, start: TaskStartPolicy) -> list["ResolvedTask"]:
        with self._lock:
            batch, self._pending[start] = self._pending[start], []
        return batch


# The active run's enqueuer, scoped to the run's async context. The ``run_id``
# on the enqueuer lets :func:`enqueue_task` reject a caller targeting a
# different/stale run.
_enqueuer: ContextVar[TaskEnqueuer | None] = ContextVar("task_enqueuer", default=None)


def create_task_enqueuer(
    run_id: str, resolve: ResolveTasksFn, source: "TaskSource | None"
) -> TaskEnqueuer:
    return TaskEnqueuer(run_id=run_id, _resolve=resolve, _source=source)


def register_task_enqueuer(enqueuer: TaskEnqueuer) -> Token[TaskEnqueuer | None]:
    """Install ``enqueuer`` as the active one; returns a token to restore with."""
    return _enqueuer.set(enqueuer)


def get_task_enqueuer() -> TaskEnqueuer | None:
    return _enqueuer.get()


def clear_task_enqueuer(token: Token[TaskEnqueuer | None]) -> None:
    """Restore the enqueuer in scope before the matching ``register`` call."""
    _enqueuer.reset(token)


def enqueue_task(
    tasks: "Tasks",
    *,
    run_id: str | None = None,
    start: TaskStartPolicy | None = None,
) -> None:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files), resolved against the
    run's models and config. They start under the run's ``max_tasks`` limit,
    which is re-read live, so raising it with ``inspect ctl config --max-tasks``
    lets a waiting task start.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.
        start: When the added tasks start. ``"when_free"``: as soon as there is
            free task capacity. ``"after_batch"``: once every task already in
            the run, running or queued, has finished. ``None`` (the default):
            ``"when_free"`` in a run driven by a :class:`~inspect_ai.TaskSource`,
            ``"after_batch"`` otherwise.

    Raises:
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, or the run has finished
            dispatching tasks.
        ValueError: If the tasks can't be resolved (propagated from resolution).
    """
    enqueuer = get_task_enqueuer()
    if enqueuer is None:
        raise RuntimeError(
            "enqueue_task() can only be called while an eval is running in this "
            "process."
        )
    if run_id is not None and run_id != enqueuer.run_id:
        raise RuntimeError(
            f"enqueue_task() run_id '{run_id}' does not match the running eval "
            f"'{enqueuer.run_id}'."
        )
    enqueuer.enqueue(tasks, start=start)
