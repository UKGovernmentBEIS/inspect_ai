"""Tests for OpenAI model API conversion functions."""

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_function_tool_call import Function
from openai.types.completion_usage import CompletionUsage, PromptTokensDetails
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
from inspect_ai.model._openai_responses import (
    reasoning_from_responses_reasoning,
    responses_reasoning_from_reasoning,
)


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


async def test_model_output_from_openai_cache_token_normalization() -> None:
    """Test that input_tokens excludes cached tokens for OpenAI Chat Completions."""
    completion = ChatCompletion(
        id="chatcmpl-cache",
        model="gpt-4o-mini",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="Hello!",
                ),
                finish_reason="stop",
                logprobs=None,
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=1000,
            completion_tokens=50,
            total_tokens=1050,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=600),
        ),
    )

    result = await model_output_from_openai(completion)

    assert result.usage is not None
    # input_tokens should exclude cached tokens: 1000 - 600 = 400
    assert result.usage.input_tokens == 400
    assert result.usage.input_tokens_cache_read == 600
    assert result.usage.output_tokens == 50
    assert result.usage.total_tokens == 1050


async def test_model_output_from_openai_no_cache_tokens() -> None:
    """Test that input_tokens is unchanged when there are no cached tokens."""
    completion = ChatCompletion(
        id="chatcmpl-nocache",
        model="gpt-4o-mini",
        object="chat.completion",
        created=1234567890,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="Hello!",
                ),
                finish_reason="stop",
                logprobs=None,
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=500,
            completion_tokens=50,
            total_tokens=550,
        ),
    )

    result = await model_output_from_openai(completion)

    assert result.usage is not None
    # No cache, input_tokens should equal prompt_tokens
    assert result.usage.input_tokens == 500
    assert result.usage.input_tokens_cache_read is None
    assert result.usage.total_tokens == 550


async def test_model_output_from_openai_responses_cache_normalization() -> None:
    """Test that input_tokens excludes cached tokens for OpenAI Responses API."""
    response = Response(
        id="resp-cache",
        created_at=1234567890,
        model="gpt-4o-mini",
        object="response",
        output=[
            ResponseOutputMessage(
                id="msg-1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text="Hello!",
                        annotations=[],
                    )
                ],
            )
        ],
        tool_choice="auto",
        tools=[],
        parallel_tool_calls=False,
        usage=ResponseUsage(
            input_tokens=1000,
            output_tokens=50,
            total_tokens=1050,
            input_tokens_details=InputTokensDetails(cached_tokens=600),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    result = await model_output_from_openai_responses(response)

    assert result.usage is not None
    # input_tokens should exclude cached tokens: 1000 - 600 = 400
    assert result.usage.input_tokens == 400
    assert result.usage.input_tokens_cache_read == 600
    assert result.usage.output_tokens == 50
    assert result.usage.total_tokens == 1050


# --- Tests for reasoning_from_responses_reasoning (ingest) ---


def test_reasoning_from_responses_both_content_and_encrypted() -> None:
    """When both content and encrypted_content exist, prefer readable content."""
    item = ResponseReasoningItem.model_construct(
        id="rs_123",
        type="reasoning",
        content=[{"type": "reasoning_text", "text": "readable thinking"}],
        encrypted_content="ENCRYPTED_BLOB",
        summary=[],
    )
    result = reasoning_from_responses_reasoning(item)
    assert result.reasoning == "readable thinking"
    assert result.redacted is False
    assert result.internal == {"encrypted_content": "ENCRYPTED_BLOB"}
    assert result.signature == "rs_123"


def test_reasoning_from_responses_only_encrypted() -> None:
    """When only encrypted_content exists, store it in reasoning as redacted."""
    item = ResponseReasoningItem.model_construct(
        id="rs_456",
        type="reasoning",
        content=None,
        encrypted_content="ENCRYPTED_ONLY",
        summary=[],
    )
    result = reasoning_from_responses_reasoning(item)
    assert result.reasoning == "ENCRYPTED_ONLY"
    assert result.redacted is True
    assert result.internal is None


def test_reasoning_from_responses_only_content() -> None:
    """When only content exists (no encryption), store readable text normally."""
    item = ResponseReasoningItem.model_construct(
        id="rs_789",
        type="reasoning",
        content=[{"type": "reasoning_text", "text": "just thinking"}],
        encrypted_content=None,
        summary=[{"type": "summary_text", "text": "a summary"}],
    )
    result = reasoning_from_responses_reasoning(item)
    assert result.reasoning == "just thinking"
    assert result.redacted is False
    assert result.internal is None
    assert result.summary == "a summary"


# --- Tests for responses_reasoning_from_reasoning (replay) ---


def test_replay_new_format_with_encrypted_in_internal() -> None:
    """New format: readable in reasoning, encrypted in internal."""
    content = ContentReasoning(
        reasoning="readable thinking",
        redacted=False,
        internal={"encrypted_content": "ENCRYPTED_BLOB"},
        signature="rs_123",
    )
    result = responses_reasoning_from_reasoning(content)
    result_content = list(result["content"])
    assert result["encrypted_content"] == "ENCRYPTED_BLOB"
    assert len(result_content) == 1
    assert result_content[0]["text"] == "readable thinking"
    assert result["id"] == "rs_123"


def test_replay_old_format_redacted() -> None:
    """Old format: encrypted in reasoning, redacted=True."""
    content = ContentReasoning(
        reasoning="ENCRYPTED_BLOB",
        redacted=True,
        signature="rs_456",
    )
    result = responses_reasoning_from_reasoning(content)
    assert result["encrypted_content"] == "ENCRYPTED_BLOB"
    assert list(result["content"]) == []
    assert result["id"] == "rs_456"


def test_replay_no_encrypted_content() -> None:
    """No encryption at all — just readable text."""
    content = ContentReasoning(
        reasoning="just thinking",
        redacted=False,
        signature="rs_789",
    )
    result = responses_reasoning_from_reasoning(content)
    result_content = list(result["content"])
    assert result["encrypted_content"] is None
    assert len(result_content) == 1
    assert result_content[0]["text"] == "just thinking"


# --- Round-trip test ---


def test_reasoning_round_trip_preserves_encrypted() -> None:
    """Ingest then replay preserves both readable text and encrypted content."""
    item = ResponseReasoningItem.model_construct(
        id="rs_rt",
        type="reasoning",
        content=[{"type": "reasoning_text", "text": "readable"}],
        encrypted_content="ENCRYPTED",
        summary=[],
    )
    content = reasoning_from_responses_reasoning(item)
    replayed = responses_reasoning_from_reasoning(content)
    replayed_content = list(replayed["content"])
    assert replayed["encrypted_content"] == "ENCRYPTED"
    assert len(replayed_content) == 1
    assert replayed_content[0]["text"] == "readable"
    assert replayed["id"] == "rs_rt"
