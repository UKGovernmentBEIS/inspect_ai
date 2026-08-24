"""Interim scoring pass for the control channel (design/ctl/interim-scoring.md).

Implements the non-destructive ``inspect ctl task score`` directive: run the
task's scorers (as resolved at eval start — see :class:`TaskScoring`) over
every scoreable sample of a running eval, compute interim metrics, and report
the results through a start + poll job model
(``POST``/``GET /tasks/<task-id>/score``).

Sample dispositions (the "Which samples" table of the design doc):

- **in-flight** samples are scored **pause-and-score**: each is briefly held
  at its next model call via a sample-keyed application of the hard-pause
  gate (:func:`inspect_ai._control.pause.hold_sample_for_scoring`), its
  then-stable live state scored handler-side against the handles published
  on the ``ActiveSample`` (live ``TaskState``, live ``Transcript``, sandbox
  environments), and released. Each held-state score is recorded as a
  ``ScoreEvent(intermediate=True)`` on the live transcript — exactly as
  task-authored ``score()`` records it — so it persists through the realtime
  sample buffer. A sample that neither parks nor quiesces within
  :data:`SCORE_HOLD_TIMEOUT` is reported un-scored, never scored while
  moving.
- **completed, unscored** samples are scored from their serialized form
  (the ``inspect score`` recipe applied mid-run, over a deep copy — the
  recorder's buffered sample is live log state and must not be mutated).
  Their scores appear in the result envelope only (injecting them into
  already-written log records mid-run would be a log mutation with no safe
  path).
- **completed, scored** samples are not re-scored; their existing final
  scores ride into the interim metrics.
- **errored** samples mirror the eval's resolved ``score_on_error`` flag;
  **cancelled** and not-yet-started samples are skipped.

The pass's scoring runs in child task contexts that deliberately do *not*
bind the sample (``sample_active()`` stays ``None``), which buys budget
isolation (grader calls can't spend a sample's limits) and hold escape (the
pass's own grader calls pass the sample-keyed hold and any task-scope hard
pause) structurally — see the design doc's "What the scoring context
deliberately does not bind".

Pass state is in-memory only (one pass per task at a time, keyed by the
stable task id); a task finish / retry / cancel tears a pass down and the
poll reports it as interrupted with whatever partial rows it produced.
"""

from __future__ import annotations

import functools
import time
from copy import deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

import anyio
from shortuuid import uuid

from inspect_ai._control.pause import (
    hold_sample_for_scoring,
    release_sample_scoring_hold,
    sample_parked_attempts,
)

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai.log._log import EvalSampleSummary
    from inspect_ai.log._samples import ActiveSample
    from inspect_ai.model import Model
    from inspect_ai.scorer import Metric, Scorer
    from inspect_ai.scorer._metric import SampleScore
    from inspect_ai.scorer._reducer import ScoreReducer

logger = getLogger(__name__)


# How long a pass waits for one in-flight sample to park at the hard-pause
# gate (and then quiesce) before reporting it un-scored. A constant to start
# (resolved open question 3 of design/ctl/interim-scoring.md); a sample mid
# long tool call, or in a solver phase with no model calls, times out here
# rather than wedging the pass.
SCORE_HOLD_TIMEOUT: float = 120.0

# Per-sample scoring deadline once a sample is held — a stuck scorer must
# not hold a parked sample indefinitely (the sample must always come back).
SCORE_SCORING_TIMEOUT: float = 600.0

# Concurrency cap for completed-sample scoring, so a large backlog can't
# starve the running eval (grader model calls are additionally governed by
# the process connection limits).
SCORE_COMPLETED_CONCURRENCY: int = 4

# Poll interval for the park ack and the terminal watch. The gate flips on
# the same event loop, so this bounds ack latency, not correctness.
_HOLD_POLL_INTERVAL: float = 0.1

# The quiescence settle window: after the park ack, the sample's transcript
# must record no new events across this window before the pass touches its
# live state. A parked single-branch solver is still by construction; a
# concurrent sibling branch between model calls presents no generate attempt
# to park, but its model/tool/span activity lands on the shared transcript —
# the non-generate activity signal the design doc's quiescence predicate
# calls for. A sample whose transcript never settles times out to the
# "did not park" row rather than being scored while moving.
_QUIESCE_SETTLE: float = 0.5


Disposition = Literal["in_flight", "completed_unscored", "completed_scored", "skipped"]
"""Which row of the design doc's dispositions table a sample fell into."""


@dataclass
class TaskScoring:
    """The task's scoring inputs as resolved at eval start.

    Published on the :class:`~inspect_ai._control.eval_state.EvalState` by
    the task runner (``set_task_scoring``) so the interim-scoring pass runs
    the task's *own* scorers and model roles — the task definition is fixed
    mid-flight (a control-channel non-goal).
    """

    scorers: "list[Scorer]"
    """The task's resolved scorers (empty when the task has none)."""

    scorer_names: "list[str]"
    """Unique scorer names, resolved once by the runner (parallel to
    :attr:`scorers`) so pass scores aggregate under the same names final
    scoring will use."""

    model: "Model"
    """The task's primary model (the scoring context's active model)."""

    model_roles: "dict[str, Model] | None"
    """The task's model roles (grader roles resolve through these)."""

    epochs_reducer: "ScoreReducer | list[ScoreReducer] | None"
    """The task's epoch reducers, for the interim metrics reduction."""

    metrics: "list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None"
    """The task's metrics (``None`` = each scorer's own)."""

    score_on_error: bool
    """The eval's resolved ``score_on_error`` flag — errored samples are
    interim-scored exactly when final scoring would score them."""


@dataclass
class ScorePass:
    """One interim-scoring pass (in-memory job state, task-keyed)."""

    pass_id: str
    task_id: str
    eval_id: str
    task: str
    as_of: float
    completed_only: bool
    running: bool = True
    total: int = 0
    """Samples this pass will attempt to score (progress denominator)."""
    scored: int = 0
    failed: int = 0
    targeted: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] | None = None
    interrupted: str | None = None
    error: str | None = None
    finished_at: float | None = None
    _task: Any = None
    """The asyncio task running the pass (cancelled at registry reset)."""


# One pass per task at a time, keyed by the stable task id (like the pause
# gates). Holds the most recent pass after it finishes so the poll can report
# it; reset at the outermost run boundary via reset_score_passes.
_score_passes: dict[str, ScorePass] = {}


def reset_score_passes() -> None:
    """Clear the pass registry, cancelling any still-running pass task.

    Called from ``reset_run_registries`` at the outermost run boundary so a
    pass task can't outlive the run whose state it closes over.
    """
    for score_pass in _score_passes.values():
        if score_pass._task is not None and not score_pass._task.done():
            score_pass._task.cancel()
    _score_passes.clear()


class _PassTargets:
    """The enumerated sample dispositions a pass acts on."""

    def __init__(self) -> None:
        self.in_flight: list[ActiveSample] = []
        self.completed_unscored: list[EvalSampleSummary] = []
        self.completed_scored: list[EvalSampleSummary] = []
        self.skipped_rows: list[dict[str, Any]] = []
        self.unaccounted: int = 0

    def counts(self, completed_only: bool) -> dict[str, int]:
        in_flight_skipped = len(self.in_flight) if completed_only else 0
        return {
            "in_flight": 0 if completed_only else len(self.in_flight),
            "completed_unscored": len(self.completed_unscored),
            "completed_scored": len(self.completed_scored),
            "skipped": len(self.skipped_rows) + self.unaccounted + in_flight_skipped,
        }


async def start_score_pass(
    task_id: str, *, dry_run: bool = False, completed_only: bool = False
) -> dict[str, Any] | None:
    """Start an interim-scoring pass (``POST /tasks/<task-id>/score``).

    Returns ``None`` when the task isn't in this process (the route 404s);
    ``{"ok": False, "error": ...}`` when the task has no scorers to run (the
    route maps it to a 409). One pass per task at a time: a start while one
    is running is the idempotent no-op (``changed: False`` with the running
    pass's id and progress), so a retrying agent never stacks passes.
    ``dry_run`` reports the targeted counts by disposition without scoring
    anything; ``completed_only`` skips the in-flight rows entirely (no
    holds) — the hold-free spelling for recurring polling.
    """
    import asyncio

    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None

    handle = state.task_scoring
    if handle is None or not handle.scorers:
        return {
            "ok": False,
            "error": (
                "task has no scorers to run in this process (the task was "
                "defined without scorers, ran with --no-score before "
                "interim scoring support, or is a reused log — use "
                "`inspect score` on its log instead)"
            ),
        }

    existing = _score_passes.get(state.task_id)
    if existing is not None and existing.running:
        return _already_running_envelope(existing, state, dry_run)

    targets = await _enumerate_targets(state, handle)

    # _enumerate_targets suspends (the recorder's summaries lock, or a log
    # read), so a concurrent start may have registered a pass meanwhile;
    # re-check before registering — everything from here to the registration
    # below is synchronous, so this closes the race. Without it the loser
    # becomes an orphan pass (invisible to GET / reset) sharing the popped-on-
    # release sample hold gates with the winner.
    existing = _score_passes.get(state.task_id)
    if existing is not None and existing.running:
        return _already_running_envelope(existing, state, dry_run)

    targeted = targets.counts(completed_only)

    score_pass = ScorePass(
        pass_id=uuid(),
        task_id=state.task_id,
        eval_id=state.eval_id,
        task=state.task,
        as_of=time.time(),
        completed_only=completed_only,
        targeted=targeted,
        total=len(targets.completed_unscored)
        + (0 if completed_only else len(targets.in_flight)),
    )

    if dry_run:
        return {
            **_pass_envelope_base(score_pass, state),
            "changed": True,
            "dry_run": True,
            "targeted": targeted,
        }

    _score_passes[state.task_id] = score_pass
    # the control server runs uvicorn on the eval's asyncio loop, so the
    # pass runs as a sibling asyncio task on that loop (the recipe the
    # server itself uses); reset_score_passes cancels it at the run boundary.
    # Spawned in a FRESH context, not a copy of the caller's: the design's
    # budget-isolation / hold-escape properties require the pass context to
    # bind no sample, which a copy would silently break if a start were ever
    # issued from in-sample code (Context().run makes the task's captured
    # context the empty one — portable, unlike create_task's context kwarg).
    import contextvars

    score_pass._task = contextvars.Context().run(
        asyncio.ensure_future, run_score_pass(score_pass, state, handle, targets)
    )
    return {
        **_pass_envelope_base(score_pass, state),
        "changed": True,
        "dry_run": False,
        "targeted": targeted,
    }


async def get_score_pass(task_id: str) -> dict[str, Any] | None:
    """Report the current (or most recent) pass (``GET /tasks/<task-id>/score``).

    Returns ``None`` when the task isn't in this process; ``{"ok": False,
    "error": ...}`` when no pass has been started (the route maps it to a
    404 with that message). Once the pass completes (or is interrupted) the
    response carries the per-sample rows and interim metrics under
    ``result``.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None:
        return None
    score_pass = _score_passes.get(state.task_id)
    if score_pass is None:
        return {
            "ok": False,
            "error": "no scoring pass has been started for this task",
        }
    response: dict[str, Any] = {
        **_pass_envelope_base(score_pass, state),
        "progress": _pass_progress(score_pass),
    }
    if not score_pass.running:
        response["result"] = {
            "counts": score_pass.targeted,
            "samples": score_pass.rows,
            "metrics": score_pass.metrics,
            # interim everywhere it surfaces: epochs may be incomplete and
            # in-flight scores describe a held moment
            "interim": True,
            "epochs": state.epochs,
        }
        if score_pass.interrupted is not None:
            response["interrupted"] = score_pass.interrupted
        if score_pass.error is not None:
            response["error"] = score_pass.error
    return response


def _already_running_envelope(
    existing: ScorePass, state: "EvalState", dry_run: bool
) -> dict[str, Any]:
    """The idempotent no-op response for a start while a pass is running."""
    return {
        **_pass_envelope_base(existing, state),
        "changed": False,
        "dry_run": dry_run,
        "reason": "a scoring pass is already running for this task",
        "progress": _pass_progress(existing),
    }


def _pass_envelope_base(score_pass: ScorePass, state: "EvalState") -> dict[str, Any]:
    return {
        "ok": True,
        "task_id": state.task_id,
        "task": state.task,
        "eval_id": score_pass.eval_id,
        "pass_id": score_pass.pass_id,
        "running": score_pass.running,
        "as_of": score_pass.as_of,
        "completed_only": score_pass.completed_only,
    }


def _pass_progress(score_pass: ScorePass) -> dict[str, int]:
    return {
        "scored": score_pass.scored,
        "failed": score_pass.failed,
        "total": score_pass.total,
    }


# ---------------------------------------------------------------------------
# Target enumeration
# ---------------------------------------------------------------------------


async def _enumerate_targets(state: "EvalState", handle: TaskScoring) -> _PassTargets:
    """Classify the eval's samples into pass dispositions.

    Completed records come from the live recorder (gap-free, ahead of disk)
    with the finalized on-disk log as fallback — the same running-vs-terminal
    split every control read makes; in-flight samples from the process's
    active-sample registry. A retried sample can appear in both (the prior
    errored attempt's record plus the live re-run) — the live row wins.
    """
    from inspect_ai._util.error import is_cancellation_message
    from inspect_ai.log._samples import active_samples

    targets = _PassTargets()

    targets.in_flight = [
        a
        for a in active_samples()
        if a.eval_id == state.eval_id
        and a.started is not None
        and a.completed is None
        and a.interrupt_action is None
    ]
    in_flight_keys = {(str(a.sample.id), a.epoch) for a in targets.in_flight}

    accounted = len(targets.in_flight)
    for summary in await _completed_summaries(state):
        if (str(summary.id), summary.epoch) in in_flight_keys:
            continue
        # a record that is neither completed nor errored isn't terminal
        # (eg. an in-progress row from a log read) — leave it unaccounted
        if summary.error is None and not summary.completed:
            continue
        accounted += 1
        cancelled = summary.error is not None and is_cancellation_message(summary.error)
        scoreable = summary.error is None or (not cancelled and handle.score_on_error)
        if not scoreable:
            targets.skipped_rows.append(
                _row(
                    summary.id,
                    summary.epoch,
                    "skipped",
                    outcome="skipped",
                    reason=(
                        "cancelled samples are never scored"
                        if cancelled
                        else "errored sample and score_on_error is off"
                    ),
                )
            )
        elif summary.scores:
            targets.completed_scored.append(summary)
        else:
            targets.completed_unscored.append(summary)

    # queued / pending samples are skipped without individual rows (the
    # counters, not the row list, are authoritative for totals)
    targets.unaccounted = max(0, state.total - accounted)
    return targets


async def _completed_summaries(state: "EvalState") -> "list[EvalSampleSummary]":
    """The eval's completed-sample summaries (recorder, else on-disk log)."""
    if state.live is not None:
        summaries = await state.live.sample_summaries()
        if summaries is not None:
            return summaries
    if state.log_sample_summaries is not None:
        return state.log_sample_summaries
    if state.log_location:
        from inspect_ai.log._file import read_eval_log_sample_summaries_async

        try:
            return await read_eval_log_sample_summaries_async(state.log_location)
        except FileNotFoundError:
            return []
    return []


def _row(
    sample_id: str | int,
    epoch: int,
    disposition: Disposition,
    *,
    outcome: str,
    reason: str | None = None,
    scores: "dict[str, SampleScore] | None" = None,
    scorer_errors: dict[str, str] | None = None,
    held_seconds: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "disposition": disposition,
        "outcome": outcome,
        "scores": {
            name: sample_score.score.value for name, sample_score in scores.items()
        }
        if scores
        else {},
    }
    if reason is not None:
        row["reason"] = reason
    if scorer_errors:
        row["scorer_errors"] = scorer_errors
    if held_seconds is not None:
        row["held_seconds"] = round(held_seconds, 3)
    return row


# ---------------------------------------------------------------------------
# The pass runner
# ---------------------------------------------------------------------------


async def run_score_pass(
    score_pass: ScorePass,
    state: "EvalState",
    handle: TaskScoring,
    targets: _PassTargets,
) -> None:
    """Run one scoring pass to completion (the start directive spawns this).

    Completed-unscored samples are scored concurrently under a small cap;
    in-flight samples are held and scored strictly one at a time. Per-sample
    scorer failures land on the row and don't fail the pass; the pass ends
    by computing interim metrics over the union of existing final scores and
    the pass's fresh scores.
    """
    from inspect_ai._util._async import tg_collect
    from inspect_ai.scorer._metric import SampleScore

    metric_scores: list[dict[str, SampleScore]] = []
    try:
        # existing final scores ride into the interim metrics un-re-scored
        for summary in targets.completed_scored:
            existing = {
                name: SampleScore(
                    score=score,
                    sample_id=summary.id,
                    sample_metadata=summary.metadata or None,
                )
                for name, score in (summary.scores or {}).items()
            }
            metric_scores.append(existing)
            score_pass.rows.append(
                _row(
                    summary.id,
                    summary.epoch,
                    "completed_scored",
                    outcome="existing",
                    scores=existing,
                )
            )
        score_pass.rows.extend(targets.skipped_rows)

        # completed-unscored samples, concurrently under a small cap
        cap = anyio.Semaphore(SCORE_COMPLETED_CONCURRENCY)

        async def score_completed(summary: "EvalSampleSummary") -> None:
            async with cap:
                row, scores = await _score_serialized_sample(state, handle, summary)
            _record(score_pass, metric_scores, row, scores)

        if targets.completed_unscored:
            # tg_collect children get their own context copies, so each
            # sample's scoring context bindings stay isolated
            await tg_collect(
                functools.partial(score_completed, summary)
                for summary in targets.completed_unscored
            )

        # in-flight samples: held and scored one at a time (never the whole
        # task at once)
        if not score_pass.completed_only:
            for active in targets.in_flight:
                if _pass_superseded(state):
                    score_pass.interrupted = (
                        "task finished or was retried during the pass"
                    )
                    break
                row, scores = await _score_held_sample(state, handle, active)
                _record(score_pass, metric_scores, row, scores)

        # interim metrics over the union (the same machinery final scoring
        # and the live display use)
        if metric_scores:
            from inspect_ai._eval.task.results import eval_results

            results, _ = eval_results(
                samples=len(metric_scores),
                scores=metric_scores,
                reducers=handle.epochs_reducer,
                scorers=handle.scorers,
                metrics=handle.metrics,
                scorer_names=handle.scorer_names,
            )
            score_pass.metrics = [
                {
                    "scorer": score.name,
                    "reducer": score.reducer,
                    "metrics": {
                        key: metric.value for key, metric in score.metrics.items()
                    },
                }
                for score in results.scores
            ]
    except anyio.get_cancelled_exc_class():
        score_pass.interrupted = "the pass was cancelled"
        raise
    except Exception as ex:
        logger.warning(
            "Interim scoring pass %s failed", score_pass.pass_id, exc_info=True
        )
        score_pass.error = f"{type(ex).__name__}: {ex}"
    finally:
        score_pass.running = False
        score_pass.finished_at = time.time()


def _record(
    score_pass: ScorePass,
    metric_scores: "list[dict[str, SampleScore]]",
    row: dict[str, Any],
    scores: "dict[str, SampleScore] | None",
) -> None:
    score_pass.rows.append(row)
    if scores:
        metric_scores.append(scores)
        score_pass.scored += 1
    else:
        score_pass.failed += 1


def _pass_superseded(state: "EvalState") -> bool:
    """Whether the pass's attempt is no longer current (finish, retry, cancel).

    Checked between held samples: a pass outlives nothing — a task that
    finished, was superseded by a retry, or has a cancel in flight must not
    have further samples held. (A finished-but-parked eval under
    ``--ctl-server=keep`` is still scoreable — its pass has no in-flight
    samples, so this check never fires for it.)
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    if state.completed_at is not None or state.live is None:
        return True
    if state.task_cancel is not None and state.task_cancel.cancel_type is not None:
        return True
    return latest_eval_for_task(state.task_id) is not state


# ---------------------------------------------------------------------------
# Completed samples (handler-side, from the serialized form)
# ---------------------------------------------------------------------------


async def _score_serialized_sample(
    state: "EvalState", handle: TaskScoring, summary: "EvalSampleSummary"
) -> "tuple[dict[str, Any], dict[str, SampleScore] | None]":
    """Score one completed sample from its serialized form.

    The ``inspect score`` recipe applied mid-run: rebuild a ``TaskState``
    from the sample's ``EvalSample`` (sourced from the live recorder, else
    the on-disk log) and run the task's scorers over it. Operates on a deep
    copy — the recorder's buffered sample is live log state. Scores land in
    the envelope only (see the module docstring).
    """
    from inspect_ai._control.state import _full_sample

    disposition: Disposition = "completed_unscored"
    sample = await _full_sample(state.eval_id, str(summary.id), summary.epoch)
    if sample is None:
        return (
            _row(
                summary.id,
                summary.epoch,
                disposition,
                outcome="failed",
                reason="sample is not readable from the recorder or log",
            ),
            None,
        )

    from inspect_ai.log._condense import resolve_sample_attachments
    from inspect_ai.log._resolve import rebind_sample_timelines
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model import ModelName
    from inspect_ai.solver import TaskState

    # deep copy before touching: the recorder's buffered sample (and the
    # memoized log read) are shared, still-to-be-written state
    sample = deepcopy(sample)
    if sample.attachments:
        sample = resolve_sample_attachments(sample)
        sample = rebind_sample_timelines(sample)

    target = _target(sample.target)
    task_state = TaskState(
        model=ModelName(handle.model),
        sample_id=sample.id,
        epoch=sample.epoch,
        input=sample.input,
        target=target,
        choices=sample.choices,
        messages=sample.messages,
        output=sample.output,
        completed=True,
        metadata=sample.metadata,
        store=sample.store,
        scores={},
        sample_uuid=sample.uuid,
    )

    _init_pass_scoring_context(handle, target)
    from inspect_ai.util._store import init_subtask_store

    init_subtask_store(task_state.store)
    # a throwaway transcript: scorers may read events / timelines, but
    # nothing recorded here persists (envelope-only scores)
    init_transcript(Transcript([*sample.events], log_model_api=False, bounded=False))
    for timeline in sample.timelines or []:
        transcript().add_timeline(timeline)

    scores: "dict[str, SampleScore]" = {}
    errors: dict[str, str] = {}
    await _apply_scorers(
        handle, task_state, target, record=False, scores=scores, errors=errors
    )
    return (
        _row(
            summary.id,
            summary.epoch,
            disposition,
            outcome="scored" if scores else "failed",
            scores=scores,
            scorer_errors=errors,
        ),
        scores or None,
    )


# ---------------------------------------------------------------------------
# In-flight samples (pause-and-score)
# ---------------------------------------------------------------------------


async def _score_held_sample(
    state: "EvalState", handle: TaskScoring, active: "ActiveSample"
) -> "tuple[dict[str, Any], dict[str, SampleScore] | None]":
    """Hold one in-flight sample, score its stable live state, release it.

    Park, then score: the pass touches the sample's live state only between
    the park ack (plus a quiescence settle over its transcript) and the
    release. The hold is bounded (:data:`SCORE_HOLD_TIMEOUT` for the park,
    :data:`SCORE_SCORING_TIMEOUT` for the scoring), and sample completion /
    interrupt / limit during any phase yields to the sample — its final
    score supersedes.
    """
    sample_id = active.sample.id
    assert sample_id is not None
    disposition: Disposition = "in_flight"
    hold_start = time.monotonic()

    def superseded_row() -> dict[str, Any]:
        return _row(
            sample_id,
            active.epoch,
            disposition,
            outcome="superseded",
            reason="completed before interim scoring finished",
            held_seconds=time.monotonic() - hold_start,
        )

    hold_sample_for_scoring(active.id)
    try:
        # wait-for-park ack: the sample's next generate attempt parks at the
        # sample-keyed gate; a sample mid tool call parks when it ends
        deadline = hold_start + SCORE_HOLD_TIMEOUT
        while sample_parked_attempts(state.task_id, active.id) == 0:
            if _sample_terminal(active):
                return superseded_row(), None
            if time.monotonic() >= deadline:
                return (
                    _row(
                        sample_id,
                        active.epoch,
                        disposition,
                        outcome="did_not_park",
                        reason=(
                            "sample did not park at a model call within the "
                            "hold timeout (a long tool call, or a solver "
                            "phase with no model calls)"
                        ),
                        held_seconds=time.monotonic() - hold_start,
                    ),
                    None,
                )
            await anyio.sleep(_HOLD_POLL_INTERVAL)

        # quiescence settle: no transcript activity across the window (a
        # concurrent solver branch between model calls presents no generate
        # attempt to park, but its activity lands on the shared transcript)
        while True:
            event_count = len(active.transcript.events)
            await anyio.sleep(_QUIESCE_SETTLE)
            if _sample_terminal(active):
                return superseded_row(), None
            if (
                len(active.transcript.events) == event_count
                and sample_parked_attempts(state.task_id, active.id) > 0
            ):
                break
            if time.monotonic() >= deadline:
                return (
                    _row(
                        sample_id,
                        active.epoch,
                        disposition,
                        outcome="did_not_park",
                        reason=(
                            "sample kept producing activity while held (a "
                            "concurrent solver branch) — not scored, to "
                            "avoid reading a moving state"
                        ),
                        held_seconds=time.monotonic() - hold_start,
                    ),
                    None,
                )

        # score the held (stable) live state, yielding to the sample and
        # bounding a stuck scorer; scores land in these dicts per-scorer, so
        # a cancellation keeps whatever finished before it
        scores: "dict[str, SampleScore]" = {}
        errors: dict[str, str] = {}
        superseded = False
        timed_out = False
        with anyio.move_on_after(SCORE_SCORING_TIMEOUT) as scope:
            async with anyio.create_task_group() as tg:

                async def watch() -> None:
                    nonlocal superseded
                    while not _sample_terminal(active):
                        await anyio.sleep(_HOLD_POLL_INTERVAL)
                    superseded = True
                    tg.cancel_scope.cancel()

                async def run_scorers() -> None:
                    # a child task: its context copy keeps the scoring
                    # bindings isolated from the pass (and the watcher)
                    try:
                        await _score_live_sample(handle, active, scores, errors)
                    finally:
                        tg.cancel_scope.cancel()

                tg.start_soon(watch)
                tg.start_soon(run_scorers)
        timed_out = scope.cancelled_caught

        if superseded and not scores:
            return superseded_row(), None
        if timed_out:
            errors[""] = "per-sample scoring deadline elapsed"
        return (
            _row(
                sample_id,
                active.epoch,
                disposition,
                outcome="scored" if scores else "failed",
                scores=scores,
                scorer_errors=errors,
                held_seconds=time.monotonic() - hold_start,
            ),
            dict(scores) or None,
        )
    finally:
        release_sample_scoring_hold(active.id)


def _sample_terminal(active: "ActiveSample") -> bool:
    return (
        active.completed is not None
        or active.interrupt_action is not None
        or active.limit_exceeded_error is not None
    )


async def _score_live_sample(
    handle: TaskScoring,
    active: "ActiveSample",
    scores: "dict[str, SampleScore]",
    errors: dict[str, str],
) -> None:
    """Run the task's scorers over a held sample's live state.

    Binds the pass's scoring context — the live transcript (so each score is
    recorded as ``ScoreEvent(intermediate=True)`` exactly as task-authored
    ``score()`` records it, and flows through the realtime buffer), the live
    store, and the sample's sandbox environments (so sandbox-inspecting
    scorers work) — but deliberately not the sample itself:
    ``sample_active()`` stays ``None``, so grader calls neither spend the
    sample's limits nor park at the sample-keyed hold.
    """
    from inspect_ai.log._transcript import init_transcript
    from inspect_ai.util._sandbox.context import sandbox_environments_context_var
    from inspect_ai.util._store import init_subtask_store

    live_state = active.live_state
    if live_state is None:
        errors[""] = "sample has no live state to score yet"
        return

    target = _target(active.sample.target)
    _init_pass_scoring_context(handle, target)
    init_transcript(active.transcript)
    init_subtask_store(live_state.store)
    if active.sandbox_environments:
        sandbox_environments_context_var.set(active.sandbox_environments)

    # the caller's dicts, filled incrementally: a scoring deadline (or the
    # sample completing) mid-run keeps the scorers that already finished
    await _apply_scorers(
        handle, live_state, target, record=True, scores=scores, errors=errors
    )


# ---------------------------------------------------------------------------
# Shared scoring helpers
# ---------------------------------------------------------------------------


def _target(value: Any) -> Any:
    from inspect_ai.scorer import Target

    return Target(value)


def _init_pass_scoring_context(handle: TaskScoring, target: Any) -> None:
    """Bind the pass's task/scoring context (model, roles, scorers, target).

    The same bindings ``inspect score`` sets up handler-side, minus any
    sample binding — see :func:`_score_live_sample`.
    """
    from inspect_ai._eval.context import init_task_context
    from inspect_ai.scorer._score import init_scoring_context

    init_task_context(handle.model, handle.model_roles)
    init_scoring_context(handle.scorers, target)


async def _apply_scorers(
    handle: TaskScoring,
    task_state: Any,
    target: Any,
    *,
    record: bool,
    scores: "dict[str, SampleScore]",
    errors: dict[str, str],
) -> None:
    """Run the task's scorers over ``task_state``, collecting per-scorer results.

    Per-scorer failures are collected (not raised) so one scorer's error
    doesn't lose its siblings' scores. Results land in the caller's
    ``scores``/``errors`` dicts as each scorer finishes, so a cancellation
    mid-run (the per-sample scoring deadline, or the sample completing)
    keeps the scorers that had already returned. ``record`` controls whether
    each score is recorded on the current transcript as an intermediate
    event.
    """
    from inspect_ai._util.registry import (
        has_registry_params,
        registry_params,
        registry_unqualified_name,
    )
    from inspect_ai.event._score import ScoreEvent
    from inspect_ai.log._transcript import transcript
    from inspect_ai.scorer._metric import SampleScore

    for scorer, scorer_name in zip(handle.scorers, handle.scorer_names):
        try:
            result = await scorer(task_state, target)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as ex:
            errors[scorer_name] = f"{type(ex).__name__}: {ex}"
            continue
        if result is None:
            continue
        if record:
            transcript()._event(
                ScoreEvent(
                    score=result,
                    target=target.target,
                    intermediate=True,
                    scorer=scorer_name,
                    scorer_args=registry_params(scorer)
                    if has_registry_params(scorer)
                    else None,
                )
            )
        scores[scorer_name] = SampleScore(
            score=result,
            sample_id=task_state.sample_id,
            sample_metadata=task_state.metadata,
            scorer=registry_unqualified_name(scorer),
        )
