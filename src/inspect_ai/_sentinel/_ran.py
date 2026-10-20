from weakref import WeakKeyDictionary

from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage

# each conversation's messages as its agent ran it; the scaffold's own objects
_ran: "WeakKeyDictionary[Transcript, dict[str, list[ChatMessage]]]" = (
    WeakKeyDictionary()
)


def record_opening(conversation: str, input: list[ChatMessage]) -> None:
    """Open the conversation's record with its first agent turn's input; later inputs are not recorded."""
    conversations = _ran.setdefault(transcript(), {})
    if conversation not in conversations:
        conversations[conversation] = list(input)


def record_ran(conversation: str, messages: list[ChatMessage]) -> None:
    """Add an agent turn's output, or the results `execute_tools()` returned, to an opened record."""
    ran = _ran.get(transcript(), {}).get(conversation)
    if ran is not None:
        ran.extend(messages)


def ran_messages(conversation: str) -> list[ChatMessage] | None:
    """The conversation as its agent ran it so far: the first agent turn's input, then each turn's output and the results `execute_tools()` returned.

    None when no agent turn has opened the conversation.
    """
    ran = _ran.get(transcript(), {}).get(conversation)
    return list(ran) if ran is not None else None
