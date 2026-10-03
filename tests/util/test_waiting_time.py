import time
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from tenacity import RetryCallState, retry, wait_fixed

from inspect_ai._util.working import (
    SampleTiming,
    WaitingTime,
    _sample_timing,
    init_sample_working_time,
    report_sample_waiting_time,
    sample_waiting,
    sample_waiting_time,
    sample_working_time,
)
from inspect_ai.model import ModelCall, ModelOutput, ModelUsage, get_model
from inspect_ai.model._retry import model_retry_config
from inspect_ai.util import working_limit


@pytest.mark.parametrize(
    "spans, expected",
    [
        ([(1, 3), (2, 4)], 3),
        ([(2, 4), (1, 3)], 3),
        ([(1, 5), (2, 3)], 4),
        ([(1, 2), (4, 5), (2, 4)], 4),
        ([(1, 2), (4, 5), (1, 2)], 2),
        ([(1, 1), (2, 1)], 0),
    ],
)
def test_waiting_time_union(spans: list[tuple[float, float]], expected: float) -> None:
    waiting = WaitingTime()
    for start, end in spans:
        waiting.record(start, end)
    assert waiting.elapsed() == expected


def test_ongoing_wait_overlapping_completed_wait() -> None:
    waiting = WaitingTime()
    with patch("time.monotonic", return_value=1) as clock:
        with waiting.track():
            clock.return_value = 3
            waiting.record(2, 3)
            with waiting.track():
                clock.return_value = 4
                assert waiting.elapsed() == 3
            clock.return_value = 5
            assert waiting.elapsed() == 4
        assert waiting.elapsed() == 4


async def test_waiting_time_updates_sample_and_nested_limits() -> None:
    with (
        patch("time.monotonic", return_value=100) as clock,
        patch("anyio.current_time", side_effect=lambda: clock.return_value + 1000),
    ):
        init_sample_working_time(100)
        with working_limit(10) as outer:
            clock.return_value = 101
            with working_limit(10) as inner:
                async with sample_waiting():
                    clock.return_value = 103
                    report_sample_waiting_time(1)
                    assert sample_waiting_time() == 2
                    assert sample_working_time() == 1
                    assert outer.usage == 1
                    assert inner.usage == 0
                clock.return_value = 104
            clock.return_value = 105
        assert sample_working_time() == 3
        assert inner.usage == 1
        assert outer.usage == 3


async def test_concurrent_retry_waits_and_cancellation() -> None:
    init_sample_working_time(time.monotonic())
    retry_started = anyio.Event()

    def log_retry(model_name: str, retry_state: RetryCallState) -> None:
        retry_started.set()

    @retry(
        **model_retry_config(
            "test",
            5,
            10,
            lambda ex: True,
            lambda ex: None,
            log_retry,
            track_waiting_time=True,
            wait=wait_fixed(5),
        )
    )
    async def failing_call() -> None:
        raise ConnectionError("temporary failure")

    with working_limit(10) as limit:
        async with anyio.create_task_group() as group:
            group.start_soon(failing_call)
            group.start_soon(failing_call)
            await retry_started.wait()
            await anyio.sleep(0.05)
            assert 0 <= sample_waiting_time() < 1
            assert 0 <= sample_working_time() < 1
            assert 0 <= limit.usage < 1
            group.cancel_scope.cancel()
        waiting = sample_waiting_time()
        await anyio.sleep(0.05)
        assert sample_waiting_time() == waiting
        assert 0.04 <= sample_working_time() < 1
        assert 0.04 <= limit.usage < 1


async def test_usage_hook_wait_does_not_replace_successful_request_time() -> None:
    model = get_model("mockllm/model")
    output = ModelOutput.from_content(model="mockllm/model", content="OK")
    output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    with (
        patch("time.monotonic", return_value=100) as clock,
        patch("anyio.current_time", side_effect=lambda: clock.return_value),
    ):
        init_sample_working_time(100)

        async def generate(**kwargs: Any) -> tuple[ModelOutput, ModelCall]:
            clock.return_value = 101
            return output, ModelCall(request={}, response={}, time=1)

        async def on_model_usage(**kwargs: Any) -> None:
            async with sample_waiting():
                clock.return_value = 102

        with (
            patch.object(model.api, "generate", side_effect=generate),
            patch(
                "inspect_ai.hooks._hooks.emit_model_usage", side_effect=on_model_usage
            ),
            working_limit(10) as limit,
        ):
            await model.generate("Hello")
            assert sample_waiting_time() == 1
            assert sample_working_time() == 1
            assert limit.usage == 1


async def test_waiting_without_sample_does_not_retain_intervals() -> None:
    timing = SampleTiming()
    token = _sample_timing.set(timing)
    try:
        with (
            patch("time.monotonic", return_value=100) as clock,
            patch("anyio.current_time", side_effect=lambda: clock.return_value),
            working_limit(10) as limit,
        ):
            for i in range(100):
                async with sample_waiting():
                    clock.return_value += 1
            assert sample_waiting_time() == 0
            assert timing.waiting._spans == []
            assert limit.usage == 0
    finally:
        _sample_timing.reset(token)
