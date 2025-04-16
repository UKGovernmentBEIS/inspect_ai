import os

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai._eval.score import task_score
from inspect_ai.log._file import read_eval_log_async

LOG_SCORED = os.path.join(
    "tests",
    "scorer",
    "logs",
    "2025-02-11T15-18-04-05-00_popularity_mj7khqpMM4GBCfVQozKgzB.eval",
)

LOG_UNSCORED = os.path.join(
    "tests",
    "scorer",
    "logs",
    "2025-02-11T15-17-00-05-00_popularity_dPiJifoWeEQBrfWsAopzWr.eval",
)


@pytest.mark.anyio
@skip_if_no_openai
async def test_score_unscored():
    unscored_log = await read_eval_log_async(LOG_UNSCORED)
    scored_log = await task_score(log=unscored_log)
    assert len(scored_log.results.scores) == 1
    assert scored_log.results.scores[0].name == "match"

    metrics = scored_log.results.scores[0].metrics
    assert len(metrics.items()) == 2


@pytest.mark.anyio
@skip_if_no_openai
async def test_score_unscored_new_scorer():
    unscored_log = await read_eval_log_async(LOG_UNSCORED)
    scored_log = await task_score(
        log=unscored_log, scorer="f1", scorer_args={"stop_words": ["roasted"]}
    )
    assert len(scored_log.results.scores) == 1
    assert scored_log.results.scores[0].name == "f1"
    assert scored_log.results.scores[0].params["stop_words"] == ["roasted"]

    metrics = scored_log.results.scores[0].metrics
    assert len(metrics.items()) == 2


@pytest.mark.anyio
@skip_if_no_openai
async def test_score_scored_append():
    unscored_log = await read_eval_log_async(LOG_SCORED)
    scored_log = await task_score(
        log=unscored_log, scorer="f1", scorer_args={"stop_words": ["woah"]}
    )
    assert len(scored_log.results.scores) == 2

    metrics2 = scored_log.results.scores[0].metrics
    assert scored_log.results.scores[0].name == "f1"
    assert scored_log.results.scores[0].params["stop_words"] == ["woah"]
    assert len(metrics2.items()) == 2

    metrics = scored_log.results.scores[1].metrics
    assert scored_log.results.scores[1].name == "match"
    assert len(metrics.items()) == 2


@pytest.mark.anyio
@skip_if_no_openai
async def test_score_scored_overwrite():
    unscored_log = await read_eval_log_async(LOG_SCORED)
    scored_log = await task_score(
        log=unscored_log,
        scorer="f1",
        scorer_args={"stop_words": ["clowns"]},
        action="overwrite",
    )
    assert len(scored_log.results.scores) == 1

    assert scored_log.results.scores[0].name == "f1"
    assert scored_log.results.scores[0].params["stop_words"] == ["clowns"]

    metrics = scored_log.results.scores[0].metrics
    assert len(metrics.items()) == 2
