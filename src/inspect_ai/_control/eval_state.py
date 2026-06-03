"""Process-level per-eval state aggregate.

Tracks running totals across the samples of each in-flight eval
(``eval_id``-keyed). Consumed by the control-channel ``GET /evals``
endpoint to surface counts that ``active_samples()`` alone can't
provide.

The eval runner calls :func:`register_eval` at task start (when the
total sample count is known), plus :func:`record_sample_completed` /
:func:`record_sample_errored` at each sample's terminal outcome. States
are not unregistered per-eval — the registry is cleared in one shot at
the outermost run boundary (``eval`` / ``eval_set``) via
:func:`clear_all_eval_states`, which keeps completed evals visible in
``inspect ctl ls`` through the run (and any keep-alive park).

Lives under ``_control/`` because the control channel is currently
the only consumer; if other surfaces (TUI, view server) ever need
process-level eval counters, this can move up.

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

# Async accessor for an eval's completed-sample summaries (a list of
# ``EvalSampleSummary``, typed loosely to keep this module dependency-free).
SummariesProvider = Callable[[], Awaitable[list[Any] | None]]


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
    """The eval's id (matches ``ActiveSample.eval_id``). Per-attempt
    on retries — see :attr:`task_id` for the stable across-retry key."""

    total: int
    """Total samples this eval expects to run (``len(dataset) * epochs``)."""

    task_id: str = ""
    """Stable task identifier across retries.

    On task retry, ``eval_id`` is regenerated (see
    :meth:`TaskLogger.reinit`) but ``task_id`` is preserved. Used by
    the control endpoint to fold retry attempts of the same task
    into a single row."""

    completed: int = 0
    """Samples that finished without error (counted once per sample, at the
    final attempt's success — retries don't double-count)."""

    errored: int = 0
    """Samples whose final attempt failed (also counted once per sample)."""

    cancelled: int = 0
    """Samples cancelled at their final attempt — a sibling's failure (or an
    eval cancel) tore the task down while they were in flight. Terminal but
    not a genuine error: counted toward the finish total so the eval isn't
    stuck "running", but kept separate from :attr:`errored` so it doesn't
    render as a failure."""

    task: str = ""
    """Task name. Carried here so consumers (control channel `ls`) can label
    the eval even after all its samples have exited ``active_samples``
    (typically: under keep-alive, after the eval body completes)."""

    model: str = ""
    """Primary model name. Same rationale as :attr:`task`."""

    log_location: str = ""
    """This eval's log file location. The per-sample listing reads
    completed samples from here once the live recorder is gone (see
    :attr:`summaries_provider`)."""

    summaries_provider: SummariesProvider | None = None
    """Live accessor for completed-sample summaries from the recorder.
    The per-sample listing prefers this and falls back to
    :attr:`log_location` when it's ``None`` (reused/synthetic eval) or
    returns ``None`` (recorder torn down)."""

    sample_ids: list[str | int] = field(default_factory=list)
    """The eval's planned sample ids (after slicing). With :attr:`epochs`,
    the full set of planned ``(sample_id, epoch)`` pairs — which lets the
    per-sample listing surface *pending* (not-yet-started) samples, since
    no live source otherwise holds them. Empty for reused/synthetic evals
    (which have no pending samples)."""

    epochs: int = 1
    """Epoch count, paired with :attr:`sample_ids` to enumerate the
    planned ``(sample_id, epoch)`` pairs."""

    run_id: str | None = None
    """Process-level run id. Same rationale as :attr:`task`."""

    completed_at: float | None = None
    """Unix timestamp when this eval's last sample finished (i.e. when
    ``completed + errored`` first reached ``total``). ``None`` while the
    eval is still running. Used by the control endpoint to surface
    completion to agents without forcing them to derive it from counters."""

    will_retry: bool = False
    """Whether a failure of this attempt will be retried (task-level).

    Set from ``TaskCancel.can_retry`` at registration. Lets the control
    endpoint render a cancelled sample as ``pending`` (a retry will re-run
    it) rather than ``cancelled`` (terminal — no retry coming)."""

    total_tokens: int = 0
    """Cumulative model tokens used by this eval's terminal samples.

    Accumulated once per sample at its final outcome (mirrors
    :attr:`completed` / :attr:`errored`), so it survives samples leaving
    ``active_samples`` — i.e. it's the "usage so far", not a live snapshot.
    The control endpoint adds the in-flight samples' live usage on top."""

    total_messages: int = 0
    """Cumulative message count, accumulated like :attr:`total_tokens`."""

    @property
    def is_finished(self) -> bool:
        """True once every sample has terminated (success, error, or cancel)."""
        return (
            self.total > 0
            and self.completed + self.errored + self.cancelled >= self.total
        )


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
    task_id: str = "",
    model: str = "",
    log_location: str = "",
    summaries_provider: SummariesProvider | None = None,
    sample_ids: list[str | int] | None = None,
    epochs: int = 1,
    run_id: str | None = None,
    will_retry: bool = False,
) -> EvalState:
    """Initialize tracking for a new eval.

    Idempotent on ``eval_id`` — re-registering an existing eval (eg.
    on retry) returns the existing state without resetting its
    counters.
    """
    with _lock:
        existing = _eval_states.get(eval_id)
        if existing is not None:
            return existing
        state = EvalState(
            eval_id=eval_id,
            total=total,
            task=task,
            task_id=task_id,
            model=model,
            log_location=log_location,
            summaries_provider=summaries_provider,
            sample_ids=sample_ids or [],
            epochs=epochs,
            run_id=run_id,
            will_retry=will_retry,
        )
        _eval_states[eval_id] = state
        return state


def register_completed_eval(
    eval_id: str,
    *,
    total: int,
    completed: int,
    errored: int = 0,
    task: str = "",
    task_id: str = "",
    model: str = "",
    log_location: str = "",
    run_id: str | None = None,
    completed_at: float | None = None,
    total_tokens: int = 0,
    total_messages: int = 0,
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
            task_id=task_id,
            model=model,
            log_location=log_location,
            run_id=run_id,
            completed_at=completed_at if completed_at is not None else time.time(),
            total_tokens=total_tokens,
            total_messages=total_messages,
        )
        _eval_states[eval_id] = state
        return state


def record_sample_completed(
    eval_id: str, *, tokens: int = 0, messages: int = 0
) -> None:
    """Mark a sample as having finished successfully, accumulating its usage.

    Called once per sample at the final outcome — retries don't increment.
    ``tokens`` / ``messages`` are that sample's model usage, accumulated into
    the eval total so usage survives the sample leaving ``active_samples``
    (the "usage so far"). Silently no-ops if the eval isn't registered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.completed += 1
            state.total_tokens += tokens
            state.total_messages += messages
            _maybe_mark_finished(state)


def record_sample_errored(eval_id: str, *, tokens: int = 0, messages: int = 0) -> None:
    """Mark a sample as having finished with an error, accumulating its usage.

    Called once per sample at the final outcome (after retries are exhausted).
    ``tokens`` / ``messages`` are accumulated like
    :func:`record_sample_completed`. Silently no-ops if the eval isn't
    registered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.errored += 1
            state.total_tokens += tokens
            state.total_messages += messages
            _maybe_mark_finished(state)


def record_sample_cancelled(
    eval_id: str, *, tokens: int = 0, messages: int = 0
) -> None:
    """Mark a sample as terminally cancelled (sibling failure / eval cancel).

    Terminal but not a genuine error — counted toward the finish total (so the
    eval isn't stuck "running") in its own bucket, separate from ``errored``.
    Usage accumulates like the other terminal records. No-ops if unregistered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.cancelled += 1
            state.total_tokens += tokens
            state.total_messages += messages
            _maybe_mark_finished(state)


def _maybe_mark_finished(state: EvalState) -> None:
    """Stamp ``completed_at`` when every sample has terminated.

    Fires the first time ``completed + errored`` reaches ``total``;
    later updates are no-ops so a late counter update from a teardown
    race doesn't overwrite the original finish time. Also drops
    ``sample_ids`` — a finished eval has no pending samples, so the
    planned-id list is dead weight (it's retained on the state until the
    run boundary clears it). Caller must hold the registry lock.
    """
    if state.completed_at is None and state.is_finished:
        state.completed_at = time.time()
        state.sample_ids = []


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

    Called at the outermost run boundary (``eval`` / ``eval_set``) — after
    any keep-alive park — to clear the registry in one shot, since evals
    are no longer unregistered individually.
    """
    with _lock:
        _eval_states.clear()
