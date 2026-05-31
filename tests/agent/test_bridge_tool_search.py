"""Unit tests for tool_search passthrough in the Responses agent bridge.

tool_search (execution="client") is a client-resolved built-in tool: the model
emits a ``tool_search_call``, the scaffold (e.g. codex-cli) resolves it locally
and returns a ``tool_search_output`` with the discovered tools. These tests cover
the full round-trip through the bridge + provider conversion helpers (no network).
"""

from __future__ import annotations

import json
from typing import Any, cast

from openai.types.responses import ResponseInputItemParam, ToolParam

from inspect_ai.agent._bridge.responses_impl import (
    messages_from_responses_input,
    responses_output_items_from_assistant_message,
    tool_from_responses_tool,
)
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._generate_config import GenerateConfig
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
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

WEB_SEARCH_PROVIDERS: Any = {}
CODE_EXECUTION_PROVIDERS: Any = {}


def _tool_search_tool_param() -> ToolParam:
    return cast(
        ToolParam,
        {
            "type": "tool_search",
            "description": "Search for available tools",
            "execution": "client",
            "parameters": {"type": "object", "properties": {}},
        },
    )


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


# 1. incoming tool_search param -> ToolInfo with marker + verbatim execution


def test_tool_from_responses_tool_tool_search() -> None:
    tool = tool_from_responses_tool(
        _tool_search_tool_param(), WEB_SEARCH_PROVIDERS, CODE_EXECUTION_PROVIDERS
    )
    assert isinstance(tool, ToolInfo)
    assert tool.name == TOOL_SEARCH_NAME
    assert tool.options is not None
    assert tool.options[TOOL_SEARCH_OPTIONS_MARKER] is True
    assert tool.options["execution"] == "client"
    assert tool.options["description"] == "Search for available tools"


# 2. ToolInfo -> native ToolSearchToolParam (and None for ordinary tools)


def test_maybe_tool_search_tool_emits_native_param() -> None:
    tool = tool_from_responses_tool(
        _tool_search_tool_param(), WEB_SEARCH_PROVIDERS, CODE_EXECUTION_PROVIDERS
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
    tool_namespaces: dict[str, str] = {}
    _harvest_tool_namespaces(namespace_tool, tool_namespaces)
    assert tool_namespaces == {
        "spawn_agent": "multi_agent_v1",
        "wait_agent": "multi_agent_v1",
    }


def test_output_items_restore_namespace_for_deferred_tool() -> None:
    from inspect_ai.agent._bridge.responses_impl import _harvest_tool_namespaces

    # mapping as harvested from a tool_search_output namespace entry
    tool_namespaces: dict[str, str] = {}
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


# 8. compaction does not clear tool_search results (tool definitions = context)


async def test_compaction_does_not_clear_tool_search() -> None:
    from inspect_ai.model import ChatMessage, ChatMessageUser
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
