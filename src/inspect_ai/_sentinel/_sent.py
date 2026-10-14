from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage


@dataclass
class _Sent:
    # every message sent, in the order sent; mostly the scaffold's own objects
    messages: list[ChatMessage] = field(default_factory=list)
    # every version sent of each message id
    versions: dict[str | None, list[ChatMessage]] = field(default_factory=dict)
    # the previous call's input, for messages rebuilt with a fresh id each call
    previous: list[ChatMessage] = field(default_factory=list)


_sent: "WeakKeyDictionary[Transcript, dict[str, _Sent]]" = WeakKeyDictionary()


def record_sent(conversation: str, input: list[ChatMessage]) -> None:
    """Add what one of the conversation's agent turns sends to what it has sent.

    A message counts once: again only as a changed version of a message sent before (the same id, different content), and not when it is unchanged from the message at its position in the previous call, as a configured system message is, rebuilt with a fresh id for every call. An unchanged message is usually the very object sent before, so most messages are checked by identity, not compared.
    """
    sent = _sent.setdefault(transcript(), {}).setdefault(conversation, _Sent())
    for position, message in enumerate(input):
        versions = sent.versions.get(message.id, [])
        if any(version is message for version in versions):
            continue
        if position < len(sent.previous) and _same(sent.previous[position], message):
            continue
        if any(_same(version, message) for version in versions):
            continue
        sent.versions.setdefault(message.id, []).append(message)
        sent.messages.append(message)
    sent.previous = input


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
