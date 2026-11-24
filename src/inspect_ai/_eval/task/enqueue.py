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

from .sample_source import HandleChannel

if TYPE_CHECKING:
    from inspect_ai._display.core.display import TaskCancel
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.run import TaskRunOptions
    from inspect_ai._eval.task.task import Task
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai.dataset import Sample
    from inspect_ai.log import EvalLog, EvalSample
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
    channel: HandleChannel | None = None
    """The channel of a task fed through its handle."""

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
        self._held_cancels: set[str] = set()
        self._token = anyio.lowlevel.current_token()

    def open(self, configure: ConfigureTasksFn, *, task_retry_attempts: int) -> None:
        """Start accepting tasks, configured with ``configure``."""
        self._configure = configure
        self.task_retry_attempts = task_retry_attempts

    def enqueue(
        self, tasks: "Tasks", *, creator: "TaskAttempt | None" = None
    ) -> "list[ResolvedTask]":
        """Resolve ``tasks`` against the run and add them.

        Tasks enqueued before the queue opens (from a run-start hook) are
        resolved now and held until :meth:`add_held`. Returns the resolved
        tasks, in resolution order.

        Args:
            tasks: The tasks to add.
            creator: The running attempt adding them, if any. Only an attempt
                can add a task fed through its handle.
        """
        self._check_not_closed()
        resolved = self._resolve(tasks)
        if self._configure is None:
            _check_fed(resolved, creator)
            self._held.append(resolved)
        else:
            self.add(resolved, creator=creator)
        return resolved

    def add_held(self) -> list[TaskRecord]:
        """Add the tasks enqueued before the queue opened, after the seed.

        They are counted with the seed when the task screen opens. A
        configuration error raises from the run, since the call that enqueued
        them has returned. A handle's ``cancel()`` made while they were held
        is applied now.
        """
        held, self._held = self._held, []
        records = [record for batch in held for record in self.add(batch, seed=True)]
        cancels, self._held_cancels = self._held_cancels, set()
        for record in records:
            if record.task_id in cancels:
                self.cancel(record)
        return records

    def resolve(self, tasks: "Tasks") -> "list[ResolvedTask]":
        """Resolve ``tasks`` against the run's models and config."""
        return self._resolve(tasks)

    def add(
        self,
        resolved: "list[ResolvedTask]",
        *,
        seed: bool = False,
        creator: "TaskAttempt | None" = None,
    ) -> list[TaskRecord]:
        """Configure and add a batch of resolved tasks.

        Every check runs for the whole batch before anything is added, so an
        error raises to the caller and adds nothing. The batch is dispatched
        sequence-major, so at ``max_tasks == 1`` all of one task definition's
        models run before the next definition's. Its logs are returned in the
        order it was given, or in dispatch order with ``results_by_sequence``.

        A task fed through its handle gets a fresh channel on its record's
        configured task, recorded in ``creator``'s channels, and is never
        retried.

        Args:
            resolved: The tasks to add.
            seed: The run's seed tasks (and those held from before it
                opened), which the task screen counts when it opens.
            creator: The running attempt adding them, if any. Only an attempt
                can add a task fed through its handle.
        """
        self._check_open()
        assert self._configure is not None
        _check_fed(resolved, creator)

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
            fed = is_fed(task.task)
            record = TaskRecord(
                task_id=task.id,
                task=task.task.name,
                model=str(task.model),
                index=-1,
                options=task_options,
                retries_remaining=0 if fed else self.task_retry_attempts,
            )
            task_options.record = record
            if fed:
                assert creator is not None
                channel = HandleChannel()
                channel.bind(self, record)
                task_options.task.sample_source = channel
                record.channel = channel
                creator.channels.append(channel)
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

        A task fed through its handle that is still queued has never started:
        it ends at once with no log. One in an attempt is cancelled as above
        and its channel closed here too, so no more samples are accepted
        whether or not the cancel is applied.
        """
        if record.phase == "ended":
            return
        if record.channel is not None and record.phase == "queued":
            self.end(record, None)
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
        if record.channel is not None:
            record.channel.close()

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
        if record.channel is not None:
            record.channel.end(lambda: TaskEndedError(record.task, log))
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


def _require_run_loop(queue: RunQueue, call: str = "enqueue_task()") -> None:
    """Refuse a call made off the run's event loop."""
    try:
        token = anyio.lowlevel.current_token()
    except anyio.NoEventLoopError:
        token = None
    if token != queue._token:
        if call != "enqueue_task()":
            raise RuntimeError(
                f"{call} must be called on the running eval's event loop. From a "
                "thread started with anyio.to_thread.run_sync(), call synchronous "
                "methods through anyio.from_thread.run_sync() and async methods "
                "through anyio.from_thread.run()."
            )
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


@dataclass(eq=False)
class TaskAttempt:
    """One attempt of a record, as the context its code runs in sees it.

    Shared by reference with every context copied from the attempt, so a
    background coroutine that outlives its attempt sees it end.
    """

    record: TaskRecord
    model: "Model"
    ended: bool = False
    """Set where the attempt publishes a retry or ends its record."""
    channels: list[HandleChannel] = field(default_factory=list)
    """The channels of the tasks fed through a handle that it added."""

    def end(self) -> None:
        """Mark the attempt ended and close the channels of the tasks it added."""
        self.ended = True
        channels, self.channels = self.channels, []
        for channel in channels:
            channel.close()


# The task attempt running in this context: set by the dispatcher around each
# attempt and cleared around TaskSource callbacks, so `creator_attempt()` is
# `None` outside a running task. Tasks added inside an attempt resolve once,
# under its model, and only an attempt can add a task fed through its handle.
# `active_model()` can't stand in for it: outside an attempt it still holds
# the last run model that up-front task resolution activated.
_attempt: ContextVar[TaskAttempt | None] = ContextVar("task_attempt", default=None)


@contextmanager
def attempt_scope(attempt: TaskAttempt | None) -> Iterator[None]:
    """Run the scope inside ``attempt``, or (``None``) as outside any attempt.

    Clearing it (``None``) for a callback leaves the enclosing attempt running.
    """
    token = _attempt.set(attempt)
    try:
        yield
    finally:
        _attempt.reset(token)


def creator_attempt() -> TaskAttempt | None:
    """The task attempt running in this context, if it has not ended."""
    attempt = _attempt.get()
    return attempt if attempt is not None and not attempt.ended else None


def creator_model() -> "Model | None":
    """The model of the task attempt running in this context, if it has not ended."""
    attempt = creator_attempt()
    return attempt.model if attempt is not None else None


def is_fed(task: "Task") -> bool:
    """Whether ``task`` takes its samples through its handle."""
    return isinstance(task.sample_source, HandleChannel)


def _check_fed(resolved: "list[ResolvedTask]", creator: TaskAttempt | None) -> None:
    """Refuse a task fed through its handle that cannot be added here."""
    for task in resolved:
        if not is_fed(task.task):
            continue
        if creator is None:
            raise RuntimeError(
                f"Task '{task.task.name}' takes its samples through its handle "
                "(samples_from_handle()), so it can only be added with "
                "enqueue_task() from code running inside a task, such as a "
                "solver, scorer or tool, and not from a TaskSource callback."
            )
        if task.task.epochs is not None and task.task.epochs > 1:
            raise ValueError(
                f"Task '{task.task.name}': a task fed through its handle runs "
                "each sample once; send a sample again to repeat it."
            )


class TaskEndedError(RuntimeError):
    """The task ended before a sample sent through its handle ran."""

    def __init__(self, task: str, log: "EvalLog | None") -> None:
        super().__init__(
            f"Task '{task}' ended before the sample sent through its handle ran."
        )
        self.log = log
        """The task's final log, or ``None`` if it ended with none."""


class SampleAbandonedError(RuntimeError):
    """A sample sent through a task's handle was cancelled before it was logged."""

    def __init__(self, sample: "Sample") -> None:
        super().__init__(
            f"Sample '{sample.id}' sent through the task's handle was cancelled "
            "before it was logged."
        )
        self.sample = sample
        """The sample as the task ran it, with the id the handle assigned."""


class TaskHandle:
    """A task added to the running eval with :func:`enqueue_task`.

    Every handle can cancel its task. A task whose dataset is
    :func:`~inspect_ai.samples_from_handle` takes its samples through
    its handle: :meth:`enqueue_sample` sends each one and returns its logged
    run, and :meth:`result` waits for the task's final log. Closing the
    handle never stops samples already sent; :meth:`cancel` does.

    Every method must be called on the running eval's event loop.
    """

    def __init__(self, queue: RunQueue, task: "ResolvedTask") -> None:
        self._queue = queue
        self.task_id: str = task.id
        """The task's id."""
        self.task: str = task.task.name
        """The task's name."""
        self.model: str = str(task.model)
        """The task's model."""
        self._found: TaskRecord | None = None

    def _record(self) -> TaskRecord | None:
        # a task added from an on_run_start hook has no record until the run
        # opens
        if self._found is None:
            self._found = self._queue.find(self.task_id)
        return self._found

    def _channel(self, call: str) -> HandleChannel:
        _require_run_loop(self._queue, f"TaskHandle.{call}")
        record = self._record()
        if record is None or record.channel is None:
            if call == "result()":
                raise RuntimeError(
                    "result() waits only on a task fed through its handle "
                    "(samples_from_handle()): wait on a task fed through its "
                    "handle, or read its log after the run."
                )
            raise RuntimeError(
                f"{call} needs a task fed through its handle "
                f"(samples_from_handle()); task '{self.task}' has its own dataset."
            )
        return record.channel

    async def enqueue_sample(self, sample: "Sample") -> "EvalSample":
        """Run ``sample`` in the task (one epoch) and return its logged run.

        The task runs a copy of ``sample`` under an id the handle assigns
        (``send-<token>-<n>``), so ``sample`` must have no ``id``. An errored
        or operator-cancelled sample is returned with its ``error`` set. If
        the caller is cancelled while it waits, the sample still runs and its
        result is dropped.

        Args:
            sample: The sample to run.

        Returns:
            The sample's logged run.

        Raises:
            RuntimeError: If the task is not fed through this handle, or the
                handle is closed.
            ValueError: If ``sample`` has an ``id``.
            TaskEndedError: If the task has ended, or ends before the sample
                runs.
            SampleAbandonedError: If the sample was cancelled before it was
                logged.
        """
        channel = self._channel("enqueue_sample()")
        if sample.id is not None:
            raise ValueError(
                "TaskHandle.enqueue_sample() assigns each sample's id; send a "
                f"sample with no id (got '{sample.id}')."
            )
        record = channel.record
        if record.phase == "ended":
            raise TaskEndedError(record.task, record.log)
        if channel.closed:
            raise RuntimeError(
                "The handle is closed, by its holder or an operator drain or "
                "cancel: send no more samples."
            )
        request = channel.send(sample)
        return await request.future.wait()

    async def result(self) -> "EvalLog | None":
        """Close the handle, then wait until the task ends.

        Returns:
            The task's final log, or ``None`` if it ended with none (it was
            closed before any sample was sent, or cancelled before it
            started).

        Raises:
            RuntimeError: If the task is not fed through this handle.
        """
        channel = self._channel("result()")
        channel.close()
        record = channel.record
        await record.ended.wait()
        return record.log

    def close(self) -> None:
        """Send no more samples; the task ends once the samples sent have run.

        Does nothing for a task not fed through its handle, or a second time.
        """
        _require_run_loop(self._queue, "TaskHandle.close()")
        record = self._record()
        if record is not None and record.channel is not None:
            record.channel.close()

    def cancel(self) -> None:
        """Abort the task, like ``inspect ctl task cancel``.

        A task fed through its handle that has not started ends at once with
        no log. Does nothing once the task has ended.
        """
        _require_run_loop(self._queue, "TaskHandle.cancel()")
        record = self._record()
        if record is None:
            # added from an on_run_start hook, before the run opened
            self._queue._held_cancels.add(self.task_id)
        else:
            self._queue.cancel(record)

    async def __aenter__(self) -> "TaskHandle":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.close()


def bind_run_queue(queue: RunQueue) -> Token[RunQueue | None]:
    """Install ``queue`` as the active one; returns a token to restore with."""
    return _run_queue.set(queue)


def get_run_queue() -> RunQueue | None:
    return _run_queue.get()


def unbind_run_queue(token: Token[RunQueue | None]) -> None:
    """Restore the queue in scope before the matching ``bind_run_queue`` call."""
    _run_queue.reset(token)


def enqueue_task(tasks: "Tasks", *, run_id: str | None = None) -> list[TaskHandle]:
    """Add one or more tasks to the running eval.

    The tasks run in this process under the current run's ``run_id`` (a fresh
    ``eval_id``/``task_id`` each, their own log files). An added task starts as
    soon as a ``max_tasks`` slot is free. A task whose dataset is
    :func:`~inspect_ai.samples_from_handle` takes its samples through its
    handle instead.

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

    Returns:
        One handle for each task added, in resolution order.

    Raises:
        RuntimeError: If no eval is currently running in this process,
            ``run_id`` doesn't match the active run, the run has stopped
            starting tasks, the call is made off the run's event loop, a
            task is a placeholder that eval-set selection pruning left in
            place of a task it did not build, or a task fed through its
            handle is added from outside a running task.
        ValueError: If the tasks can't be resolved, a task id is already
            in the run (from the run for a call from an ``on_run_start``
            hook), or a task fed through its handle sets ``epochs`` above 1
            or is passed as a ``ResolvedTask`` or ``PreviousTask``.
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
    resolved = queue.enqueue(tasks, creator=creator_attempt())
    return [TaskHandle(queue, task) for task in resolved]
