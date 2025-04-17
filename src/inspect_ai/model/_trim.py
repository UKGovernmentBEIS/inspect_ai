from dataclasses import dataclass, field

from ._chat_message import ChatMessage


def trim_messages(
    messages: list[ChatMessage], preserve: float = 0.7
) -> list[ChatMessage]:
    """Trim message list to fit within model context.

    Trim the list of messages by:
    - Retaining all system messages.
    - Retaining the 'input' messages from the sample.
    - Preserving a proportion of the remaining messages (`preserve=0.7` by default).
    - Ensuring that all assistant tool calls have corresponding tool messages.

    Args:
        messages: List of messages to trim.
        preserve: Ratio of converation messages to preserve
            (defaults to 0.7)

    Returns:
        Trimmed messages.
    """
    # validate preserve
    if not 0 <= preserve <= 1:
        raise ValueError(f"preserve must be in range [0,1], got {preserve}")

    # partition messages
    partitioned = _partition_messages(messages)

    # slice messages from the beginning of the conversation as-per preserve
    start_idx = int(len(partitioned.conversation) * (1 - preserve))
    preserved_messages = partitioned.conversation[start_idx:]

    # one last step: many model apis require tool messages to have a parent assistant
    # message with a corresponding tool_call_id. to ensure this, we build the
    # final list of conversation messages by filtering out tool messages for which
    # we haven't seen a corresponding assistant message with their id
    conversation_messages: list[ChatMessage] = []
    active_tool_ids = set()
    for message in preserved_messages:
        if message.role == "assistant":
            active_tool_ids = {tc.id for tc in (message.tool_calls or [])}
            conversation_messages.append(message)
        elif message.role == "tool" and message.tool_call_id in active_tool_ids:
            conversation_messages.append(message)
        elif message.role == "user":
            active_tool_ids = set()
            conversation_messages.append(message)

    # return trimmed messages
    return partitioned.system + partitioned.input + conversation_messages


@dataclass
class PartitionedMessages:
    system: list[ChatMessage] = field(default_factory=list)
    input: list[ChatMessage] = field(default_factory=list)
    conversation: list[ChatMessage] = field(default_factory=list)


def _partition_messages(messages: list[ChatMessage]) -> PartitionedMessages:
    # first pass at partitioning
    partitioned = PartitionedMessages()
    for message in messages:
        if message.role == "system":
            partitioned.system.append(message)
        elif message.source == "input":
            partitioned.input.append(message)
        else:
            partitioned.conversation.append(message)

    # if there are no input messages then take up to the first user message
    if len(partitioned.input) == 0:
        while partitioned.conversation:
            message = partitioned.conversation.pop(0)
            partitioned.input.append(message)
            if message.role == "user":
                break

    # all done!
    return partitioned
