from dataclasses import dataclass
from weakref import WeakKeyDictionary

from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage


@dataclass
class _Ran:
    # the conversation as its agent ran it; the scaffold's own objects
    messages: list[ChatMessage]
    # how many of messages are the opening, which stays provisional until the
    # first agent turn is sent, since a before-generate hook may change it
    opening: int
    sent: bool


_ran: "WeakKeyDictionary[Transcript, dict[str, _Ran]]" = WeakKeyDictionary()


def record_opening(conversation: str, input: list[ChatMessage], *, sent: bool) -> None:
    """Open the conversation's record with its first agent turn's input.

    An input recorded before it is sent is provisional: the first input sent replaces it. Later inputs are not recorded. With concurrent first turns in one conversation, the opening is the first input sent.
    """
    conversations = _ran.setdefault(transcript(), {})
    ran = conversations.get(conversation)
    if ran is None:
        conversations[conversation] = _Ran(list(input), len(input), sent)
    elif sent and not ran.sent:
        ran.messages[: ran.opening] = input
        ran.opening = len(input)
        ran.sent = True


def record_ran(conversation: str, messages: list[ChatMessage]) -> None:
    """Add an agent turn's output, or the results `execute_tools()` returned, to an opened record."""
    ran = _ran.get(transcript(), {}).get(conversation)
    if ran is not None:
        ran.messages.extend(messages)


def ran_messages(
    conversation: str, through: ChatMessage | None = None
) -> list[ChatMessage] | None:
    """The conversation as its agent ran it so far: the first agent turn's input, then each agent-turn output returned to the agent and the results `execute_tools()` returned.

    An output is recorded when `generate()` returns it, whether or not the agent keeps it. react drops two kinds of output that stay recorded: a refusal it generates again under `retry_refusals` (without `fail_on_refusal`, which raises instead), and a `model_length` turn its overflow recovery removes.

    Args:
        conversation: The conversation.
        through: Cut the record after this message, matched by identity; the whole record when it is not in the record.

    Returns:
        The record, or None when no agent turn has opened the conversation.
    """
    ran = _ran.get(transcript(), {}).get(conversation)
    if ran is None:
        return None
    messages = ran.messages
    if through is not None:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index] is through:
                return messages[: index + 1]
    return list(messages)
