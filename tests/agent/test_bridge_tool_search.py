"""Unit tests for tool_search passthrough in the Responses agent bridge.

tool_search (execution="client") is a client-resolved built-in tool: the model
emits a ``tool_search_call``, the scaffold (e.g. codex-cli) resolves it locally
and returns a ``tool_search_output`` with the discovered tools. These tests cover
the full round-trip through the bridge + provider conversion helpers (no network).
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseInputItemParam,
    ResponseToolSearchCall,
    ToolParam,
    ToolSearchToolParam,
)

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.responses_impl import (
    messages_from_responses_input,
    responses_output_items_from_assistant_message,
    tool_from_responses_tool,
    tools_from_client_tool_search_output,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai_responses import (
    TOOL_SEARCH_NAME,
    TOOL_SEARCH_OPTIONS_MARKER,
    _maybe_native_tool_param,
    _openai_input_item_from_chat_message,
    _process_response_output_items,
    init_sample_openai_assistant_internal,
    is_tool_search_tool_param,
    maybe_tool_search_tool,
)
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams

WEB_SEARCH_PROVIDERS: Any = {}
CODE_EXECUTION_PROVIDERS: Any = {}


def _tool_search_tool_param() -> ToolSearchToolParam:
    return {
        "type": "tool_search",
        "description": "Search for available tools",
        "execution": "client",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Maximum number of tools to return. Defaults to 8.",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for deferred tools.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def _discoverable_function_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "strict": False,
    }


def _deferred_mcp_namespace() -> dict[str, Any]:
    return {
        "type": "namespace",
        "name": "mcp__browser_tools",
        "description": "Deferred browser tools.",
        "tools": [
            {
                "type": "function",
                "name": "browser",
                "description": "Control the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"action": {"type": "string"}},
                    "required": ["action"],
                    "additionalProperties": False,
                },
                "strict": False,
                "defer_loading": True,
            },
            {
                "type": "function",
                "name": "javascript_exec",
                "description": "Run JavaScript in the task browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"script": {"type": "string"}},
                    "required": ["script"],
                    "additionalProperties": False,
                },
                "strict": False,
                "defer_loading": True,
            },
        ],
    }


async def test_client_tool_search_reaches_non_openai_with_discovered_mcp_tools() -> (
    None
):
    """A client discovery call survives a non-OpenAI bridge continuation."""
    requested_tool_search = _tool_search_tool_param()
    discovered_mcp_namespace = _deferred_mcp_namespace()
    browser_tool_name = f"{discovered_mcp_namespace['name']}__browser"
    tool_names_seen: list[set[str]] = []
    outputs = iter(
        [
            ModelOutput.for_tool_call(
                "mockllm/model",
                TOOL_SEARCH_NAME,
                {"query": "browser tools", "limit": 8},
                tool_call_id="tool_search_1",
            ),
            ModelOutput.for_tool_call(
                "mockllm/model",
                browser_tool_name,
                {"action": "screenshot"},
                tool_call_id="browser_1",
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ]
    )

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        names = {tool.name for tool in tools}
        tool_names_seen.append(names)
        if len(tool_names_seen) == 1:
            assert names == {TOOL_SEARCH_NAME}, (
                "client tool_search missing from the first non-OpenAI bridge generation"
            )
        else:
            assert names == {
                TOOL_SEARCH_NAME,
                browser_tool_name,
                f"{discovered_mcp_namespace['name']}__javascript_exec",
            }, (
                "client-discovered MCP namespace missing from the non-OpenAI "
                "bridge continuation"
            )
        if len(tool_names_seen) == 3:
            replayed_calls = [
                call
                for message in _input
                if isinstance(message, ChatMessageAssistant)
                for call in message.tool_calls or []
                if call.id == "browser_1"
            ]
            assert len(replayed_calls) == 1
            assert replayed_calls[0].function == browser_tool_name
            replayed_results = [
                message
                for message in _input
                if isinstance(message, ChatMessageTool)
                and message.tool_call_id == "browser_1"
            ]
            assert len(replayed_results) == 1
            assert replayed_results[0].function == browser_tool_name
        return next(outputs)

    model = get_model("mockllm/model", custom_outputs=custom_outputs)
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model},
    )
    first_response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [{"role": "user", "content": "Find a browser tool."}],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    first_calls = [
        item
        for item in first_response.output
        if isinstance(item, ResponseToolSearchCall)
    ]
    assert len(first_calls) == 1
    first_call = first_calls[0]
    assert first_call.call_id == "tool_search_1"
    assert first_call.arguments == {"query": "browser tools", "limit": 8}
    assert first_call.execution == "client"

    discovery_output = {
        "type": "tool_search_output",
        "call_id": first_call.call_id,
        "tools": [discovered_mcp_namespace],
        "status": "completed",
    }
    continuation = [
        {"role": "user", "content": "Find a browser tool."},
        *(item.model_dump(exclude_none=True) for item in first_response.output),
        discovery_output,
    ]
    second_response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": continuation,
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    second_calls = [
        item
        for item in second_response.output
        if isinstance(item, ResponseFunctionToolCall)
    ]
    assert len(second_calls) == 1
    second_call = second_calls[0]
    assert second_call.call_id == "browser_1"
    assert second_call.name == "browser"
    assert second_call.namespace == discovered_mcp_namespace["name"]
    assert second_call.arguments == '{"action": "screenshot"}'
    third_response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {"role": "user", "content": "Find a browser tool."},
                *(item.model_dump(exclude_none=True) for item in first_response.output),
                discovery_output,
                *(
                    item.model_dump(exclude_none=True)
                    for item in second_response.output
                ),
                {
                    "type": "function_call_output",
                    "call_id": second_call.call_id,
                    "output": "screenshot taken",
                },
            ],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    assert third_response.output_text == "done"
    assert tool_names_seen == [
        {TOOL_SEARCH_NAME},
        {
            TOOL_SEARCH_NAME,
            browser_tool_name,
            f"{discovered_mcp_namespace['name']}__javascript_exec",
        },
        {
            TOOL_SEARCH_NAME,
            browser_tool_name,
            f"{discovered_mcp_namespace['name']}__javascript_exec",
        },
    ]


async def test_client_tool_search_rejects_explicit_server_discovery_output() -> None:
    """An explicit server result cannot override client discovery metadata."""
    requested_tool_search = _tool_search_tool_param()

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        assert {tool.name for tool in tools} == {TOOL_SEARCH_NAME}
        return ModelOutput.from_content("mockllm/model", "done")

    model = get_model("mockllm/model", custom_outputs=custom_outputs)
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model},
    )
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {"role": "user", "content": "Find a browser tool."},
                {
                    "type": "tool_search_call",
                    "id": "ts_1",
                    "call_id": "tool_search_1",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_1",
                    "execution": "server",
                    "tools": [_discoverable_function_tool()],
                    "status": "completed",
                },
            ],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


async def test_client_tool_search_call_allows_missing_call_id() -> None:
    """Codex may omit call_id while the SDK falls back to the item id."""

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        assert {tool.name for tool in tools} == {TOOL_SEARCH_NAME}
        return ModelOutput.from_content("mockllm/model", "done")

    model = get_model("mockllm/model", custom_outputs=custom_outputs)
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model},
    )
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {
                    "type": "tool_search_call",
                    "id": "ts_1",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                }
            ],
            "tools": [_tool_search_tool_param()],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


async def test_client_tool_search_accumulates_namespace_discoveries() -> None:
    """Later results from one namespace add their newly discovered tools."""
    requested_tool_search = _tool_search_tool_param()
    first_discovery = _deferred_mcp_namespace()
    second_discovery = _deferred_mcp_namespace()
    first_discovery["tools"] = [first_discovery["tools"][0]]
    second_discovery["tools"] = [second_discovery["tools"][1]]
    expected_names = {
        TOOL_SEARCH_NAME,
        f"{first_discovery['name']}__browser",
        f"{second_discovery['name']}__javascript_exec",
    }

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        assert {tool.name for tool in tools} == expected_names
        return ModelOutput.from_content("mockllm/model", "done")

    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={
            "inspect": get_model("mockllm/model", custom_outputs=custom_outputs)
        },
    )
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {"role": "user", "content": "Find browser tools."},
                {
                    "type": "tool_search_call",
                    "id": "ts_1",
                    "call_id": "tool_search_1",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_1",
                    "tools": [first_discovery],
                    "status": "completed",
                },
                {
                    "type": "tool_search_call",
                    "id": "ts_2",
                    "call_id": "tool_search_2",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_2",
                    "tools": [second_discovery],
                    "status": "completed",
                },
            ],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


async def test_client_tool_search_deduplicates_repeated_plain_discoveries() -> None:
    """Repeated identical plain discoveries do not make the tool catalog ambiguous."""
    requested_tool_search = _tool_search_tool_param()
    discovered_tool = _discoverable_function_tool()

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        assert {tool.name for tool in tools} == {TOOL_SEARCH_NAME, "read_file"}
        return ModelOutput.from_content("mockllm/model", "done")

    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={
            "inspect": get_model("mockllm/model", custom_outputs=custom_outputs)
        },
    )
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {"role": "user", "content": "Find a file tool."},
                {
                    "type": "tool_search_call",
                    "id": "ts_1",
                    "call_id": "tool_search_1",
                    "arguments": {"query": "file tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_1",
                    "tools": [discovered_tool],
                    "status": "completed",
                },
                {
                    "type": "tool_search_call",
                    "id": "ts_2",
                    "call_id": "tool_search_2",
                    "arguments": {"query": "file tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_2",
                    "tools": [discovered_tool],
                    "status": "completed",
                },
            ],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


async def test_client_tool_search_accumulates_overlapping_namespace_discoveries() -> (
    None
):
    """Overlapping namespace results retain the newly discovered tool."""
    requested_tool_search = _tool_search_tool_param()
    first_discovery = _deferred_mcp_namespace()
    overlapping_discovery = _deferred_mcp_namespace()
    first_discovery["tools"] = [first_discovery["tools"][0]]
    expected_names = {
        TOOL_SEARCH_NAME,
        f"{first_discovery['name']}__browser",
        f"{overlapping_discovery['name']}__javascript_exec",
    }

    def custom_outputs(
        _input: list[ChatMessage],
        tools: list[ToolInfo],
        _tool_choice: ToolChoice,
        _config: GenerateConfig,
    ) -> ModelOutput:
        assert {tool.name for tool in tools} == expected_names
        return ModelOutput.from_content("mockllm/model", "done")

    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={
            "inspect": get_model("mockllm/model", custom_outputs=custom_outputs)
        },
    )
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [
                {"role": "user", "content": "Find browser tools."},
                {
                    "type": "tool_search_call",
                    "id": "ts_1",
                    "call_id": "tool_search_1",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_1",
                    "tools": [first_discovery],
                    "status": "completed",
                },
                {
                    "type": "tool_search_call",
                    "id": "ts_2",
                    "call_id": "tool_search_2",
                    "arguments": {"query": "browser tools"},
                    "execution": "client",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "call_id": "tool_search_2",
                    "tools": [overlapping_discovery],
                    "status": "completed",
                },
            ],
            "tools": [requested_tool_search],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


@pytest.mark.parametrize(
    "discovered_tools",
    [
        [{"type": "computer"}],
        [
            {
                "type": "namespace",
                "name": "deferred",
                "tools": [{"type": "computer"}],
            }
        ],
    ],
    ids=["top-level", "namespace"],
)
async def test_client_tool_search_rejects_discovered_computer_use(
    discovered_tools: list[dict[str, Any]],
) -> None:
    """Client discovery cannot add computer use to a non-OpenAI bridge."""
    model = get_model("mockllm/model")
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model},
    )

    with pytest.raises(RuntimeError, match="computer use with the OpenAI Responses"):
        await inspect_responses_api_request(
            {
                "model": "inspect",
                "input": [
                    {
                        "type": "tool_search_call",
                        "id": "ts_1",
                        "call_id": "tool_search_1",
                        "arguments": {"query": "browser tools"},
                        "execution": "client",
                        "status": "completed",
                    },
                    {
                        "type": "tool_search_output",
                        "call_id": "tool_search_1",
                        "tools": discovered_tools,
                        "status": "completed",
                    },
                ],
                "tools": [_tool_search_tool_param()],
            },
            None,
            None,
            None,
            bridge,
        )


async def test_client_tool_search_rejects_ambiguous_flattened_name() -> None:
    """A deferred namespace cannot shadow an existing generic tool."""
    discovered_mcp_namespace = _deferred_mcp_namespace()
    existing_tool = _discoverable_function_tool()
    existing_tool["name"] = f"{discovered_mcp_namespace['name']}__browser"
    model = get_model("mockllm/model")
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model},
    )

    with pytest.raises(RuntimeError, match="Ambiguous client tool catalog"):
        await inspect_responses_api_request(
            {
                "model": "inspect",
                "input": [
                    {
                        "type": "tool_search_call",
                        "id": "ts_1",
                        "call_id": "tool_search_1",
                        "arguments": {"query": "browser tools"},
                        "execution": "client",
                        "status": "completed",
                    },
                    {
                        "type": "tool_search_output",
                        "call_id": "tool_search_1",
                        "tools": [discovered_mcp_namespace],
                        "status": "completed",
                    },
                ],
                "tools": [_tool_search_tool_param(), existing_tool],
            },
            None,
            None,
            None,
            bridge,
        )


@pytest.mark.parametrize("plain_first", [True, False], ids=["plain", "namespace"])
async def test_client_discovery_rejects_plain_namespace_name_collisions(
    plain_first: bool,
) -> None:
    """Plain and namespaced discovery entries cannot share a generic name."""
    namespace_tool = _deferred_mcp_namespace()
    plain_tool = _discoverable_function_tool()
    plain_tool["name"] = f"{namespace_tool['name']}__browser"
    discovered_tools = (
        [plain_tool, namespace_tool] if plain_first else [namespace_tool, plain_tool]
    )
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": get_model("mockllm/model")},
    )

    with pytest.raises(RuntimeError, match="Ambiguous client tool catalog"):
        await inspect_responses_api_request(
            {
                "model": "inspect",
                "input": [
                    {
                        "type": "tool_search_call",
                        "id": "ts_1",
                        "call_id": "tool_search_1",
                        "arguments": {"query": "browser tools"},
                        "execution": "client",
                        "status": "completed",
                    },
                    {
                        "type": "tool_search_output",
                        "call_id": "tool_search_1",
                        "tools": discovered_tools,
                        "status": "completed",
                    },
                ],
                "tools": [_tool_search_tool_param()],
            },
            None,
            None,
            None,
            bridge,
        )


def test_client_discovery_skips_custom_and_server_builtins() -> None:
    """Custom and server-resolved built-ins never reach generic providers."""
    tool_namespaces: dict[str, tuple[str, str]] = {}
    tool_names: dict[str, tuple[str, str | None, ToolParams] | None] = {}
    discovered_tools = [
        cast(ToolParam, {"type": "custom", "name": "custom_tool"}),
        cast(ToolParam, {"type": "tool_search", "execution": "server"}),
        cast(
            ToolParam,
            {
                "type": "namespace",
                "name": "deferred",
                "tools": [
                    {"type": "custom", "name": "custom_tool"},
                    {"type": "tool_search", "execution": "server"},
                ],
            },
        ),
    ]

    for tool in discovered_tools:
        assert (
            tools_from_client_tool_search_output(
                tool,
                WEB_SEARCH_PROVIDERS,
                CODE_EXECUTION_PROVIDERS,
                False,
                tool_namespaces,
                tool_names,
            )
            == []
        )
    assert tool_namespaces == {}
    assert tool_names == {}


# 1. incoming tool_search param -> ToolInfo with marker + verbatim execution


def test_tool_from_responses_tool_tool_search() -> None:
    tool = tool_from_responses_tool(
        _tool_search_tool_param(),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool, ToolInfo)
    assert tool.name == TOOL_SEARCH_NAME
    assert tool.options is not None
    assert tool.options[TOOL_SEARCH_OPTIONS_MARKER] is True
    assert tool.options["execution"] == "client"
    assert tool.options["description"] == "Search for available tools"
    assert tool.options["parameters"] == _tool_search_tool_param()["parameters"]


def test_client_tool_search_keeps_schema_for_generic_provider() -> None:
    """Generic-provider serialization keeps the client discovery schema."""
    tool = tool_from_responses_tool(
        _tool_search_tool_param(),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool, ToolInfo)

    params = AnthropicAPI(
        model_name="claude-sonnet-4-6", api_key="test-key"
    ).tool_params_for_tool_info(tool, GenerateConfig())

    assert len(params) == 1
    param = cast(dict[str, Any], params[0])
    assert param["name"] == TOOL_SEARCH_NAME
    assert param["input_schema"] == _tool_search_tool_param()["parameters"]


@pytest.mark.parametrize(
    "tool_param",
    [
        cast(ToolParam, {"type": "tool_search"}),
        cast(ToolParam, {"type": "tool_search", "execution": "server"}),
        cast(ToolParam, {"type": "tool_search", "parameters": None}),
    ],
    ids=["omitted", "server", "null-schema"],
)
async def test_native_tool_search_allows_optional_parameters(
    tool_param: ToolParam,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI-native tool search preserves an omitted or null schema."""
    model = get_model("openai/gpt-4o", api_key="test-key", memoize=False)

    async def generate(*_args: Any, **_kwargs: Any) -> ModelOutput:
        return ModelOutput.from_content("openai/gpt-4o", "done")

    monkeypatch.setattr(model, "generate", generate)
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    response = await inspect_responses_api_request(
        {
            "model": "inspect",
            "input": [{"role": "user", "content": "Find a browser tool."}],
            "tools": [tool_param],
        },
        None,
        None,
        None,
        bridge,
    )

    assert response.output_text == "done"


# 2. ToolInfo -> native ToolSearchToolParam (and None for ordinary tools)


def test_maybe_tool_search_tool_emits_native_param() -> None:
    tool = tool_from_responses_tool(
        _tool_search_tool_param(),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool, ToolInfo)

    param = maybe_tool_search_tool(tool)
    assert param is not None
    assert param["type"] == "tool_search"
    assert param["execution"] == "client"

    # also reachable via the native-tool dispatch
    native = _maybe_native_tool_param(tool, "gpt-5", GenerateConfig())
    assert native is not None
    assert native["type"] == "tool_search"


def test_maybe_tool_search_tool_none_for_function_tool() -> None:
    ordinary = ToolInfo(name="read_file", description="Read a file")
    assert maybe_tool_search_tool(ordinary) is None


def test_is_tool_search_tool_param() -> None:
    assert is_tool_search_tool_param(_tool_search_tool_param()) is True
    assert (
        is_tool_search_tool_param(cast(ToolParam, _discoverable_function_tool()))
        is False
    )


# 3. assistant ToolCall(function="tool_search") -> ResponseToolSearchCall output


def test_output_items_emit_tool_search_call() -> None:
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="ts_1",
                function=TOOL_SEARCH_NAME,
                arguments={"query": "file tools"},
            )
        ],
    )
    items = responses_output_items_from_assistant_message(message)
    search_calls = [i for i in items if i.type == "tool_search_call"]
    assert len(search_calls) == 1
    call = search_calls[0]
    assert call.call_id == "ts_1"
    assert call.arguments == {"query": "file tools"}
    assert call.execution == "client"


# 3b. deferred namespace tools (discovered via tool_search) restore `namespace`
#
# codex-cli dispatches namespaced tools by (namespace, name); a function call
# with a missing namespace is rejected with "unsupported call: <name>". The
# multi_agent tools are not declared in the top-level `tools` array - they are
# discovered via tool_search and appear only inside tool_search_output items, so
# the namespace mapping must be harvested from there.


def test_harvest_tool_namespaces_from_tool_search_output() -> None:
    from inspect_ai.agent._bridge.responses_impl import _harvest_tool_namespaces

    namespace_tool = {
        "type": "namespace",
        "name": "multi_agent_v1",
        "description": "Tools for spawning and managing sub-agents.",
        "tools": [
            {"type": "function", "name": "spawn_agent"},
            {"type": "function", "name": "wait_agent"},
        ],
    }
    tool_namespaces: dict[str, tuple[str, str]] = {}
    _harvest_tool_namespaces(namespace_tool, tool_namespaces)
    assert tool_namespaces == {
        "spawn_agent": ("spawn_agent", "multi_agent_v1"),
        "wait_agent": ("wait_agent", "multi_agent_v1"),
    }


def test_output_items_restore_namespace_for_deferred_tool() -> None:
    from inspect_ai.agent._bridge.responses_impl import _harvest_tool_namespaces

    # mapping as harvested from a tool_search_output namespace entry
    tool_namespaces: dict[str, tuple[str, str]] = {}
    _harvest_tool_namespaces(
        {"name": "multi_agent_v1", "tools": [{"name": "spawn_agent"}]},
        tool_namespaces,
    )

    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="c1",
                function="spawn_agent",
                arguments={"agent_type": "explorer", "message": "find the OS version"},
            )
        ],
    )
    items = responses_output_items_from_assistant_message(message, tool_namespaces)
    calls = [i for i in items if i.type == "function_call"]
    assert len(calls) == 1
    assert calls[0].name == "spawn_agent"
    assert calls[0].namespace == "multi_agent_v1"


def test_output_items_restore_stored_raw_name_for_generic_tool() -> None:
    """A generic provider name maps back to the original Responses identity."""
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="browser_1",
                function="generic_browser",
                arguments={"action": "screenshot"},
            )
        ],
    )
    items = responses_output_items_from_assistant_message(
        message,
        {"generic_browser": ("browser", "mcp__browser_tools")},
    )
    calls = [item for item in items if item.type == "function_call"]

    assert len(calls) == 1
    assert calls[0].call_id == "browser_1"
    assert calls[0].name == "browser"
    assert calls[0].namespace == "mcp__browser_tools"
    assert calls[0].arguments == '{"action": "screenshot"}'


def test_output_items_no_namespace_for_plain_tool() -> None:
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="c1", function="exec_command", arguments={"cmd": "ls"})
        ],
    )
    items = responses_output_items_from_assistant_message(message, {})
    calls = [i for i in items if i.type == "function_call"]
    assert len(calls) == 1
    assert calls[0].namespace is None


# 3c. externally-sourced namespaced calls (codex --resume) replay with namespace
#
# On checkpoint restore the bridge runs in a fresh process: the provider's
# assistant_internal cache is empty, so a namespaced function call replayed from
# codex's rollout would otherwise lose its namespace on the way to the real
# model. The bridge seeds the cache from the inbound call so the existing
# warm-path replay carries the namespace.


def test_resume_namespaced_call_replays_with_namespace() -> None:
    from inspect_ai.model._openai_responses import (
        _tool_call_items_from_assistant_message,
        init_sample_openai_assistant_internal,
    )

    init_sample_openai_assistant_internal()  # fresh process -> empty cache

    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "spawn_agent",
                "namespace": "multi_agent_v1",
                "arguments": '{"agent_type": "explorer"}',
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "done"},
        ],
    )
    messages = messages_from_responses_input(input_items, [], "openai/gpt-5")
    assistant = next(m for m in messages if isinstance(m, ChatMessageAssistant))

    replayed = _tool_call_items_from_assistant_message(assistant)
    call = cast(
        dict[str, Any],
        next(i for i in replayed if i.get("type") == "function_call"),
    )
    assert call["name"] == "spawn_agent"
    assert call.get("namespace") == "multi_agent_v1"


def test_resume_seed_does_not_clobber_in_sample_call() -> None:
    from inspect_ai.model._openai_responses import (
        assistant_internal,
        init_sample_openai_assistant_internal,
    )

    init_sample_openai_assistant_internal()
    # richer param as cached by the provider for an in-sample generation
    assistant_internal().tool_calls["call_1"] = {
        "type": "function_call",
        "id": "fc_real",
        "call_id": "call_1",
        "name": "spawn_agent",
        "namespace": "multi_agent_v1",
        "arguments": "{}",
        "status": "completed",
    }

    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "spawn_agent",
                "namespace": "multi_agent_v1",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "x"},
        ],
    )
    messages_from_responses_input(input_items, [], "openai/gpt-5")

    cached = assistant_internal().tool_calls["call_1"]
    assert cached.get("id") == "fc_real"
    assert cached.get("status") == "completed"


def test_resume_plain_call_not_seeded() -> None:
    from inspect_ai.model._openai_responses import (
        assistant_internal,
        init_sample_openai_assistant_internal,
    )

    init_sample_openai_assistant_internal()
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "function_call",
                "call_id": "c2",
                "name": "exec_command",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "c2", "output": "x"},
        ],
    )
    messages_from_responses_input(input_items, [], "openai/gpt-5")
    assert "c2" not in assistant_internal().tool_calls


# 4. inbound [call, output] -> assistant ToolCall + ChatMessageTool with tools json


def test_messages_from_responses_input_round_trip() -> None:
    tools_list = [_discoverable_function_tool()]
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "tool_search_call",
                "id": "x1",
                "call_id": "ts_1",
                "arguments": {"query": "file tools"},
                "execution": "client",
                "status": "completed",
            },
            {
                "type": "tool_search_output",
                "call_id": "ts_1",
                "tools": tools_list,
                "execution": "client",
                "status": "completed",
            },
        ],
    )

    messages = messages_from_responses_input(input_items, [], "openai/gpt-5")
    assert len(messages) == 2

    assistant = messages[0]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].function == TOOL_SEARCH_NAME
    assert assistant.tool_calls[0].id == "ts_1"
    assert assistant.tool_calls[0].arguments == {"query": "file tools"}

    tool_msg = messages[1]
    assert isinstance(tool_msg, ChatMessageTool)
    assert tool_msg.function == TOOL_SEARCH_NAME
    assert tool_msg.tool_call_id == "ts_1"
    assert isinstance(tool_msg.content, str)
    assert json.loads(tool_msg.content) == tools_list


# 5. full replay: inbound -> provider input items (call then output, tools intact)


async def test_full_replay_to_openai_input_items() -> None:
    init_sample_openai_assistant_internal()

    tools_list = [_discoverable_function_tool()]
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "tool_search_call",
                "id": "x1",
                "call_id": "ts_1",
                "arguments": {"query": "file tools"},
                "execution": "client",
                "status": "completed",
            },
            {
                "type": "tool_search_output",
                "call_id": "ts_1",
                "tools": tools_list,
                "execution": "client",
                "status": "completed",
            },
        ],
    )
    messages = messages_from_responses_input(input_items, [], "openai/gpt-5")

    replayed = []
    for message in messages:
        replayed.extend(await _openai_input_item_from_chat_message(message))

    types = [item["type"] for item in replayed]
    assert types.index("tool_search_call") < types.index("tool_search_output")

    call = next(i for i in replayed if i["type"] == "tool_search_call")
    assert call["call_id"] == "ts_1"
    assert call["arguments"] == {"query": "file tools"}

    output = next(i for i in replayed if i["type"] == "tool_search_output")
    assert output["call_id"] == "ts_1"
    assert list(output["tools"]) == tools_list


# 6. namespace-wrapped tools survive repeated serialization (regression)
#
# NamespaceToolParam.tools (and the outer tools field) are typed `Iterable`, so
# validating the carried JSON yields lazy single-consumption ValidatorIterators.
# inspect serializes the request for the transcript before the OpenAI client
# serializes it for the wire; if the iterator isn't materialized the second pass
# sees an empty list and OpenAI rejects it ("empty array, minimum length 1").


def _namespace_tools_list() -> list[dict[str, Any]]:
    return [
        {
            "type": "namespace",
            "name": "multi_agent_v1",
            "description": "Tools for spawning and managing sub-agents.",
            "tools": [
                {
                    "type": "function",
                    "name": "spawn_agent",
                    "defer_loading": True,
                    "description": "Spawn a sub-agent",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": False,
                },
                {
                    "type": "function",
                    "name": "wait_agent",
                    "defer_loading": True,
                    "description": "Wait for an agent",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": False,
                },
            ],
        }
    ]


async def test_namespace_tools_survive_repeated_serialization() -> None:
    init_sample_openai_assistant_internal()

    tools_list = _namespace_tools_list()
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "tool_search_call",
                "id": "x1",
                "call_id": "ts_1",
                "arguments": {"query": "subagents"},
                "execution": "client",
                "status": "completed",
            },
            {
                "type": "tool_search_output",
                "call_id": "ts_1",
                "tools": tools_list,
                "execution": "client",
                "status": "completed",
            },
        ],
    )
    messages = messages_from_responses_input(input_items, [], "openai/gpt-5")

    replayed = []
    for message in messages:
        replayed.extend(await _openai_input_item_from_chat_message(message))

    output = next(i for i in replayed if i["type"] == "tool_search_output")

    # serialize twice: the nested namespace tools must remain populated both times
    first = json.loads(json.dumps(output))
    second = json.loads(json.dumps(output))
    assert first["tools"][0]["tools"], "nested namespace tools empty on first pass"
    assert second["tools"][0]["tools"], "nested namespace tools empty on second pass"
    assert first == second
    assert [t["name"] for t in first["tools"][0]["tools"]] == [
        "spawn_agent",
        "wait_agent",
    ]


# 7. provider parse: ResponseToolSearchCall -> ToolCall + cached param


def test_process_response_output_items_tool_search_call() -> None:
    from openai.types.responses import ResponseToolSearchCall

    from inspect_ai.model._openai_responses import assistant_internal

    init_sample_openai_assistant_internal()

    output = ResponseToolSearchCall(
        id="x1",
        call_id="ts_1",
        arguments={"query": "file tools"},
        execution="client",
        status="completed",
        type="tool_search_call",
    )
    _content, tool_calls, _logprobs, has_tool_calls = _process_response_output_items(
        [output], []
    )
    assert has_tool_calls is True
    assert len(tool_calls) == 1
    assert tool_calls[0].function == TOOL_SEARCH_NAME
    assert tool_calls[0].id == "ts_1"
    # raw param cached (keyed by call_id) for verbatim replay within the sample
    cached = assistant_internal().tool_calls.get("ts_1")
    assert cached is not None
    assert cached["type"] == "tool_search_call"


# 7b. tool-message replay only emits native tool_search_output when the original
# call was a tool_search_call. A user/function tool named "tool_search" (cached as
# a function_call, or uncached) must replay as a normal function_call_output.


async def test_tool_search_output_replay_gated_on_cached_call() -> None:
    from inspect_ai.model._openai_responses import (
        assistant_internal,
        init_sample_openai_assistant_internal,
    )

    init_sample_openai_assistant_internal()  # cold cache

    # an ordinary function tool that happens to be named "tool_search"
    ordinary = ChatMessageTool(
        tool_call_id="c1", function="tool_search", content="ordinary result"
    )
    items = await _openai_input_item_from_chat_message(ordinary)
    assert len(items) == 1
    assert items[0]["type"] == "function_call_output"

    # once the original call is cached as a tool_search_call, replay is native
    assistant_internal().tool_calls["c2"] = {
        "type": "tool_search_call",
        "id": "c2",
        "call_id": "c2",
        "arguments": {"query": "x"},
        "execution": "client",
        "status": "completed",
    }
    native = ChatMessageTool(
        tool_call_id="c2",
        function="tool_search",
        content=json.dumps([_discoverable_function_tool()]),
    )
    items2 = await _openai_input_item_from_chat_message(native)
    assert len(items2) == 1
    assert items2[0]["type"] == "tool_search_output"
    assert list(items2[0]["tools"]) == [_discoverable_function_tool()]


# 8. compaction does not clear tool_search results (tool definitions = context)


async def test_compaction_does_not_clear_tool_search() -> None:
    from inspect_ai.model import ChatMessageUser
    from inspect_ai.model._compaction.edit import TOOL_RESULT_REMOVED, CompactionEdit
    from inspect_ai.model._model import get_model

    tools_json = json.dumps([_discoverable_function_tool()])
    messages: list[ChatMessage] = [
        ChatMessageUser(content="find tools then read a file"),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id="ts_1", function=TOOL_SEARCH_NAME, arguments={"query": "files"}
                ),
                ToolCall(id="fn_1", function="read_file", arguments={"path": "/tmp/x"}),
            ],
        ),
        ChatMessageTool(
            tool_call_id="ts_1", function=TOOL_SEARCH_NAME, content=tools_json
        ),
        ChatMessageTool(tool_call_id="fn_1", function="read_file", content="file body"),
        ChatMessageUser(content="thanks"),
    ]

    # keep_tool_uses=0 -> clear every (clearable) tool result
    strategy = CompactionEdit(keep_tool_uses=0, keep_tool_inputs=True)
    compacted, _ = await strategy.compact(get_model("mockllm/model"), messages, [])

    by_id = {m.tool_call_id: m for m in compacted if isinstance(m, ChatMessageTool)}
    # tool_search result preserved (carries discovered tool defs, not a result)
    assert by_id["ts_1"].content == tools_json
    # ordinary tool result cleared
    assert by_id["fn_1"].content == TOOL_RESULT_REMOVED
