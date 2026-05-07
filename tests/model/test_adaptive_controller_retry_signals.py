"""Adaptive-affecting changes from the retry-timing fix."""

# pyright: reportImplicitRelativeImport=false

import time
from datetime import datetime, timezone

from _helpers.retry_provider import RaisingThenSucceedingAPI

from inspect_ai._util.working import init_sample_working_time, sample_waiting_time
from inspect_ai.model import get_model
from inspect_ai.model._generate_accounting import (
    ModelGenerateAccounting,
    current_model_generate_accounting,
    model_generate_accounting,
)


async def test_negative_waiting_delta_does_not_propagate_to_sample_waiting() -> None:
    init_sample_working_time(time.monotonic())
    model = get_model("mockllm/test", memoize=False)
    model.api = RaisingThenSucceedingAPI(
        failures=0,
        success_output_time=1000.0,
    )

    await model.generate("hello")

    assert sample_waiting_time() >= 0


async def test_report_http_retry_with_no_active_accounting_does_not_raise() -> None:
    from inspect_ai._util.retry import http_retries_count, report_http_retry

    assert current_model_generate_accounting() is None
    before = http_retries_count()
    report_http_retry()
    assert http_retries_count() == before + 1


async def test_report_http_retry_with_active_accounting_increments_counter() -> None:
    from inspect_ai._util.retry import report_http_retry

    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        working_start=0.0,
    )
    async with model_generate_accounting(acc):
        report_http_retry()
        report_http_retry()

    assert acc.http_retry_count == 2
