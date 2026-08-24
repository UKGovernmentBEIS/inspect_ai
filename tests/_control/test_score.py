"""Tests for the interim-scoring pass (design/ctl/interim-scoring.md).

Covers the sample-keyed hard hold in ``inspect_ai._control.pause`` (park,
escape, isolation from the operator latches), the pass directives in
``inspect_ai._control.scoring`` (start/poll envelopes, dispositions,
completed-sample scoring, pause-and-score of in-flight samples, interim
metrics), and the invariants the design doc calls out (``sample_active()``
unbound in the scoring context; ``ScoreEvent(intermediate=True)`` on the
live transcript; holds always released).
"""

from typing import Any

import anyio
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData
from test_helpers.utils import skip_if_trio

import inspect_ai._control.scoring as scoring_module
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    latest_eval_for_task,
    register_eval,
    set_task_scoring,
)
from inspect_ai._control.pause import (
    hold_sample_for_scoring,
    pause_task,
    release_sample_scoring_hold,
    reset_process_pause,
    reset_task_pause_gates,
    sample_parked_attempts,
    sample_scoring_held,
    wait_generate_dispatch,
)
from inspect_ai._control.scoring import (
    ScorePass,
    TaskScoring,
    _enumerate_targets,
    _score_passes,
    get_score_pass,
    reset_score_passes,
    run_score_pass,
    start_score_pass,
)
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._score import ScoreEvent
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._samples import ActiveSample, sample_active
from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model import ModelName, ModelOutput, get_model
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util._checkpoint.checkpointer_factory import create_checkpointer


@pytest.fixture(autouse=True)
def _clear_states():
    def clear() -> None:
        clear_all_eval_states()
        reset_task_pause_gates()
        reset_process_pause()
        reset_score_passes()

    clear()
    yield
    clear()


@scorer(metrics=[accuracy()])
def match_target():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(
            value=1.0 if (state.output.completion or "") == target.text else 0.0
        )

    return score


def _scoring_handle(score_on_error: bool = False, scorer_obj: Any = None) -> Any:
    return TaskScoring(
        scorers=[scorer_obj if scorer_obj is not None else match_target()],
        scorer_names=["match_target"],
        model=get_model("mockllm/model", memoize=False),
        model_roles=None,
        epochs_reducer=None,
        metrics=None,
        score_on_error=score_on_error,
    )


def _summary(
    sample_id: str,
    *,
    epoch: int = 1,
    scores: dict[str, Score] | None = None,
    error: str | None = None,
    completed: bool = True,
) -> EvalSampleSummary:
    return EvalSampleSummary(
        id=sample_id,
        epoch=epoch,
        input="input",
        target="42",
        scores=scores,
        error=error,
        completed=completed,
    )


def _eval_sample(sample_id: str, *, completion: str = "42") -> EvalSample:
    return EvalSample(
        id=sample_id,
        epoch=1,
        input="input",
        target="42",
        output=ModelOutput.from_content("mockllm/model", completion),
    )


def _active_sample(
    sample_id: str = "s1", *, eval_id: str = "e1", completion: str = "42"
) -> ActiveSample:
    active = ActiveSample(
        task="my_task",
        log_location="",
        model="mockllm/model",
        sample=Sample(id=sample_id, input="input", target="42"),
        epoch=1,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        sandboxes={},
        checkpointer=create_checkpointer(
            config=None, log_location="", sample_id=sample_id, epoch=1
        ),
        eval_id=eval_id,
        sample_uuid=f"uuid-{sample_id}",
    )
    active.started = 1.0
    active.live_state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=sample_id,
        epoch=1,
        input="input",
        messages=[],
        target=Target("42"),
        output=ModelOutput.from_content("mockllm/model", completion),
    )
    return active


def _patch_active_samples(
    monkeypatch: pytest.MonkeyPatch, samples: list[ActiveSample]
) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


def _speed_up(monkeypatch: pytest.MonkeyPatch, hold_timeout: float = 5.0) -> None:
    monkeypatch.setattr(scoring_module, "SCORE_HOLD_TIMEOUT", hold_timeout)
    monkeypatch.setattr(scoring_module, "_HOLD_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(scoring_module, "_QUIESCE_SETTLE", 0.05)


async def _run_pass(
    task_id: str,
    handle: Any,
    *,
    completed_only: bool = False,
) -> ScorePass:
    """Build and run one pass directly (trio-compatible — no asyncio spawn)."""
    state = latest_eval_for_task(task_id)
    assert state is not None
    targets = await _enumerate_targets(state, handle)
    score_pass = ScorePass(
        pass_id="p1",
        task_id=state.task_id,
        eval_id=state.eval_id,
        task=state.task,
        as_of=1.0,
        completed_only=completed_only,
        targeted=targets.counts(completed_only),
        total=len(targets.completed_unscored)
        + (0 if completed_only else len(targets.in_flight)),
    )
    _score_passes[state.task_id] = score_pass
    await run_score_pass(score_pass, state, handle, targets)
    return score_pass


# ---------------------------------------------------------------------------
# the sample-keyed hard hold
# ---------------------------------------------------------------------------


class _FakeGateSample:
    """The slice of ``ActiveSample`` the generate gate reads via ``sample_active``."""

    eval_id = "e1"
    id = "as1"
    interrupt_action: Any = None


def _bind_sample(sample: Any) -> None:
    """Bind a (fake) active sample in the calling coroutine's context.

    Sets the real ``_sample_active`` ContextVar — as the runner does — rather
    than monkeypatching ``sample_active`` (a module-attribute patch would leak
    permanently into any module that first imports the function by value
    while the patch is active).
    """
    from inspect_ai.log._samples import _sample_active

    _sample_active.set(sample)


async def test_sample_hold_parks_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scoring hold parks the held sample's generate attempts until release."""
    register_eval("e1", 5, task_id="t1")
    sample = _FakeGateSample()
    monkeypatch.setattr("inspect_ai._control.pause._HELD_CREDIT_INTERVAL", 0.02)

    hold_sample_for_scoring("as1")
    assert sample_scoring_held("as1")
    model = get_model("mockllm/model", memoize=False)
    passed = anyio.Event()

    async def attempt() -> None:
        _bind_sample(sample)
        await wait_generate_dispatch(model, lambda t: None)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        with anyio.fail_after(5):
            while sample_parked_attempts("t1", "as1") == 0:
                await anyio.sleep(0.01)
        assert not passed.is_set()
        release_sample_scoring_hold("as1")
        with anyio.fail_after(5):
            await passed.wait()
    assert not sample_scoring_held("as1")
    assert sample_parked_attempts("t1", "as1") == 0


async def test_sample_hold_ignores_other_samples_and_pass_context() -> None:
    """A hold keys on one ActiveSample id; other samples and the pass pass."""
    register_eval("e1", 5, task_id="t1")
    hold_sample_for_scoring("other-sample")
    model = get_model("mockllm/model", memoize=False)

    # a different active sample passes
    async def other_sample_attempt() -> None:
        _bind_sample(_FakeGateSample())
        with anyio.fail_after(5):
            await wait_generate_dispatch(model, lambda t: None)

    async with anyio.create_task_group() as tg:
        tg.start_soon(other_sample_attempt)

    # the pass's own grader calls (no active sample bound) pass too
    with anyio.fail_after(5):
        await wait_generate_dispatch(model, lambda t: None)


async def test_sample_hold_escapes_on_interrupt() -> None:
    """A stamped sample interrupt passes the scoring hold (cancel escalates)."""
    register_eval("e1", 5, task_id="t1")
    sample = _FakeGateSample()
    sample.interrupt_action = "score"
    hold_sample_for_scoring("as1")
    model = get_model("mockllm/model", memoize=False)

    async def attempt() -> None:
        _bind_sample(sample)
        with anyio.fail_after(5):
            await wait_generate_dispatch(model, lambda t: None)

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)


async def test_task_resume_does_not_release_scoring_hold() -> None:
    """The scoring holds are independent of the operator latches."""
    register_eval("e1", 5, task_id="t1")
    hold_sample_for_scoring("as1")
    await pause_task("t1")
    from inspect_ai._control.pause import resume_task

    await resume_task("t1")
    assert sample_scoring_held("as1")
    release_sample_scoring_hold("as1")
    assert not sample_scoring_held("as1")


# ---------------------------------------------------------------------------
# start / poll envelopes
# ---------------------------------------------------------------------------


async def test_start_score_pass_unknown_task_is_none() -> None:
    assert await start_score_pass("nope") is None
    assert await get_score_pass("nope") is None


async def test_start_score_pass_without_scorers_is_rejected() -> None:
    register_eval("e1", 1, task_id="t1")
    result = await start_score_pass("t1")
    assert result is not None and result["ok"] is False
    assert "no scorers" in result["error"]


async def test_get_score_pass_before_any_pass() -> None:
    register_eval("e1", 1, task_id="t1")
    result = await get_score_pass("t1")
    assert result is not None and result["ok"] is False
    assert "no scoring pass" in result["error"]


async def test_start_score_pass_dry_run_reports_dispositions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def summaries() -> list[EvalSampleSummary]:
        return [
            _summary("done-scored", scores={"match_target": Score(value=1.0)}),
            _summary("done-unscored"),
            _summary("errored", error="boom"),
            _summary("cancelled", error="CancelledError()"),
        ]

    register_eval(
        "e1",
        8,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries),
    )
    set_task_scoring("e1", _scoring_handle())
    _patch_active_samples(monkeypatch, [_active_sample("running")])

    result = await start_score_pass("t1", dry_run=True)
    assert result is not None and result["ok"] is True
    assert result["changed"] is True and result["dry_run"] is True
    assert result["targeted"] == {
        "in_flight": 1,
        "completed_unscored": 1,
        "completed_scored": 1,
        # errored (score_on_error off) + cancelled + 3 unaccounted (queued)
        "skipped": 5,
    }
    # a dry run starts nothing
    assert (await get_score_pass("t1") or {})["ok"] is False


async def test_start_score_pass_idempotent_while_running() -> None:
    register_eval("e1", 1, task_id="t1")
    set_task_scoring("e1", _scoring_handle())
    state = latest_eval_for_task("t1")
    assert state is not None
    _score_passes["t1"] = ScorePass(
        pass_id="running-pass",
        task_id="t1",
        eval_id="e1",
        task="",
        as_of=1.0,
        completed_only=False,
        total=3,
    )
    result = await start_score_pass("t1")
    assert result is not None and result["ok"] is True
    assert result["changed"] is False
    assert result["pass_id"] == "running-pass"
    assert result["progress"] == {"scored": 0, "failed": 0, "total": 3}


# ---------------------------------------------------------------------------
# the pass itself (run directly — trio-compatible)
# ---------------------------------------------------------------------------


async def test_score_pass_completed_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    """Completed-unscored samples are scored from their serialized form."""
    samples = {
        ("right", 1): _eval_sample("right", completion="42"),
        ("wrong", 1): _eval_sample("wrong", completion="17"),
    }

    async def summaries() -> list[EvalSampleSummary]:
        return [_summary("right"), _summary("wrong")]

    async def read_sample(id: Any, epoch: int, **kwargs: Any) -> EvalSample | None:
        return samples.get((id, epoch))

    register_eval(
        "e1",
        2,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries, sample=read_sample),
    )
    _patch_active_samples(monkeypatch, [])

    score_pass = await _run_pass("t1", _scoring_handle())
    assert score_pass.running is False
    assert score_pass.scored == 2 and score_pass.failed == 0
    by_id = {row["sample_id"]: row for row in score_pass.rows}
    assert by_id["right"]["disposition"] == "completed_unscored"
    assert by_id["right"]["outcome"] == "scored"
    assert by_id["right"]["scores"] == {"match_target": 1.0}
    assert by_id["wrong"]["scores"] == {"match_target": 0.0}
    # interim metrics over both samples (accuracy = 0.5)
    assert score_pass.metrics is not None
    (entry,) = score_pass.metrics
    assert entry["scorer"] == "match_target"
    assert entry["metrics"]["accuracy"] == 0.5
    # the recorder's in-memory samples were not mutated by the scoring
    assert samples[("right", 1)].scores is None
    assert samples[("right", 1)].events == []


async def test_score_pass_dispositions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Already-scored samples ride into metrics; errored/cancelled follow policy."""

    async def summaries() -> list[EvalSampleSummary]:
        return [
            _summary("scored", scores={"match_target": Score(value=1.0)}),
            _summary("errored", error="boom"),
            _summary("cancelled", error="CancelledError()"),
        ]

    register_eval(
        "e1",
        3,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries),
    )
    _patch_active_samples(monkeypatch, [])

    score_pass = await _run_pass("t1", _scoring_handle())
    by_id = {row["sample_id"]: row for row in score_pass.rows}
    assert by_id["scored"]["disposition"] == "completed_scored"
    assert by_id["scored"]["outcome"] == "existing"
    assert by_id["scored"]["scores"] == {"match_target": 1.0}
    assert by_id["errored"]["disposition"] == "skipped"
    assert "score_on_error" in by_id["errored"]["reason"]
    assert by_id["cancelled"]["disposition"] == "skipped"
    assert "cancelled" in by_id["cancelled"]["reason"]
    # the existing final score feeds the interim metrics
    assert score_pass.metrics is not None
    assert score_pass.metrics[0]["metrics"]["accuracy"] == 1.0


async def test_score_pass_scores_errored_when_score_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def summaries() -> list[EvalSampleSummary]:
        return [_summary("errored", error="boom")]

    async def read_sample(id: Any, epoch: int, **kwargs: Any) -> EvalSample | None:
        return _eval_sample("errored", completion="42")

    register_eval(
        "e1",
        1,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries, sample=read_sample),
    )
    _patch_active_samples(monkeypatch, [])

    score_pass = await _run_pass("t1", _scoring_handle(score_on_error=True))
    (row,) = score_pass.rows
    assert row["disposition"] == "completed_unscored"
    assert row["scores"] == {"match_target": 1.0}


async def test_score_pass_held_in_flight_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pause-and-score: hold, park ack, score the live state, release."""
    _speed_up(monkeypatch)
    monkeypatch.setattr("inspect_ai._control.pause._HELD_CREDIT_INTERVAL", 0.02)

    async def summaries() -> list[EvalSampleSummary]:
        return []

    register_eval(
        "e1",
        1,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries),
    )
    active = _active_sample("s1")
    _patch_active_samples(monkeypatch, [active])

    seen: dict[str, Any] = {}

    @scorer(metrics=[accuracy()])
    def observing_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            # the scoring context binds the live transcript but NOT the
            # sample (budget isolation / hold escape are structural)
            seen["sample_active"] = sample_active()
            seen["transcript_is_live"] = transcript() is active.transcript
            seen["state_is_live"] = state is active.live_state
            return Score(
                value=1.0 if (state.output.completion or "") == target.text else 0.0
            )

        return score

    handle = _scoring_handle(scorer_obj=observing_scorer())
    model = get_model("mockllm/model", memoize=False)
    stop = anyio.Event()
    resumed = anyio.Event()

    async def solver() -> None:
        # bind the sample in this coroutine's context, as the runner does
        from inspect_ai.log._samples import _sample_active

        _sample_active.set(active)
        parked_once = False
        while not stop.is_set():
            await wait_generate_dispatch(model, lambda t: None)
            if parked_once:
                resumed.set()
            if sample_scoring_held(active.id):
                parked_once = True
            await anyio.sleep(0.01)

    score_pass: ScorePass | None = None
    async with anyio.create_task_group() as tg:
        tg.start_soon(solver)
        with anyio.fail_after(10):
            score_pass = await _run_pass("t1", handle)
        stop.set()

    assert score_pass is not None
    (row,) = score_pass.rows
    assert row["disposition"] == "in_flight"
    assert row["outcome"] == "scored"
    assert row["scores"] == {"match_target": 1.0}
    assert row["held_seconds"] > 0
    # the scoring context bound the live handles but not the sample
    assert seen["sample_active"] is None
    assert seen["transcript_is_live"] is True
    assert seen["state_is_live"] is True
    # the held-state score was recorded on the live transcript as an
    # intermediate event (the invariant score() established)
    events = [e for e in active.transcript.events if isinstance(e, ScoreEvent)]
    assert len(events) == 1
    assert events[0].intermediate is True
    assert events[0].score.value == 1.0
    # the hold was released
    assert not sample_scoring_held(active.id)
    # interim metrics over the held-state score
    assert score_pass.metrics is not None
    assert score_pass.metrics[0]["metrics"]["accuracy"] == 1.0


async def test_score_pass_hold_timeout_reports_did_not_park(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample that never parks times out to the did-not-park row, un-scored."""
    _speed_up(monkeypatch, hold_timeout=0.3)

    async def summaries() -> list[EvalSampleSummary]:
        return []

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(summaries=summaries))
    active = _active_sample("s1")
    _patch_active_samples(monkeypatch, [active])

    with anyio.fail_after(10):
        score_pass = await _run_pass("t1", _scoring_handle())
    (row,) = score_pass.rows
    assert row["disposition"] == "in_flight"
    assert row["outcome"] == "did_not_park"
    assert row["scores"] == {}
    assert score_pass.scored == 0 and score_pass.failed == 1
    assert not sample_scoring_held(active.id)
    # nothing was recorded on the live transcript
    assert len(active.transcript.events) == 0


async def test_score_pass_completed_only_skips_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def summaries() -> list[EvalSampleSummary]:
        return [_summary("scored", scores={"match_target": Score(value=1.0)})]

    register_eval("e1", 2, task_id="t1", live=FakeLiveEvalData(summaries=summaries))
    _patch_active_samples(monkeypatch, [_active_sample("running")])

    with anyio.fail_after(10):
        score_pass = await _run_pass("t1", _scoring_handle(), completed_only=True)
    assert score_pass.targeted == {
        "in_flight": 0,
        "completed_unscored": 0,
        "completed_scored": 1,
        "skipped": 1,
    }
    # no in-flight rows, no holds taken
    assert all(row["disposition"] != "in_flight" for row in score_pass.rows)


async def test_score_pass_superseded_sample_yields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample that completes instead of parking is reported superseded."""
    _speed_up(monkeypatch)

    async def summaries() -> list[EvalSampleSummary]:
        return []

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(summaries=summaries))
    active = _active_sample("s1")
    _patch_active_samples(monkeypatch, [active])

    async def complete_soon() -> None:
        await anyio.sleep(0.1)
        active.complete()

    async with anyio.create_task_group() as tg:
        tg.start_soon(complete_soon)
        with anyio.fail_after(10):
            score_pass = await _run_pass("t1", _scoring_handle())
    (row,) = score_pass.rows
    assert row["outcome"] == "superseded"
    assert "completed before interim scoring finished" in row["reason"]
    assert not sample_scoring_held(active.id)


async def test_score_pass_scorer_failure_lands_on_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @scorer(metrics=[accuracy()])
    def failing_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            raise RuntimeError("scorer exploded")

        return score

    async def summaries() -> list[EvalSampleSummary]:
        return [_summary("done")]

    async def read_sample(id: Any, epoch: int, **kwargs: Any) -> EvalSample | None:
        return _eval_sample("done")

    register_eval(
        "e1",
        1,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries, sample=read_sample),
    )
    _patch_active_samples(monkeypatch, [])

    handle = TaskScoring(
        scorers=[failing_scorer()],
        scorer_names=["failing_scorer"],
        model=get_model("mockllm/model", memoize=False),
        model_roles=None,
        epochs_reducer=None,
        metrics=None,
        score_on_error=False,
    )
    score_pass = await _run_pass("t1", handle)
    (row,) = score_pass.rows
    assert row["outcome"] == "failed"
    assert "scorer exploded" in row["scorer_errors"]["failing_scorer"]
    assert score_pass.failed == 1
    assert score_pass.error is None  # per-sample failures don't fail the pass


async def test_score_pass_scoring_deadline_keeps_finished_scorers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scoring deadline keeps scorers that had already finished.

    Scores publish incrementally: with one scorer done and one wedged, the
    row reports the finished score plus the deadline error, not an empty
    failure.
    """
    _speed_up(monkeypatch)
    monkeypatch.setattr(scoring_module, "SCORE_SCORING_TIMEOUT", 0.5)
    monkeypatch.setattr("inspect_ai._control.pause._HELD_CREDIT_INTERVAL", 0.02)

    async def summaries() -> list[EvalSampleSummary]:
        return []

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(summaries=summaries))
    active = _active_sample("s1")
    _patch_active_samples(monkeypatch, [active])

    @scorer(metrics=[accuracy()])
    def fast_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0)

        return score

    @scorer(metrics=[accuracy()])
    def wedged_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            await anyio.sleep(3600)
            return Score(value=0.0)

        return score

    handle = TaskScoring(
        scorers=[fast_scorer(), wedged_scorer()],
        scorer_names=["fast_scorer", "wedged_scorer"],
        model=get_model("mockllm/model", memoize=False),
        model_roles=None,
        epochs_reducer=None,
        metrics=None,
        score_on_error=False,
    )

    model = get_model("mockllm/model", memoize=False)
    stop = anyio.Event()

    async def solver() -> None:
        from inspect_ai.log._samples import _sample_active

        _sample_active.set(active)
        while not stop.is_set():
            await wait_generate_dispatch(model, lambda t: None)
            await anyio.sleep(0.01)

    score_pass: ScorePass | None = None
    async with anyio.create_task_group() as tg:
        tg.start_soon(solver)
        with anyio.fail_after(30):
            score_pass = await _run_pass("t1", handle)
        stop.set()

    assert score_pass is not None
    assert score_pass.error is None
    (row,) = score_pass.rows
    assert row["disposition"] == "in_flight"
    assert row["outcome"] == "scored"
    assert row["scores"] == {"fast_scorer": 1.0}
    assert "deadline" in row["scorer_errors"][""]
    assert not sample_scoring_held(active.id)


# ---------------------------------------------------------------------------
# the spawned job (asyncio only — the control server runs on asyncio)
# ---------------------------------------------------------------------------


@skip_if_trio
async def test_start_score_pass_spawns_and_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def summaries() -> list[EvalSampleSummary]:
        return [_summary("done")]

    async def read_sample(id: Any, epoch: int, **kwargs: Any) -> EvalSample | None:
        return _eval_sample("done")

    register_eval(
        "e1",
        1,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries, sample=read_sample),
    )
    set_task_scoring("e1", _scoring_handle())
    _patch_active_samples(monkeypatch, [])

    result = await start_score_pass("t1")
    assert result is not None and result["ok"] is True and result["changed"] is True
    pass_id = result["pass_id"]
    assert result["targeted"]["completed_unscored"] == 1

    with anyio.fail_after(10):
        while True:
            status = await get_score_pass("t1")
            assert status is not None and status["ok"] is True
            assert status["pass_id"] == pass_id
            if not status["running"]:
                break
            await anyio.sleep(0.05)

    assert status["progress"] == {"scored": 1, "failed": 0, "total": 1}
    outcome = status["result"]
    assert outcome["interim"] is True
    assert outcome["counts"]["completed_unscored"] == 1
    (row,) = [r for r in outcome["samples"] if r["sample_id"] == "done"]
    assert row["scores"] == {"match_target": 1.0}
    assert outcome["metrics"][0]["metrics"]["accuracy"] == 1.0


@skip_if_trio
async def test_start_score_pass_concurrent_starts_spawn_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlapping starts interleave across the enumeration await; one wins.

    The one-pass check runs before target enumeration, which suspends (the
    recorder's summaries lock) — without the post-enumeration re-check, both
    starts would spawn passes (the loser an orphan sharing the winner's
    sample hold gates).
    """

    async def summaries() -> list[EvalSampleSummary]:
        # a checkpoint, as the real recorder's summaries lock is
        await anyio.sleep(0)
        return [_summary("done")]

    async def read_sample(id: Any, epoch: int, **kwargs: Any) -> EvalSample | None:
        return _eval_sample("done")

    register_eval(
        "e1",
        1,
        task_id="t1",
        live=FakeLiveEvalData(summaries=summaries, sample=read_sample),
    )
    set_task_scoring("e1", _scoring_handle())
    _patch_active_samples(monkeypatch, [])

    from inspect_ai._util._async import tg_collect

    results = [
        r
        for r in await tg_collect(
            [lambda: start_score_pass("t1"), lambda: start_score_pass("t1")]
        )
        if r is not None
    ]
    assert len(results) == 2 and all(r["ok"] for r in results)
    started = [r for r in results if r["changed"]]
    joined = [r for r in results if not r["changed"]]
    assert len(started) == 1 and len(joined) == 1
    # the loser joined the winner's pass rather than spawning an orphan
    assert joined[0]["pass_id"] == started[0]["pass_id"]
    assert "already running" in joined[0]["reason"]

    with anyio.fail_after(10):
        while True:
            status = await get_score_pass("t1")
            assert status is not None and status["pass_id"] == started[0]["pass_id"]
            if not status["running"]:
                break
            await anyio.sleep(0.05)
    assert status["progress"] == {"scored": 1, "failed": 0, "total": 1}


# ---------------------------------------------------------------------------
# end to end (a real eval; asyncio only — the pass spawns an asyncio task)
# ---------------------------------------------------------------------------


def test_eval_interim_score_pass_e2e(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pause-and-score against a real running eval, end to end.

    The solver starts a pass on its own task, then calls generate — which
    parks at the pass's sample-keyed hold while the pass scores the live
    state — and finally polls the pass to completion. Pins the full wiring:
    the runner's `set_task_scoring` publication, the hold/park/release cycle
    around a real generate, the `ScoreEvent(intermediate=True)` recorded on
    the live transcript riding into the final log, and final scores staying
    untouched by the interim pass.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai.log import read_eval_log
    from inspect_ai.solver import Generate, solver

    _speed_up(monkeypatch)
    monkeypatch.setattr("inspect_ai._control.pause._HELD_CREDIT_INTERVAL", 0.02)

    observed: dict[str, Any] = {}

    @solver(name=f"self_scoring_{id(observed)}")
    def self_scoring():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            task_id = get_eval_states()[0].task_id
            observed["start"] = await start_score_pass(task_id)
            active = sample_active()
            assert active is not None
            # wait for the pass to place the hold, so the generate below
            # deterministically parks under it
            with anyio.fail_after(10):
                while not sample_scoring_held(active.id):
                    await anyio.sleep(0.01)
            state = await generate(state)
            with anyio.fail_after(20):
                while True:
                    status = await get_score_pass(task_id)
                    if (
                        status is not None
                        and status.get("ok")
                        and not status["running"]
                    ):
                        break
                    await anyio.sleep(0.02)
            observed["status"] = status
            return state

        return solve

    scorer_name = f"const_one_{id(observed)}"

    @scorer(metrics=[accuracy()], name=scorer_name)
    def const_one():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0)

        return score

    log_dir = str(tmp_path / "logs")
    success, logs = eval_set(
        tasks=[
            Task(
                dataset=[Sample(input="x", target="y")],
                solver=[self_scoring()],
                scorer=const_one(),
                name="interim_score_e2e",
            )
        ],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )

    assert success and logs[0].status == "success"
    # the start targeted the in-flight sample
    assert observed["start"]["ok"] is True and observed["start"]["changed"] is True
    assert observed["start"]["targeted"]["in_flight"] == 1
    # the pass scored the held sample's live state
    status = observed["status"]
    assert status["progress"] == {"scored": 1, "failed": 0, "total": 1}
    (row,) = status["result"]["samples"]
    assert row["disposition"] == "in_flight" and row["outcome"] == "scored"
    assert row["scores"] == {scorer_name: 1.0}
    assert status["result"]["metrics"][0]["metrics"]["accuracy"] == 1.0
    # the intermediate score event rode into the final log; final scores
    # were computed by ordinary end-of-sample scoring, untouched by the pass
    log = read_eval_log(logs[0].location)
    assert log.samples is not None
    score_events = [e for e in log.samples[0].events if isinstance(e, ScoreEvent)]
    intermediate = [e for e in score_events if e.intermediate]
    final = [e for e in score_events if not e.intermediate]
    assert len(intermediate) == 1 and len(final) == 1
    assert log.samples[0].scores is not None
    assert list(log.samples[0].scores) == [scorer_name]
