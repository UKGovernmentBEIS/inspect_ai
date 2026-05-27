"""Unit tests for NamespaceToolParam flattening in the Responses agent bridge."""

from __future__ import annotations

from inspect_ai._util.content import ContentText
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
    tool_from_responses_tool,
    tools_from_responses_tool,
)
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._openai_responses import (
    is_custom_tool_param,
    is_function_tool_param,
    is_namespace_tool_param,
)
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo


def _function_tool(name: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": f"{name} description",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }


def _custom_tool(name: str) -> dict:
    return {
        "type": "custom",
        "name": name,
        "description": f"{name} description",
        "format": {"type": "text"},
    }


def test_is_namespace_tool_param_true_for_namespace():
    ns = {
        "type": "namespace",
        "name": "ns",
        "description": "ns",
        "tools": [_function_tool("a")],
    }
    assert is_namespace_tool_param(ns)
    assert not is_function_tool_param(ns)
    assert not is_custom_tool_param(ns)


def test_is_namespace_tool_param_false_for_others():
    assert not is_namespace_tool_param(_function_tool("a"))
    assert not is_namespace_tool_param(_custom_tool("a"))


def test_tools_from_responses_tool_flattens_namespace():
    ns = {
        "type": "namespace",
        "name": "submit",
        "description": "Submission tools",
        "tools": [_function_tool("submit_pov"), _function_tool("submit_patch")],
    }
    tools = tools_from_responses_tool(ns, {}, {})
    assert [t.name for t in tools] == ["submit_pov", "submit_patch"]
    for t in tools:
        assert isinstance(t, ToolInfo)


def test_tools_from_responses_tool_single_function():
    tools = tools_from_responses_tool(_function_tool("calc"), {}, {})
    assert len(tools) == 1
    assert tools[0].name == "calc"


def test_tools_from_responses_tool_passes_through_custom():
    tools = tools_from_responses_tool(_custom_tool("exec"), {}, {})
    assert len(tools) == 1
    assert tools[0].name == "exec"


def test_namespace_with_mixed_inner_tools():
    ns = {
        "type": "namespace",
        "name": "mixed",
        "description": "mixed",
        "tools": [_function_tool("fn"), _custom_tool("ct")],
    }
    tools = tools_from_responses_tool(ns, {}, {})
    assert [t.name for t in tools] == ["fn", "ct"]


def test_empty_namespace_returns_empty_list():
    ns = {"type": "namespace", "name": "empty", "description": "empty", "tools": []}
    assert tools_from_responses_tool(ns, {}, {}) == []


def test_tool_from_responses_tool_unchanged_for_function():
    t = tool_from_responses_tool(_function_tool("x"), {}, {})
    assert isinstance(t, ToolInfo)
    assert t.name == "x"


def test_response_function_tool_call_preserves_namespace():
    message = ChatMessageAssistant(
        content=[ContentText(text="")],
        tool_calls=[
            ToolCall(id="call-1", function="submit_pov", arguments={"foo": "bar"}),
            ToolCall(id="call-2", function="search", arguments={"q": "x"}),
        ],
    )
    tool_namespaces = {"submit_pov": "submit"}
    items = responses_output_items_from_assistant_message(message, tool_namespaces)
    function_calls = [
        item for item in items if getattr(item, "type", None) == "function_call"
    ]
    by_name = {fc.name: fc for fc in function_calls}
    assert by_name["submit_pov"].namespace == "submit"
    assert by_name["search"].namespace is None


def test_response_function_tool_call_no_namespace_map():
    message = ChatMessageAssistant(
        content=[ContentText(text="")],
        tool_calls=[ToolCall(id="c", function="plain", arguments={})],
    )
    items = responses_output_items_from_assistant_message(message)
    function_calls = [
        item for item in items if getattr(item, "type", None) == "function_call"
    ]
    assert len(function_calls) == 1
    assert function_calls[0].namespace is None
