import pytest

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai.agent._filter import content_only
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool import ToolCall


@pytest.mark.asyncio
async def test_removes_system_messages() -> None:
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="User message"),
        ChatMessageAssistant(content="Assistant response"),
    ]

    filtered = await content_only(messages)

    assert len(filtered) == 2
    assert all(not isinstance(msg, ChatMessageSystem) for msg in filtered)
    assert isinstance(filtered[0], ChatMessageUser)
    assert isinstance(filtered[1], ChatMessageAssistant)


@pytest.mark.asyncio
async def test_passes_through_user_messages() -> None:
    user_msg = ChatMessageUser(id="user-123", content="Test user message")
    messages: list[ChatMessage] = [user_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    assert filtered[0] == user_msg
    assert filtered[0].id == "user-123"
    assert filtered[0].content == "Test user message"


@pytest.mark.asyncio
async def test_converts_tool_messages_to_user() -> None:
    tool_msg = ChatMessageTool(
        id="tool-456",
        content="Tool result",
        tool_call_id="call-789",
        function="my_function",
    )
    messages: list[ChatMessage] = [tool_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    assert isinstance(filtered[0], ChatMessageUser)
    assert filtered[0].id == "tool-456"
    assert filtered[0].content == "Tool result"


@pytest.mark.asyncio
async def test_removes_reasoning_content() -> None:
    content: list[Content] = [
        ContentReasoning(reasoning="Internal thinking process"),
        ContentText(text="Visible response"),
        ContentReasoning(reasoning="More internal thoughts"),
        ContentText(text="More visible content"),
    ]
    assistant_msg = ChatMessageAssistant(content=content)
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 2  # Two text contents (no tool calls)
    assert all(not isinstance(c, ContentReasoning) for c in filtered_content)
    assert all(isinstance(c, ContentText) for c in filtered_content)
    assert isinstance(filtered_content[0], ContentText)
    assert filtered_content[0].text == "Visible response"
    assert isinstance(filtered_content[1], ContentText)
    assert filtered_content[1].text == "More visible content"


@pytest.mark.asyncio
async def test_removes_internal_metadata() -> None:
    content: list[Content] = [
        ContentText(text="Text with internal", internal={"key": "value"}),
        ContentImage(image="data:image/png;base64,abc", internal={"meta": "data"}),
    ]
    assistant_msg = ChatMessageAssistant(content=content)
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert all(c.internal is None for c in filtered_content)


@pytest.mark.asyncio
async def test_converts_tool_calls_to_text():
    tool_call = ToolCall(
        id="call-001", function="calculate", arguments={"x": 5, "y": 10}
    )
    assistant_msg = ChatMessageAssistant(
        content="Here's the calculation:", tool_calls=[tool_call]
    )
    messages = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    assert filtered[0].tool_calls is None
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 2
    assert filtered_content[0].text == "Here's the calculation:"
    assert "calculate" in filtered_content[1].text
    assert "x=5" in filtered_content[1].text or "x: 5" in filtered_content[1].text


@pytest.mark.asyncio
async def test_converts_multiple_tool_calls():
    tool_calls = [
        ToolCall(id="call-001", function="func1", arguments={"a": 1}),
        ToolCall(id="call-002", function="func2", arguments={"b": 2}),
        ToolCall(id="call-003", function="func3", arguments={"c": 3}),
    ]
    assistant_msg = ChatMessageAssistant(
        content="Multiple calls:", tool_calls=tool_calls
    )
    messages = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    assert filtered[0].tool_calls is None
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 2
    tool_text = filtered_content[1].text
    assert "func1" in tool_text
    assert "func2" in tool_text
    assert "func3" in tool_text


@pytest.mark.asyncio
async def test_converts_server_tool_use_to_text() -> None:
    content: list[Content] = [
        ContentText(text="Using web search:"),
        ContentToolUse(
            tool_type="web_search",
            id="search-001",
            name="web_search",
            arguments='{"query": "climate change"}',
            result="Found 10 results about climate change...",
            error=None,
        ),
        ContentText(text="Based on the search results..."),
    ]
    assistant_msg = ChatMessageAssistant(content=content)
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 3  # Three contents (no tool calls)
    assert isinstance(filtered_content[0], ContentText)
    assert isinstance(filtered_content[1], ContentText)  # Converted ContentToolUse
    assert isinstance(filtered_content[2], ContentText)
    assert "web_search" in filtered_content[1].text
    assert "climate change" in filtered_content[1].text
    assert "Found 10 results" in filtered_content[1].text


@pytest.mark.asyncio
async def test_handles_string_content() -> None:
    assistant_msg = ChatMessageAssistant(content="Simple string content")
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 1  # Just the content (no tool calls)
    assert isinstance(filtered_content[0], ContentText)
    assert filtered_content[0].text == "Simple string content"


@pytest.mark.asyncio
async def test_handles_empty_tool_calls() -> None:
    assistant_msg = ChatMessageAssistant(content="No tool calls", tool_calls=[])
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    assert isinstance(filtered[0], ChatMessageAssistant)
    assert filtered[0].tool_calls is None
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 1  # Just the content (empty tool calls not added)
    assert isinstance(filtered_content[0], ContentText)
    assert filtered_content[0].text == "No tool calls"


@pytest.mark.asyncio
async def test_complex_message_sequence() -> None:
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System instructions"),
        ChatMessageUser(content="What's the weather?"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="I need to check the weather"),
                ContentText(text="Let me check the weather for you."),
            ],
            tool_calls=[
                ToolCall(
                    id="weather-001",
                    function="get_weather",
                    arguments={"location": "New York"},
                )
            ],
        ),
        ChatMessageTool(
            content="Temperature: 72°F, Sunny",
            tool_call_id="weather-001",
            function="get_weather",
        ),
        ChatMessageAssistant(
            content=[
                ContentText(
                    text="The weather in New York is currently 72°F and sunny."
                ),
                ContentToolUse(
                    tool_type="web_search",
                    id="search-002",
                    name="web_search",
                    arguments='{"query": "NY weather forecast"}',
                    result="7-day forecast shows continued sunshine...",
                    error=None,
                ),
            ]
        ),
    ]

    filtered = await content_only(messages)

    assert len(filtered) == 4

    assert isinstance(filtered[0], ChatMessageUser)
    assert filtered[0].content == "What's the weather?"

    assert isinstance(filtered[1], ChatMessageAssistant)
    assert filtered[1].tool_calls is None
    content1 = filtered[1].content
    assert isinstance(content1, list)
    assert len(content1) == 2
    assert isinstance(content1[0], ContentText)
    assert "Let me check the weather for you." in content1[0].text
    assert isinstance(content1[1], ContentText)
    assert "get_weather" in content1[1].text

    assert isinstance(filtered[2], ChatMessageUser)
    assert filtered[2].content == "Temperature: 72°F, Sunny"

    assert isinstance(filtered[3], ChatMessageAssistant)
    content3 = filtered[3].content
    assert isinstance(content3, list)
    assert len(content3) == 2  # Two contents (no tool calls)
    assert isinstance(content3[0], ContentText)
    assert "72°F and sunny" in content3[0].text
    assert isinstance(content3[1], ContentText)
    assert "web_search" in content3[1].text
    assert "7-day forecast" in content3[1].text


@pytest.mark.asyncio
async def test_preserves_message_ids() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="user-001", content="Question"),
        ChatMessageAssistant(id="assistant-002", content="Answer"),
        ChatMessageTool(id="tool-003", content="Result", tool_call_id="call-004"),
    ]

    filtered = await content_only(messages)

    assert len(filtered) == 3
    assert filtered[0].id == "user-001"
    assert filtered[1].id == "assistant-002"
    assert filtered[2].id == "tool-003"


@pytest.mark.asyncio
async def test_handles_tool_use_with_error() -> None:
    content: list[Content] = [
        ContentToolUse(
            tool_type="mcp_call",
            id="mcp-001",
            name="database_query",
            context="SQL Server",
            arguments='{"query": "SELECT * FROM users"}',
            result="",
            error="Connection timeout",
        ),
    ]
    assistant_msg = ChatMessageAssistant(content=content)
    messages: list[ChatMessage] = [assistant_msg]

    filtered = await content_only(messages)

    assert len(filtered) == 1
    filtered_content = filtered[0].content
    assert isinstance(filtered_content, list)
    assert len(filtered_content) == 1  # Just ContentToolUse converted (no tool calls)
    assert isinstance(filtered_content[0], ContentText)
    assert "database_query" in filtered_content[0].text
    assert "SELECT * FROM users" in filtered_content[0].text
