import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import anyio
import pytest
from google.genai import Client
from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import (
    Blob,
    BlockedReason,
    Candidate,
    Content,
    File,
    FileState,
    FinishReason,
    FunctionCall,
    FunctionCallingConfigMode,
    FunctionResponse,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponsePromptFeedback,
    GenerateContentResponseUsageMetadata,
    GroundingChunk,
    GroundingChunkWeb,
    GroundingMetadata,
    GroundingSupport,
    HttpOptions,
    JobState,
    Part,
    Segment,
    ToolResponse,
    ToolType,
)
from google.genai.types import ToolCall as GeminiToolCall
from openai.types.chat import ChatCompletionAssistantMessageParam
from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.kvstore import KVStore
from inspect_ai.agent._bridge.google_api_impl import (
    gemini_response_from_output,
    messages_from_google_contents,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent, model_event_progress
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ModelOutput,
    messages_from_google,
)
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import BatchConfig, GenerateConfig
from inspect_ai.model._model import ModelAPI, RetryDecision
from inspect_ai.model._openai import messages_from_openai, openai_chat_choices
from inspect_ai.model._providers import google as google_provider
from inspect_ai.model._providers._google_citations import (
    distribute_citations_to_text_parts,
)
from inspect_ai.model._providers.google import (
    GoogleGenAIAPI,
    _malformed_function_message,
    _malformed_function_retry,
    _report_stream_part_delta,
    as_chat_messages,
    chat_content_to_part,
    completion_choice_from_candidate,
    content,
)
from inspect_ai.model._providers.util import OAUTH_PLACEHOLDER_API_KEY
from inspect_ai.model._providers.util.hooks import HttpHooks
from inspect_ai.model._stream import (
    ModelStreamObserver,
    StreamEvent,
    StreamReasoningEvent,
    StreamRetryEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import use_tools
from inspect_ai.tool import (
    ToolCall,
    ToolCallError,
    ToolInfo,
    ToolParam,
    ToolParams,
    tool,
)


@skip_if_no_google
def test_google_safety_settings():
    safety_settings = dict(
        dangerous_content="medium_and_above",
        hate_speech="low_and_above",
    )

    # run with safety settings
    eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
            scorer=includes(),
        ),
        model="google/gemini-2.5-flash",
        model_args=dict(safety_settings=safety_settings),
    )


@skip_if_no_google
def test_google_block_reason():
    safety_settings = dict(harassment="low")
    eval(
        Task(
            # TODO: we can't seem to get a content filter to trigger!
            dataset=[Sample(input="you are a shameful model")],
        ),
        model="google/gemini-3.1-flash-lite",
        model_args=dict(safety_settings=safety_settings),
    )[0]
    # TODO: comment in once we have an input that triggers the filter
    # assert log.samples
    # assert log.samples[0].output.stop_reason == "content_filter"


def test_completion_choice_malformed_function_call():
    # Copied from the ``Candidate`` object actually returned by the Google API
    candidate = Candidate(
        content=Content(parts=None, role=None),
        finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
        citation_metadata=None,
        finish_message=None,
        token_count=None,
        avg_logprobs=None,
        grounding_metadata=None,
        index=None,
        logprobs_result=None,
        safety_ratings=None,
    )

    choice = completion_choice_from_candidate("", candidate)

    # Verify the conversion
    assert "I seem to have had trouble calling a function" in str(
        choice.message.content
    )
    assert choice.stop_reason == "unknown"  # MALFORMED_FUNCTION_CALL maps to "unknown"
    assert (
        choice.message.tool_calls is None
    )  # No tool calls for malformed function calls


def test_completion_choice_multiple_function_calls():
    """Test that multiple tool calls to same function get unique IDs"""
    # Create candidate with multiple calls to same function
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(
                    function_call=FunctionCall(name="calculator", args={"expr": "2+2"})
                ),
                Part(
                    function_call=FunctionCall(name="calculator", args={"expr": "3+3"})
                ),
                Part(
                    function_call=FunctionCall(name="calculator", args={"expr": "4+4"})
                ),
            ],
        ),
        finish_reason=FinishReason.STOP,
        citation_metadata=None,
        finish_message=None,
        token_count=None,
        avg_logprobs=None,
        grounding_metadata=None,
        index=None,
        logprobs_result=None,
        safety_ratings=None,
    )

    choice = completion_choice_from_candidate("test-model", candidate)

    # Verify all IDs are unique
    tool_calls = choice.message.tool_calls
    assert tool_calls is not None
    assert len(tool_calls) == 3

    ids = [call.id for call in tool_calls]
    assert len(set(ids)) == 3, "All tool call IDs should be unique"

    # Verify IDs contain function name
    for call in tool_calls:
        assert call.id.startswith("calculator_"), (
            f"ID should start with function name: {call.id}"
        )


def test_completion_choice_drops_safety_decision():
    """A safety_decision is not replayed, so its result needs no acknowledgement."""
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(
                    function_call=FunctionCall(
                        name="purchase",
                        args={
                            "item": "espresso machine",
                            "safety_decision": {
                                "decision": "require_confirmation",
                                "explanation": "A purchase.",
                            },
                        },
                    )
                ),
            ],
        ),
        finish_reason=FinishReason.STOP,
    )

    choice = completion_choice_from_candidate("test-model", candidate)

    assert choice.message.tool_calls is not None
    assert choice.message.tool_calls[0].arguments == {"item": "espresso machine"}


async def test_tool_result_sent_as_output() -> None:
    message = ChatMessageTool(
        content="2", tool_call_id="addition_1", function="addition"
    )

    google_content = await content(MagicMock(), message)

    assert google_content.parts is not None
    response = google_content.parts[0].function_response
    assert response is not None
    assert response.name == "addition"
    assert response.response == {"output": "2"}


async def test_tool_error_sent_as_error() -> None:
    message = ChatMessageTool(
        content="",
        tool_call_id="addition_1",
        function="addition",
        error=ToolCallError("parsing", "x must be an integer"),
    )

    google_content = await content(MagicMock(), message)

    assert google_content.parts is not None
    response = google_content.parts[0].function_response
    assert response is not None
    assert response.response == {"error": "x must be an integer"}


async def test_computer_tool_result_keeps_computer_use_shape() -> None:
    message = ChatMessageTool(
        content="clicked", tool_call_id="click_at_abc", function="computer"
    )

    google_content = await content(MagicMock(), message)

    assert google_content.parts is not None
    response = google_content.parts[0].function_response
    assert response is not None
    assert response.name == "click_at"
    assert response.response == {
        "content": "clicked",
        "safety_acknowledgement": "true",
        "url": "",
    }


SAFETY_DECISION = {"decision": "require_confirmation", "explanation": "A purchase."}


def _function_responses(contents: list[Content]) -> list[dict[str, Any] | None]:
    return [
        part.function_response.response
        for c in contents
        for part in c.parts or []
        if part.function_response is not None
    ]


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"output": "Order placed.", "safety_acknowledgement": "true"}, "output"),
        ({"error": "Card declined.", "safety_acknowledgement": "true"}, "error"),
    ],
)
async def test_imported_safety_decision_result_is_acknowledged(
    response: dict[str, Any], expected: str
) -> None:
    messages = await messages_from_google(
        [
            Content(role="user", parts=[Part(text="Buy the espresso machine.")]),
            Content(
                role="model",
                parts=[
                    Part(
                        function_call=FunctionCall(
                            name="purchase",
                            args={
                                "item": "machine",
                                "safety_decision": SAFETY_DECISION,
                            },
                        )
                    )
                ],
            ),
            Content(
                role="user",
                parts=[
                    Part(
                        function_response=FunctionResponse(
                            name="purchase", response=response
                        )
                    )
                ],
            ),
        ]
    )

    contents = await as_chat_messages(MagicMock(), messages)

    assert _function_responses(contents) == [
        {expected: response[expected], "safety_acknowledgement": "true"}
    ]


async def test_bridged_safety_decision_result_is_acknowledged() -> None:
    messages = messages_from_google_contents(
        [
            {"role": "user", "parts": [{"text": "Buy the espresso machine."}]},
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "purchase",
                            "args": {
                                "item": "machine",
                                "safety_decision": SAFETY_DECISION,
                            },
                        }
                    }
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "purchase",
                            "response": {"output": "Order placed."},
                        }
                    }
                ],
            },
        ],
        None,
    )

    contents = await as_chat_messages(MagicMock(), messages)

    responses = _function_responses(contents)
    assert len(responses) == 1
    assert responses[0] is not None
    assert responses[0]["safety_acknowledgement"] == "true"


async def test_result_without_safety_decision_is_not_acknowledged() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(content="What is 1 + 1?"),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id="addition_1", function="addition", arguments={"x": 1})
            ],
        ),
        ChatMessageTool(content="2", tool_call_id="addition_1", function="addition"),
    ]

    contents = await as_chat_messages(MagicMock(), messages)

    assert _function_responses(contents) == [{"output": "2"}]


async def test_imported_result_matches_call_of_its_own_turn() -> None:
    """An earlier unanswered call to the same function does not take the result."""
    messages = await messages_from_google(
        [
            Content(role="user", parts=[Part(text="Buy the espresso machine.")]),
            # a call whose result was cut from the history
            Content(
                role="model",
                parts=[
                    Part(
                        function_call=FunctionCall(
                            name="purchase", args={"item": "grinder"}
                        )
                    )
                ],
            ),
            Content(role="user", parts=[Part(text="Buy the machine instead.")]),
            Content(
                role="model",
                parts=[
                    Part(
                        function_call=FunctionCall(
                            name="purchase",
                            args={
                                "item": "machine",
                                "safety_decision": SAFETY_DECISION,
                            },
                        )
                    )
                ],
            ),
            Content(
                role="user",
                parts=[
                    Part(
                        function_response=FunctionResponse(
                            name="purchase", response={"output": "Order placed."}
                        )
                    )
                ],
            ),
        ]
    )

    contents = await as_chat_messages(MagicMock(), messages)

    assert _function_responses(contents) == [
        {"output": "Order placed.", "safety_acknowledgement": "true"}
    ]


async def test_count_tokens_acknowledges_safety_decision() -> None:
    mock_client = _create_mock_google_count_tokens_client()
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Buy the espresso machine."),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id="purchase_1",
                    function="purchase",
                    arguments={"item": "machine", "safety_decision": SAFETY_DECISION},
                )
            ],
        ),
        ChatMessageTool(
            content="Order placed.", tool_call_id="purchase_1", function="purchase"
        ),
    ]

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-3-flash-preview", base_url=None, api_key="test-key"
        )
        assert await api.count_tokens(messages) == 7

    contents = mock_client.aio.models.count_tokens.call_args.kwargs["contents"]
    assert _function_responses(contents) == [
        {"output": "Order placed.", "safety_acknowledgement": "true"}
    ]


@skip_if_no_google
async def test_replayed_safety_decision_is_acknowledged_live() -> None:
    """Gemini 3 rejects a replayed safety_decision whose result is not acknowledged."""
    from inspect_ai.model import get_model
    from inspect_ai.tool._tools._computer._computer import _COMPUTER_TOOL_PARAMETERS

    model = "gemini-3-flash-preview"
    choice = completion_choice_from_candidate(
        model,
        Candidate(
            content=Content(
                role="model",
                parts=[
                    Part(
                        function_call=FunctionCall(
                            name="purchase", args={"item": "espresso machine"}
                        ),
                        thought_signature=b"skip_thought_signature_validator",
                    )
                ],
            ),
            finish_reason=FinishReason.STOP,
        ),
    )
    assert choice.message.tool_calls is not None
    tool_call = choice.message.tool_calls[0]
    # as kept by a history imported from elsewhere
    tool_call.arguments["safety_decision"] = SAFETY_DECISION
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Buy the espresso machine with the purchase tool."),
        choice.message,
        ChatMessageTool(
            content="Order placed.", tool_call_id=tool_call.id, function="purchase"
        ),
    ]
    tools = [
        ToolInfo(
            name="purchase",
            description="Buy an item and charge the user's card.",
            parameters=ToolParams(
                properties={"item": ToolParam(type="string")}, required=["item"]
            ),
        ),
        ToolInfo(
            name="computer",
            description="Use a computer.",
            parameters=ToolParams(
                properties={
                    k: ToolParam(type="string") for k in _COMPUTER_TOOL_PARAMETERS
                }
            ),
        ),
    ]

    output = await get_model(f"google/{model}").generate(messages, tools=tools)

    assert output.error is None
    assert output.completion


def test_completion_choice_inline_data_image():
    """Test that inline_data image parts are converted to ContentImage."""
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(text="Here is the image:"),
                Part(inline_data=Blob(mime_type="image/png", data=b"fake_png_data")),
            ],
        ),
        finish_reason=FinishReason.STOP,
    )
    choice = completion_choice_from_candidate("test-model", candidate)
    content = choice.message.content
    assert isinstance(content, list)
    assert len(content) == 2
    assert isinstance(content[0], ContentText)
    assert content[0].text == "Here is the image:"
    assert isinstance(content[1], ContentImage)
    assert content[1].image.startswith("data:image/png;base64,")


def test_completion_choice_inline_data_only():
    """Test that a response with only inline_data (no text) works."""
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(inline_data=Blob(mime_type="image/jpeg", data=b"fake_jpeg")),
            ],
        ),
        finish_reason=FinishReason.STOP,
    )
    choice = completion_choice_from_candidate("test-model", candidate)
    content = choice.message.content
    assert isinstance(content, list)
    assert len(content) == 1
    assert isinstance(content[0], ContentImage)
    assert content[0].image.startswith("data:image/jpeg;base64,")


def test_distribute_citations_single_text_part():
    """Test distributing citations to a single ContentText part."""
    content = [ContentText(text="The sky is blue and the grass is green.")]
    citations = [
        UrlCitation(
            url="https://example.com/sky",
            title="Sky Facts",
            cited_text=(4, 15),  # "sky is blue"
        ),
        UrlCitation(
            url="https://example.com/grass",
            title="Grass Facts",
            cited_text=(24, 40),  # "grass is green"
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # Should return same content list (mutated in place)
    assert result is content
    assert len(result) == 1
    assert isinstance(result[0], ContentText)

    # Check citations were added with same indexes (no adjustment needed for single part)
    assert result[0].citations is not None
    assert len(result[0].citations) == 2
    assert result[0].citations[0].url == "https://example.com/sky"
    assert result[0].citations[0].cited_text == (4, 15)
    assert result[0].citations[1].url == "https://example.com/grass"
    assert result[0].citations[1].cited_text == (24, 40)


def test_distribute_citations_multiple_text_parts():
    """Test distributing citations across multiple ContentText parts."""
    content = [
        ContentText(text="First part. "),  # 12 chars (0-12)
        ContentText(text="Second part. "),  # 13 chars (12-25)
        ContentText(text="Third part."),  # 11 chars (25-36)
    ]
    citations = [
        UrlCitation(
            url="https://example.com/first",
            title="First",
            cited_text=(0, 10),  # "First part" in first part
        ),
        UrlCitation(
            url="https://example.com/second",
            title="Second",
            cited_text=(12, 23),  # "Second part" in second part (global index)
        ),
        UrlCitation(
            url="https://example.com/third",
            title="Third",
            cited_text=(25, 35),  # "Third part" in third part (global index)
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # First part should have first citation with original indexes
    assert result[0].citations is not None
    assert len(result[0].citations) == 1
    assert result[0].citations[0].url == "https://example.com/first"
    assert result[0].citations[0].cited_text == (0, 10)

    # Second part should have second citation with adjusted indexes
    assert result[1].citations is not None
    assert len(result[1].citations) == 1
    assert result[1].citations[0].url == "https://example.com/second"
    assert result[1].citations[0].cited_text == (0, 11)  # Adjusted from (12, 23)

    # Third part should have third citation with adjusted indexes
    assert result[2].citations is not None
    assert len(result[2].citations) == 1
    assert result[2].citations[0].url == "https://example.com/third"
    assert result[2].citations[0].cited_text == (0, 10)  # Adjusted from (25, 35)


def test_distribute_citations_with_reasoning():
    """Test that ContentReasoning parts are skipped when calculating offsets."""
    content = [
        ContentText(text="First text. "),  # 12 chars (0-12)
        ContentReasoning(reasoning="Some thinking here..."),  # Not counted
        ContentText(text="Second text."),  # 12 chars (12-24 in global text)
    ]
    citations = [
        UrlCitation(
            url="https://example.com/first",
            title="First",
            cited_text=(0, 5),  # "First" in first ContentText
        ),
        UrlCitation(
            url="https://example.com/second",
            title="Second",
            cited_text=(12, 18),  # "Second" in second ContentText (global index)
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # First ContentText should have first citation
    assert result[0].citations is not None
    assert len(result[0].citations) == 1
    assert result[0].citations[0].cited_text == (0, 5)

    # ContentReasoning should remain unchanged
    assert isinstance(result[1], ContentReasoning)
    assert not hasattr(result[1], "citations")

    # Second ContentText should have second citation with adjusted indexes
    assert result[2].citations is not None
    assert len(result[2].citations) == 1
    assert result[2].citations[0].cited_text == (0, 6)  # Adjusted from (12, 18)


def test_distribute_citations_spanning_multiple_parts():
    """Test citation that spans across multiple parts - should go to first part only."""
    content = [
        ContentText(text="First part "),  # 11 chars (0-11)
        ContentText(text="Second part"),  # 11 chars (11-22)
    ]
    citations = [
        UrlCitation(
            url="https://example.com/span",
            title="Spanning",
            cited_text=(6, 17),  # Starts in first part, ends in second part
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # Citation should only be added to first part (where it starts)
    assert result[0].citations is not None
    assert len(result[0].citations) == 1
    assert result[0].citations[0].cited_text == (6, 17)  # Adjusted from start

    # Second part should have no citations
    assert result[1].citations is None


def test_distribute_citations_empty_citations_list() -> None:
    """Test with empty citations list."""
    content: list[InspectContent] = [ContentText(text="Some text")]
    citations: list[Citation] = []

    result = distribute_citations_to_text_parts(content, citations)

    # Should return same content unchanged
    assert result is content
    assert isinstance(result[0], ContentText)
    assert result[0].citations is None


def test_distribute_citations_no_matching_parts():
    """Test citation with index beyond all text parts."""
    content = [ContentText(text="Short")]  # 5 chars (0-5)
    citations = [
        UrlCitation(
            url="https://example.com/beyond",
            title="Beyond",
            cited_text=(10, 15),  # Beyond the text range
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # Citation should not be added anywhere
    assert result[0].citations is None


def test_distribute_citations_boundary_conditions():
    """Test citations at exact boundaries between parts."""
    content = [
        ContentText(text="ABC"),  # 3 chars (0-3)
        ContentText(text="DEF"),  # 3 chars (3-6)
    ]
    citations = [
        UrlCitation(
            url="https://example.com/boundary",
            title="Boundary",
            cited_text=(3, 6),  # Starts exactly at second part boundary
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # Citation at boundary should go to the second part
    assert result[0].citations is None
    assert result[1].citations is not None
    assert len(result[1].citations) == 1
    assert result[1].citations[0].cited_text == (0, 3)  # Adjusted from (3, 6)


def test_distribute_citations_preserves_citation_metadata():
    """Test that all citation metadata is preserved during distribution."""
    content = [ContentText(text="Example text")]
    citations = [
        UrlCitation(
            url="https://example.com/source",
            title="Example Source",
            cited_text=(0, 7),
            internal={"custom_field": "custom_value"},
        ),
    ]

    result = distribute_citations_to_text_parts(content, citations)

    # Check all fields are preserved
    assert result[0].citations is not None
    assert len(result[0].citations) == 1
    citation = result[0].citations[0]
    assert citation.url == "https://example.com/source"
    assert citation.title == "Example Source"
    assert citation.cited_text == (0, 7)
    assert citation.internal == {"custom_field": "custom_value"}


def test_thought_signature_on_tool_call():
    """Test that thought_signature is correctly applied to tool calls, not intermediate text."""
    # Create a mock client
    mock_client = MagicMock()

    # Create a message with reasoning + text + tool call
    # This simulates what Inspect stores after parsing a Gemini response
    # where the tool call had a thought_signature
    thought_sig = b"fake_thought_signature_bytes"
    encoded_sig = base64.b64encode(thought_sig).decode()

    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning=encoded_sig, redacted=True),
            ContentText(text="I'll use the bash tool."),
        ],
        tool_calls=[
            ToolCall(
                id="bash_123",
                function="bash",
                arguments={"command": "ls"},
            )
        ],
    )

    # Convert to Google format
    result = asyncio.run(content(mock_client, message))

    # The result should be a Content object with parts
    assert result.role == "model"
    assert result.parts is not None
    assert len(result.parts) == 2  # text part + function call part

    # First part should be text WITHOUT thought_signature
    assert result.parts[0].text == "I'll use the bash tool."
    assert result.parts[0].thought_signature is None

    # Second part should be function call WITH thought_signature
    assert result.parts[1].function_call is not None
    assert result.parts[1].function_call.name == "bash"
    assert result.parts[1].thought_signature == thought_sig


# Tests for MALFORMED_FUNCTION_CALL retry logic helper functions


def test_malformed_function_message_with_finish_message():
    """Test _malformed_function_message extracts finish_message from Candidate."""
    candidate = Candidate(
        finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
        finish_message="print(default_api.foo(x=1))",
        content=Content(parts=None, role="model"),
    )
    result = _malformed_function_message(candidate)
    assert result == "print(default_api.foo(x=1))"


def test_malformed_function_message_without_finish_message():
    """Test _malformed_function_message returns default when finish_message is None."""
    candidate = Candidate(
        finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
        finish_message=None,
        content=Content(parts=None, role="model"),
    )
    result = _malformed_function_message(candidate)
    assert "malformed function call" in result.lower()


def test_malformed_function_message_from_response():
    """Test _malformed_function_message works with GenerateContentResponse."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
                finish_message="print(api.bar())",
                content=Content(parts=None, role="model"),
            )
        ]
    )
    result = _malformed_function_message(response)
    assert result == "print(api.bar())"


def test_malformed_function_message_from_empty_response():
    """Test _malformed_function_message handles empty candidates list."""
    response = GenerateContentResponse(candidates=[])
    result = _malformed_function_message(response)
    assert "malformed function call" in result.lower()


def test_malformed_function_retry_returns_correct_content():
    """Test _malformed_function_retry returns model and user messages."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
                finish_message="print(foo())",
                content=Content(parts=None, role="model"),
            )
        ]
    )

    contents, _ = _malformed_function_retry(response, "auto")

    # Should return two Content objects: model acknowledgment + user instruction
    assert len(contents) == 2
    assert contents[0].role == "model"
    assert contents[1].role == "user"

    # Model message should contain the error
    assert contents[0].parts is not None
    assert "print(foo())" in contents[0].parts[0].text

    # User message should instruct to fix
    assert contents[1].parts is not None
    assert "JSON" in contents[1].parts[0].text


def test_malformed_function_retry_forces_any_mode_when_auto():
    """Test _malformed_function_retry sets tool_config to ANY when tool_choice is auto."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
                finish_message=None,
                content=Content(parts=None, role="model"),
            )
        ]
    )

    _, tool_config = _malformed_function_retry(response, "auto")

    assert tool_config is not None
    assert tool_config.function_calling_config is not None
    assert tool_config.function_calling_config.mode == FunctionCallingConfigMode.ANY


def test_malformed_function_retry_no_tool_config_change_when_not_auto():
    """Test _malformed_function_retry doesn't change tool_config when already forced."""
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
                finish_message=None,
                content=Content(parts=None, role="model"),
            )
        ]
    )

    # When tool_choice is already "any", no need to change tool_config
    _, tool_config = _malformed_function_retry(response, "any")
    assert tool_config is None

    # Same for "none"
    _, tool_config = _malformed_function_retry(response, "none")
    assert tool_config is None


# Integration tests for MALFORMED_FUNCTION_CALL retry loop with mocked client


def _create_mock_google_client(mock_generate: AsyncMock) -> MagicMock:
    """Create a mock Google client with the right structure for testing."""
    mock_client = MagicMock()
    mock_client.aio.__aenter__ = AsyncMock(return_value=mock_client.aio)
    mock_client.aio.__aexit__ = AsyncMock(return_value=None)
    mock_client.aio.models.generate_content = mock_generate
    mock_client._api_client._async_httpx_client = MagicMock()
    return mock_client


def _create_mock_google_count_tokens_client(total_tokens: int = 7) -> MagicMock:
    mock_client = MagicMock()
    mock_client.aio.__aenter__ = AsyncMock(return_value=mock_client.aio)
    mock_client.aio.__aexit__ = AsyncMock(return_value=None)
    mock_client.aio.models.count_tokens = AsyncMock(
        return_value=MagicMock(total_tokens=total_tokens)
    )
    mock_client._api_client._async_httpx_client = MagicMock()
    return mock_client


def _client_http_options(client_mock: MagicMock) -> HttpOptions:
    http_options = client_mock.call_args.kwargs["http_options"]
    assert isinstance(http_options, HttpOptions)
    return http_options


def _create_malformed_response(
    finish_message: str | None = None,
) -> GenerateContentResponse:
    """Create a response with MALFORMED_FUNCTION_CALL finish reason."""
    return GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.MALFORMED_FUNCTION_CALL,
                finish_message=finish_message or "print(default_api.my_tool(x=1))",
                content=Content(parts=None, role="model"),
            )
        ],
        usage_metadata=None,
    )


def _create_success_response_with_tool_call() -> GenerateContentResponse:
    """Create a successful response with a tool call."""
    return GenerateContentResponse(
        candidates=[
            Candidate(
                finish_reason=FinishReason.STOP,
                content=Content(
                    role="model",
                    parts=[
                        Part(function_call=FunctionCall(name="my_tool", args={"x": 1}))
                    ],
                ),
            )
        ],
        usage_metadata=None,
    )


def _create_test_tool() -> ToolInfo:
    """Create a simple test tool for testing."""
    return ToolInfo(
        name="my_tool",
        description="A test tool",
        parameters=ToolParams(
            type="object",
            properties={"x": ToolParam(type="integer", description="A number")},
            required=["x"],
        ),
    )


@pytest.mark.parametrize(
    ("config", "expected_timeout"),
    [
        (GenerateConfig(), 3_600_000),
        (GenerateConfig(timeout=123), 123_000),
        (GenerateConfig(timeout=0), 0),
    ],
)
@pytest.mark.anyio
async def test_google_generate_http_timeout(
    config: GenerateConfig, expected_timeout: int
) -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)

    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=config,
        )

    http_options = _client_http_options(client)
    assert http_options.timeout == expected_timeout


@pytest.mark.anyio
async def test_google_batcher_client_uses_default_http_timeout() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)

    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        config = GenerateConfig(batch=BatchConfig(size=1))

        api._resolve_batcher(config, api._http_options(config))

        assert api._batcher is not None
        assert api._batcher._client is mock_client

    http_options = client.call_args.kwargs["http_options"]
    assert http_options.timeout == 3_600_000


@pytest.mark.anyio
async def test_google_count_tokens_none_config_uses_default_http_timeout() -> None:
    mock_client = _create_mock_google_count_tokens_client()

    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        tokens = await api.count_tokens("Hello")

    assert tokens == 7
    http_options = _client_http_options(client)
    assert http_options.timeout == 3_600_000


def _capture_google_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import inspect_ai._util.logger as logger_module
    import inspect_ai.model._providers.google as google_module

    warnings: list[str] = []
    monkeypatch.setattr(logger_module, "_warned", [])
    monkeypatch.setattr(google_module.logger, "warning", warnings.append)
    return warnings


@pytest.mark.anyio
@pytest.mark.parametrize(
    "input",
    ["Hello world", [ChatMessageUser(content="Hello world")]],
    ids=["str", "messages"],
)
async def test_google_count_tokens_falls_back_when_endpoint_unavailable(
    input: str | list[ChatMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_google_warnings(monkeypatch)
    mock_client = _create_mock_google_count_tokens_client()
    mock_client.aio.models.count_tokens.side_effect = ClientError(
        404, {"error": {"code": 404, "message": "Not Found"}}
    )

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
        )
        expected = await ModelAPI.count_tokens(api, input)
        assert await api.count_tokens(input) == expected
        # endpoint is not called again once it has returned 404
        assert await api.count_tokens(input) == expected

    assert mock_client.aio.models.count_tokens.await_count == 1
    assert len(warnings) == 1
    assert "not available" in warnings[0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        ClientError(400, {"error": {"code": 400, "message": "Bad request"}}),
        ClientError(403, {"error": {"code": 403, "message": "Forbidden"}}),
    ],
    ids=["400", "403"],
)
async def test_google_count_tokens_falls_back_on_non_retryable_errors(
    error: APIError, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_google_warnings(monkeypatch)
    mock_client = _create_mock_google_count_tokens_client()
    mock_client.aio.models.count_tokens.side_effect = error

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
        )
        expected = await ModelAPI.count_tokens(api, "Hello world")
        assert await api.count_tokens("Hello world") == expected
        # not memoized: the endpoint is tried again on the next call
        assert await api.count_tokens("Hello world") == expected

    assert mock_client.aio.models.count_tokens.await_count == 2
    assert len(warnings) == 1
    assert str(error.code) in warnings[0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        ClientError(401, {"error": {"code": 401, "message": "Unauthorized"}}),
        ClientError(429, {"error": {"code": 429, "message": "Too many requests"}}),
        ServerError(503, {"error": {"code": 503, "message": "Unavailable"}}),
    ],
    ids=["401", "429", "503"],
)
async def test_google_count_tokens_propagates_retryable_and_auth_errors(
    error: APIError,
) -> None:
    mock_client = _create_mock_google_count_tokens_client()
    mock_client.aio.models.count_tokens.side_effect = error

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
        )
        with pytest.raises(APIError) as exc_info:
            await api.count_tokens("Hello world")

    assert exc_info.value is error


@pytest.mark.anyio
async def test_google_count_tokens_propagates_non_api_errors() -> None:
    mock_client = _create_mock_google_count_tokens_client()
    mock_client.aio.models.count_tokens.side_effect = ValueError("boom")

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
        )
        with pytest.raises(ValueError, match="boom"):
            await api.count_tokens("Hello world")


@pytest.mark.anyio
async def test_google_generate_preserves_request_extra_headers() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(extra_headers={"x-test-header": "present"}),
        )

    request_config = mock_generate.call_args.kwargs["config"]
    assert request_config.http_options.headers["x-test-header"] == "present"
    assert HttpHooks.REQUEST_ID_HEADER in request_config.http_options.headers


@pytest.mark.anyio
async def test_malformed_function_call_retry_succeeds():
    """Test that retry succeeds after initial MALFORMED_FUNCTION_CALL."""
    # First call returns malformed, second call succeeds
    mock_generate = AsyncMock(
        side_effect=[
            _create_malformed_response(),
            _create_success_response_with_tool_call(),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        output, _ = await api.generate(
            input=[ChatMessageUser(content="Call my_tool with x=1")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Verify retry happened (2 calls total)
        assert mock_generate.call_count == 2

        # Verify successful tool call in output
        assert output.choices[0].message.tool_calls is not None
        assert len(output.choices[0].message.tool_calls) == 1
        assert output.choices[0].message.tool_calls[0].function == "my_tool"


@pytest.mark.anyio
async def test_malformed_function_call_retry_exhausted():
    """Test behavior when all retry attempts fail with MALFORMED_FUNCTION_CALL."""
    # All 3 calls return malformed
    mock_generate = AsyncMock(
        side_effect=[
            _create_malformed_response("print(api.call1())"),
            _create_malformed_response("print(api.call2())"),
            _create_malformed_response("print(api.call3())"),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        output, _ = await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Verify all 3 attempts were made
        assert mock_generate.call_count == 3

        # Verify the synthesized error message is in the output
        content_str = str(output.choices[0].message.content)
        assert "trouble calling a function" in content_str

        # Verify stop reason
        assert output.choices[0].stop_reason == "unknown"


@pytest.mark.anyio
async def test_malformed_function_call_retry_adds_feedback_messages():
    """Test that retry adds feedback messages to the conversation."""
    # First call returns malformed, second call succeeds
    mock_generate = AsyncMock(
        side_effect=[
            _create_malformed_response(),
            _create_success_response_with_tool_call(),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Verify 2 calls were made
        assert mock_generate.call_count == 2

        # The second call should have additional feedback messages
        # We can check by examining the call args
        second_call_kwargs = mock_generate.call_args_list[1].kwargs
        contents = second_call_kwargs.get("contents", [])

        # Original message + model feedback + user instruction = at least 3 messages
        assert len(contents) >= 3

        # Check that feedback messages were added
        roles = [c.role for c in contents]
        assert "model" in roles
        assert "user" in roles


async def test_function_tools_add_no_system_instruction():
    mock_generate = AsyncMock(return_value=_create_success_response_with_tool_call())
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.5-pro", base_url=None, api_key="test-key"
        )
        await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    config = mock_generate.call_args.kwargs["config"]
    assert config.tools
    assert config.system_instruction is None


def _with_usage(
    response: GenerateContentResponse, prompt: int, candidates: int, thoughts: int
) -> GenerateContentResponse:
    response.usage_metadata = GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt,
        cached_content_token_count=1,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=prompt + candidates + thoughts,
    )
    return response


@pytest.mark.anyio
async def test_malformed_function_call_retry_sums_usage():
    """Usage covers every billed attempt of the retry loop, not just the last."""
    mock_generate = AsyncMock(
        side_effect=[
            _with_usage(_create_malformed_response(), 10, 2, 3),
            _with_usage(_create_malformed_response(), 20, 4, 5),
            _with_usage(_create_success_response_with_tool_call(), 30, 6, 7),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        output, _ = await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    assert mock_generate.call_count == 3
    assert output.choices[0].message.tool_calls is not None
    assert output.usage is not None
    # input excludes the 1 cached token per request
    assert output.usage.input_tokens == 9 + 19 + 29
    assert output.usage.input_tokens_cache_read == 3
    assert output.usage.output_tokens == 5 + 9 + 13
    assert output.usage.reasoning_tokens == 3 + 5 + 7
    assert output.usage.total_tokens == 15 + 29 + 43
    # the context size is the first attempt's prompt, not the sum
    assert output.input_context_tokens == 10


@pytest.mark.anyio
async def test_malformed_function_call_retry_exhausted_sums_usage():
    """When every attempt is malformed, usage still covers all of them once."""
    mock_generate = AsyncMock(
        side_effect=[
            _with_usage(_create_malformed_response(), 10, 2, 0),
            _with_usage(_create_malformed_response(), 20, 4, 0),
            _with_usage(_create_malformed_response(), 30, 6, 0),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        output, _ = await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    assert mock_generate.call_count == 3
    assert output.usage is not None
    assert output.usage.input_tokens == 9 + 19 + 29
    assert output.usage.output_tokens == 2 + 4 + 6
    assert output.usage.total_tokens == 12 + 24 + 36
    assert output.input_context_tokens == 10


@pytest.mark.anyio
async def test_malformed_function_call_retry_error_keeps_earlier_usage():
    """A retry rejected as too long keeps the usage of the attempts before it."""
    mock_generate = AsyncMock(
        side_effect=[
            _with_usage(_create_malformed_response(), 10, 2, 0),
            ClientError(
                400,
                {
                    "error": {
                        "code": 400,
                        "message": "input exceeds the maximum number of tokens",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            ),
        ]
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )

        output, _ = await api.generate(
            input=[ChatMessageUser(content="Call my_tool")],
            tools=[_create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "model_length"
    assert output.usage is not None
    assert output.usage.input_tokens == 9
    assert output.usage.output_tokens == 2
    assert output.input_context_tokens == 10


def _leg(
    parts: list[Part],
    finish_reason: FinishReason,
    token: bytes | None = None,
    usage: tuple[int, int, int] = (10, 2, 3),
) -> GenerateContentResponse:
    """One leg of a continuation chain: a response with usage (prompt, output, thoughts)."""
    return _with_usage(
        GenerateContentResponse(
            candidates=[
                Candidate(
                    content=Content(role="model", parts=parts),
                    finish_reason=finish_reason,
                    continuation_token=token,
                    index=0,
                )
            ]
        ),
        *usage,
    )


def _thought(text: str) -> Part:
    return Part(thought=True, text=text)


async def _generate_with_client(
    mock_client: MagicMock,
    tools: list[ToolInfo] | None = None,
    model_args: dict[str, Any] | None = None,
    config: GenerateConfig | None = None,
) -> tuple[ModelOutput, Any]:
    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.5-pro",
            base_url=None,
            api_key="test-key",
            **(model_args or {}),
        )
        result = await api.generate(
            input=[ChatMessageUser(content="Think hard")],
            tools=tools or [],
            tool_choice="auto",
            config=config or GenerateConfig(),
        )
    assert isinstance(result, tuple)
    output, model_call = result
    assert isinstance(output, ModelOutput)
    return output, model_call


async def _generate_with_legs(
    side_effect: list[Any],
) -> tuple[ModelOutput, Any, AsyncMock]:
    mock_generate = AsyncMock(side_effect=side_effect)
    output, model_call = await _generate_with_client(
        _create_mock_google_client(mock_generate)
    )
    return output, model_call, mock_generate


def _reasoning_texts(output: ModelOutput) -> list[str]:
    content = output.choices[0].message.content
    assert isinstance(content, list)
    return [c.reasoning for c in content if isinstance(c, ContentReasoning)]


@pytest.mark.anyio
async def test_continuation_is_sent_and_combined() -> None:
    """A CONTINUATION response is continued with its token in the same generate."""
    output, model_call, mock_generate = await _generate_with_legs(
        [
            _leg([_thought("part one")], FinishReason.CONTINUATION, b"tok-1"),
            _leg([_thought("part two"), Part(text="42")], FinishReason.STOP),
        ]
    )

    assert mock_generate.call_count == 2
    first, second = (c.kwargs for c in mock_generate.call_args_list)
    # the SDK must not continue on its own, or a leg would go unlogged
    assert first["config"].automatic_continuation is False
    assert first["config"].continuation_token is None
    assert second["config"].continuation_token == b"tok-1"
    # the continuation resends the same contents
    assert second["contents"] == first["contents"]

    assert _reasoning_texts(output) == ["part one", "part two"]
    assert output.completion == "42"
    assert output.stop_reason == "stop"
    # every leg's response is in the model call
    assert model_call.response is not None
    assert len(model_call.response["responses"]) == 2


@pytest.mark.anyio
async def test_several_continuations_sum_usage() -> None:
    """Usage covers every leg; the context size is the first leg's prompt."""
    output, _, mock_generate = await _generate_with_legs(
        [
            _leg([_thought("a")], FinishReason.CONTINUATION, b"t1", (10, 2, 30)),
            _leg([_thought("b")], FinishReason.CONTINUATION, b"t2", (20, 4, 50)),
            _leg([Part(text="done")], FinishReason.MAX_TOKENS, None, (30, 6, 0)),
        ]
    )

    assert mock_generate.call_count == 3
    tokens = [
        c.kwargs["config"].continuation_token for c in mock_generate.call_args_list
    ]
    assert tokens == [None, b"t1", b"t2"]
    assert _reasoning_texts(output) == ["a", "b"]
    assert output.completion == "done"
    # the final leg's stop reason
    assert output.stop_reason == "max_tokens"
    assert output.usage is not None
    # input excludes the 1 cached token per request
    assert output.usage.input_tokens == 9 + 19 + 29
    assert output.usage.input_tokens_cache_read == 3
    assert output.usage.output_tokens == 32 + 54 + 6
    assert output.usage.reasoning_tokens == 30 + 50
    assert output.input_context_tokens == 10


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize("error", ["too-long", "server-error"])
async def test_continuation_failing_partway_fails_like_one_request(
    error: str, streaming: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A continuation that fails fails the call as a single request would.

    As in the SDK, the earlier legs and their usage are not kept, and only the
    error is logged.
    """
    calls = _capture_model_calls(monkeypatch)
    first = _leg([_thought("a")], FinishReason.CONTINUATION, b"t1", (10, 2, 30))
    exception = (
        ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "input exceeds the maximum number of tokens",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
        if error == "too-long"
        else ServerError(503, {"error": {"code": 503, "message": "Unavailable"}})
    )
    mock = AsyncMock(
        side_effect=[_leg_chunks([first]) if streaming else first, exception]
    )
    mock_client = _create_mock_google_client(mock)
    if streaming:
        mock_client.aio.models.generate_content_stream = mock

    if error == "too-long":
        output, model_call = await _generate_with_client(
            mock_client, model_args=dict(streaming=streaming)
        )
        assert output.stop_reason == "model_length"
        assert output.usage is None
        assert output.input_context_tokens is None
        assert model_call.error is True
        assert model_call.response == {
            "error": {
                "message": "input exceeds the maximum number of tokens",
                "code": 400,
            }
        }
    else:
        with pytest.raises(ServerError):
            await _generate_with_client(
                mock_client, model_args=dict(streaming=streaming)
            )
        [model_call] = calls
        assert model_call.response is None
    assert mock.call_count == 2


@pytest.mark.anyio
async def test_continuation_content_filter_keeps_earlier_legs() -> None:
    """A continuation stopped by the content filter returns every leg's content."""
    output, _, _ = await _generate_with_legs(
        [
            _leg([_thought("a")], FinishReason.CONTINUATION, b"t1", (10, 2, 30)),
            _leg([_thought("b")], FinishReason.SAFETY, None, (20, 4, 5)),
        ]
    )

    assert output.stop_reason == "content_filter"
    assert _reasoning_texts(output) == ["a", "b"]
    assert output.usage is not None
    assert output.usage.output_tokens == 32 + 9
    assert output.input_context_tokens == 10


@pytest.mark.anyio
async def test_continuation_then_malformed_function_call_retry() -> None:
    """A malformed call ending a continued response retries, summing every request."""
    mock_generate = AsyncMock(
        side_effect=[
            _leg([_thought("a")], FinishReason.CONTINUATION, b"t1", (10, 2, 30)),
            _with_usage(_create_malformed_response(), 20, 4, 5),
            _with_usage(_create_success_response_with_tool_call(), 30, 6, 7),
        ]
    )
    output, model_call = await _generate_with_client(
        _create_mock_google_client(mock_generate), tools=[_create_test_tool()]
    )

    assert mock_generate.call_count == 3
    # every request's response is logged, the retried attempt's included
    assert len(model_call.response["responses"]) == 3
    tokens = [
        c.kwargs["config"].continuation_token for c in mock_generate.call_args_list
    ]
    # the retry is a new request, not a continuation
    assert tokens == [None, b"t1", None]
    assert output.choices[0].message.tool_calls is not None
    assert output.usage is not None
    assert output.usage.input_tokens == 9 + 19 + 29
    assert output.usage.output_tokens == 32 + 9 + 13
    assert output.input_context_tokens == 10


def _leg_chunks(chunks: list[GenerateContentResponse]) -> Any:
    async def stream() -> Any:
        for chunk in chunks:
            yield chunk

    return stream()


def _chunk(
    parts: list[Part] | None,
    finish_reason: FinishReason | None = None,
    token: bytes | None = None,
    usage: tuple[int, int, int] | None = None,
) -> GenerateContentResponse:
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(role="model", parts=parts),
                finish_reason=finish_reason,
                continuation_token=token,
                index=0,
            )
        ]
    )
    return _with_usage(response, *usage) if usage else response


async def _generate_streamed(
    legs: list[list[GenerateContentResponse]],
) -> tuple[ModelOutput, Any, AsyncMock]:
    mock_stream = AsyncMock(side_effect=[_leg_chunks(leg) for leg in legs])
    mock_client = _create_mock_google_client(AsyncMock())
    mock_client.aio.models.generate_content_stream = mock_stream
    output, model_call = await _generate_with_client(
        mock_client, model_args=dict(streaming=True)
    )
    return output, model_call, mock_stream


@pytest.mark.anyio
async def test_streamed_continuation_is_combined() -> None:
    """Streamed legs are continued, taking a token sent before the last chunk."""
    mock_stream = AsyncMock(
        side_effect=[
            _leg_chunks(
                [
                    _chunk([_thought("a1")]),
                    _chunk([_thought("a2")], token=b"t1"),
                    _chunk(None, FinishReason.CONTINUATION, usage=(10, 2, 30)),
                ]
            ),
            _leg_chunks(
                [
                    _chunk([_thought("b")]),
                    _chunk([Part(text="done")], FinishReason.STOP, usage=(20, 4, 5)),
                ]
            ),
        ]
    )
    mock_client = _create_mock_google_client(AsyncMock())
    mock_client.aio.models.generate_content_stream = mock_stream

    output, model_call = await _generate_with_client(
        mock_client, model_args=dict(streaming=True)
    )

    assert mock_stream.call_count == 2
    tokens = [c.kwargs["config"].continuation_token for c in mock_stream.call_args_list]
    assert tokens == [None, b"t1"]
    assert _reasoning_texts(output) == ["a1a2", "b"]
    assert output.completion == "done"
    assert output.stop_reason == "stop"
    assert output.usage is not None
    assert output.usage.output_tokens == 32 + 9
    assert output.input_context_tokens == 10
    assert len(model_call.response["responses"]) == 2


_EMPTY_PART_PLACEMENTS = pytest.mark.parametrize(
    ("before", "after"),
    [
        ([], []),
        ([Part()], []),
        ([], [Part()]),
        ([Part(text="")], []),
        ([], [Part(text="")]),
    ],
    ids=[
        "no-empty-part",
        "empty-part-before",
        "empty-part-after",
        "empty-text-before",
        "empty-text-after",
    ],
)


@pytest.mark.anyio
@_EMPTY_PART_PLACEMENTS
async def test_continuation_text_split_across_legs(
    before: list[Part], after: list[Part]
) -> None:
    """Output text split at a leg boundary reads as one text, so JSON stays valid.

    Each leg's parts stay apart, as the SDK keeps them; empty parts without a
    signature have nothing to replay and are dropped.
    """
    output, _, _ = await _generate_with_legs(
        [
            _leg(
                [Part(text='{"answer":"hel'), *before],
                FinishReason.CONTINUATION,
                b"t1",
            ),
            _leg([*after, Part(text='lo"}')], FinishReason.STOP),
        ]
    )

    assert output.completion == '{"answer":"hello"}'
    content_list = output.message.content
    assert isinstance(content_list, list)
    assert [c.text for c in content_list if isinstance(c, ContentText)] == [
        '{"answer":"hel',
        'lo"}',
    ]
    replayed = await content(MagicMock(), output.message)
    assert replayed.parts == [Part(text='{"answer":"hel'), Part(text='lo"}')]


@pytest.mark.anyio
@_EMPTY_PART_PLACEMENTS
async def test_streamed_continuation_text_split_across_legs(
    before: list[Part], after: list[Part]
) -> None:
    """A streamed leg boundary inside output text adds no newline either."""
    output, _, _ = await _generate_streamed(
        [
            [
                _chunk([Part(text='{"answer":"hel')]),
                _chunk(before or None, FinishReason.CONTINUATION, b"t1"),
            ],
            [
                _chunk(after or None),
                _chunk([Part(text='lo"}')], FinishReason.STOP),
            ],
        ]
    )

    assert output.completion == '{"answer":"hello"}'


def _signed(text: str | None, signature: bytes | None = b"s1") -> Part:
    return Part(text=text, thought_signature=signature)


_HEL = Part(text='{"answer":"hel')
_LO = Part(text='lo"}')

# (first leg, last leg, replayed parts, replayed parts when streamed): a
# streamed request joins a signature onto the output text before it in that
# request, as it always has
_SIGNED_BOUNDARIES = {
    "signed-left": (
        [_signed('{"answer":"hel')],
        [_LO],
        [_signed('{"answer":"hel'), _LO],
        None,
    ),
    "signed-right": (
        [_HEL],
        [_signed('lo"}', b"s2")],
        [_HEL, _signed('lo"}', b"s2")],
        None,
    ),
    "both-signed": (
        [_signed('{"answer":"hel')],
        [_signed('lo"}', b"s2")],
        [_signed('{"answer":"hel'), _signed('lo"}', b"s2")],
        None,
    ),
    "signature-only-ends-leg": (
        [_HEL, _signed(None)],
        [_LO],
        [_HEL, _signed(""), _LO],
        [_signed('{"answer":"hel'), _LO],
    ),
    "signature-only-starts-leg": (
        [_HEL],
        [_signed(None), _LO],
        [_HEL, _signed(""), _LO],
        None,
    ),
    "signed-empty-ends-leg": (
        [_HEL, _signed("")],
        [_LO],
        [_HEL, _signed(""), _LO],
        [_signed('{"answer":"hel'), _LO],
    ),
    "signed-empty-starts-leg": (
        [_HEL],
        [_signed(""), _LO],
        [_HEL, _signed(""), _LO],
        None,
    ),
    # visible thinking is not replayed, as for a single response
    "signed-empty-after-thinking": (
        [_thought("thinking"), _signed("")],
        [Part(text='{"answer":"hello"}')],
        [_signed(""), Part(text='{"answer":"hello"}')],
        None,
    ),
    # a later signature is not the reasoning's when output text came between
    "signed-right-after-thinking-and-text": (
        [_thought("thinking"), _HEL],
        [_signed('lo"}', b"s2")],
        [_thought("thinking"), _HEL, _signed('lo"}', b"s2")],
        None,
    ),
    "signature-only-starts-leg-after-thinking-and-text": (
        [_thought("thinking"), _HEL],
        [_signed(None, b"s2"), _LO],
        [_thought("thinking"), _HEL, _signed("", b"s2"), _LO],
        None,
    ),
    "signed-empty-starts-leg-after-thinking-and-text": (
        [_thought("thinking"), _HEL],
        [_signed("", b"s2"), _LO],
        [_thought("thinking"), _HEL, _signed("", b"s2"), _LO],
        None,
    ),
}


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize("case", list(_SIGNED_BOUNDARIES))
async def test_continuation_replays_signatures_in_place(
    case: str, streaming: bool
) -> None:
    """Every signed part of a continued turn replays with its signature in place.

    Checked after the output goes through its JSON form, as a log stores it.
    A part with only a signature replays as signed empty text. Each request's
    logged response keeps its signatures.
    """
    first, last, replay, streamed_replay = _SIGNED_BOUNDARIES[case]
    if streaming:
        output, model_call, _ = await _generate_streamed(
            [
                [*(_chunk([part]) for part in first)]
                + [_chunk(None, FinishReason.CONTINUATION, b"t1")],
                [*(_chunk([part]) for part in last)]
                + [_chunk(None, FinishReason.STOP)],
            ]
        )
    else:
        output, model_call, _ = await _generate_with_legs(
            [
                _leg(first, FinishReason.CONTINUATION, b"t1"),
                _leg(last, FinishReason.STOP),
            ]
        )

    assert json.loads(output.completion) == {"answer": "hello"}
    stored = ModelOutput.model_validate_json(output.model_dump_json())
    replayed = await content(MagicMock(), stored.message)
    assert replayed.parts == ((streaming and streamed_replay) or replay)
    signatures = sum(part.thought_signature is not None for part in first + last)
    assert json.dumps(model_call.response).count("thoughtSignature") == signatures


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize(
    "text", [None, "", "hel"], ids=["signature-only", "signed-empty", "signed-text"]
)
async def test_continuation_replays_text_signature_before_tool_call(
    text: str | None, streaming: bool
) -> None:
    """A signed text part keeps its signature when a tool call follows it.

    The function call keeps its own signature and place.
    """
    first = [_signed(text)]
    last = [
        Part(
            function_call=FunctionCall(name="calculator", args={"expr": "2+2"}),
            thought_signature=b"s2",
        )
    ]
    if streaming:
        output, _, _ = await _generate_streamed(
            [
                [_chunk(first), _chunk(None, FinishReason.CONTINUATION, b"t1")],
                [_chunk(last), _chunk(None, FinishReason.STOP)],
            ]
        )
    else:
        output, _, _ = await _generate_with_legs(
            [
                _leg(first, FinishReason.CONTINUATION, b"t1"),
                _leg(last, FinishReason.STOP),
            ]
        )

    assert output.completion == (text or "")
    stored = ModelOutput.model_validate_json(output.model_dump_json())
    replayed = await content(MagicMock(), stored.message)
    assert replayed.parts is not None
    text_part, call_part = replayed.parts
    assert text_part == _signed(text or "")
    assert call_part.function_call is not None
    assert call_part.function_call.name == "calculator"
    assert call_part.thought_signature == b"s2"


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize(
    "tool_type", [ToolType.GOOGLE_SEARCH_WEB, ToolType.GOOGLE_SEARCH_IMAGE]
)
async def test_continuation_replays_search_and_answer_signatures(
    tool_type: ToolType, streaming: bool
) -> None:
    """A server-side search ends the reasoning before it, so a later signature is the answer's.

    The search call, its result and the answer each replay with their own
    signature, after the output goes through its JSON form.
    """
    search = Part(
        thought_signature=b"s1",
        tool_call=GeminiToolCall(
            id="search-1", tool_type=tool_type, args={"queries": ["q"]}
        ),
    )
    result = Part(
        thought_signature=b"r1",
        tool_response=ToolResponse(
            id="search-1", tool_type=tool_type, response={"results": ["r"]}
        ),
    )
    first = [_thought("thinking"), search, result]
    last = [_signed("answer", b"s2")]
    if streaming:
        output, _, _ = await _generate_streamed(
            [
                [*(_chunk([part]) for part in first)]
                + [_chunk(None, FinishReason.CONTINUATION, b"t1")],
                [*(_chunk([part]) for part in last), _chunk(None, FinishReason.STOP)],
            ]
        )
    else:
        output, _, _ = await _generate_with_legs(
            [
                _leg(first, FinishReason.CONTINUATION, b"t1"),
                _leg(last, FinishReason.STOP),
            ]
        )

    stored = ModelOutput.model_validate_json(output.model_dump_json())
    replayed = await content(MagicMock(), stored.message)
    assert replayed.parts is not None
    signatures = {
        "call": [p.thought_signature for p in replayed.parts if p.tool_call],
        "result": [p.thought_signature for p in replayed.parts if p.tool_response],
        "answer": [p.thought_signature for p in replayed.parts if p.text == "answer"],
    }
    assert signatures == {"call": [b"s1"], "result": [b"r1"], "answer": [b"s2"]}


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize(
    "text", [None, "", "answer"], ids=["signature-only", "signed-empty", "signed-text"]
)
@pytest.mark.parametrize(
    "tool_type", [ToolType.GOOGLE_SEARCH_WEB, ToolType.GOOGLE_SEARCH_IMAGE]
)
async def test_continuation_unsigned_call_after_search_and_signed_text(
    tool_type: ToolType, text: str | None, streaming: bool
) -> None:
    """An unsigned function call after a search and signed text stays unsigned.

    As in the SDK's merge, the search's signature does not move onto the call
    across the signed text, after the output goes through its JSON form.
    """
    first = [
        Part(
            thought_signature=b"s1",
            tool_call=GeminiToolCall(
                id="search-1", tool_type=tool_type, args={"queries": ["q"]}
            ),
        ),
        Part(
            thought_signature=b"r1",
            tool_response=ToolResponse(
                id="search-1", tool_type=tool_type, response={"results": ["r"]}
            ),
        ),
    ]
    last = [
        _signed(text, b"s2"),
        Part(function_call=FunctionCall(name="calculator", args={"expr": "2+2"})),
    ]
    if streaming:
        output, _, _ = await _generate_streamed(
            [
                [*(_chunk([part]) for part in first)]
                + [_chunk(None, FinishReason.CONTINUATION, b"t1")],
                [*(_chunk([part]) for part in last), _chunk(None, FinishReason.STOP)],
            ]
        )
    else:
        output, _, _ = await _generate_with_legs(
            [
                _leg(first, FinishReason.CONTINUATION, b"t1"),
                _leg(last, FinishReason.STOP),
            ]
        )

    stored = ModelOutput.model_validate_json(output.model_dump_json())
    replayed = await content(MagicMock(), stored.message)
    assert replayed.parts is not None
    search, result, signed, call = replayed.parts
    assert (search.tool_call is not None, search.thought_signature) == (True, b"s1")
    assert (result.tool_response is not None, result.thought_signature) == (
        True,
        b"r1",
    )
    assert signed == _signed(text or "", b"s2")
    assert call.function_call is not None
    assert call.thought_signature is None


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
async def test_continuation_with_only_empty_text_keeps_its_completion(
    streaming: bool,
) -> None:
    """A continued turn with no text takes the message's text as its completion.

    So the completion is the same after the output is reloaded.
    """
    call = Part(
        function_call=FunctionCall(name="calculator", args={"expr": "2+2"}),
        thought_signature=b"s3",
    )
    first = [_signed("")]
    last = [_signed("", b"s2"), call]
    if streaming:
        output, _, _ = await _generate_streamed(
            [
                [_chunk(first), _chunk(None, FinishReason.CONTINUATION, b"t1")],
                [*(_chunk([part]) for part in last), _chunk(None, FinishReason.STOP)],
            ]
        )
    else:
        output, _, _ = await _generate_with_legs(
            [
                _leg(first, FinishReason.CONTINUATION, b"t1"),
                _leg(last, FinishReason.STOP),
            ]
        )

    assert output.completion == output.message.text == "\n"
    stored = ModelOutput.model_validate_json(output.model_dump_json())
    assert stored.completion == output.completion


@pytest.mark.anyio
@pytest.mark.parametrize("bridge", ["google", "chat-completions"])
async def test_continuation_bridges_like_one_response(bridge: str) -> None:
    """A continued turn goes through the agent bridges as one response would.

    The continued output holds the same content as a single response with
    the same parts, so the bridges need nothing more for it.
    """
    first = [_signed('{"answer":"hel')]
    last = [_signed('lo"}', b"s2")]
    continued, _, _ = await _generate_with_legs(
        [
            _leg(first, FinishReason.CONTINUATION, b"t1"),
            _leg(last, FinishReason.STOP),
        ]
    )
    single, _, _ = await _generate_with_legs([_leg(first + last, FinishReason.STOP)])
    assert continued.message.content == single.message.content

    async def round_trip(output: ModelOutput) -> tuple[Any, list[Part] | None]:
        if bridge == "google":
            response = gemini_response_from_output(output, "gemini-2.5-pro")
            wire = response["candidates"][0]["content"]
            messages = messages_from_google_contents([wire], None)
        else:
            [choice] = openai_chat_choices(output.choices)
            wire = ChatCompletionAssistantMessageParam(
                role="assistant", content=choice.message.content
            )
            messages = await messages_from_openai([wire])
        message = messages[-1]
        assert isinstance(message, ChatMessageAssistant)
        return wire, (await content(MagicMock(), message)).parts

    assert await round_trip(continued) == await round_trip(single)


@pytest.mark.anyio
async def test_continuation_text_marked_not_thought() -> None:
    """Parts marked thought=False are output text, and empty ones are skipped."""
    output, _, _ = await _generate_with_legs(
        [
            _leg(
                [Part(text='{"a":"hel', thought=False), Part(thought=False)],
                FinishReason.CONTINUATION,
                b"t1",
            ),
            _leg([Part(text='lo"}', thought=False)], FinishReason.STOP),
        ]
    )

    assert output.completion == '{"a":"hello"}'


def _blocked_leg() -> GenerateContentResponse:
    return _with_usage(
        GenerateContentResponse(
            prompt_feedback=GenerateContentResponsePromptFeedback(
                block_reason=BlockedReason.PROHIBITED_CONTENT
            )
        ),
        20,
        0,
        0,
    )


@pytest.mark.anyio
async def test_continuation_blocked_without_candidate() -> None:
    """A continuation blocked with no candidate reports the block, not a stop."""
    output, _, _ = await _generate_with_legs(
        [
            _leg([Part(text="partial")], FinishReason.CONTINUATION, b"t1", (10, 2, 3)),
            _blocked_leg(),
        ]
    )

    assert output.completion == "partial"
    assert output.stop_reason == "content_filter"
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.type == "PROHIBITED_CONTENT"
    assert output.usage is not None
    assert output.usage.input_tokens == 9 + 19
    assert output.input_context_tokens == 10


@pytest.mark.anyio
async def test_streamed_continuation_blocked_without_candidate() -> None:
    """A streamed continuation blocked with no candidate reports the block."""
    output, _, _ = await _generate_streamed(
        [
            [_chunk([Part(text="partial")], FinishReason.CONTINUATION, b"t1")],
            [_blocked_leg()],
        ]
    )

    assert output.completion == "partial"
    assert output.stop_reason == "content_filter"


def _grounded_leg(
    parts: list[Part],
    url: str,
    start: int,
    end: int,
    finish_reason: FinishReason,
    token: bytes | None = None,
) -> GenerateContentResponse:
    return _ground(_leg(parts, finish_reason, token), url, start, end)


def _ground(
    response: GenerateContentResponse, url: str, start: int, end: int
) -> GenerateContentResponse:
    assert response.candidates
    response.candidates[0].grounding_metadata = GroundingMetadata(
        grounding_chunks=[GroundingChunk(web=GroundingChunkWeb(uri=url, title=url))],
        grounding_supports=[
            GroundingSupport(
                grounding_chunk_indices=[0],
                segment=Segment(start_index=start, end_index=end),
            )
        ],
    )
    return response


def _citations(output: ModelOutput) -> list[tuple[str, list[Any]]]:
    content = output.message.content
    assert isinstance(content, list)
    return [
        (
            c.text,
            [
                (citation.url, citation.cited_text)
                for citation in c.citations or []
                if isinstance(citation, UrlCitation)
            ],
        )
        for c in content
        if isinstance(c, ContentText)
    ]


@pytest.mark.anyio
async def test_continuation_citations_follow_their_leg() -> None:
    """A later leg's grounding cites its own text, not the first leg's."""
    output, _, _ = await _generate_with_legs(
        [
            _grounded_leg(
                [Part(text="Alpha")],
                "https://a",
                0,
                5,
                FinishReason.CONTINUATION,
                b"t1",
            ),
            _grounded_leg([Part(text="Bravo")], "https://b", 0, 5, FinishReason.STOP),
        ]
    )

    assert _citations(output) == [
        ("Alpha", [("https://a", (0, 5))]),
        ("Bravo", [("https://b", (0, 5))]),
    ]


@pytest.mark.anyio
async def test_continuation_citations_after_reasoning() -> None:
    """A later leg's citations stay on its text when reasoning comes before it."""
    output, _, _ = await _generate_with_legs(
        [
            _grounded_leg(
                [Part(text="Alpha")],
                "https://a",
                0,
                5,
                FinishReason.CONTINUATION,
                b"t1",
            ),
            _grounded_leg(
                [_thought("checking"), Part(text="Bravo")],
                "https://b",
                0,
                5,
                FinishReason.STOP,
            ),
        ]
    )

    assert _citations(output) == [
        ("Alpha", [("https://a", (0, 5))]),
        ("Bravo", [("https://b", (0, 5))]),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("first_leg", ["continued", "cut-off", "trimmed"])
async def test_streamed_continuation_citations(first_leg: str) -> None:
    """A leg keeps its citations unless it was trimmed to its checkpoint.

    A trimmed leg's grounding may cite the discarded text, so it is dropped
    rather than moved onto the text that replaced it.
    """
    legs = {
        "continued": [
            _ground(
                _chunk([Part(text="kept")], FinishReason.CONTINUATION, b"t1"),
                "https://kept",
                0,
                4,
            )
        ],
        "cut-off": [
            _ground(_chunk([Part(text="kept")], token=b"t1"), "https://kept", 0, 4)
        ],
        "trimmed": [
            _chunk([Part(text="kept")], token=b"t1"),
            _ground(_chunk([Part(text=" lost")]), "https://lost", 4, 9),
        ],
    }
    output, _, _ = await _generate_streamed(
        [
            legs[first_leg],
            [_chunk([Part(text=" rest")], FinishReason.STOP)],
        ]
    )

    assert output.completion == "kept rest"
    citations = [cited for _, cited in _citations(output)]
    if first_leg == "trimmed":
        assert citations == [[], []]
    else:
        assert citations == [[("https://kept", (0, 4))], []]


@pytest.mark.anyio
async def test_cut_off_stream_resumes_from_its_checkpoint() -> None:
    """A stream that ends after a checkpoint with no finish reason is continued.

    The text after the checkpoint is dropped, since the next leg resumes from
    the checkpoint, and the leg's usage is its usage at the checkpoint.
    """
    events: list[StreamEvent] = []

    async def collect(event: StreamEvent) -> None:
        events.append(event)

    observer = ModelStreamObserver(
        model="google/test", on_stream=collect, publish_partial=False
    )
    event = ModelEvent(
        model="google/test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        pending=True,
    )
    await observer.begin_attempt(event)
    with model_stream_observer(observer):
        output, model_call, mock_stream = await _generate_streamed(
            [
                [
                    _chunk([Part(text="kept")], token=b"t1", usage=(10, 2, 3)),
                    _chunk([Part(text=" lost")], usage=(10, 4, 3)),
                ],
                [_chunk([Part(text=" rest")], FinishReason.STOP, usage=(20, 1, 0))],
            ]
        )

    # observers are told to drop the discarded text and are sent the kept
    # text, with its token count
    assert _streamed_text(events) == "kept rest"
    progress = model_event_progress(event)
    assert progress is not None and progress.output_tokens == 5 + 1
    assert mock_stream.call_count == 2
    tokens = [c.kwargs["config"].continuation_token for c in mock_stream.call_args_list]
    assert tokens == [None, b"t1"]
    assert output.completion == "kept rest"
    assert output.stop_reason == "stop"
    assert output.usage is not None
    assert output.usage.output_tokens == 5 + 1
    assert len(model_call.response["responses"]) == 2


def _streamed_text(events: list[StreamEvent]) -> str:
    """The text an accumulating stream consumer ends with."""
    text = ""
    for event in events:
        if isinstance(event, StreamRetryEvent):
            text = ""
        elif isinstance(event, StreamTextEvent):
            text += event.text
    return text


@pytest.mark.anyio
@pytest.mark.parametrize("finished", [False, True], ids=["cut-off", "finished"])
async def test_stream_with_trailing_metadata_chunk(finished: bool) -> None:
    """A last chunk with only usage neither hides a finish nor a cut-off stream."""
    usage_only = _with_usage(GenerateContentResponse(), 10, 2, 3)
    first_leg = [
        _chunk(
            [Part(text="kept")],
            FinishReason.STOP if finished else None,
            token=None if finished else b"t1",
        ),
        usage_only,
    ]
    output, _, mock_stream = await _generate_streamed(
        [first_leg]
        if finished
        else [
            first_leg,
            [_chunk([Part(text=" rest")], FinishReason.STOP, usage=(20, 1, 0))],
        ]
    )

    assert mock_stream.call_count == (1 if finished else 2)
    assert output.completion == ("kept" if finished else "kept rest")
    assert output.stop_reason == "stop"
    # the trailing usage is the first leg's, at its checkpoint when cut off
    assert output.usage is not None
    assert output.usage.output_tokens == (5 if finished else 5 + 1)
    assert output.input_context_tokens == 10


@pytest.mark.anyio
@pytest.mark.parametrize("usage_at", ["before", "on", "after"])
async def test_cut_off_stream_usage_at_its_checkpoint(usage_at: str) -> None:
    """A cut-off leg is billed its usage at the checkpoint, not after it.

    The usage can come on a chunk before the checkpoint's own chunk, on it, or
    on a metadata-only chunk right after it. Usage after a later part is not
    the checkpoint's.
    """
    checkpoint_usage = (10, 5, 0)
    first_leg = [
        _chunk(
            [Part(text="kept")],
            usage=checkpoint_usage if usage_at == "before" else None,
        ),
        _chunk(None, token=b"t1", usage=checkpoint_usage if usage_at == "on" else None),
        *(
            [_with_usage(GenerateContentResponse(), *checkpoint_usage)]
            if usage_at == "after"
            else []
        ),
        _chunk([Part(text=" lost")], usage=(10, 9, 0)),
    ]
    output, _, mock_stream = await _generate_streamed(
        [
            first_leg,
            [_chunk([Part(text=" rest")], FinishReason.STOP, usage=(20, 1, 0))],
        ]
    )

    assert mock_stream.call_count == 2
    assert output.completion == "kept rest"
    assert output.usage is not None
    assert output.usage.output_tokens == 5 + 1
    assert output.input_context_tokens == 10


@pytest.mark.anyio
async def test_cut_off_stream_usage_first_reported_after_its_checkpoint() -> None:
    """Usage first reported on discarded output still gives the prompt.

    The request keeps its prompt and context size, but not the discarded
    output.
    """
    output, _, mock_stream = await _generate_streamed(
        [
            [
                _chunk([Part(text="kept")]),
                _chunk(None, token=b"t1"),
                _chunk([Part(text=" lost")], usage=(10, 9, 0)),
            ],
            [_chunk([Part(text=" rest")], FinishReason.STOP, usage=(20, 1, 0))],
        ]
    )

    assert mock_stream.call_count == 2
    assert output.completion == "kept rest"
    assert output.usage is not None
    assert output.usage.input_tokens == 9 + 19
    assert output.usage.output_tokens == 1
    assert output.input_context_tokens == 10


@pytest.mark.anyio
@pytest.mark.parametrize("dropped", [False, True], ids=["eof", "transport-error"])
async def test_reconnect_without_checkpoint_keeps_its_usage(dropped: bool) -> None:
    """A reconnect that reports usage but no checkpoint or part is billed.

    The SDK sends it again from the same token; its usage is counted, as the
    SDK's own usage total counts it.
    """

    async def metadata_only() -> Any:
        yield _with_usage(GenerateContentResponse(), 20, 0, 0)
        if dropped:
            raise aiohttp.ServerDisconnectedError()

    mock_stream = AsyncMock(
        side_effect=[
            _leg_chunks([_chunk([Part(text="kept")], token=b"t1", usage=(10, 2, 0))]),
            metadata_only(),
            _leg_chunks(
                [_chunk([Part(text=" rest")], FinishReason.STOP, usage=(20, 1, 0))]
            ),
        ]
    )
    mock_client = _create_mock_google_client(AsyncMock())
    mock_client.aio.models.generate_content_stream = mock_stream
    output, model_call = await _generate_with_client(
        mock_client, model_args=dict(streaming=True)
    )

    tokens = [c.kwargs["config"].continuation_token for c in mock_stream.call_args_list]
    assert tokens == [None, b"t1", b"t1"]
    assert output.completion == "kept rest"
    assert output.usage is not None
    # each request's prompt (10, 20, 20) less its 1 cached token
    assert output.usage.input_tokens == 9 + 19 + 19
    assert output.usage.output_tokens == 2 + 1
    assert output.input_context_tokens == 10
    responses = model_call.response["responses"]
    assert len(responses) == 3
    assert responses[1]["usageMetadata"]["promptTokenCount"] == 20


@pytest.mark.anyio
async def test_dropped_stream_resumes_from_its_checkpoint() -> None:
    """A stream that raises a transport error after a checkpoint is resumed."""

    async def dropped() -> Any:
        yield _chunk([Part(text="kept")], token=b"t1", usage=(10, 2, 3))
        yield _chunk([Part(text=" lost")])
        raise aiohttp.ServerDisconnectedError()

    mock_stream = AsyncMock(
        side_effect=[
            dropped(),
            _leg_chunks([_chunk([Part(text=" rest")], FinishReason.STOP)]),
        ]
    )
    mock_client = _create_mock_google_client(AsyncMock())
    mock_client.aio.models.generate_content_stream = mock_stream
    output, model_call = await _generate_with_client(
        mock_client, model_args=dict(streaming=True)
    )

    tokens = [c.kwargs["config"].continuation_token for c in mock_stream.call_args_list]
    assert tokens == [None, b"t1"]
    # every request is sent with the SDK's own continuation turned off
    assert all(
        c.kwargs["config"].automatic_continuation is False
        for c in mock_stream.call_args_list
    )
    assert output.completion == "kept rest"
    assert len(model_call.response["responses"]) == 2


def _capture_model_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Collect the model calls the Google provider creates."""
    import inspect_ai.model._providers.google as google_module
    from inspect_ai.log._samples import set_active_model_event_call as create

    calls: list[Any] = []

    def capture(*args: Any, **kwargs: Any) -> Any:
        call = create(*args, **kwargs)
        calls.append(call)
        return call

    monkeypatch.setattr(google_module, "set_active_model_event_call", capture)
    return calls


def _timed_requests(
    case: str,
) -> list[tuple[list[tuple[int, int, int]], GenerateContentResponse]]:
    """Each request: its attempts as (seconds until the response, status, seconds of backoff after it), and its response."""
    return {
        "single": [([(100, 200, 0)], _leg([Part(text="a")], FinishReason.STOP))],
        "continued": [
            ([(100, 200, 0)], _leg([Part(text="a")], FinishReason.CONTINUATION, b"t1")),
            ([(10, 200, 0)], _leg([Part(text="b")], FinishReason.STOP)),
        ],
        "retried-then-continued": [
            (
                [(4, 429, 6), (100, 200, 0)],
                _leg([Part(text="a")], FinishReason.CONTINUATION, b"t1"),
            ),
            ([(10, 200, 0)], _leg([Part(text="b")], FinishReason.STOP)),
        ],
        "malformed-then-continued": [
            ([(100, 200, 0)], _leg([], FinishReason.MALFORMED_FUNCTION_CALL)),
            ([(10, 200, 0)], _leg([Part(text="a")], FinishReason.CONTINUATION, b"t1")),
            ([(5, 200, 0)], _leg([Part(text="b")], FinishReason.STOP)),
        ],
    }[case]


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
@pytest.mark.parametrize(
    ("case", "seconds", "retries"),
    [
        ("single", 100, 0),
        ("continued", 110, 0),
        ("retried-then-continued", 110, 1),
        ("malformed-then-continued", 115, 0),
    ],
)
async def test_continuation_request_time_and_retries(
    case: str,
    seconds: float,
    retries: int,
    streaming: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each request of a call counts its time, and only real retries count as retries.

    A request's time runs from its last attempt, so an SDK's failed attempt
    and backoff are left out. A continuation (or a malformed function call
    retry) is a new request, not an HTTP retry.
    """
    import inspect_ai.model._providers.util.hooks as hooks_module

    clock = [0.0]
    monkeypatch.setattr(
        hooks_module, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    reported: list[Any] = []
    monkeypatch.setattr(
        hooks_module, "report_http_retry", lambda **kwargs: reported.append(kwargs)
    )
    calls = _capture_model_calls(monkeypatch)
    http_client = SimpleNamespace(event_hooks={"request": [], "response": []})
    requests = iter(_timed_requests(case))

    async def send(config: GenerateContentConfig) -> GenerateContentResponse:
        attempts, response = next(requests)
        assert config.http_options and config.http_options.headers
        headers = dict(config.http_options.headers)
        request = SimpleNamespace(method="POST", url="u", headers=headers)
        for seconds_to_response, status, backoff in attempts:
            for hook in http_client.event_hooks["request"]:
                await hook(request)
            clock[0] += seconds_to_response
            for hook in http_client.event_hooks["response"]:
                await hook(
                    SimpleNamespace(
                        request=request,
                        status_code=status,
                        http_version="HTTP/1.1",
                        reason_phrase="",
                        headers={},
                    )
                )
            clock[0] += backoff
        return response

    async def plain(**kwargs: Any) -> GenerateContentResponse:
        return await send(kwargs["config"])

    async def streamed(**kwargs: Any) -> Any:
        return _leg_chunks([await send(kwargs["config"])])

    mock_client = _create_mock_google_client(AsyncMock(side_effect=plain))
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=streamed)
    mock_client._api_client._async_httpx_client = http_client
    await _generate_with_client(mock_client, model_args=dict(streaming=streaming))

    [model_call] = calls
    assert model_call.time == seconds
    assert len(reported) == retries


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True], ids=["plain", "streamed"])
async def test_continuation_without_token_is_not_continued(streaming: bool) -> None:
    """A CONTINUATION without a token is returned as cut at max_tokens, with a warning."""
    response = _chunk([Part(text="partial")], FinishReason.CONTINUATION)
    with patch("inspect_ai.model._providers.google.warn_once") as warn:
        if streaming:
            output, _, mock_request = await _generate_streamed([[response]])
        else:
            output, _, mock_request = await _generate_with_legs([response])

    assert mock_request.call_count == 1
    assert output.stop_reason == "max_tokens"
    [call] = warn.call_args_list
    assert "without a continuation token" in call.args[1]


@pytest.mark.anyio
@pytest.mark.parametrize("arrived", [2, 1])
async def test_continuation_with_several_candidates_is_not_continued(
    arrived: int,
) -> None:
    """A request for several candidates is not continued, however many arrive.

    The CONTINUATION candidates are returned as cut at max_tokens.
    """
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(role="model", parts=[Part(text=f"partial {i}")]),
                finish_reason=FinishReason.CONTINUATION,
                continuation_token=b"t1",
                index=i,
            )
            for i in range(arrived)
        ]
    )
    mock_generate = AsyncMock(side_effect=[response])
    output, _ = await _generate_with_client(
        _create_mock_google_client(mock_generate),
        config=GenerateConfig(num_choices=2),
    )

    assert mock_generate.call_count == 1
    assert [c.stop_reason for c in output.choices] == ["max_tokens"] * arrived


def _candidates_chunk(
    texts: list[str],
    finish_reason: FinishReason | None = None,
    token: bytes | None = None,
) -> GenerateContentResponse:
    """A streamed chunk with one candidate per text, the token on the first."""
    return GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(role="model", parts=[Part(text=text)]),
                finish_reason=finish_reason,
                continuation_token=token if i == 0 else None,
                index=i,
            )
            for i, text in enumerate(texts)
        ]
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("requested", "arrived"),
    [(1, 1), (2, 2), (2, 1)],
    ids=["one", "several", "several-requested-one-arrived"],
)
@pytest.mark.parametrize("ending", ["eof", "dropped", "continuation"])
async def test_streamed_continuation_with_several_candidates_is_not_resumed(
    ending: str, requested: int, arrived: int
) -> None:
    """A stream for several candidates is not resumed, as one for one is.

    With several requested, however many arrive, a stream that drops raises
    its error, one that ends early returns what arrived (nothing trimmed),
    and CONTINUATION returns the candidates cut at max_tokens. One requested
    candidate resumes in each case.
    """
    texts = ["a", "b"][:arrived]

    async def first_leg() -> Any:
        if ending == "continuation":
            yield _candidates_chunk(texts, FinishReason.CONTINUATION, b"t1")
            return
        yield _candidates_chunk(texts, token=b"t1")
        yield _candidates_chunk([" more"] * arrived)
        if ending == "dropped":
            raise aiohttp.ServerDisconnectedError()

    mock_stream = AsyncMock(
        side_effect=[
            first_leg(),
            _leg_chunks([_chunk([Part(text=" rest")], FinishReason.STOP)]),
        ]
    )
    mock_client = _create_mock_google_client(AsyncMock())
    mock_client.aio.models.generate_content_stream = mock_stream

    async def generate() -> ModelOutput:
        output, _ = await _generate_with_client(
            mock_client,
            model_args=dict(streaming=True),
            config=GenerateConfig(num_choices=requested),
        )
        return output

    if requested == 1:
        output = await generate()
        assert mock_stream.call_count == 2
        assert output.completion == "a rest"
        assert output.stop_reason == "stop"
    elif ending == "dropped":
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await generate()
        assert mock_stream.call_count == 1
    else:
        output = await generate()
        assert mock_stream.call_count == 1
        if ending == "eof":
            # untrimmed, and with no finish reason read as STOP, as before
            # continuations were handled
            assert [c.message.text for c in output.choices] == [
                f"{text} more" for text in texts
            ]
            assert [c.stop_reason for c in output.choices] == ["stop"] * arrived
        else:
            assert [c.message.text for c in output.choices] == texts
            assert [c.stop_reason for c in output.choices] == ["max_tokens"] * arrived


def test_batch_request_dict_omits_automatic_continuation() -> None:
    """automatic_continuation is an SDK setting, not part of the REST request."""
    from inspect_ai.model._providers._google_batch import batch_request_dict

    config = GenerateContentConfig(temperature=0.5, automatic_continuation=False)
    request = batch_request_dict(
        config, [Content(role="user", parts=[Part.from_text(text="hi")])]
    )

    assert request["generation_config"] == {"temperature": 0.5}


@pytest.mark.anyio
async def test_batch_continuation_is_not_continued() -> None:
    """The batch API has no continuations, so a batch response is never continued."""
    mock_client = _create_mock_google_client(AsyncMock())
    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.5-pro", base_url=None, api_key="test-key"
        )
        batcher = MagicMock()
        batcher.generate_for_request = AsyncMock(
            return_value=_leg([Part(text="partial")], FinishReason.CONTINUATION, b"t1")
        )
        api._batcher = batcher
        result = await api.generate(
            input=[ChatMessageUser(content="Think hard")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    assert isinstance(result, tuple)
    output = result[0]
    assert isinstance(output, ModelOutput)
    assert batcher.generate_for_request.call_count == 1
    assert output.completion == "partial"
    assert output.stop_reason == "max_tokens"


# Tests for count_tokens with unpaired tool messages


@pytest.mark.anyio
@skip_if_no_google
async def test_google_count_tokens_single_tool_call() -> None:
    """Test counting tokens for a single assistant message with one tool call."""
    from inspect_ai.model import get_model

    model = get_model("google/gemini-3.1-flash-lite")

    # Create an assistant message with a single tool call (no tool result)
    assistant_msg = ChatMessageAssistant(
        content="I'll help you with that.",
        tool_calls=[
            ToolCall(
                id="call_test_123",
                function="test_function",
                arguments={"arg1": "value1"},
            )
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@pytest.mark.anyio
@skip_if_no_google
async def test_google_count_tokens_multiple_tool_calls() -> None:
    """Test counting tokens for a single assistant message with multiple tool calls."""
    from inspect_ai.model import get_model

    model = get_model("google/gemini-3.1-flash-lite")

    # Create an assistant message with multiple tool calls (no tool results)
    assistant_msg = ChatMessageAssistant(
        content="I'll run multiple tools.",
        tool_calls=[
            ToolCall(
                id="call_test_abc",
                function="function_a",
                arguments={"x": 1},
            ),
            ToolCall(
                id="call_test_def",
                function="function_b",
                arguments={"y": 2},
            ),
            ToolCall(
                id="call_test_ghi",
                function="function_c",
                arguments={"z": 3},
            ),
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@pytest.mark.anyio
@skip_if_no_google
async def test_google_count_tokens_single_tool_result() -> None:
    """Test counting tokens for a single tool result message (no preceding tool use)."""
    from inspect_ai.model import get_model

    model = get_model("google/gemini-3.1-flash-lite")

    # Create a tool result message without a preceding assistant message
    tool_msg = ChatMessageTool(
        content="Tool result content here",
        tool_call_id="call_test_xyz",
        function="some_function",
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([tool_msg])
    assert token_count > 0


async def _collect_part_deltas(part: Part) -> list[StreamEvent]:
    """Run _report_stream_part_delta under an observer, returning its deltas."""
    events: list[StreamEvent] = []

    async def collect(event: StreamEvent) -> None:
        events.append(event)

    observer = ModelStreamObserver(model="google/test", on_stream=collect)
    with model_stream_observer(observer):
        await _report_stream_part_delta(part)
    return events


async def test_report_stream_part_delta_text() -> None:
    events = await _collect_part_deltas(Part(text="hello"))
    assert events == [StreamTextEvent(text="hello")]


async def test_report_stream_part_delta_thought() -> None:
    events = await _collect_part_deltas(Part(text="thinking", thought=True))
    assert events == [StreamReasoningEvent(reasoning="thinking")]


async def test_report_stream_part_delta_function_call() -> None:
    events = await _collect_part_deltas(
        Part(function_call=FunctionCall(id="c1", name="add", args={"x": 1}))
    )
    assert events == [
        StreamToolCallEvent(id="c1", function="add", arguments='{"x": 1}')
    ]


async def test_report_stream_part_delta_function_call_without_args() -> None:
    events = await _collect_part_deltas(Part(function_call=FunctionCall(name="ping")))
    assert events == [StreamToolCallEvent(id=None, function="ping", arguments="")]


async def test_report_stream_part_delta_other_parts_report_nothing() -> None:
    # empty text and non-content parts produce no delta (the progress
    # heartbeat comes from the per-chunk report, not from here)
    assert await _collect_part_deltas(Part()) == []
    assert await _collect_part_deltas(Part(text="")) == []
    assert await _collect_part_deltas(Part(text="", thought=True)) == []


async def test_report_stream_part_delta_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer no delta is constructed or reported.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    import inspect_ai.model._providers.google as google_module

    async def fail(delta: object) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(google_module, "report_model_stream_delta", fail)
    observer = ModelStreamObserver(model="google/test", on_stream=None)
    with model_stream_observer(observer):
        await _report_stream_part_delta(Part(text="hello"))
        await _report_stream_part_delta(
            Part(function_call=FunctionCall(id="c1", name="add", args={"x": 1}))
        )


@skip_if_no_google
def test_google_streaming_basic():
    """Test basic streaming with simple prompt."""
    result = eval(
        Task(
            dataset=[Sample(input="Say hello in one sentence", target="hello")],
            scorer=includes(),
        ),
        model="google/gemini-3.1-flash-lite",
        model_args=dict(streaming=True),
    )[0]

    assert result.status == "success"
    assert result.samples
    assert result.samples[0].output


@skip_if_no_google
def test_google_streaming_with_tools():
    """Test streaming with tool calls."""

    @tool
    def add(x: int, y: int) -> int:
        """
        Add two numbers.

        Args:
            x: The first number to add.
            y: The second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    result = eval(
        Task(
            dataset=[Sample(input="What is 5 + 3?", target="8")],
            solver=use_tools([add]),
            scorer=includes(),
        ),
        model="google/gemini-3.1-flash-lite",
        model_args=dict(streaming=True),
    )[0]

    assert result.status == "success"


@skip_if_no_google
def test_google_streaming_large_output():
    """Test streaming with large max_tokens."""
    result = eval(
        Task(
            dataset=[
                Sample(
                    input="Write a detailed story about space exploration",
                    target="space",
                )
            ],
            scorer=includes(),
        ),
        model="google/gemini-3.1-flash-lite",
        model_args=dict(streaming=True),
        max_tokens=4096,
    )[0]

    assert result.status == "success"
    assert result.samples[0].output


@skip_if_no_google
def test_google_streaming_captures_reasoning_summaries():
    """Test that streaming DOES capture reasoning summaries from Gemini 3 thinking."""
    result = eval(
        Task(
            dataset=[
                Sample(
                    input="What is the sum of the first 50 prime numbers?",
                    target="5117",
                )
            ],
            scorer=includes(),
        ),
        model="google/gemini-3.1-pro-preview",
        model_args=dict(streaming=True),
    )[0]

    assert result.status == "success"

    # Find assistant messages with reasoning
    reasoning_blocks = []
    for msg in result.samples[0].messages:
        if msg.role == "assistant":
            reasoning_blocks.extend(
                [c for c in msg.content if isinstance(c, ContentReasoning)]
            )

    # Should have at least one reasoning block with a summary
    assert len(reasoning_blocks) > 0, "Expected at least one ContentReasoning block"
    assert any(r.summary and len(r.summary) > 0 for r in reasoning_blocks), (
        "Expected at least one reasoning block with summary text"
    )
    assert all(r.redacted for r in reasoning_blocks), (
        "All reasoning blocks should be redacted"
    )


class _AlarmTimeout(Exception):
    pass


def _alarm_handler(signum: int, frame: object) -> None:
    raise _AlarmTimeout


@skip_if_no_google
def test_google_batch_with_thinking_model():
    """Batch submission should not reject thinking_config (issue #3257).

    Bug: eval() raises immediately with 'no such field: thinking_config'.
    Fixed: eval() blocks on batch completion, alarm fires after 4s, test passes.
    """
    import signal

    from inspect_ai.model._generate_config import BatchConfig

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(4)
    try:
        eval(
            Task(
                dataset=[Sample(input="What is 2+2?", target="4")],
                scorer=includes(),
            ),
            model="google/gemini-2.5-flash",
            batch=BatchConfig(size=1, send_delay=0, tick=0.1),
            fail_on_error=True,
        )
    except _AlarmTimeout:
        pass  # submission succeeded, batch just didn't complete
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _make_batcher_and_batch(job_state: JobState) -> tuple:
    from datetime import datetime, timezone

    from google.genai.types import BatchJob, BatchJobDestination

    from inspect_ai.model._generate_config import BatchConfig
    from inspect_ai.model._providers._google_batch import GoogleBatcher
    from inspect_ai.model._providers.util.batch import Batch, BatchRequest
    from inspect_ai.model._retry import model_retry_config

    client = MagicMock()
    mock_batch_job = BatchJob(
        name="batch-123",
        state=job_state,
        create_time=datetime.now(tz=timezone.utc),
        dest=BatchJobDestination(file_name="files/result-123"),
    )
    client.aio.batches.get = AsyncMock(return_value=mock_batch_job)

    batcher = GoogleBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
        model_name="gemini-2.0-flash",
    )

    send_stream = MagicMock()
    req: BatchRequest[Any] = BatchRequest(
        request={},
        result_stream=send_stream,
        custom_id="req-1",
    )
    batch = Batch(id="batch-123", requests={"req-1": req})
    return batcher, batch


def test_google_batch_result_line_tolerates_unknown_rest_fields() -> None:
    """Batch result parsing must not fail on REST fields the SDK model lacks.

    Google's batch results carry ``usageMetadata.serviceTier``, which no
    released google-genai models; validating the raw dict with
    ``extra="forbid"`` rejected every result (issue #5100 follow-on).
    """
    from google.genai.types import GenerateContentResponse
    from pydantic import JsonValue

    from inspect_ai.model._generate_config import BatchConfig
    from inspect_ai.model._providers._google_batch import GoogleBatcher
    from inspect_ai.model._retry import model_retry_config

    batcher = GoogleBatcher(
        client=MagicMock(),
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
        model_name="gemini-2.5-flash-lite",
    )
    line: dict[str, JsonValue] = {
        "key": "req-1",
        "response": {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Blue"}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 2,
                "totalTokenCount": 22,
                "serviceTier": "SERVICE_TIER_STANDARD",
            },
            "modelVersion": "gemini-2.5-flash-lite",
            "responseId": "abc123",
        },
    }

    key, result = batcher._parse_jsonl_line(line)

    assert key == "req-1"
    assert isinstance(result, GenerateContentResponse)
    assert result.text == "Blue"
    assert result.usage_metadata is not None
    assert result.usage_metadata.total_token_count == 22


def test_batch_request_dict_wraps_system_instruction() -> None:
    from google.genai.types import Content, GenerateContentConfig, Part

    from inspect_ai.model._providers._google_batch import batch_request_dict

    config = GenerateContentConfig(
        system_instruction=["You are helpful.", "Be concise."]
    )
    request = batch_request_dict(
        config, [Content(role="user", parts=[Part.from_text(text="hi")])]
    )

    assert request["system_instruction"] == {
        "parts": [{"text": "You are helpful."}, {"text": "Be concise."}],
    }
    assert request["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
    ]

    config_parts = GenerateContentConfig(
        system_instruction=[Part.from_text(text="You are helpful.")]
    )
    request_parts = batch_request_dict(
        config_parts, [Content(role="user", parts=[Part.from_text(text="hi")])]
    )
    assert request_parts["system_instruction"] == {
        "parts": [{"text": "You are helpful."}],
    }


@pytest.mark.parametrize(
    "state,expect_completed,expect_failed,expect_completion_info",
    [
        pytest.param("JOB_STATE_PENDING", False, False, False, id="pending"),
        pytest.param("JOB_STATE_RUNNING", False, False, False, id="running"),
        pytest.param("JOB_STATE_SUCCEEDED", True, False, True, id="succeeded"),
        pytest.param(
            "JOB_STATE_PARTIALLY_SUCCEEDED",
            True,
            False,
            True,
            id="partially-succeeded",
        ),
        pytest.param("JOB_STATE_FAILED", False, True, False, id="failed"),
        pytest.param("JOB_STATE_CANCELLED", False, True, False, id="cancelled"),
        pytest.param("JOB_STATE_EXPIRED", False, True, False, id="expired"),
    ],
)
@pytest.mark.anyio
async def test_check_batch_terminal_states(
    state: str,
    expect_completed: bool,
    expect_failed: bool,
    expect_completion_info: bool,
) -> None:
    """_check_batch must map all terminal JobStates so polling terminates."""
    job_state = getattr(JobState, state)
    batcher, batch = _make_batcher_and_batch(job_state)
    result = await batcher._check_batch(batch)

    if expect_completed:
        assert result.completed_count > 0, f"{state} should report completed"
    if expect_failed:
        assert result.failed_count > 0, f"{state} should report failed"
    if not expect_completed and not expect_failed:
        assert result.completed_count == 0 and result.failed_count == 0
    assert (result.completion_info is not None) == expect_completion_info


async def test_image_generation_round_trip():
    """Test that an image generated by Google round-trips through assistant message → API input."""
    # Step 1: Simulate model returning an image via inline_data
    image_bytes = b"\x89PNG\r\n\x1a\nfake_png_data"
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(text="Here is your image:"),
                Part(inline_data=Blob(mime_type="image/png", data=image_bytes)),
            ],
        ),
        finish_reason=FinishReason.STOP,
    )
    choice = completion_choice_from_candidate("test-model", candidate)
    msg_content = choice.message.content
    assert isinstance(msg_content, list)

    # Verify we got text + image
    texts = [c for c in msg_content if isinstance(c, ContentText)]
    images = [c for c in msg_content if isinstance(c, ContentImage)]
    assert len(texts) == 1
    assert len(images) == 1
    assert images[0].image.startswith("data:image/png;base64,")

    # Step 2: Build assistant message and convert back to Google Content
    assistant_msg = ChatMessageAssistant(
        content=msg_content,
        model="test-model",
        source="generate",
    )
    google_content = await content(MagicMock(), assistant_msg)

    # Verify the round-tripped content has both parts
    assert google_content.role == "model"
    assert len(google_content.parts) == 2

    # First part should be text
    assert google_content.parts[0].text == "Here is your image:"

    # Second part should be the image as inline_data with the original bytes
    blob = google_content.parts[1].inline_data
    assert blob is not None
    assert blob.mime_type == "image/png"
    assert blob.data == image_bytes


async def test_image_only_round_trip():
    """Test round-trip for an image-only response (no text)."""
    image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
    candidate = Candidate(
        content=Content(
            role="model",
            parts=[
                Part(inline_data=Blob(mime_type="image/jpeg", data=image_bytes)),
            ],
        ),
        finish_reason=FinishReason.STOP,
    )
    choice = completion_choice_from_candidate("test-model", candidate)
    msg_content = choice.message.content
    assert isinstance(msg_content, list)
    assert len(msg_content) == 1
    assert isinstance(msg_content[0], ContentImage)

    # Round-trip through assistant message
    assistant_msg = ChatMessageAssistant(
        content=msg_content,
        model="test-model",
        source="generate",
    )
    google_content = await content(MagicMock(), assistant_msg)

    assert google_content.role == "model"
    assert len(google_content.parts) == 1
    blob = google_content.parts[0].inline_data
    assert blob is not None
    assert blob.mime_type == "image/jpeg"
    assert blob.data == image_bytes


async def test_image_in_user_follow_up():
    """Test that an image from a model response can be sent back as user input."""
    # Model generates an image
    image_bytes = b"\x89PNG\r\n\x1a\ntest_image"
    b64 = base64.b64encode(image_bytes).decode()
    data_uri = f"data:image/png;base64,{b64}"

    # User sends the image back in a follow-up message
    user_msg = ChatMessageUser(
        content=[
            ContentText(text="What's in this image?"),
            ContentImage(image=data_uri),
        ]
    )
    google_content = await content(MagicMock(), user_msg)

    assert google_content.role == "user"
    assert len(google_content.parts) == 2

    # First part is text
    assert google_content.parts[0].text == "What's in this image?"

    # Second part is the image data
    blob = google_content.parts[1].inline_data
    assert blob is not None
    assert blob.mime_type == "image/png"
    assert blob.data == image_bytes


@pytest.mark.parametrize(
    "exception_factory",
    [
        lambda: aiohttp.ClientOSError(103, "Software caused connection abort"),
        lambda: aiohttp.ServerDisconnectedError(),
        lambda: aiohttp.ClientConnectorError(MagicMock(), OSError("connect failed")),
        lambda: asyncio.TimeoutError(),
    ],
)
def test_should_retry_aiohttp_transport_errors(exception_factory):
    from inspect_ai.model._model import RetryDecision

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
    )

    decision = api.should_retry(exception_factory())

    assert isinstance(decision, RetryDecision)
    assert decision.retry
    assert decision.kind == "transient"


def test_should_retry_unrelated_error_not_retried():
    from inspect_ai.model._model import RetryDecision

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash", base_url=None, api_key="test-key"
    )

    decision = api.should_retry(ValueError("bad input"))

    assert isinstance(decision, RetryDecision)
    assert not decision.retry


def test_usage_metadata_folds_thoughts_into_output_tokens():
    from google.genai.types import GenerateContentResponseUsageMetadata

    from inspect_ai.model._providers.google import usage_metadata_to_model_usage

    usage = usage_metadata_to_model_usage(
        GenerateContentResponseUsageMetadata(
            prompt_token_count=100,
            cached_content_token_count=40,
            candidates_token_count=20,
            thoughts_token_count=30,
            total_token_count=150,
        )
    )

    assert usage is not None
    assert usage.input_tokens == 60
    assert usage.input_tokens_cache_read == 40
    # thoughts fold into output (OpenAI/Anthropic convention), with
    # reasoning_tokens as the detail subset
    assert usage.output_tokens == 50
    assert usage.reasoning_tokens == 30
    assert usage.total_tokens == 150


def test_usage_metadata_without_thoughts():
    from google.genai.types import GenerateContentResponseUsageMetadata

    from inspect_ai.model._providers.google import usage_metadata_to_model_usage

    usage = usage_metadata_to_model_usage(
        GenerateContentResponseUsageMetadata(
            prompt_token_count=10,
            candidates_token_count=5,
            total_token_count=15,
        )
    )

    assert usage is not None
    assert usage.output_tokens == 5
    assert usage.reasoning_tokens == 0


# ---- OAuth / ADC credentials for the Gemini Developer API ----


class _FakeCreds:
    """Minimal google-auth credentials stand-in for OAuth tests.

    Mirrors google-auth semantics: `valid` derives from the token and an
    expired flag, so invalidating the token (as `initialize()` does) makes
    the credentials refreshable.
    """

    def __init__(self, token: str = "tok-1", valid: bool = True) -> None:
        self.token: str | None = token
        self.expired = not valid
        self.refresh_calls = 0

    @property
    def valid(self) -> bool:
        return self.token is not None and not self.expired

    def refresh(self, request: Any) -> None:
        self.refresh_calls += 1
        self.expired = False
        self.token = f"tok-refreshed-{self.refresh_calls}"


def _adc_api(fake: _FakeCreds, **model_args: Any) -> GoogleGenAIAPI:
    """Construct a dev-endpoint OAuth model backed by `fake` ADC credentials."""
    with patch("google.auth.default", return_value=(fake, None)):
        return GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key=None,
            use_adc=True,
            **model_args,
        )


@pytest.mark.anyio
async def test_google_oauth_headers_injected() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(_FakeCreds(token="tok-1"), quota_project_id="proj-x")
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-1"
    assert headers["x-goog-user-project"] == "proj-x"
    assert client.call_args.kwargs["api_key"] == OAUTH_PLACEHOLDER_API_KEY


@pytest.mark.anyio
async def test_google_oauth_quota_project_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "proj-env")
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(_FakeCreds(token="tok-adc"))
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-adc"
    assert headers["x-goog-user-project"] == "proj-env"


@pytest.mark.anyio
async def test_google_oauth_quota_header_omitted_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_QUOTA_PROJECT", raising=False)
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(_FakeCreds())
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    headers = _client_http_options(client).headers
    assert headers is not None
    assert "x-goog-user-project" not in headers


@pytest.mark.anyio
async def test_google_oauth_refreshes_when_invalid() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    creds = _FakeCreds(valid=False)
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(creds)
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    assert creds.refresh_calls >= 1
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == f"Bearer tok-refreshed-{creds.refresh_calls}"


@pytest.mark.anyio
async def test_google_oauth_concurrent_refresh_single_flight() -> None:
    creds = _FakeCreds(valid=False)
    api = _adc_api(creds)
    await tg_collect([api._ensure_oauth_token for _ in range(5)])
    assert creds.refresh_calls == 1
    assert creds.valid


@pytest.mark.anyio
async def test_google_oauth_refresh_cancellable() -> None:
    """A cancelled waiter must not be shielded until the refresh thread finishes."""

    class _SlowCreds(_FakeCreds):
        def refresh(self, request: Any) -> None:
            time.sleep(2)
            super().refresh(request)

    creds = _SlowCreds(valid=False)
    api = _adc_api(creds)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.1):
            await api._ensure_oauth_token()
    assert time.monotonic() - start < 1.0


@pytest.mark.anyio
async def test_google_use_adc_takes_precedence_over_api_key() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    fake = _FakeCreds(token="tok-adc")
    with (
        patch(
            "inspect_ai.model._providers.google.Client", return_value=mock_client
        ) as client,
        patch("google.auth.default", return_value=(fake, None)),
    ):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="explicit-key",
            use_adc=True,
        )
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    assert api._oauth is True
    assert client.call_args.kwargs["api_key"] == OAUTH_PLACEHOLDER_API_KEY
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-adc"


@pytest.mark.anyio
async def test_google_use_adc_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_USE_ADC", "true")
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    fake = _FakeCreds(token="tok-env")
    with (
        patch(
            "inspect_ai.model._providers.google.Client", return_value=mock_client
        ) as client,
        patch("google.auth.default", return_value=(fake, None)),
    ):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key=None,
        )
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    assert api._oauth is True
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-env"
    assert client.call_args.kwargs["api_key"] == OAUTH_PLACEHOLDER_API_KEY


def test_google_use_adc_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_USE_ADC", "true")
    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="test-key",
        use_adc=False,
    )
    assert api._oauth is False


@pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
def test_google_use_adc_env_var_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GOOGLE_USE_ADC", value)
    with patch("google.auth.default", return_value=(_FakeCreds(), None)):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key=None,
        )
    assert api._oauth is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", ""])
def test_google_use_adc_env_var_falsy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GOOGLE_USE_ADC", value)
    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="test-key",
    )
    assert api._oauth is False


def test_google_no_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_USE_ADC", raising=False)
    with pytest.raises(PrerequisiteError, match="GOOGLE_API_KEY"):
        GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key=None,
        )


@pytest.mark.anyio
async def test_google_oauth_args_not_forwarded_to_client() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(
            _FakeCreds(),
            quota_project_id="p",
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    for key in ("use_adc", "scopes", "quota_project_id"):
        assert key not in client.call_args.kwargs
        assert key not in api.model_args


def test_google_oauth_initialize_invalidates_token() -> None:
    creds = _FakeCreds(token="tok-0")
    api = _adc_api(creds)
    api.initialize()
    assert creds.token is None
    assert not creds.valid
    assert creds.refresh_calls == 0


@pytest.mark.anyio
async def test_google_oauth_refresh_after_initialize() -> None:
    mock_generate = AsyncMock(return_value=GenerateContentResponse(candidates=[]))
    mock_client = _create_mock_google_client(mock_generate)
    creds = _FakeCreds(token="tok-0")
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(creds)
        # simulate the 401 backstop: before_retry() invalidates via initialize()
        api.initialize()
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )
    assert creds.refresh_calls == 1
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-refreshed-1"


def test_google_oauth_401_retry_classification() -> None:
    err = APIError(401, {"error": {"message": "unauthorized", "code": 401}})
    oauth_api = _adc_api(_FakeCreds())
    decision = oauth_api.should_retry(err)
    assert isinstance(decision, RetryDecision)
    assert decision.retry

    api_key_api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="explicit-key",
    )
    decision = api_key_api.should_retry(err)
    assert isinstance(decision, RetryDecision)
    assert not decision.retry


def test_google_oauth_batch_raises() -> None:
    api = _adc_api(_FakeCreds())
    config = GenerateConfig(batch=BatchConfig(size=1))
    with pytest.raises(NotImplementedError, match="OAuth"):
        api._resolve_batcher(config, api._http_options(config))


@pytest.mark.anyio
async def test_google_oauth_count_tokens_headers() -> None:
    mock_client = _create_mock_google_count_tokens_client()
    with patch(
        "inspect_ai.model._providers.google.Client", return_value=mock_client
    ) as client:
        api = _adc_api(_FakeCreds(token="tok-ct"), quota_project_id="proj")
        await api.count_tokens("Hello")
    headers = _client_http_options(client).headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-ct"
    assert headers["x-goog-user-project"] == "proj"


def test_google_oauth_real_client_excludes_placeholder_api_key() -> None:
    """OAuth requests must not send the SDK's required placeholder as an API key."""
    api = _adc_api(_FakeCreds(token="tok-real"), quota_project_id="proj-real")
    client = api.model_client(api._http_options())
    headers = client._api_client._http_options.headers
    assert headers is not None
    assert headers["Authorization"] == "Bearer tok-real"
    assert headers["x-goog-user-project"] == "proj-real"
    assert "x-goog-api-key" not in headers


def test_google_use_adc_rejected_on_vertex() -> None:
    with pytest.raises(PrerequisiteError, match="use_adc"):
        GoogleGenAIAPI(
            model_name="vertex/gemini-2.0-flash",
            base_url=None,
            api_key=None,
            use_adc=True,
        )


def test_google_credentials_arg_rejected() -> None:
    with pytest.raises(PrerequisiteError, match="credentials"):
        GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key=None,
            credentials=object(),
        )


def test_model_client_reuses_one_ssl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated client construction must not rebuild the SSL context.

    `Client()` is built per generate() call, and genai otherwise creates a default
    context from the CA bundle for each one — a synchronous disk read on the event
    loop, three times per client. Under high sandbox concurrency that blocking work
    starves the sandbox-service RPC consumer.
    """
    import ssl as ssl_module

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    calls = 0
    real = ssl_module.create_default_context

    def counting(*args: Any, **kwargs: Any) -> ssl_module.SSLContext:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ssl_module, "create_default_context", counting)
    monkeypatch.setattr("google.genai._api_client.ssl.create_default_context", counting)

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="x" * 20,
    )
    GoogleGenAIAPI._ssl_context.cache_clear()
    for _ in range(5):
        api.model_client()

    # one build for the whole process, not three per client
    assert calls <= 1, f"rebuilt the SSL context {calls} times across 5 clients"


def test_model_client_reuses_ssl_context_with_client_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge path passes `client_args`, which changed which dict genai reads.

    genai resolves the context with a conditional that, when `client_args` is
    non-empty, never consults `async_client_args` (google/genai/_api_client.py:
    `args.get(verify) if args else None or async_args.get(verify) ...` parses as
    `args.get(v) if args else ((None or async_args.get(v)) if async_args else
    None)`). Seeding only the async dict therefore missed and genai rebuilt the
    context ON the event loop — caught by py-spy on a live run as
    create_default_context under bridge_generate.
    """
    import ssl as ssl_module

    from google.genai.types import HttpOptions

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    calls = 0
    real = ssl_module.create_default_context

    def counting(*args: Any, **kwargs: Any) -> ssl_module.SSLContext:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ssl_module, "create_default_context", counting)
    monkeypatch.setattr("google.genai._api_client.ssl.create_default_context", counting)

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="x" * 20,
    )
    GoogleGenAIAPI._ssl_context.cache_clear()
    for _ in range(5):
        api.model_client(HttpOptions(client_args={"timeout": 30.0}))

    assert calls <= 1, (
        f"rebuilt the SSL context {calls} times across 5 clients with client_args"
    )


def test_model_client_preserves_custom_verify_for_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied CA/SSLContext on `client_args` must reach async requests too.

    genai's SSL-context resolution (`_ensure_httpx_ssl_ctx`) only consults
    `async_client_args` when `client_args` is non-empty, so pre-seeding
    `async_client_args` with the shared default before genai runs would silently
    override a caller-supplied custom verify for async requests while sync
    requests stayed correctly validated against it.
    """
    import ssl as ssl_module
    from typing import Any

    from google.genai._api_client import AsyncHttpxClient
    from google.genai.types import HttpOptions

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    custom_context = ssl_module.create_default_context()

    captured: dict[str, Any] = {}
    real_init = AsyncHttpxClient.__init__

    def capturing_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        real_init(self, **kwargs)

    monkeypatch.setattr(AsyncHttpxClient, "__init__", capturing_init)

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="x" * 20,
    )
    GoogleGenAIAPI._ssl_context.cache_clear()
    api.model_client(HttpOptions(client_args={"verify": custom_context}))

    assert captured["verify"] is custom_context, (
        "async httpx client did not receive the caller-supplied custom verify"
    )


def test_model_client_converts_str_verify_for_aiohttp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied CA-bundle *path* must not reach aiohttp's `ssl` param.

    httpx's `verify` legally accepts a CA-bundle path (the PR's stated contract, e.g.
    `certifi.where()`), but aiohttp's `ssl` param only accepts
    `SSLContext | bool | Fingerprint | None` — `aiohttp.client_reqrep` raises
    `TypeError` on a bare path, so every aiohttp/websocket request would fail before
    sending unless the path is converted into a context first.
    """
    import ssl as ssl_module

    import certifi
    from google.genai._api_client import AsyncHttpxClient
    from google.genai.types import HttpOptions

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    ca_path = str(certifi.where())

    captured: dict[str, Any] = {}
    real_init = AsyncHttpxClient.__init__

    def capturing_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        real_init(self, **kwargs)

    monkeypatch.setattr(AsyncHttpxClient, "__init__", capturing_init)

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="x" * 20,
    )
    GoogleGenAIAPI._ssl_context.cache_clear()
    GoogleGenAIAPI._ssl_context_for_path.cache_clear()
    client = api.model_client(HttpOptions(client_args={"verify": ca_path}))

    # httpx's async client keeps the original path -- that's a legal httpx `verify`.
    assert captured["verify"] == ca_path

    # aiohttp's `ssl` param only accepts SSLContext | bool | Fingerprint | None; the
    # resolved verify value must be converted, not copied verbatim.
    aiohttp_args = client._api_client._async_client_session_request_args
    assert isinstance(aiohttp_args["ssl"], ssl_module.SSLContext), (
        f"aiohttp 'ssl' arg was {aiohttp_args['ssl']!r}, not an SSLContext"
    )


def test_model_client_preserves_verify_false_for_aiohttp() -> None:
    """`verify=False` must reach aiohttp as `ssl=False` unchanged, not converted."""
    from google.genai.types import HttpOptions

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="x" * 20,
    )
    GoogleGenAIAPI._ssl_context.cache_clear()
    client = api.model_client(HttpOptions(client_args={"verify": False}))

    assert client._api_client._async_client_session_request_args["ssl"] is False


class _FakeFiles:
    """Records Files API uploads and serves them back by name."""

    def __init__(self) -> None:
        self.files: dict[str, File] = {}
        self.uploads: list[str] = []
        self.gets: list[str] = []

    def upload(self, *, file: Any, config: dict[str, Any]) -> File:
        name = f"files/{len(self.files)}"
        self.files[name] = File(
            name=name,
            uri=f"https://example.com/{name}",
            mime_type=config["mime_type"],
            state=FileState.ACTIVE,
        )
        self.uploads.append(config["mime_type"])
        return self.files[name]

    def get(self, *, name: str) -> File:
        self.gets.append(name)
        return self.files[name]


class _GoogleFiles(NamedTuple):
    client: Client
    files: _FakeFiles
    db_path: Path


@pytest.fixture
def google_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _GoogleFiles:
    db_path = tmp_path / "google_files.db"
    monkeypatch.setattr(
        google_provider,
        "inspect_kvstore",
        lambda name, max_entries=None: KVStore(db_path.as_posix(), max_entries),
    )
    client = Client(api_key="test-key")
    fake = _FakeFiles()
    monkeypatch.setattr(client, "_files", fake)
    return _GoogleFiles(client, fake, db_path)


def _document(mime_type: str, data: bytes = b"a,b\n1,2\n") -> ContentDocument:
    return ContentDocument(
        document=f"data:{mime_type};base64,{base64.b64encode(data).decode()}"
    )


async def test_google_files_cache_keys_on_mime_type(
    google_files: _GoogleFiles,
) -> None:
    client, fake, _ = google_files
    csv_part = await chat_content_to_part(client, _document("text/csv"))
    text_part = await chat_content_to_part(client, _document("text/plain"))

    assert fake.uploads == ["text/csv", "text/plain"]
    assert csv_part.file_data and text_part.file_data
    assert csv_part.file_data.mime_type == "text/csv"
    assert text_part.file_data.mime_type == "text/plain"
    assert csv_part.file_data.file_uri != text_part.file_data.file_uri


async def test_google_files_cache_reuses_same_bytes_and_mime_type(
    google_files: _GoogleFiles,
) -> None:
    client, fake, _ = google_files
    first = await chat_content_to_part(client, _document("text/csv"))
    second = await chat_content_to_part(client, _document("text/csv"))

    assert fake.uploads == ["text/csv"]
    assert fake.gets == ["files/0"]
    assert first.file_data and second.file_data
    assert first.file_data.file_uri == second.file_data.file_uri
    assert second.file_data.mime_type == "text/csv"


async def test_google_files_cache_ignores_old_format_entries(
    google_files: _GoogleFiles,
) -> None:
    client, fake, db_path = google_files
    data = b"a,b\n1,2\n"
    # an entry written by the previous cache, keyed by the bytes' sha256 only
    old = fake.upload(file=None, config={"mime_type": "text/csv"})
    fake.uploads.clear()
    with KVStore(db_path.as_posix()) as files_db:
        files_db.put(hashlib.sha256(data).hexdigest(), str(old.name))

    part = await chat_content_to_part(client, _document("text/csv", data))

    assert fake.gets == []
    assert fake.uploads == ["text/csv"]
    assert part.file_data and part.file_data.mime_type == "text/csv"
    assert part.file_data.file_uri != old.uri


async def test_google_files_cache_scoped_to_api_key(
    google_files: _GoogleFiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake, db_path = google_files
    await chat_content_to_part(client, _document("text/csv"))
    other_client = Client(api_key="other-key")
    monkeypatch.setattr(other_client, "_files", fake)
    await chat_content_to_part(other_client, _document("text/csv"))

    assert fake.uploads == ["text/csv", "text/csv"]
    assert fake.gets == []
    with KVStore(db_path.as_posix()) as files_db:
        rows = files_db.conn.execute("SELECT key, value FROM kv_store").fetchall()
    assert len(rows) == 2
    stored = " ".join(" ".join(row) for row in rows)
    assert "test-key" not in stored and "other-key" not in stored


@pytest.mark.anyio
async def test_google_output_records_response_id() -> None:
    mock_generate = AsyncMock(
        return_value=GenerateContentResponse(candidates=[], response_id="g-response")
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-2.0-flash",
            base_url=None,
            api_key="test-key",
        )
        result = await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )

    assert isinstance(result, tuple)
    output, _ = result
    assert isinstance(output, ModelOutput)
    assert output.response_id == "g-response"


@pytest.mark.anyio
async def test_google_streamed_response_keeps_response_id() -> None:
    chunks = [
        GenerateContentResponse(
            candidates=[
                Candidate(
                    content=Content(parts=[Part(text=text)], role="model"), index=0
                )
            ],
            response_id="g-stream-response",
        )
        for text in ["hel", "lo"]
    ]

    output, _, _ = await _generate_streamed([chunks])

    assert output.response_id == "g-stream-response"


def test_google_explicit_api_key_overrides_ambient_adc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit API key must win over GOOGLE_USE_ADC's ambient default."""
    monkeypatch.setenv("GOOGLE_USE_ADC", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-key")

    def unexpected_adc_resolution(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail(
            "ambient ADC should not be resolved when an explicit API key is supplied"
        )

    monkeypatch.setattr(
        "inspect_ai.model._providers.google.resolve_google_credentials",
        unexpected_adc_resolution,
    )

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="explicit-key",
    )

    assert api.api_key == "explicit-key"
    assert api._oauth is False


def test_google_ambient_adc_overrides_environment_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient ADC must take precedence over an API key found only in the environment."""
    monkeypatch.setenv("GOOGLE_USE_ADC", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-key")
    credentials = MagicMock()
    monkeypatch.setattr(
        "inspect_ai.model._providers.google.resolve_google_credentials",
        lambda *_args, **_kwargs: credentials,
    )

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key=None,
    )

    assert api._oauth is True
    assert api._credentials is credentials


def test_google_explicit_use_adc_overrides_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit use_adc=true remains authoritative over a supplied API key."""
    monkeypatch.setenv("GOOGLE_USE_ADC", "false")
    credentials = MagicMock()
    monkeypatch.setattr(
        "inspect_ai.model._providers.google.resolve_google_credentials",
        lambda *_args, **_kwargs: credentials,
    )

    api = GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="explicit-key",
        use_adc=True,
    )

    assert api._oauth is True
    assert api._credentials is credentials
