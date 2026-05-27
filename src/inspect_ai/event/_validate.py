from pydantic import TypeAdapter

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai.model._chat_message import ChatMessage

from ._event import Event

_chat_message_list_adapter: TypeAdapter[list[ChatMessage]] = TypeAdapter(
    list[ChatMessage]
)
_event_list_adapter: TypeAdapter[list[Event]] = TypeAdapter(list[Event])


def validate_chat_messages(
    messages: object, *, context: dict[str, object] | None = None
) -> list[ChatMessage]:
    return _chat_message_list_adapter.validate_python(messages, context=context)


def validate_events(events: object) -> list[Event]:
    return _event_list_adapter.validate_python(
        events, context=get_deserializing_context()
    )


def validate_events_json(events: str) -> list[Event]:
    return _event_list_adapter.validate_json(
        events, context=get_deserializing_context()
    )
