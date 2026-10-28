"""Stable message ID generation based on content hash."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

import mmh3
from shortuuid import uuid as shortuuid

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.hash import mm3_hash

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
        json_str = json.dumps(msg_dict, sort_keys=True)
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


def with_edited_id(source: ChatMessage, edited: EditedT) -> EditedT:
    """`edited` under an id of its own, recording its source in `derived_from`.

    Different content never shares an id. The id is derived from the source's
    id and the edited content, so a message edited the same way on every model
    call is one message. An edit of an edit names the original source. An edit
    that leaves the content unchanged keeps the source's id.
    """
    content = content_hash(edited)
    if source.id is None:
        edited.id = shortuuid()
    elif content == content_hash(source):
        edited.id = source.id
    else:
        original = _edited_from(source) or source.id
        edited.id = edit_id(original, content)
        edited.metadata = (edited.metadata or {}) | {"derived_from": [original]}
    return edited


def _edited_from(message: ChatMessage) -> str | None:
    """The original a message is an edit of, if `with_edited_id` made it."""
    sources = (message.metadata or {}).get("derived_from")
    if (
        isinstance(sources, list)
        and len(sources) == 1
        and isinstance(sources[0], str)
        and message.id == edit_id(sources[0], content_hash(message))
    ):
        return sources[0]
    return None


def edit_id(source_id: str, content: str) -> str:
    """Id of an edit of message `source_id` whose `content_hash` is `content`.

    Shared by every producer of edits, so an edit made in one place (a response
    filter) is recognized as one where it returns (the agent bridge).
    """
    return shortuuid(name=f"inspect-edit:{json.dumps([source_id, content])}")


def content_hash(message: ChatMessage) -> str:
    """Hash of what a message shows: versions that differ here are different messages.

    Provider-internal fields (reasoning signatures, `internal`, citations), the
    `model` and `source`, metadata and the id are left out, and string content
    equals the same text as a content list.
    """
    items = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else message.content
    )
    return mm3_hash(
        json.dumps(
            [
                message.role,
                [
                    ["text", item.text]
                    if isinstance(item, ContentText)
                    else ["reasoning", item.reasoning, item.redacted]
                    if isinstance(item, ContentReasoning)
                    else item.model_dump(exclude_none=True, exclude={"internal"})
                    for item in items
                ],
                [
                    [
                        call.id,
                        call.function,
                        json.dumps(call.arguments, sort_keys=True, default=str),
                    ]
                    for call in message.tool_calls or []
                ]
                if isinstance(message, ChatMessageAssistant)
                else None,
                [
                    message.tool_call_id,
                    [message.error.type, message.error.message]
                    if message.error
                    else None,
                ]
                if isinstance(message, ChatMessageTool)
                else None,
            ],
            default=str,
        )
    )
