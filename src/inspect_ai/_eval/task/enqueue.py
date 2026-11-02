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
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    NamedTuple,
)

import anyio

from inspect_ai._control.pause import dispatch_model_name, note_dispatch_models
from inspect_ai._display import display
from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._display.core.display import TaskSpec
    from inspect_ai._eval.task.log import TaskLogger
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import TaskRunOptions
    from inspect_ai._eval.task.setup_cache import SetupFailure, SetupJob
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.dataset import Dataset
    from inspect_ai.log import EvalLog
    from inspect_ai.model import Model

TaskState = Literal["queued", "running", "ended"]
"""Where a task added to the run is (see :attr:`TaskHandle.state`)."""

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
    """A task of the run, from the moment it is queued until it ends.

    An attempt's own state (its log, the control channel's ``EvalState``) is
    created when the attempt starts; the record carries what lasts across
    attempts. When the record ends it drops the configured task, so a
    finished task's dataset is not kept until the run ends.
    """

    task_id: str
    task: str
    model: Model
    configured: ConfiguredTask | None
    setup_keys: tuple[Any, ...]
    """The sandbox configs its selected samples use, in sample order."""
    logger: TaskLogger | None = None
    """A seed task's first logger, created (not yet initialised) when the seed
    starts up and taken by its first attempt. Other tasks create theirs when
    they start."""
    setups: list[SetupJob[Any]] | None = None
    """The setup jobs of ``setup_keys`` (``None`` until they are requested)."""
    log: EvalLog | None = None
    """The log of its latest attempt; once it has ended, its final log
    (``None`` if no attempt started: it was cancelled while queued, or the
    run ended first)."""
    ended: bool = False
    """Whether it has ended (set only by :meth:`RunTasks.end`)."""
    ended_event: anyio.Event | None = None
    """Set when it ends, for those waiting for it (created by the first)."""

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
    added (a ``next_tasks()`` batch ahead of the records added while it was
    made, see :meth:`add_ahead`), and ``running`` those that have started (including one between
    attempts); the scheduling loop moves a record from one to the other with
    :meth:`start`. Every way a record ends goes through :meth:`end`. Every
    method that changes the records rings :attr:`changed`, so whoever changes
    them never has to. Only adding tasks awaits (to resolve them), and the
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
        sequence_order: bool,
    ) -> None:
        """Create the tasks of one run.

        Args:
            run_id: The run's id (``enqueue_task`` checks callers against it).
            resolve: Resolves tasks against the run's models and config.
            configure: Configures tasks for the run.
            prepare: Resolves a configured task's sandbox configs.
            changed: Rung whenever the scheduling loop should look at the
                tasks again: by every change to them, by the run's
                ``SetupCache`` as each setup ends, and by ``inspect ctl`` as a
                setting that decides what can start changes.
            sequence_order: Order the tasks of each addition by sequence (at a
                launch limit of 1: the scheduling loop breaks ties in queue
                order, so all of a task's model fan-outs then run before the
                next task's).
        """
        self.run_id = run_id
        self._resolve = resolve
        self._configure = configure
        self._prepare = prepare
        self._sequence_order = sequence_order
        self.queued: list[TaskRecord] = []
        self.running: set[TaskRecord] = set()
        self.changed = changed
        self.records: list[TaskRecord] = []
        """Every record queued, in the order it was queued, except that a
        ``next_tasks()`` batch is ahead of the records queued while it was
        made (see :meth:`add_ahead`)."""
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
                setup_keys=await self._prepare(configured),
            )
            for configured in configured_tasks
        ]

    def find(self, task_id: str) -> TaskRecord | None:
        """The record of the run's task with this id, if there is one."""
        return self._by_id.get(task_id)

    async def add(self, tasks: Tasks) -> list[TaskRecord]:
        """Resolve tasks added to the run, create their records and queue them.

        The one way tasks are added once the run has started: by
        :func:`enqueue_task`, which tasks a ``TaskSource`` callback returns
        go through too, and (with :meth:`add_ahead`) by the scheduling loop
        for a ``next_tasks()`` batch. Resolution, configuration and sandbox
        config errors surface to the caller; none of the tasks is queued
        then. Returns the records in start order.
        """
        records = await self._create_added(tasks)
        self.enqueue(records)
        return records

    async def add_ahead(self, tasks: Tasks) -> list[TaskRecord]:
        """Add tasks as :meth:`add` does, but queue them ahead of the queued records.

        How the scheduling loop adds a ``next_tasks()`` batch: it asks for
        one only when nothing is queued or running, so the records queued by
        the time the batch is ready were added while it was being made, and
        the batch goes ahead of them.
        """
        records = await self._create_added(tasks)
        self.enqueue_ahead(records)
        return records

    async def _create_added(self, tasks: Tasks) -> list[TaskRecord]:
        """Records for tasks added to the run, unless it has finished starting tasks."""
        records = await self.create(self._resolve(tasks))
        if self._closed:
            raise RuntimeError(
                f"enqueue_task(): run '{self.run_id}' has finished dispatching "
                "tasks, so an added task would never run."
            )
        return records

    def enqueue(self, records: list[TaskRecord]) -> None:
        """Queue records to start, after those already queued."""
        self.records.extend(records)
        self.queued.extend(records)
        self._note_queued(records)

    def enqueue_ahead(self, records: list[TaskRecord]) -> None:
        """Queue records to start, ahead of those already queued.

        They are also listed in :attr:`records` (so in the run's results)
        ahead of the first queued record.
        """
        position = (
            self.records.index(self.queued[0]) if self.queued else len(self.records)
        )
        self.records[position:position] = records
        self.queued[:0] = records
        self._note_queued(records)

    def _note_queued(self, records: list[TaskRecord]) -> None:
        """Take note of records just queued.

        Indexes them by task id, notes their models for the model pause
        directives (a task that has not started has no ``EvalState`` to
        check) and grows the task display's count.
        """
        self._by_id.update((record.task_id, record) for record in records)
        note_dispatch_models([dispatch_model_name(r.model) for r in records])
        display().update_task_count(len(records))
        self.changed.set()

    def state(self, record: TaskRecord) -> TaskState:
        """Whether a record is waiting to start, has started, or has ended."""
        if record.ended:
            return "ended"
        return "running" if record in self.running else "queued"

    def start(self, record: TaskRecord) -> None:
        """Move a queued record to the running ones as its attempt starts."""
        self.queued.remove(record)
        self.running.add(record)
        self.changed.set()

    def end(self, record: TaskRecord) -> None:
        """End a record, keeping its latest log; it drops what only its attempts need.

        The one place a record ends: after its last attempt, when it is
        cancelled while waiting to start, and when the run ends before it
        does.
        """
        self.running.discard(record)
        record.ended = True
        if record.ended_event is not None:
            record.ended_event.set()
        record.configured = None
        record.logger = None
        record.setups = None
        self.changed.set()

    def cancel_waiting(self, record: TaskRecord) -> None:
        """End a queued record that will now never start (an operator cancelled it).

        It leaves the task display's count, as it will have no row there.
        """
        self.queued.remove(record)
        self.end(record)
        display().update_task_count(-1)

    async def wait_for_change(self) -> None:
        """Wait until :attr:`changed` rings (since the last wait returned)."""
        await self.changed.wait()

    def close(self) -> None:
        """Refuse further additions and end every record that has not ended.

        Called by the scheduling loop once nothing is queued, running or
        coming, and again as the run ends: a cancelled or failed run leaves
        records queued, which will now never start, and running ones, whose
        attempts it interrupted. Each keeps its latest attempt's log, if any.
        """
        self._closed = True
        for record in [*self.queued, *self.running]:
            self.end(record)
        self.queued = []

    def results(self) -> list[EvalLog]:
        """The final log of each task that has one, in :attr:`records` order."""
        return [
            record.log
            for record in self.records
            if record.ended and record.log is not None
        ]


class TaskHandle:
    """A task added to the running eval (see :func:`enqueue_task`).

    The handle and ``inspect ctl`` act on the same task: a cancel from either
    is seen by both, and ``inspect ctl`` reaches the task from other
    processes by :attr:`task_id`. Entering the handle with ``async with``
    cancels the task when the block exits.
    """

    def __init__(self, tasks: RunTasks, record: TaskRecord) -> None:
        self._tasks = tasks
        self._record = record

    @property
    def task_id(self) -> str:
        """The task's id (the same for all its attempts)."""
        return self._record.task_id

    @property
    def state(self) -> TaskState:
        """``"queued"`` (waiting to start), ``"running"`` (including between attempts) or ``"ended"``."""
        return self._tasks.state(self._record)

    def cancel(self) -> None:
        """Cancel the task, in any state, as ``inspect ctl task cancel`` does.

        A task that has not started ends without running (and without a
        log); a running task is aborted (its log records the cancel) and is
        not retried; a task between attempts keeps its last attempt's log.
        Cancelling an ended task does nothing.
        """
        from inspect_ai._control.cancel import cancel_task

        if self._record.ended:
            return
        result = cancel_task(self.task_id)
        if result is None or not result["ok"]:
            raise RuntimeError(
                f"Task '{self._record.task}' ({self.task_id}) could not be "
                f"cancelled: {result}"
            )

    async def wait(self) -> EvalLog:
        """Wait for the task to end; its final log.

        Raises:
            RuntimeError: If the task ended without a log: it was cancelled
                before it started, or the run ended first.
        """
        record = self._record
        if not record.ended:
            if record.ended_event is None:
                record.ended_event = anyio.Event()
            await record.ended_event.wait()
        if record.log is None:
            raise RuntimeError(
                f"Task '{record.task}' ({self.task_id}) ended without a log: it "
                "was cancelled before it started, or the run ended first."
            )
        return record.log

    async def __aenter__(self) -> "TaskHandle":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Cancel the task (if it has not ended)."""
        self.cancel()


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


async def enqueue_task(
    tasks: "Tasks", *, run_id: str | None = None
) -> list[TaskHandle]:
    """Add one or more tasks to the running eval.

    Returns a :class:`TaskHandle` per task added (one per task and model),
    in start order: its ``task_id``, its ``state``, ``cancel()`` and
    ``await wait()`` for its final log. Entering a handle with ``async with``
    cancels its task when the block exits::

        [worker] = await enqueue_task(worker_task())
        async with worker:
            ...

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files), resolved against the
    run's models and config. Each starts when a task slot is free, under the
    run's ``max_tasks`` limit (which ``inspect ctl config --max-tasks``
    changes live), after the tasks queued before it. It returns once the
    tasks are queued: it resolves each task's sandbox configs first, so
    an invalid config raises there and adds none of the tasks. A task whose
    sandboxes are still being set up does not hold back a later task that is
    ready. If an added task's sandbox setup fails, that task ends with an
    error log (its retries apply) and the run continues.

    A task that waits for a task it added needs a free slot for it:
    ``eval()`` defaults ``max_tasks`` to the number of models, so without a
    higher ``max_tasks`` the run hangs. In a :class:`~inspect_ai.TaskSource`
    run, tasks added while ``next_tasks()`` runs start only after it returns,
    behind the batch it returns, so ``next_tasks()`` must not wait for them.

    Call from the eval's event loop, not from another thread: from a solver,
    scorer or tool, a ``TaskSource`` callback, or a hook Inspect calls during
    a task (such as ``on_task_start`` or ``on_sample_end``). It raises in
    ``on_run_start`` and ``on_run_end``, which run outside the run.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.

    Returns:
        A handle per task added (one per task and model), in start order.

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
    return [TaskHandle(run_tasks, record) for record in await run_tasks.add(tasks)]
