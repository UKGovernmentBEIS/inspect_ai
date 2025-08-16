from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser


def user_prompt(messages: list[ChatMessage]) -> ChatMessageUser:
    """Get the last "user" message within a message history.

    Args:
       messages: Message history.

    Raises:
       ValueError: If no user messages are in the history.
    """
    prompt = next((m for m in reversed(messages) if m.role == "user"), None)
    if prompt is not None:
        return prompt
    else:
        raise ValueError("No user messages available in the history.")
