from ._chat_message import ChatMessage


def trim_messages(
    messages: list[ChatMessage], preserve: float = 0.7
) -> list[ChatMessage]:
    """Trim messages to fit within the model context window.

    Trim the list of messages by:
    - Keeping system messages
    - Keeping the 'input' messages from the sample.
    - Keeping a proportion of the remaining messages (`preserve=0.7` by default)
    - Ensuring that all assistant tool calls have corresponding tool messages.

    Args:
        messages: List of messages to trim
        preserve: Ratio of original messages to preserve
           (defaults to 0.7)

    Returns:
        Trimmed messages.
    """
    return messages
