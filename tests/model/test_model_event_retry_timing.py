"""Comprehensive retry-timing scenarios."""

# pyright: reportImplicitRelativeImport=false

import anyio
import pytest
from _helpers.event_assertions import (
    assert_attempt_group,
    assert_no_legacy_rewrite,
    model_events,
)
from _helpers.retry_provider import (
    RetryableModelError,
    SlowThenSuccessAPI,
    install_retry_classifier,
    make_mockllm_with_callable,
)
from tenacity import RetryError

from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model


async def _retry_then_success(failures: int) -> Transcript:
    remaining = [failures]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        from inspect_ai.model._model_output import ModelOutput

        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)
    await model.generate("hello", config=GenerateConfig(max_retries=failures + 5))
    return transcript


@pytest.mark.parametrize("failures", [1, 2, 5])
async def test_n_retries_then_success(failures: int) -> None:
    transcript = await _retry_then_success(failures)
    events = model_events(transcript)
    assert len(events) == failures + 1
    assert_attempt_group(events, retries=failures, terminal_kind="success")


async def test_terminal_event_call_working_time_le_wall_duration() -> None:
    transcript = await _retry_then_success(2)
    terminal = model_events(transcript)[-1]
    assert terminal.call_completed_at is not None
    assert terminal.call_started_at is not None
    assert terminal.call_working_time is not None
    wall = (terminal.call_completed_at - terminal.call_started_at).total_seconds()
    assert terminal.call_working_time <= wall + 1e-6


async def test_exhausted_retries_emit_terminal_failure_event() -> None:
    def always_fail(input, tools, tool_choice, config):
        raise RetryableModelError("persistent")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(always_fail)
    install_retry_classifier(model)
    with pytest.raises(RetryError):
        await model.generate("hello", config=GenerateConfig(max_retries=3))

    events = model_events(transcript)
    assert len(events) == 3
    assert_attempt_group(events, retries=2, terminal_kind="exhausted")
    assert_no_legacy_rewrite(events)


async def test_cancellation_mid_attempt_emits_terminal_failure_event() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = SlowThenSuccessAPI(slow_seconds=10.0)

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            try:
                await model.generate("hello")
            except BaseException:
                pass

        tg.start_soon(run)
        await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    events = model_events(transcript)
    assert len(events) == 1
    event = events[0]
    assert event.error is not None
    assert event.completed is not None
    assert event.call_started_at is not None
    assert event.call_completed_at is not None
