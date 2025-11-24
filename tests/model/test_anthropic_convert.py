"""Tests for Anthropic model API conversion functions."""

import pytest
from anthropic.types import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    model_output_from_anthropic,
)
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ModelOutput


@pytest.mark.asyncio
async def test_model_output_from_anthropic_basic() -> None:
    """Test basic Message conversion to ModelOutput."""
    message = Message(
        id="msg_123",
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        content=[TextBlock(type="text", text="Hello! How can I help you today?")],
        type="message",
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=10,
            output_tokens=20,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    assert result.model == "claude-3-5-sonnet-20241022"
    assert len(result.choices) == 1
    assert isinstance(result.choices[0].message, ChatMessageAssistant)
    assert result.choices[0].stop_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20
    assert result.usage.total_tokens == 30

    # Check content
    message_obj = result.choices[0].message
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 1
    assert isinstance(message_obj.content[0], ContentText)
    assert message_obj.content[0].text == "Hello! How can I help you today?"


@pytest.mark.asyncio
async def test_model_output_from_anthropic_with_tool_use() -> None:
    """Test Message with tool use conversion."""
    message = Message(
        id="msg_456",
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        content=[
            TextBlock(type="text", text="Let me check the weather for you."),
            ToolUseBlock(
                type="tool_use",
                id="toolu_123",
                name="get_weather",
                input={"location": "San Francisco"},
            ),
        ],
        type="message",
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(
            input_tokens=15,
            output_tokens=25,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "tool_calls"

    message_obj = result.choices[0].message
    assert isinstance(message_obj, ChatMessageAssistant)
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 1

    # Check text content
    assert isinstance(message_obj.content[0], ContentText)
    assert message_obj.content[0].text == "Let me check the weather for you."

    # Check tool calls are stored separately
    assert message_obj.tool_calls is not None
    assert len(message_obj.tool_calls) == 1
    assert message_obj.tool_calls[0].id == "toolu_123"
    assert message_obj.tool_calls[0].function == "get_weather"
    assert message_obj.tool_calls[0].arguments == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_model_output_from_anthropic_with_thinking() -> None:
    """Test Message with thinking blocks (reasoning) conversion."""
    message = Message(
        id="msg_789",
        model="claude-3-7-sonnet-20250219",
        role="assistant",
        content=[
            ThinkingBlock(
                type="thinking",
                thinking="Let me carefully consider this problem...",
                signature="thinking-sig-1",
            ),
            TextBlock(type="text", text="The answer is 42."),
        ],
        type="message",
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=50,
            output_tokens=150,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    message_obj = result.choices[0].message
    assert isinstance(message_obj, ChatMessageAssistant)
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 2

    # Check reasoning content
    assert isinstance(message_obj.content[0], ContentReasoning)
    assert "carefully consider" in message_obj.content[0].reasoning

    # Check text content
    assert isinstance(message_obj.content[1], ContentText)
    assert message_obj.content[1].text == "The answer is 42."


@pytest.mark.asyncio
async def test_model_output_from_anthropic_dict_input() -> None:
    """Test conversion from dict representation of Message."""
    message_dict = {
        "id": "msg_dict",
        "model": "claude-3-5-sonnet-20241022",
        "role": "assistant",
        "content": [{"type": "text", "text": "Dict test response"}],
        "type": "message",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 5,
            "output_tokens": 10,
        },
    }

    result = await model_output_from_anthropic(message_dict)

    assert isinstance(result, ModelOutput)
    assert result.model == "claude-3-5-sonnet-20241022"
    message_obj = result.choices[0].message
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 1
    assert isinstance(message_obj.content[0], ContentText)
    assert message_obj.content[0].text == "Dict test response"


@pytest.mark.asyncio
async def test_model_output_from_anthropic_max_tokens_stop_reason() -> None:
    """Test Message with max_tokens stop reason."""
    message = Message(
        id="msg_max",
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        content=[
            TextBlock(type="text", text="This response was cut off due to token limit")
        ],
        type="message",
        stop_reason="max_tokens",
        stop_sequence=None,
        usage=Usage(
            input_tokens=10,
            output_tokens=100,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "max_tokens"


@pytest.mark.asyncio
async def test_model_output_from_anthropic_stop_sequence() -> None:
    """Test Message with stop_sequence stop reason."""
    message = Message(
        id="msg_stop_seq",
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        content=[TextBlock(type="text", text="Response stopped early")],
        type="message",
        stop_reason="stop_sequence",
        stop_sequence="STOP",
        usage=Usage(
            input_tokens=10,
            output_tokens=15,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "stop"


@pytest.mark.asyncio
async def test_model_output_from_anthropic_multiple_thinking_blocks() -> None:
    """Test Message with multiple thinking blocks."""
    message = Message(
        id="msg_multi_think",
        model="claude-3-7-sonnet-20250219",
        role="assistant",
        content=[
            ThinkingBlock(
                type="thinking",
                thinking="First reasoning step...",
                signature="thinking-sig-1",
            ),
            ThinkingBlock(
                type="thinking",
                thinking="Second reasoning step...",
                signature="thinking-sig-2",
            ),
            TextBlock(type="text", text="Final answer based on reasoning."),
        ],
        type="message",
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=30,
            output_tokens=80,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    message_obj = result.choices[0].message
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 3

    # Check both reasoning blocks
    assert isinstance(message_obj.content[0], ContentReasoning)
    assert "First reasoning step" in message_obj.content[0].reasoning

    assert isinstance(message_obj.content[1], ContentReasoning)
    assert "Second reasoning step" in message_obj.content[1].reasoning

    # Check text content
    assert isinstance(message_obj.content[2], ContentText)
    assert message_obj.content[2].text == "Final answer based on reasoning."


@pytest.mark.asyncio
async def test_model_output_from_anthropic_mixed_content() -> None:
    """Test Message with mixed content types."""
    message = Message(
        id="msg_mixed",
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        content=[
            TextBlock(type="text", text="I'll help with that."),
            ToolUseBlock(
                type="tool_use",
                id="toolu_456",
                name="search",
                input={"query": "test"},
            ),
            TextBlock(type="text", text="Based on the results..."),
        ],
        type="message",
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(
            input_tokens=20,
            output_tokens=40,
        ),
    )

    result = await model_output_from_anthropic(message)

    assert isinstance(result, ModelOutput)
    message_obj = result.choices[0].message
    assert isinstance(message_obj.content, list)
    assert len(message_obj.content) == 2

    # Verify content types in order (tool use is moved to tool_calls)
    assert isinstance(message_obj.content[0], ContentText)
    assert message_obj.content[0].text == "I'll help with that."
    assert isinstance(message_obj.content[1], ContentText)
    assert message_obj.content[1].text == "Based on the results..."

    # Verify tool call is stored separately
    assert message_obj.tool_calls is not None
    assert len(message_obj.tool_calls) == 1
    assert message_obj.tool_calls[0].function == "search"
