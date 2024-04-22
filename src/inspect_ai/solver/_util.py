from inspect_ai.model import ChatMessage, ChatMessageSystem


def append_system_message(
    messages: list[ChatMessage], message: ChatMessageSystem
) -> None:
    # find last index of any existing system message
    lastIndex = -1
    for i in list(reversed(range(0, len(messages)))):
        if isinstance(messages[i], ChatMessageSystem):
            lastIndex = i
            break

    # insert it
    messages.insert(lastIndex + 1, message)
