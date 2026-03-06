import contextlib
from typing import Literal, Type

import pytest

from inspect_ai.log._edit import (
    ProvenanceData,
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
