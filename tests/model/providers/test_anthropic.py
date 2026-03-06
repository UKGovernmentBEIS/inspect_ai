import types
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentToolUse
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
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


def test_anthropic_fast_mode_config_opus_4_6() -> None:
    """Test that speed='fast' produces correct request params for Opus 4.6."""
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
    model = get_model("anthropic/claude-opus-4-6")
    api: Any = model.api
    config = GenerateConfig(speed="fast", max_tokens=64)
    params, extra_body, _headers, betas = api.completion_config(config)
    assert extra_body.get("speed") == "fast"
    assert "fast-mode-2026-02-01" in betas


def test_anthropic_fast_mode_config_non_4_6_ignored() -> None:
    """Test that speed='fast' is silently ignored on non-4.6 models."""
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
    model = get_model("anthropic/claude-sonnet-4-5")
    api: Any = model.api
    config = GenerateConfig(speed="fast", max_tokens=64)
    params, extra_body, _headers, betas = api.completion_config(config)
    assert "speed" not in extra_body
    assert "fast-mode-2026-02-01" not in betas


def test_anthropic_fast_mode_with_effort() -> None:
    """Test that speed='fast' and effort='low' coexist correctly."""
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
    model = get_model("anthropic/claude-opus-4-6")
    api: Any = model.api
    config = GenerateConfig(speed="fast", effort="low", max_tokens=64)
    params, extra_body, _headers, betas = api.completion_config(config)
    assert extra_body.get("speed") == "fast"
    assert "fast-mode-2026-02-01" in betas
    assert "effort-2025-11-24" in betas
    assert params.get("output_config") == {"effort": "low"}


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
