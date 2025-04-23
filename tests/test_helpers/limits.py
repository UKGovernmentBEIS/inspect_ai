from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import (
    BaseEvent,
    SampleLimitEvent,
    SubtaskEvent,
    ToolEvent,
)


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
