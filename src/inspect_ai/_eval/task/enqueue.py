"""Add tasks to a running eval.

A run can have tasks added to it while it is in progress. By default, after
each batch of tasks completes, the eval loop drains whatever was enqueued during
that batch and runs it as the next batch — under the same ``run_id`` — repeating
until nothing remains. A task enqueued with ``start="when_free"`` instead joins
the batch that is running and starts as soon as there is free task capacity.
This module is the in-process primitive that makes that possible; higher layers
(an RL driver, a control-channel directive) build on it.

The eval runner registers a :class:`TaskEnqueuer` for the lifetime of the run.
It holds a *resolve* closure (built by the runner, capturing the run's models /
config / sandbox) that turns submitted tasks into ``ResolvedTask`` objects, plus
a buffer the loop drains. The active enqueuer lives in a ``ContextVar`` so it is
scoped to the run's async context (and propagates to its child tasks);
:func:`enqueue_task` validates an optional ``run_id`` against it so a stray/late
caller can't enqueue into the wrong (or torn-down) run.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.tasks import Tasks

# Resolve submitted tasks to concrete ``ResolvedTask``s against the run's
# models / config. Built by the eval runner (which holds that context) and
# handed to the enqueuer. Raises on tasks it can't resolve.
ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]

TaskStartPolicy = Literal["after_batch", "when_free"]
"""When an enqueued task starts (see :func:`enqueue_task`)."""


@dataclass
class TaskEnqueuer:
    """Buffers tasks added to one run and hands them to the eval loop.

    Owned by the eval runner for the run's lifetime. ``enqueue`` resolves and
    buffers (so a resolution error surfaces to the caller). Tasks enqueued with
    ``start="after_batch"`` are held in one buffer, which ``drain`` empties after
    each batch; tasks enqueued with ``start="when_free"`` are held in a second
    buffer, which ``drain_when_free`` empties on every dispatch cycle of the
    running batch.
    """

    run_id: str
    _resolve: ResolveTasksFn
    _pending: list["ResolvedTask"] = field(default_factory=list)
    _pending_when_free: list["ResolvedTask"] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)
    on_enqueue: Callable[[], None] | None = None
    """Fired after ``after_batch`` tasks are buffered — used by a live run to wake dispatch."""
    on_enqueue_when_free: Callable[[], None] | None = None
    """Fired after ``when_free`` tasks are buffered — wakes the running batch's dispatch."""

    def enqueue(
        self, tasks: "Tasks", *, start: TaskStartPolicy = "after_batch"
    ) -> list["ResolvedTask"]:
        """Resolve ``tasks`` and queue them to run; returns the resolved tasks."""
        resolved = self._resolve(tasks)
        with self._lock:
            if start == "when_free":
                self._pending_when_free.extend(resolved)
            else:
                self._pending.extend(resolved)
        wake = self.on_enqueue_when_free if start == "when_free" else self.on_enqueue
        if wake is not None:
            wake()
        return resolved

    def drain(self) -> list["ResolvedTask"]:
        """Remove and return all buffered ``after_batch`` tasks (empty if none)."""
        with self._lock:
            batch, self._pending = self._pending, []
        return batch

    def drain_when_free(self) -> list["ResolvedTask"]:
        """Remove and return all buffered ``when_free`` tasks (empty if none)."""
        with self._lock:
            batch, self._pending_when_free = self._pending_when_free, []
        return batch


# The active run's enqueuer, scoped to the run's async context. The ``run_id``
# on the enqueuer lets :func:`enqueue_task` reject a caller targeting a
# different/stale run.
_enqueuer: ContextVar[TaskEnqueuer | None] = ContextVar("task_enqueuer", default=None)


def create_task_enqueuer(run_id: str, resolve: ResolveTasksFn) -> TaskEnqueuer:
    return TaskEnqueuer(run_id=run_id, _resolve=resolve)


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
    start: TaskStartPolicy = "after_batch",
) -> None:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files), resolved against the
    run's models and config.

    With ``start="after_batch"`` (the default), added tasks run as a follow-up
    batch, after the in-flight batch of tasks completes. The exception is a run
    driven by a :class:`~inspect_ai.TaskSource` with ``max_tasks`` greater than
    1: there, added tasks start as soon as there is free capacity.

    With ``start="when_free"``, added tasks join the running batch and start as
    soon as there is free capacity under ``max_tasks``, whatever drove the run
    (``eval()``, ``eval_set()``, or a ``TaskSource``). Capacity is re-read live,
    so raising the limit with ``inspect ctl config --max-tasks`` gives a queued
    task its slot. A task enqueued after its batch has stopped dispatching runs
    as the next batch.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.
        start: When the added tasks start: ``"after_batch"`` or ``"when_free"``.

    Raises:
        RuntimeError: If no eval is currently running in this process, or
            ``run_id`` doesn't match the active run.
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
