"""Interim scoring pass for the control channel (design/ctl/interim-scoring.md).

Implements the non-destructive ``inspect ctl task score`` directive: run the
task's scorers (as resolved at eval start — see :class:`TaskScoring`) over
a running eval's in-flight samples, fold completed samples' existing final
scores into interim metrics, and report the results through a start + poll
job model (``POST``/``GET /tasks/<task-id>/score``).

Sample dispositions (the "Which samples" table of the design doc):

- **in-flight** samples are scored **pause-and-score**: each is briefly held
  at its next model call via a sample-keyed application of the hard-pause
  gate (:func:`inspect_ai._control.pause.hold_sample_for_scoring`), its
  then-stable live state scored handler-side against the handles published
  on the ``ActiveSample`` (live ``TaskState``, live ``Transcript``, sandbox
  environments), and released. Each held-state score is recorded as a
  ``ScoreEvent(intermediate=True)`` on the live transcript — as task-authored
  ``score()`` records it — so it persists through the realtime sample
  buffer. A sample that neither parks nor quiesces within
  :data:`SCORE_HOLD_TIMEOUT` is reported un-scored, never scored while
  moving.
- **completed, scored** samples are not re-scored; their existing final
  scores ride into the interim metrics.
- **completed, unscored** samples (a scorer previously errored) are *not*
  scored by the pass — they get a skip row pointing at post-run
  ``inspect score``. Mid-run re-scoring from the serialized form was
  removed: it carried most of the feature's risk (deep copies on the eval
  loop, long pass windows) for a population that is near-empty on normal
  runs, and its envelope-only scores were re-bought on every pass.
- **errored** samples mirror the eval's resolved ``score_on_error`` flag
  for classification; **cancelled** and not-yet-started samples are skipped.

The pass's scoring runs in child task contexts that deliberately do *not*
bind the sample (``sample_active()`` stays ``None``), which buys budget
isolation (grader calls can't spend a sample's limits) and hold escape (the
pass's own grader calls pass the sample-keyed hold and any task-scope hard
pause) structurally — see the design doc's "What the scoring context
deliberately does not bind".

Pass state is in-memory only (one pass per task at a time, keyed by the
stable task id); a task finish / retry / cancel tears a pass down
(:func:`cancel_score_pass` at the attempt boundary, the between-samples
supersede check while running) and the poll reports it as interrupted with
whatever partial rows it produced.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Literal, NamedTuple

import anyio
from shortuuid import uuid

from inspect_ai._control.pause import (
    discard_park_waiter,
    hold_sample_for_scoring,
    release_sample_scoring_hold,
    sample_park_waiter,
    sample_parked_attempts,
)

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai.log._log import EvalSampleSummary
    from inspect_ai.log._samples import ActiveSample
    from inspect_ai.model import GenerateConfig, Model
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
# not hold a parked sample indefinitely (the sample must always come back),
# nor wedge the pass: with one pass per task at a time, an unbounded scorer
# would disable the directive for the rest of the attempt.
SCORE_SCORING_TIMEOUT: float = 600.0

# The quiescence settle window: after the park ack, the sample's transcript
# must record no new events across this window — and carry no pending
# events — before the pass touches its live state. A parked single-branch
# solver is still by construction; a concurrent sibling branch between model
# calls presents no generate attempt to park, but its model/tool/span
# activity lands on the shared transcript — the non-generate activity signal
# the design doc's quiescence predicate calls for. The pending-events check
# covers silent in-flight work the event count can't see: a ToolEvent is
# emitted (pending) at call *start*, so a sibling branch mid tool call adds
# no new events across the window yet is about to mutate the shared
# TaskState with its result. (Parked generate attempts themselves have no
# pending event — the gate is awaited before the attempt's ModelEvent is
# created.) A sample whose transcript never settles times out to the
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

    model_roles: "dict[str, Model | list[Model]] | None"
    """The task's model roles (grader roles resolve through these)."""

    generate_config: "GenerateConfig"
    """The eval's resolved generate config, bound as the scoring context's
    active config so interim grader calls run under the same settings final
    scoring will use (rather than a default ``GenerateConfig``, which could
    make interim model-graded scores systematically disagree)."""

    epochs_reducer: "ScoreReducer | list[ScoreReducer] | None"
    """The task's epoch reducers, for the interim metrics reduction."""

    metrics: "list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None"
    """The task's metrics (``None`` = each scorer's own)."""

    score_on_error: bool
    """The eval's resolved ``score_on_error`` flag — errored samples are
    classified as scoreable exactly when final scoring would score them."""


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
    """Samples this pass will attempt to score (progress denominator) —
    the in-flight samples (completed samples are never scored by a pass)."""
    scored: int = 0
    failed: int = 0
    """Samples whose scoring was attempted and produced no scores (scorer
    errors) — distinct from :attr:`unscored`."""
    unscored: int = 0
    """In-flight samples the pass never scored — they completed on their own
    mid-hold (``superseded``) or never parked (``did_not_park``). Nothing
    failed for these, so they get their own progress bucket."""
    targeted: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] | None = None
    interrupted: str | None = None
    error: str | None = None
    _task: Any = None
    """The asyncio task running the pass (cancelled at registry reset and
    when the attempt it belongs to is superseded — see cancel_score_pass)."""


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


def cancel_score_pass(task_id: str, eval_id: str) -> None:
    """Cancel a running pass whose attempt has been superseded.

    Called from ``detach_eval_live`` at the retry boundary: a pass started
    under the superseded attempt must not keep running against its dead
    recorder — and, via the one-pass-per-task guard, must not block
    ``ctl task score`` against the new attempt until it drains. The
    cancelled pass reports itself interrupted ("the pass was cancelled")
    with whatever partial rows it produced. No-op when the task's current
    pass belongs to a different attempt or isn't running.
    """
    score_pass = _score_passes.get(task_id)
    if (
        score_pass is not None
        and score_pass.running
        and score_pass.eval_id == eval_id
        and score_pass._task is not None
        and not score_pass._task.done()
    ):
        score_pass._task.cancel()
        # mark the pass interrupted eagerly: cancellation lands at the
        # task's next scheduling point — or never, for a task cancelled
        # before its first run, whose finally would then never fire — and
        # neither the poll nor the one-pass guard may keep reporting a
        # superseded pass as running in the meantime
        score_pass.running = False
        if score_pass.interrupted is None:
            score_pass.interrupted = "the pass was cancelled (attempt superseded)"


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
    holds, and — since completed samples are never re-scored — no grader
    calls at all): interim metrics over existing final scores, the free
    spelling for recurring polling.
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
                "defined without scorers, the eval ran with --no-score — "
                "which disables interim scoring too — or is a reused log; "
                "use `inspect score` on its log after the run instead)"
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
    total = 0 if completed_only else len(targets.in_flight)

    if dry_run:
        # a dry run registers nothing: no ScorePass is even constructed, so
        # the envelope reports nothing running and no pass id — a follow-up
        # poll would never find one
        return {
            "ok": True,
            "task_id": state.task_id,
            "task": state.task,
            "eval_id": state.eval_id,
            "running": False,
            "as_of": time.time(),
            "completed_only": completed_only,
            "changed": True,
            "dry_run": True,
            "targeted": targeted,
        }

    score_pass = ScorePass(
        pass_id=uuid(),
        task_id=state.task_id,
        eval_id=state.eval_id,
        task=state.task,
        as_of=time.time(),
        completed_only=completed_only,
        targeted=targeted,
        total=total,
    )
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
        "unscored": score_pass.unscored,
        "total": score_pass.total,
    }


# ---------------------------------------------------------------------------
# Target enumeration
# ---------------------------------------------------------------------------


async def _enumerate_targets(state: "EvalState", handle: TaskScoring) -> _PassTargets:
    """Classify the eval's samples into pass dispositions.

    Completed records come from the live recorder (gap-free, ahead of disk)
    with the finalized on-disk log as fallback — the same running-vs-terminal
    split every control read makes (the shared
    ``completed_eval_sample_summaries`` helper); in-flight samples from the
    process's active-sample registry. A retried sample can appear in both
    (the prior errored attempt's record plus the live re-run) — the live row
    wins.
    """
    from inspect_ai._control.state import completed_eval_sample_summaries
    from inspect_ai._util.error import is_cancellation_message
    from inspect_ai.log._samples import active_samples

    targets = _PassTargets()

    targets.in_flight = [
        a
        for a in active_samples()
        if a.eval_id == state.eval_id
        and a.started is not None
        and not _sample_terminal(a)
    ]
    in_flight_keys = {(str(a.sample.id), a.epoch) for a in targets.in_flight}

    accounted = len(targets.in_flight)
    for summary in await completed_eval_sample_summaries(state):
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

    In-flight samples are held and scored strictly one at a time; completed
    samples are never scored (their existing final scores fold into the
    interim metrics, and unscored ones get a skip row pointing at post-run
    ``inspect score``). Per-sample scorer failures land on the row and don't
    fail the pass; the pass ends by computing interim metrics over the union
    of existing final scores and the pass's fresh held-state scores.
    """
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
        # completed-unscored samples are not scored mid-run (see the module
        # docstring) — report them so the operator knows the metrics exclude
        # them and where their scores come from
        for summary in targets.completed_unscored:
            score_pass.rows.append(
                _row(
                    summary.id,
                    summary.epoch,
                    "completed_unscored",
                    outcome="skipped",
                    reason=(
                        "unscored completed sample — use `inspect score` on "
                        "the log after the run"
                    ),
                )
            )
        score_pass.rows.extend(targets.skipped_rows)

        # in-flight samples: held and scored one at a time (never the whole
        # task at once)
        if not score_pass.completed_only:
            for active in targets.in_flight:
                if _pass_superseded(state):
                    score_pass.interrupted = (
                        "task finished or was retried during the pass"
                    )
                    break
                result = await _score_held_sample(state, handle, active)
                _record(score_pass, metric_scores, result.row, result.scores)

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
        # cancel_score_pass may already have stamped a more specific reason
        if score_pass.interrupted is None:
            score_pass.interrupted = "the pass was cancelled"
        raise
    except Exception as ex:
        logger.warning(
            "Interim scoring pass %s failed", score_pass.pass_id, exc_info=True
        )
        score_pass.error = f"{type(ex).__name__}: {ex}"
    finally:
        score_pass.running = False


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
    elif row.get("outcome") in ("superseded", "did_not_park", "unscored"):
        # not a failure: the sample completed on its own, never parked, or
        # every scorer declined to score it — `failed` stays a count of
        # genuine scoring failures
        score_pass.unscored += 1
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
# In-flight samples (pause-and-score)
# ---------------------------------------------------------------------------


class _SampleScoreResult(NamedTuple):
    """One held sample's scoring outcome.

    The sample's result row plus the scores (``None`` when nothing was
    scored) that feed the interim metrics.
    """

    row: dict[str, Any]
    scores: "dict[str, SampleScore] | None"


async def _score_held_sample(
    state: "EvalState", handle: TaskScoring, active: "ActiveSample"
) -> _SampleScoreResult:
    """Hold one in-flight sample, score its stable live state, release it.

    Park, then score: the pass touches the sample's live state only between
    the park ack (plus a quiescence settle over its transcript) and the
    release. The hold is bounded (:data:`SCORE_HOLD_TIMEOUT` for the park,
    :data:`SCORE_SCORING_TIMEOUT` for the scoring), and sample completion /
    interrupt / limit during any phase yields to the sample — its final
    score supersedes. Both waits are event-driven (the gate's park waiter
    and the sample's terminal event) rather than polled.
    """
    sample_id = active.sample.id
    assert sample_id is not None
    disposition: Disposition = "in_flight"
    hold_start = time.monotonic()

    def held_row(
        outcome: str,
        *,
        reason: str | None = None,
        scores: "dict[str, SampleScore] | None" = None,
        scorer_errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert sample_id is not None
        return _row(
            sample_id,
            active.epoch,
            disposition,
            outcome=outcome,
            reason=reason,
            scores=scores,
            scorer_errors=scorer_errors,
            held_seconds=time.monotonic() - hold_start,
        )

    def superseded_result() -> _SampleScoreResult:
        return _SampleScoreResult(
            held_row("superseded", reason="completed before interim scoring finished"),
            None,
        )

    hold_sample_for_scoring(active.id)
    try:
        deadline = hold_start + SCORE_HOLD_TIMEOUT
        # wait-for-park ack: the sample's next generate attempt parks at the
        # sample-keyed gate (a sample mid tool call parks when it ends); wake
        # on the gate's park signal or the sample's terminal event, bounded
        # by the hold deadline — the loop re-checks its predicates on wake
        while sample_parked_attempts(state.task_id, active.id) == 0:
            if _sample_terminal(active):
                return superseded_result()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _SampleScoreResult(
                    held_row(
                        "did_not_park",
                        reason=(
                            "sample did not park at a model call within the "
                            "hold timeout (a long tool call, or a solver "
                            "phase with no model calls)"
                        ),
                    ),
                    None,
                )
            parked = sample_park_waiter(active.id)
            try:
                await _wait_for_park_or_terminal(parked, active, remaining)
            finally:
                discard_park_waiter(active.id, parked)

        # quiescence settle: no new transcript events across the window and
        # no pending events (see the _QUIESCE_SETTLE note for why both)
        while True:
            event_count = len(active.transcript.events)
            await anyio.sleep(_QUIESCE_SETTLE)
            if _sample_terminal(active):
                return superseded_result()
            if (
                len(active.transcript.events) == event_count
                and not active.transcript.pending_events
                and sample_parked_attempts(state.task_id, active.id) > 0
            ):
                break
            if time.monotonic() >= deadline:
                return _SampleScoreResult(
                    held_row(
                        "did_not_park",
                        reason=(
                            "sample kept producing activity while held (a "
                            "concurrent solver branch, or a tool call still "
                            "in flight) — not scored, to avoid reading a "
                            "moving state"
                        ),
                    ),
                    None,
                )

        # score the held (stable) live state, yielding to the sample and
        # bounding a stuck scorer; scores land in these dicts per-scorer, so
        # a cancellation keeps whatever finished before it. Pass-level (non-
        # scorer) failures travel on the row's `reason` field — `scorer_errors`
        # is keyed by scorer name only.
        scores: "dict[str, SampleScore]" = {}
        errors: dict[str, str] = {}
        pass_error: str | None = None
        superseded = False
        with anyio.move_on_after(SCORE_SCORING_TIMEOUT) as scope:
            async with anyio.create_task_group() as tg:

                async def watch() -> None:
                    nonlocal superseded
                    await active.wait_terminal()
                    superseded = True
                    tg.cancel_scope.cancel()

                async def run_scorers() -> None:
                    # a child task: its context copy keeps the scoring
                    # bindings isolated from the pass (and the watcher)
                    nonlocal pass_error
                    try:
                        pass_error = await _score_live_sample(
                            handle, active, scores, errors
                        )
                    finally:
                        tg.cancel_scope.cancel()

                tg.start_soon(watch)
                tg.start_soon(run_scorers)
        if scope.cancelled_caught:
            pass_error = "per-sample scoring deadline elapsed"

        # re-check terminality directly, not just the watcher's flag: the
        # scorers finishing cancels the watcher, which can lose the race
        # against a terminal transition the recording predicate already saw
        if (superseded or _sample_terminal(active)) and not scores:
            return superseded_result()
        if scores:
            outcome, reason = "scored", pass_error
        elif errors or pass_error:
            outcome, reason = "failed", pass_error
        else:
            # every scorer returned None — legal per the Scorer protocol
            # ("no score for this sample", plausible for incomplete work) —
            # so this is a decline, not a scoring failure
            outcome = "unscored"
            reason = "every scorer returned no score for this sample"
        return _SampleScoreResult(
            held_row(
                outcome,
                reason=reason,
                scores=scores,
                scorer_errors=errors,
            ),
            dict(scores) or None,
        )
    finally:
        release_sample_scoring_hold(active.id)


async def _wait_for_park_or_terminal(
    parked: anyio.Event, active: "ActiveSample", timeout: float
) -> None:
    """Park until the gate's park signal or the sample's terminal event fires.

    Bounded by ``timeout``; the caller's loop re-checks its predicates on
    wake (a fresh park waiter per wait, so a fired-then-stale event can't
    spin it).
    """
    with anyio.move_on_after(timeout):
        async with anyio.create_task_group() as tg:

            async def wake_on_park() -> None:
                await parked.wait()
                tg.cancel_scope.cancel()

            async def wake_on_terminal() -> None:
                await active.wait_terminal()
                tg.cancel_scope.cancel()

            tg.start_soon(wake_on_park)
            tg.start_soon(wake_on_terminal)


def _sample_terminal(active: "ActiveSample") -> bool:
    return active.terminal


async def _score_live_sample(
    handle: TaskScoring,
    active: "ActiveSample",
    scores: "dict[str, SampleScore]",
    errors: dict[str, str],
) -> str | None:
    """Run the task's scorers over a held sample's live state.

    Returns a pass-level failure reason when scoring could not be attempted
    at all (surfaced on the row's ``reason`` field, not ``scorer_errors``,
    which is keyed by scorer name only), or ``None``.

    Binds the pass's scoring context — the live transcript (so each score is
    recorded as ``ScoreEvent(intermediate=True)`` on it, as task-authored
    ``score()`` records one, and flows through the realtime buffer), the
    live store, and the sample's sandbox environments with the same default
    resolution sample init sets up (so ``sandbox()`` and sandbox-inspecting
    scorers work) — but deliberately not the sample itself:
    ``sample_active()`` stays ``None``, so grader calls neither spend the
    sample's limits nor park at the sample-keyed hold.
    """
    from inspect_ai.log._transcript import init_transcript
    from inspect_ai.util._sandbox.context import (
        sandbox_default_context_var,
        sandbox_environments_context_var,
        sandbox_with_environments_context_var,
    )
    from inspect_ai.util._store import init_subtask_store

    live_state = active.live_state
    if live_state is None:
        return "sample has no live state to score yet"

    target = _target(active.sample.target)
    _init_pass_scoring_context(handle, target)
    init_transcript(active.transcript)
    init_subtask_store(live_state.store)
    if active.sandbox_environments:
        sandbox_environments_context_var.set(active.sandbox_environments)
        # mirror sample init: the first environment is the default (without
        # it, sandbox() raises LookupError — the var has no default), and
        # sandbox_with gets a fresh discovery cache
        sandbox_default_context_var.set(next(iter(active.sandbox_environments)))
        sandbox_with_environments_context_var.set({})

    # the caller's dicts, filled incrementally: a scoring deadline (or the
    # sample completing) mid-run keeps the scorers that already finished.
    # Recording stops the moment the sample reaches a terminal transition —
    # its transcript is finalizing, and an event appended now would be
    # silently absent from (or race) the final log.
    await _apply_scorers(
        handle,
        live_state,
        target,
        should_record=lambda: not _sample_terminal(active),
        scores=scores,
        errors=errors,
    )
    return None


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _target(value: Any) -> Any:
    from inspect_ai.scorer import Target

    return Target(value)


def _init_pass_scoring_context(handle: TaskScoring, target: Any) -> None:
    """Bind the pass's task/scoring context (model, roles, config, scorers, target).

    The same bindings ``inspect score`` sets up handler-side — including the
    eval's resolved generate config, so interim grader calls run under the
    settings final scoring will use — minus any sample binding (see
    :func:`_score_live_sample`).
    """
    from inspect_ai._eval.context import init_task_context
    from inspect_ai.scorer._score import init_scoring_context

    init_task_context(handle.model, handle.model_roles, handle.generate_config)
    init_scoring_context(handle.scorers, target)


async def _apply_scorers(
    handle: TaskScoring,
    task_state: Any,
    target: Any,
    *,
    should_record: Callable[[], bool],
    scores: "dict[str, SampleScore]",
    errors: dict[str, str],
) -> None:
    """Run the task's scorers concurrently, collecting per-scorer results.

    Scorers run concurrently (each in its own child task, inheriting the
    caller's scoring-context bindings) so a held sample's hold lasts as long
    as the slowest scorer, not the sum. Per-scorer failures — including a
    failure to record — are collected (not raised) so one scorer's error
    doesn't lose its siblings' scores; results land in the caller's
    ``scores``/``errors`` dicts as each scorer finishes, so a cancellation
    mid-run (the per-sample scoring deadline, or the sample completing)
    keeps the scorers that had already returned.

    ``should_record`` gates recording each score on the current transcript
    as an intermediate ``ScoreEvent`` — re-checked synchronously immediately
    before the append (check-then-append is atomic on the loop), so a sample
    that reached a terminal transition after a scorer returned never gets an
    event appended to its finalizing transcript. A score the predicate
    rejects is dropped entirely: reporting it as scored while its event is
    absent from the log would misstate what persisted (the final score
    supersedes it anyway).

    The recorded event deliberately differs from task-authored ``score()``'s
    in one respect: no ``model_usage``/``role_usage`` snapshot. Those read
    the *sample's* context-bound usage, which the pass's context doesn't
    share — the pass context's own usage would misstate them as the grader's
    spend.
    """
    import functools

    from inspect_ai._util._async import tg_collect
    from inspect_ai._util.registry import (
        has_registry_params,
        registry_params,
        registry_unqualified_name,
    )
    from inspect_ai.event._score import ScoreEvent
    from inspect_ai.log._transcript import transcript
    from inspect_ai.scorer._metric import SampleScore

    async def apply(scorer: "Scorer", scorer_name: str) -> None:
        try:
            result = await scorer(task_state, target)
            if result is None:
                return
            if not should_record():
                return
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
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as ex:
            errors[scorer_name] = f"{type(ex).__name__}: {ex}"
            return
        scores[scorer_name] = SampleScore(
            score=result,
            sample_id=task_state.sample_id,
            sample_metadata=task_state.metadata,
            scorer=registry_unqualified_name(scorer),
        )

    await tg_collect(
        functools.partial(apply, scorer, scorer_name)
        for scorer, scorer_name in zip(handle.scorers, handle.scorer_names)
    )
