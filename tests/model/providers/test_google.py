import asyncio
import base64
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.types import (
    Blob,
    Candidate,
    Content,
    FinishReason,
    FunctionCall,
    FunctionCallingConfigMode,
    GenerateContentResponse,
    JobState,
    Language,
    Outcome,
    Part,
    ToolResponse,
    ToolType,
)
from google.genai.types import (
    Tool as GeminiTool,
)
from google.genai.types import (
    ToolCall as GeminiToolCall,
)
from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ModelOutput
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers._google_citations import (
    distribute_citations_to_text_parts,
)
from inspect_ai.model._providers.google import (
    GoogleGenAIAPI,
    _malformed_function_message,
    _malformed_function_retry,
    completion_choice_from_candidate,
    content,
    gemini_native_tool_combination,
    gemini_native_tool_combination_config,
    parts_from_server_tool_use,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import use_tools
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolFunction,
    ToolInfo,
    ToolParam,
    ToolParams,
    tool,
    web_search,
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
        model="google/gemini-3.1-flash-lite-preview",
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


def _create_gemini_web_search_tool() -> ToolInfo:
    """Create a Gemini-native web search tool for testing."""
    return ToolInfo(
        name="web_search",
        description="Search the web",
        options={"gemini": {}},
    )


def _create_google_code_execution_tool() -> ToolInfo:
    """Create a Google-native code execution tool for testing."""
    return ToolInfo(
        name="code_execution",
        description="Execute Python code",
        options={"providers": {"google": {}}},
    )


def _create_record_result_tool() -> ToolInfo:
    """Create a string-valued custom tool for live mixed-tool tests."""
    return ToolInfo(
        name="record_result",
        description="Record an answer",
        parameters=ToolParams(
            type="object",
            properties={
                "answer": ToolParam(type="string", description="Answer summary")
            },
            required=["answer"],
        ),
    )


def _create_days_in_year_tool() -> ToolInfo:
    """Create a days-in-year custom tool for mixed native/custom replay tests."""
    return ToolInfo(
        name="days_in_year",
        description="Return the number of days in a year.",
        parameters=ToolParams(
            type="object",
            properties={
                "year": ToolParam(type="integer", description="The year to check.")
            },
            required=["year"],
        ),
    )


def _days_in_year_tool() -> Tool:
    @tool
    def days_in_year() -> Tool:
        async def execute(year: int) -> str:
            """Return the number of days in a year.

            Args:
                year: The year to check.
            """
            leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            return f"{year} has {366 if leap else 365} days."

        return execute

    return days_in_year()


def test_gemini_3_native_search_can_combine_with_function_declarations() -> None:
    api = GoogleGenAIAPI(
        model_name="gemini-3.1-pro-preview",
        base_url=None,
        api_key="test-key",
    )

    has_native_tools, gemini_tools = api.chat_tools(
        [_create_gemini_web_search_tool(), _create_test_tool()]
    )

    assert has_native_tools is True
    assert gemini_native_tool_combination(gemini_tools)
    assert len(gemini_tools) == 2
    assert isinstance(gemini_tools[0], GeminiTool)
    assert isinstance(gemini_tools[1], GeminiTool)
    assert gemini_tools[0].function_declarations is not None
    assert gemini_tools[0].function_declarations[0].name == "my_tool"
    assert gemini_tools[1].google_search is not None


def test_gemini_3_native_code_execution_can_combine_with_functions() -> None:
    api = GoogleGenAIAPI(
        model_name="gemini-3.1-pro-preview",
        base_url=None,
        api_key="test-key",
    )

    has_native_tools, gemini_tools = api.chat_tools(
        [_create_google_code_execution_tool(), _create_test_tool()]
    )

    assert has_native_tools is True
    assert gemini_native_tool_combination(gemini_tools)
    assert len(gemini_tools) == 2
    assert isinstance(gemini_tools[0], GeminiTool)
    assert isinstance(gemini_tools[1], GeminiTool)
    assert gemini_tools[0].function_declarations is not None
    assert gemini_tools[0].function_declarations[0].name == "my_tool"
    assert gemini_tools[1].code_execution is not None


def test_gemini_2_5_native_search_still_rejects_function_declarations() -> None:
    api = GoogleGenAIAPI(
        model_name="gemini-2.5-pro",
        base_url=None,
        api_key="test-key",
    )

    with pytest.raises(ValueError, match="requires Gemini 3 or later"):
        api.chat_tools([_create_gemini_web_search_tool(), _create_test_tool()])


def test_gemini_2_5_native_code_execution_still_rejects_function_declarations() -> None:
    api = GoogleGenAIAPI(
        model_name="gemini-2.5-pro",
        base_url=None,
        api_key="test-key",
    )

    with pytest.raises(ValueError, match="code execution"):
        api.chat_tools([_create_google_code_execution_tool(), _create_test_tool()])


def test_gemini_native_tool_combination_config_respects_tool_choice() -> None:
    auto_config = gemini_native_tool_combination_config("auto")
    assert auto_config.function_calling_config is not None
    assert (
        auto_config.function_calling_config.mode == FunctionCallingConfigMode.VALIDATED
    )

    any_config = gemini_native_tool_combination_config("any")
    assert any_config.function_calling_config is not None
    assert any_config.function_calling_config.mode == FunctionCallingConfigMode.ANY

    none_config = gemini_native_tool_combination_config("none")
    assert none_config.function_calling_config is not None
    assert none_config.function_calling_config.mode == FunctionCallingConfigMode.NONE

    function_config = gemini_native_tool_combination_config(
        ToolFunction(name="my_tool")
    )
    assert function_config.function_calling_config is not None
    assert function_config.function_calling_config.mode == FunctionCallingConfigMode.ANY
    assert function_config.function_calling_config.allowed_function_names == ["my_tool"]


@pytest.mark.anyio
async def test_gemini_3_tool_combination_uses_server_side_tool_invocations() -> None:
    mock_generate = AsyncMock(
        return_value=GenerateContentResponse(
            candidates=[
                Candidate(
                    finish_reason=FinishReason.STOP,
                    content=Content(role="model", parts=[Part(text="done")]),
                )
            ],
            usage_metadata=None,
        )
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-3.1-pro-preview",
            base_url=None,
            api_key="test-key",
        )

        await api.generate(
            input=[ChatMessageUser(content="Search and call my_tool")],
            tools=[_create_gemini_web_search_tool(), _create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    config = mock_generate.call_args.kwargs["config"]
    assert config.tool_config == gemini_native_tool_combination_config("auto")
    assert config.tool_config.include_server_side_tool_invocations is True
    assert config.tool_config.function_calling_config.mode == (
        FunctionCallingConfigMode.VALIDATED
    )


@pytest.mark.anyio
async def test_gemini_3_code_exec_combo_uses_server_invocations() -> None:
    mock_generate = AsyncMock(
        return_value=GenerateContentResponse(
            candidates=[
                Candidate(
                    finish_reason=FinishReason.STOP,
                    content=Content(role="model", parts=[Part(text="done")]),
                )
            ],
            usage_metadata=None,
        )
    )
    mock_client = _create_mock_google_client(mock_generate)

    with patch("inspect_ai.model._providers.google.Client", return_value=mock_client):
        api = GoogleGenAIAPI(
            model_name="gemini-3.1-pro-preview",
            base_url=None,
            api_key="test-key",
        )

        await api.generate(
            input=[ChatMessageUser(content="Run code and call my_tool")],
            tools=[_create_google_code_execution_tool(), _create_test_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    config = mock_generate.call_args.kwargs["config"]
    assert config.tool_config == gemini_native_tool_combination_config("auto")
    assert config.tool_config.include_server_side_tool_invocations is True
    assert config.tools is not None
    assert isinstance(config.tools[0], GeminiTool)
    assert isinstance(config.tools[1], GeminiTool)
    assert config.tools[0].function_declarations is not None
    assert config.tools[0].function_declarations[0].name == "my_tool"
    assert config.tools[1].code_execution is not None


def test_gemini_server_tool_call_round_trips_for_replay() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part(
                    thought_signature=b"search-context",
                    tool_call=GeminiToolCall(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        args={"queries": ["current Gemini API tool combination docs"]},
                    ),
                ),
                Part(
                    thought_signature=b"search-context-response",
                    tool_response=ToolResponse(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        response={"search_suggestions": ["Gemini tool combination"]},
                    ),
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)

    assert isinstance(choice.message.content, list)
    assert isinstance(choice.message.content[0], ContentToolUse)
    tool_use = choice.message.content[0]
    replayed_parts = parts_from_server_tool_use(tool_use)
    assert replayed_parts[0].tool_call is not None
    assert replayed_parts[0].tool_call.id == "search-1"
    assert replayed_parts[0].thought_signature == b"search-context"
    assert replayed_parts[1].tool_response is not None
    assert replayed_parts[1].tool_response.id == "search-1"
    assert replayed_parts[1].thought_signature == b"search-context-response"


def test_gemini_server_tool_call_without_signature_is_omitted_for_replay() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part(
                    tool_call=GeminiToolCall(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        args={"queries": ["current Gemini API tool combination docs"]},
                    ),
                ),
                Part(
                    tool_response=ToolResponse(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        response={"search_suggestions": ["Gemini tool combination"]},
                    ),
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)

    assert isinstance(choice.message.content, list)
    assert isinstance(choice.message.content[0], ContentToolUse)
    tool_use = choice.message.content[0]
    assert parts_from_server_tool_use(tool_use) == []


@pytest.mark.anyio
async def test_gemini_signed_function_call_replays_before_server_tool() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part(text="Plan", thought=True),
                Part(
                    thought_signature=b"days-signature",
                    function_call=FunctionCall(
                        id="days-1",
                        name="days_in_year",
                        args={"year": 2024},
                    ),
                ),
                Part(
                    thought_signature=b"search-signature",
                    tool_call=GeminiToolCall(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        args={"queries": ["most populous country"]},
                    ),
                ),
                Part(
                    thought_signature=b"search-response-signature",
                    tool_response=ToolResponse(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        response={"search_suggestions": ["India population"]},
                    ),
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)
    google_content = await content(MagicMock(), choice.message, emulate_reasoning=False)

    assert google_content.parts is not None
    assert google_content.parts[0].text == "Plan"
    assert google_content.parts[0].thought is True
    assert google_content.parts[1].function_call is not None
    assert google_content.parts[1].function_call.id == "days-1"
    assert google_content.parts[1].thought_signature == b"days-signature"
    assert google_content.parts[2].tool_call is not None
    assert google_content.parts[2].tool_call.id == "search-1"
    assert google_content.parts[2].thought_signature == b"search-signature"
    assert google_content.parts[3].tool_response is not None
    assert google_content.parts[3].tool_response.id == "search-1"


@pytest.mark.anyio
async def test_gemini_unsigned_function_call_uses_server_tool_signature() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part(text="Plan", thought=True),
                Part(
                    thought_signature=b"search-signature",
                    tool_call=GeminiToolCall(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        args={"queries": ["most populous country"]},
                    ),
                ),
                Part(
                    thought_signature=b"search-response-signature",
                    tool_response=ToolResponse(
                        id="search-1",
                        tool_type=ToolType.GOOGLE_SEARCH_WEB,
                        response={"search_suggestions": ["India population"]},
                    ),
                ),
                Part(
                    function_call=FunctionCall(
                        id="days-1",
                        name="days_in_year",
                        args={"year": 2024},
                    ),
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)
    google_content = await content(MagicMock(), choice.message, emulate_reasoning=False)

    assert google_content.parts is not None
    assert google_content.parts[0].text == "Plan"
    assert google_content.parts[1].tool_call is not None
    assert google_content.parts[1].thought_signature == b"search-signature"
    assert google_content.parts[2].tool_response is not None
    assert google_content.parts[3].function_call is not None
    assert google_content.parts[3].function_call.id == "days-1"
    assert google_content.parts[3].thought_signature == b"search-signature"


def test_gemini_unsupported_server_tool_call_is_omitted() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part(
                    thought_signature=b"url-context",
                    tool_call=GeminiToolCall(
                        id="url-context-1",
                        tool_type=ToolType.URL_CONTEXT,
                        args={"urls": ["https://example.com"]},
                    ),
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)

    assert choice.message.content == ""


def test_gemini_code_execution_round_trips_for_replay() -> None:
    candidate = Candidate(
        finish_reason=FinishReason.STOP,
        content=Content(
            role="model",
            parts=[
                Part.from_executable_code(
                    code="print(6 * 7)",
                    language=Language.PYTHON,
                ),
                Part.from_code_execution_result(
                    outcome=Outcome.OUTCOME_OK,
                    output="42\n",
                ),
            ],
        ),
    )

    choice = completion_choice_from_candidate("gemini-3.1-pro-preview", candidate)

    assert isinstance(choice.message.content, list)
    assert isinstance(choice.message.content[0], ContentToolUse)
    tool_use = choice.message.content[0]
    assert tool_use.tool_type == "code_execution"
    assert tool_use.name == Language.PYTHON
    assert tool_use.arguments == "print(6 * 7)"
    assert tool_use.result == "42\n"

    replayed_parts = parts_from_server_tool_use(tool_use)
    assert replayed_parts[0].executable_code is not None
    assert replayed_parts[0].executable_code.language == Language.PYTHON
    assert replayed_parts[0].executable_code.code == "print(6 * 7)"
    assert replayed_parts[1].code_execution_result is not None
    assert replayed_parts[1].code_execution_result.outcome == Outcome.OUTCOME_OK
    assert replayed_parts[1].code_execution_result.output == "42\n"


@pytest.mark.anyio
async def test_gemini_function_response_preserves_tool_call_id() -> None:
    message = ChatMessageTool(
        content="42",
        tool_call_id="call-123",
        function="my_tool",
    )

    google_content = await content(MagicMock(), message, emulate_reasoning=False)

    assert google_content.parts is not None
    assert google_content.parts[0].function_response is not None
    assert google_content.parts[0].function_response.id == "call-123"


@pytest.mark.anyio
async def test_gemini_function_call_preserves_tool_call_id() -> None:
    message = ChatMessageAssistant(
        content=[],
        tool_calls=[
            ToolCall(
                id="call-123",
                function="my_tool",
                arguments={"x": 42},
            )
        ],
    )

    google_content = await content(MagicMock(), message, emulate_reasoning=False)

    assert google_content.parts is not None
    assert google_content.parts[0].function_call is not None
    assert google_content.parts[0].function_call.id == "call-123"


@pytest.mark.anyio
@skip_if_no_google
async def test_gemini_3_native_search_with_function_tool_replays() -> None:
    api = GoogleGenAIAPI(
        model_name="gemini-3.1-pro-preview",
        base_url=None,
        api_key=os.environ["GOOGLE_API_KEY"],
    )
    user = ChatMessageUser(
        content=(
            "Use days_in_year(2024) AND web search 'most populous country'. "
            "Then a 1-line answer."
        )
    )

    first_output, _ = await api.generate(
        input=[user],
        tools=[_create_gemini_web_search_tool(), _create_days_in_year_tool()],
        tool_choice="auto",
        config=GenerateConfig(max_tokens=2048),
    )
    assert isinstance(first_output, ModelOutput)
    assistant = first_output.choices[0].message

    assert isinstance(assistant.content, list)
    assert any(isinstance(item, ContentToolUse) for item in assistant.content)
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) > 0

    tool_call = assistant.tool_calls[0]
    tool_result = ChatMessageTool(
        content="2024 has 366 days.",
        tool_call_id=tool_call.id,
        function=tool_call.function,
    )

    second_output, _ = await api.generate(
        input=[user, assistant, tool_result],
        tools=[_create_gemini_web_search_tool(), _create_days_in_year_tool()],
        tool_choice="auto",
        config=GenerateConfig(max_tokens=2048),
    )
    assert isinstance(second_output, ModelOutput)

    assert second_output.choices[0].stop_reason == "stop"
    assert second_output.choices[0].message.text is not None


@skip_if_no_google
def test_gemini_3_native_search_with_function_tool_react_loop() -> None:
    result = eval(
        Task(
            dataset=[
                Sample(
                    input=(
                        "Use days_in_year(2024) AND web search 'most populous "
                        "country'. Then submit a one-line summary."
                    )
                )
            ],
            solver=react(tools=[web_search(providers="gemini"), _days_in_year_tool()]),
        ),
        model="google/gemini-3.1-pro-preview",
        message_limit=10,
        max_tokens=4096,
        fail_on_error=False,
    )[0]

    assert result.status == "success"
    assert result.samples
    assert result.samples[0].output is not None


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


# Tests for count_tokens with unpaired tool messages


@pytest.mark.anyio
@skip_if_no_google
async def test_google_count_tokens_single_tool_call() -> None:
    """Test counting tokens for a single assistant message with one tool call."""
    from inspect_ai.model import get_model

    model = get_model("google/gemini-3.1-flash-lite-preview")

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

    model = get_model("google/gemini-3.1-flash-lite-preview")

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

    model = get_model("google/gemini-3.1-flash-lite-preview")

    # Create a tool result message without a preceding assistant message
    tool_msg = ChatMessageTool(
        content="Tool result content here",
        tool_call_id="call_test_xyz",
        function="some_function",
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([tool_msg])
    assert token_count > 0


@skip_if_no_google
def test_google_streaming_basic():
    """Test basic streaming with simple prompt."""
    result = eval(
        Task(
            dataset=[Sample(input="Say hello in one sentence", target="hello")],
            scorer=includes(),
        ),
        model="google/gemini-3.1-flash-lite-preview",
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
        model="google/gemini-3.1-flash-lite-preview",
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
        model="google/gemini-3.1-flash-lite-preview",
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
