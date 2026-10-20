"""Regression tests for Bedrock sending a failed tool call's error message.

The Converse provider marks a failed tool result with ``status="error"``, but
previously sent only the (empty) content, so the model was told that the call
failed without ever seeing why. The native Anthropic provider sends
``error.message`` with ``is_error=True``, and OpenAI and Google send it as the
result text; Bedrock must do the equivalent or an agent cannot recover from
what actually went wrong. See #5951.
"""

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai.model._chat_message import ChatMessageTool  # noqa: E402
from inspect_ai.model._providers.bedrock import converse_chat_message  # noqa: E402
from inspect_ai.tool._tool_call import ToolCallError  # noqa: E402


async def test_failed_tool_call_sends_error_message():
    message = ChatMessageTool(
        content="",
        tool_call_id="read_1",
        function="read_file",
        error=ToolCallError("file_not_found", "File not found: /etc/missing.conf"),
    )

    result = await converse_chat_message(message)

    assert result is not None
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.status == "error"
    texts = [c.text for c in tool_result.content if c.text is not None]
    assert "File not found: /etc/missing.conf" in texts


async def test_failed_tool_call_appends_error_to_content():
    # A tool may return partial output before failing; the error message is
    # appended, not swapped in, so the model keeps both.
    message = ChatMessageTool(
        content="partial output",
        tool_call_id="read_1",
        function="read_file",
        error=ToolCallError("output_limit", "output limit exceeded"),
    )

    result = await converse_chat_message(message)

    assert result is not None
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.status == "error"
    texts = [c.text for c in tool_result.content if c.text is not None]
    assert "partial output" in texts
    assert "output limit exceeded" in texts


async def test_successful_tool_call_unchanged():
    message = ChatMessageTool(
        content="2", tool_call_id="addition_1", function="addition"
    )

    result = await converse_chat_message(message)

    assert result is not None
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.status == "success"
    texts = [c.text for c in tool_result.content if c.text is not None]
    assert texts == ["2"]
