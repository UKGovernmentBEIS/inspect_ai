import types
from typing import Any, cast
from unittest.mock import AsyncMock, create_autospec

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
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
from inspect_ai.tool import ToolCall, ToolInfo


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


_FULL_THINKING_BETA = "dev-full-thinking-2025-05-14"


def test_anthropic_full_thinking_removes_display_adaptive() -> None:
    """The dev-full-thinking beta only takes effect when 'display' is absent.

    See the Anthropic thinking.display param: it defaults to 'omitted' on 4.7
    and 'summarized' elsewhere, but the dev-full-thinking beta is ignored unless
    the param is omitted entirely. So when that beta is present we must drop it.
    """
    api = AnthropicAPI(
        model_name="claude-opus-4-7", api_key="test-key", betas=[_FULL_THINKING_BETA]
    )
    config = GenerateConfig(max_tokens=64, reasoning_effort="high")
    params, _extra_body, _headers, betas = api.completion_config(config)
    assert _FULL_THINKING_BETA in betas
    assert params["thinking"]["type"] == "adaptive"
    assert "display" not in params["thinking"]


def test_anthropic_full_thinking_removes_display_budget() -> None:
    """Same removal applies on the pre-4.6 extended-thinking (budget) path."""
    api = AnthropicAPI(
        model_name="claude-sonnet-4-6", api_key="test-key", betas=[_FULL_THINKING_BETA]
    )
    config = GenerateConfig(max_tokens=64, reasoning_tokens=2048)
    params, _extra_body, _headers, _betas = api.completion_config(config)
    assert params["thinking"]["type"] == "enabled"
    assert "display" not in params["thinking"]


def test_anthropic_thinking_keeps_display_without_full_thinking_beta() -> None:
    """Without the beta, 'display' stays 'summarized' on both thinking paths."""
    adaptive = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    params, _e, _h, _b = adaptive.completion_config(
        GenerateConfig(max_tokens=64, reasoning_effort="high")
    )
    assert params["thinking"]["display"] == "summarized"

    budget = AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test-key")
    params, _e, _h, _b = budget.completion_config(
        GenerateConfig(max_tokens=64, reasoning_tokens=2048)
    )
    assert params["thinking"]["display"] == "summarized"


@pytest.mark.parametrize(
    "model_name,disabled",
    [
        # 4.7+ run adaptive thinking by default and accept `disabled`
        ("claude-sonnet-5", True),
        ("claude-opus-4-8", True),
        ("claude-opus-4-7", True),
        # Fable/Mythos 5 always think and reject `disabled` — leave thinking unset
        ("claude-fable-5", False),
        ("claude-mythos-5", False),
        # pre-4.7 default to no thinking — omitting the field already means off
        ("claude-sonnet-4-6", False),
        ("claude-sonnet-4-5", False),
    ],
)
def test_anthropic_reasoning_effort_none_disables_thinking(
    model_name: str, disabled: bool
) -> None:
    """`reasoning_effort="none"` disables thinking only where it applies.

    Sends `thinking:{type:"disabled"}` where thinking is on by default and can be
    turned off (Claude 4.7+, excluding Fable/Mythos); omits it otherwise.
    """
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    params, _e, _h, _b = api.completion_config(
        GenerateConfig(max_tokens=64, reasoning_effort="none")
    )
    if disabled:
        assert params["thinking"] == {"type": "disabled"}
    else:
        assert "thinking" not in params


def test_anthropic_reasoning_effort_high_still_adaptive_on_sonnet_5() -> None:
    """A real effort still routes to adaptive thinking on Sonnet 5 (not disabled)."""
    api = AnthropicAPI(model_name="claude-sonnet-5", api_key="test-key")
    params, _e, _h, _b = api.completion_config(
        GenerateConfig(max_tokens=64, reasoning_effort="high")
    )
    assert params["thinking"]["type"] == "adaptive"


@pytest.mark.parametrize(
    "header_key", ["anthropic_beta", "anthropic-beta", "Anthropic-Beta"]
)
def test_anthropic_full_thinking_beta_via_extra_header(header_key: str) -> None:
    """The beta is honored via extra_headers in both header spellings.

    The underscore form is Inspect's convention; the hyphen form is the literal
    Anthropic header name. Both must be parsed into betas so the beta is both
    detected (for display removal) and forwarded, rather than silently dropped.
    """
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    config = GenerateConfig(
        max_tokens=64,
        reasoning_effort="high",
        extra_headers={header_key: _FULL_THINKING_BETA},
    )
    params, _extra_body, headers, betas = api.completion_config(config)
    assert _FULL_THINKING_BETA in betas
    assert header_key not in headers
    assert "display" not in params["thinking"]


def test_anthropic_full_thinking_beta_via_client_default_header() -> None:
    """The beta is honored when set as a client default header.

    Client default betas (e.g. oauth-2025-04-20) are only merged into the
    per-request betas list after completion_config returns, so detection must
    consult them directly rather than relying on the returned betas.
    """
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    # original casing is preserved by the SDK; detection must be case-insensitive
    cast(dict[str, str], api.client._custom_headers)["Anthropic-Beta"] = (
        _FULL_THINKING_BETA
    )
    config = GenerateConfig(max_tokens=64, reasoning_effort="high")
    params, _extra_body, _headers, _betas = api.completion_config(config)
    assert "display" not in params["thinking"]


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

    # truncated request body (TCP interruption) should be retried
    truncation_response = httpx.Response(
        status_code=400, request=httpx.Request("POST", "https://example.com")
    )
    ex = APIStatusError(
        "error",
        response=truncation_response,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "The request body is not valid JSON: unexpected end of data: line 1 column 18030593 (char 18030592)",
            },
        },
    )
    assert model.api.should_retry(ex)

    # genuine 400 errors should NOT be retried
    genuine_400_response = httpx.Response(
        status_code=400, request=httpx.Request("POST", "https://example.com")
    )
    ex = APIStatusError(
        "error",
        response=genuine_400_response,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "max_tokens: must be at least 1",
            },
        },
    )
    assert not model.api.should_retry(ex)

    # deterministic encoding errors (e.g. surrogate pairs) should NOT be retried
    ex = APIStatusError(
        "error",
        response=httpx.Response(
            status_code=400, request=httpx.Request("POST", "https://example.com")
        ),
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "The request body is not valid JSON: invalid high surrogate in string: line 1 column 73900 (char 73899)",
            },
        },
    )
    assert not model.api.should_retry(ex)


def test_anthropic_handle_bad_request_content_filter_apistatuserror() -> None:
    """Mid-stream content-filter errors arrive as a plain APIStatusError.

    The Anthropic SDK raises errors that occur after streaming has begun via
    `_make_status_error`; because the HTTP response was already 200, the SDK
    can't infer the 400 subclass, so the exception is the base APIStatusError
    rather than BadRequestError. handle_bad_request() must still convert
    "content filtering" messages into a content_filter refusal.
    """
    import httpx
    from anthropic import APIStatusError

    from inspect_ai.model._model_output import ModelOutput

    api = AnthropicAPI(model_name="claude-opus-4-6", api_key="test-key")
    ex = APIStatusError(
        "Output blocked by content filtering policy",
        response=httpx.Response(
            status_code=200,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        ),
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Output blocked by content filtering policy",
            },
        },
    )

    result = api.handle_bad_request(ex)
    assert isinstance(result, ModelOutput)
    assert result.stop_reason == "content_filter"


@pytest.mark.anyio
async def test_anthropic_generate_handles_midstream_content_filter() -> None:
    """generate() must convert a mid-stream APIStatusError into a content_filter refusal.

    Regression: the outer `except APIStatusError` block previously only handled
    status_code == 413 and re-raised everything else, so content-filter errors
    that surfaced mid-stream killed the eval instead of becoming a refusal.
    """
    import httpx
    from anthropic import APIStatusError

    from inspect_ai.model._model_output import ModelOutput

    api = AnthropicAPI(model_name="claude-opus-4-6", api_key="test-key")

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        raise APIStatusError(
            "Output blocked by content filtering policy",
            response=httpx.Response(
                status_code=200,
                request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Output blocked by content filtering policy",
                },
            },
        )

    api._perform_request_and_continuations = fake_perform  # type: ignore[method-assign]

    output, _model_call = await api.generate(
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(max_tokens=64),
    )

    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "content_filter"


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


@skip_if_no_anthropic
async def test_anthropic_count_tokens_multiple_reasoning_blocks() -> None:
    """count_tokens must not 400 on an assistant turn with multiple reasoning blocks.

    Reproduces the production compaction failure: when an assistant message
    carries more than one reasoning block, Anthropic's count_tokens rejects the
    second+ block with a 400 ("`thinking` or `redacted_thinking` blocks in the
    latest assistant message cannot be modified"). Compaction counts message
    subsets, so such a turn reaches count_tokens as the "latest assistant
    message" and trips the check. Verified end-to-end: without thinking
    neutralization this call 400s against the live API; with it, it succeeds.

    Real signatures only come from the API, so we generate first, then build the
    multi-reasoning-block message from the real reasoning content.
    """
    model = get_model(
        "anthropic/claude-opus-4-8",
        config=GenerateConfig(max_tokens=2048, reasoning_effort="medium"),
    )

    output = await model.generate("What is 17 * 23? Reason it through.")
    reasoning = (
        [c for c in output.message.content if isinstance(c, ContentReasoning)]
        if isinstance(output.message.content, list)
        else []
    )
    if not reasoning:
        pytest.skip("model did not emit a reasoning block for this prompt")

    # an assistant turn with two reasoning blocks — the shape that 400'd in
    # production; count it as a subset the way compaction does
    message = ChatMessageAssistant(
        content=[
            reasoning[0],
            reasoning[0].model_copy(deep=True),
            ContentText(text="The answer is 391."),
        ]
    )
    token_count = await model.api.count_tokens([message])
    assert token_count > 0


@skip_if_no_anthropic
async def test_anthropic_count_tokens_empty_reasoning_block() -> None:
    """count_tokens must not 400 on a reasoning block with empty text + signature.

    The other production error: a `ContentReasoning` with an empty summary and an
    empty signature reconstructs to a `thinking` block with empty `thinking` and
    empty `signature`, which the API rejects with "each thinking block must
    contain thinking". (An empty summary with a *valid* signature is accepted —
    it's the empty signature that triggers it.) This needs no real signature, so
    the input is deterministic. Verified end-to-end: without thinking
    neutralization this 400s against the live API; with it, it succeeds.
    """
    model = get_model("anthropic/claude-opus-4-8")
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(summary="", reasoning=""),
            ContentText(text="done"),
        ]
    )
    token_count = await model.api.count_tokens([message])
    assert token_count > 0


@skip_if_no_anthropic
async def test_anthropic_count_tokens_nonempty_thinking_empty_signature() -> None:
    """count_tokens must not 400 on a reasoning block with text but no signature.

    A third production shape (reported alongside the other two): a thinking block
    with *non-empty* summary text but an empty signature reconstructs to a
    `thinking` block with real `thinking` and empty `signature`, which the API
    rejects with "Invalid signature in thinking block" — distinct from the
    empty-text case's "each thinking block must contain thinking". Both stem from
    the same root cause (an empty signature), which is why neutralization strips
    every thinking block regardless of its signature. This needs no real
    signature, so the input is deterministic. Verified end-to-end: without
    neutralization this 400s against the live API; with it, it succeeds.
    """
    model = get_model("anthropic/claude-opus-4-8")
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(
                summary="I'm working through the relativePathTo test cases.",
                reasoning="",
            ),
            ContentText(text="done"),
        ]
    )
    token_count = await model.api.count_tokens([message])
    assert token_count > 0


def test_neutralize_thinking_for_token_counting() -> None:
    """Thinking/redacted blocks are replaced with text before count_tokens.

    Reproduces the two count_tokens 400s that compaction hit: an empty-summary
    thinking block ("each thinking block must contain thinking", from Claude
    4.7+ `display: "omitted"`) and a signature-bearing thinking block in a
    subset's latest assistant message ("blocks ... cannot be modified"). Both
    are dropped from the payload for a robust token estimate.
    """
    from inspect_ai.model._providers.anthropic import (
        neutralize_thinking_for_token_counting,
    )

    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig-empty"},
                {"type": "text", "text": "hello"},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "answer"},
                {"type": "thinking", "thinking": "some summary", "signature": "sig-2"},
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "redacted_thinking", "data": "opaque"}],
        },
        {"role": "user", "content": "unchanged"},
    ]

    result = neutralize_thinking_for_token_counting(messages)  # type: ignore[arg-type]

    def blocks(index: int) -> list[dict[str, Any]]:
        content = result[index]["content"]
        assert isinstance(content, list)
        return cast(list[dict[str, Any]], content)

    for msg in result:
        content = msg["content"]
        if isinstance(content, list):
            assert all(
                b.get("type") not in ("thinking", "redacted_thinking") for b in content
            )

    # empty-summary thinking dropped, sibling text preserved verbatim
    assert blocks(0) == [{"type": "text", "text": "hello"}]
    # non-empty summary converted to text (approximate token weight preserved)
    assert {"type": "text", "text": "some summary"} in blocks(1)
    # a message that was only redacted_thinking never becomes empty
    assert len(blocks(2)) == 1
    assert blocks(2)[0]["type"] == "text"
    # non-assistant messages are untouched
    assert result[3] == {"role": "user", "content": "unchanged"}


async def test_anthropic_count_tokens_strips_thinking_from_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """count_tokens never sends thinking blocks (or a `thinking` param) upstream.

    On a fresh process the thinking-block replay cache is empty, so
    ContentReasoning is reconstructed into a ThinkingBlockParam — exactly the
    cache-miss path that a deployed/resumed run hits. The reconstructed block
    must be neutralized before reaching the API.
    """
    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")

    captured: dict[str, Any] = {}

    async def fake_count_tokens(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return types.SimpleNamespace(input_tokens=123)

    monkeypatch.setattr(api.client.messages, "count_tokens", fake_count_tokens)

    assistant = ChatMessageAssistant(
        content=[
            ContentReasoning(summary="a thinking summary", reasoning="fake-signature"),
            ContentText(text="the answer"),
        ]
    )

    count = await api.count_tokens([assistant])
    assert count == 123

    for msg in captured["messages"]:
        content = msg["content"]
        if isinstance(content, list):
            assert all(
                b.get("type") not in ("thinking", "redacted_thinking") for b in content
            )
    assert "thinking" not in captured


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
    # instance attribute set in __init__, not captured by create_autospec
    api.cache_ttl = None
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
@pytest.mark.parametrize(
    "model_name,expects_top_level_cache_control",
    [
        ("claude-sonnet-4-6", True),
        ("bedrock/us.anthropic.claude-sonnet-4-6", False),
        ("vertex/claude-sonnet-4-6@20250929", False),
    ],
)
async def test_anthropic_top_level_cache_control_skipped_on_bedrock_vertex(
    model_name: str, expects_top_level_cache_control: bool
) -> None:
    """Skip top-level cache_control on Bedrock/Vertex.

    Per Anthropic's docs, top-level cache_control is only supported on the direct
    Claude API and Azure AI Foundry; "support for Amazon Bedrock and Google Vertex
    AI is coming later." Regression: the field was added in PR #3656 without
    gating those services, breaking Anthropic-on-Bedrock with
    `cache_control: Extra inputs are not permitted`.
    ref: https://docs.claude.com/en/docs/build-with-claude/prompt-caching#automatic-caching
    """
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_REGION", "us-east5")

    api = AnthropicAPI(model_name=model_name, api_key="test-key")

    captured: dict[str, Any] = {}

    from inspect_ai.model._model_output import ModelOutput

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    api._perform_request_and_continuations = fake_perform  # type: ignore[method-assign]

    await api.generate(
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(cache_prompt=True),
    )

    assert ("cache_control" in captured) is expects_top_level_cache_control


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


# ---------------------------------------------------------------------------
# effort / reasoning_effort downgrade behavior across model versions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,requested,expected",
    [
        # xhigh: requires 4.7+ (is_claude_latest), downgrades to high otherwise
        ("claude-opus-4-5", "xhigh", "high"),
        ("claude-opus-4-6", "xhigh", "high"),
        ("claude-opus-4-7", "xhigh", "xhigh"),
        # max: requires 4.6+, downgrades to high otherwise
        ("claude-opus-4-5", "max", "high"),
        ("claude-opus-4-6", "max", "max"),
        ("claude-opus-4-7", "max", "max"),
        # baseline values pass through on every supported model
        ("claude-opus-4-5", "low", "low"),
        ("claude-opus-4-6", "medium", "medium"),
        ("claude-opus-4-7", "high", "high"),
    ],
)
def test_anthropic_effort_downgrade(
    model_name: str, requested: str, expected: str
) -> None:
    """The explicit `effort` setting downgrades to `high` when the model is too old."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    config = GenerateConfig(effort=requested, max_tokens=64)  # type: ignore[arg-type]
    params, _extra_body, _headers, betas = api.completion_config(config)
    assert "effort-2025-11-24" in betas
    assert params["output_config"] == {"effort": expected}


@pytest.mark.parametrize(
    "model_name,requested,expected",
    [
        # xhigh: requires 4.7+ in the reasoning_effort path too
        ("claude-opus-4-6", "xhigh", "high"),
        ("claude-opus-4-7", "xhigh", "xhigh"),
        # max: gated by the outer 4.6+ check (returns None on older models)
        ("claude-opus-4-6", "max", "max"),
        ("claude-opus-4-7", "max", "max"),
        # baseline mappings on a supported model
        ("claude-opus-4-6", "minimal", "low"),
        ("claude-opus-4-6", "medium", "medium"),
        ("claude-opus-4-6", "high", "high"),
    ],
)
def test_anthropic_reasoning_effort_downgrade(
    model_name: str, requested: str, expected: str
) -> None:
    """`effort_from_reasoning_effort` mirrors the `effort` downgrade rules for xhigh."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    config = GenerateConfig(reasoning_effort=requested)  # type: ignore[arg-type]
    assert api.effort_from_reasoning_effort(config) == expected


def test_anthropic_reasoning_effort_returns_none_for_old_models() -> None:
    """Models older than 4.6 should not get any reasoning_effort mapping."""
    api = AnthropicAPI(model_name="claude-opus-4-5", api_key="test-key")
    for value in ["low", "medium", "high", "xhigh", "max"]:
        config = GenerateConfig(reasoning_effort=value)  # type: ignore[arg-type]
        assert api.effort_from_reasoning_effort(config) is None


# ---------------------------------------------------------------------------
# sampling param stripping for Claude 4.7+ (adaptive-thinking-only)
# ---------------------------------------------------------------------------


_SAMPLING_PARAMS: dict[str, float | int] = {
    "temperature": 0.0,
    "top_p": 0.9,
    "top_k": 40,
}


def _cfg(**kwargs: Any) -> GenerateConfig:
    return GenerateConfig(max_tokens=64, **kwargs)


@pytest.mark.parametrize("param,value", list(_SAMPLING_PARAMS.items()))
def test_anthropic_claude_4_7_strips_sampling_params(
    param: str, value: float | int
) -> None:
    """Claude 4.7+ rejects temperature/top_p/top_k outright; the provider must omit them."""
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    params, _extra_body, _headers, _betas = api.completion_config(
        _cfg(**{param: value})
    )
    assert param not in params


@pytest.mark.parametrize("param,value", list(_SAMPLING_PARAMS.items()))
def test_anthropic_claude_4_7_strips_sampling_params_with_reasoning_effort_none(
    param: str, value: float | int
) -> None:
    """reasoning_effort='none' must not re-enable sending sampling params on 4.7."""
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    params, _extra_body, _headers, _betas = api.completion_config(
        _cfg(reasoning_effort="none", **{param: value})
    )
    assert param not in params


@pytest.mark.parametrize(
    "model_name", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
)
@pytest.mark.parametrize("param,value", list(_SAMPLING_PARAMS.items()))
def test_anthropic_pre_4_7_keeps_sampling_params_without_thinking(
    model_name: str, param: str, value: float | int
) -> None:
    """Pre-4.7 models still accept sampling params when thinking is off."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    params, _extra_body, _headers, _betas = api.completion_config(
        _cfg(**{param: value})
    )
    assert params[param] == value


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-opus-5-0",
        "claude-sonnet-4-7",
        "claude-sonnet-5-0",
    ],
)
@pytest.mark.parametrize("param,value", list(_SAMPLING_PARAMS.items()))
def test_anthropic_future_4_7_plus_strips_sampling_params(
    model_name: str, param: str, value: float | int
) -> None:
    """All 4.7+ models inherit the adaptive-thinking restriction."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    params, _extra_body, _headers, _betas = api.completion_config(
        _cfg(**{param: value})
    )
    assert param not in params


@pytest.fixture
def _warn_once_messages() -> Any:
    # warn_once dedupes via a module-level list; clear it and yield it so the
    # test can assert on what was emitted. caplog isn't reliable here because
    # init_logger sets propagate=False on the inspect_ai logger once any
    # earlier test triggers it.
    from inspect_ai._util import logger as _inspect_logger

    _inspect_logger._warned.clear()
    yield _inspect_logger._warned
    _inspect_logger._warned.clear()


def test_anthropic_claude_4_7_emits_adaptive_only_warning(
    _warn_once_messages: list[str],
) -> None:
    """Claude 4.7+ should emit the adaptive-only message, not the extended-thinking one."""
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    api.completion_config(_cfg(temperature=0.0))
    assert any(
        "adaptive thinking only" in m and "claude-opus-4-7" in m
        for m in _warn_once_messages
    )
    assert not any("when using extended thinking" in m for m in _warn_once_messages)


def test_anthropic_thinking_model_emits_extended_thinking_warning(
    _warn_once_messages: list[str],
) -> None:
    """A non-adaptive-only thinking model should emit the extended-thinking message."""
    api = AnthropicAPI(model_name="claude-opus-4-6", api_key="test-key")
    api.completion_config(_cfg(reasoning_effort="low", temperature=0.0))
    assert any("when using extended thinking" in m for m in _warn_once_messages)
    assert not any("adaptive thinking only" in m for m in _warn_once_messages)


# ---------------------------------------------------------------------------
# live API exercises against claude-opus-4-7 (require --runapi)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@skip_if_no_anthropic
@pytest.mark.parametrize("effort", ["xhigh", "max"])
async def test_anthropic_effort_xhigh_max_live(effort: str) -> None:
    """Verify the API accepts the new effort values on Claude Opus 4.7."""
    model = get_model(
        "anthropic/claude-opus-4-7",
        config=GenerateConfig(effort=effort, max_tokens=128),  # type: ignore[arg-type]
    )
    response = await model.generate(input="Say hello in one short sentence.")
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_anthropic
@pytest.mark.parametrize("reasoning_effort", ["xhigh", "max"])
async def test_anthropic_reasoning_effort_xhigh_max_live(
    reasoning_effort: str,
) -> None:
    """Verify the API accepts the new reasoning_effort values on Claude Opus 4.7."""
    model = get_model(
        "anthropic/claude-opus-4-7",
        config=GenerateConfig(
            reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
            max_tokens=2048,
        ),
    )
    response = await model.generate(input="What is 2 + 2? Briefly.")
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_opus_4_7_accepts_temperature_config_live() -> None:
    """Regression for #3721: explicit temperature=0.0 must not 400 on Opus 4.7."""
    model = get_model(
        "anthropic/claude-opus-4-7",
        config=GenerateConfig(temperature=0.0, max_tokens=64),
    )
    response = await model.generate(input="Say hello in one short sentence.")
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_opus_4_7_accepts_temperature_with_reasoning_effort_none_live() -> (
    None
):
    """Regression for #3721: reasoning_effort='none' + temperature must not 400 on Opus 4.7."""
    model = get_model(
        "anthropic/claude-opus-4-7",
        config=GenerateConfig(
            reasoning_effort="none",
            temperature=0.0,
            max_tokens=64,
        ),
    )
    response = await model.generate(input="Say hello in one short sentence.")
    assert len(response.completion) >= 1


# ---------------------------------------------------------------------------
# max_tokens caps across model versions (incl. forward-compat routing)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,expected_cap",
    [
        # Opus 4.6+: 128k
        ("claude-opus-4-6", 128000),
        ("claude-opus-4-7", 128000),
        # Hypothetical future minor opus version: 128k via frontier+opus
        ("claude-opus-4-8", 128000),
        # Claude 5 (GA fable + hypothetical tier-named): 128k via "claude 5+" branch
        ("claude-fable-5", 128000),
        ("claude-opus-5-0", 128000),
        ("claude-sonnet-5-0", 128000),
        # Non-opus 4.5 / 4.6+ (incl. 4.7 and future 4.x minor): 64k
        ("claude-sonnet-4-5", 64000),
        ("claude-sonnet-4-6", 64000),
        ("claude-sonnet-4-7", 64000),
        ("claude-sonnet-4-8", 64000),
        ("claude-haiku-4-5", 64000),
        # Opus 4.0 / 4.1: 32k
        ("claude-opus-4-0", 32000),
        ("claude-opus-4-1", 32000),
        # Claude 3.7: 128k (extended output beta)
        ("claude-3-7-sonnet-latest", 128000),
    ],
)
def test_anthropic_max_tokens_caps(model_name: str, expected_cap: int) -> None:
    """Verify max_tokens cap routing for current and hypothetical future models."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    # Inflate via reasoning_tokens so the cap (not the base) decides the result.
    config = GenerateConfig(reasoning_tokens=200000)
    assert api.max_tokens_for_config(config) == expected_cap


@pytest.mark.parametrize(
    "model_name",
    [
        # GA / limited-release names
        "claude-fable-5",
        "claude-mythos-5",
        # forward-compat variants: point release, tier-named, new codename
        "claude-fable-5-1",
        "claude-opus-5-0",
        "claude-saga-5",
    ],
)
def test_anthropic_claude_5_is_known_frontier(model_name: str) -> None:
    """Any claude-*-5 is a known frontier version, not 'latest'/unknown."""
    from inspect_ai.model._providers.anthropic import _supports_memory

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    assert api.is_claude_5() is True
    assert api.is_claude_latest() is False
    assert api.is_claude_frontier() is True
    assert api.is_claude_4_7_or_later() is True
    assert api.is_claude_4_8_or_later() is True
    # native memory tool is enabled for all Claude 5 variants (per the launch docs)
    assert _supports_memory(api.model_family()) is True


# ---------------------------------------------------------------------------
# Native computer-use tool param routing (incl. Claude 5 not supported)
# ---------------------------------------------------------------------------


def _computer_tool_info() -> ToolInfo:
    """Build a ToolInfo that satisfies is_computer_tool_info() (our built-in computer())."""
    from inspect_ai.tool._tool_params import ToolParam, ToolParams
    from inspect_ai.tool._tools._computer._computer import _COMPUTER_TOOL_PARAMETERS

    return ToolInfo(
        name="computer",
        description="computer",
        parameters=ToolParams(
            properties={k: ToolParam(type="string") for k in _COMPUTER_TOOL_PARAMETERS}
        ),
    )


@pytest.mark.parametrize(
    "model_name", ["claude-fable-5", "claude-mythos-5", "claude-opus-5-0"]
)
def test_anthropic_claude_5_computer_use_errors(model_name: str) -> None:
    """Undocumented Claude 5 models error on computer use rather than degrade.

    Covers Fable/Mythos and forward-compat non-Sonnet variants (e.g. Opus 5).
    Sonnet 5 is supported and covered by test_anthropic_computer_use_tool_version.
    """
    from inspect_ai._util.error import PrerequisiteError

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    with pytest.raises(PrerequisiteError) as exc_info:
        api.computer_use_tool_param(_computer_tool_info())
    # PrerequisiteError stores the message on .message (it doesn't call super().__init__);
    # .message is a RenderableType, so coerce to str for the substring checks.
    message = str(exc_info.value.message)
    assert "Computer use is not supported" in message
    assert model_name in message


@pytest.mark.parametrize(
    "model_name,expected_type",
    [
        # Frontier (4.6/4.7/4.8) + Opus 4.5 → computer_20251124
        ("claude-opus-4-8", "computer_20251124"),
        ("claude-opus-4-6", "computer_20251124"),
        ("claude-opus-4-5", "computer_20251124"),
        ("claude-sonnet-4-6", "computer_20251124"),
        # Sonnet 5: the one Claude 5 model Anthropic documents for computer use
        ("claude-sonnet-5", "computer_20251124"),
        # Older 4.x → computer_20250124
        ("claude-sonnet-4-5", "computer_20250124"),
        ("claude-haiku-4-5", "computer_20250124"),
    ],
)
def test_anthropic_computer_use_tool_version(
    model_name: str, expected_type: str
) -> None:
    """Models map to the correct native computer-use tool version."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    param = api.computer_use_tool_param(_computer_tool_info())
    assert param is not None
    assert param["type"] == expected_type


# ---------------------------------------------------------------------------
# max_tokens default-bump for xhigh / max effort (migration-guide ≥64k floor)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,config_kwargs,expected",
    [
        # reasoning_effort: low/medium/high baseline (unchanged)
        ("claude-opus-4-7", {"reasoning_effort": "low"}, 32000 + 4096),
        ("claude-opus-4-7", {"reasoning_effort": "medium"}, 32000 + 10000),
        ("claude-opus-4-7", {"reasoning_effort": "high"}, 32000 + 16000),
        # reasoning_effort xhigh / max → 64k via dict bump (migration guide floor)
        ("claude-opus-4-7", {"reasoning_effort": "xhigh"}, 64000),
        ("claude-opus-4-7", {"reasoning_effort": "max"}, 64000),
        # standalone effort xhigh / max → 64k via post-bump floor
        ("claude-opus-4-7", {"effort": "xhigh"}, 64000),
        ("claude-opus-4-7", {"effort": "max"}, 64000),
        # standalone effort low/medium/high: no bump (just the 32k base)
        ("claude-opus-4-7", {"effort": "high"}, 32000),
        # opus-4-0 caps at 32k even when xhigh requested (cap wins over floor)
        ("claude-opus-4-0", {"effort": "xhigh"}, 32000),
        # sonnet-4-7 (non-opus, 64k cap) with xhigh effort → 64k
        ("claude-sonnet-4-7", {"effort": "xhigh"}, 64000),
    ],
)
def test_anthropic_max_tokens_xhigh_max_floor(
    model_name: str, config_kwargs: dict, expected: int
) -> None:
    """xhigh/max effort should default max_tokens to ≥64k per the migration guide."""
    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    config = GenerateConfig(**config_kwargs)
    assert api.max_tokens_for_config(config) == expected


async def test_anthropic_container_replayed_after_client_tool_call() -> None:
    """Pending code execution must survive the round trip after a client tool call.

    When a turn mixes code-execution-backed server tool use with a client
    tool call, the turn ends with stop_reason "tool_use" while the code
    execution is still pending, and the response carries the container id.
    The follow-up request (which returns the client tool result) must:

    1. replay the pending server_tool_use block in the assistant message
       (the API can't resume work it isn't shown), and
    2. include the container id as the `container` param -- otherwise the
       API rejects the request with "container_id is required when there
       are pending tool uses generated by code execution with tools."

    Both currently fail: the pending block is dropped from the replay, and
    the container id is never sent (it is only threaded through same-turn
    pause_turn continuations).
    """
    from anthropic._models import construct_type
    from anthropic.types import Message

    from inspect_ai.model import ModelOutput
    from inspect_ai.model._providers.anthropic import (
        init_sample_anthropic_assistant_internal,
    )
    from inspect_ai.tool._tool_params import ToolParam, ToolParams

    init_sample_anthropic_assistant_internal()
    container_id = "container_0123456789"

    def message(
        content: list[dict[str, Any]], stop_reason: str, container: bool
    ) -> Message:
        data: dict[str, Any] = {
            "id": "msg_x",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        if container:
            data["container"] = {
                "id": container_id,
                "expires_at": "2026-07-23T00:00:00Z",
            }
        return cast(Message, construct_type(value=data, type_=Message))

    head = message(
        [
            {
                "type": "server_tool_use",
                "id": "srvtoolu_ce1",
                "name": "code_execution",
                "input": {"code": "print('hi')"},
                "caller": {"type": "direct"},
            },
            # no result block for the code execution above -- the client tool
            # call below ended the turn while it was still running
            {
                "type": "tool_use",
                "id": "toolu_client1",
                "name": "lookup_constant",
                "input": {"name": "alpha"},
            },
        ],
        stop_reason="tool_use",
        container=True,
    )
    tail = message([{"type": "text", "text": "done"}], "end_turn", container=False)

    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    create_mock = AsyncMock(side_effect=[head, tail])
    api.client.messages.create = create_mock  # type: ignore[method-assign]

    tools = [
        ToolInfo(
            name="lookup_constant",
            description="Look up a named constant.",
            parameters=ToolParams(
                properties={"name": ToolParam(type="string")}, required=["name"]
            ),
        )
    ]
    config = GenerateConfig()
    user = ChatMessageUser(content="go")

    output, _ = await api.generate([user], tools, "auto", config)
    assert isinstance(output, ModelOutput)
    assistant = output.message
    assert assistant.tool_calls, "client tool call should surface from the response"

    tool_result = ChatMessageTool(
        content="42",
        tool_call_id=assistant.tool_calls[0].id,
        function="lookup_constant",
    )
    output2, _ = await api.generate(
        [user, assistant, tool_result], tools, "auto", config
    )
    assert isinstance(output2, ModelOutput)

    follow_up_request = create_mock.call_args_list[1].kwargs

    # the pending code execution block must be replayed
    replayed_assistant = follow_up_request["messages"][1]
    replayed_blocks = [(b["type"], b.get("id")) for b in replayed_assistant["content"]]
    assert ("server_tool_use", "srvtoolu_ce1") in replayed_blocks

    # and the container id must accompany the request
    assert follow_up_request.get("container") == container_id


async def test_anthropic_stream_capture_restores_container() -> None:
    """The container must survive streaming despite the SDK dropping it.

    The SDK's non-beta stream accumulator drops `message_delta.container`, so
    the final snapshot reports `container=None` even though the wire carried
    the id (anthropics/anthropic-sdk-python#1776). Inspect's stream capture
    must restore it from the raw message_delta event.
    """
    from datetime import datetime, timezone

    from anthropic._models import construct_type
    from anthropic.types import Container, Message

    from inspect_ai.model._providers.anthropic import (
        _capture_compaction_from_stream,
    )

    # snapshot as the SDK produces it today: container missing
    snapshot = cast(
        Message,
        construct_type(
            value={
                "id": "msg_x",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": [{"type": "text", "text": "hi"}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            type_=Message,
        ),
    )
    container = Container(
        id="container_from_delta",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    class FakeStream:
        current_message_snapshot = snapshot

        def __aiter__(self) -> Any:
            async def events() -> Any:
                yield types.SimpleNamespace(type="message_start")
                yield types.SimpleNamespace(
                    type="message_delta",
                    delta=types.SimpleNamespace(type=None, container=container),
                )

            return events()

    message, _ = await _capture_compaction_from_stream(cast(Any, FakeStream()))
    assert message.container is not None
    assert message.container.id == "container_from_delta"
