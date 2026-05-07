"""Per-attempt completed/working_time set on every event outcome."""

# pyright: reportImplicitRelativeImport=false

import pytest
from _helpers.event_assertions import model_events
from _helpers.retry_provider import (
    RaisingThenSucceedingAPI,
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)
from tenacity import RetryError

from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model


async def test_success_event_has_completed_and_working_time() -> None:
    def custom_outputs(input, tools, tool_choice, config):
        from inspect_ai.model._model_output import ModelOutput

        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    await model.generate("hello")

    events = model_events(transcript)
    assert len(events) == 1
    assert events[0].completed is not None
    assert events[0].working_time is not None
    assert events[0].working_time >= 0


async def test_failed_attempts_have_completed_and_working_time() -> None:
    def always_fail(input, tools, tool_choice, config):
        raise RetryableModelError("boom")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(always_fail)
    install_retry_classifier(model)
    with pytest.raises(RetryError):
        await model.generate("hello", config=GenerateConfig(max_retries=2))

    events = model_events(transcript)
    assert len(events) == 2
    for event in events:
        assert event.error is not None
        assert event.completed is not None
        assert event.working_time is not None
        assert event.working_time >= 0


async def test_cache_read_event_has_per_attempt_completed_and_working_time() -> None:
    model = get_model("mockllm/test", memoize=False)
    model.api = RaisingThenSucceedingAPI(
        failures=0,
        success_output_time=5.0,
    )
    await model.generate("hello", cache=True)

    transcript = Transcript()
    init_transcript(transcript)
    await model.generate("hello", cache=True)

    events = model_events(transcript)
    assert len(events) == 1
    event = events[0]
    assert event.cache == "read"
    assert event.completed is not None
    assert event.working_time is not None
    assert event.working_time < 5.0
