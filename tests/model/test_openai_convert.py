"""Tests for OpenAI model API conversion functions."""

import pytest
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_function_tool_call import Function
from openai.types.completion_usage import CompletionUsage
from openai.types.responses import (
    Response,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    model_output_from_openai,
    model_output_from_openai_responses,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
)
from inspect_ai.model._model_output import ModelOutput


@pytest.mark.asyncio
async def test_model_output_from_openai_basic() -> None:
    """Test basic ChatCompletion conversion to ModelOutput."""
    completion = ChatCompletion(
        id="chatcmpl-123",
        model="gpt-4",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="Hello! How can I help you today?",
                ),
                finish_reason="stop",
                logprobs=None,
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
    )

    result = await model_output_from_openai(completion)

    assert isinstance(result, ModelOutput)
    assert result.model == "gpt-4"
    assert len(result.choices) == 1
    assert isinstance(result.choices[0].message, ChatMessageAssistant)
    assert result.choices[0].message.content == "Hello! How can I help you today?"
    assert result.choices[0].stop_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20
    assert result.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_model_output_from_openai_with_tool_calls() -> None:
    """Test ChatCompletion with tool calls conversion."""
    from openai.types.chat.chat_completion_message_function_tool_call import (
        ChatCompletionMessageFunctionToolCall,
    )

    completion = ChatCompletion(
        id="chatcmpl-456",
        model="gpt-4",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageFunctionToolCall(
                            id="call_123",
                            type="function",
                            function=Function(
                                name="get_weather",
                                arguments='{"location": "San Francisco"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
                logprobs=None,
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=15,
            completion_tokens=25,
            total_tokens=40,
        ),
    )

    result = await model_output_from_openai(completion)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "tool_calls"
    message = result.choices[0].message
    assert isinstance(message, ChatMessageAssistant)
    # Tool calls are stored in the message's tool_calls attribute
    assert hasattr(message, "tool_calls")
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].function == "get_weather"


@pytest.mark.asyncio
async def test_model_output_from_openai_dict_input() -> None:
    """Test conversion from dict representation of ChatCompletion."""
    completion_dict = {
        "id": "chatcmpl-789",
        "model": "gpt-3.5-turbo",
        "object": "chat.completion",
        "created": 1234567890,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 10,
            "total_tokens": 15,
        },
    }

    result = await model_output_from_openai(completion_dict)

    assert isinstance(result, ModelOutput)
    assert result.model == "gpt-3.5-turbo"
    assert result.choices[0].message.content == "Test response"


@pytest.mark.asyncio
async def test_model_output_from_openai_responses_basic() -> None:
    """Test basic Response conversion to ModelOutput."""
    response = Response.model_construct(
        id="resp-123",
        model="gpt-4o",
        object="response",
        created_at=1234567890,
        output=[
            ResponseOutputMessage(
                id="msg-123",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text="This is a response.",
                        annotations=[],
                    )
                ],
            )
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
        incomplete_details=None,
        error=None,
    )

    result = await model_output_from_openai_responses(response)

    assert isinstance(result, ModelOutput)
    assert result.model == "gpt-4o"
    assert len(result.choices) == 1
    assert isinstance(result.choices[0].message, ChatMessageAssistant)
    assert result.choices[0].stop_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 200
    assert result.usage.total_tokens == 300


@pytest.mark.asyncio
async def test_model_output_from_openai_responses_with_reasoning() -> None:
    """Test Response with reasoning blocks conversion."""
    response = Response.model_construct(
        id="resp-456",
        model="o3-mini",
        object="response",
        created_at=1234567890,
        output=[
            ResponseReasoningItem(
                id="reasoning-1",
                type="reasoning",
                summary=[],
            ),
            ResponseOutputMessage(
                id="msg-456",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text="The answer is 42.",
                        annotations=[],
                    )
                ],
            ),
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        usage=ResponseUsage(
            input_tokens=50,
            output_tokens=150,
            total_tokens=200,
            input_tokens_details=InputTokensDetails(cached_tokens=10),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=50),
        ),
        incomplete_details=None,
        error=None,
    )

    result = await model_output_from_openai_responses(response)

    assert isinstance(result, ModelOutput)
    message = result.choices[0].message
    assert isinstance(message, ChatMessageAssistant)
    assert isinstance(message.content, list)

    # Should have both reasoning and text content
    has_reasoning = any(isinstance(c, ContentReasoning) for c in message.content)
    has_text = any(isinstance(c, ContentText) for c in message.content)
    assert has_reasoning
    assert has_text

    # Check usage includes reasoning tokens
    assert result.usage is not None
    assert result.usage.reasoning_tokens == 50
    assert result.usage.input_tokens_cache_read == 10


@pytest.mark.asyncio
async def test_model_output_from_openai_responses_dict_input() -> None:
    """Test conversion from dict representation of Response."""
    response_dict = {
        "id": "resp-789",
        "model": "gpt-4o",
        "object": "response",
        "created_at": 1234567890,
        "output": [
            {
                "id": "msg-789",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Dict test response",
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 30,
            "total_tokens": 50,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }

    result = await model_output_from_openai_responses(response_dict)

    assert isinstance(result, ModelOutput)
    assert result.model == "gpt-4o"
    assert result.usage is not None
    assert result.usage.input_tokens == 20


@pytest.mark.asyncio
async def test_model_output_from_openai_responses_with_refusal() -> None:
    """Test Response with refusal content."""
    response = Response.model_construct(
        id="resp-refusal",
        model="gpt-4o",
        object="response",
        created_at=1234567890,
        output=[
            ResponseOutputMessage(
                id="msg-refusal",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputRefusal(
                        type="refusal",
                        refusal="I cannot help with that request.",
                    )
                ],
            )
        ],
        usage=ResponseUsage(
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
        incomplete_details=None,
        error=None,
    )

    result = await model_output_from_openai_responses(response)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "stop"


@pytest.mark.asyncio
async def test_model_output_from_openai_multiple_choices() -> None:
    """Test ChatCompletion with multiple choices (n > 1)."""
    completion = ChatCompletion(
        id="chatcmpl-multi",
        model="gpt-4",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="First response",
                ),
                finish_reason="stop",
                logprobs=None,
            ),
            Choice(
                index=1,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="Second response",
                ),
                finish_reason="stop",
                logprobs=None,
            ),
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
    )

    result = await model_output_from_openai(completion)

    assert isinstance(result, ModelOutput)
    assert len(result.choices) == 2
    assert result.choices[0].message.content == "First response"
    assert result.choices[1].message.content == "Second response"


@pytest.mark.asyncio
async def test_model_output_from_openai_length_stop_reason() -> None:
    """Test ChatCompletion with length finish reason."""
    completion = ChatCompletion(
        id="chatcmpl-length",
        model="gpt-3.5-turbo",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="This response was cut off due to",
                ),
                finish_reason="length",
                logprobs=None,
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=100,
            total_tokens=110,
        ),
    )

    result = await model_output_from_openai(completion)

    assert isinstance(result, ModelOutput)
    assert result.choices[0].stop_reason == "max_tokens"
