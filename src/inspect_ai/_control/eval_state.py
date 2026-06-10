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
``inspect ctl tasks`` through the run (and any keep-alive park).

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
from dataclasses import dataclass, field
from logging import getLogger
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple, Protocol

logger = getLogger(__name__)

# The provider types live under TYPE_CHECKING so this module stays
# dependency-free at runtime (it's imported during eval bootstrap, before the
# log/event packages finish initializing). PEP 563 (`from __future__ import
# annotations`) means every annotation below is a string, so nothing here is
# evaluated at runtime — but note that `typing.get_type_hints(EvalState)`
# would fail outside a type-checking context.
if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from inspect_ai.log._log import EvalSample, EvalSampleSummary
    from inspect_ai.log._transcript import TranscriptHistoryProvider

    # Async accessor for an eval's completed-sample summaries.
    SummariesProvider = Callable[[], Awaitable[list[EvalSampleSummary] | None]]

    # Async accessor for one full sample by ``(id, epoch)``. A Protocol
    # (rather than a Callable alias) because of the keyword-only
    # ``exclude_fields`` argument.
    class SampleProvider(Protocol):
        def __call__(
            self,
            id: str | int,
            epoch: int,
            *,
            exclude_fields: set[str] | None = None,
        ) -> Awaitable[EvalSample | None]: ...

    # Sync accessor for one sample's transcript-event history by
    # ``(id, epoch)``, or None once the backing buffer is torn down.
    EventsProvider = Callable[[str | int, int], TranscriptHistoryProvider | None]

    # Async accessor for a reused eval's summaries-derived stats, resolved
    # lazily on first control request (see ``DeferredSampleStats``).
    DeferredStatsProvider = Callable[[], Awaitable["DeferredSampleStats"]]


class DeferredSampleStats(NamedTuple):
    """Summaries-derived stats for a reused eval, resolved lazily.

    A reused log's header is already parsed (eval-set reads it to decide
    reuse), but these fields require reading the per-sample summaries — a
    full log read that would otherwise run serially per reused log at
    eval-set startup, whether or not a control client ever connects.
    They're deferred behind :attr:`EvalState.deferred_sample_stats` and
    resolved (once, memoized) by the first ``current_eval_summaries`` call.
    """

    total_messages: int
    completed: int
    errored: int


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
    """Task name. Carried here so consumers (control channel `tasks`) can label
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

    sample_provider: SampleProvider | None = None
    """Live accessor for one full sample (``EvalSample``) from the recorder.
    The whole-sample analogue of :attr:`summaries_provider`: per-sample
    reads (error detail, event pages) prefer this gap-free source so they
    agree with the samples listing, falling back to the on-disk
    :attr:`log_location` when it's ``None`` (reused/synthetic eval) or the
    recorder no longer holds the sample (flushed / torn down)."""

    events_provider: EventsProvider | None = None
    """Live accessor for one sample's transcript-event history (a
    ``TranscriptHistoryProvider``) from the realtime buffer. The events
    analogue of :attr:`sample_provider`, for streaming-completion samples
    whose recorder copy is event-less (their events live in the buffer
    database): event pages read through the eval's own buffer instance
    rather than the control layer re-deriving the buffer's location.
    ``None`` for reused/synthetic evals; returns ``None`` once the buffer
    is torn down."""

    deferred_sample_stats: DeferredStatsProvider | None = None
    """Lazy accessor for a reused eval's summaries-derived stats
    (:class:`DeferredSampleStats`). Resolved once — on the first
    ``current_eval_summaries`` call — by
    :func:`resolve_deferred_sample_stats`, which overwrites
    :attr:`total_messages` / :attr:`completed` / :attr:`errored` and clears
    this field. Until then (and permanently, if the resolution read fails)
    those fields hold the header-derived provisional values set at
    registration. ``None`` for live evals."""

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
    def terminal(self) -> int:
        """Samples that reached a terminal outcome (completed/errored/cancelled).

        The single definition of the terminal sum — used by both
        :attr:`is_finished` and :func:`finalize_eval` so a future bucket
        can't be added to one and missed by the other.
        """
        return self.completed + self.errored + self.cancelled

    @property
    def is_finished(self) -> bool:
        """True once every sample has terminated (success, error, or cancel).

        A zero-sample eval is finished immediately: ``--limit`` can slice past
        the dataset (a valid, successful outcome), so ``total == 0`` must read
        as done (``0 >= 0``) rather than "running" forever. There's no spurious
        early-finish risk for ``total > 0`` — ``0 >= total`` is already False
        until enough samples terminate.
        """
        return self.terminal >= self.total


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
    sample_provider: SampleProvider | None = None,
    events_provider: EventsProvider | None = None,
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
            sample_provider=sample_provider,
            events_provider=events_provider,
            sample_ids=sample_ids or [],
            epochs=epochs,
            run_id=run_id,
            will_retry=will_retry,
        )
        _eval_states[eval_id] = state
        # A zero-sample eval (``total == 0``, eg. a limit past the dataset) is
        # already finished — no sample will ever run to fire a terminal counter
        # and stamp ``completed_at`` via record_sample_*, so do it now. A no-op
        # for the normal ``total > 0`` case (not yet finished at registration).
        _maybe_mark_finished(state)
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
    deferred_sample_stats: DeferredStatsProvider | None = None,
) -> EvalState:
    """Register an eval that has already finished.

    Used by ``eval_set`` to publish synthetic state for tasks whose
    successful logs were reused from a prior run — those tasks never
    enter ``task_run.py``, so the per-sample counter path that would
    normally maintain the state never fires. This bulk-equivalent
    sets the terminal counters up-front so ``current_eval_summaries``
    surfaces the eval as completed.

    ``completed`` / ``errored`` / ``total_messages`` may be provisional
    (header-derived) values refined later by ``deferred_sample_stats`` —
    see :class:`DeferredSampleStats`.

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
            deferred_sample_stats=deferred_sample_stats,
        )
        _eval_states[eval_id] = state
        return state


async def resolve_deferred_sample_stats(state: EvalState) -> None:
    """Resolve a reused eval's deferred summaries-derived stats (once).

    Claims the provider under the lock first, so concurrent requests perform
    at most one read (a loser briefly sees the provisional header-derived
    values — benign). Failure semantics by class:

    - Any ``Exception`` (unreadable or corrupt log — eg. ``BadZipFile``,
      storage backend errors): the provisional values stand permanently
      (they sum to ``total``, so the row still renders terminal) and the
      provider is not retried. The read must never fail the surrounding
      request, and a caught failure must never cancel sibling resolutions.
    - Cancellation (client disconnect / server teardown mid-read): the
      claim is restored so a later request retries the resolution, rather
      than stranding the row on provisional values forever.
    """
    with _lock:
        provider = state.deferred_sample_stats
        state.deferred_sample_stats = None
    if provider is None:
        return
    try:
        stats = await provider()
    except Exception as ex:
        logger.warning(
            "Could not resolve sample stats for reused eval %s (%s): %s",
            state.eval_id,
            state.log_location,
            ex,
        )
        return
    except BaseException:
        # cancelled mid-read — restore the claim for a later retry
        with _lock:
            if state.deferred_sample_stats is None:
                state.deferred_sample_stats = provider
        raise
    with _lock:
        state.total_messages = stats.total_messages
        state.completed = stats.completed
        state.errored = stats.errored


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


def detach_eval_providers(eval_id: str) -> None:
    """Null a superseded attempt's live providers.

    Called by ``TaskLogger.reinit()`` when a task retry re-points the (one,
    shared) logger at a fresh attempt: the superseded attempt's providers are
    bound methods of that logger, so left attached they would silently serve
    the *new* attempt's recorder/log/buffer data under the old attempt's
    eval_id. Detaching them makes the superseded attempt's reads fall back to
    its own ``log_location`` — its data stays correct until the retry sweep
    removes that log, after which per-sample reads degrade to empty/404
    (the counters on the state itself are unaffected). No-ops if the eval
    isn't registered.
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            state.summaries_provider = None
            state.sample_provider = None
            state.events_provider = None


def finalize_eval(eval_id: str) -> None:
    """Reconcile terminal counters when a task finishes.

    A sample cancelled while still *queued* (eg. parked at the sample
    semaphore when a sibling's failure tears the task group down) never
    reaches a per-sample terminal record — the cancellation propagates
    before its recording code runs, so ``completed + errored + cancelled``
    can fall short of ``total`` and the eval would read "running" forever.
    Called at the task's single finish point, after every sample task has
    exited: any planned sample still unaccounted for can no longer run in
    this attempt, so fold the shortfall into :attr:`EvalState.cancelled`
    (the existing bucket for teardown cancellations) and stamp
    ``completed_at``. A no-op when the counters already reached ``total``,
    and for unregistered evals (eg. ``run_samples=False``, which returns
    before registration).
    """
    with _lock:
        state = _eval_states.get(eval_id)
        if state is not None:
            shortfall = state.total - state.terminal
            if shortfall > 0:
                state.cancelled += shortfall
            _maybe_mark_finished(state)


def _maybe_mark_finished(state: EvalState) -> None:
    """Stamp ``completed_at`` when every sample has terminated.

    Fires the first time the terminal sum (``completed + errored +
    cancelled``) reaches ``total``; later updates are no-ops so a late
    counter update from a teardown race doesn't overwrite the original
    finish time. Also drops
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
