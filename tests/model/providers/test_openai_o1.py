from inspect_ai.model import ChatMessageAssistant
from inspect_ai.model._providers.openai_o1 import O1PreviewChatAPIHandler


def test_openai_o1_tool_call_parsing() -> None:
    handler = O1PreviewChatAPIHandler()

    resp: ChatMessageAssistant = handler.parse_assistant_response(
        response="""I will enter the search term into the search box and submit the search.

<tool_call>{"name": "web_browser_type_submit", "arguments": {"element_id": 11399, "text": "hilarious cat videos"}}</tool_call>""",
        tools=[],
    )

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].function == "web_browser_type_submit"
    assert resp.tool_calls[0].arguments == {
        "element_id": 11399,
        "text": "hilarious cat videos",
    }


def test_openai_o1_tool_call_parsing_empty_arguments() -> None:
    handler = O1PreviewChatAPIHandler()

    resp: ChatMessageAssistant = handler.parse_assistant_response(
        response="""I need to return to the search results to explore other potential sources for the answer.

<tool_call>
{"name": "web_browser_back", "arguments": {}}
</tool_call>""",
        tools=[],
    )

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].function == "web_browser_back"
    assert resp.tool_calls[0].arguments == {}


def test_openai_o1_tool_call_parsing_no_arguments() -> None:
    handler = O1PreviewChatAPIHandler()

    resp: ChatMessageAssistant = handler.parse_assistant_response(
        response="""I need to return to the search results to explore other potential sources for the answer.

<tool_call>
{"name": "web_browser_back"}
</tool_call>""",
        tools=[],
    )

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].function == "unknown"
    assert resp.tool_calls[0].parse_error is not None
