from pathlib import Path
from typing import Any, cast

import pytest
from anthropic.types import ThinkingBlockParam

from inspect_ai._util.content import ContentDocument
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
from inspect_ai.model._providers.anthropic import AnthropicAPI, message_block_params
from inspect_ai.tool import WebSearchProviders
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


# --- pause_turn at the provider's continuation bound -------------------------


def _paused_head(index: int, stop_reason: str = "pause_turn") -> Any:
    """A head message carrying text and a complete web search call."""
    from anthropic.types import (
        Message,
        ServerToolUseBlock,
        TextBlock,
        Usage,
        WebSearchToolResultBlock,
        WebSearchToolResultError,
    )

    return Message(
        id=f"msg_{index}",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        stop_reason=cast(Any, stop_reason),
        content=[
            TextBlock(type="text", text=f"part {index}"),
            ServerToolUseBlock(
                id=f"srvtoolu_{index}",
                type="server_tool_use",
                name="web_search",
                input={"query": f"query {index}"},
            ),
            WebSearchToolResultBlock(
                type="web_search_tool_result",
                tool_use_id=f"srvtoolu_{index}",
                content=WebSearchToolResultError(
                    type="web_search_tool_result_error", error_code="unavailable"
                ),
            ),
        ],
        usage=Usage(
            input_tokens=10 * index,
            output_tokens=index,
            cache_read_input_tokens=100 * index,
        ),
    )


def _anthropic_bridge(responses: list[Any]) -> tuple[Any, Any, list[Any]]:
    """A bridge whose "claude-test" model is a real Anthropic provider on a mock client.

    Returns the bridge, the mocked `messages.create`, and a list that collects
    each ModelOutput the bridge generated.
    """
    from unittest.mock import AsyncMock, create_autospec

    from anthropic import AsyncAnthropic

    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.types import AgentBridge
    from inspect_ai.model import GenerateConfig, get_model

    model = get_model(
        "anthropic/claude-sonnet-4-6",
        api_key="test-key",
        streaming=False,
        memoize=False,
        config=GenerateConfig(max_retries=0),
    )
    client = create_autospec(AsyncAnthropic, instance=True)
    create = AsyncMock(side_effect=responses)
    client.messages.create = create
    setattr(model.api, "client", client)
    bridge = AgentBridge(
        state=AgentState(messages=[]), model_aliases={"claude-test": model}
    )
    return bridge, create, []


async def _bridge_request(
    monkeypatch: pytest.MonkeyPatch,
    bridge: Any,
    outputs: list[Any],
    messages: list[dict[str, Any]],
    beta: bool,
) -> Any:
    import inspect_ai.agent._bridge.anthropic_api_impl as impl
    from inspect_ai.agent._bridge.util import bridge_generate

    async def recording_generate(*args: Any, **kwargs: Any) -> Any:
        output, c_message = await bridge_generate(*args, **kwargs)
        outputs.append(output)
        return output, c_message

    monkeypatch.setattr(impl, "bridge_generate", recording_generate)
    return await impl.inspect_anthropic_api_request_impl(
        {"model": "claude-test", "max_tokens": 1024, "messages": messages},
        headers=None,
        web_search=None,
        code_execution=None,
        bridge=bridge,
        beta=beta,
    )


@pytest.mark.parametrize("beta", [False, True])
@pytest.mark.anyio
async def test_bridge_returns_pause_turn_at_continuation_bound(
    monkeypatch: pytest.MonkeyPatch, beta: bool
) -> None:
    """A turn still paused at the bound reaches the client as pause_turn, intact."""
    from inspect_ai.model._providers.anthropic import MAX_PAUSE_TURN_CONTINUATIONS

    requests = MAX_PAUSE_TURN_CONTINUATIONS + 1
    bridge, create, outputs = _anthropic_bridge(
        [_paused_head(i) for i in range(1, requests + 1)]
    )

    message = await _bridge_request(
        monkeypatch, bridge, outputs, [{"role": "user", "content": "search"}], beta
    )

    assert create.await_count == requests
    assert message.stop_reason == "pause_turn"
    assert [block.type for block in message.content] == [
        "text",
        "server_tool_use",
        "web_search_tool_result",
    ] * requests
    assert [b.id for b in message.content if b.type == "server_tool_use"] == [
        f"srvtoolu_{i}" for i in range(1, requests + 1)
    ]
    assert [
        b.tool_use_id for b in message.content if b.type == "web_search_tool_result"
    ] == [f"srvtoolu_{i}" for i in range(1, requests + 1)]
    assert message.usage.input_tokens == sum(10 * i for i in range(1, requests + 1))
    assert message.usage.cache_read_input_tokens == sum(
        100 * i for i in range(1, requests + 1)
    )
    assert outputs[0].input_context_tokens == 10 + 100


@pytest.mark.anyio
async def test_bridge_pause_turn_replay_continues_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resending the paused turn continues it without duplicating server tool blocks."""
    from inspect_ai.model._providers.anthropic import MAX_PAUSE_TURN_CONTINUATIONS

    requests = MAX_PAUSE_TURN_CONTINUATIONS + 1
    tail = _paused_head(requests + 1, stop_reason="end_turn")
    bridge, create, outputs = _anthropic_bridge(
        [_paused_head(i) for i in range(1, requests + 1)] + [tail]
    )
    user = {"role": "user", "content": "search"}
    paused = await _bridge_request(monkeypatch, bridge, outputs, [user], False)
    assert paused.stop_reason == "pause_turn"

    # the client resends with the partial assistant turn as the last message
    partial = {
        "role": "assistant",
        "content": [block.model_dump(exclude_none=True) for block in paused.content],
    }
    message = await _bridge_request(
        monkeypatch, bridge, outputs, [user, partial], False
    )

    assert create.await_count == requests + 1
    sent = create.call_args.kwargs["messages"]
    assert sent[-1]["role"] == "assistant"
    sent_blocks = [
        block if isinstance(block, dict) else block.model_dump()
        for block in sent[-1]["content"]
    ]
    server_tool_ids = [b["id"] for b in sent_blocks if b["type"] == "server_tool_use"]
    result_ids = [
        b["tool_use_id"] for b in sent_blocks if b["type"] == "web_search_tool_result"
    ]
    expected = [f"srvtoolu_{i}" for i in range(1, requests + 1)]
    assert server_tool_ids == expected
    assert result_ids == expected

    assert message.stop_reason == "end_turn"
    assert [block.type for block in message.content] == [
        "text",
        "server_tool_use",
        "web_search_tool_result",
    ]
    # usage and context are the continuation request's own
    assert message.usage.input_tokens == 10 * (requests + 1)
    assert outputs[-1].usage.input_tokens == 10 * (requests + 1)
    assert outputs[-1].input_context_tokens == 110 * (requests + 1)


@pytest.mark.parametrize("beta", [False, True])
@pytest.mark.anyio
async def test_bridge_pause_turn_at_bound_keeps_pending_server_tool_call(
    monkeypatch: pytest.MonkeyPatch, beta: bool
) -> None:
    """A server tool call still running at the bound is resumed by the resent turn."""
    from anthropic._models import construct_type
    from anthropic.types import Message

    import inspect_ai.model._providers.anthropic as anthropic_provider
    from inspect_ai.model._providers.anthropic import (
        init_sample_anthropic_assistant_internal,
    )

    init_sample_anthropic_assistant_internal()
    monkeypatch.setattr(anthropic_provider, "MAX_PAUSE_TURN_CONTINUATIONS", 1)

    def message(id: str, content: list[dict[str, Any]], **fields: Any) -> Message:
        data = {
            "id": id,
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": content,
            "usage": {"input_tokens": 20, "output_tokens": 2},
        } | fields
        return cast(Message, construct_type(value=data, type_=Message))

    # the call runs in a code execution container (e.g. dynamic filtering)
    pending = message(
        "msg_pending",
        [
            {"type": "text", "text": "searching again"},
            {
                "type": "server_tool_use",
                "id": "srvtoolu_pending",
                "name": "web_search",
                "input": {"query": "still running"},
                "caller": {"type": "direct"},
            },
        ],
        stop_reason="pause_turn",
        container={"id": "cntr_pending", "expires_at": "2026-12-01T00:00:00Z"},
    )
    resumed = message(
        "msg_resumed",
        [
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_pending",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "unavailable",
                },
            },
            {"type": "text", "text": "done"},
        ],
        stop_reason="end_turn",
    )
    bridge, create, outputs = _anthropic_bridge([_paused_head(1), pending, resumed])
    user = {"role": "user", "content": "search"}

    paused = await _bridge_request(monkeypatch, bridge, outputs, [user], beta)

    assert create.await_count == 2
    assert paused.stop_reason == "pause_turn"
    assert [block.type for block in paused.content] == [
        "text",
        "server_tool_use",
        "web_search_tool_result",
        "text",
        "server_tool_use",
    ]
    assert paused.content[-1].id == "srvtoolu_pending"

    # the client resends the paused turn: the resumed request carries the
    # pending call and names its container
    partial = {
        "role": "assistant",
        "content": [block.model_dump(exclude_none=True) for block in paused.content],
    }
    message_out = await _bridge_request(
        monkeypatch, bridge, outputs, [user, partial], beta
    )

    assert create.await_count == 3
    resumed_request = create.call_args.kwargs
    sent_blocks = [
        block if isinstance(block, dict) else block.model_dump()
        for block in resumed_request["messages"][-1]["content"]
    ]
    assert [b["id"] for b in sent_blocks if b["type"] == "server_tool_use"] == [
        "srvtoolu_1",
        "srvtoolu_pending",
    ]
    assert resumed_request.get("container") == "cntr_pending"
    assert message_out.stop_reason == "end_turn"
    assert [block.type for block in message_out.content] == [
        "web_search_tool_result",
        "text",
    ]
    assert message_out.content[0].tool_use_id == "srvtoolu_pending"


def test_anthropic_stop_reason_pause_turn_only_from_stop_details() -> None:
    from inspect_ai.agent._bridge.anthropic_api_impl import anthropic_stop_reason
    from inspect_ai.model._model_output import StopDetails

    assert (
        anthropic_stop_reason("unknown", StopDetails(type="pause_turn")) == "pause_turn"
    )
    assert anthropic_stop_reason("unknown") == "end_turn"
    assert anthropic_stop_reason("unknown", StopDetails(type="other")) == "end_turn"
    assert anthropic_stop_reason("stop", StopDetails(type="pause_turn")) == "end_turn"


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
