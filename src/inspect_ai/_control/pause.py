"""Pause / resume directives for the control channel.

Implements the quiesce semantics of ``design/ctl/pause-resume.md``: **pause**
stops a run from *starting* work — no new samples leave the queue, no task
retry attempts start, no eval-set tasks dispatch — while everything already
in flight completes normally (solving, scoring, log writes) under its
original limits. **resume** re-opens the gates in O(1). Both are
non-destructive, idempotent, last-write-wins, and dry-runnable, per the
phase-3 directive conventions.

Two independent latches, both checked at every dispatch point:

- **Task gates** (:func:`pause_task` / :func:`resume_task`) live in a
  task-id-keyed registry parallel to the sample-semaphore registry in
  ``inspect_ai.util._concurrency`` and reset at the same run boundary, so a
  pause survives in-run retry attempts of the same task.
- **The process latch** (:func:`pause_process` / :func:`resume_process`) is
  one module-level gate — the eval-set spelling ("pause the whole run") —
  reset at the outermost run boundary like the keep-alive intent.

``process resume`` deliberately does not clear task-level pauses (nor vice
versa): resuming the run after an incident must not silently un-pause a task
an operator paused for its own reasons.

The dispatch hooks all run on the eval's single event loop (the control
server is embedded), so gate flips are plain synchronous state changes — no
locks. Cancel escalates over pause: an abort/retry cancel tears down the
task scope (cancelling gate waiters with it), and a graceful score/error
resolution wakes gate waiters via :func:`wake_pause_waiters` so held samples
proceed to the queue-exit abandon check rather than staying parked.

Pause state is in-memory only — durability comes from quiesce (paused with
zero dispatched samples — in flight *or* still initializing — reported by
``GET /tasks``) plus the auto-flush in
:func:`flush_quiesced_tasks`, after which killing the process loses nothing
that re-invoking ``eval-set`` on the same log dir can't recover.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Literal

import anyio

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState

logger = getLogger(__name__)


PauseScope = Literal["task", "process", "both"]
"""Which latch(es) hold a paused task (the ``paused`` field of ``GET /tasks``)."""


class PauseGate:
    """A re-armable pause latch whose waiters can be woken to re-check.

    ``anyio.Event`` can't re-arm and pause/resume is last-write-wins, so the
    gate keeps a plain ``paused`` flag plus a replaceable change event
    (precedent: the keep-alive ``_park_cond`` in ``_control/server.py``).
    The event is created lazily on first wait — ``anyio.Event()`` needs a
    running async context, and gates are created/reset at module scope and
    run boundaries where there may be none.

    All access happens on the eval's event loop: the flag check and the
    ``wait()`` call in :meth:`wait_open` have no await point between them,
    so a flip can't slip between predicate and park.
    """

    def __init__(self) -> None:
        self._paused = False
        self._changed: anyio.Event | None = None

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> bool:
        """Close the gate. Returns whether the state changed."""
        if self._paused:
            return False
        self._paused = True
        return True

    def resume(self) -> bool:
        """Open the gate, waking waiters. Returns whether the state changed."""
        if not self._paused:
            return False
        self._paused = False
        self.wake()
        return True

    def wake(self) -> None:
        """Wake waiters so they re-check their predicate.

        Used both by :meth:`resume` (the gate opened) and by external state
        changes a waiter's ``escape`` predicate observes (a task cancel being
        stamped) — the gate itself may still be closed.
        """
        if self._changed is not None:
            self._changed.set()
            self._changed = None

    async def wait_open(self, escape: Callable[[], bool] | None = None) -> None:
        """Park while the gate is closed (or until ``escape`` returns True).

        ``escape`` lets a terminal transition pass a closed gate — the gate
        holds *starts*, not teardown (a graceful task cancel must reach the
        queue-exit abandon check of samples parked here).
        """
        while self._paused and not (escape is not None and escape()):
            if self._changed is None:
                self._changed = anyio.Event()
            await self._changed.wait()


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

# Task pause gates, keyed by task_id (stable across retry attempts, like the
# sample-semaphore registry in inspect_ai.util._concurrency and reset at the
# same run boundary) — so a pause survives an in-run task retry, matching how
# a `ctl config --max-samples` retune does. Created lazily by whichever side
# (directive or dispatch hook) touches a task first.
_task_gates: dict[str, PauseGate] = {}

# The process latch — one gate every dispatch point in the process checks
# (the "pause the eval-set" spelling). Reset at the outermost run boundary
# like the keep-alive intent.
_process_gate = PauseGate()

# Wake callbacks of the task dispatchers (`run_task_retry_attempts`
# registers its dispatch-loop wake here) so a resume re-evaluates task
# dispatch without polling.
_dispatch_wakers: list[Callable[[], None]] = []

# Dispatched samples per task, maintained by PauseGatedSemaphore at the true
# dispatch boundary (gate exit through semaphore release). Counts derived
# from ``active_samples`` have a hole: a sample past the gate registers there
# only after real await points (base64 content materialization, sandbox
# connections), so a pause landing in that window would read quiesced — and
# auto-flush — then flip back when the sample registers, the exact
# non-monotonicity ``design/ctl/pause-resume.md`` rules out. Reset with the task
# gates (samples never span an ``eval()`` call).
_dispatch_counts: dict[str, int] = {}


def _task_gate(task_id: str) -> PauseGate:
    gate = _task_gates.get(task_id)
    if gate is None:
        gate = PauseGate()
        _task_gates[task_id] = gate
    return gate


def task_pause_scope(task_id: str) -> PauseScope | None:
    """Which latch(es) hold the task — ``None`` when it is dispatchable."""
    gate = _task_gates.get(task_id)
    task_paused = gate is not None and gate.paused
    if task_paused and _process_gate.paused:
        return "both"
    if task_paused:
        return "task"
    if _process_gate.paused:
        return "process"
    return None


def task_dispatch_paused(task_id: str) -> bool:
    """Whether starting new work for ``task_id`` is held by a pause latch."""
    return task_pause_scope(task_id) is not None


def process_paused() -> bool:
    """Whether the process-level pause latch is closed."""
    return _process_gate.paused


def task_dispatched_count(task_id: str) -> int:
    """Samples of ``task_id`` past the pause gate and not yet finished.

    Counted at the gate itself (:class:`PauseGatedSemaphore` increments on
    entry, decrements on exit) rather than derived from ``active_samples``,
    so a sample is dispatched from the instant it passes the gate — through
    materialization and sandbox creation (minutes, with ``started=None``) —
    until its semaphore slot is released. A gate-held sample never enters,
    so under a pause this count is non-increasing by construction, keeping
    ``quiesced`` (paused and zero dispatched) monotonic — the "safe to kill"
    signal must not flip true→false while an operator acts on it.
    """
    return _dispatch_counts.get(task_id, 0)


def _dispatch_entered(task_id: str) -> None:
    _dispatch_counts[task_id] = _dispatch_counts.get(task_id, 0) + 1


def _dispatch_exited(task_id: str) -> None:
    _dispatch_counts[task_id] = max(0, _dispatch_counts.get(task_id, 0) - 1)


async def wait_task_dispatch(
    task_id: str, escape: Callable[[], bool] | None = None
) -> None:
    """Park until both the task's gate and the process latch are open.

    ``escape`` (see :meth:`PauseGate.wait_open`) short-circuits the wait —
    used by the sample gate so a stamped graceful cancel passes through.
    """
    while True:
        if escape is not None and escape():
            return
        if _process_gate.paused:
            await _process_gate.wait_open(escape)
            continue
        gate = _task_gates.get(task_id)
        if gate is not None and gate.paused:
            await gate.wait_open(escape)
            continue
        return


def add_dispatch_waker(waker: Callable[[], None]) -> None:
    """Register a dispatcher wake callback fired on any pause-state change."""
    _dispatch_wakers.append(waker)


def remove_dispatch_waker(waker: Callable[[], None]) -> None:
    """Unregister a callback registered with :func:`add_dispatch_waker`."""
    try:
        _dispatch_wakers.remove(waker)
    except ValueError:
        pass


def _fire_dispatch_wakers() -> None:
    for waker in list(_dispatch_wakers):
        waker()


def wake_pause_waiters() -> None:
    """Wake every gate waiter so escape predicates get re-checked.

    Called at the cancel-stamp choke point (the ``cancel_task`` closure in
    ``_eval/run.py``): a sample parked at the pause gate must observe a
    graceful (score/error) resolution and proceed to the queue-exit abandon
    check — the gate holds starts, not terminal transitions. Waking on
    abort/retry too is harmless (the task scope's cancellation reaps the
    waiters regardless).
    """
    _process_gate.wake()
    for gate in _task_gates.values():
        gate.wake()
    _fire_dispatch_wakers()


def reset_task_pause_gates() -> None:
    """Clear the task pause gates (called per ``eval()`` run boundary).

    The same boundary that resets the sample-semaphore registry — so legacy
    batch-mode retries (``eval_set`` with ``retry_immediate=False``), which
    run each attempt as its own ``eval()`` call, start each attempt with
    open gates (task-level pause is documented as not surviving into the
    next batch attempt in that mode).
    """
    _task_gates.clear()
    _dispatch_counts.clear()


def reset_process_pause() -> None:
    """Clear the process pause latch (the outermost run boundary)."""
    global _process_gate
    _process_gate = PauseGate()


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------


async def pause_task(task_id: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Pause a running task (``POST /tasks/<task-id>/pause``).

    Closes the task's pause gate (unless ``dry_run``): no new samples leave
    the queue and a queued in-run retry attempt does not start; in-flight
    samples finish naturally. Returns ``None`` when the task isn't in this
    process (the route 404s); a ``changed: False`` no-op when it has already
    finished (nothing left to hold — but not for a task *between attempts*,
    whose queued retry the gate parks) or is already task-paused.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None
    result = _task_result(state, dry_run=dry_run)
    if state.completed_at is not None and not state.retry_pending:
        return {**result, "changed": False, "reason": "task already finished"}
    gate = _task_gate(state.task_id)
    if gate.paused:
        return {**result, "changed": False, "reason": "task already paused"}
    if not dry_run:
        gate.pause()
        result["paused"] = task_pause_scope(state.task_id)
        # a task paused with nothing in flight is quiesced immediately —
        # make the pause durable now rather than waiting on a sample exit
        await flush_quiesced_tasks()
    return {**result, "changed": True}


async def resume_task(task_id: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Resume a paused task (``POST /tasks/<task-id>/resume``).

    Opens the task's pause gate (unless ``dry_run``), waking parked samples
    and the task dispatchers. Returns ``None`` when the task isn't in this
    process; a ``changed: False`` no-op when its gate isn't closed. Does not
    clear the process latch — a task under both latches stays held by the
    process pause until ``process resume`` (independent latches; the
    response's ``paused`` scope reports what still holds it).
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None
    result = _task_result(state, dry_run=dry_run)
    gate = _task_gates.get(state.task_id)
    if gate is None or not gate.paused:
        return {**result, "changed": False, "reason": "task is not paused"}
    if not dry_run:
        gate.resume()
        result["paused"] = task_pause_scope(state.task_id)
        _fire_dispatch_wakers()
    return {**result, "changed": True}


async def pause_process(*, dry_run: bool = False) -> dict[str, Any]:
    """Pause the whole run (``POST /pause``).

    Closes the process latch: no new eval-set tasks dispatch, no task retry
    attempts start, and no samples dispatch in any task. Never ``None`` — a
    process always exists. Idempotent (``changed: False`` when already
    paused).
    """
    changed = not _process_gate.paused
    if changed and not dry_run:
        _process_gate.pause()
        await flush_quiesced_tasks()
    return {
        "ok": True,
        # the actual latch state (read after the conditional flip), matching
        # the task envelope — under dry_run the process is still unpaused
        "paused": _process_gate.paused,
        "dry_run": dry_run,
        "changed": changed,
        **({} if changed else {"reason": "process already paused"}),
    }


async def resume_process(*, dry_run: bool = False) -> dict[str, Any]:
    """Resume a paused run (``POST /resume``).

    Opens the process latch, waking parked samples and the task dispatchers.
    Task-level pauses are left in place (independent latches). Idempotent
    (``changed: False`` when not paused).
    """
    changed = _process_gate.paused
    if changed and not dry_run:
        _process_gate.resume()
        _fire_dispatch_wakers()
    return {
        "ok": True,
        "paused": _process_gate.paused,
        "dry_run": dry_run,
        "changed": changed,
        **({} if changed else {"reason": "process is not paused"}),
    }


def _task_result(state: "EvalState", *, dry_run: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "task_id": state.task_id,
        "task": state.task,
        "eval_id": state.eval_id,
        "paused": task_pause_scope(state.task_id),
        "dry_run": dry_run,
        # named `dispatched`, not `in_flight`: it includes samples still
        # initializing (started=None), which the /tasks listing's
        # samples.in_flight counts as queued
        "dispatched": task_dispatched_count(state.task_id),
    }


# ---------------------------------------------------------------------------
# Quiesce auto-flush
# ---------------------------------------------------------------------------


async def flush_quiesced_tasks() -> None:
    """Flush buffered samples of every quiesced (paused + idle) task.

    Makes a quiesced pause durable by default: everything completed is in
    the log, so killing the process at that point loses nothing a later
    ``eval-set`` re-invocation can't account for. Called when a pause lands
    (an already-idle task quiesces immediately) and from the sample gate's
    exit path (the last in-flight sample of a paused task completing is the
    quiesce transition). Idempotent — a flush with nothing pending writes
    nothing — and failures are logged, never raised (auto-flush is a
    convenience on the sample/directive path, not a correctness step).
    """
    from inspect_ai._control.eval_state import get_eval_states

    latest_by_task: dict[str, EvalState] = {}
    for state in get_eval_states():
        if state.task_id:
            latest_by_task[state.task_id] = state
    for state in latest_by_task.values():
        if state.live is None or state.completed_at is not None:
            continue
        if task_pause_scope(state.task_id) is None:
            continue
        if task_dispatched_count(state.task_id) > 0:
            continue
        try:
            await state.live.flush_samples()
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            logger.warning(
                "Error flushing samples for quiesced task %s",
                state.task_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Sample dispatch gate
# ---------------------------------------------------------------------------


class PauseGatedSemaphore(AbstractAsyncContextManager[None]):
    """The task's sample semaphore behind the pause gate.

    The queue-exit boundary of ``task_run_sample``: entering waits for both
    pause latches *before* acquiring a sample-semaphore slot (a held sample
    pins no limiter slot, has no sandbox, and — because materialization and
    the sample clocks start after the semaphore — has spent none of its
    ``time_limit`` / ``working_limit``), then re-checks after the acquire:
    a pause landing while a coroutine was already blocked on the semaphore
    must not leak a start, so on re-check failure the slot is released and
    the gate re-awaited.

    ``escape`` (a stamped task cancel) passes the gate — the sample proceeds
    to the queue-exit ``cancel_type`` abandon check rather than staying
    parked through teardown.

    Entry and exit also maintain the task's dispatched-sample count
    (:func:`task_dispatched_count`): the gate is the true dispatch boundary,
    so counting here — rather than from ``active_samples`` registration,
    which happens only after further await points — keeps ``quiesced``
    monotonic under a pause.

    Exiting releases the slot and, when the task is paused, runs the quiesce
    auto-flush — the last dispatched sample of a paused task completing is
    exactly the quiesce transition ``design/ctl/pause-resume.md`` makes durable.

    Reusable and concurrency-safe like the limiter it wraps (no per-entry
    state); the in-run sample retry path re-enters the same instance, so a
    paused task holds error retries of its own samples too.
    """

    def __init__(
        self,
        semaphore: AbstractAsyncContextManager[Any],
        task_id: str,
        escape: Callable[[], bool] | None = None,
    ) -> None:
        self._semaphore = semaphore
        self._task_id = task_id
        self._escape = escape

    def _escaped(self) -> bool:
        return self._escape is not None and self._escape()

    async def __aenter__(self) -> None:
        while True:
            await wait_task_dispatch(self._task_id, self._escape)
            await self._semaphore.__aenter__()
            if not task_dispatch_paused(self._task_id) or self._escaped():
                _dispatch_entered(self._task_id)
                return None
            await self._semaphore.__aexit__(None, None, None)

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        # decrement before the first await so a teardown cancellation
        # interrupting the semaphore release can't leave the count stuck
        _dispatch_exited(self._task_id)
        result = await self._semaphore.__aexit__(exc_type, exc_val, exc_tb)
        # only on a clean sample exit: under an exception/cancellation the
        # task is tearing down and the flush would await inside a cancelled
        # scope (an abort's teardown flushes via its own finalization path)
        if exc_type is None and task_dispatch_paused(self._task_id):
            await flush_quiesced_tasks()
        return result
