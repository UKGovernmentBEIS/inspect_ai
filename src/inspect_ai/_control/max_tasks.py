"""Live mid-flight override for the task dispatcher's ``max_tasks`` limit.

The ``inspect ctl config --max-tasks`` retune surface (see
``design/ctl/max-tasks-retune.md``). ``max_tasks`` resolves to a plain int
(``parallel``) before a run starts and the dispatcher
(``TaskDispatcher`` in ``inspect_ai._eval.run``) is a select loop,
not a semaphore acquire — and dispatchers can be recreated within a run (an
eval-set in legacy ``retry_immediate=False`` mode re-invokes ``eval()`` per
retry pass). So rather than a resizable limiter owned by one dispatcher, this
is a **process-global override read at the point of use**, modeled on the
retry-knob layer in
:mod:`inspect_ai.model._generate_overrides`: every dispatcher's admission
check reads :func:`effective_max_tasks` each iteration, so a retune survives
dispatcher boundaries, and setting the override fires the dispatch wakers so
a waiting dispatcher re-evaluates immediately. Raising the limit starts
pending tasks at once; lowering never preempts — in-flight tasks run to
completion and new ones just don't start until ``in_flight`` drains below
the limit. Reset at the outermost run boundary via
``reset_run_registries()``, like the retry overrides.

The module also keeps a live-dispatcher registry: each running dispatcher
registers itself alongside its dispatch waker, so the config view can report
where dispatch actually stands, and the control channel can list, cancel and
stop retrying the tasks that have not started.

No lock: single-threaded by construction — the writer (the control-server
handler) runs as a task on the same event loop as the reading dispatchers,
and each accessor is a single atomic operation.
"""

from __future__ import annotations

from typing import Literal, NamedTuple, Protocol


class TaskDispatcherStats(NamedTuple):
    """A live task dispatcher's launch limit and queue counters."""

    launch: int
    """The launch-resolved ``parallel`` (max concurrent task × model units)."""

    in_flight: int
    """Tasks currently running (may exceed the limit after a lowering)."""

    pending: int
    """Tasks waiting to start: queued (including retry attempts), or added
    and not yet taken by the scheduling loop."""


WaitingFor = Literal[
    "added",
    "after_batch",
    "next_tasks",
    "paused",
    "sandbox resolution",
    "setup turn",
    "sandbox setup",
    "failed setup",
    "slot",
]
"""Why a task has not started.

- ``added``: added, and the scheduling loop has not taken it yet.
- ``after_batch``: added with ``start="after_batch"``; taken once no task runs.
- ``next_tasks``: added while ``TaskSource.next_tasks()`` runs; taken after it.
- ``paused``: held by a pause.
- ``sandbox resolution``: its sandbox configs are being resolved.
- ``setup turn``: its sandbox setup has not been requested yet (only the next
  ``max_tasks`` queued tasks set up ahead).
- ``sandbox setup``: its sandbox setup is running or waiting for another.
- ``failed setup``: its setup failed; it is about to start and end with that
  error.
- ``slot``: ready, waiting for a free task slot.
"""


class QueuedTask(NamedTuple):
    """A task of the run waiting to start (its first attempt, or a retry)."""

    task_id: str
    task: str
    model: str
    attempt: int
    """The attempt it waits to start (1 for a task that has never run)."""
    waiting_for: WaitingFor


class DispatcherHandle(Protocol):
    """A live run's scheduling loop, as the control channel sees it."""

    def stats(self) -> TaskDispatcherStats:
        """Its launch limit and queue counters."""
        ...

    def queued_tasks(self) -> list[QueuedTask]:
        """The tasks waiting to start, in start order."""
        ...

    def queued_task(self, task_id: str) -> QueuedTask | None:
        """The task ``task_id``, if it is waiting to start."""
        ...

    def cancel_queued(self, task_id: str) -> None:
        """End a task waiting to start, without running it (and without a retry)."""
        ...

    def abandon_retry(self, task_id: str) -> None:
        """Stop a task from being retried (its pending retry, or the next one)."""
        ...


_override: int | None = None

# The live task dispatchers, registered/removed by TaskDispatcher alongside
# its dispatch waker (so lifetime management is shared). At most one
# dispatcher runs at a time in practice; readers use the most recently
# registered.
_dispatchers: list[DispatcherHandle] = []


def set_max_tasks_override(value: int | None) -> None:
    """Set (or clear, with ``None``) the live ``max_tasks`` override.

    The override applies process-wide from the next dispatch decision —
    every live (and future) dispatcher in the run reads it in its admission
    check — and firing the dispatch wakers here makes a raise take effect
    immediately rather than at the next completion. An out-of-range value
    raises: the wire layers reject one first (``max_tasks 0`` would be a
    disguised pause — ``inspect ctl process pause`` is the real spelling —
    and values above :data:`MAX_GENERATE_CONFIG_OVERRIDE` are absurd), so
    like ``set_generate_config_override`` this guards programmatic callers
    on both sides: a sign or magnitude bug must not become a live override.
    """
    from inspect_ai.model._generate_overrides import MAX_GENERATE_CONFIG_OVERRIDE

    global _override
    if value is not None and (value < 1 or value > MAX_GENERATE_CONFIG_OVERRIDE):
        raise ValueError(
            f"max_tasks override must be between 1 and "
            f"{MAX_GENERATE_CONFIG_OVERRIDE} (got {value})"
        )
    _override = value
    from inspect_ai._control.pause import fire_dispatch_wakers

    fire_dispatch_wakers()


def max_tasks_override() -> int | None:
    """The live override, or ``None`` when none is set."""
    return _override


def effective_max_tasks(launch: int) -> int:
    """The dispatch limit in effect: the live override, else ``launch``.

    Read by the dispatcher on each admission-check iteration (the point of
    use), so a retune reaches dispatchers that are already running. An
    explicit ``is not None`` check — the floor makes 0 unreachable, but an
    ``or``-composed read would silently misread one.
    """
    return _override if _override is not None else launch


def register_task_dispatcher(dispatcher: DispatcherHandle) -> None:
    """Register a live dispatcher (the config and queued views' source)."""
    _dispatchers.append(dispatcher)


def remove_task_dispatcher(dispatcher: DispatcherHandle) -> None:
    """Unregister a dispatcher registered with :func:`register_task_dispatcher`."""
    try:
        _dispatchers.remove(dispatcher)
    except ValueError:
        pass


def task_dispatcher() -> DispatcherHandle | None:
    """The live dispatcher, or ``None`` when no dispatcher is live."""
    return _dispatchers[-1] if _dispatchers else None


def task_dispatcher_stats() -> TaskDispatcherStats | None:
    """The live dispatcher's stats, or ``None`` when no dispatcher is live.

    ``None`` covers the windows where a set still lands usefully in the
    override layer — a run still in startup (e.g. pulling sandbox images)
    before its dispatcher registers — which is why the knob stays adjustable
    without a handle.
    """
    return _dispatchers[-1].stats() if _dispatchers else None


def reset_max_tasks_override() -> None:
    """Clear the override (called at the outermost run boundary).

    The handle registry is cleared too as a safety net — dispatchers remove
    their own handles in a ``finally``, so it is normally already empty.
    """
    global _override
    _override = None
    _dispatchers.clear()
