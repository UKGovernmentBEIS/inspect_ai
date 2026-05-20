import contextlib
from typing import Literal, Type

import pytest

from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    edit_eval_log,
    invalidate_samples,
    uninvalidate_samples,
)
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSample, EvalSpec


@pytest.fixture(name="eval_log")
def fixture_eval_log(request: pytest.FixtureRequest) -> EvalLog:
    invalid_samples = getattr(request, "param", {})
    return EvalLog(
        version=2,
        invalidated=len(invalid_samples) > 0,
        eval=EvalSpec(
            eval_id="test_eval",
            run_id="test_run",
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test_task_id",
            dataset=EvalDataset(),
            model="test_model",
            config=EvalConfig(),
        ),
        samples=[
            EvalSample(
                uuid=(sample_uuid := str(idx_sample + 1)),
                id="test_sample",
                epoch=idx_sample,
                input="test_input",
                target="test_target",
                invalidation=(
                    ProvenanceData(
                        author="test_person",
                        reason="test_reason",
                    )
                    if sample_uuid in invalid_samples
                    else None
                ),
            )
            for idx_sample in range(10)
        ],
    )


@pytest.mark.parametrize(
    ("sample_uuids", "expected_error", "expected_invalidated"),
    [
        pytest.param([], None, False, id="no_samples"),
        pytest.param(["1"], None, True, id="single_sample"),
        pytest.param("all", None, True, id="all_samples"),
        pytest.param(
            [str(idx_sample + 1) for idx_sample in range(10)],
            None,
            True,
            id="all_samples_by_uuid",
        ),
        pytest.param(["notexists"], ValueError, False, id="invalid_sample_uuid"),
    ],
)
def test_invalidate_samples(
    eval_log: EvalLog,
    sample_uuids: list[str] | Literal["all"],
    expected_error: Type[Exception] | None,
    expected_invalidated: bool,
):
    with (
        pytest.raises(expected_error)
        if expected_error is not None
        else contextlib.nullcontext()
    ):
        eval_log = invalidate_samples(
            eval_log,
            sample_uuids,
            ProvenanceData(author="test_person", reason="test_reason"),
        )

    assert eval_log.invalidated is expected_invalidated
    for sample in eval_log.samples or []:
        if expected_invalidated and (
            sample_uuids == "all" or str(sample.uuid) in sample_uuids
        ):
            assert sample.invalidation is not None
            assert sample.invalidation.author == "test_person"
            assert sample.invalidation.reason == "test_reason"
        else:
            assert sample.invalidation is None


@pytest.mark.parametrize(
    ("sample_uuids", "expected_error", "expect_uninvalidated"),
    [
        pytest.param([], None, False, id="no_samples"),
        pytest.param(["1"], None, False, id="single_sample"),
        pytest.param(
            ["1", "4"],
            None,
            True,
            id="multiple_samples",
        ),
        pytest.param("all", None, True, id="all_samples"),
        pytest.param(["notexists"], ValueError, False, id="invalid_sample_uuid"),
    ],
)
@pytest.mark.parametrize("eval_log", [{"1": "complete", "4": "error"}], indirect=True)
def test_uninvalidate_samples(
    eval_log: EvalLog,
    sample_uuids: list[str] | Literal["all"],
    expected_error: Type[Exception] | None,
    expect_uninvalidated: bool,
):
    invalid_samples = {
        sample.uuid
        for sample in eval_log.samples or []
        if sample.invalidation is not None
    }

    with (
        pytest.raises(expected_error)
        if expected_error is not None
        else contextlib.nullcontext()
    ):
        eval_log = uninvalidate_samples(eval_log, sample_uuids)

    assert eval_log.invalidated is not expect_uninvalidated
    for sample in eval_log.samples or []:
        sample_uuid = str(sample.uuid)
        if (
            sample_uuid not in invalid_samples
            or sample_uuid in sample_uuids
            or sample_uuids == "all"
        ):
            expect_sample_invalidated = False
        else:
            expect_sample_invalidated = True

        if expect_sample_invalidated:
            assert sample.invalidation is not None
            assert sample.invalidation.author == "test_person"
            assert sample.invalidation.reason == "test_reason"
        else:
            assert sample.invalidation is None


# ---------------------------------------------------------------------------
# edit_eval_log: MetadataEdit
# ---------------------------------------------------------------------------


def _provenance() -> ProvenanceData:
    return ProvenanceData(author="tester", reason="metadata edit test")


def test_metadata_edit_adds_null_valued_key(eval_log: EvalLog) -> None:
    # Regression: `current_metadata.get(k) != v` mis-classified adding a
    # brand-new key whose value is None as a no-op, because `dict.get`
    # returns None for absent keys. The viewer's "add key + type=null"
    # flow silently dropped the new key. Now the filter checks key
    # presence first so the null value lands in metadata.
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"missing": None})],
        _provenance(),
    )
    assert log.metadata == {"missing": None}
    assert "missing" in log.metadata


def test_metadata_edit_adds_non_null_key(eval_log: EvalLog) -> None:
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"author": "alice"})],
        _provenance(),
    )
    assert log.metadata == {"author": "alice"}


def test_metadata_edit_overwriting_with_null_is_persisted(
    eval_log: EvalLog,
) -> None:
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"score": "pending"})],
        _provenance(),
    )
    assert log.metadata == {"score": "pending"}
    log = edit_eval_log(
        log, [MetadataEdit(metadata_set={"score": None})], _provenance()
    )
    assert log.metadata == {"score": None}


def test_metadata_edit_skips_no_op_when_value_already_matches(
    eval_log: EvalLog,
) -> None:
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"k": "v"})],
        _provenance(),
    )
    prior_updates = len(log.log_updates or [])
    log_again = edit_eval_log(
        log, [MetadataEdit(metadata_set={"k": "v"})], _provenance()
    )
    assert len(log_again.log_updates or []) == prior_updates


def test_metadata_edit_skips_no_op_when_null_already_matches(
    eval_log: EvalLog,
) -> None:
    # Setting an existing null-valued key to null again should still be
    # a no-op — the new key-presence check must not turn every null
    # write into an unnecessary LogUpdate.
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"k": None})],
        _provenance(),
    )
    prior_updates = len(log.log_updates or [])
    log_again = edit_eval_log(
        log, [MetadataEdit(metadata_set={"k": None})], _provenance()
    )
    assert len(log_again.log_updates or []) == prior_updates


def test_metadata_edit_remove_key(eval_log: EvalLog) -> None:
    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"k": 1})],
        _provenance(),
    )
    log = edit_eval_log(
        log, [MetadataEdit(metadata_remove=["k"])], _provenance()
    )
    assert "k" not in log.metadata


def test_metadata_edit_null_value_survives_write_then_read(
    eval_log: EvalLog, tmp_path
) -> None:
    # End-to-end regression: edit → write_eval_log → read_eval_log must
    # preserve null-valued keys. Catches not just the in-memory filter
    # bug but any pydantic / recorder serialization that strips nulls.
    from inspect_ai.log._file import read_eval_log, write_eval_log

    log = edit_eval_log(
        eval_log,
        [MetadataEdit(metadata_set={"null_key": None, "ok_key": "v"})],
        _provenance(),
    )
    assert log.metadata == {"null_key": None, "ok_key": "v"}

    out_path = str(tmp_path / "edited.eval")
    write_eval_log(log, out_path, "eval")

    reread = read_eval_log(out_path)
    # Both keys must round-trip; in particular `null_key` must still be
    # present with value None.
    assert "null_key" in reread.metadata
    assert reread.metadata["null_key"] is None
    assert reread.metadata["ok_key"] == "v"
    # The LogUpdate audit trail must also carry the null edit.
    assert reread.log_updates is not None
    last_edit = reread.log_updates[-1].edits[-1]
    assert isinstance(last_edit, MetadataEdit)
    assert last_edit.metadata_set == {"null_key": None, "ok_key": "v"}
