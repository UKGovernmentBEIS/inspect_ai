"""Add tasks to a running eval, and the records of a run's tasks.

A run can have tasks added to it while it is in progress, under the same
``run_id``. Each run has one :class:`RunTasks`, which holds a
:class:`TaskRecord` for every task: the seed, tasks added with
:func:`enqueue_task` or returned by a :class:`~inspect_ai.TaskSource`
callback, and each ``next_tasks()`` batch. The run's scheduling loop
(``TaskDispatcher`` in ``inspect_ai._eval.run``) starts them. The active
``RunTasks`` lives in a ``ContextVar``, so it is scoped to the run's async
context; it refuses additions once the run has finished starting tasks.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, NamedTuple

from inspect_ai._control.pause import dispatch_model_name, note_dispatch_models
from inspect_ai._display import display
from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._display.core.display import TaskSpec
    from inspect_ai._eval.task.log import TaskLogger
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import EvalSampleSource, TaskRunOptions
    from inspect_ai._eval.task.setup_cache import SetupFailure, SetupJob
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.dataset import Dataset
    from inspect_ai.log import EvalLog
    from inspect_ai.model import Model

ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]
"""Resolves submitted tasks against the run's models, config and sandbox (built
by the eval runner, which owns that state); raises on tasks it can't resolve."""


@dataclass(frozen=True)
class ConfiguredTask:
    """A task configured for the run: everything its attempts need but a logger."""

    resolved: ResolvedTask
    spec: TaskSpec
    """Its row in the task display."""
    options: Callable[[TaskLogger], TaskRunOptions]
    """The run options of an attempt that logs to the given logger."""
    new_logger: Callable[[], TaskLogger]
    """A logger for a new attempt (not yet initialised)."""
    selected_samples: Callable[[], Dataset]
    """The samples the run's sample selection runs, as the task resolves it."""


ConfigureFn = Callable[["list[ResolvedTask]"], "list[ConfiguredTask]"]
"""Configures tasks for the run, in the order given; raises on invalid ones."""

PrepareFn = Callable[[ConfiguredTask], Awaitable[tuple[Any, ...]]]
"""Prepares a configured task to start: the sandbox configs its selected
samples use, in sample order; raises on configs it can't resolve."""


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
    retries: int
    """How many times the task is retried after an attempt that fails."""
    setup_keys: tuple[Any, ...]
    """The sandbox configs its selected samples use, in sample order."""
    logger: TaskLogger | None = None
    """The logger the record's next attempt uses: a seed task's first one
    (created when the seed starts up), or a failed attempt's, which its retry
    reinitialises. Other first attempts create theirs when they start."""
    setups: list[SetupJob[Any]] | None = None
    """The setup jobs of ``setup_keys`` (``None`` until they are requested)."""
    attempt: int = 1
    retry_source: EvalSampleSource | None = None
    """Where a retry attempt reads the completed samples of the failed one
    (``None``: the task's own sample source)."""
    log: EvalLog | None = None
    """The log of its latest attempt; once it has ended, its final log
    (``None`` if no attempt started: it was cancelled while queued, or the
    run ended first)."""
    ended: bool = False
    """Whether it has ended (set only by :meth:`RunTasks.end`)."""

    @property
    def retries_remaining(self) -> int:
        """Retry attempts left after the current one."""
        return self.retries - (self.attempt - 1)

    @property
    def failure(self) -> SetupFailure | None:
        """Why its sandboxes could not be set up; its next attempt ends with it."""
        return next((j.failure for j in self.setups or [] if j.failure), None)

    @property
    def can_start(self) -> bool:
        """Whether its sandboxes are set up, or have failed."""
        return self.failure is not None or (
            self.setups is not None and all(j.succeeded for j in self.setups)
        )


class RunTasks:
    """The records of every task of one eval run.

    ``queued`` holds the records that may start, in the order they were
    added, and ``running`` those with an attempt running; the scheduling loop
    moves a record from one to the other with :meth:`start` and back to the
    end of ``queued`` with :meth:`retry`. Every way a record ends goes
    through :meth:`end`. Only adding tasks awaits (to resolve them), and the
    lists change only after it has, so they need no lock.
    """

    def __init__(
        self,
        run_id: str,
        resolve: ResolveTasksFn,
        configure: ConfigureFn,
        prepare: PrepareFn,
        *,
        changed: Wake,
        retries: int,
        sequence_order: bool,
    ) -> None:
        """Create the tasks of one run.

        Args:
            run_id: The run's id (``enqueue_task`` checks callers against it).
            resolve: Resolves tasks against the run's models and config (also
                used by the loop for a ``TaskSource``'s ``next_tasks()``).
            configure: Configures tasks for the run.
            prepare: Resolves a configured task's sandbox configs.
            changed: Set whenever the scheduling loop should look at the tasks
                again: as tasks are queued, and by the run's ``SetupCache`` as
                each setup ends.
            retries: How many times a task that fails is retried.
            sequence_order: Order the tasks of each addition by sequence (at a
                launch limit of 1: the scheduling loop breaks ties in queue
                order, so all of a task's model fan-outs then run before the
                next task's).
        """
        self.run_id = run_id
        self.resolve = resolve
        self._configure = configure
        self._prepare = prepare
        self._retries = retries
        self._sequence_order = sequence_order
        self.queued: list[TaskRecord] = []
        self.running: set[TaskRecord] = set()
        self.changed = changed
        self.records: list[TaskRecord] = []
        """Every record queued, in the order it was queued."""
        self._by_id: dict[str, TaskRecord] = {}
        self._closed = False

    async def create(self, resolved: list[ResolvedTask]) -> list[TaskRecord]:
        """Records for resolved tasks, in start order (not yet queued).

        Configures every task first, so an invalid one raises before any is
        prepared; then resolves each one's sandbox configs.

        Raises:
            PrerequisiteError: If a task can't run with the run's settings.
            Exception: What resolving a task's sandbox configs raised.
        """
        if self._sequence_order:
            resolved = sorted(resolved, key=lambda t: t.sequence)
        configured_tasks = self._configure(resolved)
        return [
            TaskRecord(
                task_id=configured.resolved.id,
                task=configured.resolved.task.name,
                model=configured.resolved.model,
                configured=configured,
                retries=self._retries,
                setup_keys=await self._prepare(configured),
            )
            for configured in configured_tasks
        ]

    def find(self, task_id: str) -> TaskRecord | None:
        """The record of the run's task with this id, if there is one."""
        return self._by_id.get(task_id)

    async def add(self, tasks: Tasks) -> list[TaskRecord]:
        """Resolve tasks added to the run, create their records and queue them.

        Resolution, configuration and sandbox config errors surface to the
        caller; none of the tasks is queued then. Returns the records in
        start order.
        """
        records = await self.create(self.resolve(tasks))
        if self._closed:
            raise RuntimeError(
                f"enqueue_task(): run '{self.run_id}' has finished dispatching "
                "tasks, so an added task would never run."
            )
        self.enqueue(records)
        return records

    def enqueue(self, records: list[TaskRecord]) -> None:
        """Queue records to start, after those already queued.

        Notes their models for the model pause directives (a task that has not
        started has no ``EvalState`` to check) and grows the task display's
        count.
        """
        self.records.extend(records)
        self.queued.extend(records)
        self._by_id.update((record.task_id, record) for record in records)
        note_dispatch_models([dispatch_model_name(r.model) for r in records])
        display().update_task_count(len(records))
        self.changed.set()

    def start(self, record: TaskRecord) -> None:
        """Move a queued record to the running ones as its attempt starts."""
        self.queued.remove(record)
        self.running.add(record)

    def retry(self, record: TaskRecord) -> None:
        """Put a running record whose attempt failed back at the end of the queue."""
        self.running.remove(record)
        record.attempt += 1
        self.queued.append(record)

    def end(self, record: TaskRecord) -> None:
        """End a record, keeping its latest log; it drops what only its attempts need.

        The one place a record ends: after its last attempt, when it is
        cancelled while waiting to start, and when the run ends before it
        does.
        """
        self.running.discard(record)
        record.ended = True
        record.configured = None
        record.logger = None
        record.retry_source = None
        record.setups = None

    def close_if_idle(self) -> bool:
        """Refuse additions once nothing is running or queued; whether it closed.

        A single call, so nothing can be added between the check and the close.
        """
        if self.running or self.queued:
            return False
        self._closed = True
        return True

    def close(self) -> list[TaskRecord]:
        """Refuse further additions and empty the queue.

        Returns the records that will now never start.
        """
        self._closed = True
        unstarted, self.queued = self.queued, []
        return unstarted

    def results(self) -> list[EvalLog]:
        """The final log of each task that has one, in the order they were queued."""
        return [
            record.log
            for record in self.records
            if record.ended and record.log is not None
        ]


# The tasks of the current eval run. A ContextVar (not a module global) so
# concurrent or nested runs in one process each see their own, and child tasks
# inherit it.
_run_tasks: ContextVar[RunTasks | None] = ContextVar("run_tasks", default=None)

# The tasks of every run active in this process, for `inspect ctl`: its handlers run on
# the eval's event loop but not in the run's context.
_active_runs: list[RunTasks] = []


def register_run_tasks(tasks: RunTasks) -> Token[RunTasks | None]:
    """Make ``tasks`` the active run's; returns a token to restore the previous."""
    _active_runs.append(tasks)
    return _run_tasks.set(tasks)


def get_run_tasks() -> RunTasks | None:
    """The active run's tasks, or ``None`` if no eval is running here."""
    return _run_tasks.get()


def clear_run_tasks(token: Token[RunTasks | None]) -> None:
    """Restore the run's tasks in scope before the matching ``register`` call."""
    tasks = _run_tasks.get()
    assert tasks is not None
    _active_runs.remove(tasks)
    _run_tasks.reset(token)


class ActiveTask(NamedTuple):
    """A task of a run in progress in this process."""

    tasks: RunTasks
    record: TaskRecord


def find_active_task(task_id: str) -> ActiveTask | None:
    """The task with this id in a run in progress in this process, if any."""
    for tasks in _active_runs:
        record = tasks.find(task_id)
        if record is not None:
            return ActiveTask(tasks, record)
    return None


async def enqueue_task(tasks: "Tasks", *, run_id: str | None = None) -> None:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files), resolved against the
    run's models and config. Each starts when a task slot is free, under the
    run's ``max_tasks`` limit (which ``inspect ctl config --max-tasks``
    changes live), after the tasks queued before it. The call returns once
    the tasks are queued: it resolves each task's sandbox configs first, so
    an invalid config raises here and adds none of the tasks. A task whose
    sandboxes are still being set up does not hold back a later task that is
    ready. If an added task's sandbox setup fails, that task ends with an
    error log (its retries apply) and the run continues.

    A task that waits for a task it added needs a free slot for it:
    ``eval()`` defaults ``max_tasks`` to the number of models, so without a
    higher ``max_tasks`` the run hangs. In a :class:`~inspect_ai.TaskSource`
    run, tasks added while ``next_tasks()`` runs start only after it returns,
    so ``next_tasks()`` must not wait for them.

    Call from the eval's event loop, not from another thread: from a solver,
    scorer or tool, a ``TaskSource`` callback, or a hook Inspect calls during
    a task (such as ``on_task_start`` or ``on_sample_end``). It raises in
    ``on_run_start`` and ``on_run_end``, which run outside the run.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.

    Raises:
        ValueError: If the tasks can't be resolved (propagated from
            resolution).
        PrerequisiteError: If a task can't run with the run's settings (for
            example duplicate sample ids).
        Exception: What resolving a task's sandbox configs raised (for
            example a missing compose file).
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, or the run has finished
            starting tasks.
    """
    run_tasks = get_run_tasks()
    if run_tasks is None:
        raise RuntimeError(
            "enqueue_task() can only be called while an eval is running in this "
            "process."
        )
    if run_id is not None and run_id != run_tasks.run_id:
        raise RuntimeError(
            f"enqueue_task() run_id '{run_id}' does not match the running eval "
            f"'{run_tasks.run_id}'."
        )
    await run_tasks.add(tasks)
