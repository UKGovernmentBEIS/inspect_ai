"""Tests for Google GenAI model API conversion functions."""

import pytest
from google.genai.types import (
    Candidate,
    Content,
    ContentDict,
    FinishReason,
    FunctionCall,
    FunctionResponse,
    GenerateContentResponse,
    GenerateContentResponseUsageMetadata,
    Part,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    messages_from_google,
    model_output_from_google,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model_output import ModelOutput


@pytest.mark.asyncio
async def test_messages_from_google_basic() -> None:
    """Test basic Content list conversion to ChatMessage list."""
    contents = [
        Content(
            role="user",
            parts=[Part(text="Hello, how are you?")],
        ),
        Content(
            role="model",
            parts=[Part(text="I'm doing well, thank you!")],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 2
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[0].content, list)
    assert len(result[0].content) == 1
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "Hello, how are you?"
    assert isinstance(result[1], ChatMessageAssistant)
    assert isinstance(result[1].content, list)
    assert len(result[1].content) == 1
    assert isinstance(result[1].content[0], ContentText)
    assert result[1].content[0].text == "I'm doing well, thank you!"


@pytest.mark.asyncio
async def test_messages_from_google_with_system_instruction() -> None:
    """Test conversion with system instruction."""
    contents = [
        Content(
            role="user",
            parts=[Part(text="What is 2+2?")],
        ),
    ]

    result = await messages_from_google(
        contents, system_instruction="You are a helpful math tutor."
    )

    assert len(result) == 2
    assert isinstance(result[0], ChatMessageSystem)
    assert result[0].content == "You are a helpful math tutor."
    assert isinstance(result[1], ChatMessageUser)


@pytest.mark.asyncio
async def test_messages_from_google_with_tool_calls() -> None:
    """Test Content with function calls conversion."""
    contents = [
        Content(
            role="model",
            parts=[
                Part(text="Let me check the weather."),
                Part(
                    function_call=FunctionCall(
                        name="get_weather",
                        args={"location": "San Francisco"},
                    )
                ),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageAssistant)
    assert isinstance(message.content, list)
    assert len(message.content) == 1
    assert isinstance(message.content[0], ContentText)
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].function == "get_weather"
    assert message.tool_calls[0].arguments == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_messages_from_google_with_tool_response() -> None:
    """Test Content with function response conversion (tool message)."""
    contents = [
        Content(
            role="user",
            parts=[
                Part(
                    function_response=FunctionResponse(
                        name="get_weather",
                        response={"content": "Sunny, 72°F"},
                    )
                ),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageTool)
    assert message.function == "get_weather"
    assert "Sunny" in message.content


@pytest.mark.asyncio
async def test_messages_from_google_with_reasoning() -> None:
    """Test Content with thought parts (reasoning) conversion."""
    contents = [
        Content(
            role="model",
            parts=[
                Part(text="Let me think about this...", thought=True),
                Part(text="The answer is 42."),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageAssistant)
    assert isinstance(message.content, list)
    assert len(message.content) == 2

    # Check reasoning content
    assert isinstance(message.content[0], ContentReasoning)
    assert message.content[0].reasoning == "Let me think about this..."
    assert message.content[0].redacted is False

    # Check text content
    assert isinstance(message.content[1], ContentText)
    assert message.content[1].text == "The answer is 42."


@pytest.mark.asyncio
async def test_messages_from_google_dict_input() -> None:
    """Test conversion from dict representation of Content."""
    contents: list[ContentDict] = [
        {
            "role": "user",
            "parts": [{"text": "Hello from dict"}],
        },
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[0].content, list)
    assert len(result[0].content) == 1
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "Hello from dict"


@pytest.mark.asyncio
async def test_model_output_from_google_basic() -> None:
    """Test basic GenerateContentResponse conversion to ModelOutput."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[Part(text="This is a test response.")],
                ),
                finish_reason=FinishReason.STOP,
                index=0,
            )
        ],
        usage_metadata=GenerateContentResponseUsageMetadata(
            prompt_token_count=10,
            candidates_token_count=20,
            total_token_count=30,
        ),
        model_version="gemini-2.0-flash-exp",
    )

    result = await model_output_from_google(response)

    assert isinstance(result, ModelOutput)
    assert result.model == "gemini-2.0-flash-exp"
    assert len(result.choices) == 1
    assert isinstance(result.choices[0].message, ChatMessageAssistant)
    assert result.choices[0].stop_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20
    assert result.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_model_output_from_google_with_tool_calls() -> None:
    """Test GenerateContentResponse with tool calls conversion."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        Part(
                            function_call=FunctionCall(
                                name="search",
                                args={"query": "AI news"},
                            )
                        )
                    ],
                ),
                finish_reason=FinishReason.STOP,
                index=0,
            )
        ],
        usage_metadata=GenerateContentResponseUsageMetadata(
            prompt_token_count=15,
            candidates_token_count=25,
            total_token_count=40,
        ),
        model_version="gemini-2.0-flash-exp",
    )

    result = await model_output_from_google(response)

    assert isinstance(result, ModelOutput)
    message = result.choices[0].message
    assert isinstance(message, ChatMessageAssistant)
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].function == "search"


@pytest.mark.asyncio
async def test_model_output_from_google_with_reasoning() -> None:
    """Test GenerateContentResponse with reasoning (thought parts) conversion."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        Part(text="Analyzing the problem...", thought=True),
                        Part(text="The solution is X."),
                    ],
                ),
                finish_reason=FinishReason.STOP,
                index=0,
            )
        ],
        usage_metadata=GenerateContentResponseUsageMetadata(
            prompt_token_count=50,
            candidates_token_count=150,
            total_token_count=200,
        ),
        model_version="gemini-2.0-flash-thinking-exp",
    )

    result = await model_output_from_google(response)

    assert isinstance(result, ModelOutput)
    message = result.choices[0].message
    assert isinstance(message, ChatMessageAssistant)
    assert isinstance(message.content, list)

    # Should have both reasoning and text content
    has_reasoning = any(isinstance(c, ContentReasoning) for c in message.content)
    has_text = any(isinstance(c, ContentText) for c in message.content)
    assert has_reasoning
    assert has_text


@pytest.mark.asyncio
async def test_model_output_from_google_dict_input() -> None:
    """Test conversion from dict representation of GenerateContentResponse."""
    response_dict = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Dict test response"}],
                },
                "finish_reason": "STOP",
                "index": 0,
            }
        ],
        "usage_metadata": {
            "prompt_token_count": 5,
            "candidates_token_count": 10,
            "total_token_count": 15,
        },
        "model_version": "gemini-2.0-flash-exp",
    }

    result = await model_output_from_google(response_dict)

    assert isinstance(result, ModelOutput)
    assert result.model == "gemini-2.0-flash-exp"
    message = result.choices[0].message
    assert isinstance(message.content, list)
    assert len(message.content) == 1
    assert isinstance(message.content[0], ContentText)


@pytest.mark.asyncio
async def test_model_output_from_google_max_tokens_stop_reason() -> None:
    """Test GenerateContentResponse with max_tokens finish reason."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[Part(text="This response was cut off")],
                ),
                finish_reason=FinishReason.MAX_TOKENS,
                index=0,
            )
        ],
        usage_metadata=GenerateContentResponseUsageMetadata(
            prompt_token_count=10,
            candidates_token_count=100,
            total_token_count=110,
        ),
        model_version="gemini-2.0-flash-exp",
    )

    result = await model_output_from_google(response)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "max_tokens"


@pytest.mark.asyncio
async def test_model_output_from_google_model_override() -> None:
    """Test model name override parameter."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[Part(text="Test")],
                ),
                finish_reason=FinishReason.STOP,
                index=0,
            )
        ],
        usage_metadata=GenerateContentResponseUsageMetadata(
            prompt_token_count=5,
            candidates_token_count=5,
            total_token_count=10,
        ),
        model_version="gemini-2.0-flash-exp",
    )

    result = await model_output_from_google(response, model="custom-model-name")

    assert isinstance(result, ModelOutput)
    assert result.model == "custom-model-name"


@pytest.mark.asyncio
async def test_messages_from_google_with_model_tag() -> None:
    """Test that model parameter is passed to assistant messages."""
    contents = [
        Content(
            role="model",
            parts=[Part(text="Response")],
        ),
    ]

    result = await messages_from_google(contents, model="gemini-2.0-flash-exp")

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageAssistant)
    assert message.model == "gemini-2.0-flash-exp"


@pytest.mark.asyncio
async def test_messages_from_google_mixed_content() -> None:
    """Test Content with mixed content types."""
    contents = [
        Content(
            role="model",
            parts=[
                Part(text="First text."),
                Part(
                    function_call=FunctionCall(
                        name="tool1",
                        args={"param": "value"},
                    )
                ),
                Part(text="Second text."),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageAssistant)
    assert isinstance(message.content, list)
    assert len(message.content) == 2

    # Verify text content in order (tool call should be in tool_calls)
    assert isinstance(message.content[0], ContentText)
    assert message.content[0].text == "First text."
    assert isinstance(message.content[1], ContentText)
    assert message.content[1].text == "Second text."

    # Verify tool call is stored separately
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].function == "tool1"


@pytest.mark.asyncio
async def test_messages_from_google_with_role_tool() -> None:
    """Test Content with role='tool' (official SDK pattern for function responses)."""
    contents = [
        Content(
            role="tool",
            parts=[
                Part(
                    function_response=FunctionResponse(
                        name="get_weather",
                        response={"content": "Sunny, 75°F"},
                    )
                ),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    assert len(result) == 1
    message = result[0]
    assert isinstance(message, ChatMessageTool)
    assert message.function == "get_weather"
    assert "Sunny" in message.content


@pytest.mark.asyncio
async def test_messages_from_google_mixed_user_content() -> None:
    """Test user Content with BOTH text and function response (mixed parts)."""
    contents = [
        Content(
            role="user",
            parts=[
                Part(text="Here's the context before calling the tool."),
                Part(
                    function_response=FunctionResponse(
                        name="search",
                        response={"results": ["result1", "result2"]},
                    )
                ),
                Part(text="And here's my follow-up question."),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    # Should produce 3 messages: user text, tool response, user text
    assert len(result) == 3

    # First message: user text before tool response
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[0].content, list)
    assert len(result[0].content) == 1
    assert isinstance(result[0].content[0], ContentText)
    assert "before calling" in result[0].content[0].text

    # Second message: tool response
    assert isinstance(result[1], ChatMessageTool)
    assert result[1].function == "search"
    assert "results" in result[1].content

    # Third message: user text after tool response
    assert isinstance(result[2], ChatMessageUser)
    assert isinstance(result[2].content, list)
    assert len(result[2].content) == 1
    assert isinstance(result[2].content[0], ContentText)
    assert "follow-up" in result[2].content[0].text


@pytest.mark.asyncio
async def test_messages_from_google_multiple_tool_responses_in_user() -> None:
    """Test user Content with multiple function responses interleaved with text."""
    contents = [
        Content(
            role="user",
            parts=[
                Part(text="First query"),
                Part(
                    function_response=FunctionResponse(
                        name="tool1",
                        response={"data": "response1"},
                    )
                ),
                Part(text="Second query"),
                Part(
                    function_response=FunctionResponse(
                        name="tool2",
                        response={"data": "response2"},
                    )
                ),
            ],
        ),
    ]

    result = await messages_from_google(contents)

    # Should produce 4 messages: user, tool, user, tool
    assert len(result) == 4
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[1], ChatMessageTool)
    assert result[1].function == "tool1"
    assert isinstance(result[2], ChatMessageUser)
    assert isinstance(result[3], ChatMessageTool)
    assert result[3].function == "tool2"
