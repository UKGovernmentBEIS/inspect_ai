"""Add tasks to a running eval.

A run can have tasks added to it while it is in progress. After each batch of
tasks completes, the eval loop drains whatever was enqueued during that batch
and runs it as the next batch — under the same ``run_id`` — repeating until
nothing remains. This module is the in-process primitive that makes that
possible; higher layers (an RL driver, a control-channel directive) build on it.

The eval runner registers a :class:`TaskEnqueuer` for the lifetime of the run.
It holds a *resolve* closure (built by the runner, capturing the run's models /
config / sandbox) that turns submitted tasks into ``ResolvedTask`` objects, plus
a buffer the loop drains. The active enqueuer lives in a ``ContextVar`` so it is
scoped to the run's async context (and propagates to its child tasks);
:func:`enqueue_task` validates an optional ``run_id`` against it so a stray/late
caller can't enqueue into the wrong (or torn-down) run.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Callable, Iterator

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.model import Model

# Resolve submitted tasks to concrete ``ResolvedTask``s against the run's
# models / config. Built by the eval runner (which holds that context) and
# handed to the enqueuer. Raises on tasks it can't resolve.
ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]


@dataclass
class TaskEnqueuer:
    """Buffers tasks added to one run and hands them to the eval loop.

    Owned by the eval runner for the run's lifetime. ``enqueue`` resolves and
    buffers (so a resolution error surfaces to the caller); ``drain`` is the
    non-blocking pull the loop does after each batch.
    """

    run_id: str
    _resolve: ResolveTasksFn
    _pending: list["ResolvedTask"] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)
    on_enqueue: Callable[[], None] | None = None
    """Fired after tasks are buffered — used by a live run to wake dispatch."""

    def enqueue(self, tasks: "Tasks") -> list["ResolvedTask"]:
        """Resolve ``tasks`` and queue them to run; returns the resolved tasks."""
        resolved = self._resolve(tasks)
        with self._lock:
            self._pending.extend(resolved)
        if self.on_enqueue is not None:
            self.on_enqueue()
        return resolved

    def drain(self) -> list["ResolvedTask"]:
        """Remove and return all currently-buffered tasks (empty if none)."""
        with self._lock:
            batch, self._pending = self._pending, []
        return batch


# The active run's enqueuer, scoped to the run's async context. The ``run_id``
# on the enqueuer lets :func:`enqueue_task` reject a caller targeting a
# different/stale run.
_enqueuer: ContextVar[TaskEnqueuer | None] = ContextVar("task_enqueuer", default=None)


@dataclass
class _CreatorAttempt:
    """The running attempt's model, marked ended when the attempt exits.

    Shared by reference with every context copied from the attempt, so a
    background coroutine that outlives its attempt sees it end.
    """

    model: Model
    ended: bool = False


# The task attempt running in this context: set for the duration of each
# attempt and cleared around TaskSource callbacks, so `creator_model()` is
# `None` outside a running task. Tasks added inside an attempt resolve once,
# under its model. `active_model()` can't stand in for
# it: outside an attempt it still holds the last run model that up-front task
# resolution activated. Temporary: the task handles design's `_attempt`
# ContextVar (set by `run_one` around the attempt, cleared in TaskSource
# callbacks) replaces it.
_creator: ContextVar[_CreatorAttempt | None] = ContextVar(
    "enqueue_creator", default=None
)


@contextmanager
def creator_model_scope(model: Model | None) -> Iterator[None]:
    """Run the scope as a task attempt on ``model``, or (``None``) as outside any attempt.

    An attempt's scope ends on every exit, including errors and cancellation;
    clearing it (``None``) leaves the enclosing attempt running.
    """
    attempt = _CreatorAttempt(model) if model is not None else None
    token = _creator.set(attempt)
    try:
        yield
    finally:
        if attempt is not None:
            attempt.ended = True
        _creator.reset(token)


def creator_model() -> Model | None:
    """The model of the task attempt running in this context, if it has not ended."""
    attempt = _creator.get()
    return attempt.model if attempt is not None and not attempt.ended else None


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


def enqueue_task(tasks: "Tasks", *, run_id: str | None = None) -> None:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files).

    Called from inside a running task (a solver, scorer, tool or other code
    the task runs), the tasks are added once, under that task's model.
    Called anywhere else, including from a ``TaskSource`` callback, they are
    added once per model of the run. A task that sets its own ``model`` keeps
    it. Model roles and generate config come from the run.

    When the run is driven by a :class:`~inspect_ai.TaskSource`, added tasks are
    *live*: they start as soon as there is free capacity. Otherwise they run as a
    follow-up batch, after the in-flight batch of tasks completes.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.

    Raises:
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, or a task is a
            placeholder that eval-set selection pruning left in place of a
            task it did not build.
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
    enqueuer.enqueue(tasks)
