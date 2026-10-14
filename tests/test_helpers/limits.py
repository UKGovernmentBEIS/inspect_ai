from typing import Callable

from inspect_ai.event._base import BaseEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._subtask import (
    SubtaskEvent,
)
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
    StreamEvent,
    StreamRetryEvent,
    StreamTextEvent,
    get_model,
)
from inspect_ai.model._stream import NoStreamDataError, report_model_stream_delta
from inspect_ai.tool import ToolChoice, ToolInfo


def check_limit_event(log: EvalLog, type: str) -> None:
    event = find_limit_event(log)
    assert event is not None, f"Limit event '{type}' not found in log"
    assert type == event.type


def find_limit_event(log: EvalLog) -> SampleLimitEvent | None:
    if not log.samples:
        return None
    sample = log.samples[0]
    for event in sample.events:
        result = find_limit_event_recursive(event)
        if result is not None:
            return result
    return None


def find_limit_event_recursive(event: BaseEvent) -> SampleLimitEvent | None:
    if isinstance(event, SampleLimitEvent):
        return event
    # ToolEvent and SubtaskEvent can contain other events
    if isinstance(event, ToolEvent | SubtaskEvent):
        for child in event.events:
            result = find_limit_event_recursive(child)
            if result is not None:
                return result
    return None


async def generate_with_retry_boundary(
    calls: list[list[ChatMessage]], on_retry_boundary: Callable[[], None]
) -> ModelOutput:
    """Generate with a first attempt that streams a delta and then fails.

    The retry is announced to `on_stream` before the second attempt is sent.
    `on_retry_boundary` runs inside that callback, standing in for a
    concurrent call that records usage while the callback is awaited. Each
    provider attempt is appended to `calls`; an attempt uses one token.
    """

    async def outputs(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        calls.append(input)
        if len(calls) == 1:
            await report_model_stream_delta(StreamTextEvent(text="partial"))
            raise NoStreamDataError("retry me")
        output = ModelOutput.from_content("mockllm/model", "hello")
        output.usage = ModelUsage(total_tokens=1)
        return output

    async def on_stream(event: StreamEvent) -> None:
        if isinstance(event, StreamRetryEvent):
            on_retry_boundary()

    model = get_model("mockllm/model", custom_outputs=outputs)
    return await model.generate(
        "", config=GenerateConfig(max_retries=1), on_stream=on_stream
    )
