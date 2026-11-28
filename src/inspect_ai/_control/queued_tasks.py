"""Tasks of the running eval that have not registered with the control channel.

A task is listed here from the moment it is added to the run's queue until one
of its attempts registers its ``EvalState`` (``register_eval``) or the task
ends, so ``GET /tasks`` lists it and ``inspect ctl task cancel`` / ``drain``
reach it before it starts (see ``design/task-dispatch.md``, "Control
channel"). A task that ends without registering is registered as a finished
eval before it leaves, so a directive always finds it in one of the two.

Only the run's event loop changes the registry, in synchronous steps, and the
control server runs on that loop, so it needs no lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from inspect_ai._eval.task.enqueue import TaskRecord
    from inspect_ai.log._log import EvalSpec


@dataclass(frozen=True)
class QueuedTask:
    """A task that has not registered: its run-queue record and how to cancel it."""

    record: "TaskRecord"
    cancel: Callable[[], None]
    """Cancels the record through its run queue (``RunQueue.cancel``)."""

    @property
    def eval(self) -> "EvalSpec":
        """The eval spec of the task's current attempt."""
        options = self.record.options
        assert options is not None, "a listed task has not ended"
        return options.logger.eval

    @property
    def epochs(self) -> int:
        """The task's planned epoch count."""
        return self.record.epochs


_queued_tasks: dict[str, QueuedTask] = {}


def register_queued_task(record: "TaskRecord", cancel: Callable[[], None]) -> None:
    """List a task added to the run's queue."""
    _queued_tasks[record.task_id] = QueuedTask(record=record, cancel=cancel)


def unregister_queued_task(record: "TaskRecord") -> None:
    """Remove ``record``'s entry (when it registers or ends)."""
    entry = _queued_tasks.get(record.task_id)
    if entry is not None and entry.record is record:
        del _queued_tasks[record.task_id]


def find_queued_task(task_id: str) -> QueuedTask | None:
    """The listed task with ``task_id``, if any."""
    return _queued_tasks.get(task_id)


def queued_tasks() -> list[QueuedTask]:
    """Every listed task, in the order they were added."""
    return list(_queued_tasks.values())


def reset_queued_tasks() -> None:
    """Clear the registry (run boundary; see ``reset_run_registries``)."""
    _queued_tasks.clear()
