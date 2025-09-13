from typing import Literal

MessageType = Literal["all", "system", "user", "assistant", "tool"]
EventType = Literal[
    "all",
    "sample_init",
    "sample_limit",
    "sandbox",
    "state",
    "store",
    "model",
    "tool",
    "approval",
    "input",
    "score",
    "error",
    "logger",
    "info",
    "span_begin",
    "span_end",
]

MessagesFilter = MessageType | list[MessageType]
EventsFilter = EventType | list[EventType]


def validate_messages_filter(filter: MessagesFilter) -> None:
    allowed: set[str] = {"all", "system", "user", "assistant", "tool"}
    if isinstance(filter, list):
        if not filter:
            raise ValueError("messages=[] is not allowed; provide at least one filter")
        bad = [x for x in filter if x not in allowed]
        if bad:
            raise ValueError(
                f"Invalid messages filter(s): {bad}. Allowed: {sorted(allowed)}"
            )
    else:
        if filter not in allowed:
            raise ValueError(f"Invalid messages filter: {filter!r}")


def validate_events_filter(filter: EventsFilter) -> None:
    allowed: set[str] = {
        "all",
        "sample_init",
        "sample_limit",
        "sandbox",
        "state",
        "store",
        "model",
        "tool",
        "approval",
        "input",
        "score",
        "error",
        "logger",
        "info",
        "span_begin",
        "span_end",
    }
    if isinstance(filter, list):
        if not filter:
            raise ValueError("events=[] is not allowed; provide at least one filter")
        bad = [x for x in filter if x not in allowed]
        if bad:
            raise ValueError(
                f"Invalid events filter(s): {bad}. Allowed: {sorted(allowed)}"
            )
    else:
        if filter not in allowed:
            raise ValueError(f"Invalid events filter: {filter!r}")


def normalize_messages_filter(spec: MessagesFilter) -> MessagesFilter:
    if not isinstance(spec, list):
        return spec
    uniq: list[MessageType] = []
    seen: set[MessageType] = set()
    for x in spec:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    if len(uniq) == 1:
        return uniq[0]
    return uniq


def normalize_events_filter(spec: EventsFilter) -> EventsFilter:
    if not isinstance(spec, list):
        return spec
    uniq: list[EventType] = []
    seen: set[EventType] = set()
    for x in spec:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    if len(uniq) == 1:
        return uniq[0]
    return uniq
