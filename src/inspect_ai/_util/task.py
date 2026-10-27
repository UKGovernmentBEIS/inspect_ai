"""Task naming helpers and the active task (:func:`task_active`)."""

import contextlib
from contextvars import ContextVar
from typing import Iterator, NamedTuple

from inspect_ai._util.registry import registry_unqualified_name


def task_display_name(task_name: str) -> str:
    if task_name.startswith("hf/"):
        return task_name
    else:
        return registry_unqualified_name(task_name)


class ActiveTask(NamedTuple):
    """Identity of the task running in the current context.

    Set by the task runner (:func:`active_task`) for the task's whole run, so
    its samples, scoring and the task's code outside samples (such as a
    ``SampleSource``) see it. The task-level counterpart of ``ActiveSample``.
    """

    run_id: str
    """Run the task belongs to."""

    eval_id: str
    """Eval id of this attempt of the task (new for each retry)."""

    task_id: str
    """Task id (unchanged across retries)."""

    task: str
    """Task name."""

    log_location: str
    """Location of the task's log."""


@contextlib.contextmanager
def active_task(
    *, run_id: str, eval_id: str, task_id: str, task: str, log_location: str
) -> Iterator[ActiveTask]:
    """Make a task the active task (:func:`task_active`) for the enclosed code."""
    active = ActiveTask(
        run_id=run_id,
        eval_id=eval_id,
        task_id=task_id,
        task=task,
        log_location=log_location,
    )
    token = _task_active.set(active)
    try:
        yield active
    finally:
        _task_active.reset(token)


def task_active() -> ActiveTask | None:
    """The task running in the current context, or ``None`` outside any task."""
    return _task_active.get(None)


_task_active: ContextVar[ActiveTask | None] = ContextVar("_task_active", default=None)
