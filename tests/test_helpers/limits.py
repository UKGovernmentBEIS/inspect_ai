import anyio

from inspect_ai.event._base import BaseEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._subtask import (
    SubtaskEvent,
)
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._limit import check_token_limit, record_model_usage, token_limit


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


async def exceed_token_limit_in_child_task(
    tokens: int = 1_000_000, own_limit: bool = False
) -> None:
    """Exceed a token limit from a child task, so the error arrives in a group.

    Args:
        tokens: Tokens to record against the open token limits.
        own_limit: Exceed a limit the child task opens itself, rather than
            the enclosing one.
    """

    async def exceed() -> None:
        with token_limit(1 if own_limit else None):
            record_model_usage(ModelUsage(total_tokens=tokens))
            check_token_limit()

    async with anyio.create_task_group() as tg:
        tg.start_soon(exceed)
