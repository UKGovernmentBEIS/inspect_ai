"""Add tasks to a running eval, and the run's queue of tasks waiting to start.

A run can have tasks added to it while it is in progress, under the same
``run_id``. Each run has one :class:`RunQueue`, which holds every task waiting
to start: the attempts that are ready (started up, waiting for a free slot or
a retry) and the tasks added with :func:`enqueue_task` (or returned by a
:class:`~inspect_ai.TaskSource` callback), filed by start policy until the
run's scheduling loop (``TaskDispatcher`` in ``inspect_ai._eval.run``) takes
them. The active queue lives in a ``ContextVar``, so it is scoped to the run's
async context (and propagates to its child tasks); :func:`enqueue_task`
validates an optional ``run_id`` against it so a stray or late caller can't
add to the wrong run, and the queue refuses additions once the run has
finished dispatching tasks.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Callable, Literal, NamedTuple, get_args

from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import TaskRunOptions
    from inspect_ai._eval.task.tasks import Tasks

# Resolve submitted tasks to concrete ``ResolvedTask``s against the run's
# models / config / sandbox. Built by the eval runner (which owns that state) and
# handed to the run's queue. Raises on tasks it can't resolve.
ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]

TaskStartPolicy = Literal["when_free", "after_batch"]
"""When an enqueued task starts (see :func:`enqueue_task`)."""


class Attempt(NamedTuple):
    """One attempt of a task, ready to start."""

    idx: int
    """Position of the task's log in the run's results (its retries keep it)."""

    options: TaskRunOptions
    """The attempt's run options, including its logger."""

    retries_remaining: int
    """Retry attempts left after this one."""


class RunQueue:
    """Every task waiting to start in one eval run.

    ``ready`` holds attempts that have started up. The scheduling loop owns
    it (it adds, picks and requeues attempts); the queue holds it so that
    :meth:`close` can hand back the attempts that will never start. Added tasks wait by start policy until the loop takes them:
    ``when_free`` ones on each of its cycles, ``after_batch`` ones once nothing
    is ready or running.

    Used only from the eval's event loop, and no method awaits, so no method
    interleaves with another and the queue needs no lock.
    """

    def __init__(
        self, run_id: str, resolve: ResolveTasksFn, default_start: TaskStartPolicy
    ) -> None:
        """Create the queue of one run.

        Args:
            run_id: The run's id (``enqueue_task`` checks callers against it).
            resolve: Resolves tasks against the run's models and config (also
                used by the loop for a ``TaskSource``'s ``next_tasks()``).
            default_start: The policy of ``put(start=None)``: ``when_free`` in a
                ``TaskSource`` run, ``after_batch`` otherwise.
        """
        self.run_id = run_id
        self.resolve = resolve
        self.default_start = default_start
        self.ready: list[Attempt] = []
        self.wake = Wake()
        """Set whenever the scheduling loop should look at the queue again."""
        self._added: dict[TaskStartPolicy, list[ResolvedTask]] = {
            "when_free": [],
            "after_batch": [],
        }
        self._closed = False

    def put(
        self, tasks: Tasks, *, start: TaskStartPolicy | None = None
    ) -> list[ResolvedTask]:
        """Resolve tasks added to the run and file them by start policy.

        Resolution errors surface to the caller. Returns the resolved tasks.

        Raises:
            RuntimeError: If the run has finished dispatching tasks.
        """
        if self._closed:
            raise RuntimeError(
                f"enqueue_task(): run '{self.run_id}' has finished dispatching "
                "tasks, so an added task would never run."
            )
        resolved = self.resolve(tasks)
        self._added[start or self.default_start].extend(resolved)
        self.wake.set()
        return resolved

    def take(self, start: TaskStartPolicy) -> list[ResolvedTask]:
        """Remove and return the added tasks waiting with this start policy."""
        taken, self._added[start] = self._added[start], []
        return taken

    def waiting(self) -> int:
        """The number of added tasks not yet taken."""
        return sum(len(tasks) for tasks in self._added.values())

    def close(self) -> list[Attempt]:
        """Refuse further additions and empty the queue.

        Returns the ready attempts, which will now never start, so the caller
        can discard their log entries.
        """
        self._closed = True
        self._added = {"when_free": [], "after_batch": []}
        ready, self.ready = self.ready, []
        return ready


# The run queue for the current eval run. A ContextVar (not a module global) so
# concurrent or nested runs in one process each see their own, and child tasks
# inherit it.
_run_queue: ContextVar[RunQueue | None] = ContextVar("run_queue", default=None)


def register_run_queue(queue: RunQueue) -> Token[RunQueue | None]:
    """Make ``queue`` the active run queue; returns a token to restore the previous."""
    return _run_queue.set(queue)


def get_run_queue() -> RunQueue | None:
    """The active run queue, or ``None`` if no eval is running here."""
    return _run_queue.get()


def clear_run_queue(token: Token[RunQueue | None]) -> None:
    """Restore the run queue in scope before the matching ``register`` call."""
    _run_queue.reset(token)


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

    A task that waits for a ``"when_free"`` task it added needs a free slot for
    it: ``eval()`` defaults ``max_tasks`` to the number of models (1 for a
    single model), so without a higher ``max_tasks`` the added task never
    starts and the run hangs. The same applies to ``eval_set()`` in selection
    mode (an external runner running the tasks it selected): ``eval_set()``'s
    own default (at least 10) is not applied there, so ``eval()``'s default
    is used unless the selection or the ``eval_set()`` call sets ``max_tasks``.

    In a :class:`~inspect_ai.TaskSource` run, tasks added while
    ``next_tasks()`` runs start only after it returns, so ``next_tasks()``
    must not wait for them.

    Call from the eval's event loop, not from another thread: from a solver,
    scorer or tool, a ``TaskSource``'s ``next_tasks()`` or completion
    callbacks, or a hook Inspect calls during a task (such as
    ``on_task_start`` or ``on_sample_end``). It raises in ``on_run_start``,
    which runs before the run accepts added tasks, and in ``on_run_end``,
    which runs after the run has finished starting tasks.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.
        start: When the added tasks start. ``"when_free"``: as soon as there is
            free task capacity. ``"after_batch"``: once no task is queued or
            running, including tasks added later with ``"when_free"``. ``None``
            (the default): ``"when_free"`` in a run driven by a
            :class:`~inspect_ai.TaskSource`, ``"after_batch"`` otherwise.

    Raises:
        ValueError: If ``start`` is not one of the values above, or the tasks
            can't be resolved (propagated from resolution).
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, or the run has finished
            dispatching tasks.
    """
    if start is not None and start not in get_args(TaskStartPolicy):
        raise ValueError(
            "enqueue_task(): start must be 'when_free', 'after_batch' or None, "
            f"not {start!r}."
        )
    queue = get_run_queue()
    if queue is None:
        raise RuntimeError(
            "enqueue_task() can only be called while an eval is running in this "
            "process."
        )
    if run_id is not None and run_id != queue.run_id:
        raise RuntimeError(
            f"enqueue_task() run_id '{run_id}' does not match the running eval "
            f"'{queue.run_id}'."
        )
    queue.put(tasks, start=start)
