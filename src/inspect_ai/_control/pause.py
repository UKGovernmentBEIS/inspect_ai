"""Pause / resume directives for the control channel.

Implements the quiesce semantics of ``design/ctl/pause-resume.md``: **pause**
stops a run from *starting* work — no new samples leave the queue, no task
retry attempts start, no eval-set tasks dispatch — while everything already
in flight completes normally (solving, scoring, log writes) under its
original limits. **resume** re-opens the gates in O(1). Both are
non-destructive, idempotent, last-write-wins, and dry-runnable, per the
phase-3 directive conventions.

Each latch has two strengths. The default (**soft**) pause is pure quiesce.
The **hard** variant (``pause --now`` — the ``now`` param on the wire)
additionally holds in-flight samples at their next model call: outstanding
model calls (and batch waits) complete, but no new generate (or compaction)
attempt starts until resume (see :func:`wait_generate_dispatch`). ``resume`` clears both
strengths for its scope; a plain ``pause`` after ``pause --now`` downgrades
to soft (last-write-wins).

Three independent latches, all checked at every dispatch point:

- **Task gates** (:func:`pause_task` / :func:`resume_task`) live in a
  task-id-keyed registry parallel to the sample-semaphore registry in
  ``inspect_ai.util._concurrency`` and reset at the same run boundary, so a
  pause survives in-run retry attempts of the same task.
- **Model gates** (:func:`pause_model` / :func:`resume_model`) live in a
  registry keyed by the task's *primary* model name (the
  :func:`dispatch_model_name` snapshot, the name ``GET /tasks`` reports;
  role/grader models deliberately don't match)
  and reset with the task gates. One latch holds every task of that model —
  including not-yet-started eval-set tasks, which task-level pause
  structurally cannot reach — without fanning out over task pauses.
- **The process latch** (:func:`pause_process` / :func:`resume_process`) is
  one module-level gate — the eval-set spelling ("pause the whole run") —
  reset at the outermost run boundary like the keep-alive intent.

``resume`` at any scope deliberately clears only its own latch: resuming the
run after an incident must not silently un-pause a task (or model) an
operator paused for its own reasons.

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

import time
from contextlib import AbstractAsyncContextManager
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Literal, NamedTuple

import anyio

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai.model import Model

logger = getLogger(__name__)


PauseSource = Literal["task", "process", "model"]
"""One latch holding a paused task.

The ``paused`` field of ``GET /tasks`` (and of the task pause/resume
envelopes) is ``None`` when the task is dispatchable, else the non-empty
list of holding sources in the fixed order task, process, model. (Before
the model latch existed it was a single string with ``"both"`` for
task+process — the CLI still normalizes that legacy shape when talking to
an older server.)
"""


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
        self._hard = False
        self._changed: anyio.Event | None = None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def hard(self) -> bool:
        """Whether the gate is hard-closed (``pause --now``).

        Hard implies paused: the hard latch additionally parks generate
        attempts (:func:`wait_generate_dispatch`) on top of the dispatch
        holds every closed gate imposes.
        """
        return self._hard

    def would_change(self, now: bool = False) -> bool:
        """Whether :meth:`pause` with this strength would change the state.

        Side-effect-free: the pause verbs use it to answer idempotent
        repeats (and dry runs) without flipping the gate.
        """
        return not self._paused or self._hard != now

    def pause(self, now: bool = False) -> bool:
        """Close the gate (``now`` additionally closes the generate latch).

        Last-write-wins across strengths: ``pause --now`` on a soft-paused
        gate escalates; a plain ``pause`` on a hard-paused gate downgrades to
        soft, waking waiters so parked generate attempts proceed (dispatch
        waiters re-check, find the gate still closed, and re-park). Returns
        whether the state changed.
        """
        changed = self.would_change(now)
        if self._hard and not now:
            self.wake()
        self._paused = True
        self._hard = now
        return changed

    def resume(self) -> bool:
        """Open the gate (both strengths), waking waiters. Returns whether the state changed."""
        if not self._paused:
            return False
        self._paused = False
        self._hard = False
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

    async def wait_hard_open(self) -> None:
        """Park while the gate is hard-closed (the ``pause --now`` latch).

        No ``escape`` counterpart to :meth:`wait_open`: the generate gate's
        terminal transitions arrive as sample-scope cancellation (a sample
        or task cancel tears down the sample's task group), which cancels
        the parked wait directly.
        """
        while self._hard:
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

# Model pause gates, keyed by the task's primary model name (the
# dispatch_model_name snapshot — the value register_eval stores and
# GET /tasks reports). One gate holds every dispatch point of that model's
# tasks, including not-yet-started eval-set tasks (which have no EvalState
# yet — the scheduler passes the model name alongside the task id). Reset
# with the task gates: the same run boundary, the same legacy batch-mode
# caveat.
_model_gates: dict[str, PauseGate] = {}

# First-seen str(model) per Model object (identity-keyed, like the
# dispatcher's model_counts — see dispatch_model_name). Reset with the task
# gates.
_dispatch_model_names: dict["Model", str] = {}

# Primary model names of every task handed to the run dispatcher
# (run_task_retry_attempts registers them via note_dispatch_models),
# including tasks that haven't started — which have no EvalState for the
# model directives to validate against. Reset with the task gates.
_dispatch_models: set[str] = set()

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

# Samples currently held at the hard-pause generate gate, per task:
# task_id -> ActiveSample.id -> count of parked generate attempts (one
# sample can park several concurrent generates; task_held_count reports
# distinct samples). Reset with the task gates.
_held_samples: dict[str, dict[str, int]] = {}


def _task_gate(task_id: str) -> PauseGate:
    gate = _task_gates.get(task_id)
    if gate is None:
        gate = PauseGate()
        _task_gates[task_id] = gate
    return gate


def _model_gate(model: str) -> PauseGate:
    gate = _model_gates.get(model)
    if gate is None:
        gate = PauseGate()
        _model_gates[model] = gate
    return gate


def _resolve_task_model(task_id: str, model: str | None) -> str | None:
    """The task's primary model name for the model-gate check.

    Dispatch hooks pass the name they already hold (``model``); callers
    without one (the task directives, tests) fall back to the registered
    ``EvalState`` — which a not-yet-started eval-set task doesn't have,
    which is exactly why the scheduler must pass the name itself. Resolved
    only when some model gate is actually closed, so the common no-latch
    path stays lookup-free.
    """
    if model is not None:
        return model
    if not any(gate.paused for gate in _model_gates.values()):
        return None
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    return state.model or None if state is not None else None


def _task_pause_sources(
    task_id: str, model: str | None, closed: Callable[[PauseGate], bool]
) -> list[PauseSource]:
    """The latches for which ``closed`` holds, in the fixed task/process/model order.

    Note the hard variant leans on hard implying paused:
    :func:`_resolve_task_model`'s fast path only resolves when some model
    gate is *paused*.
    """
    sources: list[PauseSource] = []
    gate = _task_gates.get(task_id)
    if gate is not None and closed(gate):
        sources.append("task")
    if closed(_process_gate):
        sources.append("process")
    model_name = _resolve_task_model(task_id, model)
    if model_name is not None:
        model_gate = _model_gates.get(model_name)
        if model_gate is not None and closed(model_gate):
            sources.append("model")
    return sources


def task_pause_sources(task_id: str, model: str | None = None) -> list[PauseSource]:
    """The latches holding the task — empty when it is dispatchable.

    ``model`` is the task's primary model name where the caller knows it
    (see :func:`_resolve_task_model`). Sources come back in the fixed
    task / process / model order :data:`PauseSource` documents.
    """
    return _task_pause_sources(task_id, model, lambda gate: gate.paused)


def task_pause_now_sources(task_id: str, model: str | None = None) -> list[PauseSource]:
    """The latches *hard*-holding (``pause --now``) the task.

    A subset of :func:`task_pause_sources` (hard implies paused). Reported
    as the ``paused_now`` field alongside ``paused``, so the read surface
    can tell the hard variant apart: a hard-paused task additionally holds
    its in-flight samples at their next model call (see the ``held`` count).
    """
    return _task_pause_sources(task_id, model, lambda gate: gate.hard)


def task_dispatch_paused(task_id: str, model: str | None = None) -> bool:
    """Whether starting new work for ``task_id`` is held by a pause latch.

    ``model`` (the task's primary model name) lets the caller include the
    model latch for a task with no registered ``EvalState`` yet — the
    eval-set scheduler's not-yet-started tasks.
    """
    return bool(task_pause_sources(task_id, model))


def process_paused() -> bool:
    """Whether the process-level pause latch is closed."""
    return _process_gate.paused


def process_paused_now() -> bool:
    """Whether the process-level pause latch is hard-closed (``pause --now``)."""
    return _process_gate.hard


def model_paused(model: str) -> bool:
    """Whether ``model``'s pause latch is closed."""
    gate = _model_gates.get(model)
    return gate is not None and gate.paused


def model_paused_now(model: str) -> bool:
    """Whether ``model``'s pause latch is hard-closed (``pause --now``)."""
    gate = _model_gates.get(model)
    return gate is not None and gate.hard


def paused_models() -> list[str]:
    """The models whose pause latch is closed, sorted by name.

    Stamped on every ``GET /tasks`` row (like ``process_paused``) so the
    read surface reports the latched models even when none of their tasks
    has registered yet.
    """
    return sorted(name for name, gate in _model_gates.items() if gate.paused)


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


def task_held_count(task_id: str) -> int:
    """Samples of ``task_id`` currently held at the hard-pause generate gate.

    A held sample is still *dispatched* (mid-flight, sandbox up), so a
    hard-paused task doesn't read ``quiesced`` while any sample is held —
    and unlike soft pause, ``quiesced`` is not the safe-to-kill signal for a
    hard pause: killing while ``held > 0`` forfeits the in-sample progress
    hold semantics exist to preserve. This count doubles as the
    don't-kill-yet warning on the read surface.
    """
    return len(_held_samples.get(task_id, {}))


def _held_entered(task_id: str, sample_id: str) -> None:
    held = _held_samples.setdefault(task_id, {})
    held[sample_id] = held.get(sample_id, 0) + 1


def _held_exited(task_id: str, sample_id: str) -> None:
    held = _held_samples.get(task_id)
    if held is None:
        return
    count = held.get(sample_id, 0) - 1
    if count > 0:
        held[sample_id] = count
    else:
        held.pop(sample_id, None)
        if not held:
            _held_samples.pop(task_id, None)


async def wait_task_dispatch(
    task_id: str,
    escape: Callable[[], bool] | None = None,
    model: str | None = None,
) -> None:
    """Park until the task's gate, its model's gate, and the process latch are open.

    ``escape`` (see :meth:`PauseGate.wait_open`) short-circuits the wait —
    used by the sample gate so a stamped graceful cancel passes through.
    ``model`` is the task's primary model name (see :func:`task_dispatch_paused`).
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
        model_name = _resolve_task_model(task_id, model)
        if model_name is not None:
            model_gate = _model_gates.get(model_name)
            if model_gate is not None and model_gate.paused:
                await model_gate.wait_open(escape)
                continue
        return


# Interval between waiting-time credits while a generate attempt is held at
# the hard-pause gate. monitor_working_limit polls working time every second
# (skipping only active model events — a span the gate sits outside), so held
# time must be credited incrementally: crediting only at hold end would let a
# working_limit expire and kill the sample mid-hold, forfeiting exactly the
# in-sample progress hold semantics exist to preserve. Unlike retry backoff,
# a hold cannot pre-credit — its duration is unknown at hold start. Half the
# monitor's poll interval: the tick and the poll are unsynchronized, so a
# full-interval tick could leave ~1s of hold uncredited at a monitor wake —
# enough to reap a sample that entered the hold with under a second of
# working budget left.
_HELD_CREDIT_INTERVAL: float = 0.5


def _any_hard_gate() -> bool:
    """Fast path for the per-attempt generate-gate check.

    The registries hold at most a handful of gates, so scanning them on
    every generate attempt is cheap — and when nothing is hard-paused (the
    overwhelmingly common case) the gate does no sample/task resolution at
    all.
    """
    return (
        _process_gate.hard
        or any(gate.hard for gate in _task_gates.values())
        or any(gate.hard for gate in _model_gates.values())
    )


def _generate_hold_gate(task_id: str | None, model: str) -> PauseGate | None:
    """The first hard-closed latch holding a generate attempt, or ``None``.

    The model check keys on the model *actually being called* — deliberately
    unlike the soft model latch's primary-model-only keying — so a hard model
    pause holds grader/role calls to the latched model too: exactly what a
    provider incident wants.
    """
    if _process_gate.hard:
        return _process_gate
    if task_id:
        gate = _task_gates.get(task_id)
        if gate is not None and gate.hard:
            return gate
    model_gate = _model_gates.get(model)
    if model_gate is not None and model_gate.hard:
        return model_gate
    return None


class _HoldKey(NamedTuple):
    task_id: str | None
    sample: Any  # ActiveSample | None (imported lazily; avoid a log import cycle)


def _active_sample_hold_key() -> _HoldKey:
    """The active sample's task id and the sample itself.

    The task id feeds the task-gate check, the sample the held-samples count
    (keyed by ``sample.id``) and the interrupt-escape check; both are
    ``None`` outside a sample context.
    """
    from inspect_ai.log._samples import sample_active

    sample = sample_active()
    if sample is None:
        return _HoldKey(task_id=None, sample=None)
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(sample.eval_id)
    task_id = (state.task_id or None) if state is not None else None
    return _HoldKey(task_id=task_id, sample=sample)


async def wait_generate_dispatch(
    model: "Model", report_waiting_time: Callable[[float], None]
) -> None:
    """Hard-pause gate for one generate attempt (``pause --now``).

    Awaited at the top of the tenacity-wrapped attempt in ``Model._generate``
    and ``Model.compact`` (provider-native compaction rewrites conversation
    state and can be a long-context sample's single most expensive call;
    ``Model.count_tokens`` deliberately stays ungated — non-generative,
    read-only, cheap to free), so first attempts and retry attempts gate
    uniformly: an attempt begins
    when its backoff has elapsed *and* the gate is open (extending resolved
    question 2 of ``design/ctl/pause-resume.md`` to the hard gate; the two
    waiting spans are disjoint by construction, since backoff pre-credits its
    sleep and a park starts only after the sleep completes). Parks while the
    process latch, the active sample's task gate, or the called model's gate
    is hard-closed.

    Held time is credited as waiting time incrementally (every
    ``_HELD_CREDIT_INTERVAL`` seconds, and on the way out — including
    cancellation) through ``report_waiting_time``, which must feed
    ``report_sample_waiting_time`` (keeping ``working_limit`` enforcement and
    the sample's reported working time honest) plus whatever call-local
    accounting the caller keeps: generate passes a closure that also feeds
    its own waiting accumulator, whose post-call reconciliation would
    otherwise re-report the held span as provider-internal waiting; compact
    has no reconciliation and passes ``report_sample_waiting_time`` directly. ``time_limit``
    deadlines deliberately keep running while held — explicitly the
    operator's risk with ``pause --now``.

    Cancel escalates over pause: a stamped sample interrupt (graceful
    cancel) passes the gate rather than parking — the sample-scope
    cancellation that usually reaps a parked wait can't reach a generate
    issued *after* the sample's task group exited (a model-graded scorer
    running under a ``score`` resolution), so the escape is checked at
    entry and re-checked on every wake/tick.
    """
    if not _any_hard_gate():
        return
    model_name = dispatch_model_name(model)
    task_id, sample = _active_sample_hold_key()

    def escaped() -> bool:
        return sample is not None and sample.interrupt_action is not None

    gate = _generate_hold_gate(task_id, model_name)
    if gate is None or escaped():
        return
    if task_id is not None and sample is not None:
        _held_entered(task_id, sample.id)
    last = time.monotonic()
    try:
        while gate is not None and not escaped():
            # the tick both keeps working-limit crediting incremental and
            # bounds the latency of an escape stamped while parked (a
            # per-sample interrupt has no waker into this gate)
            with anyio.move_on_after(_HELD_CREDIT_INTERVAL):
                await gate.wait_hard_open()
            now = time.monotonic()
            report_waiting_time(now - last)
            last = now
            # re-resolve: the parked-on gate may have opened while another
            # latch hard-closed (independent latches)
            gate = _generate_hold_gate(task_id, model_name)
    finally:
        tail = time.monotonic() - last
        if tail > 0:
            report_waiting_time(tail)
        if task_id is not None and sample is not None:
            _held_exited(task_id, sample.id)


def dispatch_model_name(model: "Model") -> str:
    """The stable model name the model pause latch keys on.

    ``str(model)`` isn't stable: a provider may rewrite its model name on
    first use (vLLM resolves a ``base:adapter`` LoRA spec to ``base`` on the
    first generate — the same hazard that makes the run dispatcher key its
    balancing counts by ``Model`` identity). The latch's name is captured at
    several different times (dispatcher enqueue, task start, live at every
    scheduler pick), so a mid-run rename would fragment it — neither the old
    nor the new name would hold every dispatch point. Snapshotting
    ``str(model)`` at first sight per ``Model`` object (one object serves all
    of a model's tasks) keeps every surface — gate keys, dispatch checks,
    ``GET /tasks`` — agreed on one name for the whole run. Reset with the
    task gates.
    """
    name = _dispatch_model_names.get(model)
    if name is None:
        name = str(model)
        _dispatch_model_names[model] = name
    return name


def note_dispatch_models(models: list[str]) -> None:
    """Record the primary model names of tasks handed to the run dispatcher.

    Called by ``run_task_retry_attempts`` as tasks are enqueued (initial and
    injected alike), so the model directives can validate a model name
    against tasks that haven't started — which have no ``EvalState`` to
    check. Reset with the task gates.
    """
    _dispatch_models.update(models)


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
    for gate in _model_gates.values():
        gate.wake()
    _fire_dispatch_wakers()


def reset_task_pause_gates() -> None:
    """Clear the task and model pause gates (called per ``eval()`` run boundary).

    The same boundary that resets the sample-semaphore registry — so legacy
    batch-mode retries (``eval_set`` with ``retry_immediate=False``), which
    run each attempt as its own ``eval()`` call, start each attempt with
    open gates (task- and model-level pause is documented as not surviving
    into the next batch attempt in that mode). The model gates reset here
    rather than with the process latch: they key on run-scoped model names,
    exactly like the task gates key on run-scoped task ids.
    """
    _task_gates.clear()
    _model_gates.clear()
    _dispatch_models.clear()
    _dispatch_model_names.clear()
    _dispatch_counts.clear()
    _held_samples.clear()


def reset_process_pause() -> None:
    """Clear the process pause latch (the outermost run boundary)."""
    global _process_gate
    _process_gate = PauseGate()


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------


async def pause_task(
    task_id: str, *, now: bool = False, dry_run: bool = False
) -> dict[str, Any] | None:
    """Pause a running task (``POST /tasks/<task-id>/pause``).

    Closes the task's pause gate (unless ``dry_run``): no new samples leave
    the queue and a queued in-run retry attempt does not start; in-flight
    samples finish naturally. ``now`` closes the gate *hard* — in-flight
    samples additionally hold at their next model call until resume. Returns
    ``None`` when the task isn't in this process (the route 404s); a
    ``changed: False`` no-op when it has already finished (nothing left to
    hold — but not for a task *between attempts*, whose queued retry the
    gate parks) or is already paused at the requested strength (changing
    strength counts as a change: ``--now`` escalates a soft pause, a plain
    pause downgrades a hard one).
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None
    result = _task_result(state, dry_run=dry_run)
    if state.completed_at is not None and not state.retry_pending:
        return {**result, "changed": False, "reason": "task already finished"}
    gate = _task_gate(state.task_id)
    if not gate.would_change(now):
        reason = "task already paused --now" if now else "task already paused"
        return {**result, "changed": False, "reason": reason}
    if not dry_run:
        gate.pause(now)
        result["paused"] = (
            task_pause_sources(state.task_id, state.model or None) or None
        )
        result["paused_now"] = (
            task_pause_now_sources(state.task_id, state.model or None) or None
        )
        # a task paused with nothing in flight is quiesced immediately —
        # make the pause durable now rather than waiting on a sample exit
        await flush_quiesced_tasks()
    return {**result, "changed": True}


async def resume_task(task_id: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Resume a paused task (``POST /tasks/<task-id>/resume``).

    Opens the task's pause gate (unless ``dry_run``), waking parked samples
    and the task dispatchers. Returns ``None`` when the task isn't in this
    process; a ``changed: False`` no-op when its gate isn't closed. Does not
    clear the process or model latches — a task under several latches stays
    held until each is resumed (independent latches; the response's
    ``paused`` sources report what still holds it).
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
        result["paused"] = (
            task_pause_sources(state.task_id, state.model or None) or None
        )
        result["paused_now"] = (
            task_pause_now_sources(state.task_id, state.model or None) or None
        )
        _fire_dispatch_wakers()
    return {**result, "changed": True}


async def pause_process(*, now: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Pause the whole run (``POST /pause``).

    Closes the process latch: no new eval-set tasks dispatch, no task retry
    attempts start, and no samples dispatch in any task. ``now`` closes it
    *hard* — in-flight samples additionally hold at their next model call.
    Never ``None`` — a process always exists. Idempotent (``changed: False``
    when already paused at the requested strength).
    """
    changed = _process_gate.would_change(now)
    if changed and not dry_run:
        _process_gate.pause(now)
        await flush_quiesced_tasks()
    return {
        "ok": True,
        # the actual latch state (read after the conditional flip), matching
        # the task envelope — under dry_run the process is still unpaused
        "paused": _process_gate.paused,
        "now": _process_gate.hard,
        "dry_run": dry_run,
        "changed": changed,
        **(
            {}
            if changed
            else {
                "reason": "process already paused --now"
                if now
                else "process already paused"
            }
        ),
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
        "now": _process_gate.hard,
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
        "paused": task_pause_sources(state.task_id, state.model or None) or None,
        "paused_now": task_pause_now_sources(state.task_id, state.model or None)
        or None,
        "dry_run": dry_run,
        # named `dispatched`, not `in_flight`: it includes samples still
        # initializing (started=None), which the /tasks listing's
        # samples.in_flight counts as queued
        "dispatched": task_dispatched_count(state.task_id),
        # samples parked at the hard-pause generate gate (a subset of
        # `dispatched` — held samples are mid-flight)
        "held": task_held_count(state.task_id),
    }


def _known_model(model: str) -> bool:
    """Whether ``model`` is a primary model this process could dispatch.

    The union of the run dispatcher's task models (which covers
    not-yet-started eval-set tasks) and the registered evals' models (which
    covers a process whose dispatcher hasn't enqueued yet, and reused logs),
    plus any model that already has a gate (so a pause stays resumable even
    if the name later drops out of both sets). Unknown names 404 at the
    route — for an incident lever, a typo'd model name silently latching
    nothing is worse than an error.
    """
    if model in _dispatch_models or model in _model_gates:
        return True
    from inspect_ai._control.eval_state import get_eval_states

    return any(state.model == model for state in get_eval_states())


class ModelTaskStats(NamedTuple):
    tasks: int
    dispatched: int


def _model_task_stats(model: str) -> ModelTaskStats:
    """Unfinished tasks of ``model`` and their dispatched-sample sum.

    Counts only *registered* tasks (latest attempt per task_id, same fold as
    the listing): a not-yet-started eval-set task has no ``EvalState``, so
    the counts understate the latch's reach — the envelope's messaging is
    phrased accordingly.
    """
    from inspect_ai._control.eval_state import get_eval_states

    latest_by_task: dict[str, "EvalState"] = {}
    for state in get_eval_states():
        if state.task_id:
            latest_by_task[state.task_id] = state
    tasks = [
        state
        for state in latest_by_task.values()
        if state.model == model and (state.completed_at is None or state.retry_pending)
    ]
    return ModelTaskStats(
        tasks=len(tasks),
        dispatched=sum(task_dispatched_count(s.task_id) for s in tasks),
    )


async def pause_model(
    model: str, *, now: bool = False, dry_run: bool = False
) -> dict[str, Any] | None:
    """Pause dispatch for one model (``POST /models/pause``).

    Closes the model's pause gate (unless ``dry_run``): no samples dispatch
    in tasks whose *primary* model is ``model``, their queued retry attempts
    hold, and the eval-set scheduler does not start their not-yet-started
    tasks — while every other model's work continues. In-flight samples
    finish naturally (quiesce semantics), including generate calls to this
    model from other tasks' roles/graders — the soft latch gates dispatch,
    not generate. ``now`` closes the gate *hard*: generate calls hold at
    their next attempt too, keyed on the model *actually being called*
    (deliberately unlike the soft latch's primary-model-only keying), so
    grader/role calls to the latched model hold as well. Returns ``None``
    when the model isn't known to this process (the route 404s); idempotent
    (``changed: False`` when already paused at the requested strength).
    """
    if not _known_model(model):
        return None
    result = _model_result(model, dry_run=dry_run)
    gate = _model_gate(model)
    if not gate.would_change(now):
        reason = "model already paused --now" if now else "model already paused"
        return {**result, "changed": False, "reason": reason}
    if not dry_run:
        gate.pause(now)
        result["paused"] = True
        result["now"] = gate.hard
        await flush_quiesced_tasks()
    return {**result, "changed": True}


async def resume_model(model: str, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Resume a paused model (``POST /models/resume``).

    Opens the model's pause gate (unless ``dry_run``), waking parked samples
    and the task dispatchers. Task-level and process-level pauses are left
    in place (independent latches). Returns ``None`` when the model isn't
    known to this process; a ``changed: False`` no-op when its gate isn't
    closed.
    """
    if not _known_model(model):
        return None
    result = _model_result(model, dry_run=dry_run)
    gate = _model_gates.get(model)
    if gate is None or not gate.paused:
        return {**result, "changed": False, "reason": "model is not paused"}
    if not dry_run:
        gate.resume()
        result["paused"] = False
        result["now"] = False
        _fire_dispatch_wakers()
    return {**result, "changed": True}


def _model_result(model: str, *, dry_run: bool) -> dict[str, Any]:
    stats = _model_task_stats(model)
    return {
        "ok": True,
        "model": model,
        "paused": model_paused(model),
        "now": model_paused_now(model),
        "dry_run": dry_run,
        # registered, unfinished tasks of this model — not-yet-started
        # eval-set tasks aren't registered, so the latch can hold more than
        # this counts (see _model_task_stats)
        "tasks": stats.tasks,
        "dispatched": stats.dispatched,
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
        if not task_pause_sources(state.task_id, state.model or None):
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

    The queue-exit boundary of ``task_run_sample``: entering waits for every
    pause latch (task, model, process) *before* acquiring a sample-semaphore
    slot (a held sample
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
        model: str | None = None,
    ) -> None:
        self._semaphore = semaphore
        self._task_id = task_id
        self._escape = escape
        self._model = model

    def _escaped(self) -> bool:
        return self._escape is not None and self._escape()

    async def __aenter__(self) -> None:
        while True:
            await wait_task_dispatch(self._task_id, self._escape, self._model)
            await self._semaphore.__aenter__()
            if not task_dispatch_paused(self._task_id, self._model) or self._escaped():
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
        if exc_type is None and task_dispatch_paused(self._task_id, self._model):
            await flush_quiesced_tasks()
        return result
