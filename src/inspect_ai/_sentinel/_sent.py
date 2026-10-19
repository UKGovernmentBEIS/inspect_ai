from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage


@dataclass
class _Sent:
    # every message sent, in the order sent; mostly the scaffold's own objects
    messages: list[ChatMessage] = field(default_factory=list)
    # the versions sent under each message id
    versions: dict[str | None, list[ChatMessage]] = field(default_factory=dict)
    # an id unchanged messages were rebuilt under -> those messages as first
    # sent; each keeps only its latest rebuilt id, so the index stays one
    # entry per message however often a scaffold rebuilds it, and an id
    # reused for another message does not displace the first
    aliases: dict[str | None, list[ChatMessage]] = field(default_factory=dict)
    # id() of a message as first sent -> its latest rebuilt id
    latest_alias: dict[int, str | None] = field(default_factory=dict)
    # what the previous call sent at each position, as first sent; a list of
    # its own, since the caller may go on to extend the list it passed
    previous: list[ChatMessage] = field(default_factory=list)


_sent: "WeakKeyDictionary[Transcript, dict[str, _Sent]]" = WeakKeyDictionary()


def record_sent(conversation: str, input: list[ChatMessage]) -> None:
    """Add what one of the conversation's agent turns sends to what it has sent.

    A message counts once: again only as a changed version of a message sent before (the same id, different content), and not when it is unchanged from the message at its position in the previous call, as a configured system message is, rebuilt with a fresh id for every call. The latest id a message was rebuilt under is remembered as that message, so the rebuilt copy is not counted again when it comes back later or elsewhere; an earlier rebuilt id is forgotten, so a scaffold that alternates between two rebuilt ids for one message can see it repeated. An unchanged message is usually the very object sent before, so most messages are checked by identity, not compared.
    """
    sent = _sent.setdefault(transcript(), {}).setdefault(conversation, _Sent())
    previous: list[ChatMessage] = []
    for position, message in enumerate(input):
        previous.append(_record(sent, position, message))
    sent.previous = previous


def _record(sent: _Sent, position: int, message: ChatMessage) -> ChatMessage:
    # the message as first sent that this one is, recording it if it is new
    candidates = [
        *sent.versions.get(message.id, []),
        *sent.aliases.get(message.id, []),
    ]
    for candidate in candidates:
        if candidate is message:
            return candidate
    for candidate in candidates:
        if _same(candidate, message):
            return candidate
    if position < len(sent.previous) and _same(sent.previous[position], message):
        original = sent.previous[position]
        _alias(sent, message.id, original)
        return original
    sent.versions.setdefault(message.id, []).append(message)
    sent.messages.append(message)
    return message


def _alias(sent: _Sent, rebuilt: str | None, original: ChatMessage) -> None:
    key = id(original)  # originals are held in sent.messages, so ids are stable
    if key in sent.latest_alias:
        earlier = sent.latest_alias[key]
        originals = sent.aliases[earlier]
        originals[:] = [kept for kept in originals if kept is not original]
        if not originals:
            del sent.aliases[earlier]
    sent.aliases.setdefault(rebuilt, []).append(original)
    sent.latest_alias[key] = rebuilt


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
