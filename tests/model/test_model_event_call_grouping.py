"""call_id and attempt invariants for ModelEvent retry groups."""

# pyright: reportImplicitRelativeImport=false

import anyio
from _helpers.event_assertions import assert_no_legacy_rewrite, model_events
from _helpers.retry_provider import (
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)

from inspect_ai.log._transcript import Transcript, init_transcript


async def test_single_success_has_call_id_and_attempt_1() -> None:
    def custom_outputs(input, tools, tool_choice, config):
        from inspect_ai.model._model_output import ModelOutput

        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    await model.generate("hello")

    events = model_events(transcript)
    assert len(events) == 1
    assert events[0].call_id
    assert events[0].attempt == 1


async def test_retry_events_share_call_id_with_contiguous_attempts() -> None:
    remaining = [2]

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
    await model.generate("hello")

    events = model_events(transcript)
    assert len(events) == 3
    assert len({event.call_id for event in events}) == 1
    assert [event.attempt for event in events] == [1, 2, 3]


async def test_consecutive_generates_have_distinct_call_ids() -> None:
    def custom_outputs(input, tools, tool_choice, config):
        from inspect_ai.model._model_output import ModelOutput

        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    await model.generate("first")
    await model.generate("second")

    events = model_events(transcript)
    assert len(events) == 2
    assert events[0].call_id != events[1].call_id
    assert events[0].attempt == 1
    assert events[1].attempt == 1


async def test_concurrent_generates_have_independent_call_ids() -> None:
    def custom_outputs(input, tools, tool_choice, config):
        from inspect_ai.model._model_output import ModelOutput

        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    async with anyio.create_task_group() as tg:
        tg.start_soon(model.generate, "a")
        tg.start_soon(model.generate, "b")

    events = model_events(transcript)
    assert len(events) == 2
    assert len({event.call_id for event in events}) == 2
    assert all(event.attempt == 1 for event in events)
    assert_no_legacy_rewrite(events)
