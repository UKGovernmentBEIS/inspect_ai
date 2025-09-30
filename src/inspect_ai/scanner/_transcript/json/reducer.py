from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generator, Literal

from ijson import ObjectBuilder  # type: ignore
from ijson.utils import coroutine as _ijson_coroutine  # type: ignore

# Public constants / prefixes
ATTACHMENT_PREFIX = "attachment://"
ATTACHMENT_PREFIX_LEN = len(ATTACHMENT_PREFIX)
ATTACHMENTS_PREFIX = "attachments."
MESSAGES_ITEM_PREFIX = "messages.item"
EVENTS_ITEM_PREFIX = "events.item"


def _should_skip(
    filter_field_value: str, filter_list: None | Literal["all"] | list[str]
) -> bool:
    if filter_list is None:
        return True
    if filter_list == "all":
        return False
    return filter_field_value not in filter_list


@dataclass(frozen=True, slots=True)
class ListProcessingConfig:
    array_item_prefix: str
    filter_field: str
    filter_list: None | Literal["all"] | list[str]
    filter_prefix: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "filter_prefix", f"{self.array_item_prefix}.{self.filter_field}"
        )


@dataclass(slots=True)
class ParseState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    attachment_refs: set[str] = field(default_factory=set)
    attachments: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Coroutine-based object processors (idiomatic style with early filtering)
# ---------------------------------------------------------------------------

EventTuple = tuple[str, str, Any]
CoroutineGen = Generator[None, EventTuple, None]


@_ijson_coroutine
def _item_coroutine(
    target_list: list[dict[str, Any]],
    attachment_refs: set[str],
    config: ListProcessingConfig,
) -> CoroutineGen:  # pragma: no cover
    builder: ObjectBuilder | None = None
    attachments: set[str] = set()
    skip = False
    item_prefix = config.array_item_prefix
    filter_prefix = config.filter_prefix
    while True:
        prefix, event, value = yield
        if prefix == item_prefix and event == "start_map":
            builder = ObjectBuilder()
            builder.event(event, value)
            attachments.clear()
            skip = False
            continue
        if builder is None:
            continue
        if prefix == filter_prefix and event == "string":
            if _should_skip(value, config.filter_list):
                builder = None
                skip = True
                attachments.clear()
                continue
        if prefix == item_prefix and event == "end_map":
            if not skip and builder is not None:
                try:
                    builder.event(event, value)
                    item = builder.value
                    target_list.append(item)
                    attachment_refs.update(attachments)
                except Exception:
                    pass
            builder = None
            skip = False
            attachments.clear()
            continue
        if skip:
            continue
        try:
            builder.event(event, value)
        except Exception:
            builder = None
            continue
        if event == "string" and isinstance(value, str):
            if len(value) == 45 and value.startswith(ATTACHMENT_PREFIX):
                attachments.add(value[ATTACHMENT_PREFIX_LEN:])


def message_item_coroutine(
    state: ParseState, config: ListProcessingConfig
) -> CoroutineGen:
    return _item_coroutine(state.messages, state.attachment_refs, config)


def event_item_coroutine(
    state: ParseState, config: ListProcessingConfig
) -> CoroutineGen:
    return _item_coroutine(state.events, state.attachment_refs, config)


@_ijson_coroutine
def attachments_coroutine(state: ParseState) -> CoroutineGen:  # pragma: no cover
    attachments_prefix_len = len(ATTACHMENTS_PREFIX)
    while True:
        prefix, event, value = yield
        if event != "string":
            continue
        if not prefix.startswith(ATTACHMENTS_PREFIX):
            continue
        end = prefix.find(".", attachments_prefix_len)
        attachment_id = (
            prefix[attachments_prefix_len:]
            if end == -1
            else prefix[attachments_prefix_len:end]
        )
        if attachment_id in state.attachment_refs:
            state.attachments[attachment_id] = value


__all__ = [
    "ListProcessingConfig",
    "ParseState",
    "message_item_coroutine",
    "event_item_coroutine",
    "attachments_coroutine",
    "ATTACHMENT_PREFIX",
    "ATTACHMENT_PREFIX_LEN",
    "ATTACHMENTS_PREFIX",
    "MESSAGES_ITEM_PREFIX",
    "EVENTS_ITEM_PREFIX",
]
