from dataclasses import dataclass, field

from shortuuid import uuid

from inspect_ai._util.content import Content, ContentText

from ._chat_message import ChatMessage


async def trim_messages(
    messages: list[ChatMessage], preserve: float = 0.7
) -> list[ChatMessage]:
    """Trim message list to fit within model context.

    Trim the list of messages by:
    - Retaining all system messages.
    - Retaining the 'input' messages from the sample.
    - Preserving a proportion of the remaining messages (`preserve=0.7` by default).
    - Ensuring that all assistant tool calls have corresponding tool messages.
    - Ensuring that the sequence of messages doesn't end with an assistant message.

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
    partitioned = partition_messages(messages)

    # slice messages from the beginning of the conversation as-per preserve
    start_idx = int(len(partitioned.conversation) * (1 - preserve))
    preserved_messages = partitioned.conversation[start_idx:]

    # many model apis require tool messages to have a parent assistant
    # message with a corresponding tool_call_id. to ensure this, we build the
    # final list of conversation messages by filtering out tool messages for which
    # we haven't seen a corresponding assistant message with their id
    conversation_messages: list[ChatMessage] = []
    active_tool_ids: set[str] = set()
    for message in preserved_messages:
        if message.role == "assistant":
            active_tool_ids = {tc.id for tc in (message.tool_calls or [])}
            conversation_messages.append(message)
        elif message.role == "tool" and message.tool_call_id in active_tool_ids:
            conversation_messages.append(message)
        elif message.role == "user":
            active_tool_ids = set()
            conversation_messages.append(message)

    # also filter out orphan tool_calls (assistant tool_calls without corresponding
    # tool results). this can happen when trimming removes tool messages but keeps
    # the assistant message with tool_calls. some model APIs (e.g. Anthropic) require
    # every tool_use to have a corresponding tool_result.
    tool_ids_with_results = {
        msg.tool_call_id for msg in conversation_messages if msg.role == "tool"
    }
    sanitized_messages: list[ChatMessage] = []
    for msg in conversation_messages:
        if msg.role == "assistant" and msg.tool_calls:
            # Keep only tool_calls that have corresponding results
            valid_tool_calls = [
                tc for tc in msg.tool_calls if tc.id in tool_ids_with_results
            ]
            if len(valid_tool_calls) != len(msg.tool_calls):
                # Some tool_calls were orphaned, update the message
                msg = msg.model_copy(
                    update={
                        "tool_calls": valid_tool_calls if valid_tool_calls else None
                    }
                )
        sanitized_messages.append(msg)
    conversation_messages = sanitized_messages

    # it's possible that we end with an assistant message w/ if so, remove it
    if len(conversation_messages) and conversation_messages[-1].role == "assistant":
        conversation_messages.pop()

    # return trimmed messages with citations stripped
    return strip_citations(
        partitioned.system + partitioned.input + conversation_messages
    )


@dataclass
class PartitionedMessages:
    system: list[ChatMessage] = field(default_factory=list)
    input: list[ChatMessage] = field(default_factory=list)
    conversation: list[ChatMessage] = field(default_factory=list)


def partition_messages(messages: list[ChatMessage]) -> PartitionedMessages:
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


def strip_citations(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Strip citations from all ContentText blocks in messages.

    Citations reference server-side tool results (e.g., web_search) by index.
    When trimming or compaction removes messages containing those results,
    citations become dangling references that cause API errors.
    """
    result: list[ChatMessage] = []
    for msg in messages:
        if isinstance(msg.content, list):
            new_content: list[Content] = []
            modified = False
            for content in msg.content:
                if isinstance(content, ContentText) and content.citations:
                    new_content.append(content.model_copy(update={"citations": None}))
                    modified = True
                else:
                    new_content.append(content)
            if modified:
                result.append(
                    msg.model_copy(update={"id": uuid(), "content": new_content})
                )
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result
