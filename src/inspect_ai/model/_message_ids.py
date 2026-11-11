"""Stable message ID generation based on content hash."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

import mmh3
from shortuuid import uuid as shortuuid

from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import json_normalize_numbers, jsonable_python
from inspect_ai.model._assistant_internal import copy_assistant_internal

from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from ._model_output import ModelOutput

if TYPE_CHECKING:
    from inspect_ai.event._model import ModelEvent


def stable_message_ids() -> Callable[[Sequence[ChatMessage] | ModelEvent], None]:
    """Create a function that applies stable message IDs based on content hash.

    Messages with identical content receive the same ID within a transcript,
    enabling cross-event message identity tracking. This is useful when an
    agent makes multiple LLM calls where subsequent calls include previous
    messages in the conversation history.

    Returns:
        A function that applies IDs to either a Sequence[ChatMessage] or ModelEvent.

    Example:
        apply_ids = stable_message_ids()
        apply_ids(messages)  # Apply to message list
        apply_ids(event)     # Apply to ModelEvent
    """
    hash_to_ids: dict[str, list[str]] = {}

    def hash_message(message: ChatMessage) -> str:
        """Hash message content using mmh3 (fast 128-bit hash)."""
        msg_dict = message.model_dump(exclude={"id"}, exclude_none=True)
        json_str = json.dumps(jsonable_python(msg_dict), sort_keys=True)
        hash_bytes = mmh3.hash_bytes(json_str.encode())
        return hash_bytes.hex()

    def get_id(message: ChatMessage, conversation_ids: set[str]) -> str:
        """Get stable ID for message, avoiding duplicates within conversation."""
        msg_hash = hash_message(message)
        existing_ids = hash_to_ids.get(msg_hash, [])

        # Reuse existing ID if not already in this conversation
        for existing_id in existing_ids:
            if existing_id not in conversation_ids:
                return existing_id

        # Generate new ID
        new_id = shortuuid()
        hash_to_ids.setdefault(msg_hash, []).append(new_id)
        return new_id

    def apply_ids_to_messages(messages: Sequence[ChatMessage]) -> set[str]:
        """Apply stable IDs to a list of messages, returning the assigned IDs."""
        # Maintain the set of assigned IDs incrementally and pass it into
        # get_id(). Avoids get_id() rebuilding it from the message list
        # on every call (which would mean O(n^2) ID assignment).
        conversation_ids: set[str] = set()
        for msg in messages:
            msg.id = get_id(msg, conversation_ids)
            conversation_ids.add(msg.id)
        return conversation_ids

    def apply_ids(target: Sequence[ChatMessage] | ModelEvent) -> None:
        """Apply stable IDs to messages or a ModelEvent."""
        # Use duck typing to check for ModelEvent (avoid circular import)
        if hasattr(target, "event") and getattr(target, "event") == "model":
            input_messages = list(target.input)  # type: ignore[union-attr]
            conversation_ids = apply_ids_to_messages(input_messages)
            output = target.output  # type: ignore[union-attr]
            if (
                isinstance(output, ModelOutput)
                and output.choices
                and len(output.choices) > 0
            ):
                output.message.id = get_id(output.message, conversation_ids)
        else:
            apply_ids_to_messages(target)  # type: ignore[arg-type]

    return apply_ids


EditedT = TypeVar("EditedT", bound=ChatMessage)


def edited_message(source: EditedT, **update: Any) -> EditedT:
    """A copy of `source` with `update` applied, under its own id (`with_edited_id`)."""
    return with_edited_id(source, cast(EditedT, source.model_copy(update=update)))


def with_edited_id(
    source: ChatMessage, edited: EditedT, keep_provider_state: bool = True
) -> EditedT:
    """`edited` under an id of its own, derived from `source`'s id and its content.

    Different content never shares an id. The same edit of a message on every
    model call is one message, and an edit of an edit is derived from the edit
    it was made from. An edit that leaves the content unchanged keeps the
    source's id. An edit of an assistant message keeps the provider state
    recorded under the source's id (Anthropic's pending server work) unless
    `keep_provider_state` is False.
    """
    if source.id is None:
        edited.id = shortuuid()
    elif same_content(source, edited):
        edited.id = source.id
    else:
        edited.id = edit_id(source.id, content_hash(edited))
        if keep_provider_state and isinstance(source, ChatMessageAssistant):
            copy_assistant_internal(source.id, edited.id)
    return edited


def edit_id(source_id: str, content: str) -> str:
    """Id of an edit of message `source_id` whose `content_hash` is `content`.

    Shared by every producer of edits, so an edit made in one place (a response
    filter) is recognized as one where it returns (the agent bridge).
    """
    return shortuuid(name=f"inspect-edit:{json.dumps([source_id, content])}")


def canonical_tool_arguments(arguments: dict[str, Any]) -> str:
    """Serialize tool arguments so that `json_equal` arguments serialize alike.

    A scaffold's JSON round-trip (5.0 sent back as 5) then leaves its copy of a
    call unchanged, as the sandbox bridge's execution grants already treat it.
    """
    return json.dumps(
        json_normalize_numbers(jsonable_python(arguments)), sort_keys=True, default=str
    )


def shown_content(content: str | list[Content]) -> list[Content]:
    """`content` as a list, without the empty text parts that show nothing."""
    items = [ContentText(text=content)] if isinstance(content, str) else content
    return [
        item for item in items if not (isinstance(item, ContentText) and not item.text)
    ]


def shown_text(content: str | list[Content]) -> str:
    """The text of `content` joined as `ChatMessage.text` joins it, without empty text parts.

    Text derived from a message to identify it (a tool error's message, which
    `content_hash` includes; the bridge's thread fingerprints) must use this, so
    empty text parts change it no more than they change `content_hash`.
    """
    return "\n".join(
        item.text for item in shown_content(content) if isinstance(item, ContentText)
    )


def content_hash(message: ChatMessage) -> str:
    """Hash of what a message shows: versions that differ here are different messages.

    Provider-internal fields (reasoning signatures, `internal`, citations), a cache
    breakpoint, the `refusal` flag (not every dialect sends it back), the
    `model` and `source`, metadata and the id are left out, and string content
    equals the same text as a content list. Empty text shows nothing, so an
    empty string, an empty list and a list with an empty text part are equal.
    """
    return mm3_hash(json.dumps(_shown(message), default=str))


def same_content(a: ChatMessage, b: ChatMessage) -> bool:
    """Whether `a` and `b` have the same `content_hash`, without hashing them.

    Compares what each shows rather than serializing it, so a check of a
    message holding inline media against an edit sharing or dropping that
    media does not serialize the media.
    """
    return _dumps_equal(_shown(a), _shown(b))


def _shown(message: ChatMessage) -> list[Any]:
    """What `content_hash` hashes."""
    items = shown_content(message.content)
    return [
        message.role,
        [
            ["text", item.text]
            if isinstance(item, ContentText)
            else ["reasoning", item.reasoning, item.summary, item.redacted]
            if isinstance(item, ContentReasoning)
            else item.model_dump(exclude_none=True, exclude={"internal"})
            for item in items
        ],
        [
            [
                call.id,
                call.type,
                call.function,
                canonical_tool_arguments(call.arguments),
            ]
            for call in message.tool_calls or []
        ]
        if isinstance(message, ChatMessageAssistant)
        else None,
        [
            message.tool_call_id,
            [message.error.type, message.error.message] if message.error else None,
        ]
        if isinstance(message, ChatMessageTool)
        else None,
    ]


_JSON_SCALARS = (int, float, bool, type(None))


def _json_kind(value: Any) -> str | None:
    """The kind of JSON `value` serializes as, or `None` if another type (`default=str`)."""
    if type(value) is str:
        return "string"
    if type(value) in (list, tuple):
        return "array"
    if type(value) is dict:
        return "object"
    if type(value) in _JSON_SCALARS:
        return "scalar"
    return None


def _dumps_equal(a: Any, b: Any) -> bool:
    """Whether `json.dumps(a, default=str) == json.dumps(b, default=str)`.

    Strings, lists and string-keyed dicts are compared in place (a list or
    dict serializes as its members' serializations in order), and values of
    different JSON kinds never serialize alike; anything else is serialized.
    """
    kind_a, kind_b = _json_kind(a), _json_kind(b)
    if kind_a is not None and kind_b is not None and kind_a != kind_b:
        return False
    if kind_a == "string" and kind_b == "string":
        return bool(a == b)
    if kind_a == "array" and kind_b == "array":
        return len(a) == len(b) and all(_dumps_equal(x, y) for x, y in zip(a, b))
    if (
        kind_a == "object"
        and kind_b == "object"
        and all(type(key) is str for key in a)
        and all(type(key) is str for key in b)
    ):
        return list(a) == list(b) and all(_dumps_equal(a[key], b[key]) for key in a)
    return json.dumps(a, default=str) == json.dumps(b, default=str)
