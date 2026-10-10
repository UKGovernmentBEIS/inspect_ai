import contextlib
import functools
import pathlib
from typing import Any, AsyncIterator

import anyio
import pydantic
import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval, eval_async, score
from inspect_ai._eval.score import (
    ScoreAction,
    _get_updated_events,
    _get_updated_scores,
    _score_name,
    named_scorers_from_log_header,
    resolve_scorers,
    score_async,
    score_names_from_log_header,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._input import InputEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.log import (
    EvalLog,
    EvalSample,
    Transcript,
    recompute_metrics,
)
from inspect_ai.log._file import read_eval_log, read_eval_log_async
from inspect_ai.log._transcript import init_transcript
from inspect_ai.model import ChatCompletionChoice, GenerateConfig, ModelOutput
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.scorer import accuracy, exact, match
from inspect_ai.scorer._metric import SampleScore, Score
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._span import span


class UpdatedScoresTestCase(pydantic.BaseModel):
    action: ScoreAction
    existing_scores: dict[str, Score]
    new_scores: dict[str, SampleScore]
    expected_scores: dict[str, Score]


@pytest.mark.parametrize(
    "test_case",
    [
        pytest.param(
            UpdatedScoresTestCase(
                action="append",
                existing_scores={"old-scorer": Score(value=0.1)},
                new_scores={
                    "old-scorer": SampleScore(score=Score(value=0.2)),
                    "new-scorer": SampleScore(score=Score(value=0.5)),
                },
                expected_scores={
                    "old-scorer": Score(value=0.1),
                    "old-scorer-1": Score(value=0.2),
                    "new-scorer": Score(value=0.5),
                },
            ),
            id="append",
        ),
        pytest.param(
            UpdatedScoresTestCase(
                action="overwrite",
                existing_scores={"old-scorer": Score(value=0.1)},
                new_scores={
                    "old-scorer": SampleScore(score=Score(value=0.2)),
                    "new-scorer": SampleScore(score=Score(value=0.5)),
                },
                expected_scores={
                    "old-scorer": Score(value=0.2),
                    "new-scorer": Score(value=0.5),
                },
            ),
            id="overwrite",
        ),
    ],
)
def test_get_updated_scores(test_case: UpdatedScoresTestCase):
    sample = EvalSample(
        id="1",
        scores=test_case.existing_scores,
        epoch=1,
        input="input",
        target="target",
    )

    updated_scores = _get_updated_scores(
        sample,
        test_case.new_scores,
        action=test_case.action,
    )

    assert updated_scores == test_case.expected_scores


class UpdatedEventsTestCase(pydantic.BaseModel):
    action: ScoreAction
    existing_scores: list[tuple[str, Score]]
    new_scores: list[tuple[str, Score]]
    expected_scores: list[tuple[str, Score]]
    expected_new_scorer_span: bool


@pytest.mark.parametrize(
    "test_case",
    [
        pytest.param(
            UpdatedEventsTestCase(
                action="append",
                existing_scores=[
                    ("old-scorer", Score(value=0.1)),
                ],
                new_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_scores=[
                    ("old-scorer", Score(value=0.1)),
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_new_scorer_span=False,
            ),
            id="append",
        ),
        pytest.param(
            UpdatedEventsTestCase(
                action="append",
                existing_scores=[],
                new_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_new_scorer_span=True,
            ),
            id="append-empty",
        ),
        pytest.param(
            UpdatedEventsTestCase(
                action="overwrite",
                existing_scores=[
                    ("old-scorer", Score(value=0.1)),
                ],
                new_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_new_scorer_span=True,
            ),
            id="overwrite",
        ),
        pytest.param(
            UpdatedEventsTestCase(
                action="overwrite",
                existing_scores=[],
                new_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_scores=[
                    ("old-scorer", Score(value=0.2)),
                    ("new-scorer", Score(value=0.5)),
                ],
                expected_new_scorer_span=True,
            ),
            id="overwrite-empty",
        ),
    ],
)
async def test_get_updated_events(test_case: UpdatedEventsTestCase):
    base_events: list[Event] = [
        SampleInitEvent(
            sample=Sample(id="1", input="input", target="target"), state={}
        ),
        InputEvent(input="input", input_ansi="input_ansi"),
        ModelEvent(
            model="model",
            role="role",
            input=[ChatMessageUser(role="user", content="input")],
            output=ModelOutput(
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            role="assistant",
                            content="output",
                        )
                    )
                ]
            ),
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        ),
    ]

    existing_events = [*base_events]
    expected_events = [*base_events]
    new_events: list[Event] = []
    events: list[Event]
    transcript: Transcript = Transcript()

    for events, scores in (
        (existing_events, test_case.existing_scores),
        (expected_events, test_case.expected_scores),
        (new_events, test_case.new_scores),
    ):
        if not scores:
            continue
        transcript = Transcript()
        init_transcript(transcript)
        async with span(name="scorers"):
            for scorer_name, score in scores:
                async with span(scorer_name, type="scorer"):
                    transcript._event(
                        ScoreEvent(
                            score=score,
                            target="target",
                        )
                    )
        events.extend(transcript.events)

    sample = EvalSample(
        id="1",
        events=existing_events,
        epoch=1,
        input="input",
        target="target",
    )

    updated_events = _get_updated_events(sample, new_events, action=test_case.action)

    assert len(updated_events) == len(expected_events)
    assert updated_events[: len(base_events)] == base_events
    for updated_event, expected_event in zip(
        updated_events[len(base_events) :], expected_events[len(base_events) :]
    ):
        included_fields = {
            "intermediate",
            "name",
            "score",
            "target",
            "type",
        }
        assert isinstance(updated_event, expected_event.__class__)
        assert updated_event.model_dump(
            include=included_fields
        ) == expected_event.model_dump(include=included_fields)

    existing_scorers_span, updated_scorers_span = (
        next(
            (
                event
                for event in events[::-1]
                if event.event == "span_begin" and event.name == "scorers"
            ),
            None,
        )
        for events in (existing_events, updated_events)
    )

    assert (existing_scorers_span is None) is not bool(test_case.existing_scores)
    assert updated_scorers_span is not None
    assert (
        existing_scorers_span == updated_scorers_span
    ) is not test_case.expected_new_scorer_span


LOGS_DIR = pathlib.Path(__file__).parents[1] / "scorer/logs"
LOG_SCORED = (
    LOGS_DIR / "2025-02-11T15-18-04-05-00_popularity_mj7khqpMM4GBCfVQozKgzB.eval"
)
LOG_UNSCORED = (
    LOGS_DIR / "2025-02-11T15-17-00-05-00_popularity_dPiJifoWeEQBrfWsAopzWr.eval"
)


@scorer(metrics=[accuracy()])
def adds_to_state() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        state.scores = (state.scores or {}) | {"adds_to_state": Score(value=0.5)}
        return Score(value=0.5)

    return score


@pytest.mark.parametrize(
    ("log_file", "action", "scorers_unresolved", "expected_scores", "expected_error"),
    [
        pytest.param(
            LOG_UNSCORED,
            None,
            [("match", dict[str, Any]())],
            {"match": {"num_metrics": 2}},
            None,
            id="unscored",
        ),
        pytest.param(
            LOG_UNSCORED,
            "overwrite",
            [("match", dict[str, Any]())],
            {"match": {"num_metrics": 2}},
            None,
            id="unscored-overwrite",
        ),
        pytest.param(
            LOG_UNSCORED,
            "append",
            [("f1", {"stop_words": ["roasted"]})],
            {"f1": {"num_metrics": 2, "stop_words": ["roasted"]}},
            None,
            id="unscored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            [("f1", {"stop_words": ["woah"]})],
            {
                "match": {"num_metrics": 2},
                "f1": {"num_metrics": 2, "stop_words": ["woah"]},
            },
            None,
            id="scored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "overwrite",
            [("f1", {"stop_words": ["clowns"]})],
            {"f1": {"num_metrics": 2, "stop_words": ["clowns"]}},
            None,
            id="scored-overwrite",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            [("f1", dict[str, Any]()), ("includes", dict[str, Any]())],
            {
                "match": {"num_metrics": 2},
                "f1": {"num_metrics": 2},
                "includes": {"num_metrics": 2},
            },
            None,
            id="multiple-scorers",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            [("adds_to_state", dict[str, Any]())],
            None,
            pytest.raises(RuntimeError, match="modified state.scores"),
            id="scored-append-with-state-score",
        ),
    ],
)
@pytest.mark.anyio
@skip_if_no_openai
async def test_score(
    log_file: pathlib.Path,
    action: ScoreAction | None,
    scorers_unresolved: list[tuple[str, dict[str, Any]]],
    expected_scores: dict[str, dict[str, int]] | None,
    expected_error: contextlib.AbstractContextManager[Any] | None,
):
    unscored_log = await read_eval_log_async(log_file)
    assert unscored_log.samples is not None
    assert len(unscored_log.samples) > 0

    mock_scorers: list[Scorer] = []
    seen_scores: dict[tuple[int | str, str], dict[str, Score]] = {}
    for scorer_unresolved in scorers_unresolved:
        for scorer_fn in resolve_scorers(
            unscored_log, scorer_unresolved[0], scorer_unresolved[1]
        ):

            @functools.wraps(scorer_fn)
            async def scorer_wrapped(
                state: TaskState,
                target: Target,
                scorer_name: str = scorer_unresolved[0],
                scorer_fn: Scorer = scorer_fn,
            ) -> Score | None:
                seen_scores[state.sample_id, scorer_name] = (state.scores or {}).copy()
                return await scorer_fn(state, target)

            mock_scorers.append(scorer_wrapped)

    with (
        expected_error if expected_error is not None else contextlib.nullcontext()
    ) as exc_info:
        scored_log = await score_async(
            log=unscored_log, scorers=mock_scorers, action=action
        )

    if exc_info is not None:
        return

    assert scored_log.results is not None
    scores = {score.name: score for score in scored_log.results.scores}
    assert [*scores] == [*(expected_scores or {})]
    for score_name, expected_score in (expected_scores or {}).items():
        assert len(scores[score_name].metrics.items()) == expected_score["num_metrics"]
        if expected_stop_words := expected_score.get("stop_words"):
            assert scores[score_name].params["stop_words"] == expected_stop_words

    scored_samples = {sample.id: sample for sample in scored_log.samples or []}
    assert len(scored_samples) == len(unscored_log.samples)
    for unscored_sample in unscored_log.samples:
        scored_sample = scored_samples[unscored_sample.id]
        assert scored_sample.scores is not None
        for idx_scorer, (scorer_name, _) in enumerate(scorers_unresolved):
            scores_passed_to_scorer = seen_scores[unscored_sample.id, scorer_name]
            expected_scores_passed_to_scorer = (
                (unscored_sample.scores or {}) if action == "append" else {}
            )
            if idx_scorer > 0:
                expected_scores_passed_to_scorer.update(
                    {
                        scorer_name: scored_sample.scores[scorer_name]
                        for scorer_name, _ in scorers_unresolved[:idx_scorer]
                    }
                )
            assert scores_passed_to_scorer == expected_scores_passed_to_scorer


@skip_if_no_openai
def test_score_append_with_unavailable_metrics():
    """Test that score_async(action="append") works with unavailable metrics.

    Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/3238.
    When the original eval's metrics come from external packages that are not
    installed, append should still succeed because it doesn't recreate them.
    """
    from inspect_ai.log._log import EvalMetricDefinition

    log = read_eval_log(LOG_SCORED)

    # Inject a metric that would fail registry_create (simulating an external package)
    log.eval.metrics = [
        EvalMetricDefinition(name="fake_package/nonexistent_metric"),
    ]

    # Resolve an f1 scorer to append
    f1_scorers = resolve_scorers(log, "f1", {})

    # This should succeed — append should not try to recreate original metrics
    scored_log = score(log=log, scorers=f1_scorers, action="append")

    assert scored_log.results is not None
    scores = {score.name: score for score in scored_log.results.scores}
    # Original "match" scores should be preserved from log.results.scores
    assert "match" in scores
    # New "f1" scores should be appended
    assert "f1" in scores


def test_score_append_preserves_existing_reductions():
    """score(action="append") must keep pre-existing scorers' reductions.

    Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/4764.
    The reductions computed during an append pass only cover the scorers run in
    that pass, so they must be appended to log.reductions rather than replacing
    it -- otherwise every pre-existing scorer's reductions are silently dropped
    even though results.scores still retains their entries.
    """
    log = read_eval_log(LOG_SCORED)

    # The fixture already carries a reduction for its original "match" scorer.
    original_reducers = [r.scorer for r in (log.reductions or [])]
    assert "match" in original_reducers

    f1_scorers = resolve_scorers(log, "f1", {})
    # f1 never calls a model, so name mockllm to keep this running without an
    # API key (score() otherwise resolves the header model and would raise).
    scored_log = score(
        log=log, scorers=f1_scorers, action="append", model="mockllm/model"
    )

    reducers = [r.scorer for r in (scored_log.reductions or [])]
    # Original reduction preserved and the new scorer's reduction appended.
    assert "match" in reducers
    assert "f1" in reducers


@pytest.mark.anyio
async def test_score_preserves_model_usage_in_score_event():
    """Test that model_usage from sample is correctly captured in ScoreEvent when re-scoring."""
    from inspect_ai._eval.score import _run_score_task
    from inspect_ai.log import EvalLog
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalPlanStep,
        EvalSpec,
    )
    from inspect_ai.model._model import ModelUsage

    # Create a sample with model_usage set
    sample_model_usage = {
        "openai/gpt-4": ModelUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
        )
    }
    sample = EvalSample(
        id="test-1",
        epoch=1,
        input="What is 2+2?",
        target="4",
        messages=[ChatMessageUser(role="user", content="What is 2+2?")],
        output=ModelOutput(
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(role="assistant", content="4")
                )
            ]
        ),
        model_usage=sample_model_usage,
    )

    # Create minimal log header
    log_header = EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test",
            run_id="test-run",
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="test",
            steps=[EvalPlanStep(solver="generate")],
            config=GenerateConfig(),
        ),
    )

    # Simple scorer that returns a score
    @scorer(metrics=[accuracy()])
    def simple_scorer(threshold: float = 0.5) -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0 if state.output.completion == target.text else 0.0)

        return score

    # Run the scoring
    from inspect_ai.model._model import get_model

    results, _ = await _run_score_task(
        log_header=log_header,
        sample=sample,
        scorers=[simple_scorer(threshold=0.75)],
        model=get_model("mockllm/model"),
        model_roles={},
        action="append",
    )

    # Check that the ScoreEvent in the sample's events has the correct model_usage
    score_events = [e for e in sample.events if isinstance(e, ScoreEvent)]
    assert len(score_events) == 1
    assert score_events[0].model_usage == sample_model_usage
    assert score_events[0].scorer == "simple_scorer"
    assert score_events[0].scorer_args == {"threshold": 0.75}


@pytest.mark.anyio
async def test_score_model_roles_override():
    """score_async() model_roles overrides merge over roles reconstructed from the log."""
    from inspect_ai.log import EvalLog
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalPlanStep,
        EvalSpec,
    )
    from inspect_ai.model._model import get_model
    from inspect_ai.model._model_config import ModelConfig

    @scorer(metrics=[accuracy()])
    def judge_model_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            judge = get_model(role="judge")
            return Score(value=1.0, answer=str(judge))

        return score

    sample = EvalSample(
        id="test-1",
        epoch=1,
        input="q",
        target="a",
        messages=[ChatMessageUser(role="user", content="q")],
        output=ModelOutput(
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(role="assistant", content="a")
                )
            ]
        ),
    )

    log = EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test",
            run_id="test-run",
            dataset=EvalDataset(),
            model="mockllm/model",
            model_roles={"judge": ModelConfig(model="mockllm/log-judge")},
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="test",
            steps=[EvalPlanStep(solver="generate")],
            config=GenerateConfig(),
        ),
        samples=[sample],
    )

    # no override -> judge role resolved from log header
    scored = await score_async(
        log=log, scorers=[judge_model_scorer()], action="overwrite"
    )
    assert scored.samples is not None
    assert scored.samples[0].scores is not None
    assert scored.samples[0].scores["judge_model_scorer"].answer == "mockllm/log-judge"

    # override -> caller-supplied judge wins over the log-derived one
    override = get_model("mockllm/override-judge")
    scored = await score_async(
        log=log,
        scorers=[judge_model_scorer()],
        model_roles={"judge": override},
        action="overwrite",
    )
    assert scored.samples is not None
    assert scored.samples[0].scores is not None
    assert (
        scored.samples[0].scores["judge_model_scorer"].answer
        == "mockllm/override-judge"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["overwrite", "append"])
async def test_score_preserves_logged_samples(action: ScoreAction) -> None:
    """Rescoring must carry EvalResults.logged_samples into the rebuilt results.

    The eval-set run-vs-reuse check classifies a drained (or gracefully
    cancelled) log by this count; a rescore that dropped it would make the
    log read complete and the abandoned remainder would silently never re-run.
    """
    from inspect_ai.log import EvalLog
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalPlanStep,
        EvalResults,
        EvalSpec,
    )

    @scorer(metrics=[accuracy()])
    def constant_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1.0)

        return score

    sample = EvalSample(
        id="test-1",
        epoch=1,
        input="q",
        target="a",
        messages=[ChatMessageUser(role="user", content="q")],
        output=ModelOutput(
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(role="assistant", content="a")
                )
            ]
        ),
    )

    # a drained log: three planned, one resolved
    log = EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test",
            run_id="test-run",
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="test",
            steps=[EvalPlanStep(solver="generate")],
            config=GenerateConfig(),
        ),
        results=EvalResults(total_samples=3, completed_samples=1, logged_samples=1),
        samples=[sample],
    )

    scored = await score_async(log=log, scorers=[constant_scorer()], action=action)
    assert scored.results is not None
    assert scored.results.logged_samples == 1


@pytest.mark.anyio
async def test_score_resolves_attachments_for_scorer_state_and_transcript() -> None:
    from inspect_ai._eval.score import _run_score_task
    from inspect_ai.log import EvalLog
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalPlanStep,
        EvalSpec,
    )
    from inspect_ai.log._transcript import transcript
    from inspect_ai.model._model import get_model

    input_ref = "attachment://input-ref"
    message_ref = "attachment://message-ref"
    event_ref = "attachment://event-ref"

    sample = EvalSample(
        id="test-1",
        epoch=1,
        input=[ChatMessageUser(content=input_ref)],
        target="target",
        messages=[ChatMessageUser(content=message_ref)],
        output=ModelOutput(
            choices=[ChatCompletionChoice(message=ChatMessageAssistant(content="done"))]
        ),
        events=[
            ModelEvent(
                model="mockllm/model",
                role="assistant",
                input=[ChatMessageUser(content=event_ref)],
                output=ModelOutput(
                    choices=[
                        ChatCompletionChoice(
                            message=ChatMessageAssistant(content="done")
                        )
                    ]
                ),
                tools=[],
                tool_choice="none",
                config=GenerateConfig(),
            )
        ],
        attachments={
            "input-ref": "resolved input",
            "message-ref": "resolved message",
            "event-ref": "resolved event",
        },
    )
    log_header = EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="t",
            task_id="t",
            run_id="r",
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="t", steps=[EvalPlanStep(solver="generate")], config=GenerateConfig()
        ),
    )

    seen: dict[str, str] = {}

    @scorer(metrics=[accuracy()])
    def attachment_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            assert isinstance(state.input, list)
            seen["input"] = state.input[0].text
            seen["messages"] = state.messages[0].text

            model_events = [
                event for event in transcript().events if isinstance(event, ModelEvent)
            ]
            seen["transcript"] = model_events[0].input[0].text
            return Score(value=1.0)

        return score

    await _run_score_task(
        log_header=log_header,
        sample=sample,
        scorers=[attachment_scorer()],
        model=get_model("mockllm/model"),
        model_roles={},
        action="append",
    )

    assert seen == {
        "input": "resolved input",
        "messages": "resolved message",
        "transcript": "resolved event",
    }

    assert isinstance(sample.input, list)
    assert sample.input[0].content == input_ref
    assert sample.messages[0].content == message_ref
    assert isinstance(sample.events[0], ModelEvent)
    assert sample.events[0].input[0].content == event_ref
    assert sample.attachments == {
        "input-ref": "resolved input",
        "message-ref": "resolved message",
        "event-ref": "resolved event",
    }


async def test_score_restores_sample_timelines() -> None:
    """Re-scoring should expose stored ``sample.timelines`` to scorers.

    During a live eval, solvers populate ``transcript().timelines`` via
    ``add_timeline()``; those timelines are persisted to ``sample.timelines``.
    When re-scoring a completed log, ``_run_score_task`` rebuilds the
    transcript from ``sample.events`` — this verifies it also restores
    ``sample.timelines`` so timeline-dependent scorers (e.g.
    ``inspect_scout.@scanner(timeline=True)``) work on re-score.
    """
    from inspect_ai._eval.score import _run_score_task
    from inspect_ai.event import Timeline, TimelineSpan
    from inspect_ai.log import EvalLog
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalPlanStep,
        EvalSpec,
    )
    from inspect_ai.log._transcript import transcript
    from inspect_ai.model._model import get_model

    stored = Timeline(
        name="target", description="", root=TimelineSpan(id="root-span", name="root")
    )
    sample = EvalSample(
        id="test-1",
        epoch=1,
        input="x",
        target="y",
        messages=[ChatMessageUser(role="user", content="x")],
        output=ModelOutput(
            choices=[ChatCompletionChoice(message=ChatMessageAssistant(content="y"))]
        ),
        timelines=[stored],
    )
    log_header = EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="t",
            task_id="t",
            run_id="r",
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="t", steps=[EvalPlanStep(solver="generate")], config=GenerateConfig()
        ),
    )

    seen: list[str] = []

    @scorer(metrics=[accuracy()])
    def timeline_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            seen.extend(tl.name for tl in transcript().timelines)
            return Score(value=1.0)

        return score

    await _run_score_task(
        log_header=log_header,
        sample=sample,
        scorers=[timeline_scorer()],
        model=get_model("mockllm/model"),
        model_roles={},
        action="append",
    )
    assert seen == ["target"]


def test_scorer_from_spec_resolves_registered_scanner() -> None:
    """``--scorer pkg/name`` must resolve ``@scanner`` objects, not just ``@scorer``.

    Scanners live under the ``scanner`` registry type. The ``file.py@name`` path of
    ``scorer_from_spec`` already checks both types (wrapping scanners via
    ``inspect_scout.as_scorer``); the registry-name path has to do the same so that
    e.g. ``inspect score log.eval --scorer inspect_petri/audit_judge`` works.
    """
    pytest.importorskip("inspect_scout")
    from inspect_scout import Result, Transcript, scanner

    from inspect_ai._eval.loader import scorer_from_spec
    from inspect_ai._util.registry import registry_info
    from inspect_ai.scorer._scorer import ScorerSpec

    @scanner(messages="all")
    def registry_only_scanner(threshold: int = 1) -> Any:
        async def scan(transcript: Transcript) -> Result:
            return Result(value=threshold)

        return scan

    resolved = scorer_from_spec(
        ScorerSpec(scorer="registry_only_scanner"), task_path=None, threshold=3
    )
    assert registry_info(resolved).type == "scorer"
    assert registry_info(resolved).name.endswith("registry_only_scanner")


def test_scorer_from_spec_unknown_name_is_prerequisite_error() -> None:
    """An unknown registry name should surface the guidance error, not a raw LookupError."""
    from inspect_ai._eval.loader import scorer_from_spec
    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.scorer._scorer import ScorerSpec

    with pytest.raises(PrerequisiteError, match="couldn't be loaded"):
        scorer_from_spec(ScorerSpec(scorer="no_such_scorer_anywhere"), task_path=None)


def test_scorer_from_spec_preserves_scorer_name_argument() -> None:
    from inspect_ai._eval.loader import scorer_from_spec
    from inspect_ai.scorer._scorer import ScorerSpec

    received_names: list[str] = []

    @scorer(metrics=[accuracy()])
    def scorer_with_name_argument(scorer_name: str) -> Scorer:
        received_names.append(scorer_name)

        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1)

        return score

    resolved = scorer_from_spec(
        ScorerSpec(scorer="scorer_with_name_argument"),
        task_path=None,
        scorer_name="custom",
    )
    assert callable(resolved)
    assert received_names == ["custom"]


def _named_scorers() -> dict[str, Scorer]:
    """Two `match` scorers under caller-chosen names."""
    return {
        "accuracy_strict": match(location="end"),
        "accuracy_loose": match(location="begin"),
    }


def _score_with_named_scorers() -> EvalLog:
    """`LOG_SCORED` rescored by `_named_scorers()`."""
    # match never calls a model, so name mockllm to keep this running without an
    # API key (score() otherwise resolves the header model and would raise).
    return score(
        log=read_eval_log(LOG_SCORED),
        scorers=_named_scorers(),
        model="mockllm/model",
    )


async def _score_async_with_named_scorers() -> EvalLog:
    """`LOG_SCORED` rescored by `_named_scorers()` through `score_async()`."""
    return await score_async(
        await read_eval_log_async(LOG_SCORED),
        _named_scorers(),
        model="mockllm/model",
    )


def _score_entries(log: EvalLog) -> list[dict[str, Any]]:
    """Name, scorer, params, reducer, metrics and metadata of each result entry."""
    assert log.results is not None
    return [
        entry.model_dump(
            include={"name", "scorer", "params", "reducer", "metrics", "metadata"}
        )
        for entry in log.results.scores
    ]


def _reductions(log: EvalLog) -> list[dict[str, Any]]:
    """Each sample reduction, with its score name and reduced values."""
    assert log.reductions is not None
    return [reduction.model_dump() for reduction in log.reductions]


def _sample_score_keys(log: EvalLog) -> list[list[str]]:
    """Score names on each sample."""
    assert log.samples is not None
    keys: list[list[str]] = []
    for sample in log.samples:
        assert sample.scores is not None
        keys.append(list(sample.scores))
    return keys


def test_score_dict_uses_keys_as_score_names() -> None:
    """Dict keys name the scores, next to existing scores of the same scorer."""
    expected = ["match", "accuracy_strict", "accuracy_loose"]

    log = read_eval_log(LOG_SCORED)
    scorers = {
        "accuracy_strict": match(location="end"),
        "accuracy_loose": match(location="begin"),
    }

    # match never calls a model, so name mockllm to keep this running without an
    # API key (score() otherwise resolves the header model and would raise).
    scored_log = score(log=log, scorers=scorers, model="mockllm/model")

    assert scored_log.samples is not None
    for sample in scored_log.samples:
        assert sample.scores is not None
        assert list(sample.scores) == expected

    assert scored_log.results is not None
    assert [(s.name, s.scorer) for s in scored_log.results.scores] == [
        (name, name) for name in expected
    ]

    assert scored_log.eval.scorers is not None
    header = scored_log.eval.scorers
    assert [s.name for s in header] == ["match"] * len(expected)
    assert [_score_name(s) or s.name for s in header] == expected


async def test_score_dict_names_survive_recompute_metrics() -> None:
    """Recomputing metrics keeps the score names a dict of scorers gave."""
    scored = await _score_async_with_named_scorers()
    entries = _score_entries(scored)
    reductions = _reductions(scored)
    keys = _sample_score_keys(scored)

    recompute_metrics(scored)

    assert _score_entries(scored) == entries
    assert _reductions(scored) == reductions
    assert _sample_score_keys(scored) == keys


async def test_score_dict_names_survive_rescoring_from_log() -> None:
    """Rescoring a log with scorers rebuilt from its header keeps the score names."""
    scored = await _score_async_with_named_scorers()
    rebuilt = named_scorers_from_log_header(scored, resolve_scorers(scored))
    rescored = await score_async(
        scored, rebuilt, action="overwrite", model="mockllm/model"
    )
    assert [entry["name"] for entry in _score_entries(rescored)] == [
        "match",
        "accuracy_strict",
        "accuracy_loose",
    ]


async def test_score_dict_name_already_in_log_is_error() -> None:
    """A dict key naming a score already in the log is an error when appending."""
    with pytest.raises(ValueError, match="already in the log: match"):
        await score_async(
            log=await read_eval_log_async(LOG_SCORED),
            scorers={"match": match(location="begin")},
            model="mockllm/model",
            action="append",
        )


async def test_score_dict_empty_name_is_error() -> None:
    """An empty dict key is an error."""
    with pytest.raises(ValueError, match="must be non-empty strings: ''"):
        await score_async(
            log=await read_eval_log_async(LOG_SCORED),
            scorers={"": match(location="begin")},
            model="mockllm/model",
        )


@scorer(metrics=[accuracy()], **{"__score_name__": "taken"})
def _reserved_key_scorer(scored_samples: list[int | str]) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        scored_samples.append(state.sample_id)
        return Score(value=1)

    return score


@pytest.mark.parametrize("as_dict", [True, False])
async def test_score_reserved_metadata_key_is_error(as_dict: bool) -> None:
    """A scorer using the metadata key reserved for score names fails before scoring."""
    scored_samples: list[int | str] = []
    reserved = _reserved_key_scorer(scored_samples)

    with pytest.raises(ValueError, match="reserved metadata key '__score_name__'"):
        await score_async(
            await read_eval_log_async(LOG_SCORED),
            {"reserved": reserved} if as_dict else [reserved],
            model="mockllm/model",
        )
    assert scored_samples == []


def test_eval_reserved_metadata_key_is_error() -> None:
    """An eval whose scorer uses the reserved metadata key fails before running."""
    task = Task(
        dataset=[Sample(input="Say hello", target="hello")],
        scorer=_reserved_key_scorer([]),
    )
    with pytest.raises(ValueError, match="reserved metadata key '__score_name__'"):
        eval(task, model="mockllm/model", display="none")


@pytest.mark.parametrize(
    ("recorded", "error"),
    [
        ("accuracy_strict", "duplicate score names: accuracy_strict"),
        ("", "Invalid '__score_name__'"),
        (None, "Invalid '__score_name__'"),
    ],
)
def test_score_dict_invalid_recorded_name_is_error(
    recorded: str | None, error: str
) -> None:
    """An invalid name recorded in the log header is an error on recompute."""
    scored = _score_with_named_scorers()
    assert scored.eval.scorers is not None
    loose = scored.eval.scorers[2]
    loose.metadata = {**(loose.metadata or {}), "__score_name__": recorded}

    with pytest.raises(ValueError, match=error):
        recompute_metrics(scored)


async def test_score_dict_name_of_existing_scorer_is_error() -> None:
    """A dict key naming an existing scorer whose scores have other names is an error."""

    @scorer(metrics={"helpful": [accuracy()], "harmless": [accuracy()]})
    def rubric() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value={"helpful": 1, "harmless": 0})

        return score

    log = await score_async(
        await read_eval_log_async(LOG_SCORED), [rubric()], model="mockllm/model"
    )
    assert log.results is not None
    assert {"helpful", "harmless"} <= {s.name for s in log.results.scores}

    with pytest.raises(ValueError, match="already in the log: rubric"):
        await score_async(
            log,
            {"rubric": match(location="begin")},
            model="mockllm/model",
            action="append",
        )


async def test_score_list_appended_to_named_log_records_its_names() -> None:
    """Scorers appended as a list to a log that records names record theirs too."""
    scored = await _score_async_with_named_scorers()
    assert scored.samples is not None
    for sample in scored.samples:
        assert sample.scores is not None
        # a score a solver set without a scorer takes the next generated name
        sample.scores["match1"] = Score(value="C")

    appended = await score_async(scored, [match()], model="mockllm/model")

    assert score_names_from_log_header(appended) == [
        "match",
        "accuracy_strict",
        "accuracy_loose",
        "match2",
    ]


@scorer(metrics=[accuracy()])
def _first_sample_only() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score | None:
        return Score(value=1) if state.sample_id == 1 else None

    return score


async def test_score_list_appended_to_named_log_uses_one_name_per_scorer(
    tmp_path: pathlib.Path,
) -> None:
    """A scorer appended to a log that records names gets one name on every sample."""
    task = Task(
        dataset=[
            Sample(input="a", target="a", id=1),
            Sample(input="b", target="b", id=2),
        ],
        scorer=exact(),
    )
    logs = await eval_async(task, model="mockllm/model", log_dir=str(tmp_path))
    named = await score_async(logs[0], {"match": _first_sample_only()})

    appended = await score_async(named, [match()])

    assert appended.samples is not None
    assert [sorted(sample.scores or {}) for sample in appended.samples] == [
        ["exact", "match", "match1"],
        ["exact", "match1"],
    ]


async def test_score_dict_name_with_no_scores_in_log_is_error() -> None:
    """A dict key naming a recorded scorer that produced no scores is an error."""

    @scorer(metrics=[])
    def never_scores() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score | None:
            return None

        return score

    log = await score_async(
        await read_eval_log_async(LOG_SCORED),
        {"silent": never_scores()},
        model="mockllm/model",
    )
    assert log.results is not None
    assert "silent" not in {eval_score.name for eval_score in log.results.scores}

    with pytest.raises(ValueError, match="already in the log: silent"):
        await score_async(
            log, {"silent": match()}, model="mockllm/model", action="append"
        )


async def _unscored_log(tmp_path: pathlib.Path) -> EvalLog:
    """A two-sample log of a `match()` task evaluated without scoring."""
    task = Task(
        dataset=[
            Sample(input="a", target="a", id=1),
            Sample(input="b", target="b", id=2),
        ],
        scorer=match(),
    )
    (unscored,) = await eval_async(
        task, model="mockllm/model", log_dir=str(tmp_path), score=False
    )
    return unscored


async def test_score_dict_name_of_unscored_header_scorer_is_allowed(
    tmp_path: pathlib.Path,
) -> None:
    """A dict key naming a header scorer that produced no scores is free when appending."""
    scored = await score_async(await _unscored_log(tmp_path), {"match": match()})

    assert _sample_score_keys(scored) == [["match"], ["match"]]
    assert [(entry["name"], entry["scorer"]) for entry in _score_entries(scored)] == [
        ("match", "match")
    ]


@pytest.mark.parametrize("score_name", ["match", "strict"])
async def test_score_dict_on_unscored_log_survives_recompute_metrics(
    tmp_path: pathlib.Path, score_name: str
) -> None:
    """Recomputing a log a dict scored after `--no-score` keeps its results and headline."""
    scored = await score_async(await _unscored_log(tmp_path), {score_name: match()})
    assert scored.results is not None
    entries = _score_entries(scored)
    reductions = _reductions(scored)
    headline = scored.results.headline

    recompute_metrics(scored)

    assert _score_entries(scored) == entries
    assert _reductions(scored) == reductions
    assert scored.results.headline == headline
    assert score_names_from_log_header(scored) == [score_name]


@scorer(metrics=[accuracy()])
def _counting_scorer(scored_samples: list[int | str]) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        scored_samples.append(state.sample_id)
        return Score(value=1)

    return score


@pytest.mark.parametrize("as_dict", [True, False])
async def test_score_invalid_recorded_name_fails_before_scoring(as_dict: bool) -> None:
    """An invalid name recorded in the header fails an append before any scoring."""
    scored = await _score_async_with_named_scorers()
    assert scored.eval.scorers is not None
    loose = scored.eval.scorers[2]
    loose.metadata = {**(loose.metadata or {}), "__score_name__": ""}
    scored_samples: list[int | str] = []
    counting = _counting_scorer(scored_samples)

    with pytest.raises(ValueError, match="Invalid '__score_name__'"):
        await score_async(
            scored,
            {"counted": counting} if as_dict else [counting],
            model="mockllm/model",
        )
    assert scored_samples == []


async def test_score_dict_names_with_no_samples() -> None:
    """With no samples to score, results still use the dict keys as score names."""
    log = await read_eval_log_async(LOG_SCORED)
    log.samples = []

    scored = await score_async(log, _named_scorers(), model="mockllm/model")

    assert scored.results is not None
    assert [eval_score.name for eval_score in scored.results.scores][-2:] == [
        "accuracy_strict",
        "accuracy_loose",
    ]


async def test_score_streamed_sample_name_conflict_fails_before_its_scorers() -> None:
    """A chosen name already on a streamed sample is an error before its scorers run."""
    scored = await _score_async_with_named_scorers()
    samples = scored.samples
    assert samples is not None
    for sample in samples:
        assert sample.scores is not None
        # on the samples only: not in the header or the results
        sample.scores["_counting_scorer"] = Score(value="C")
    header = scored.model_copy(update={"samples": None})

    @contextlib.asynccontextmanager
    async def read_sample(index: int) -> AsyncIterator[EvalSample]:
        yield samples[index]

    scored_samples: list[int | str] = []
    with pytest.raises(ValueError, match="already on sample"):
        await score_async(
            header,
            [_counting_scorer(scored_samples)],
            model="mockllm/model",
            samples=read_sample,
        )
    assert scored_samples == []


@scorer(metrics=[accuracy()])
def _blocking_scorer(started: anyio.Event, cancelled: list[int | str]) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        started.set()
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            cancelled.append(state.sample_id)
            raise
        return Score(value=1)

    return score


async def test_score_streamed_name_conflict_cancels_running_scorers() -> None:
    """A streamed name conflict cancels scorers running on other samples; readers close."""
    scored = await _score_async_with_named_scorers()
    samples = scored.samples
    assert samples is not None and samples[1].scores is not None
    # on the second sample only, so other samples' scorers are already running
    samples[1].scores["_blocking_scorer"] = Score(value="C")
    header = scored.model_copy(update={"samples": None})

    started = anyio.Event()
    opened: list[int] = []
    closed: list[int] = []

    @contextlib.asynccontextmanager
    async def read_sample(index: int) -> AsyncIterator[EvalSample]:
        if index == 1:
            await started.wait()
        opened.append(index)
        try:
            yield samples[index]
        finally:
            closed.append(index)

    cancelled: list[int | str] = []
    with anyio.fail_after(30), pytest.raises(ValueError, match="already on sample"):
        await score_async(
            header,
            [_blocking_scorer(started, cancelled)],
            model="mockllm/model",
            samples=read_sample,
        )
    assert cancelled
    assert samples[1].id not in cancelled
    assert 1 in opened
    assert sorted(closed) == sorted(opened)
