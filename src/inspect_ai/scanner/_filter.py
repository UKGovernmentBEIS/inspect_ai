from typing import Literal

MessageType = Literal["system", "user", "assistant", "tool"]
EventType = Literal[
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


def normalize_messages_filter(
    filter: list[MessageType] | Literal["all"],
) -> list[MessageType] | Literal["all"]:
    if filter == "all":
        return filter
    uniq: list[MessageType] = []
    seen: set[MessageType] = set()
    for x in filter:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    validate_messages_filter(uniq)
    return uniq


def normalize_events_filter(
    filter: list[EventType] | Literal["all"],
) -> list[EventType] | Literal["all"]:
    if filter == "all":
        return filter
    uniq: list[EventType] = []
    seen: set[EventType] = set()
    for x in filter:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    validate_events_filter(uniq)
    return uniq


def validate_messages_filter(filter: list[MessageType] | None) -> None:
    if filter is None:
        return
    allowed: set[str] = {"all", "system", "user", "assistant", "tool"}
    if not filter:
        raise ValueError("messages=[] is not allowed; provide at least one filter")
    bad = [x for x in filter if x not in allowed]
    if bad:
        raise ValueError(
            f"Invalid messages filter(s): {bad}. Allowed: {sorted(allowed)}"
        )


def validate_events_filter(filter: list[EventType] | None) -> None:
    if filter is None:
        return
    allowed: set[str] = {
        "all",
        "model",
        "tool",
        # "sample_init",
        # "sample_limit",
        # "sandbox",
        # "state",
        # "store",
        # "approval",
        # "input",
        # "score",
        # "error",
        # "logger",
        # "info",
        # "span_begin",
        # "span_end",
    }
    if not filter:
        raise ValueError("events=[] is not allowed; provide at least one filter")
    bad = [x for x in filter if x not in allowed]
    if bad:
        raise ValueError(f"Invalid events filter(s): {bad}. Allowed: {sorted(allowed)}")
