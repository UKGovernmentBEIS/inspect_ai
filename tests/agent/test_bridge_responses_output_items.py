"""Responses-API output items the agent bridge hands back to a scaffold."""

from __future__ import annotations

from inspect_ai._util.content import ContentToolUse
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.model._chat_message import ChatMessageAssistant


def test_server_tool_use_items_with_empty_id_get_unique_item_ids() -> None:
    """Server tool use content with `id=""` (google, mistral) gets a minted item id."""
    message = ChatMessageAssistant(
        content=[
            ContentToolUse(
                tool_type="web_search",
                id="",
                name="web_search",
                arguments='{"type": "search", "query": "inspect"}',
                result="",
            ),
            ContentToolUse(
                tool_type="web_search",
                id="",
                name="web_search",
                arguments='{"type": "search", "query": "aisi"}',
                result="",
            ),
            ContentToolUse(
                tool_type="code_execution",
                id="",
                name="python",
                arguments="print(1)",
                result="1",
            ),
            ContentToolUse(
                tool_type="code_execution",
                id="",
                name="python",
                arguments="print(2)",
                result="2",
            ),
        ]
    )

    items = responses_output_items_from_assistant_message(message)

    assert [item.type for item in items] == [
        "web_search_call",
        "web_search_call",
        "code_interpreter_call",
        "code_interpreter_call",
    ]
    ids = [item.id for item in items]
    assert all(isinstance(item_id, str) and item_id for item_id in ids)
    assert len(set(ids)) == 4


def test_function_and_custom_tool_calls_get_non_null_item_ids() -> None:
    """function_call / custom_tool_call items carry their own item id.

    The id is distinct from call_id; Responses clients key dispatch on it (#5366).
    """
    from inspect_ai.tool._tool_call import ToolCall

    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call-1", function="bash", arguments={"command": "ls"}),
            ToolCall(
                id="call-2",
                function="submit",
                arguments={"answer": "42"},
                type="custom",
            ),
        ],
    )

    items = responses_output_items_from_assistant_message(message)

    tool_items = [i for i in items if i.type in ("function_call", "custom_tool_call")]
    assert [i.type for i in tool_items] == ["function_call", "custom_tool_call"]
    for item, call in zip(tool_items, message.tool_calls or [], strict=True):
        assert isinstance(item.id, str) and item.id, f"{item.type} has null item id"
        assert item.id != call.id, f"{item.type} reuses call_id as item id"
        assert item.call_id == call.id
    assert tool_items[0].id != tool_items[1].id
