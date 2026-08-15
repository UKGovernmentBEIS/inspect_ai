"""Tests for the cache diagnostics beta on the Anthropic provider.

Claude API only; opt-in via the `cache-diagnosis-2026-04-07` beta header.
https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics
"""

from typing import Any

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util.content import Content, ContentText
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

_CACHE_DIAG = "cache-diagnosis-2026-04-07"


# ---------------------------------------------------------------------------
# Beta-presence detection
# ---------------------------------------------------------------------------


def test_cache_diag_detects_beta_in_self_betas() -> None:
    api = AnthropicAPI(
        model_name="claude-opus-4-8", api_key="test-key", betas=[_CACHE_DIAG]
    )
    assert api.cache_diagnostics_enabled(GenerateConfig()) is True


@pytest.mark.parametrize(
    "header_key", ["anthropic_beta", "anthropic-beta", "Anthropic-Beta"]
)
def test_cache_diag_detects_beta_in_extra_headers(header_key: str) -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    config = GenerateConfig(extra_headers={header_key: _CACHE_DIAG})
    assert api.cache_diagnostics_enabled(config) is True


def test_cache_diag_detects_beta_in_client_default_headers() -> None:
    """Honor beta set as an SDK client default header.

    Matches the existing OAuth pattern at ANTHROPIC_AUTH_TOKEN setup, where
    the SDK client carries `anthropic-beta` in its default headers rather
    than per-request.
    """
    from typing import cast

    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    # header names are case-insensitive; SDK stores them with caller-cased keys
    cast(dict[str, str], api.client._custom_headers)["Anthropic-Beta"] = _CACHE_DIAG
    assert api.cache_diagnostics_enabled(GenerateConfig()) is True


def test_cache_diag_detects_beta_alongside_other_client_default_betas() -> None:
    """Comma-separated client default betas list — pick out our entry."""
    from typing import cast

    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    cast(dict[str, str], api.client._custom_headers)["anthropic-beta"] = (
        f"oauth-2025-04-20,{_CACHE_DIAG},mcp-client-2025-04-04"
    )
    assert api.cache_diagnostics_enabled(GenerateConfig()) is True


def test_cache_diag_off_when_beta_absent() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    assert api.cache_diagnostics_enabled(GenerateConfig()) is False


def test_cache_diag_off_on_bedrock_and_vertex_even_with_beta() -> None:
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_REGION", "us-east5")

    bedrock = AnthropicAPI(
        model_name="bedrock/claude-opus-4-8",
        api_key="test-key",
        betas=[_CACHE_DIAG],
    )
    vertex = AnthropicAPI(
        model_name="vertex/claude-opus-4-8",
        api_key="test-key",
        betas=[_CACHE_DIAG],
    )
    assert bedrock.cache_diagnostics_enabled(GenerateConfig()) is False
    assert vertex.cache_diagnostics_enabled(GenerateConfig()) is False


# ---------------------------------------------------------------------------
# previous_message_id lookback
# ---------------------------------------------------------------------------


def test_previous_assistant_id_pulled_from_metadata() -> None:
    from inspect_ai.model._providers.anthropic import _previous_assistant_message_id

    input: list[ChatMessage] = [
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello", metadata={"message_id": "msg_abc"}),
        ChatMessageUser(content="more"),
    ]
    assert _previous_assistant_message_id(input) == "msg_abc"


def test_previous_assistant_id_none_when_no_prior_assistant() -> None:
    from inspect_ai.model._providers.anthropic import _previous_assistant_message_id

    assert _previous_assistant_message_id([ChatMessageUser(content="hi")]) is None


def test_previous_assistant_id_none_when_metadata_missing() -> None:
    from inspect_ai.model._providers.anthropic import _previous_assistant_message_id

    input: list[ChatMessage] = [
        ChatMessageAssistant(content="hello"),  # no metadata
    ]
    assert _previous_assistant_message_id(input) is None


def test_previous_assistant_id_walks_back_past_user_and_tool() -> None:
    from inspect_ai.model._providers.anthropic import _previous_assistant_message_id

    input: list[ChatMessage] = [
        ChatMessageAssistant(content="earlier", metadata={"message_id": "msg_earlier"}),
        ChatMessageUser(content="u1"),
        ChatMessageTool(content="t1", tool_call_id="t"),
        ChatMessageUser(content="u2"),
    ]
    # most recent assistant (the only one here) wins
    assert _previous_assistant_message_id(input) == "msg_earlier"


def test_previous_assistant_id_returns_latest_when_multiple() -> None:
    from inspect_ai.model._providers.anthropic import _previous_assistant_message_id

    input: list[ChatMessage] = [
        ChatMessageAssistant(content="first", metadata={"message_id": "msg_1"}),
        ChatMessageUser(content="u1"),
        ChatMessageAssistant(content="second", metadata={"message_id": "msg_2"}),
        ChatMessageUser(content="u2"),
    ]
    assert _previous_assistant_message_id(input) == "msg_2"


# ---------------------------------------------------------------------------
# Request-side wiring
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_request_carries_diagnostics_when_beta_on() -> None:
    """When the beta is on, /v1/messages receives diagnostics in extra_body."""
    api = AnthropicAPI(
        model_name="claude-opus-4-8", api_key="test-key", betas=[_CACHE_DIAG]
    )
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
        input=[
            ChatMessageAssistant(content="prior", metadata={"message_id": "msg_prev"}),
            ChatMessageUser(content="follow-up"),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    diag = (captured.get("extra_body") or {}).get("diagnostics")
    assert diag == {"previous_message_id": "msg_prev"}


@pytest.mark.anyio
async def test_request_carries_diagnostics_with_null_on_first_turn() -> None:
    api = AnthropicAPI(
        model_name="claude-opus-4-8", api_key="test-key", betas=[_CACHE_DIAG]
    )
    captured: dict[str, Any] = {}

    from inspect_ai.model._model_output import ModelOutput

    async def fake_perform(
        request: dict[str, Any], *_args: Any, **_kwargs: Any
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    api._perform_request_and_continuations = fake_perform  # type: ignore[method-assign]

    await api.generate(
        input=[ChatMessageUser(content="first turn")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    diag = (captured.get("extra_body") or {}).get("diagnostics")
    assert diag == {"previous_message_id": None}


@pytest.mark.anyio
async def test_request_omits_diagnostics_when_beta_off() -> None:
    api = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    captured: dict[str, Any] = {}

    from inspect_ai.model._model_output import ModelOutput

    async def fake_perform(
        request: dict[str, Any], *_args: Any, **_kwargs: Any
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    api._perform_request_and_continuations = fake_perform  # type: ignore[method-assign]

    await api.generate(
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    assert "diagnostics" not in (captured.get("extra_body") or {})


# ---------------------------------------------------------------------------
# Response-side capture: message_id on assistant, diagnostics on ModelOutput
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assistant_message_id_captured_when_beta_on() -> None:
    from anthropic.types import Message, Usage

    from inspect_ai.model._providers.anthropic import model_output_from_message

    message = Message(
        id="msg_xyz",
        type="message",
        role="assistant",
        model="claude-opus-4-8",
        stop_reason="end_turn",
        content=[],
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    output, _ = await model_output_from_message(
        client=None,
        model="claude-opus-4-8",
        message=message,
        tools=[],
        cache_diagnostics=True,
    )
    assert output.message.metadata == {"message_id": "msg_xyz"}


@pytest.mark.anyio
async def test_assistant_message_id_not_captured_when_beta_off() -> None:
    from anthropic.types import Message, Usage

    from inspect_ai.model._providers.anthropic import model_output_from_message

    message = Message(
        id="msg_xyz",
        type="message",
        role="assistant",
        model="claude-opus-4-8",
        stop_reason="end_turn",
        content=[],
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    output, _ = await model_output_from_message(
        client=None,
        model="claude-opus-4-8",
        message=message,
        tools=[],
        # cache_diagnostics defaults to False
    )
    assert output.message.metadata is None


@pytest.mark.anyio
async def test_diagnostics_captured_on_model_output_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics goes on ModelOutput.metadata, message_id on the assistant."""
    from anthropic.types import Message

    from inspect_ai.model._providers import anthropic as anthropic_mod
    from inspect_ai.model._providers.anthropic import model_output_from_message

    warnings: list[str] = []
    monkeypatch.setattr(
        anthropic_mod, "warn_once", lambda _logger, msg: warnings.append(str(msg))
    )

    raw = {
        "id": "msg_miss",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-8",
        "stop_reason": "end_turn",
        "content": [],
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "diagnostics": {
            "cache_miss_reason": {
                "type": "system_changed",
                "cache_missed_input_tokens": 4242,
            }
        },
    }
    message = Message.model_validate(raw)

    output, _ = await model_output_from_message(
        client=None,
        model="claude-opus-4-8",
        message=message,
        tools=[],
        cache_diagnostics=True,
    )
    # message_id on the assistant message
    assert output.message.metadata == {"message_id": "msg_miss"}
    # diagnostics on the ModelOutput
    assert output.metadata is not None
    assert (
        output.metadata["diagnostics"]["cache_miss_reason"]["type"] == "system_changed"
    )
    # warning fired naming the reason
    assert any("system_changed" in w for w in warnings)


@pytest.mark.anyio
async def test_diagnostics_pending_no_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`{cache_miss_reason: null}` means comparison still pending — no warning."""
    from anthropic.types import Message

    from inspect_ai.model._providers import anthropic as anthropic_mod
    from inspect_ai.model._providers.anthropic import model_output_from_message

    warnings: list[str] = []
    monkeypatch.setattr(
        anthropic_mod, "warn_once", lambda _logger, msg: warnings.append(str(msg))
    )

    raw = {
        "id": "msg_pending",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-8",
        "stop_reason": "end_turn",
        "content": [],
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "diagnostics": {"cache_miss_reason": None},
    }
    message = Message.model_validate(raw)

    output, _ = await model_output_from_message(
        client=None,
        model="claude-opus-4-8",
        message=message,
        tools=[],
        cache_diagnostics=True,
    )
    assert output.metadata is not None
    assert output.metadata["diagnostics"] == {"cache_miss_reason": None}
    assert warnings == []


# ---------------------------------------------------------------------------
# Live API
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_cache_diagnostics_first_turn_live() -> None:
    """Single request with the beta header; tag the assistant with message_id."""
    import re

    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(
            max_tokens=60,
            cache_prompt=False,
            extra_headers={"anthropic-beta": _CACHE_DIAG},
        ),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="Say hello in one word.")]
    )
    md = response.message.metadata
    assert md is not None
    assert re.match(r"^msg_", md["message_id"])


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_no_message_id_when_beta_off_live() -> None:
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(max_tokens=60, cache_prompt=False),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="Say hello in one word.")]
    )
    md = response.message.metadata
    assert md is None or "message_id" not in md


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_cache_diagnostics_threaded_live() -> None:
    """Turn 1 + turn 2 with stable prefix: no divergence reported."""
    model = get_model(
        "anthropic/claude-sonnet-4-6",
        config=GenerateConfig(
            max_tokens=60,
            cache_prompt=True,
            extra_headers={"anthropic-beta": _CACHE_DIAG},
        ),
    )

    # Make the prefix large enough to be worth caching.
    paragraph = "The quick brown fox jumps over the lazy dog. " * 80
    stable_blocks: list[Content] = [
        ContentText(text=f"Reference passage {i}: {paragraph}") for i in range(3)
    ]
    base: list[ChatMessage] = [
        ChatMessageSystem(content="You are a precise assistant."),
        ChatMessageUser(content=stable_blocks),
    ]
    response1 = await model.generate(input=base)
    prior_id = (response1.message.metadata or {}).get("message_id")
    assert prior_id and prior_id.startswith("msg_")

    followup: list[ChatMessage] = base + [
        response1.message,  # echoes back metadata with message_id
        ChatMessageUser(content="Now summarize the passage in one sentence."),
    ]
    response2 = await model.generate(input=followup)
    asst_md2 = response2.message.metadata or {}
    out_md2 = response2.metadata or {}
    assert asst_md2.get("message_id", "").startswith("msg_")

    # With a stable prefix, diagnostics should report no divergence
    # (None or {cache_miss_reason: None}). A *_changed result would mean
    # our lookback wiring is sending something different than expected.
    diag = out_md2.get("diagnostics")
    if diag is not None:
        reason = diag.get("cache_miss_reason")
        if isinstance(reason, dict):
            assert reason.get("type") in (None, "unavailable"), (
                f"unexpected cache miss reason: {reason}"
            )


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_cache_diagnostics_detects_system_change_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliberately change the system prompt between turns; the API should return system_changed.

    The API returns `cache_miss_reason.type == "system_changed"` and we
    should surface it on ModelOutput.metadata and fire a warning naming the
    type. Exercises the full read path end-to-end (response.diagnostics →
    dict normalization → metadata key → warning), which the threaded
    happy-path test can't verify since it expects no divergence.
    """
    from inspect_ai.model._providers import anthropic as anthropic_mod

    warnings: list[str] = []
    monkeypatch.setattr(
        anthropic_mod,
        "warn_once",
        lambda _logger, msg: warnings.append(str(msg)),
    )

    # Make the prefix big enough that a cache breakpoint is meaningful.
    paragraph = "The quick brown fox jumps over the lazy dog. " * 80
    stable_blocks: list[Content] = [
        ContentText(text=f"Reference passage {i}: {paragraph}") for i in range(3)
    ]

    config = GenerateConfig(
        max_tokens=60,
        cache_prompt=True,
        extra_headers={"anthropic-beta": _CACHE_DIAG},
    )
    model = get_model("anthropic/claude-sonnet-4-6", config=config)

    # Turn 1: establish a cached prefix with system "A".
    turn1: list[ChatMessage] = [
        ChatMessageSystem(content="You are assistant A. Be concise."),
        ChatMessageUser(content=stable_blocks),
    ]
    response1 = await model.generate(input=turn1)
    prior_id = (response1.message.metadata or {}).get("message_id")
    assert prior_id and prior_id.startswith("msg_")

    # Turn 2: identical user content + previous assistant, but a DIFFERENT
    # system prompt. The previous assistant carries metadata.message_id so
    # our lookback feeds it as previous_message_id.
    turn2: list[ChatMessage] = [
        ChatMessageSystem(content="You are assistant B. Verbose is fine."),
        ChatMessageUser(content=stable_blocks),
        response1.message,
        ChatMessageUser(content="What did you just say?"),
    ]
    response2 = await model.generate(input=turn2)

    diag = (response2.metadata or {}).get("diagnostics")
    assert diag is not None, "expected diagnostics on ModelOutput.metadata"
    reason = diag.get("cache_miss_reason")
    assert isinstance(reason, dict), f"expected cache_miss_reason dict, got {reason!r}"
    assert reason.get("type") == "system_changed", (
        f"expected system_changed cache_miss_reason, got {reason!r}"
    )
    assert any("system_changed" in w for w in warnings), (
        f"expected warning to fire naming system_changed; got {warnings!r}"
    )
