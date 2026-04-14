import types
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai._util.content import Content, ContentText, ContentToolUse
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.tool import ToolCall


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_api() -> None:
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
        ),
    )

    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1


@skip_if_no_anthropic
def test_anthropic_effort() -> None:
    log = eval(
        Task(dataset=[Sample(input="Please tell a story about toys.")]),
        model="anthropic/claude-opus-4-5",
        effort="low",
    )[0]
    assert log.status == "success"


def test_anthropic_oauth_beta_preserved_with_effort() -> None:
    """Test that OAuth beta header is preserved when per-request betas are added.

    When using ANTHROPIC_AUTH_TOKEN, the client sets oauth-2025-04-20 as a
    default header. Per-request extra_headers must not overwrite it.
    """
    import os

    orig = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    try:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-oauth-token"
        os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
        model = get_model("anthropic/claude-opus-4-5")
        api: Any = model.api
        # Verify client has the OAuth beta as a default header
        client_beta = getattr(api.client, "_custom_headers", {}).get(
            "anthropic-beta", ""
        )
        assert "oauth-2025-04-20" in client_beta
        # Use effort to trigger per-request betas
        config = GenerateConfig(effort="low", max_tokens=64)
        _params, _extra_body, _headers, betas = api.completion_config(config)
        assert "effort-2025-11-24" in betas
        # The generate() method merges client betas - simulate that here
        if betas:
            if client_beta:
                for b in client_beta.split(","):
                    b = b.strip()
                    if b and b not in betas:
                        betas.insert(0, b)
        assert "oauth-2025-04-20" in betas, (
            "OAuth beta header must be preserved when per-request betas are set"
        )
    finally:
        if orig is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = orig
        else:
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def test_anthropic_extra_headers_not_mutated_across_calls() -> None:
    """Ensure per-call extra_headers are stable across repeated use."""
    api = AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test-key")
    config = GenerateConfig(
        max_tokens=64,
        extra_headers={
            "anthropic_beta": "context-1m-2025-08-07",
            "x-test-header": "value",
        },
    )

    for _ in range(2):
        _params, _extra_body, headers, betas = api.completion_config(config)
        assert headers == {"x-test-header": "value"}
        assert betas == ["context-1m-2025-08-07"]
        assert config.extra_headers == {
            "anthropic_beta": "context-1m-2025-08-07",
            "x-test-header": "value",
        }


@skip_if_no_anthropic
def test_anthropic_should_retry():
    import httpx
    from anthropic import APIStatusError

    # scaffold for should_retry
    model = get_model("anthropic/claude-sonnet-4-6")
    response = httpx.Response(
        status_code=405, request=httpx.Request("GET", "https://example.com")
    )

    # check whether we handle overloaded_error correctly
    ex = APIStatusError(
        "error", response=response, body={"error": {"type": "overloaded_error"}}
    )
    assert model.api.should_retry(ex)

    # check whether we handle body not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body="error")
    model.api.should_retry(ex)

    # check whether we handle error not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body={"error": "error"})
    model.api.should_retry(ex)


@skip_if_no_anthropic
async def test_anthropic_count_tokens_single_tool_call() -> None:
    """Test counting tokens for a single assistant message with one tool call."""
    model = get_model("anthropic/claude-sonnet-4-6")

    # Create an assistant message with a single tool call (no tool result)
    assistant_msg = ChatMessageAssistant(
        content="I'll help you with that.",
        tool_calls=[
            ToolCall(
                id="toolu_test_123",
                function="test_function",
                arguments={"arg1": "value1"},
            )
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@skip_if_no_anthropic
async def test_anthropic_count_tokens_multiple_tool_calls() -> None:
    """Test counting tokens for a single assistant message with multiple tool calls."""
    model = get_model("anthropic/claude-sonnet-4-6")

    # Create an assistant message with multiple tool calls (no tool results)
    assistant_msg = ChatMessageAssistant(
        content="I'll run multiple tools.",
        tool_calls=[
            ToolCall(
                id="toolu_test_abc",
                function="function_a",
                arguments={"x": 1},
            ),
            ToolCall(
                id="toolu_test_def",
                function="function_b",
                arguments={"y": 2},
            ),
            ToolCall(
                id="toolu_test_ghi",
                function="function_c",
                arguments={"z": 3},
            ),
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@skip_if_no_anthropic
async def test_anthropic_count_tokens_single_tool_result() -> None:
    """Test counting tokens for a single tool result message (no preceding tool use)."""
    model = get_model("anthropic/claude-sonnet-4-6")

    # Create a tool result message without a preceding assistant message
    tool_msg = ChatMessageTool(
        content="Tool result content here",
        tool_call_id="toolu_test_xyz",
        function="some_function",
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([tool_msg])
    assert token_count > 0


async def test_anthropic_continuation_preserves_server_tool_pairing() -> None:
    """Ensure continuation parsing preserves server tool-use/result pairing."""
    from anthropic import AsyncAnthropic
    from anthropic.types import (
        Message,
        ServerToolUseBlock,
        Usage,
        WebSearchToolResultBlock,
        WebSearchToolResultError,
    )

    head_message = Message(
        id="msg_head",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        stop_reason="pause_turn",
        content=[
            ServerToolUseBlock(
                id="toolu_1",
                type="server_tool_use",
                name="web_search",
                input={"query": "inspect ai"},
            )
        ],
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    tail_message = Message(
        id="msg_tail",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        content=[
            WebSearchToolResultBlock(
                type="web_search_tool_result",
                tool_use_id="toolu_1",
                content=WebSearchToolResultError(
                    type="web_search_tool_result_error",
                    error_code="unavailable",
                ),
            )
        ],
        usage=Usage(input_tokens=1, output_tokens=1),
    )

    api = create_autospec(AnthropicAPI, instance=True)
    api._batcher = None
    api.model_name = "claude-sonnet-4-6"
    api.service_model_name.return_value = "claude-sonnet-4-6"

    client = create_autospec(AsyncAnthropic, instance=True)
    client.messages.create = AsyncMock(side_effect=[head_message, tail_message])
    api.client = client

    # Bind the real method so recursive continuation calls work
    api._perform_request_and_continuations = types.MethodType(
        AnthropicAPI._perform_request_and_continuations, api
    )

    _, output = await api._perform_request_and_continuations(
        request={"messages": []},
        streaming=False,
        tools=[],
        config=GenerateConfig(),
    )

    tool_uses = [c for c in output.message.content if isinstance(c, ContentToolUse)]
    assert len(tool_uses) == 1
    assert tool_uses[0].id == "toolu_1"


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_prompt_caching() -> None:
    """Verify prompt caching produces cache_read tokens on second request."""
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(max_tokens=50, temperature=0.0),
    )

    # Large system message to exceed minimum cacheable threshold (2048 tokens
    # for sonnet 4.6). Anthropic silently skips caching below the threshold.
    system_text = "You are a helpful assistant. " * 400
    messages: list[ChatMessage] = [
        ChatMessageSystem(content=system_text),
        ChatMessageUser(content="Say hello."),
    ]

    # First call: creates cache or hits existing cache from prior run
    response1 = await model.generate(input=messages)
    assert response1.usage is not None

    # Second call with same prefix: should always hit cache
    response2 = await model.generate(input=messages)
    assert response2.usage is not None
    assert (response2.usage.input_tokens_cache_read or 0) > 0


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_prompt_caching_content_blocks() -> None:
    """Verify caching works at the content block level within messages.

    Builds a multi-turn conversation with multiple content blocks per message
    (no system message or tools) and confirms that the shared prefix of content
    blocks from turn 1 produces a cache hit on turn 2.
    """
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(max_tokens=50, temperature=0.0, cache_prompt=True),
    )

    # Build a user message with several content blocks totalling >2048 tokens
    paragraph = "The quick brown fox jumps over the lazy dog. " * 50
    content_blocks: list[Content] = [
        ContentText(text=f"Section {i}: {paragraph}") for i in range(5)
    ]

    # Turn 1: user message with multiple content blocks
    turn1_messages: list[ChatMessage] = [
        ChatMessageUser(content=content_blocks),
    ]
    response1 = await model.generate(input=turn1_messages)
    assert response1.usage is not None

    # Turn 2: same user content blocks + assistant reply + new user content
    turn2_messages: list[ChatMessage] = [
        ChatMessageUser(content=content_blocks),
        ChatMessageAssistant(content=response1.completion),
        ChatMessageUser(
            content=[
                ContentText(text="Follow-up question part A."),
                ContentText(text="Follow-up question part B."),
            ]
        ),
    ]
    response2 = await model.generate(input=turn2_messages)
    assert response2.usage is not None
    assert (response2.usage.input_tokens_cache_read or 0) > 0


@pytest.mark.anyio
async def test_anthropic_cache_marks_penultimate_block() -> None:
    """Verify the second-to-last content block gets an explicit cache marker.

    Auto-cache marks the last block; this marker gives the 20-block lookback
    a write to find when only the last block changes. The penultimate block
    is content[-2] of the last message when it has multiple blocks, otherwise
    content[-1] of the previous message.
    """
    api = create_autospec(AnthropicAPI, instance=True)
    api.service_model_name.return_value = "claude-sonnet-4-6"
    api.partition_tools.return_value = ([], [])
    api.resolve_chat_input = types.MethodType(AnthropicAPI.resolve_chat_input, api)

    def marked(content: Any) -> list[int]:
        assert isinstance(content, list)
        return [i for i, b in enumerate(content) if "cache_control" in b]

    async def resolve(input: list[ChatMessage], cache: bool = True) -> Any:
        return await api.resolve_chat_input(
            input=input, tools=[], config=GenerateConfig(cache_prompt=cache)
        )

    # multi-block last message: mark content[-2]
    blocks: list[Content] = [ContentText(text=f"block {i}") for i in range(4)]
    _, _, _, msgs, _ = await resolve([ChatMessageUser(content=blocks)])
    assert marked(msgs[0]["content"]) == [2]

    # single-block last message: mark previous message's content[-1]
    _, _, _, msgs, _ = await resolve(
        [
            ChatMessageUser(content="context"),
            ChatMessageAssistant(content="reply with two parts. " * 2),
            ChatMessageUser(content="follow-up"),
        ]
    )
    # assistant content is always a list; its last block should be marked
    assert marked(msgs[1]["content"]) == [len(msgs[1]["content"]) - 1]
    # neither user message should be marked
    assert "cache_control" not in msgs[0]
    assert "cache_control" not in msgs[2]

    # single message, single block: no penultimate position, no marker
    _, _, _, msgs, _ = await resolve([ChatMessageUser(content="only")])
    assert msgs[0]["content"] == "only"

    # cache_prompt=False: nothing marked
    _, _, _, msgs, cache_prompt = await resolve(
        [ChatMessageUser(content=blocks)], cache=False
    )
    assert cache_prompt is False
    assert marked(msgs[0]["content"]) == []


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_prompt_caching_changing_suffix() -> None:
    """Verify caching when only the last content block changes.

    Builds a user message with several stable blocks plus a final block that
    differs between calls. The penultimate-block marker should give the
    auto-cache lookback a write to fall back to.
    """
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(max_tokens=50, temperature=0.0, cache_prompt=True),
    )

    # stable prefix blocks totalling >2048 tokens
    paragraph = "The quick brown fox jumps over the lazy dog. " * 50
    stable: list[Content] = [
        ContentText(text=f"Section {i}: {paragraph}") for i in range(5)
    ]

    msgs1: list[ChatMessage] = [
        ChatMessageUser(content=stable + [ContentText(text="Question one?")]),
    ]
    msgs2: list[ChatMessage] = [
        ChatMessageUser(content=stable + [ContentText(text="Question two?")]),
    ]

    response1 = await model.generate(input=msgs1)
    assert response1.usage is not None

    response2 = await model.generate(input=msgs2)
    assert response2.usage is not None
    assert (response2.usage.input_tokens_cache_read or 0) > 0
