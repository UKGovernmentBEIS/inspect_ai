from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage


@dataclass
class _Sent:
    # every message sent, in the order sent; mostly the scaffold's own objects
    messages: list[ChatMessage] = field(default_factory=list)
    # the versions sent under each message id; an id rebuilt for an unchanged
    # message maps to the message first sent, so a fresh copy is not kept
    versions: dict[str | None, list[ChatMessage]] = field(default_factory=dict)
    # what the previous call sent at each position, as first sent; a list of
    # its own, since the caller may go on to extend the list it passed
    previous: list[ChatMessage] = field(default_factory=list)


_sent: "WeakKeyDictionary[Transcript, dict[str, _Sent]]" = WeakKeyDictionary()


def record_sent(conversation: str, input: list[ChatMessage]) -> None:
    """Add what one of the conversation's agent turns sends to what it has sent.

    A message counts once: again only as a changed version of a message sent before (the same id, different content), and not when it is unchanged from the message at its position in the previous call, as a configured system message is, rebuilt with a fresh id for every call. A rebuilt id is remembered as the message it repeats, so it is not counted again when it comes back later or elsewhere. An unchanged message is usually the very object sent before, so most messages are checked by identity, not compared.
    """
    sent = _sent.setdefault(transcript(), {}).setdefault(conversation, _Sent())
    previous: list[ChatMessage] = []
    for position, message in enumerate(input):
        previous.append(_record(sent, position, message))
    sent.previous = previous


def _record(sent: _Sent, position: int, message: ChatMessage) -> ChatMessage:
    # the message as first sent that this one is, recording it if it is new
    versions = sent.versions.setdefault(message.id, [])
    for version in versions:
        if version is message:
            return version
    for version in versions:
        if _same(version, message):
            return version
    if position < len(sent.previous) and _same(sent.previous[position], message):
        repeated = sent.previous[position]
        versions.append(repeated)
        return repeated
    versions.append(message)
    sent.messages.append(message)
    return message


def sent_messages(conversation: str) -> list[ChatMessage]:
    """Every message the conversation's agent turns have sent so far, in the order sent."""
    found = _sent.get(transcript(), {}).get(conversation)
    return list(found.messages) if found is not None else []


# the id, source and metadata are not sent to the model
_NOT_SENT = {"id": None, "source": None, "metadata": None}


def _same(a: ChatMessage, b: ChatMessage) -> bool:
    return a is b or (
        type(a) is type(b)
        and a.model_copy(update=_NOT_SENT) == b.model_copy(update=_NOT_SENT)
    )
