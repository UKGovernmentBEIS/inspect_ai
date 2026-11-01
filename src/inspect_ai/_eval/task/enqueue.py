"""Add tasks to a running eval, and the records of a run's tasks.

A run can have tasks added to it while it is in progress, under the same
``run_id``. Each run has one :class:`RunQueue`, which holds a
:class:`TaskRecord` for every task from the moment it is added until it ends:
the seed tasks, tasks added with :func:`enqueue_task` or returned by a
:class:`~inspect_ai.TaskSource` callback, and each ``next_tasks()`` batch. The
run's scheduling loop (``TaskDispatcher`` in ``inspect_ai._eval.run``) starts
them. The active queue lives in a ``ContextVar``, so it is scoped to the run's
async context (and propagates to its child tasks); :func:`enqueue_task`
validates an optional ``run_id`` against it so a stray or late caller can't add
to the wrong run, and the queue refuses additions once the run has finished
starting tasks.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, get_args

from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._eval.task.log import TaskLogger
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import EvalSampleSource, TaskRunOptions
    from inspect_ai._eval.task.setup_cache import SetupFailure, SetupJob
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.log import EvalLog
    from inspect_ai.model import Model

ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]
"""Resolves submitted tasks against the run's models, config and sandbox (built
by the eval runner, which owns that state); raises on tasks it can't resolve."""

TaskStartPolicy = Literal["when_free", "after_batch"]
"""When an enqueued task starts (see :func:`enqueue_task`)."""


@dataclass(frozen=True)
class ConfiguredTask:
    """A task configured for the run: everything its attempts need but a logger."""

    resolved: ResolvedTask
    options: Callable[[TaskLogger], TaskRunOptions]
    """The run options of an attempt that logs to the given logger."""
    new_logger: Callable[[], TaskLogger]
    """A logger for a new attempt (not yet initialised)."""


ConfigureFn = Callable[["list[ResolvedTask]"], "list[ConfiguredTask]"]
"""Configures tasks for the run, in the order given; raises on invalid ones."""


@dataclass(eq=False)
class TaskRecord:
    """A task of the run, from the moment it is added until it ends.

    An attempt's own state (its log, the control channel's ``EvalState``) is
    created when the attempt starts; the record carries what lasts across
    attempts. When the record ends it drops the configured task and its
    logger, so a finished task's dataset is not kept until the run ends.
    """

    task_id: str
    task: str
    model: Model
    configured: ConfiguredTask | None
    retries_remaining: int
    """Retry attempts left after the current one."""
    logger: TaskLogger | None = None
    """The logger the record's next attempt uses: a seed task's first one
    (created when the seed starts up), or a failed attempt's, which its retry
    reinitialises. Other first attempts create theirs when they start."""
    setups: list[SetupJob[Any]] | None = None
    """The setup jobs of the sandbox configs its selected samples use (``None``
    until the record is prepared)."""
    setup_failure: SetupFailure | None = None
    """Why its sandbox configs could not be resolved (when preparing it)."""
    attempt: int = 1
    retry_source: EvalSampleSource | None = None
    """Where a retry attempt reads the completed samples of the failed one
    (``None``: the task's own sample source)."""
    log: EvalLog | None = None

    @property
    def failure(self) -> SetupFailure | None:
        """Why its sandboxes could not be prepared or set up; its next attempt ends with it."""
        if self.setup_failure is not None:
            return self.setup_failure
        return next((j.failure for j in self.setups or [] if j.failure), None)

    @property
    def can_start(self) -> bool:
        """Whether its sandboxes are set up, or have failed."""
        return self.failure is not None or (
            self.setups is not None and all(j.succeeded for j in self.setups)
        )

    def end(self) -> None:
        """Drop what only its attempts need: its task, logger and setups."""
        self.configured = None
        self.logger = None
        self.retry_source = None
        self.setups = None
        self.setup_failure = None


class RunQueue:
    """The records of every task of one eval run.

    ``queued`` holds the records that may start, in start order; the
    scheduling loop owns it (it picks records and puts retries back at the
    end), and the queue holds it so that :meth:`close` can end the records
    that will never start. Added records wait by start policy until the loop
    takes them: ``when_free`` ones on each of its cycles, ``after_batch`` ones
    once nothing is queued or running.

    Used only from the eval's event loop, and no method awaits, so no method
    interleaves with another and the queue needs no lock.
    """

    def __init__(
        self,
        run_id: str,
        resolve: ResolveTasksFn,
        configure: ConfigureFn,
        *,
        retries: int,
        sequence_order: bool,
        default_start: TaskStartPolicy,
    ) -> None:
        """Create the queue of one run.

        Args:
            run_id: The run's id (``enqueue_task`` checks callers against it).
            resolve: Resolves tasks against the run's models and config (also
                used by the loop for a ``TaskSource``'s ``next_tasks()``).
            configure: Configures tasks for the run.
            retries: How many times a task that fails is retried.
            sequence_order: Order the tasks of each addition by sequence (at a
                launch limit of 1: the scheduling loop breaks ties in queue
                order, so all of a task's model fan-outs then run before the
                next task's).
            default_start: The policy of ``put(start=None)``: ``when_free`` in a
                ``TaskSource`` run, ``after_batch`` otherwise.
        """
        self.run_id = run_id
        self.resolve = resolve
        self.default_start = default_start
        self._configure = configure
        self._retries = retries
        self._sequence_order = sequence_order
        self.queued: list[TaskRecord] = []
        self.wake = Wake()
        """Set whenever the scheduling loop should look at the queue again."""
        self.records: list[TaskRecord] = []
        """Every record the loop has taken, in the order it took them."""
        self._added: dict[TaskStartPolicy, list[TaskRecord]] = {
            "when_free": [],
            "after_batch": [],
        }
        self._closed = False

    def add(self, resolved: list[ResolvedTask]) -> list[TaskRecord]:
        """Configure resolved tasks; their records, in start order (not yet filed).

        Raises:
            RuntimeError: If the run has finished dispatching tasks.
            PrerequisiteError: If a task can't run with the run's settings.
        """
        self._check_open()
        if self._sequence_order:
            resolved = sorted(resolved, key=lambda t: t.sequence)
        return [
            TaskRecord(
                task_id=configured.resolved.id,
                task=configured.resolved.task.name,
                model=configured.resolved.model,
                configured=configured,
                retries_remaining=self._retries,
            )
            for configured in self._configure(resolved)
        ]

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError(
                f"enqueue_task(): run '{self.run_id}' has finished dispatching "
                "tasks, so an added task would never run."
            )

    def put(
        self, tasks: Tasks, *, start: TaskStartPolicy | None = None
    ) -> list[TaskRecord]:
        """Resolve and configure tasks added to the run, and file them by start policy.

        Resolution and configuration errors surface to the caller; no record
        is created for any of the tasks then. Returns the records in start
        order.
        """
        self._check_open()
        records = self.add(self.resolve(tasks))
        policy = start or self.default_start
        self._added[policy].extend(records)
        self.wake.set()
        return records

    def take(self, start: TaskStartPolicy) -> list[TaskRecord]:
        """Remove and return the added records waiting with this start policy."""
        taken, self._added[start] = self._added[start], []
        return taken

    def enqueue(self, records: list[TaskRecord]) -> None:
        """Make records eligible to start, after those already queued."""
        self.records.extend(records)
        self.queued.extend(records)

    def unstarted(self) -> list[TaskRecord]:
        """Every record waiting to start: queued, then added and not yet taken."""
        return [*self.queued, *self._added["when_free"], *self._added["after_batch"]]

    def remove(self, record: TaskRecord) -> None:
        """Remove a record that has not started from the queue (it will not start)."""
        if record in self.queued:
            self.queued.remove(record)
        for added in self._added.values():
            if record in added:
                added.remove(record)

    def close_if_idle(self, running: int) -> bool:
        """Refuse further additions if nothing is left to start; whether it closed.

        ``running`` is the number of records running. A single call, so nothing
        can be added between the check and the close.
        """
        if running or self.unstarted():
            return False
        self._closed = True
        return True

    def close(self) -> list[TaskRecord]:
        """Refuse further additions and empty the queue.

        Returns the records that will now never start; the caller releases
        their loggers and ends them.
        """
        self._closed = True
        unstarted = self.unstarted()
        self.queued = []
        self._added = {"when_free": [], "after_batch": []}
        return unstarted

    def results(self) -> list[EvalLog]:
        """The final log of each task that wrote one, in the order the loop took them."""
        return [record.log for record in self.records if record.log is not None]


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
    lets a waiting task start. A task whose sandboxes are still being set up
    does not hold back a later task that is ready to start.

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

    If an added task's sandbox setup fails, the task ends with an error log
    (its retries apply), and the run continues.

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
        PrerequisiteError: If a task can't run with the run's settings (for
            example duplicate sample ids).
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, or the run has finished
            starting tasks.
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
