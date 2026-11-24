import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from inspect_scout import Result, Scanner, Transcript, scanner, transcripts_from
from inspect_scout.aio import scan_async
from test_helpers.utils import skip_if_trio

from inspect_ai._eval.scan_results import import_scan_results_async
from inspect_ai._eval.score import resolve_scorers
from inspect_ai.log import write_eval_log_async
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalMetric,
    EvalResults,
    EvalSample,
    EvalScore,
    EvalScorer,
    EvalSpec,
)
from inspect_ai.log._metric import recompute_metrics
from inspect_ai.scorer import Score


@scanner(name="scan_import_e2e", messages="all")
def scan_import_e2e() -> Scanner[Transcript]:
    async def scan_transcript(transcript: Transcript) -> Result:
        return Result(
            value=True,
            explanation=f"Imported {transcript.transcript_id}",
            metadata={"origin": "e2e"},
        )

    return scan_transcript


def _log() -> EvalLog:
    samples = [
        EvalSample(
            id=index,
            epoch=1,
            input=f"input {index}",
            target="target",
            uuid=f"uuid-{index}",
            scores={"existing": Score(value=index)},
        )
        for index in range(1, 4)
    ]
    return EvalLog(
        status="success",
        eval=EvalSpec(
            eval_id="eval-1",
            created="2026-08-08T00:00:00Z",
            task="scan_import_test",
            dataset=EvalDataset(samples=3),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        samples=samples,
        results=EvalResults(
            total_samples=3,
            completed_samples=3,
            scores=[
                EvalScore(
                    name="existing",
                    scorer="existing",
                    metrics={"mean": EvalMetric(name="mean", value=2)},
                )
            ],
        ),
    )


def _row(
    transcript_id: str,
    value: Any,
    value_type: str,
    *,
    source_id: str = "eval-1",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "transcript_id": transcript_id,
        "transcript_source_id": source_id,
        "value": value,
        "value_type": value_type,
        "answer": None,
        "explanation": None,
        "metadata": "{}",
        "message_references": "[]",
        "event_references": "[]",
        "scan_error": None,
        **extra,
    }


def _scan(
    frames: dict[str, pd.DataFrame],
    *,
    complete: bool = True,
    errors: list[Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(complete=complete, errors=errors or [], scanners=frames)


def _install_scan(monkeypatch: pytest.MonkeyPatch, scan: SimpleNamespace) -> None:
    async def scan_results_df_async(
        scan_location: str, *, rows: str
    ) -> SimpleNamespace:
        assert scan_location == "scan-dir"
        assert rows == "transcripts"
        return scan

    monkeypatch.setattr(
        "inspect_scout.aio.scan_results_df_async", scan_results_df_async
    )


@pytest.mark.anyio
async def test_import_sparse_multiple_scanners_and_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    for sample in log.samples or []:
        sample.scores = {"risk": Score(value=0)}
    assert log.results is not None
    log.results.scores[0].name = "risk"

    scan = _scan(
        {
            "risk": pd.DataFrame(
                [
                    _row(
                        "uuid-1",
                        True,
                        "boolean",
                        answer="yes",
                        explanation="matched policy",
                        metadata='{"threshold":0.8}',
                        message_references='[{"type":"message","id":"m1"}]',
                    )
                ]
            ),
            "quality": pd.DataFrame([_row("uuid-2", "0.75", "number")]),
        },
    )
    _install_scan(monkeypatch, scan)

    imported = await import_scan_results_async(log, "scan-dir", action="append")

    assert imported is not log
    assert imported.samples is not None
    assert set(imported.samples[0].scores or {}) == {"risk", "risk-1"}
    risk = (imported.samples[0].scores or {})["risk-1"]
    assert risk.value is True
    assert risk.answer == "yes"
    assert risk.explanation == "matched policy"
    assert risk.metadata == {
        "threshold": 0.8,
        "scanner_references": [{"type": "message", "id": "m1"}],
    }
    assert (imported.samples[1].scores or {})["quality"].value == 0.75
    assert "quality" not in (imported.samples[2].scores or {})
    assert imported.results is not None
    assert [score.name for score in imported.results.scores] == [
        "risk",
        "risk-1",
        "quality",
    ]
    assert imported.results.scores[1].metrics["mean"].value == 1.0
    assert set(imported.results.scores[2].metrics) == {"mean", "stderr"}


@pytest.mark.anyio
async def test_import_resultset_overwrites_existing_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    resultset = [
        {"label": "safe", "value": True},
        {
            "label": "details",
            "value": {"severity": 2},
            "explanation": "nested context",
            "metadata": {"reviewed": True},
            "references": [{"type": "event", "id": "event-1"}],
        },
    ]
    scan = _scan(
        {"labels": pd.DataFrame([_row("uuid-1", json.dumps(resultset), "resultset")])},
    )
    _install_scan(monkeypatch, scan)

    imported = await import_scan_results_async(log, "scan-dir", action="overwrite")

    assert imported.samples is not None
    score_value = (imported.samples[0].scores or {})["labels"].value
    assert isinstance(score_value, dict)
    assert score_value["safe"] is True
    assert json.loads(str(score_value["details"])) == {"severity": 2}
    score_metadata = (imported.samples[0].scores or {})["labels"].metadata
    assert score_metadata is not None
    assert score_metadata["scanner_results"][1]["explanation"] == "nested context"
    assert imported.samples[1].scores == {}
    assert imported.results is not None
    # a result set is not numeric: it gets no metrics and no results entry
    assert imported.results.scores == []
    assert [scorer.name for scorer in imported.eval.scorers or []] == ["labels"]
    # rescoring the log does not try to load the scanner as a scorer
    assert resolve_scorers(imported) == []


@pytest.mark.anyio
async def test_import_rejects_foreign_rows_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    original = log.model_dump()
    scan = _scan(
        {
            "risk": pd.DataFrame(
                [
                    _row("uuid-1", True, "boolean"),
                    _row("foreign-uuid", False, "boolean", source_id="eval-2"),
                ]
            )
        }
    )
    _install_scan(monkeypatch, scan)

    with pytest.raises(ValueError, match="not this log's eval"):
        await import_scan_results_async(log, "scan-dir", action="overwrite", copy=False)

    assert log.model_dump() == original


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scan", "match"),
    [
        (_scan({"risk": pd.DataFrame()}, complete=False), "incomplete"),
        (
            _scan({"risk": pd.DataFrame()}, errors=[object()]),
            "contains 1 scan error",
        ),
        (
            _scan(
                {
                    "risk": pd.DataFrame(
                        [_row("uuid-1", True, "boolean", scan_error="failed")]
                    )
                }
            ),
            "contain an error",
        ),
    ],
)
async def test_import_rejects_incomplete_or_error_bearing_scans(
    monkeypatch: pytest.MonkeyPatch, scan: SimpleNamespace, match: str
) -> None:
    _install_scan(monkeypatch, scan)
    with pytest.raises(ValueError, match=match):
        await import_scan_results_async(_log(), "scan-dir")


@pytest.mark.anyio
async def test_import_rejects_multiple_rows_per_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = _scan(
        {
            "risk": pd.DataFrame(
                [
                    _row("uuid-1", True, "boolean"),
                    _row("uuid-1", False, "boolean"),
                ]
            )
        }
    )
    _install_scan(monkeypatch, scan)
    with pytest.raises(ValueError, match="multiple rows"):
        await import_scan_results_async(_log(), "scan-dir")


@pytest.mark.anyio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_import_rejects_missing_or_duplicate_sample_uuids(
    monkeypatch: pytest.MonkeyPatch, duplicate: bool
) -> None:
    log = _log()
    assert log.samples is not None
    if duplicate:
        log.samples[1].uuid = log.samples[0].uuid
        match = "duplicate sample UUIDs"
    else:
        log.samples[1].uuid = None
        match = "without UUIDs"
    _install_scan(
        monkeypatch,
        _scan({"risk": pd.DataFrame([_row("uuid-1", True, "boolean")])}),
    )

    with pytest.raises(ValueError, match=match):
        await import_scan_results_async(log, "scan-dir")


@pytest.mark.anyio
@skip_if_trio
async def test_import_real_scout_scan_directory(tmp_path: Path) -> None:
    log = _log()
    log_file = tmp_path / "source.eval"
    await write_eval_log_async(log, log_file)

    status = await scan_async(
        scanners=[scan_import_e2e()],
        transcripts=transcripts_from(str(log_file)),
        scans=str(tmp_path / "scans"),
        max_processes=1,
    )
    assert status.complete

    imported = await import_scan_results_async(log, status.location)

    assert imported.samples is not None
    for sample in imported.samples:
        score = (sample.scores or {})["scan_import_e2e"]
        assert score.value is True
        assert score.explanation == f"Imported {sample.uuid}"
        assert score.metadata == {"origin": "e2e", "scanner_references": []}


@scanner(name="scan_import_sparse_e2e", messages="all")
def scan_import_sparse_e2e() -> Scanner[Transcript]:
    async def scan_transcript(transcript: Transcript) -> Result:
        # no finding for one transcript, so the stored value column mixes types
        return Result(value=None if transcript.transcript_id == "uuid-2" else True)

    return scan_transcript


@pytest.mark.anyio
@skip_if_trio
async def test_import_real_scout_scan_with_a_transcript_that_has_no_finding(
    tmp_path: Path,
) -> None:
    log = _log()
    log_file = tmp_path / "source.eval"
    await write_eval_log_async(log, log_file)

    status = await scan_async(
        scanners=[scan_import_sparse_e2e()],
        transcripts=transcripts_from(str(log_file)),
        scans=str(tmp_path / "scans"),
        max_processes=1,
    )
    assert status.complete

    imported = await import_scan_results_async(log, status.location)

    assert imported.samples is not None
    found = {
        sample.uuid: (sample.scores or {}).get("scan_import_sparse_e2e")
        for sample in imported.samples
    }
    assert found["uuid-2"] is None
    assert found["uuid-1"] is not None and found["uuid-1"].value is True
    assert found["uuid-3"] is not None and found["uuid-3"].value is True


@pytest.mark.anyio
async def test_import_reduces_epochs_and_recomputes_to_the_same_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    log.samples = [
        EvalSample(
            id=sample_id,
            epoch=epoch,
            input="input",
            target="target",
            uuid=f"uuid-{sample_id}-{epoch}",
        )
        for sample_id in (1, 2)
        for epoch in (1, 2)
    ]
    log.results = None
    values = {"uuid-1-1": True, "uuid-1-2": False, "uuid-2-1": True, "uuid-2-2": True}
    frame = pd.DataFrame(
        [_row(uuid, value, "boolean") for uuid, value in values.items()]
    )
    _install_scan(monkeypatch, _scan({"risk": frame}))

    imported = await import_scan_results_async(log, "scan-dir")

    assert imported.results is not None
    (risk,) = imported.results.scores
    # one reduced score per sample, not one per sample and epoch
    assert risk.scored_samples == 2
    assert risk.metrics["mean"].value == pytest.approx(0.75)
    assert [reduction.scorer for reduction in imported.reductions or []] == ["risk"]

    before = {name: metric.value for name, metric in risk.metrics.items()}
    recompute_metrics(imported)
    assert imported.results is not None
    (recomputed,) = imported.results.scores
    assert {name: metric.value for name, metric in recomputed.metrics.items()} == before


@pytest.mark.anyio
async def test_import_into_an_unscored_log_recomputes_to_the_same_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    log.results = None
    log.eval.scorers = [EvalScorer(name="match")]
    for sample in log.samples or []:
        sample.scores = None
    frame = pd.DataFrame([_row("uuid-1", True, "boolean")])
    _install_scan(monkeypatch, _scan({"risk": frame}))

    imported = await import_scan_results_async(log, "scan-dir")

    # as when a scorer is run on an unscored log, the header lists what was applied
    assert [scorer.name for scorer in imported.eval.scorers or []] == ["risk"]
    recompute_metrics(imported)
    assert imported.results is not None
    assert [score.name for score in imported.results.scores] == ["risk"]


@pytest.mark.anyio
async def test_rescoring_after_import_finds_scorers_named_only_in_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log()
    assert log.results is not None and log.eval.scorers is None
    log.results.scores[0].name = log.results.scores[0].scorer = "match"
    frame = pd.DataFrame([_row("uuid-1", True, "boolean")])
    _install_scan(monkeypatch, _scan({"risk": frame}))

    imported = await import_scan_results_async(log, "scan-dir")

    assert [scorer.name for scorer in imported.eval.scorers or []] == ["risk"]
    # the scanner is not loaded as a scorer, and the log's own scorer still is
    assert len(resolve_scorers(imported)) == 1


@pytest.mark.anyio
async def test_import_decodes_numbers_and_booleans_stored_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            _row("uuid-1", "3", "number"),
            _row("uuid-2", "inf", "number"),
            _row("uuid-3", "True", "boolean"),
        ]
    )
    _install_scan(monkeypatch, _scan({"risk": frame}))

    imported = await import_scan_results_async(_log(), "scan-dir")

    assert imported.samples is not None
    values = [(sample.scores or {})["risk"].value for sample in imported.samples]
    assert values == [3, float("inf"), True]
