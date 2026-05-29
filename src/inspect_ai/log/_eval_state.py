"""Process-level per-eval state aggregate.

Sibling concept to :class:`inspect_ai.log._samples.ActiveSample` — that
tracks one in-flight sample; this tracks the running totals across
samples within one eval (``eval_id``-keyed).

The eval runner calls :func:`register_eval` at task start (when the
total sample count is known) and :func:`unregister_eval` at task end,
plus :func:`record_sample_started` / :func:`record_sample_completed` /
:func:`record_sample_errored` at each sample's lifecycle transitions.

The control channel reads these states to populate ``GET /evals``.
The viewer / TUI could too; nothing here is control-channel-specific.

Why a counter aggregate rather than computing on demand from
``active_samples()``:

- ``active_samples`` carries only currently-registered samples;
  completed ones are removed, so we can't count them.
- The total sample count is known at task start but isn't otherwise
  available from the sample-level state.
- A running counter is cheap and updated at well-defined transition
  points, vs. polling derived state from elsewhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass
class EvalState:
    """Per-eval terminal-sample counters.

    Only stores ``total`` plus terminal-outcome counters. ``in_flight``
    is intentionally NOT stored here — it's derived from
    :func:`inspect_ai.log._samples.active_samples` at read time so
    retries (which open a fresh ``ActiveSample`` per attempt) can't
    drift the counter. ``queued`` is also derived (everything not
    accounted for elsewhere).
    """

    eval_id: str
    """The eval's id (matches ``ActiveSample.eval_id``)."""

    total: int
    """Total samples this eval expects to run (``len(dataset) * epochs``)."""

    completed: int = 0
    """Samples that finished without error (counted once per sample, at the
    final attempt's success — retries don't double-count)."""

    errored: int = 0
    """Samples whose final attempt failed (also counted once per sample)."""

    task: str = ""
    """Task name. Carried here so consumers (control channel `ls`) can label
    the eval even after all its samples have exited ``active_samples``
    (typically: under keep-alive, after the eval body completes)."""

    model: str = ""
    """Primary model name. Same rationale as :attr:`task`."""

    run_id: str | None = None
    """Process-level run id. Same rationale as :attr:`task`."""

    completed_at: float | None = None
    """Unix timestamp when this eval's last sample finished (i.e. when
    ``completed + errored`` first reached ``total``). ``None`` while the
    eval is still running. Used by the control endpoint to surface
    completion to agents without forcing them to derive it from counters."""

    @property
    def is_finished(self) -> bool:
        """True once every sample has terminated (success or error)."""
        return self.total > 0 and self.completed + self.errored >= self.total


# Module-level registry. Keyed by eval_id. A process can host multiple
# evals concurrently (an eval-set passes all tasks to one ``eval()``
# call), so this is a dict not a single slot.
_eval_states: dict[str, EvalState] = {}
_lock = Lock()


def register_eval(
    eval_id: str,
    total: int,
    *,
    task: str = "",
    model: str = "",
    run_id: str | None = None,
) -> EvalState:
    """Initialize tracking for a new eval.

    Idempotent on ``eval_id`` — re-registering an existing eval (eg.
    on retry) returns the existing state without resetting its
    counters. Callers that want a clean slate must
    :func:`unregister_eval` first.
    """
    with _lock:
        existing = _eval_states.get(eval_id)
        if existing is not None:
            return existing
        state = EvalState(
            eval_id=eval_id, total=total, task=task, model=model, run_id=run_id
        )
        _eval_states[eval_id] = state
        return state


def unregister_eval(eval_id: str) -> None:
    """Remove an eval from tracking (best-effort; unknown id is a no-op)."""
    with _lock:
        _eval_states.pop(eval_id, None)


def register_completed_eval(
    eval_id: str,
    *,
    total: int,
    completed: int,
    errored: int = 0,
    task: str = "",
    model: str = "",
    run_id: str | None = None,
    completed_at: float | None = None,
) -> EvalState:
    """Register an eval that has already finished.

    Used by ``eval_set`` to publish synthetic state for tasks whose
    successful logs were reused from a prior run — those tasks never
    enter ``task_run.py``, so the per-sample counter path that would
    normally maintain the state never fires. This bulk-equivalent
    sets the terminal counters up-front so ``current_eval_summaries``
    surfaces the eval as completed.

    If an :class:`EvalState` for ``eval_id`` already exists, its
    fields are overwritten (the reused-log data is authoritative —
    we never reuse an eval that's also actively running).
    ``completed_at`` defaults to "now" when not supplied.
    """
    with _lock:
        state = EvalState(
            eval_id=eval_id,
            total=total,
            completed=completed,
            errored=errored,
            task=task,
            model=model,
            run_id=run_id,
            completed_at=completed_at if completed_at is not None else time.time(),
        )
        _eval_states[eval_id] = state
        return state


def record_sample_completed(eval_id: str) -> None:
    """Mark a sample as having finished successfully.

    Called once per sample at the final outcome — retries don't
    increment. Silently no-ops if the eval isn't registered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.completed += 1
            _maybe_mark_finished(state)


def record_sample_errored(eval_id: str) -> None:
    """Mark a sample as having finished with an error.

    Called once per sample at the final outcome (after retries are
    exhausted). Silently no-ops if the eval isn't registered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.errored += 1
            _maybe_mark_finished(state)


def _maybe_mark_finished(state: EvalState) -> None:
    """Stamp ``completed_at`` when every sample has terminated.

    Fires the first time ``completed + errored`` reaches ``total``;
    later updates are no-ops so a late counter update from a teardown
    race doesn't overwrite the original finish time. Caller must hold
    the registry lock.
    """
    if state.completed_at is None and state.is_finished:
        state.completed_at = time.time()


def get_eval_state(eval_id: str) -> EvalState | None:
    """Look up state for one eval, or None if not tracked."""
    with _lock:
        return _eval_states.get(eval_id)


def get_eval_states() -> list[EvalState]:
    """Snapshot of all currently-tracked eval states."""
    with _lock:
        return list(_eval_states.values())


def clear_all_eval_states() -> None:
    """Remove every tracked eval state.

    Used by the keep-alive teardown to clear the registry on shutdown
    (where per-task ``unregister_eval`` was skipped while keep-alive
    was active).
    """
    with _lock:
        _eval_states.clear()
