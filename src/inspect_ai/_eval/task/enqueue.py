"""Add tasks to a running eval.

Every eval run has one :class:`RunQueue`. The seed tasks, tasks added with
:func:`enqueue_task`, tasks a ``TaskSource`` returns and task retries all go
through it, and the run's dispatcher starts each one as soon as a
``max_tasks`` slot is free (see ``design/task-dispatch.md``).

The queue is bound in a ``ContextVar`` for the run, so it is scoped to the
run's async context and propagates to its child tasks; :func:`enqueue_task`
validates an optional ``run_id`` against it so a stray or late caller can't add
to the wrong run.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator, Literal

import anyio
import anyio.lowlevel

from inspect_ai._util._async import Wake

if TYPE_CHECKING:
    from inspect_ai._display.core.display import TaskCancel
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import TaskRunOptions
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.log import EvalLog
    from inspect_ai.model import Model

logger = logging.getLogger(__name__)

# Resolve submitted tasks to concrete ``ResolvedTask``s against the run's
# models / config. Built by the eval runner (which holds that context). Raises
# on tasks it can't resolve.
ResolveTasksFn = Callable[["Tasks"], "list[ResolvedTask]"]

# Configure a batch of resolved tasks for the run, without awaiting: apply the
# eval-level overrides, run the configuration checks, resolve each task's
# sample selection against the given task names and construct its logger.
# Raises on a configuration error. Built by ``eval_run``.
ConfigureTasksFn = Callable[["list[ResolvedTask]", "list[str]"], "list[TaskRunOptions]"]

TaskPhase = Literal["queued", "attempt", "ended"]
"""Where a task is: waiting for its next attempt, in an attempt, or ended."""

TaskReached = Literal["added", "row_opened", "registered"]
"""How far a task's attempts have got, in order (never moves back)."""

_REACHED_ORDER: dict[TaskReached, int] = {
    "added": 0,
    "row_opened": 1,
    "registered": 2,
}


@dataclass(eq=False)
class TaskRecord:
    """One task × model in a run, from when it is added until it ends."""

    task_id: str
    task: str
    """The task's name, kept after the record ends."""
    model: str
    index: int
    """Result order: the seed first, then each batch in the order it was added."""
    options: "TaskRunOptions | None"
    """The configured task, released when the record ends."""
    retries_remaining: int
    phase: TaskPhase = "queued"
    reached: TaskReached = "added"
    abort_requested: bool = False
    """Cancelled while queued: the dispatcher starts an attempt that aborts at once."""
    attempt_cancel: "TaskCancel | None" = None
    """The current attempt's cancel handle, held while the record is in an attempt."""
    attempt_scope: anyio.CancelScope | None = None
    """The scope the current attempt's abort or retry request cancels."""
    log: "EvalLog | None" = None
    """The last attempt's log; the final log once the record has ended."""
    ended: anyio.Event = field(default_factory=anyio.Event)

    def on_row_opened(self) -> None:
        """An attempt opened the task's display row."""
        self._reach("row_opened")

    def on_registered(self) -> None:
        """An attempt registered the task with the control channel."""
        self._reach("registered")

    def _reach(self, reached: TaskReached) -> None:
        if _REACHED_ORDER[reached] > _REACHED_ORDER[self.reached]:
            self.reached = reached


class RunQueue:
    """The run's tasks, from when each is added until it ends.

    Only the run's event loop changes the queue, in synchronous steps, so it
    needs no lock. The dispatcher (``dispatch_tasks``) takes records from
    :attr:`pending` and runs their attempts.
    """

    def __init__(
        self,
        run_id: str,
        resolve: ResolveTasksFn,
        task_names: list[str],
        *,
        results_by_sequence: bool = False,
    ) -> None:
        """Create the run's queue.

        Args:
            run_id: The run's id.
            resolve: Resolves tasks against the run's models and config.
            task_names: The task names the run starts with.
            results_by_sequence: Return each batch's logs in dispatch
                (sequence-major) order rather than the order given, as a run
                at ``max_tasks == 1`` does.
        """
        self.run_id = run_id
        self._results_by_sequence = results_by_sequence
        self.closed = False
        """No more additions or retries: dispatch has ended."""
        self.task_names = list(task_names)
        """Every task name of the run, for resolving `task:id` sample selectors."""
        self.wake = Wake()
        """Rung by every phase change and addition."""
        self.screen_open = False
        """Set while the dispatcher is inside the task screen."""
        self.pending: list[TaskRecord] = []
        """Records in ``queued``, in start order."""
        self.records: list[TaskRecord] = []
        """Every record of the run, ended or not."""
        self._resolve = resolve
        self._configure: ConfigureTasksFn | None = None
        self.task_retry_attempts = 0
        """The run's retry budget for each task."""
        self._ids: set[str] = set()
        self._held: list[list[ResolvedTask]] = []
        self._token = anyio.lowlevel.current_token()

    def open(self, configure: ConfigureTasksFn, *, task_retry_attempts: int) -> None:
        """Start accepting tasks, configured with ``configure``."""
        self._configure = configure
        self.task_retry_attempts = task_retry_attempts

    def enqueue(self, tasks: "Tasks") -> None:
        """Resolve ``tasks`` against the run and add them.

        Tasks enqueued before the queue opens (from a run-start hook) are
        resolved now and held until :meth:`add_held`.
        """
        self._check_not_closed()
        resolved = self._resolve(tasks)
        if self._configure is None:
            self._held.append(resolved)
        else:
            self.add(resolved)

    def add_held(self) -> list[TaskRecord]:
        """Add the tasks enqueued before the queue opened, after the seed.

        They are counted with the seed when the task screen opens. A
        configuration error raises from the run, since the call that enqueued
        them has returned.
        """
        held, self._held = self._held, []
        return [record for batch in held for record in self.add(batch, seed=True)]

    def resolve(self, tasks: "Tasks") -> "list[ResolvedTask]":
        """Resolve ``tasks`` against the run's models and config."""
        return self._resolve(tasks)

    def add(
        self, resolved: "list[ResolvedTask]", *, seed: bool = False
    ) -> list[TaskRecord]:
        """Configure and add a batch of resolved tasks.

        Every check runs for the whole batch before anything is added, so an
        error raises to the caller and adds nothing. The batch is dispatched
        sequence-major, so at ``max_tasks == 1`` all of one task definition's
        models run before the next definition's. Its logs are returned in the
        order it was given, or in dispatch order with ``results_by_sequence``.

        Args:
            resolved: The tasks to add.
            seed: The run's seed tasks (and those held from before it
                opened), which the task screen counts when it opens.
        """
        self._check_open()
        assert self._configure is not None

        batch_ids: set[str] = set()
        for task in resolved:
            if task.id in self._ids or task.id in batch_ids:
                raise ValueError(
                    f"task id '{task.id}' (task '{task.task.name}') is already in "
                    "this run: a ResolvedTask or PreviousTask keeps its id, so it "
                    "can be added once, in a run with one model; pass the Task to "
                    "run it once per model"
                )
            batch_ids.add(task.id)

        names = self.task_names + [
            name
            for name in dict.fromkeys(task.task.name for task in resolved)
            if name not in self.task_names
        ]
        ordered = sorted(resolved, key=lambda task: task.sequence)
        options = self._configure(ordered, names)

        # commit (no checks below)
        self.task_names = names
        records: list[TaskRecord] = []
        for task, task_options in zip(ordered, options):
            record = TaskRecord(
                task_id=task.id,
                task=task.task.name,
                model=str(task.model),
                index=-1,
                options=task_options,
                retries_remaining=self.task_retry_attempts,
            )
            task_options.record = record
            self._ids.add(task.id)
            self.pending.append(record)
            records.append(record)
        by_id = {record.task_id: record for record in records}
        for task in ordered if self._results_by_sequence else resolved:
            record = by_id[task.id]
            record.index = len(self.records)
            self.records.append(record)

        from inspect_ai._control.pause import dispatch_model_name, note_dispatch_models

        note_dispatch_models([dispatch_model_name(task.model) for task in ordered])
        if not seed and records:
            from inspect_ai._display import display

            display().update_task_count(len(records))
        self.wake.set()
        return records

    def find(self, task_id: str) -> TaskRecord | None:
        """The run's record for ``task_id``, if it has one."""
        return next((r for r in self.records if r.task_id == task_id), None)

    def cancel(self, record: TaskRecord) -> None:
        """Cancel a record: abort it, or abandon its pending retry.

        A record whose attempt has registered with the control channel is
        cancelled as ``inspect ctl task cancel`` cancels it. One still queued
        that never registered gets an attempt that aborts before it starts,
        on the dispatcher's next pass; one in an attempt that has not
        registered is aborted through that attempt's cancel handle.
        """
        if record.phase == "ended":
            return
        if record.reached == "registered":
            from inspect_ai._control.cancel import cancel_task

            cancel_task(record.task_id)
        elif record.phase == "queued":
            record.abort_requested = True
            self.wake.set()
        else:
            assert record.attempt_cancel is not None
            record.attempt_cancel.request("abort")

    def requeue(self, record: TaskRecord) -> None:
        """Put a record whose attempt failed back at the end of the queue."""
        record.phase = "queued"
        record.attempt_cancel = None
        record.attempt_scope = None
        self.pending.append(record)
        self.wake.set()

    def end(self, record: TaskRecord, log: "EvalLog | None") -> None:
        """End a record with ``log`` (``None`` if it has none)."""
        if record.phase == "ended":
            return
        record.log = log
        record.phase = "ended"
        record.attempt_cancel = None
        record.attempt_scope = None
        if record in self.pending:
            self.pending.remove(record)
        # the displays count completed tasks from the rows attempts open
        if record.reached == "added" and self.screen_open:
            from inspect_ai._display import display

            display().update_task_count(-1)
        record.options = None
        record.ended.set()
        self.wake.set()

    def close(self) -> None:
        """Refuse every later addition and retry."""
        self.closed = True

    def end_unstarted(self) -> None:
        """End every queued record with its stored log."""
        for record in list(self.pending):
            self.end(record, record.log)

    def end_all(self) -> None:
        """End every record not yet ended with its stored log."""
        for record in self.records:
            self.end(record, record.log)

    def logs(self) -> "list[EvalLog]":
        """The log of each record that has one, in result order."""
        return [record.log for record in self.records if record.log is not None]

    def _check_not_closed(self) -> None:
        _require_run_loop(self)
        if self.closed:
            raise RuntimeError(
                "enqueue_task() was called after the run stopped starting tasks."
            )

    def _check_open(self) -> None:
        self._check_not_closed()
        if self._configure is None:
            raise RuntimeError(
                "enqueue_task() was called before the run started its tasks."
            )


def _require_run_loop(queue: RunQueue) -> None:
    """Refuse a call made off the run's event loop."""
    try:
        token = anyio.lowlevel.current_token()
    except anyio.NoEventLoopError:
        token = None
    if token != queue._token:
        raise RuntimeError(
            "enqueue_task() must be called on the running eval's event loop. From "
            "a thread started with anyio.to_thread.run_sync(), call "
            "anyio.from_thread.run_sync(lambda: enqueue_task(...)). From any "
            "other thread, capture token = anyio.lowlevel.current_token() and "
            "context = contextvars.copy_context() in the running task and call "
            "anyio.from_thread.run_sync(context.run, enqueue_task, tasks, "
            "token=token)."
        )


# The active run's queue, scoped to the run's async context.
_run_queue: ContextVar[RunQueue | None] = ContextVar("run_queue", default=None)


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


def bind_run_queue(queue: RunQueue) -> Token[RunQueue | None]:
    """Install ``queue`` as the active one; returns a token to restore with."""
    return _run_queue.set(queue)


def get_run_queue() -> RunQueue | None:
    return _run_queue.get()


def unbind_run_queue(token: Token[RunQueue | None]) -> None:
    """Restore the queue in scope before the matching ``bind_run_queue`` call."""
    _run_queue.reset(token)


def enqueue_task(tasks: "Tasks", *, run_id: str | None = None) -> None:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files). An added task starts as
    soon as a ``max_tasks`` slot is free.

    Called from inside a running task (a solver, scorer, tool or other code
    the task runs), the tasks are added once, under that task's model.
    Called anywhere else, including from a ``TaskSource`` callback, they are
    added once per model of the run. A task that sets its own ``model`` keeps
    it. Model roles and generate config come from the run.

    Sample selectors that name a task (``task:id``) resolve when the task is
    added, against the tasks added so far, so tasks whose selectors name each
    other must be added in one call.

    Called from an ``on_run_start`` hook, the tasks are resolved at the call
    and start after the run's own tasks. Their configuration, sample
    selection and task id checks run after the hooks return; a failing check
    ends the run before any task starts.

    Call it on the running eval's event loop. From a thread started with
    ``anyio.to_thread.run_sync()``, use
    ``anyio.from_thread.run_sync(lambda: enqueue_task(...))``. From any other
    thread, capture ``token = anyio.lowlevel.current_token()`` and
    ``context = contextvars.copy_context()`` in the running task and call
    ``anyio.from_thread.run_sync(context.run, enqueue_task, tasks,
    token=token)``.

    Args:
        tasks: A ``Task`` (or list of tasks) to add to the running eval.
        run_id: Optionally, the ``run_id`` the caller believes is running; if
            given it must match the active run, else the call is rejected.

    Raises:
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, the run has stopped
            starting tasks, the call is made off the run's event loop, or a
            task is a placeholder that eval-set selection pruning left in
            place of a task it did not build.
        ValueError: If the tasks can't be resolved, or a task id is already
            in the run (from the run for a call from an ``on_run_start``
            hook).
        PrerequisiteError: If a task's configuration or sample selection is
            invalid (from the run for a call from an ``on_run_start`` hook).
    """
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
    queue.enqueue(tasks)
