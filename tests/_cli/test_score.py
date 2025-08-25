import pathlib

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai._cli.score import score
from inspect_ai._eval.score import ScoreAction
from inspect_ai.log._file import read_eval_log_async

LOGS_DIR = pathlib.Path(__file__).parents[1] / "scorer/logs"
LOG_SCORED = (
    LOGS_DIR / "2025-02-11T15-18-04-05-00_popularity_mj7khqpMM4GBCfVQozKgzB.eval"
)
LOG_UNSCORED = (
    LOGS_DIR / "2025-02-11T15-17-00-05-00_popularity_dPiJifoWeEQBrfWsAopzWr.eval"
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("log_file", "action", "scorer", "expected_scores"),
    [
        pytest.param(
            LOG_UNSCORED, None, None, {"match": {"num_metrics": 2}}, id="unscored"
        ),
        pytest.param(
            LOG_UNSCORED,
            "overwrite",
            None,
            {"match": {"num_metrics": 2}},
            id="unscored-overwrite",
        ),
        pytest.param(
            LOG_UNSCORED,
            "append",
            ("f1", ("stop_words=[roasted]",)),
            {"f1": {"num_metrics": 2, "stop_words": ["roasted"]}},
            id="unscored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            ("f1", ("stop_words=[woah]",)),
            {
                "f1": {"num_metrics": 2, "stop_words": ["woah"]},
                "match": {"num_metrics": 2},
            },
            id="scored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "overwrite",
            ("f1", ("stop_words=[clowns]",)),
            {"f1": {"num_metrics": 2, "stop_words": ["clowns"]}},
            id="scored-overwrite",
        ),
    ],
)
@skip_if_no_openai
async def test_score(
    tmp_path: pathlib.Path,
    log_file: pathlib.Path,
    action: ScoreAction | None,
    scorer: tuple[str, tuple[str, ...]] | None,
    expected_scores: dict[str, dict[str, int]],
):
    output_file = tmp_path / "scored.eval"
    await score(
        log_dir="",
        log_file=str(log_file),
        action=action,
        log_level=None,
        output_file=str(output_file),
        overwrite=True,
        scorer=scorer[0] if scorer else None,
        s=scorer[1] if scorer else None,
    )
    scored_log = await read_eval_log_async(output_file)
    assert scored_log.results is not None

    scores = {score.name: score for score in scored_log.results.scores}
    assert [*scores] == [*expected_scores]
    for name, expected in expected_scores.items():
        assert len(scores[name].metrics.items()) == expected["num_metrics"]
        if expected_stop_words := expected.get("stop_words"):
            assert scores[name].params["stop_words"] == expected_stop_words
