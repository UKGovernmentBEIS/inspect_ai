"""The rows of the Messages tab: tool messages folded into the message that called them."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from inspect_ai._util.content import Content, ContentText
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
)

SYSTEM_ROW_ID = "sys-message-6815A84B062A"
"""Id of the synthetic row the viewer renders for the merged system messages."""


@dataclass
class MessageRow:
    message: ChatMessage
    tool_messages: list[ChatMessageTool] = field(default_factory=list)


def message_rows(messages: Sequence[ChatMessage]) -> list[MessageRow]:
    """Fold a conversation the way the viewer's `resolveMessages` does.

    Every non-tool message starts a row and collects the tool messages that
    follow it (a leading tool message has no row and is dropped); id-less
    messages get `msg-{index}`; all system messages merge into one synthetic
    first row.
    """
    rows: list[MessageRow] = []
    for index, message in enumerate(messages):
        if message.id is None:
            message = message.model_copy(update={"id": f"msg-{index}"})
        if isinstance(message, ChatMessageTool):
            if rows:
                rows[-1].tool_messages.append(message)
            continue
        rows.append(MessageRow(message))
    system = merged_system_message(
        [row.message for row in rows if isinstance(row.message, ChatMessageSystem)]
    )
    rows = [row for row in rows if not isinstance(row.message, ChatMessageSystem)]
    return ([MessageRow(system)] if system else []) + rows


def merged_system_message(
    messages: Sequence[ChatMessageSystem],
) -> ChatMessageSystem | None:
    content: list[Content] = []
    for message in messages:
        items = (
            [message.content] if isinstance(message.content, str) else message.content
        )
        content.extend(
            ContentText(text=item) if isinstance(item, str) else item for item in items
        )
    if not content:
        return None
    return ChatMessageSystem(id=SYSTEM_ROW_ID, content=content, source="input")


def row_anchors(rows: Sequence[MessageRow]) -> list[str]:
    """One unique find anchor per row (mirrors the viewer's `messageRowAnchorIds`).

    A row's anchor is its message id (the empty string for an empty id) unless
    a prior row already holds that anchor; then `id#index`, with `#index`
    repeated while the result is taken. Only prior rows are consulted, so an
    anchor never changes when a live sample appends rows.
    """
    assigned: set[str] = set()
    anchors: list[str] = []
    for index, row in enumerate(rows):
        anchor = row.message.id or ""
        if anchor in assigned:
            anchor = f"{anchor}#{index}"
            while anchor in assigned:
                anchor += f"#{index}"
        assigned.add(anchor)
        anchors.append(anchor)
    return anchors


def messages_from_events(events: Iterable[Event]) -> list[ChatMessage]:
    """The running-sample conversation as the viewer's `messagesFromEvents` builds it.

    Each successful model event's input is merged in order: a known id moves
    the insertion cursor to its position, an unseen id is inserted after the
    cursor (which starts at the end of the list); the output message appends.
    Messages without ids are skipped.
    """
    messages: list[ChatMessage] = []
    positions: dict[str, int] = {}
    for event in events:
        if not isinstance(event, ModelEvent) or event.error:
            continue
        cursor = len(messages) - 1
        seen: set[str] = set()
        for message in event.input:
            if not message.id or message.id in seen:
                continue
            seen.add(message.id)
            known = positions.get(message.id)
            if known is not None:
                cursor = known
                continue
            cursor += 1
            messages.insert(cursor, message)
            for index in range(cursor, len(messages)):
                id = messages[index].id
                if id:
                    positions[id] = index
        output = event.output.choices[0].message if event.output.choices else None
        if output is not None and output.id and output.id not in positions:
            positions[output.id] = len(messages)
            messages.append(output)
    return messages
