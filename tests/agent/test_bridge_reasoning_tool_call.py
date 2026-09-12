"""Unit tests for reasoning + tool-call serialization in the Responses agent bridge.

Regression coverage for a bug where an assistant turn containing reasoning *and*
a tool call was serialized as ``[message(<think>, status=completed), function_call]``.
Responses clients (e.g. opencode) treat a completed ``message`` item as the end of
the turn and never dispatch the trailing ``function_call``, so the agent stalls
after a single model call with no answer.

Real OpenAI Responses output for a reasoning model that calls a tool has the shape
``[reasoning, function_call]`` (a ``reasoning`` item, never a completed ``message``),
which clients handle correctly. These tests pin that shape.
"""

from __future__ import annotations

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.tool._tool_call import ToolCall


def _item_types(items: list) -> list[str]:
    return [getattr(item, "type", None) for item in items]


def test_redacted_reasoning_with_tool_call_emits_reasoning_item_not_message():
    """Redacted reasoning + a tool call must serialize as [reasoning, function_call].

    Before the fix the reasoning was emitted as a ``message`` (output_text <think>
    tag) with status="completed", which terminates the turn for Responses clients
    and drops the trailing tool call.
    """
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="ENCRYPTED_REASONING_BLOB",
                signature="rs_abc123",
                redacted=True,
            )
        ],
        tool_calls=[
            ToolCall(id="call-1", function="bash", arguments={"command": "ls"})
        ],
    )

    items = responses_output_items_from_assistant_message(message)
    types = _item_types(items)

    # No completed assistant "message" item should precede the tool call: that is
    # exactly what makes Responses clients stop the turn early.
    assert "message" not in types

    # The turn should serialize as a reasoning item followed by the function call.
    assert types == ["reasoning", "function_call"]

    # The function call survives and is dispatchable.
    function_calls = [i for i in items if getattr(i, "type", None) == "function_call"]
    assert len(function_calls) == 1
    assert function_calls[0].name == "bash"

    # A Responses output item must carry a non-null `id` (distinct from
    # `call_id`). Streaming clients (e.g. opencode's AI SDK) key the tool call on
    # this item id; a null id means the tool call is never registered and the
    # turn ends with finish_reason=stop, stalling the agent after one call.
    assert function_calls[0].id is not None
    assert function_calls[0].id != ""
    assert function_calls[0].call_id == "call-1"

    # Redacted reasoning replays via encrypted_content; the signature is preserved
    # as the item id.
    reasoning_item = next(i for i in items if getattr(i, "type", None) == "reasoning")
    assert reasoning_item.encrypted_content == "ENCRYPTED_REASONING_BLOB"
    assert reasoning_item.id == "rs_abc123"


def test_readable_reasoning_with_tool_call_emits_reasoning_item():
    """Readable (non-redacted) reasoning + a tool call also serialize as a reasoning item."""
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="let me think about this",
                summary="planning step",
                redacted=False,
            )
        ],
        tool_calls=[ToolCall(id="c", function="glob", arguments={"pattern": "*.py"})],
    )

    items = responses_output_items_from_assistant_message(message)
    types = _item_types(items)

    assert "message" not in types
    assert types == ["reasoning", "function_call"]


def test_reasoning_then_text_then_tool_call_keeps_reasoning_as_item():
    """Reasoning becomes a reasoning item while visible text stays a message.

    The trailing tool call is still preserved after both.
    """
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="blob", signature="rs_x", redacted=True),
            ContentText(text="Here is the plan."),
        ],
        tool_calls=[ToolCall(id="c2", function="bash", arguments={"command": "pwd"})],
    )

    items = responses_output_items_from_assistant_message(message)
    types = _item_types(items)

    assert types == ["reasoning", "message", "function_call"]
