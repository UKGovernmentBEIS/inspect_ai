import pathlib

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai._cli import score as score_cli
from inspect_ai._cli.score import score
from inspect_ai._eval.score import ScoreAction
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._file import read_eval_log, read_eval_log_async, write_eval_log
from inspect_ai.log._recorders import create_recorder_for_location

LOGS_DIR = pathlib.Path(__file__).parents[1] / "scorer/logs"
LOG_SCORED = (
    LOGS_DIR / "2025-02-11T15-18-04-05-00_popularity_mj7khqpMM4GBCfVQozKgzB.eval"
)
LOG_UNSCORED = (
    LOGS_DIR / "2025-02-11T15-17-00-05-00_popularity_dPiJifoWeEQBrfWsAopzWr.eval"
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stream",
    [
        pytest.param(True, id="stream"),
        pytest.param(False, id="no-stream"),
    ],
)
@pytest.mark.parametrize(
    ("log_file", "action", "scorer", "expected_scores", "metric"),
    [
        pytest.param(
            LOG_UNSCORED, None, None, {"match": {"num_metrics": 2}}, None, id="unscored"
        ),
        pytest.param(
            LOG_UNSCORED,
            "overwrite",
            None,
            {"match": {"num_metrics": 2}},
            None,
            id="unscored-overwrite",
        ),
        pytest.param(
            LOG_UNSCORED,
            "append",
            ("f1", ("stop_words=[roasted]",)),
            {"f1": {"num_metrics": 2, "stop_words": ["roasted"]}},
            None,
            id="unscored-append",
        ),
        pytest.param(
            LOG_SCORED,
            "append",
            ("f1", ("stop_words=[woah]",)),
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
            ("f1", ("stop_words=[clowns]",)),
            {"f1": {"num_metrics": 2, "stop_words": ["clowns"]}},
            None,
            id="scored-overwrite",
        ),
        pytest.param(
            LOG_UNSCORED,
            None,
            None,
            {"match": {"num_metrics": 1}},
            ("accuracy",),
            id="unscored-metric",
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
    stream: bool,
    metric: tuple[str, ...] | None,
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
        metric=metric,
        stream=stream,
    )
    scored_log = await read_eval_log_async(output_file)
    assert scored_log.results is not None

    scores = {score.name: score for score in scored_log.results.scores}
    assert [*scores] == [*expected_scores]
    for name, expected in expected_scores.items():
        assert len(scores[name].metrics.items()) == expected["num_metrics"]
        if expected_stop_words := expected.get("stop_words"):
            assert scores[name].params["stop_words"] == expected_stop_words


@pytest.mark.anyio
async def test_score_stream_preserves_log_updates(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_file = tmp_path / LOG_SCORED.name
    output_file = tmp_path / "rescored.eval"

    log = read_eval_log(str(LOG_SCORED))
    log = edit_eval_log(
        log,
        [
            TagsEdit(tags_add=["qa_reviewed"]),
            MetadataEdit(metadata_set={"reviewer": "alice"}),
        ],
        ProvenanceData(author="alice", reason="qa"),
    )
    write_eval_log(log, str(input_file))

    monkeypatch.setattr(score_cli, "init_eval_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(score_cli, "print_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        score_cli, "resolve_scorers", lambda *args, **kwargs: [object()]
    )

    async def fake_score_async(
        *, log, scorers, metrics, model, model_roles, action, copy, samples
    ):
        assert samples is not None
        return log

    monkeypatch.setattr(score_cli, "score_async", fake_score_async)

    await score(
        log_dir="",
        log_file=str(input_file),
        action="overwrite",
        log_level=None,
        output_file=str(output_file),
        overwrite=True,
        scorer="match",
        s=(),
        metric=None,
        stream=True,
    )

    rescored_log = await read_eval_log_async(output_file)
    assert rescored_log.log_updates == log.log_updates
    assert rescored_log.tags == log.tags
    assert rescored_log.metadata == log.metadata


@pytest.mark.anyio
async def test_score_stream_flushes_periodically(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_file = tmp_path / "rescored.eval"
    flush_counts: list[int] = []

    class FlushTrackingRecorder:
        def __init__(self, recorder):
            self.recorder = recorder
            self.flush_count = 0

        def __getattr__(self, name):
            return getattr(self.recorder, name)

        async def flush(self, eval):
            self.flush_count += 1
            flush_counts.append(self.flush_count)
            await self.recorder.flush(eval)

    def create_recorder(location: str, log_dir: str):
        recorder = create_recorder_for_location(location, log_dir)
        if pathlib.Path(location) == output_file:
            return FlushTrackingRecorder(recorder)
        return recorder

    monkeypatch.setattr(
        "inspect_ai._cli.score.create_recorder_for_location", create_recorder
    )
    monkeypatch.setattr(score_cli, "init_eval_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(score_cli, "print_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        score_cli, "resolve_scorers", lambda *args, **kwargs: [object()]
    )

    async def fake_score_async(
        *, log, scorers, metrics, model, model_roles, action, copy, samples
    ):
        assert samples is not None
        for idx in range(10):
            async with samples(idx):
                pass
        return log

    monkeypatch.setattr(score_cli, "score_async", fake_score_async)

    await score(
        log_dir="",
        log_file=str(LOG_SCORED),
        action="overwrite",
        log_level=None,
        output_file=str(output_file),
        overwrite=True,
        scorer="match",
        s=(),
        metric=None,
        stream=3,
    )

    assert flush_counts == [1, 2, 3]
