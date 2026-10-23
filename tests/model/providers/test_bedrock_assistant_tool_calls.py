"""Regression tests for Bedrock keeping assistant text/reasoning with tool calls.

The Bedrock provider must preserve assistant text and reasoning content when the
same assistant turn also contains tool calls.

Previously `converse_chat_message` emitted one assistant message per tool call
containing only a `toolUse` block, dropping any `ContentText`/`ContentReasoning`
the model produced in the same turn. In multi-turn tool-calling evals this
removed the model's interleaved reasoning from later-turn context. See #4457.
"""

import pytest

from inspect_ai.model._call_tools import execute_tools
from inspect_ai.tool import Tool, tool

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai._util.content import (  # noqa: E402
    Content,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model._chat_message import (  # noqa: E402
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._providers.bedrock import converse_chat_message  # noqa: E402
from inspect_ai.tool._tool_call import ToolCall, ToolCallError  # noqa: E402


def _tool_call(id: str, function: str) -> ToolCall:
    return ToolCall(id=id, function=function, arguments={})


async def test_assistant_text_preserved_alongside_tool_calls():
    message = ChatMessageAssistant(
        content="Let me check the directory, then create the temp dir.",
        tool_calls=[_tool_call("t1", "pwd"), _tool_call("t2", "ls")],
    )

    result = await converse_chat_message(message)

    # A single assistant message carrying text + both toolUse blocks.
    assert result is not None
    assert len(result) == 1
    blocks = result[0].content
    texts = [b.text for b in blocks if b.text is not None]
    tool_uses = [b.toolUse for b in blocks if b.toolUse is not None]
    assert texts == ["Let me check the directory, then create the temp dir."]
    assert [tu.name for tu in tool_uses] == ["pwd", "ls"]
    # Text must come before the tool calls.
    assert blocks[0].text is not None


async def test_assistant_reasoning_preserved_alongside_tool_calls():
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="I should list files first."),
            ContentText(text="Listing now."),
        ],
        tool_calls=[_tool_call("t1", "ls")],
    )

    # emulate_reasoning=True mirrors the Claude-on-Bedrock path.
    result = await converse_chat_message(message, emulate_reasoning=True)

    assert result is not None and len(result) == 1
    blocks = result[0].content
    assert any(b.text and "I should list files first." in b.text for b in blocks)
    assert any(b.text == "Listing now." for b in blocks)
    assert [b.toolUse.name for b in blocks if b.toolUse is not None] == ["ls"]


async def test_assistant_tool_calls_without_content_unchanged():
    message = ChatMessageAssistant(
        content="",
        tool_calls=[_tool_call("t1", "pwd")],
    )

    result = await converse_chat_message(message)

    assert result is not None and len(result) == 1
    blocks = result[0].content
    # No spurious NO_CONTENT text block; just the tool call.
    assert [b.toolUse.name for b in blocks if b.toolUse is not None] == ["pwd"]
    assert all(b.text is None for b in blocks)


async def test_failed_tool_call_error_sent_to_bedrock() -> None:
    @tool
    def lookup() -> Tool:
        async def execute(path: str) -> str:
            """Look up a file.

            Args:
                path: File path.
            """
            raise FileNotFoundError(f"{path}: does not exist")

        return execute

    call = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="c1", function="lookup", arguments={"path": "/tmp/missing"})
        ],
    )
    message = (await execute_tools([call], [lookup()])).messages[0]
    assert isinstance(message, ChatMessageTool)
    assert message.content == ""
    assert message.error == ToolCallError(
        type="file_not_found", message="/tmp/missing: does not exist"
    )

    result = await converse_chat_message(message)

    assert result is not None and len(result) == 1
    assert result[0].role == "user"
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.model_dump(exclude_none=True) == {
        "toolUseId": "c1",
        "content": [{"text": "/tmp/missing: does not exist"}],
        "status": "error",
    }


@pytest.mark.parametrize(
    ("error_message", "content", "expected"),
    [
        ("Tool timed out", "Partial output", "Tool timed out"),
        ("Tool timed out", [ContentText(text="Partial output")], "Tool timed out"),
        ("", "Partial output", "Partial output"),
        ("", [ContentText(text="Partial output")], "Partial output"),
        ("", "", "error"),
        ("", [], "error"),
    ],
)
async def test_tool_error_content(
    error_message: str, content: str | list[Content], expected: str
) -> None:
    message = ChatMessageTool(
        content=content,
        tool_call_id="c1",
        function="lookup",
        error=ToolCallError(type="timeout", message=error_message),
    )

    result = await converse_chat_message(message)

    assert result is not None and len(result) == 1
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.status == "error"
    assert [block.text for block in tool_result.content] == [expected]


@pytest.mark.parametrize("content", ["Tool output", [ContentText(text="Tool output")]])
async def test_successful_tool_result_content(content: str | list[Content]) -> None:
    message = ChatMessageTool(content=content, tool_call_id="c1", function="lookup")

    result = await converse_chat_message(message)

    assert result is not None and len(result) == 1
    tool_result = result[0].content[0].toolResult
    assert tool_result is not None
    assert tool_result.status == "success"
    assert [block.text for block in tool_result.content] == ["Tool output"]
