from pathlib import Path
from typing import Any, cast

import pytest
from anthropic.types import ThinkingBlockParam

from inspect_ai._util.constants import NO_CONTENT
from inspect_ai._util.content import ContentDocument, ContentReasoning, ContentText
from inspect_ai._util.hash import mm3_hash
from inspect_ai.agent._bridge.anthropic_api_impl import (
    anthropic_system_to_texts,
    base_64_data,
    content_block_to_content,
    messages_from_anthropic_input,
    tools_from_anthropic_tools,
)
from inspect_ai.agent._bridge.util import (
    internal_web_search_providers,
    resolve_bridge_web_search,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._openai_convert import messages_from_openai
from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    assistant_internal,
    assistant_message_block_params,
    init_sample_anthropic_assistant_internal,
    message_block_params,
)
from inspect_ai.tool import ToolCall, WebSearchProviders
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_util import tool_to_tool_info


@pytest.mark.anyio
async def test_inline_system_role_str_content() -> None:
    """Claude 4.8+ clients may send role="system" inside the messages array."""
    messages = await messages_from_anthropic_input(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "system", "content": "<system-reminder>note</system-reminder>"},
            {"role": "user", "content": "continue"},
        ],
        tools=[],
    )
    assert [type(m) for m in messages] == [
        ChatMessageUser,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    ]
    assert messages[2].text == "<system-reminder>note</system-reminder>"


@pytest.mark.anyio
async def test_inline_system_role_block_content() -> None:
    messages = await messages_from_anthropic_input(
        [
            {"role": "user", "content": "hello"},
            {
                "role": "system",
                "content": [{"type": "text", "text": "reminder"}],
            },
        ],
        tools=[],
    )
    assert isinstance(messages[1], ChatMessageSystem)
    assert messages[1].text == "reminder"


@pytest.mark.anyio
async def test_inline_system_role_multi_block_content() -> None:
    """A role="system" turn with multiple blocks keeps one message per block."""
    messages = await messages_from_anthropic_input(
        [
            {"role": "user", "content": "hello"},
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "x-anthropic-billing-header: abc"},
                    {"type": "text", "text": "instructions"},
                ],
            },
        ],
        tools=[],
    )
    assert [type(m) for m in messages] == [
        ChatMessageUser,
        ChatMessageSystem,
        ChatMessageSystem,
    ]
    assert messages[1].text == "x-anthropic-billing-header: abc"
    assert messages[2].text == "instructions"


@pytest.mark.anyio
async def test_inline_text_document_round_trip() -> None:
    content = content_block_to_content(
        cast(
            Any,
            {
                "type": "document",
                "source": {
                    "type": "text",
                    "data": "hello inline document",
                    "media_type": "text/plain",
                },
            },
        )
    )
    assert isinstance(content, ContentDocument)
    assert content.document.startswith("data:text/plain;base64,")

    blocks = await message_block_params(content)
    block = cast(dict[str, Any], blocks[0])
    source = cast(dict[str, Any], block["source"])
    assert source == {
        "type": "text",
        "data": "hello inline document",
        "media_type": "text/plain",
    }


def test_file_image_source_raises() -> None:
    with pytest.raises(RuntimeError, match="Unsupported image source type: file"):
        content_block_to_content(
            cast(
                Any,
                {"type": "image", "source": {"type": "file", "file_id": "file_123"}},
            )
        )


def test_file_document_source_raises() -> None:
    with pytest.raises(RuntimeError, match="Unsupported document source type: file"):
        content_block_to_content(
            cast(
                Any,
                {"type": "document", "source": {"type": "file", "file_id": "file_123"}},
            )
        )


def test_browser_state_block_raises() -> None:
    with pytest.raises(
        RuntimeError, match="Unsupported content block type: browser_state"
    ):
        content_block_to_content(cast(Any, {"type": "browser_state"}))


def test_anthropic_system_to_texts_preserves_block_boundaries() -> None:
    """Blocks stay separate so a header block can't be glued to instructions."""
    assert anthropic_system_to_texts(None) == []
    assert anthropic_system_to_texts("") == []
    assert anthropic_system_to_texts("plain") == ["plain"]
    assert anthropic_system_to_texts(
        [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    ) == ["a", "b"]
    # empty blocks contribute no system message
    assert anthropic_system_to_texts(
        [{"type": "text", "text": "a"}, {"type": "text", "text": ""}]
    ) == ["a"]
    # non-text blocks are ignored
    assert anthropic_system_to_texts(
        [{"type": "image"}, {"type": "text", "text": "a"}]
    ) == ["a"]


def test_anthropic_system_header_block_not_glued_to_instructions() -> None:
    """Regression: a metadata header block must not absorb the real prompt.

    Claude Code's auto-mode classifier sends ``system`` as
    ``[billing-header, monitor-prompt, session-context]``. The Anthropic API
    consumes a system block starting with ``x-anthropic-*-header:`` as request
    metadata and DROPS that block, so concatenating the blocks made the API
    discard the monitor prompt too -- the classifier then had no instructions
    and no verdict grammar, and fail-closed on every action.
    """
    header = "x-anthropic-billing-header: cc_version=2.1.205; cc_entrypoint=sdk-cli;"
    prompt = "You are a security monitor for autonomous AI coding agents."
    context = "## Session Context"
    texts = anthropic_system_to_texts(
        [
            {"type": "text", "text": header},
            {"type": "text", "text": prompt},
            {"type": "text", "text": context},
        ]
    )
    assert texts == [header, prompt, context]
    # the header must stand alone: nothing else may ride along in its block
    assert texts[0] == header
    assert prompt not in texts[0]


@pytest.mark.anyio
async def test_unexpected_input_parameter_error_includes_value() -> None:
    """An unhandled user content block reports the offending block, not '{c}'."""
    block: ThinkingBlockParam = {
        "type": "thinking",
        "thinking": "hmm",
        "signature": "sig",
    }
    with pytest.raises(RuntimeError) as exc_info:
        await messages_from_anthropic_input(
            [{"role": "user", "content": [block]}],
            tools=[],
        )
    assert "thinking" in str(exc_info.value)
    assert "{c}" not in str(exc_info.value)


def test_base_64_data_error_includes_value() -> None:
    """A non-str, non-stream image source reports its value, not '{data}'."""
    with pytest.raises(RuntimeError) as exc_info:
        base_64_data(Path("/tmp/image.png"))
    assert "/tmp/image.png" in str(exc_info.value)
    assert "{data}" not in str(exc_info.value)


# --- impl-level: request `system` becomes leading system messages ------------


class _CapturedMessages(Exception):
    """Sentinel carrying the messages the impl handed to generation."""

    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages


async def _request_impl_messages(
    monkeypatch: pytest.MonkeyPatch, json_data: dict[str, Any]
) -> list[Any]:
    """Run inspect_anthropic_api_request_impl and capture its inspect messages."""
    import inspect_ai.agent._bridge.anthropic_api_impl as impl
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.types import AgentBridge

    async def capture(
        bridge: Any, model: Any, messages: Any, *args: Any, **kwargs: Any
    ) -> Any:
        raise _CapturedMessages(messages)

    monkeypatch.setattr(impl, "bridge_generate", capture)
    bridge = AgentBridge(state=AgentState(messages=[]), allow_client_model_names=True)
    with pytest.raises(_CapturedMessages) as exc_info:
        await impl.inspect_anthropic_api_request_impl(
            {
                "model": "mockllm/model",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "hello"}],
                **json_data,
            },
            headers=None,
            web_search=None,
            code_execution=None,
            bridge=bridge,
        )
    return exc_info.value.messages


@pytest.mark.anyio
async def test_request_impl_no_system(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = await _request_impl_messages(monkeypatch, {})
    assert [type(m) for m in messages] == [ChatMessageUser]


@pytest.mark.anyio
async def test_request_impl_string_system(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = await _request_impl_messages(monkeypatch, {"system": "be helpful"})
    assert [type(m) for m in messages] == [ChatMessageSystem, ChatMessageUser]
    assert messages[0].text == "be helpful"


@pytest.mark.anyio
async def test_request_impl_single_block_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = await _request_impl_messages(
        monkeypatch, {"system": [{"type": "text", "text": "be helpful"}]}
    )
    assert [type(m) for m in messages] == [ChatMessageSystem, ChatMessageUser]
    assert messages[0].text == "be helpful"


@pytest.mark.anyio
async def test_request_impl_multi_block_system_preserves_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One leading system message per Anthropic system block, in order."""
    messages = await _request_impl_messages(
        monkeypatch,
        {
            "system": [
                {"type": "text", "text": "x-anthropic-billing-header: abc"},
                {"type": "text", "text": "you are a security classifier"},
                {"type": "text", "text": "session context"},
            ]
        },
    )
    assert [type(m) for m in messages] == [
        ChatMessageSystem,
        ChatMessageSystem,
        ChatMessageSystem,
        ChatMessageUser,
    ]
    assert [m.text for m in messages[:3]] == [
        "x-anthropic-billing-header: abc",
        "you are a security classifier",
        "session context",
    ]


def test_anthropic_usage_forwards_thinking_tokens() -> None:
    """Bridge clients read thinking tokens from usage.output_tokens_details.

    Extended-thinking clients size and meter reasoning off this field, so
    dropping it makes a thinking response indistinguishable from a plain one.
    """
    from inspect_ai.agent._bridge.anthropic_api_impl import anthropic_usage
    from inspect_ai.model._model_output import ModelUsage

    usage = anthropic_usage(
        ModelUsage(
            input_tokens=100,
            output_tokens=500,
            total_tokens=600,
            reasoning_tokens=412,
        )
    )

    assert usage.output_tokens_details is not None
    assert usage.output_tokens_details.thinking_tokens == 412
    # breakout of output_tokens, not added on top
    assert usage.output_tokens == 500


def test_anthropic_usage_omits_thinking_tokens_when_absent() -> None:
    """No reasoning means no thinking-token detail rather than a bogus zero."""
    from inspect_ai.agent._bridge.anthropic_api_impl import anthropic_usage
    from inspect_ai.model._model_output import ModelUsage

    usage = anthropic_usage(ModelUsage(input_tokens=10, output_tokens=20))

    assert usage.output_tokens_details is None


def test_anthropic_usage_forwards_thinking_tokens_beta() -> None:
    """Beta bridge clients also read thinking tokens from output_tokens_details.

    Mirrors test_anthropic_usage_forwards_thinking_tokens for the beta=True
    path, which must return BetaUsage carrying a BetaOutputTokensDetails.
    """
    from anthropic.types.beta import BetaOutputTokensDetails, BetaUsage

    from inspect_ai.agent._bridge.anthropic_api_impl import anthropic_usage
    from inspect_ai.model._model_output import ModelUsage

    usage = anthropic_usage(
        ModelUsage(
            input_tokens=100,
            output_tokens=500,
            total_tokens=600,
            reasoning_tokens=412,
        ),
        beta=True,
    )

    assert isinstance(usage, BetaUsage)
    assert usage.output_tokens_details is not None
    assert isinstance(usage.output_tokens_details, BetaOutputTokensDetails)
    assert usage.output_tokens_details.thinking_tokens == 412
    # breakout of output_tokens, not added on top
    assert usage.output_tokens == 500


def test_anthropic_usage_omits_thinking_tokens_when_absent_beta() -> None:
    """No reasoning means no thinking-token detail rather than a bogus zero."""
    from inspect_ai.agent._bridge.anthropic_api_impl import anthropic_usage
    from inspect_ai.model._model_output import ModelUsage

    usage = anthropic_usage(ModelUsage(input_tokens=10, output_tokens=20), beta=True)

    assert usage.output_tokens_details is None


# the providers a bridge resolves by default, and the raw default before resolution
DEFAULT_WEB_SEARCH = pytest.mark.parametrize(
    "providers",
    [
        resolve_bridge_web_search(True, default_grant=False),
        internal_web_search_providers(),
    ],
    ids=["resolved", "raw"],
)


def _bridged_web_search_params(
    client_tool: dict[str, Any],
    providers: WebSearchProviders | None,
    model_name: str = "claude-opus-5",
) -> list[Any] | None:
    """The web tools the provider sends for a client's web_search declaration."""
    tools = tools_from_anthropic_tools(
        [cast(Any, client_tool)], None, providers, None, False
    )
    assert len(tools) == 1
    tool = tools[0]
    tool_info = tool if isinstance(tool, ToolInfo) else tool_to_tool_info(tool)
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    return api.web_search_tool_params(tool_info)


@DEFAULT_WEB_SEARCH
def test_bridge_preserves_claude_code_web_search_version(
    providers: WebSearchProviders | None,
) -> None:
    # the tool Claude Code's WebSearch sends with a forced tool_choice
    params = _bridged_web_search_params(
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 8},
        providers,
    )
    assert params == [
        {"name": "web_fetch", "type": "web_fetch_20250910", "max_uses": 8},
        {"name": "web_search", "type": "web_search_20250305", "max_uses": 8},
    ]


@DEFAULT_WEB_SEARCH
def test_bridge_preserves_client_latest_web_search_version(
    providers: WebSearchProviders | None,
) -> None:
    # honoured even on a model whose default is the older version
    params = _bridged_web_search_params(
        {"type": "web_search_20260209", "name": "web_search"},
        providers,
        model_name="claude-sonnet-4-5",
    )
    assert params == [
        {"name": "web_fetch", "type": "web_fetch_20260209"},
        {"name": "web_search", "type": "web_search_20260209"},
    ]


@DEFAULT_WEB_SEARCH
def test_bridge_unknown_web_search_version_uses_provider_choice(
    providers: WebSearchProviders | None,
) -> None:
    params = _bridged_web_search_params(
        {"type": "web_search_20990101", "name": "web_search"}, providers
    )
    assert params is not None
    assert [param["type"] for param in params] == [
        "web_fetch_20260209",
        "web_search_20260209",
    ]


@pytest.mark.anyio
async def test_bridge_round_trip_tool_turn_no_trailing_text() -> None:
    """A bridge round trip of a tool-call-only turn replays without trailing text.

    A chat-completions loop inside ``agent_bridge`` replays its turns as
    ``{"content": "", "reasoning_content": ..., "tool_calls": [...]}``, which
    ``messages_from_openai`` rebuilds as reasoning plus an empty text sibling.
    Materializing that sibling as a "(no content)" text block leaves trailing
    text after the final ``tool_use``, which claude reads as an assistant
    prefill attempt and rejects with a 400 (#5970).
    """
    # the conversation exactly as the bridged OpenAI client replays it: a
    # tool-call-only assistant turn (empty content, reasoning carried in the
    # OpenAI-compatible reasoning_content field)
    openai_messages = [
        {"role": "user", "content": "list the items"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I should call list_items first.",
            "tool_calls": [
                {
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "list_items", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": '["a1", "b2"]'},
    ]
    messages = await messages_from_openai(openai_messages, "claude-sonnet-5-5")
    turns = [
        message
        for message in messages
        if isinstance(message, ChatMessageAssistant) and message.tool_calls
    ]
    assert len(turns) == 1

    # stand in for the provider-side state recorded when anthropic generated
    # this turn during the bridge loop: the verbatim thinking block (keyed by
    # content hash) and the wire position of the client tool call
    init_sample_anthropic_assistant_internal()
    internal = assistant_internal()
    reasoning = turns[0].content[0]
    assert isinstance(reasoning, ContentReasoning)
    internal.thinking_blocks[mm3_hash(reasoning.reasoning)] = ThinkingBlockParam(
        type="thinking", thinking=reasoning.reasoning, signature="sig-original"
    )
    internal.client_tool_call_positions[turns[0].tool_calls[0].id] = 1

    blocks = await assistant_message_block_params(turns[0])
    assert [block["type"] for block in blocks] == ["thinking", "tool_use"]
    # no text block may follow the final tool_use block
    last_tool_use = max(
        i for i, block in enumerate(blocks) if block["type"] == "tool_use"
    )
    assert all(block["type"] != "text" for block in blocks[last_tool_use + 1 :])


@pytest.mark.anyio
async def test_assistant_empty_text_only_content_replays_placeholder() -> None:
    """An empty-text-only assistant turn still replays a "(no content)" placeholder.

    Dropping empty text items must not turn such a turn into an empty assistant
    message, which claude rejects.
    """
    turn = ChatMessageAssistant(content=[ContentText(text="")])
    blocks = await assistant_message_block_params(turn)
    assert [block["type"] for block in blocks] == ["text"]
    assert blocks[0]["text"] == NO_CONTENT


@pytest.mark.anyio
@pytest.mark.parametrize("recorded_position", [0, None], ids=["leading", "default"])
async def test_bridge_tool_first_turn_no_trailing_text(
    recorded_position: int | None,
) -> None:
    """A tool-first turn replayed with empty str content has no trailing text.

    Without reasoning to trigger list normalization, the bridged replay of a
    tool-call-only turn keeps ``content=""`` as a str; the placeholder must
    not materialize after the ``tool_use`` block whether its position was
    recorded (wire order: tool first) or defaults to last (#5970).
    """
    init_sample_anthropic_assistant_internal()
    turn = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="toolu_1", function="list_items", arguments={})],
    )
    if recorded_position is not None:
        assistant_internal().client_tool_call_positions["toolu_1"] = recorded_position
    blocks = await assistant_message_block_params(turn)
    assert [block["type"] for block in blocks] == ["tool_use"]


@pytest.mark.anyio
async def test_empty_text_sibling_keeps_tool_position_arithmetic() -> None:
    """Dropping an empty text item must not shift recorded tool positions.

    A skipped item still occupies a slot in the segment list, so a tool call
    recorded after two content items splices after the surviving item, not
    before it.
    """
    init_sample_anthropic_assistant_internal()
    turn = ChatMessageAssistant(
        content=[ContentText(text=""), ContentText(text="after the call")],
        tool_calls=[ToolCall(id="toolu_1", function="list_items", arguments={})],
    )
    assistant_internal().client_tool_call_positions["toolu_1"] = 1
    blocks = await assistant_message_block_params(turn)
    assert [(block["type"], block.get("text")) for block in blocks] == [
        ("tool_use", None),
        ("text", "after the call"),
    ]
