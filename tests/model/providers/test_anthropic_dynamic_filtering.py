"""Tests for Anthropic web search dynamic filtering replay (issue #4191).

With the `web_search_20260209` / `web_fetch_20260209` tool versions, web
searches run inside the code execution sandbox and come back as a nested
block sequence (code_execution use -> web_search use w/ caller link ->
web_search result -> code_execution result). The API requires that this
structure -- block order, nesting, and `caller` source links -- be replayed
exactly on subsequent turns, otherwise it fails with
`source tool ... not found for tool use block ...`.
"""

import types
from typing import Any, cast
from unittest.mock import AsyncMock, create_autospec

from anthropic import AsyncAnthropic
from anthropic.types import Message
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util.content import ContentToolUse
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._compaction.edit import TOOL_RESULT_REMOVED
from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    assistant_message_block_params,
    assistant_message_blocks,
    content_and_tool_calls_from_assistant_content_blocks,
    init_sample_anthropic_assistant_internal,
    model_output_from_message,
)
from inspect_ai.tool import ToolCall

CE_ID = "srvtoolu_011"
WS_ID = "srvtoolu_014"
WS2_ID = "srvtoolu_015"


def _ce_use(id: str = CE_ID) -> dict[str, Any]:
    return {
        "type": "server_tool_use",
        "id": id,
        "name": "code_execution",
        "input": {"code": "results = web_search('nhl scores')"},
        "caller": {"type": "direct"},
    }


def _ws_use(id: str = WS_ID, caller_id: str = CE_ID) -> dict[str, Any]:
    return {
        "type": "server_tool_use",
        "id": id,
        "name": "web_search",
        "input": {"query": "nhl scores last night"},
        "caller": {"type": "code_execution_20260120", "tool_id": caller_id},
    }


def _ws_result(id: str = WS_ID, caller_id: str = CE_ID) -> dict[str, Any]:
    return {
        "type": "web_search_tool_result",
        "tool_use_id": id,
        "content": [
            {
                "type": "web_search_result",
                "title": "NHL Scores",
                "url": "https://nhl.com/scores",
                "encrypted_content": "ENCRYPTED_CONTENT",
            }
        ],
        "caller": {"type": "code_execution_20260120", "tool_id": caller_id},
    }


def _ce_result(id: str = CE_ID) -> dict[str, Any]:
    return {
        "type": "code_execution_tool_result",
        "tool_use_id": id,
        "content": {
            "type": "encrypted_code_execution_result",
            "encrypted_stdout": "ENCRYPTED_STDOUT",
            "return_code": 0,
            "stderr": "",
            "content": [],
        },
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


NESTED_SEARCH_CONTENT: list[dict[str, Any]] = [
    _text("Let me search for that."),
    _ce_use(),
    _ws_use(),
    _ws_result(),
    _ce_result(),
    _text("The Bruins won 3-2."),
]


def _message(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


async def _parse(content: list[dict[str, Any]]) -> ChatMessageAssistant:
    output, _ = await model_output_from_message(
        client=None, model="claude-opus-4-8", message=_message(content), tools=[]
    )
    return output.message


def _content(message: ChatMessageAssistant) -> list[Any]:
    assert isinstance(message.content, list)
    return cast(list[Any], message.content)


def _tool_uses(message: ChatMessageAssistant) -> list[ContentToolUse]:
    return [c for c in _content(message) if isinstance(c, ContentToolUse)]


async def _replay(message: ChatMessageAssistant) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], await assistant_message_block_params(message))


def _signatures(blocks: list[dict[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [
        (b["type"], b.get("id") or b.get("tool_use_id"), b.get("caller"))
        for b in blocks
    ]


async def test_nested_filtered_search_round_trip() -> None:
    """Replay must restore exact wire order, nesting, and caller links."""
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    # parse flattens to content items in result-arrival order
    assert [(c.tool_type, c.id) for c in _tool_uses(assistant)] == [
        ("web_search", WS_ID),
        ("code_execution", CE_ID),
    ]

    # replay restores the original wire order with callers intact
    assert _signatures(await _replay(assistant)) == _signatures(NESTED_SEARCH_CONTENT)


async def test_edit_reflection_without_server_tools() -> None:
    """Messages without server tools take the per-content path (edits surface)."""
    init_sample_anthropic_assistant_internal()
    message = ChatMessageAssistant(
        content="original",
        tool_calls=[ToolCall(id="toolu_1", function="f", arguments={"x": 1})],
        model="claude-opus-4-8",
    )
    message.content = "edited text"
    block_params = await _replay(message)
    assert block_params[0] == {"type": "text", "text": "edited text"}
    assert block_params[1]["type"] == "tool_use"


async def test_mixed_turn_prose_edits_surface_with_verbatim_span() -> None:
    """Prose edits are reflected while the server tool span replays verbatim."""
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    _content(assistant)[0].text = "EDITED LEADING"
    _content(assistant)[-1].text = "EDITED TRAILING"

    block_params = await _replay(assistant)
    assert block_params[0]["text"] == "EDITED LEADING"
    assert block_params[-1]["text"] == "EDITED TRAILING"
    assert _signatures(block_params) == _signatures(NESTED_SEARCH_CONTENT)


async def test_multiple_searches_one_code_block() -> None:
    """Two web searches nested in one code execution block form one span."""
    init_sample_anthropic_assistant_internal()
    content = [
        _ce_use(),
        _ws_use(WS_ID),
        _ws_result(WS_ID),
        _ws_use(WS2_ID),
        _ws_result(WS2_ID),
        _ce_result(),
        _text("Done."),
    ]
    assistant = await _parse(content)

    assert [c.id for c in _tool_uses(assistant)] == [WS_ID, WS2_ID, CE_ID]
    assert _signatures(await _replay(assistant)) == _signatures(content)


async def test_multiple_spans_interleaved_with_text() -> None:
    """Back-to-back and text-separated spans split and replay in order."""
    init_sample_anthropic_assistant_internal()
    content = [
        _text("First I'll search."),
        _ce_use("srvtoolu_ce1"),
        _ws_use("srvtoolu_ws1", "srvtoolu_ce1"),
        _ws_result("srvtoolu_ws1", "srvtoolu_ce1"),
        _ce_result("srvtoolu_ce1"),
        # back-to-back span (no delimiter between this and the previous span)
        _ce_use("srvtoolu_ce2"),
        _ws_use("srvtoolu_ws2", "srvtoolu_ce2"),
        _ws_result("srvtoolu_ws2", "srvtoolu_ce2"),
        _ce_result("srvtoolu_ce2"),
        _text("Now another."),
        _ce_use("srvtoolu_ce3"),
        _ws_use("srvtoolu_ws3", "srvtoolu_ce3"),
        _ws_result("srvtoolu_ws3", "srvtoolu_ce3"),
        _ce_result("srvtoolu_ce3"),
        _text("All done."),
    ]
    assistant = await _parse(content)
    assert _signatures(await _replay(assistant)) == _signatures(content)


async def test_deleted_span_items_drop_span() -> None:
    """If a scaffold removes all of a span's content items the span is dropped."""
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    # remove both server tool content items
    assistant.content = [
        c for c in _content(assistant) if not isinstance(c, ContentToolUse)
    ]

    block_params = await _replay(assistant)
    assert [b["type"] for b in block_params] == ["text", "text"]


async def test_compaction_clearing_on_nested_span() -> None:
    """Clearing one result substitutes a placeholder without breaking structure."""
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    # clear the inner web search result (as edit compaction does)
    ws_content = _tool_uses(assistant)[0]
    assert ws_content.id == WS_ID
    ws_content.result = TOOL_RESULT_REMOVED

    block_params = await _replay(assistant)

    # order, nesting, and callers unchanged
    assert [(b["type"], b.get("id") or b.get("tool_use_id")) for b in block_params] == [
        (b["type"], b.get("id") or b.get("tool_use_id")) for b in NESTED_SEARCH_CONTENT
    ]

    # web search result cleared, code execution result untouched
    ws_result = next(b for b in block_params if b["type"] == "web_search_tool_result")
    assert ws_result["content"] == {
        "type": "web_search_tool_result_error",
        "error_code": "unavailable",
    }
    ce_result = next(
        b for b in block_params if b["type"] == "code_execution_tool_result"
    )
    assert ce_result["content"]["encrypted_stdout"] == "ENCRYPTED_STDOUT"

    # the recorded span itself was not mutated: un-clear and replay again
    ws_content.result = "restored"
    block_params = await _replay(assistant)
    ws_result = next(b for b in block_params if b["type"] == "web_search_tool_result")
    assert ws_result["content"][0]["encrypted_content"] == "ENCRYPTED_CONTENT"


async def test_replay_with_rewritten_message_id() -> None:
    """Replay falls back to the tool use id index for rewritten message ids.

    The agent bridge rewrites message ids -- server tool use ids survive
    the bridge so replay resolves spans through the tool use id index.
    """
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    assistant.id = "rewritten-by-bridge"
    assert _signatures(await _replay(assistant)) == _signatures(NESTED_SEARCH_CONTENT)


async def test_foreign_server_tools_normalize_via_fall_through() -> None:
    """Foreign server tool content still normalizes via the fall-through.

    Server tool content with no recorded span (e.g. from another system)
    normalizes to schema-valid use/result pairs.
    """
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    # fresh internal state simulates content originating elsewhere
    init_sample_anthropic_assistant_internal()
    block_params = await _replay(assistant)
    assert [b["type"] for b in block_params] == [
        "text",
        "server_tool_use",
        "web_search_tool_result",
        "server_tool_use",
        "bash_code_execution_tool_result",
        "text",
    ]


async def test_history_reparse_fills_tool_use_index() -> None:
    """History re-parse registers spans in the tool use id index.

    Re-parsing conversation history (bridge style, dict blocks) registers
    spans in the tool use id index so replay works after the original
    generate-time records are gone.
    """
    init_sample_anthropic_assistant_internal()
    content, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        cast(list[Any], NESTED_SEARCH_CONTENT), tools=[]
    )
    assistant = ChatMessageAssistant(
        content=content, tool_calls=tool_calls, model="claude-opus-4-8"
    )
    assert _signatures(await _replay(assistant)) == _signatures(NESTED_SEARCH_CONTENT)


async def test_assistant_message_blocks_preserves_caller() -> None:
    """Bridge output rendering must carry real callers (not force direct)."""
    init_sample_anthropic_assistant_internal()
    assistant = await _parse(NESTED_SEARCH_CONTENT)

    blocks = cast(list[Any], await assistant_message_blocks(assistant, beta=True))
    server_uses = {b.id: b for b in blocks if b.type == "server_tool_use"}
    assert server_uses[CE_ID].caller.type == "direct"
    assert server_uses[WS_ID].caller.type == "code_execution_20260120"
    assert server_uses[WS_ID].caller.tool_id == CE_ID
    # the full block sequence (including code_execution_tool_result) round trips
    assert [b.type for b in blocks] == [b["type"] for b in NESTED_SEARCH_CONTENT]


async def test_pause_turn_split_span_continuation() -> None:
    """A span can straddle a pause_turn continuation.

    The span's use block arrives in the head message and its result in the
    tail -- the recorder is threaded through continuations and the record is
    merged under the final message id. The code execution container is also
    reused for the continuation request.
    """
    init_sample_anthropic_assistant_internal()

    head_message = Message.model_validate(
        {
            "id": "msg_head",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "stop_reason": "pause_turn",
            "content": [_text("Searching..."), _ce_use(), _ws_use(), _ws_result()],
            "container": {"id": "container_abc", "expires_at": "2026-06-10T12:00:00Z"},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    tail_message = Message.model_validate(
        {
            "id": "msg_tail",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "stop_reason": "end_turn",
            "content": [_ce_result(), _text("The Bruins won 3-2.")],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )

    api = create_autospec(AnthropicAPI, instance=True)
    api._batcher = None
    api.model_name = "claude-opus-4-8"
    api.service_model_name.return_value = "claude-opus-4-8"
    api.cache_diagnostics_enabled.return_value = False

    client = create_autospec(AsyncAnthropic, instance=True)
    client.messages.create = AsyncMock(side_effect=[head_message, tail_message])
    api.client = client

    # bind the real method so recursive continuation calls work
    api._perform_request_and_continuations = types.MethodType(
        AnthropicAPI._perform_request_and_continuations, api
    )

    _, output = await api._perform_request_and_continuations(
        request={"messages": []},
        streaming=False,
        tools=[],
        config=GenerateConfig(),
    )

    # the continuation request reused the head message's container
    continuation_kwargs = client.messages.create.call_args_list[1].kwargs
    assert continuation_kwargs["container"] == "container_abc"

    # merged message replays the full span in wire order with callers intact
    merged = output.message
    assert [c.id for c in _tool_uses(merged)] == [WS_ID, CE_ID]
    assert _signatures(await _replay(merged)) == _signatures(
        [
            _text("Searching..."),
            _ce_use(),
            _ws_use(),
            _ws_result(),
            _ce_result(),
            _text("The Bruins won 3-2."),
        ]
    )


@skip_if_no_anthropic
async def test_anthropic_dynamic_filtering_multi_turn() -> None:
    """Live multi-turn smoke test for web search dynamic filtering.

    A follow-up turn after a dynamically filtered web search must not fail
    with `source tool ... not found`.
    """
    from inspect_ai.tool import web_search

    model = get_model("anthropic/claude-opus-4-8")
    tools = [web_search("anthropic")]

    messages: list[ChatMessage] = [
        ChatMessageUser(
            content="Search the web for the scores of last night's NHL games. "
            "Filter the search results to only games decided by one goal."
        )
    ]
    output = await model.generate(input=messages, tools=tools)

    # confirm a *filtered* (nested) search actually ran: dynamic filtering
    # runs the search inside a code execution block, so the content must
    # include both tool types (otherwise this test isn't exercising the
    # nested replay path)
    tool_types = {c.tool_type for c in _tool_uses(output.message)}
    assert "web_search" in tool_types
    assert "code_execution" in tool_types

    # follow-up turn replays the assistant turn -- this is what previously
    # failed with `source tool ... not found`
    messages = messages + [
        output.message,
        ChatMessageUser(content="Which of those games went to overtime?"),
    ]
    output = await model.generate(input=messages, tools=tools)
    assert output.message.text

    # third turn replays multiple searched turns
    messages = messages + [
        output.message,
        ChatMessageUser(content="And which game had the highest total score?"),
    ]
    output = await model.generate(input=messages, tools=tools)
    assert output.message.text
