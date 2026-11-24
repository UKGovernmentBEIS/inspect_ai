"""Responses-API output items the agent bridge hands back to a scaffold."""

from __future__ import annotations

from typing import Any

import pytest
from test_helpers.message_ids import edited_id

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    default_code_execution_providers,
    internal_web_search_providers,
)
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
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


def _reply(kind: str) -> ChatMessageAssistant:
    """A generated reply that the bridge serializes as Responses items of `kind`."""
    match kind:
        case "message":
            return ChatMessageAssistant(content="hello")
        case "refusal":
            return ChatMessageAssistant(content=[ContentText(text="no", refusal=True)])
        case "reasoning":
            return ChatMessageAssistant(
                content=[
                    ContentReasoning(reasoning="think", signature="sig"),
                    ContentText(text="hello"),
                ]
            )
        case "web_search_call":
            return ChatMessageAssistant(
                content=[
                    ContentToolUse(
                        tool_type="web_search",
                        id="ws_1",
                        name="search",
                        arguments='{"type": "search", "query": "inspect"}',
                        result="",
                    ),
                    # a provider's own form, as Anthropic and Google give it
                    ContentToolUse(
                        tool_type="web_search",
                        id="ws_2",
                        name="web_search",
                        arguments='{"query": "aisi"}',
                        result="[]",
                    ),
                    ContentToolUse(
                        tool_type="web_search",
                        id="ws_3",
                        name="web_search",
                        arguments="inspect evals",
                        result="",
                    ),
                ]
            )
        case "code_interpreter_call":
            return ChatMessageAssistant(
                content=[
                    ContentToolUse(
                        tool_type="code_execution",
                        id="ci_1",
                        name="code_interpreter_call",
                        arguments="print(1)",
                        result="1",
                    ),
                    # Anthropic code execution, and a failed run
                    ContentToolUse(
                        tool_type="code_execution",
                        id="srvtoolu_1",
                        name="bash_code_execution",
                        arguments='{"command": "echo 2"}',
                        result='{"stdout": "2"}',
                        error="failed",
                    ),
                    ContentText(text="ran it"),
                ]
            )
        case "mcp_list_tools":
            return ChatMessageAssistant(
                content=[
                    ContentToolUse(
                        tool_type="mcp_call",
                        id="mcpl_1",
                        name="mcp_list_tools",
                        context="server",
                        arguments="",
                        result='[{"name": "echo", "input_schema": {}}]',
                    )
                ]
            )
        case "mcp_call":
            return ChatMessageAssistant(
                content=[
                    ContentToolUse(
                        tool_type="mcp_call",
                        id="mcp_1",
                        name="echo",
                        context="server",
                        arguments='{"text": "hi"}',
                        result="hi",
                    ),
                    ContentToolUse(
                        tool_type="mcp_call",
                        id="mcp_2",
                        name="echo",
                        context="server",
                        arguments='{"text": "oops"}',
                        result="",
                        error="failed",
                    ),
                ]
            )
        case "function_call":
            return ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(id="call_1", function="read_file", arguments={"path": "a"})
                ],
            )
        case "custom_tool_call":
            return ChatMessageAssistant(
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
        case "computer_call":
            return ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function="computer",
                        arguments={"actions": [{"action": "screenshot"}]},
                    )
                ],
            )
        case "tool_search_call":
            return ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function="tool_search",
                        arguments={"query": "files"},
                    )
                ],
            )
    raise AssertionError(kind)


def _results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scaffold's answer to each client-run call in `items`."""
    results: list[dict[str, Any]] = []
    for item in items:
        match item["type"]:
            case "function_call":
                results.append(
                    {
                        "type": "function_call_output",
                        "call_id": item["call_id"],
                        "output": "1",
                    }
                )
            case "custom_tool_call":
                results.append(
                    {
                        "type": "custom_tool_call_output",
                        "call_id": item["call_id"],
                        "output": "done",
                    }
                )
            case "computer_call":
                results.append(
                    {
                        "type": "computer_call_output",
                        "call_id": item["call_id"],
                        "output": {
                            "type": "computer_screenshot",
                            "image_url": "data:image/png;base64,iVBORw0KGgo=",
                        },
                    }
                )
            case "tool_search_call":
                results.append(
                    {
                        "type": "tool_search_output",
                        "call_id": item["call_id"],
                        "execution": "client",
                        "status": "completed",
                        "tools": [],
                    }
                )
    return results


EMITTED_KINDS = [
    "message",
    "refusal",
    "reasoning",
    "web_search_call",
    "code_interpreter_call",
    "mcp_list_tools",
    "mcp_call",
    "function_call",
    "custom_tool_call",
    "computer_call",
    "tool_search_call",
]


@pytest.mark.parametrize("kind", EMITTED_KINDS)
async def test_request_handler_returns_and_continues_each_emitted_item(
    kind: str,
) -> None:
    """Every item type the bridge hands a Responses scaffold can be handed out and sent back.

    The handler parses its own output items to recognize the reply when the
    scaffold sends it back, so an item type the input parser rejects fails
    the first request, not only a continued one.
    """
    # usage is set so mockllm doesn't estimate it (which downloads an encoding)
    usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    done = ModelOutput.from_content("mockllm/model", "done")
    done.usage = usage
    model = get_model(
        "mockllm/model",
        memoize=False,
        custom_outputs=[
            ModelOutput(
                model="mockllm/model",
                choices=[
                    ChatCompletionChoice(message=_reply(kind), stop_reason="stop")
                ],
                usage=usage,
            ),
            done,
        ],
    )
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="go")]),
        model_aliases={"scaffold": model},
    )
    tools = [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]

    async def request(input: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = await inspect_responses_api_request(
            {"model": "scaffold", "input": input, "tools": tools},
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        return [item.model_dump(exclude_none=True) for item in response.output]

    history: list[dict[str, Any]] = [{"role": "user", "content": "go"}]
    items = await request(history)
    expected = "message" if kind in ("refusal", "reasoning") else kind
    assert expected in [item["type"] for item in items]
    generated = bridge.state.output.message

    history += [*items, *_results(items), {"role": "user", "content": "continue"}]
    assert [item["type"] for item in await request(history)] == ["message"]

    # the reply sent back is placed: it keeps its generated id, or an id
    # derived from it for the dialect's wire form
    sent = next(m for m in bridge.state.messages if isinstance(m, ChatMessageAssistant))
    assert sent.id in (generated.id, edited_id(generated.id, sent))
