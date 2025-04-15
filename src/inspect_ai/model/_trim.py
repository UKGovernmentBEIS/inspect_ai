from typing import NamedTuple

from ._chat_message import ChatMessage


def trim_messages(
    messages: list[ChatMessage], preserve: float = 0.7
) -> list[ChatMessage]:
    """Trim message list to fit within model context.

    ::: callout-note
    The `trim_messages()` function is available only in the development version of Inspect.
    To install the development version from GitHub:

    ``` bash
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
    ```
    :::

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
    # partition messages
    system_messages, input_messages, conversation_messages = _partition_messages(
        messages
    )

    # slice messages from the beginning of the conversation as-per preserve
    start_idx = max(1, int(len(conversation_messages) * (1 - preserve)))
    preserved_messages = conversation_messages[start_idx:]

    # one last step: many model apis require tool messages to have a parent assistant
    # message with a corresponding tool_call_id. to ensure this, we build the
    # final list of conversation messages by filtering out tool messages for which
    # we haven't seen a corresponding assistatn message with their id
    conversation_messages = []
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
    return system_messages + input_messages + conversation_messages


class PartitionedMessages(NamedTuple):
    system: list[ChatMessage] = []
    input: list[ChatMessage] = []
    conversation: list[ChatMessage] = []


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
