"""Failed tool calls reach a Bedrock model with their error message.

Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/5951

The Bedrock (Converse) provider marked a failed tool result with
`status="error"` but sent only the tool message's content, which Inspect leaves
empty when a tool call fails. The model was told the call failed and nothing
else, so it could not correct a path or react to a timeout the way it can on
the native Anthropic, OpenAI and Google providers.
"""

from __future__ import annotations

from typing import Any

from inspect_ai._util.content import ContentText
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.model._providers.bedrock import converse_chat_message
from inspect_ai.tool._tool_call import ToolCallError


async def _tool_result(error: ToolCallError | None, content: Any = "") -> Any:
    messages = await converse_chat_message(
        ChatMessageTool(
            content=content, tool_call_id="call_1", function="read_file", error=error
        )
    )
    assert messages is not None
    tool_result = messages[0].content[0].toolResult
    assert tool_result is not None
    return tool_result


def _texts(tool_result: Any) -> list[str]:
    return [part.text for part in tool_result.content or [] if part.text is not None]


async def test_bedrock_tool_success_sends_content_only() -> None:
    """A successful tool result is unchanged."""
    result = await _tool_result(None, "result text")
    assert result.status == "success"
    assert _texts(result) == ["result text"]


async def test_bedrock_tool_error_sends_the_error_message() -> None:
    """A failed tool result carries the reason, not just the status."""
    result = await _tool_result(
        ToolCallError("unknown", "file not found: /etc/x"), "partial output"
    )
    assert result.status == "error"
    # Exactly one part: the error replaces the content, as it does for Anthropic.
    assert _texts(result) == ["file not found: /etc/x"]


async def test_bedrock_tool_error_does_not_duplicate_text_content() -> None:
    """Text the error already repeats is not sent twice."""
    result = await _tool_result(
        ToolCallError("timeout", "timed out after 30s"),
        [ContentText(type="text", text="timed out after 30s")],
    )
    assert _texts(result) == ["timed out after 30s"]


async def test_bedrock_tool_error_without_message_uses_a_placeholder() -> None:
    """An error with no message and no content still sends a non-empty part."""
    result = await _tool_result(ToolCallError("unknown", ""))
    texts = _texts(result)
    assert len(texts) == 1
    assert texts[0].strip() != ""
