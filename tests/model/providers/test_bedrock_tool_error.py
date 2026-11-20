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

import pytest

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


@pytest.mark.parametrize(
    "error,expected_status,expected_texts",
    [
        (None, "success", []),
        (
            ToolCallError("unknown", "file not found: /etc/x"),
            "error",
            ["file not found: /etc/x"],
        ),
    ],
)
async def test_bedrock_tool_error_message_is_sent(
    error: ToolCallError | None,
    expected_status: str,
    expected_texts: list[str],
) -> None:
    result = await _tool_result(error)
    assert result.status == expected_status
    texts = _texts(result)
    for text in expected_texts:
        assert text in texts


async def test_bedrock_tool_error_keeps_reported_content() -> None:
    """Content the tool did produce is still sent alongside the error."""
    result = await _tool_result(
        ToolCallError("timeout", "timed out after 30s"), "partial output"
    )
    texts = _texts(result)
    assert "timed out after 30s" in texts
    assert "partial output" in texts


async def test_bedrock_tool_error_without_message_falls_back_to_content_text() -> None:
    """An empty error message falls back to the text content the tool kept."""
    result = await _tool_result(
        ToolCallError("unknown", ""), [ContentText(type="text", text="kept text")]
    )
    texts = _texts(result)
    assert "kept text" in texts
