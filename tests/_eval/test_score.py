import pathlib
from typing import Any

import pydantic
import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai._eval.score import (
    ScoreAction,
    _get_updated_events,
    _get_updated_scores,
    resolve_scorers,
    score_async,
)
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalSample,
    Event,
    InputEvent,
    ModelEvent,
    SampleInitEvent,
    ScoreEvent,
    Transcript,
)
from inspect_ai.log._file import read_eval_log_async
from inspect_ai.log._transcript import init_transcript
from inspect_ai.model import ChatCompletionChoice, GenerateConfig, ModelOutput
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.scorer._metric import SampleScore, Score
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
    transcript: Transcript

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
        id="1", events=existing_events, epoch=1, input="input", target="target"
    )

    updated_events = _get_updated_events(sample, transcript, action=test_case.action)

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


@pytest.mark.parametrize(
    ("log_file", "action", "scorer", "expected_scores"),
    [
        pytest.param(
            LOG_UNSCORED,
            None,
            ("match", {}),
            {"match": {"num_metrics": 2}},
            id="unscored",
        ),
        pytest.param(
            LOG_UNSCORED,
            "overwrite",
            ("match", {}),
            {"match": {"num_metrics": 2}},
            id="unscored-overwrite",
        ),
        pytest.param(
            LOG_UNSCORED,
            "append",
            ("f1", {"stop_words": ["roasted"]}),
            {"f1": {"num_metrics": 2, "stop_words": ["roasted"]}},
            id="unscored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            ("f1", {"stop_words": ["woah"]}),
            {
                "f1": {"num_metrics": 2, "stop_words": ["woah"]},
                "match": {"num_metrics": 2},
            },
            id="scored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "overwrite",
            ("f1", {"stop_words": ["clowns"]}),
            {"f1": {"num_metrics": 2, "stop_words": ["clowns"]}},
            id="scored-overwrite",
        ),
    ],
)
@pytest.mark.anyio
@skip_if_no_openai
async def test_score(
    log_file: pathlib.Path,
    action: ScoreAction | None,
    scorer: tuple[str, dict[str, Any]],
    expected_scores: dict[str, dict[str, int]],
):
    unscored_log = await read_eval_log_async(log_file)

    scored_log = await score_async(
        log=unscored_log,
        scorers=resolve_scorers(unscored_log, scorer[0], scorer[1]),
        action=action,
    )

    assert scored_log.results is not None
    scores = {score.name: score for score in scored_log.results.scores}
    assert [*scores] == [*expected_scores]
    for score_name, expected_score in expected_scores.items():
        assert len(scores[score_name].metrics.items()) == expected_score["num_metrics"]
        if expected_stop_words := expected_score.get("stop_words"):
            assert scores[score_name].params["stop_words"] == expected_stop_words
