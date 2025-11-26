import asyncio
import base64
from unittest.mock import MagicMock

from google.genai.types import Candidate, Content, FinishReason, FunctionCall, Part
from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentReasoning,
    ContentText,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.model._providers._google_citations import (
    distribute_citations_to_text_parts,
)
from inspect_ai.model._providers.google import (
    completion_choice_from_candidate,
    content,
)
from inspect_ai.scorer import includes
from inspect_ai.tool import ToolCall


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
        model="google/gemini-2.0-flash",
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
    assert choice.message.content == ""  # Empty content for malformed calls
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
