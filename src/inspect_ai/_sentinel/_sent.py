from dataclasses import dataclass, field
from hashlib import sha1
from typing import NamedTuple
from weakref import WeakKeyDictionary

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import (
    Transcript,
    TranscriptHistoryUnavailableError,
    transcript,
)
from inspect_ai.model._chat_message import ChatMessage

# events read per page while folding, so a long history is never read at once
_PAGE = 256


class _Position(NamedTuple):
    event: int  # logical index of the model event in the transcript
    message: int  # index of the message in the event's input


@dataclass
class _Conversation:
    # logical index of the next transcript event to fold
    cursor: int = 0
    # where each message sent is, in the order sent
    positions: list[_Position] = field(default_factory=list)
    # (message id, content digest) of every version sent
    versions: set[tuple[str | None, bytes]] = field(default_factory=set)
    # (role, content digest) of each message in the previous call's input
    previous: list[tuple[str, bytes]] = field(default_factory=list)
    unavailable: bool = False


@dataclass
class _Sent:
    # agent-turn model event uuid -> conversation, until its conversation folds it
    turns: dict[str, str] = field(default_factory=dict)
    conversations: dict[str, _Conversation] = field(default_factory=dict)


# no ChatMessage is held here: messages are read back from the transcript, so
# a bounded transcript can evict them
_sent: "WeakKeyDictionary[Transcript, _Sent]" = WeakKeyDictionary()


def record_turn(event: ModelEvent, conversation: str) -> None:
    if event.uuid is not None:
        _sent.setdefault(transcript(), _Sent()).turns[event.uuid] = conversation


def sent_messages(conversation: str) -> list[ChatMessage] | None:
    """Every message the conversation's agent turns have sent, in the order sent.

    Folds the transcript from where the last call left off, then reads each message back from its model event. A message counts once: again only when its content changed (a new version), and not when a call rebuilt it with a fresh id at the position it had in the call before (a configured system message).

    Returns:
        The messages, or `None` when an earlier call's event can no longer be read.
    """
    current = transcript()
    sent = _sent.setdefault(current, _Sent())
    state = sent.conversations.setdefault(conversation, _Conversation())
    if state.unavailable:
        return None
    try:
        _fold(current, sent.turns, conversation, state)
        return _resolve(current, state.positions)
    except TranscriptHistoryUnavailableError:
        # evicted events cannot come back, so the history stays unavailable
        state.unavailable = True
        return None


def _fold(
    current: Transcript, turns: dict[str, str], conversation: str, state: _Conversation
) -> None:
    while page := current.history.events_from(state.cursor, _PAGE):
        for offset, event in enumerate(page):
            if (
                isinstance(event, ModelEvent)
                and event.uuid is not None
                and turns.get(event.uuid) == conversation
            ):
                del turns[event.uuid]
                _fold_input(state, state.cursor + offset, event.input)
        state.cursor += len(page)


def _fold_input(state: _Conversation, index: int, input: list[ChatMessage]) -> None:
    current: list[tuple[str, bytes]] = []
    for position, message in enumerate(input):
        digest = _digest(message)
        current.append((message.role, digest))
        if (message.id, digest) in state.versions:
            continue
        # rebuilt with a fresh id for every call (a configured system message)
        if position < len(state.previous) and state.previous[position] == current[-1]:
            continue
        state.versions.add((message.id, digest))
        state.positions.append(_Position(index, position))
    state.previous = current


def _digest(message: ChatMessage) -> bytes:
    # what the model is sent: the id, source and metadata are not
    content = message.model_dump_json(exclude={"id", "source", "metadata"})
    return sha1(content.encode(), usedforsecurity=False).digest()


def _resolve(current: Transcript, positions: list[_Position]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    index, event = -1, None
    for position in positions:
        if event is None or index != position.event:
            index = position.event
            event = _model_event(current, index)
        messages.append(event.input[position.message])
    return messages


def _model_event(current: Transcript, index: int) -> ModelEvent:
    [event] = current.history.events_from(index, 1)
    assert isinstance(event, ModelEvent)
    return event
