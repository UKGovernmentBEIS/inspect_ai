"""Responses-API output items the agent bridge hands back to a scaffold."""

from __future__ import annotations

import pytest
from openai.types.responses import ResponseOutputMessage

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput, StopReason
from inspect_ai.tool._tool_call import ToolCall


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


@pytest.mark.parametrize(
    ("stop_reason", "status", "incomplete_reason"),
    [
        ("max_tokens", "incomplete", "max_output_tokens"),
        ("content_filter", "incomplete", "content_filter"),
        ("stop", "completed", None),
    ],
)
async def test_response_status_reports_truncated_generation(
    stop_reason: StopReason, status: str, incomplete_reason: str | None
) -> None:
    """A truncated generation is `status="incomplete"` with an incomplete final message."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model", content="partial answer", stop_reason=stop_reason
            )
        ],
    )
    bridge = AgentBridge(AgentState(messages=[]))
    bridge.model_aliases = {"gpt-5": model}

    response = await inspect_responses_api_request(
        {"model": "gpt-5", "input": "hi"}, None, None, None, bridge
    )

    assert response.status == status
    reason = response.incomplete_details.reason if response.incomplete_details else None
    assert reason == incomplete_reason
    assert len(response.output) == 1
    message = response.output[0]
    assert isinstance(message, ResponseOutputMessage)
    assert message.status == status


def test_incomplete_marks_only_a_final_message_item() -> None:
    """Truncation stopped the last item generated; items before it are complete."""
    reasoning_then_text = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="thinking"), ContentText(text="partial")]
    )
    items = responses_output_items_from_assistant_message(
        reasoning_then_text, incomplete=True
    )
    assert len(items) == 2
    assert [
        item.status for item in items if isinstance(item, ResponseOutputMessage)
    ] == ["completed", "incomplete"]

    text_then_tool_call = ChatMessageAssistant(
        content="calling a tool",
        tool_calls=[ToolCall(id="call-a", function="bash", arguments={})],
    )
    items = responses_output_items_from_assistant_message(
        text_then_tool_call, incomplete=True
    )
    assert [item.type for item in items] == ["message", "function_call"]
    assert isinstance(items[0], ResponseOutputMessage)
    assert items[0].status == "completed"
