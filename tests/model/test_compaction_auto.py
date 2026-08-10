"""Tests for the CompactionAuto strategy."""

import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._compaction._compaction import compaction
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.model._compaction.native import CompactionNative
from inspect_ai.model._model import Model, get_model
from inspect_ai.tool._tool_info import ToolInfo


def _sample_messages() -> list[ChatMessage]:
    """Create a simple message list for testing."""
    return [
        ChatMessageSystem(content="System prompt", id="sys1"),
        ChatMessageUser(content="Hello", id="msg1"),
        ChatMessageAssistant(content="Hi there", id="msg2"),
        ChatMessageUser(content="How are you?", id="msg3"),
        ChatMessageAssistant(content="I'm doing well.", id="msg4"),
    ]


async def test_auto_uses_fallback_on_unsupported_provider() -> None:
    """CompactionAuto falls back to summary on unsupported providers."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Should succeed via fallback (no exception)
    result, summary = await strategy.compact(model, messages, [])

    # Should return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)


async def test_auto_fallback_is_stateless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CompactionAuto tries native on every call (no sticky state)."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    native_call_count = 0
    original_compact = strategy._native.compact

    async def counting_compact(m: object, msgs: object, t: object) -> object:
        nonlocal native_call_count
        native_call_count += 1
        return await original_compact(m, msgs, t)  # type: ignore[arg-type]

    monkeypatch.setattr(strategy._native, "compact", counting_compact)

    await strategy.compact(model, messages, [])
    await strategy.compact(model, messages, [])

    assert native_call_count == 2


async def test_auto_parameter_forwarding() -> None:
    """CompactionAuto forwards parameters to internal strategies."""
    threshold = 0.8
    instructions = "Focus on code snippets"
    memory = False

    strategy = CompactionAuto(
        threshold=threshold,
        instructions=instructions,
        memory=memory,
    )

    # Verify parameters are forwarded to internal strategies
    assert strategy._native.threshold == threshold
    assert strategy._native._instructions == instructions
    assert strategy._native.memory == memory

    assert strategy._summary.threshold == threshold
    assert strategy._summary.instructions == instructions
    assert strategy._summary.memory == memory


async def test_auto_memory_auto_default() -> None:
    """CompactionAuto defaults memory to 'auto' — True since fallback may occur."""
    strategy = CompactionAuto()

    # Default memory setting should be "auto"
    assert strategy._memory_setting == "auto"
    # Native doesn't need memory
    assert strategy._native.memory is False
    # Summary benefits from memory warnings
    assert strategy._summary.memory is True
    # Memory property returns True (conservative — can't predict native support)
    assert strategy.memory is True


async def test_auto_no_warning_on_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CompactionAuto does not warn when provider doesn't support native compaction."""
    warnings: list[str] = []

    import inspect_ai.model._compaction.auto as auto_module

    monkeypatch.setattr(
        auto_module.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg))
    )

    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    await strategy.compact(model, messages, [])

    assert len(warnings) == 0


async def test_auto_memory_explicit_true() -> None:
    """CompactionAuto with memory=True enables memory for both strategies."""
    strategy = CompactionAuto(memory=True)

    assert strategy._memory_setting is True
    assert strategy._native.memory is True
    assert strategy._summary.memory is True
    assert strategy.memory is True


async def test_auto_memory_explicit_false() -> None:
    """CompactionAuto with memory=False disables memory for both strategies."""
    strategy = CompactionAuto(memory=False)

    assert strategy._memory_setting is False
    assert strategy._native.memory is False
    assert strategy._summary.memory is False
    assert strategy.memory is False


async def test_auto_warns_on_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CompactionAuto logs a warning when native compaction fails with a non-NotImplementedError."""
    warnings: list[str] = []

    import inspect_ai.model._compaction.auto as auto_module

    monkeypatch.setattr(
        auto_module.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg))
    )

    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Patch native to raise a real error (not NotImplementedError)
    async def failing_compact(m, msgs, t):
        raise RuntimeError("API rate limit exceeded")

    monkeypatch.setattr(strategy._native, "compact", failing_compact)

    result, _ = await strategy.compact(model, messages, [])

    # Should fall back to summary successfully
    assert len(result) > 0
    # Should have logged a warning
    assert len(warnings) == 1
    assert "Native compaction failed" in warnings[0]
    assert "Falling back to summary compaction" in warnings[0]


@skip_if_no_openai
async def test_auto_uses_native_when_supported() -> None:
    """CompactionAuto uses native compaction when the provider supports it."""
    strategy = CompactionAuto()
    model = get_model("openai/gpt-5.3-codex")
    messages = _sample_messages()

    result, summary = await strategy.compact(model, messages, [])

    # Native compaction should return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)

    # Native compaction returns None for the supplemental message
    assert summary is None


@skip_if_no_anthropic
async def test_auto_fallback_on_unsupported_anthropic_model() -> None:
    """CompactionAuto falls back on unsupported Anthropic models."""
    strategy = CompactionAuto()
    # Use an older model that doesn't support compaction
    config = GenerateConfig(max_tokens=4096)
    model = get_model("anthropic/claude-haiku-4-5", config=config)
    messages = _long_messages()  # Need enough tokens to pass minimum threshold

    # Should succeed via fallback since model doesn't support compaction
    result, summary = await strategy.compact(model, messages, [])
    assert len(result) > 0


def _long_messages() -> list[ChatMessage]:
    """Create a message list with enough tokens to meet the minimum compaction threshold.

    Anthropic requires minimum 50k tokens for compaction trigger.
    With trigger at 90%, we need ~56k tokens total.
    """
    # Each repetition is ~20 tokens, so 100 reps = ~2000 tokens per message
    long_text = (
        "This is a detailed explanation of various topics including science, "
        "mathematics, history, and philosophy. " * 100
    ).strip()
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant.", id="sys1"),
    ]
    # 30 pairs * ~4000 tokens per pair = ~120k tokens (well above 56k minimum)
    for i in range(30):
        messages.append(ChatMessageUser(content=long_text, id=f"user_{i}"))
        messages.append(
            ChatMessageAssistant(content=f"Response {i}: {long_text}", id=f"asst_{i}")
        )
    # End with user message so API can respond
    messages.append(ChatMessageUser(content="Please continue.", id="final_user"))
    return messages


async def test_auto_outcome_native_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native success reports CompactionNative and its prefix rule."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")

    async def fake_native(m: object, msgs: object, t: object) -> object:
        return [ChatMessageAssistant(content="[COMPACTED BLOCK]", id="block")], None

    monkeypatch.setattr(strategy._native, "compact", fake_native)

    outcome = await strategy.compact_outcome(model, _sample_messages(), [])

    assert outcome.applied == "CompactionNative"
    assert outcome.preserve_prefix is False
    assert outcome.fallback_reason is None
    assert [m.id for m in outcome.input] == ["block"]


async def test_auto_outcome_unsupported_fallback_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported provider falls back to summary, records why, logs nothing."""
    import inspect_ai.model._compaction.auto as auto_module

    warnings: list[str] = []
    monkeypatch.setattr(
        auto_module.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg))
    )

    strategy = CompactionAuto()
    model = get_model("mockllm/model")

    async def unsupported(m: object, msgs: object, t: object) -> object:
        raise NotImplementedError("provider does not support native compaction")

    monkeypatch.setattr(strategy._native, "compact", unsupported)

    outcome = await strategy.compact_outcome(model, _sample_messages(), [])

    assert outcome.applied == "CompactionSummary"
    assert outcome.preserve_prefix is True
    assert "not supported" in (outcome.fallback_reason or "")
    assert warnings == []


async def test_auto_outcome_error_fallback_records_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected native failure records the reason and still warns."""
    import inspect_ai.model._compaction.auto as auto_module

    warnings: list[str] = []
    monkeypatch.setattr(
        auto_module.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg))
    )

    strategy = CompactionAuto()
    model = get_model("mockllm/model")

    async def boom(m: object, msgs: object, t: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(strategy._native, "compact", boom)

    outcome = await strategy.compact_outcome(model, _sample_messages(), [])

    assert outcome.applied == "CompactionSummary"
    assert "kaboom" in (outcome.fallback_reason or "")
    assert len(warnings) == 1


async def test_auto_compact_still_returns_two_tuple() -> None:
    """compact() keeps its public 2-tuple signature."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")

    result, summary = await strategy.compact(model, _sample_messages(), [])

    assert isinstance(result, list)
    assert len(result) > 0


def _anthropic_shaped_compact():
    """A stub native compact() returning Anthropic's compaction shape."""

    async def compact(m: object, msgs: object, t: object) -> object:
        return [
            ChatMessageAssistant(content="[COMPACTED BLOCK]", id="block"),
            ChatMessageUser(content="Please continue working.", id="continue"),
        ], None

    return compact


def _prefix() -> list[ChatMessage]:
    return [
        ChatMessageSystem(content="System prompt", id="sys1"),
        ChatMessageUser(content="Initial input", id="input1", source="input"),
    ]


async def test_auto_native_matches_plain_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CompactionAuto on its native path must equal plain CompactionNative."""
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [
        *_prefix(),
        ChatMessageAssistant(content="A" * 200, id="msg1"),
        ChatMessageUser(content="Q" * 200, id="msg2"),
    ]

    auto = CompactionAuto(threshold=100)
    monkeypatch.setattr(auto._native, "compact", _anthropic_shaped_compact())
    auto_handler = compaction(auto, prefix=_prefix(), tools=None, model=model)

    native = CompactionNative(threshold=100)
    monkeypatch.setattr(native, "compact", _anthropic_shaped_compact())
    native_handler = compaction(native, prefix=_prefix(), tools=None, model=model)

    auto_result, _ = await auto_handler.compact_input(list(messages))
    native_result, _ = await native_handler.compact_input(list(messages))

    assert [m.id for m in auto_result] == [m.id for m in native_result]
    assert not any(m.id == "input1" for m in auto_result)


async def test_auto_native_then_summary_fallback_restores_prompt_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After native drops the input, a later summary fallback restores it once."""
    model = get_model("mockllm/model")
    auto = CompactionAuto(threshold=100)

    calls = {"n": 0}

    async def flaky_native(m: object, msgs: object, t: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                ChatMessageAssistant(content="[COMPACTED BLOCK]", id="block"),
                ChatMessageUser(content="Please continue working.", id="continue"),
            ], None
        raise NotImplementedError("native compaction did not trigger")

    monkeypatch.setattr(auto._native, "compact", flaky_native)
    handler = compaction(auto, prefix=_prefix(), tools=None, model=model)

    # Content must be long enough that [sys1, input1, msg1] alone exceeds the
    # threshold=100 on the very first call (200 chars only counts ~34 tokens
    # with mockllm's tokenizer and never triggers compaction at all).
    first, _ = await handler.compact_input(
        [*_prefix(), ChatMessageAssistant(content="A" * 800, id="msg1")]
    )
    assert first[0].role == "system"
    assert not any(m.id == "input1" for m in first)

    second, _ = await handler.compact_input(
        [*first, ChatMessageAssistant(content="B" * 800, id="msg2")]
    )

    assert second[0].role == "system"
    assert sum(1 for m in second if m.role == "system") == 1
    assert sum(1 for m in second if m.id == "input1") == 1


class _MarkerAuto(CompactionAuto):
    """A CompactionAuto subclass overriding compact() with a post-processing step.

    Third-party shape: this is the pattern the orchestrator's per-call switch
    to compact_outcome() must not silently bypass.
    """

    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        result, message = await super().compact(model, messages, tools)
        marker = ChatMessageUser(content="MARKER", id="marker")
        return [*result, marker], message


async def test_auto_subclass_compact_override_runs_through_orchestrator() -> None:
    """A subclass overriding compact() is not bypassed by compact_outcome()."""
    model = get_model("mockllm/model")
    strategy = _MarkerAuto(threshold=100)
    handler = compaction(strategy, prefix=_prefix(), tools=None, model=model)

    messages: list[ChatMessage] = [
        *_prefix(),
        ChatMessageAssistant(content="A" * 200, id="msg1"),
        ChatMessageUser(content="Q" * 200, id="msg2"),
    ]

    result, _ = await handler.compact_input(messages)

    assert any(m.id == "marker" for m in result)


async def test_auto_subclass_compact_outcome_direct_call_terminates() -> None:
    """compact_outcome() on a compact()-overriding subclass must not recurse.

    Reports `applied` as the subclass name since the subclass has replaced
    the delegation logic and per-delegate provenance can't be known.
    """
    model = get_model("mockllm/model")
    strategy = _MarkerAuto(threshold=100)

    outcome = await strategy.compact_outcome(model, _sample_messages(), [])

    assert any(m.id == "marker" for m in outcome.input)
    assert outcome.applied == "_MarkerAuto"
