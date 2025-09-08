"""Test for bug fix: ResponseFunctionWebSearch should exclude None values when stored in server_tool_uses.

This test covers the bug where ResponseFunctionWebSearch.model_dump() would include
None values (specifically in the 'sources' field), causing OpenAI to return 400 errors
when the data in server_tool_uses was sent back to OpenAI.
The fix was to use model_dump(exclude_none=True) to exclude None values.
"""

from unittest.mock import MagicMock, patch

from openai.types.responses import ResponseFunctionWebSearch
from openai.types.responses.response_function_web_search import ActionSearch

from inspect_ai.model._openai_responses import (
    _chat_message_assistant_from_openai_response,
    _openai_input_items_from_chat_message_assistant,
)


def test_web_search_round_trip_excludes_none():
    """Test the complete round-trip: OpenAI Response -> ChatMessageAssistant -> OpenAI Input Items.

    This test verifies that sources=None in the original OpenAI Response does NOT
    appear in the final input items after the round-trip conversion, demonstrating
    that the bug fix prevents None values from being sent back to OpenAI.
    """
    # Create a web search with ActionSearch that has sources=None (the bug condition)
    web_search = ResponseFunctionWebSearch(
        type="web_search_call",
        id="round-trip-web-search",
        action=ActionSearch(type="search", query="test round trip", sources=None),
        status="completed",
    )

    # Verify the original has sources=None (the problematic input)
    original_dump = web_search.model_dump()
    assert "sources" in original_dump["action"]
    assert original_dump["action"]["sources"] is None

    # Step 1: Convert OpenAI Response to ChatMessageAssistant
    mock_response = MagicMock()
    mock_response.incomplete_details = None
    mock_response.output = [web_search]

    with patch(
        "inspect_ai.model._openai_responses.assistant_internal"
    ) as mock_assistant_internal:
        mock_internal = MagicMock()
        mock_internal.server_tool_uses = {}
        mock_assistant_internal.return_value = mock_internal

        with patch(
            "inspect_ai.model._openai_responses.web_search_to_tool_use"
        ) as mock_web_search_to_tool_use:
            from inspect_ai._util.content import ContentToolUse

            mock_web_search_to_tool_use.return_value = ContentToolUse(
                tool_type="web_search",
                id="round-trip-web-search",
                name="search",
                arguments='{"query": "test round trip"}',
                result="",
                error=None,
            )

            # Convert OpenAI Response to ChatMessageAssistant
            chat_message, _stop_reason = _chat_message_assistant_from_openai_response(
                model="gpt-4", response=mock_response, tools=[]
            )

            # Verify server_tool_uses excludes None values (the fix working)
            stored_data = mock_internal.server_tool_uses["round-trip-web-search"]
            assert "sources" not in stored_data["action"], (
                "server_tool_uses should exclude None values (bug fix)"
            )

            # Step 2: Convert ChatMessageAssistant back to OpenAI Input Items
            input_items = _openai_input_items_from_chat_message_assistant(chat_message)

            # Find the web search call in the input items
            web_search_items = [
                item for item in input_items if item.get("type") == "web_search_call"
            ]

            # The critical assertion: verify None values are NOT present in final output
            # This demonstrates the complete fix - None values from original response
            # don't make it back to the input items that would be sent to OpenAI
            web_search_item = web_search_items[0]
            assert "sources" not in web_search_item["action"], (
                "Final input items should not contain sources=None (complete bug fix)"
            )
