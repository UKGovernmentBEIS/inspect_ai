"""Stable message ID generation based on content hash."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import mmh3
from shortuuid import uuid as shortuuid

from ._chat_message import ChatMessage
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

    def get_id(message: ChatMessage, conversation: list[ChatMessage]) -> str:
        """Get stable ID for message, avoiding duplicates within conversation."""
        msg_hash = hash_message(message)
        existing_ids = hash_to_ids.get(msg_hash, [])
        conversation_ids = {m.id for m in conversation if m.id}

        # Reuse existing ID if not already in this conversation
        for existing_id in existing_ids:
            if existing_id not in conversation_ids:
                return existing_id

        # Generate new ID
        new_id = shortuuid()
        hash_to_ids.setdefault(msg_hash, []).append(new_id)
        return new_id

    def apply_ids_to_messages(messages: Sequence[ChatMessage]) -> None:
        """Apply stable IDs to a list of messages."""
        processed: list[ChatMessage] = []
        for msg in messages:
            msg.id = get_id(msg, processed)
            processed.append(msg)

    def apply_ids(target: Sequence[ChatMessage] | ModelEvent) -> None:
        """Apply stable IDs to messages or a ModelEvent."""
        # Use duck typing to check for ModelEvent (avoid circular import)
        if hasattr(target, "event") and getattr(target, "event") == "model":
            input_messages = list(target.input)  # type: ignore[union-attr]
            apply_ids_to_messages(input_messages)
            output = target.output  # type: ignore[union-attr]
            if isinstance(output, ModelOutput) and output.choices:
                output.message.id = get_id(output.message, input_messages)
        else:
            apply_ids_to_messages(target)  # type: ignore[arg-type]

    return apply_ids
