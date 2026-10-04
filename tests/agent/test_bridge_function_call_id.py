"""Regression tests: Responses tool-call output items must carry a non-null id.

An assistant turn that calls a tool is serialized (for Responses clients such as
opencode) into ``function_call`` / ``custom_tool_call`` output items. Each output
item must have a non-null item ``id`` (distinct from ``call_id``): streaming
clients key the emitted tool call on that item id, and a null id means the tool
call is never registered -- the turn ends with ``finish_reason=stop`` and the
agent stalls after a single model call.
"""

from __future__ import annotations

from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.tool._tool_call import ToolCall


def test_function_call_items_have_non_null_unique_ids():
    """Each function_call item gets a non-null, unique id; call_id round-trips."""
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call-a", function="bash", arguments={"command": "ls"}),
            ToolCall(id="call-b", function="glob", arguments={"pattern": "*.py"}),
        ],
    )

    items = responses_output_items_from_assistant_message(message)
    function_calls = [i for i in items if getattr(i, "type", None) == "function_call"]

    assert len(function_calls) == 2
    ids = [fc.id for fc in function_calls]
    assert all(i for i in ids)  # non-null and non-empty
    assert len(set(ids)) == 2  # unique per item
    # `call_id` still round-trips the originating tool call id.
    assert [fc.call_id for fc in function_calls] == ["call-a", "call-b"]
    assert [fc.name for fc in function_calls] == ["bash", "glob"]


def test_custom_tool_call_item_has_non_null_id():
    """A custom tool call item also carries a non-null id."""
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="call-c",
                function="my_custom",
                arguments={"input": "payload"},
                type="custom",
            )
        ],
    )

    items = responses_output_items_from_assistant_message(message)
    custom_calls = [i for i in items if getattr(i, "type", None) == "custom_tool_call"]
    assert len(custom_calls) == 1
    assert custom_calls[0].id
    assert custom_calls[0].call_id == "call-c"
