from inspect_ai._util.format import format_function_call
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant


def message_text(message: ChatMessage) -> str:
    return message.text


def message_tool_calls(message: ChatMessage) -> str | None:
    if isinstance(message, ChatMessageAssistant) and message.tool_calls is not None:
        tool_calls = "\n".join(
            [
                format_function_call(
                    tool_call.function, tool_call.arguments, width=1000
                )
                for tool_call in message.tool_calls
            ]
        )
        return tool_calls
    else:
        return None
