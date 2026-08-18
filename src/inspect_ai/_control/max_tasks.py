"""Live mid-flight override for the task dispatcher's ``max_tasks`` limit.

The ``inspect ctl config --max-tasks`` retune surface (see
``design/ctl/max-tasks-retune.md``). ``max_tasks`` resolves to a plain int
(``parallel``) before a run starts and the dispatcher
(``run_task_retry_attempts`` in ``inspect_ai._eval.run``) is a select loop,
not a semaphore acquire — and dispatchers can be recreated within a run
(``enqueue_task``-driven batches, legacy eval-set retry passes). So rather
than a resizable limiter owned by
one dispatcher, this is a **process-global override read at the point of
use**, modeled on the retry-knob layer in
:mod:`inspect_ai.model._generate_overrides`: every dispatcher's admission
check reads :func:`effective_max_tasks` each iteration, so a retune survives
dispatcher boundaries, and setting the override fires the dispatch wakers so
a waiting dispatcher re-evaluates immediately. Raising the limit starts
pending tasks at once; lowering never preempts — in-flight tasks run to
completion and new ones just don't start until ``in_flight`` drains below
the limit. Reset at the outermost run boundary via
``reset_run_registries()``, like the retry overrides.

The module also keeps a live-dispatcher handle registry: each running
dispatcher registers a stats callback (its launch ``parallel``, current
in-flight count, and pending-queue length) alongside its dispatch waker, so
the config view can report where dispatch actually stands.

No lock: single-threaded by construction — the writer (the control-server
handler) runs as a task on the same event loop as the reading dispatchers,
and each accessor is a single atomic operation.
"""

from __future__ import annotations

from typing import Callable, NamedTuple


class TaskDispatcherStats(NamedTuple):
    """A live task dispatcher's launch limit and queue counters."""

    launch: int
    """The launch-resolved ``parallel`` (max concurrent task × model units)."""

    in_flight: int
    """Tasks currently running (may exceed the limit after a lowering)."""

    pending: int
    """Tasks queued and not yet started (including queued retry attempts)."""


_override: int | None = None

# Stats callbacks of the live task dispatchers, registered/removed by
# run_task_retry_attempts alongside its dispatch waker (so lifetime
# management is shared). At most one dispatcher runs at a time in practice;
# the view reads the most recently registered.
_dispatchers: list[Callable[[], TaskDispatcherStats]] = []


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


def register_task_dispatcher(stats: Callable[[], TaskDispatcherStats]) -> None:
    """Register a live dispatcher's stats callback (the config view's source)."""
    _dispatchers.append(stats)


def remove_task_dispatcher(stats: Callable[[], TaskDispatcherStats]) -> None:
    """Unregister a callback registered with :func:`register_task_dispatcher`."""
    try:
        _dispatchers.remove(stats)
    except ValueError:
        pass


def task_dispatcher_stats() -> TaskDispatcherStats | None:
    """The live dispatcher's stats, or ``None`` when no dispatcher is live.

    ``None`` covers the windows where a set still lands usefully in the
    override layer — a batch still in startup (e.g. pulling sandbox images)
    before its dispatcher registers, or a run blocked between
    ``enqueue_task``-driven batches — which is why the knob stays adjustable
    without a handle.
    """
    return _dispatchers[-1]() if _dispatchers else None


def reset_max_tasks_override() -> None:
    """Clear the override (called at the outermost run boundary).

    The handle registry is cleared too as a safety net — dispatchers remove
    their own handles in a ``finally``, so it is normally already empty.
    """
    global _override
    _override = None
    _dispatchers.clear()
