"""Tests for mid-conversation system messages on Claude Opus 4.8+.

https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages
"""

from typing import Any

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util.content import Content, ContentText, ContentToolUse
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


async def _resolve_system(
    api: AnthropicAPI, input: list[ChatMessage]
) -> tuple[list[Any] | None, list[Any]]:
    system_param, _, _, message_params, _ = await api.resolve_chat_input(
        input=input, tools=[], config=GenerateConfig(cache_prompt=False)
    )
    return system_param, message_params


@pytest.mark.anyio
async def test_mid_conv_system_supported_4_8_pulls_leading_only() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="A"),
        ChatMessageSystem(content="B"),
        ChatMessageUser(content="hi"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["A", "B"]
    # nothing inline (no mid-conv system to emit)
    assert [m["role"] for m in msgs] == ["user"]


@pytest.mark.anyio
async def test_mid_conv_system_kept_when_trailing_4_8() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),
        ChatMessageUser(content="more"),
        ChatMessageSystem(content="from now on, French"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "system"]
    assert msgs[-1]["content"] == "from now on, French"


@pytest.mark.anyio
async def test_mid_conv_system_consecutive_merged() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageSystem(content="rule A"),
        ChatMessageSystem(content="rule B"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user", "system"]
    assert msgs[-1]["content"] == "rule A\n\nrule B"


@pytest.mark.anyio
async def test_mid_conv_system_invalid_position_hoisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.model._providers import anthropic as anthropic_mod

    warnings: list[str] = []
    monkeypatch.setattr(
        anthropic_mod.logger,
        "warning",
        lambda msg, *a, **kw: warnings.append(str(msg)),
    )
    # also bypass warn_once's dedup cache
    monkeypatch.setattr(
        anthropic_mod, "warn_once", lambda _logger, msg: warnings.append(str(msg))
    )

    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    # mid system sits between assistant (non-server-tool-use) and user — invalid
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),
        ChatMessageSystem(content="bad-position"),
        ChatMessageUser(content="more"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead", "bad-position"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert any("repositioned" in w for w in warnings)


@pytest.mark.anyio
async def test_mid_conv_system_after_tool_result_valid() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    # tool result maps to user-role on the wire → valid prev for a system msg
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(
            content="ok",
            tool_calls=[ToolCall(id="t1", function="f", arguments={})],
        ),
        ChatMessageTool(content="result", tool_call_id="t1"),
        ChatMessageSystem(content="mid"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    # tool result was converted to a user-role MessageParam; mid system follows it
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "system"]


@pytest.mark.anyio
async def test_mid_conv_system_after_server_tool_use_valid() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    server_tool = ContentToolUse(
        tool_type="web_search",
        id="s1",
        name="web_search",
        arguments="{}",
        result="...",
    )
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content=[server_tool]),
        ChatMessageSystem(content="mid"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "system"]


@pytest.mark.anyio
async def test_mid_conv_system_unsupported_becomes_reminder_4_7() -> None:
    # On 4.7 (no mid-conv support) only the leading block is hoisted; a
    # mid-conversation system becomes a <system-reminder> user turn rather
    # than being hoisted (which would bust the prompt cache).
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),
        ChatMessageSystem(content="from now on, French"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == (
        "<system-reminder>\nfrom now on, French\n</system-reminder>"
    )


@pytest.mark.anyio
async def test_mid_conv_reminder_merges_with_adjacent_user_4_7() -> None:
    # A reminder converted from a mid-conv system merges into the preceding
    # user turn via the consecutive-user reducer.
    api = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageSystem(content="be brief"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"] == "hi\n<system-reminder>\nbe brief\n</system-reminder>"


@pytest.mark.anyio
async def test_mid_conv_reminder_used_for_bedrock_4_8() -> None:
    # Bedrock has no mid-conv support even on 4.8, so it uses the reminder
    # fallback rather than native role="system" turns.
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")

    api = AnthropicAPI(model_name="bedrock/claude-opus-4-8", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(content="lead"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),
        ChatMessageSystem(content="mid"),
    ]
    system_param, msgs = await _resolve_system(api, input)
    assert system_param is not None
    assert [b["text"] for b in system_param] == ["lead"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "<system-reminder>\nmid\n</system-reminder>"


def test_supports_mid_conv_off_for_bedrock_and_vertex_4_8() -> None:
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_REGION", "us-east5")

    bedrock_api = AnthropicAPI(model_name="bedrock/claude-opus-4-8", api_key="test-key")
    vertex_api = AnthropicAPI(model_name="vertex/claude-opus-4-8", api_key="test-key")
    api_4_7 = AnthropicAPI(model_name="claude-opus-4-7", api_key="test-key")
    api_4_8 = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")

    assert bedrock_api.supports_mid_conversation_system() is False
    assert vertex_api.supports_mid_conversation_system() is False
    assert api_4_7.supports_mid_conversation_system() is False
    assert api_4_8.supports_mid_conversation_system() is True


# ---------------------------------------------------------------------------
# Live API
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_mid_conversation_system_live() -> None:
    """A trailing mid-conversation system instruction is honored by the model."""
    model = get_model(
        "anthropic/claude-opus-4-8",
        config=GenerateConfig(max_tokens=120, cache_prompt=False),
    )
    response = await model.generate(
        input=[
            ChatMessageSystem(content="Reply in one short sentence."),
            ChatMessageUser(content="What color is the sky on a clear day?"),
            ChatMessageAssistant(content="The sky is blue."),
            ChatMessageUser(content="Name a fruit."),
            # Mid-conversation system: must be obeyed for this turn.
            ChatMessageSystem(
                content=("From now on, respond only in French. Use no English words.")
            ),
        ]
    )
    assert response.completion
    # French response will contain at least one non-ASCII accented character
    # (é, à, etc.) or at minimum a French-specific word; assert it's clearly
    # not English by checking for common French markers.
    text = response.completion.lower()
    assert any(
        marker in text for marker in ("le ", "la ", "une ", "un ", "est ", "c'est")
    ), f"expected French response, got: {response.completion!r}"


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_mid_conversation_system_caches_live() -> None:
    """Appending a mid-conversation system message preserves the cached prefix."""
    model = get_model(
        "anthropic/claude-opus-4-8",
        config=GenerateConfig(max_tokens=50, cache_prompt=True),
    )

    # Build a cacheable user message (>1024 tokens of stable content).
    paragraph = "The quick brown fox jumps over the lazy dog. " * 80
    stable_blocks: list[Content] = [
        ContentText(text=f"Reference passage {i}: {paragraph}") for i in range(3)
    ]

    base: list[ChatMessage] = [
        ChatMessageSystem(content="You are a precise assistant."),
        ChatMessageUser(content=stable_blocks),
    ]
    response1 = await model.generate(input=base)
    assert response1.usage is not None

    # Append assistant reply + a new user turn + mid-conv system.
    # The cached prefix (system + first user) should still match.
    followup: list[ChatMessage] = base + [
        ChatMessageAssistant(content=response1.completion),
        ChatMessageUser(content="Summarize the passage in one sentence."),
        ChatMessageSystem(content="From now on, answer with exactly five words."),
    ]
    response2 = await model.generate(input=followup)
    assert response2.usage is not None
    assert (response2.usage.input_tokens_cache_read or 0) > 0
