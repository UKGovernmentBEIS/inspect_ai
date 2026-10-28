import contextlib
import functools
import pathlib
from typing import Any, Iterator

import pydantic
import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai import score
from inspect_ai._eval.score import (
    ScoreAction,
    _get_updated_events,
    _get_updated_scores,
    resolve_scorers,
    score_async,
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
)
from inspect_ai.log._file import read_eval_log, read_eval_log_async
from inspect_ai.log._transcript import init_transcript
from inspect_ai.model import ChatCompletionChoice, GenerateConfig, ModelOutput
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.scorer import accuracy
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


# --- scorer names from the log -------------------------------------------------

FILE_SCORER = "recorded_file_scorer"


@pytest.fixture
def imports(tmp_path: pathlib.Path) -> pathlib.Path:
    """File the marker modules append to when imported."""
    return tmp_path / "imports.txt"


def _imported(imports: pathlib.Path) -> list[str]:
    return imports.read_text().splitlines() if imports.exists() else []


@pytest.fixture
def scorer_file(
    tmp_path: pathlib.Path, imports: pathlib.Path
) -> Iterator[pathlib.Path]:
    """A task file that records its import and defines FILE_SCORER."""
    from inspect_ai._util.registry import _registry, registry_key

    path = tmp_path / "scorer_task.py"
    path.write_text(
        f"with open({str(imports)!r}, 'a') as f:\n    f.write(__file__ + '\\n')\n"
        + f"""
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState


@scorer(metrics=[accuracy()])
def {FILE_SCORER}() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return score
"""
    )
    yield path
    _registry.pop(registry_key("scorer", FILE_SCORER), None)


def _scorer_log(
    name: str,
    task_file: pathlib.Path | str | None = None,
    options: dict[str, Any] | None = None,
    legacy: bool = False,
) -> EvalLog:
    """Log naming one scorer, in `eval.scorers` or (legacy) only in `results.scores`."""
    from datetime import datetime, timezone

    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalResults,
        EvalScore,
        EvalScorer,
        EvalSpec,
    )

    return EvalLog(
        eval=EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="scorer_task",
            task_file=str(task_file) if task_file else None,
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
            scorers=None if legacy else [EvalScorer(name=name, options=options)],
        ),
        results=EvalResults(
            scores=[EvalScore(name=name, scorer=name, params=options or {})]
        )
        if legacy
        else None,
    )


@pytest.fixture
def fresh_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start with no display, display type or Rich console, as a new process does.

    Earlier tests leave these set (a quiet console, a cached display), which
    would hide or redirect the output these tests capture. The new console is
    wide enough not to wrap the long temporary paths in that output.
    """
    import rich

    from inspect_ai._display.core import active
    from inspect_ai.util import _display

    monkeypatch.setattr(active, "_active_display", None)
    monkeypatch.setattr(_display, "_display_type", None)
    monkeypatch.setattr(rich, "_console", None)
    monkeypatch.setenv("COLUMNS", "1000")


def _printed(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def _record(path: pathlib.Path, scorer: str) -> str:
    return (
        f"Imported task file {path.absolute().as_posix()} "
        f"(recorded in the log) to load scorer '{scorer}'."
    )


@pytest.mark.parametrize("legacy", [False, True], ids=["eval_scorers", "results"])
@pytest.mark.parametrize("form", ["at", "path"])
def test_recorded_scorer_name_is_not_imported_as_a_path(
    scorer_file: pathlib.Path, imports: pathlib.Path, form: str, legacy: bool
) -> None:
    from inspect_ai._util.error import PrerequisiteError

    name = f"{scorer_file}@{FILE_SCORER}" if form == "at" else str(scorer_file)
    with pytest.raises(PrerequisiteError, match="couldn't be loaded"):
        resolve_scorers(_scorer_log(name, legacy=legacy))
    assert _imported(imports) == []


@pytest.mark.parametrize("source", ["recorded", "bare_scorer_option"])
def test_unregistered_scorer_loads_from_recorded_task_file(
    scorer_file: pathlib.Path,
    imports: pathlib.Path,
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    fresh_display: None,
) -> None:
    from inspect_ai._util.registry import registry_info
    from inspect_ai.util._display import init_display_type

    # the CLI chooses the display at startup
    init_display_type("plain")
    # the log records the task file relative to the working directory
    monkeypatch.chdir(scorer_file.parent)
    if source == "recorded":
        log = _scorer_log(FILE_SCORER, task_file=scorer_file.name)
        scorer_arg = None
    else:
        log = _scorer_log("match", task_file=scorer_file.name)
        scorer_arg = FILE_SCORER

    with caplog.at_level("INFO", logger="inspect_ai._eval.loader"):
        scorers = resolve_scorers(log, scorer_arg)

    assert registry_info(scorers[0]).name == FILE_SCORER
    assert len(_imported(imports)) == 1
    record = _record(pathlib.Path.cwd() / scorer_file.name, FILE_SCORER)
    assert record in _printed(capsys)
    assert record in caplog.text


@scorer(metrics=[accuracy()])
def value_error_scorer(mode: str = "ok") -> Scorer:
    if mode != "ok":
        raise ValueError(f"invalid mode {mode}")

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return score


def test_registered_scorer_rejecting_options_falls_back_to_task_file(
    scorer_file: pathlib.Path,
    imports: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    fresh_display: None,
) -> None:
    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.util._display import init_display_type

    init_display_type("plain")
    log = _scorer_log("value_error_scorer", scorer_file, options={"mode": "bad"})
    with pytest.raises(PrerequisiteError, match="in the file"):
        resolve_scorers(log)
    assert len(_imported(imports)) == 1
    assert _record(scorer_file, "value_error_scorer") in _printed(capsys)


def test_scorer_option_file_spec_still_loads_that_file(
    scorer_file: pathlib.Path, imports: pathlib.Path
) -> None:
    from inspect_ai._util.registry import registry_info

    scorers = resolve_scorers(_scorer_log("match"), f"{scorer_file}@{FILE_SCORER}")
    assert registry_info(scorers[0]).name == FILE_SCORER
    assert len(_imported(imports)) == 1


received_names: list[str] = []


@scorer(metrics=[accuracy()])
def name_option_scorer(name: str) -> Scorer:
    received_names.append(name)

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return score


def test_recorded_scorer_option_called_name_reaches_factory() -> None:
    received_names.clear()
    resolve_scorers(_scorer_log("name_option_scorer", options={"name": "custom"}))
    assert received_names == ["custom"]


LOG_BASE_URL = "https://scoring.invalid/v1"


@pytest.fixture
def base_url_log(tmp_path: pathlib.Path) -> pathlib.Path:
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.log import write_eval_log
    from inspect_ai.scorer import match

    log = inspect_eval(
        Task(dataset=[Sample(input="a", target="a")], scorer=match()),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
    )[0]
    log.eval.model_base_url = LOG_BASE_URL
    path = tmp_path / "base_url.eval"
    write_eval_log(log, str(path))
    return path


def test_score_command_prints_log_model_base_url(
    base_url_log: pathlib.Path, tmp_path: pathlib.Path, fresh_display: None
) -> None:
    from click.testing import CliRunner

    from inspect_ai._cli.score import score_command

    output = tmp_path / "scored.eval"
    args = [str(base_url_log), "--scorer", "match", "--action", "append"]
    result = CliRunner().invoke(score_command, [*args, "--output-file", str(output)])
    assert result.exit_code == 0, result.output
    record = f"Scoring model mockllm/model from the log, base URL {LOG_BASE_URL}."
    assert record in result.output

    result = CliRunner().invoke(
        score_command,
        [
            *args,
            "--model",
            "mockllm/model",
            "--output-file",
            str(output),
            "--overwrite",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Scoring model" not in result.output


@pytest.mark.parametrize("display", [None, "none"])
async def test_fallback_record_leaves_the_scoring_display_to_the_caller(
    base_url_log: pathlib.Path,
    scorer_file: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    display: Any,
    fresh_display: None,
) -> None:
    from inspect_ai._display.core.active import active_display
    from inspect_ai.util._display import display_type, display_type_initialized

    with caplog.at_level("INFO", logger="inspect_ai._eval.loader"):
        scorers = resolve_scorers(_scorer_log(FILE_SCORER, task_file=scorer_file))
    assert _record(scorer_file, FILE_SCORER) in caplog.text
    # nothing printed, so no display was chosen or created
    assert not display_type_initialized() and active_display() is None

    await score_async(
        await read_eval_log_async(base_url_log),
        scorers,
        action="append",
        display=display,
    )
    assert display_type() == (display or "plain")


def _prompting_log(
    base_url_log: pathlib.Path, scorer_file: pathlib.Path, trigger: str
) -> pathlib.Path:
    """A scored log whose rescoring prints a record of the given kind."""
    from inspect_ai.log import write_eval_log
    from inspect_ai.log._log import EvalScorer

    log = read_eval_log(base_url_log)
    if trigger == "fallback":
        log.eval.model_base_url = None
        log.eval.task_file = str(scorer_file)
        log.eval.scorers = [EvalScorer(name=FILE_SCORER)]
    path = base_url_log.parent / f"{trigger}.eval"
    write_eval_log(log, str(path))
    return path


@pytest.mark.parametrize("trigger", ["base_url", "fallback"])
def test_score_command_prompts_stay_visible_with_display_none(
    base_url_log: pathlib.Path,
    scorer_file: pathlib.Path,
    trigger: str,
    fresh_display: None,
) -> None:
    from click.testing import CliRunner

    from inspect_ai._cli.score import score_command

    log_file = _prompting_log(base_url_log, scorer_file, trigger)
    args = [str(log_file), "--display", "none"]
    if trigger == "base_url":
        args += ["--scorer", "match"]
    # append to the scores, create a new file, accept the suggested name
    result = CliRunner().invoke(score_command, args, input="append\ncreate\n\n")
    assert result.exit_code == 0, result.output

    output = result.output
    assert "Overwrite existing scores or append as additional scores?" in output
    assert f"Overwrite {log_file} or create new file?" in output
    assert "Output file name?" in output
    assert "Scoring model" not in output and "Imported task file" not in output


def test_score_logs_log_model_base_url(
    base_url_log: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    from inspect_ai.scorer import match

    log = read_eval_log(base_url_log)
    with caplog.at_level("INFO", logger="inspect_ai._eval.score"):
        score(log, match(), action="append")
    assert f"base URL {LOG_BASE_URL}" in caplog.text


def test_records_escape_control_characters_from_the_log(
    scorer_file: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    from inspect_ai._eval.score import log_model_record
    from inspect_ai._util.error import PrerequisiteError

    # a carriage return and an erase-line sequence could overwrite the record
    control = "\r\x1b[2K"
    log = _scorer_log(f"evil{control}name", task_file=scorer_file)
    log.eval.model_base_url = f"https://scoring.invalid/{control}v1"

    assert log_model_record(log) == (
        "Scoring model mockllm/model from the log, "
        "base URL https://scoring.invalid/\\r\\x1b[2Kv1."
    )
    with caplog.at_level("INFO", logger="inspect_ai._eval.loader"):
        with pytest.raises(PrerequisiteError):
            resolve_scorers(log)
    assert _record(scorer_file, "evil\\r\\x1b[2Kname") in caplog.text
    assert control not in caplog.text


def test_score_command_help_says_trusted_logs_only() -> None:
    from click.testing import CliRunner

    from inspect_ai._cli.score import score_command

    result = CliRunner().invoke(score_command, ["--help"])
    help_text = " ".join(result.output.split())
    assert "Only run it on logs you trust." in help_text
    assert "the log's metrics are rebuilt without importing its task file" in help_text
