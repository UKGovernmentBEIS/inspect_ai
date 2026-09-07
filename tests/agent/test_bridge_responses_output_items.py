"""Responses-API output items the agent bridge hands back to a scaffold."""

from __future__ import annotations

from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.tool._tool_call import ToolCall


def test_function_call_items_carry_an_item_id_and_completed_status() -> None:
    """Every `function_call` output item has a string `id` and is `completed`.

    Regression: items were emitted with `id: null`. The Vercel AI SDK's
    OpenAI Responses provider (used by opencode) validates streamed
    `response.output_item.added/done` items against a schema requiring
    `id: string` (and `status: "completed"` on the done event); a
    non-conforming item falls through to its "unknown chunk" fallback, so
    the tool call was silently dropped and the scaffold finished the turn as
    if the model had only produced text.
    """
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call_1", function="bash", arguments={"command": "ls"}),
            ToolCall(id="call_2", function="read", arguments={"path": "/x"}),
        ],
    )

    items = responses_output_items_from_assistant_message(message)
    function_calls = [item for item in items if item.type == "function_call"]

    assert [fc.call_id for fc in function_calls] == ["call_1", "call_2"]
    for fc in function_calls:
        assert isinstance(fc.id, str) and fc.id
        assert fc.status == "completed"
        dumped = fc.model_dump(mode="json", warnings=False)
        assert isinstance(dumped["id"], str)
        assert dumped["status"] == "completed"
    assert len({fc.id for fc in function_calls}) == 2


def test_custom_tool_call_items_carry_an_item_id() -> None:
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="call_1",
                function="apply_patch",
                arguments={"input": "*** Begin Patch"},
                type="custom",
            )
        ],
    )

    items = responses_output_items_from_assistant_message(message)
    (custom,) = [item for item in items if item.type == "custom_tool_call"]

    assert custom.call_id == "call_1"
    assert isinstance(custom.id, str) and custom.id
    assert custom.model_dump(mode="json", warnings=False)["status"] == "completed"
