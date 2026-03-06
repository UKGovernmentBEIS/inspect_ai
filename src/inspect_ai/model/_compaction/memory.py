from shortuuid import uuid

from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.tool import ToolCall

# Name of memory tool
MEMORY_TOOL = "memory"

# Arguments to clear from memory tool calls (contain large content)
MEMORY_CONTENT_ARGS = ("file_text", "insert_text", "new_str")


def clear_memory_content(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Clear content arguments from memory tool calls.

    When memory integration is active, the model may save content to memory
    before compaction. The saved content appears in ToolCall.arguments,
    which would otherwise persist after compaction. This function clears
    those large content arguments while preserving the tool call metadata
    (command, path, etc.) so the model knows what it saved and where.
    """
    result = list(messages)
    for i, msg in enumerate(result):
        if isinstance(msg, ChatMessageAssistant) and msg.tool_calls:
            new_tool_calls: list[ToolCall] = []
            modified = False
            for tc in msg.tool_calls:
                if tc.function == MEMORY_TOOL and any(
                    arg in tc.arguments for arg in MEMORY_CONTENT_ARGS
                ):
                    # Clear content args, keep metadata args
                    new_args = {
                        k: "(content saved to memory)"
                        if k in MEMORY_CONTENT_ARGS
                        else v
                        for k, v in tc.arguments.items()
                    }
                    new_tool_calls.append(
                        ToolCall(id=tc.id, function=tc.function, arguments=new_args)
                    )
                    modified = True
                else:
                    new_tool_calls.append(tc)
            if modified:
                result[i] = msg.model_copy(
                    update={"id": uuid(), "tool_calls": new_tool_calls}
                )
    return result


def has_memory_calls(messages: list[ChatMessage]) -> bool:
    """Check if any messages contain memory tool calls."""
    for msg in messages:
        if isinstance(msg, ChatMessageAssistant) and msg.tool_calls:
            if any(tc.function == MEMORY_TOOL for tc in msg.tool_calls):
                return True
    return False


def memory_warning_message() -> ChatMessageUser:
    return ChatMessageUser(
        content=(
            "Context compaction approaching. Use memory() to save concise notes on:\n"
            "- Key decisions made and why\n"
            "- Important discoveries (APIs, data structures, error solutions)\n"
            "- Critical file paths and changes made\n"
            "- Next steps to continue the task\n\n"
            "Do NOT save raw tool outputs or full file contents—keep notes brief and synthesized."
        )
    )
