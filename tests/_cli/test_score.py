import pathlib

import pytest
import rich
from test_helpers.utils import skip_if_no_openai

from inspect_ai._cli import score as score_cli
from inspect_ai._cli.score import print_results, score
from inspect_ai._display import display
from inspect_ai._display.core.results import sample_coverage_messages
from inspect_ai._eval.score import ScoreAction
from inspect_ai.log import EvalLog, read_eval_log_async, write_eval_log_async
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalMetric,
    EvalResults,
    EvalScore,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders import create_recorder_for_location
from inspect_ai.util._early_stopping import EarlyStop, EarlyStoppingSummary

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

    log = await read_eval_log_async(str(LOG_SCORED))
    log = edit_eval_log(
        log,
        [
            TagsEdit(tags_add=["qa_reviewed"]),
            MetadataEdit(metadata_set={"reviewer": "alice"}),
        ],
        ProvenanceData(author="alice", reason="qa"),
    )
    await write_eval_log_async(log, str(input_file))

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


def early_stops(count: int) -> EarlyStoppingSummary:
    return EarlyStoppingSummary(
        manager="test",
        early_stops=[EarlyStop(id=i, epoch=1) for i in range(count)],
        metadata={},
    )


def messages(
    total_samples: int,
    completed_samples: int,
    early_stopping: EarlyStoppingSummary | None = None,
    score_on_error: bool | None = False,
) -> list[str]:
    return sample_coverage_messages(
        total_samples=total_samples,
        completed_samples=completed_samples,
        early_stopping=early_stopping,
        score_on_error=score_on_error,
    )


def test_no_messages_when_every_sample_completed() -> None:
    assert messages(total_samples=10, completed_samples=10) == []


def test_errors_are_reported_with_the_unscored_qualifier() -> None:
    (warning,) = messages(total_samples=10, completed_samples=5)
    assert "5 of 10 executed samples (50%) had errors and were not scored" in warning


def test_error_percentage_is_taken_over_executed_not_planned_samples() -> None:
    """With early stops the two denominators differ: 2 of 6, not 2 of 10."""
    _, warning = messages(
        total_samples=10, completed_samples=4, early_stopping=early_stops(4)
    )
    assert "2 of 6 executed samples (33%) had errors" in warning


def test_no_messages_when_an_overwritten_log_has_lost_its_stopped_samples() -> None:
    """`--action overwrite` leaves total == completed over the surviving samples.

    The early-stopping summary rides along with the original count, so without
    the guard this renders a NOTE reading "4 of 6 samples (66%)".
    """
    assert (
        messages(total_samples=6, completed_samples=6, early_stopping=early_stops(4))
        == []
    )


def test_score_on_error_drops_the_unscored_qualifier() -> None:
    (warning,) = messages(total_samples=10, completed_samples=5, score_on_error=True)
    assert "had errors." in warning
    assert "were not scored" not in warning


def test_early_stops_are_excluded_from_the_error_remainder() -> None:
    """An early stop is a deliberate outcome, not an error.

    Counting it as one would contradict the NOTE rendered directly above: with
    4 stopped and 6 executed of which all completed, `total - completed` is 4,
    but there are no errors to report.
    """
    note = messages(
        total_samples=10,
        completed_samples=6,
        early_stopping=early_stops(4),
    )
    assert len(note) == 1
    assert "4 of 10 samples (40%) were not executed due to early stopping" in note[0]
    assert "WARNING" not in note[0]


def test_early_stops_and_errors_are_reported_separately() -> None:
    note, warning = messages(
        total_samples=10,
        completed_samples=4,
        early_stopping=early_stops(4),
    )
    assert "4 of 10 samples (40%) were not executed due to early stopping" in note
    # 6 executed, 4 completed: the error percentage is over the executed count,
    # not the planned one, so this is 2/6 rather than 2/10.
    assert "2 of 6 executed samples (33%) had errors" in warning


def _log(total_samples: int, completed_samples: int) -> EvalLog:
    return EvalLog(
        eval=EvalSpec(
            task="demo",
            dataset=EvalDataset(samples=total_samples),
            model="mockllm/model",
            config=EvalConfig(score_on_error=False),
            created="2026-08-24",
        ),
        results=EvalResults(
            total_samples=total_samples,
            completed_samples=completed_samples,
            scores=[
                EvalScore(
                    name="accuracy",
                    scorer="match",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=1.0)},
                )
            ],
        ),
        stats=EvalStats(started_at="", completed_at="", model_usage={}),
    )


def rendered(log: EvalLog, coverage: EvalResults | None = None) -> str:
    # `print_results` calls `display()`, which reconfigures the global console.
    # Doing that inside the capture resets the buffer and yields an empty
    # string, so initialise the display first.
    display()
    console = rich.get_console()
    with console.capture() as capture:
        print_results("/tmp/demo.eval", log, coverage=coverage)
    return capture.get()


def test_score_cli_reports_samples_that_errored() -> None:
    """A re-scored log that lost half its samples must not read as a complete run."""
    output = rendered(_log(total_samples=10, completed_samples=5))
    assert "accuracy" in output
    assert "5 of 10 executed samples (50%) had errors." in output
    # this pass scored those samples, so the eval-time qualifier would be false
    assert "were not scored" not in output


def test_score_cli_stays_quiet_on_a_complete_run() -> None:
    output = rendered(_log(total_samples=10, completed_samples=10))
    assert "accuracy" in output
    assert "WARNING" not in output


@pytest.mark.parametrize("completed", [0, 1, 9])
def test_score_cli_reports_every_partial_run(completed: int) -> None:
    output = rendered(_log(total_samples=10, completed_samples=completed))
    assert f"{10 - completed} of 10 executed samples" in output


def test_score_cli_uses_the_pre_score_coverage_when_results_were_overwritten() -> None:
    """`--action overwrite` recounts `total_samples` over the samples in the log.

    Early-stopped samples were never written, so those counts do not share a
    denominator with the early-stopping summary carried forward from the
    header. Reading coverage from the post-score results turns a run of 10 with
    4 stopped and 2 errored into "4 of 6 (66%)", and drops the error warning
    entirely, because the remainder goes negative.
    """
    overwritten = _log(total_samples=6, completed_samples=4)
    assert overwritten.results is not None
    overwritten.results.early_stopping = early_stops(4)

    before = EvalResults(
        total_samples=10, completed_samples=4, early_stopping=early_stops(4)
    )
    output = rendered(overwritten, coverage=before)

    assert "4 of 10 samples (40%) were not executed due to early stopping" in output
    assert "2 of 6 executed samples (33%) had errors" in output


@pytest.mark.anyio
async def test_score_reads_coverage_before_the_scoring_pass_replaces_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage must be captured before `score_async`, not read back after it.

    `--action overwrite` replaces `results` with counts taken over the samples
    present in the log. Early-stopped samples were never written, so reading
    coverage afterwards reports them against the surviving count.
    """
    input_file = tmp_path / LOG_SCORED.name
    output_file = tmp_path / "rescored.eval"

    log = await read_eval_log_async(str(LOG_SCORED))
    assert log.results is not None
    log.results.total_samples = 10
    log.results.completed_samples = 4
    log.results.early_stopping = early_stops(4)
    await write_eval_log_async(log, str(input_file))

    captured: list[EvalResults | None] = []

    monkeypatch.setattr(score_cli, "init_eval_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        score_cli,
        "print_results",
        lambda *args, coverage=None, **kwargs: captured.append(coverage),
    )
    monkeypatch.setattr(
        score_cli, "resolve_scorers", lambda *args, **kwargs: [object()]
    )

    async def fake_score_async(*, log, **kwargs):
        # what `--action overwrite` leaves behind: recounted over the 6 samples
        # still in the log, with the original early-stopping summary carried on
        log.results = EvalResults(
            total_samples=6, completed_samples=6, early_stopping=early_stops(4)
        )
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
        stream=False,
    )

    (coverage,) = captured
    assert coverage is not None
    assert (coverage.total_samples, coverage.completed_samples) == (10, 4)
