"""Unit tests for `additional_tools` handling in the Responses agent bridge.

Newer OpenAI models (and CLI scaffolds like codex >= 0.144) declare tools via
`additional_tools` input items rather than the request's top-level `tools`
array. The bridge must (a) not choke on the item when converting input to
messages, and (b) forward the declared tools to the model with their original
schemas preserved verbatim -- reconstructing a tool param from a `ToolInfo` is
lossy and breaks models that validate reserved tool schemas byte-for-byte.

These tests cover the conversion helpers directly (no network). The end-to-end
merge of `additional_tools` into the generate() tool set lives in
`inspect_responses_api_request_impl`, which requires a live bridge/model and is
exercised by the `--runapi`-gated bridge tests.
"""

from __future__ import annotations

from typing import Any, cast

from openai.types.responses import ResponseInputItemParam

from inspect_ai.agent._bridge.responses_impl import (
    messages_from_responses_input,
    tool_from_responses_tool,
)
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._openai_responses import (
    RESPONSES_VERBATIM,
    is_additional_tools,
    openai_responses_tools,
)
from inspect_ai.tool._tool_info import ToolInfo

WEB_SEARCH_PROVIDERS: Any = {}
CODE_EXECUTION_PROVIDERS: Any = {}

MODEL_NAME = "openai/gpt-5.6"


def _reserved_function_tool() -> dict[str, Any]:
    # mimics a codex `collaboration.*` tool: carries a JSON-schema extension
    # (`encrypted`) and an explicit `strict` that lossy reconstruction drops.
    return {
        "type": "function",
        "name": "collaboration.request_input",
        "description": "reserved collaboration tool",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "additionalProperties": False,
            "encrypted": True,
        },
        "strict": True,
    }


def _custom_tool() -> dict[str, Any]:
    return {
        "type": "custom",
        "name": "exec",
        "description": "run a shell command",
        "format": {"type": "text"},
    }


def _additional_tools_item(*tools: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "additional_tools",
        "role": "developer",
        "tools": list(tools),
        "id": "at_1",
    }


# 1. is_additional_tools predicate


def test_is_additional_tools_predicate() -> None:
    assert is_additional_tools(cast(ResponseInputItemParam, _additional_tools_item()))
    assert not is_additional_tools(
        cast(ResponseInputItemParam, _reserved_function_tool())
    )
    assert not is_additional_tools(
        cast(
            ResponseInputItemParam,
            {"type": "message", "role": "user", "content": "hi"},
        )
    )


# 2. converting input containing an additional_tools item does not raise and
#    produces no spurious message (regression: it previously raised
#    "Type additional_tools is not supported by the agent bridge")


def test_messages_from_responses_input_skips_additional_tools() -> None:
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
            _additional_tools_item(_custom_tool()),
        ],
    )

    messages = messages_from_responses_input(input_items, [], MODEL_NAME)

    # only the user message survives; the additional_tools item is not a message
    assert len(messages) == 1
    assert isinstance(messages[0], ChatMessageUser)
    assert messages[0].text == "hello"


def test_messages_from_responses_input_additional_tools_only() -> None:
    # an input that is *only* an additional_tools declaration yields no messages
    input_items = cast(
        list[ResponseInputItemParam],
        [_additional_tools_item(_reserved_function_tool())],
    )
    assert messages_from_responses_input(input_items, [], MODEL_NAME) == []


# 3. a converted function/custom tool is re-emitted verbatim, preserving schema
#    extensions that lossy reconstruction would drop


def _emit(tool_info: ToolInfo) -> dict[str, Any]:
    param = openai_responses_tools([tool_info], MODEL_NAME, GenerateConfig(), True)[0]
    return dict(param)


def test_function_tool_round_trips_verbatim() -> None:
    original = _reserved_function_tool()
    tool_info = tool_from_responses_tool(
        cast(Any, original),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool_info, ToolInfo)
    assert RESPONSES_VERBATIM in (tool_info.options or {})

    # verbatim: byte-for-byte identical to what the client declared
    assert _emit(tool_info) == original


def test_custom_tool_round_trips_verbatim() -> None:
    original = _custom_tool()
    tool_info = tool_from_responses_tool(
        cast(Any, original),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool_info, ToolInfo)
    assert RESPONSES_VERBATIM in (tool_info.options or {})

    assert _emit(tool_info) == original


def test_reconstruction_without_verbatim_drifts() -> None:
    # documents *why* verbatim is required: dropping the stashed param forces
    # reconstruction from ToolInfo, which drops schema extensions and
    # normalizes fields -> drift that reserved-schema models reject (HTTP 400).
    original = _reserved_function_tool()
    tool_info = tool_from_responses_tool(
        cast(Any, original),
        WEB_SEARCH_PROVIDERS,
        CODE_EXECUTION_PROVIDERS,
        allow_remote_mcp=True,
    )
    assert isinstance(tool_info, ToolInfo)

    stripped = tool_info.model_copy(
        update={
            "options": {
                k: v
                for k, v in (tool_info.options or {}).items()
                if k != RESPONSES_VERBATIM
            }
        }
    )
    reconstructed = _emit(stripped)

    assert reconstructed != original
    # the schema extension is lost on the reconstruction path
    assert "encrypted" not in reconstructed["parameters"]
