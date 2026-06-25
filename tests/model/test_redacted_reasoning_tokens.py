"""Tests for the redacted-reasoning-tokens metadata stamp and provider flag.

The stamp lives in `Model.generate()` (extracted as `_stamp_redacted_reasoning_tokens`)
and writes a `redacted_reasoning_tokens` metadata key onto the assistant message
when ALL reasoning blocks in the response are redacted. Compaction reads it
when the provider declares the input-counting blind spot via
`apply_redacted_reasoning_tokens_to_input()`.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._model import (
    REDACTED_REASONING_TOKENS_METADATA_KEY,
    _stamp_redacted_reasoning_tokens,
)


def _make_output(content: list, reasoning_tokens: int | None = 100) -> ModelOutput:
    """Build a ModelOutput with the given content and reasoning_tokens count."""
    output = ModelOutput.from_message(
        ChatMessageAssistant(content=content, model="test")
    )
    output.usage = ModelUsage(
        input_tokens=10,
        output_tokens=200,
        total_tokens=210,
        reasoning_tokens=reasoning_tokens,
    )
    return output


# ---- Stamp behavior ----


def test_stamp_writes_metadata_for_all_redacted_response() -> None:
    output = _make_output(
        [
            ContentReasoning(reasoning="enc", redacted=True),
            ContentText(text="answer"),
        ],
        reasoning_tokens=512,
    )
    _stamp_redacted_reasoning_tokens(output)
    assert output.message.metadata is not None
    assert output.message.metadata[REDACTED_REASONING_TOKENS_METADATA_KEY] == 512, (
        "Expected stamped count to equal usage.reasoning_tokens"
    )


def test_stamp_skips_when_no_reasoning_blocks() -> None:
    output = _make_output(
        [ContentText(text="just text")],
        reasoning_tokens=512,
    )
    _stamp_redacted_reasoning_tokens(output)
    metadata = output.message.metadata or {}
    assert REDACTED_REASONING_TOKENS_METADATA_KEY not in metadata, (
        "No reasoning blocks present — stamp should not run"
    )


def test_stamp_skips_when_any_reasoning_block_is_visible() -> None:
    output = _make_output(
        [
            ContentReasoning(reasoning="enc", redacted=True),
            ContentReasoning(reasoning="visible thinking", redacted=False),
            ContentText(text="answer"),
        ],
        reasoning_tokens=512,
    )
    _stamp_redacted_reasoning_tokens(output)
    metadata = output.message.metadata or {}
    assert REDACTED_REASONING_TOKENS_METADATA_KEY not in metadata, (
        "Mixed visible/redacted reasoning — single usage.reasoning_tokens "
        "can't be split between them, so the stamp should be skipped"
    )


def test_stamp_skips_when_reasoning_tokens_zero_or_none() -> None:
    output_zero = _make_output(
        [ContentReasoning(reasoning="enc", redacted=True)],
        reasoning_tokens=0,
    )
    _stamp_redacted_reasoning_tokens(output_zero)
    md_zero = output_zero.message.metadata or {}
    assert REDACTED_REASONING_TOKENS_METADATA_KEY not in md_zero

    output_none = _make_output(
        [ContentReasoning(reasoning="enc", redacted=True)],
        reasoning_tokens=None,
    )
    _stamp_redacted_reasoning_tokens(output_none)
    md_none = output_none.message.metadata or {}
    assert REDACTED_REASONING_TOKENS_METADATA_KEY not in md_none


def test_stamp_preserves_existing_metadata() -> None:
    output = _make_output(
        [ContentReasoning(reasoning="enc", redacted=True)],
        reasoning_tokens=256,
    )
    output.message.metadata = {"unrelated": "value"}
    _stamp_redacted_reasoning_tokens(output)
    md = output.message.metadata or {}
    assert md.get("unrelated") == "value"
    assert md.get(REDACTED_REASONING_TOKENS_METADATA_KEY) == 256


# ---- Provider flag ----


def test_openai_apply_flag_responses_vs_chat_completions() -> None:
    """OpenAIAPI overrides the flag to follow `self.responses_api`."""
    from inspect_ai.model._providers.openai import OpenAIAPI

    # __new__ avoids full init (no API key etc.)
    api_responses = OpenAIAPI.__new__(OpenAIAPI)
    api_responses.responses_api = True
    assert api_responses.apply_redacted_reasoning_tokens_to_input() is True

    api_chat = OpenAIAPI.__new__(OpenAIAPI)
    api_chat.responses_api = False
    assert api_chat.apply_redacted_reasoning_tokens_to_input() is False


def test_default_flag_is_false() -> None:
    """Base ModelAPI defaults the flag to False.

    Non-OpenAI providers inherit the default and don't accidentally apply
    the correction.
    """
    from inspect_ai.model._providers.mockllm import MockLLM

    # mockllm doesn't override → inherits the default
    api = MockLLM.__new__(MockLLM)
    assert api.apply_redacted_reasoning_tokens_to_input() is False


# ---- Live API end-to-end ----


OPENAI_REASONING_MODEL = "openai/gpt-5-mini"
OPENAI_REASONING_CONFIG = GenerateConfig(reasoning_effort="high")
OPENAI_REASONING_PROMPT = (
    "Compute the exact final integer for this expression: "
    "(137 * 241) - (89 * 173) + (4567 * 13) - 42. "
    "Return only the integer."
)


@skip_if_no_openai
@pytest.mark.slow
async def test_openai_responses_stamps_redacted_reasoning_tokens_e2e() -> None:
    """End-to-end: OpenAI Responses with reasoning stamps the metadata.

    Calls the live OpenAI Responses API and asserts that the wrapper's
    metadata stamp ran with the value from `usage.reasoning_tokens`. This
    is the test the original PR was missing — without it, a regression in
    the stamp logic would only surface on real workloads with compaction
    enabled. Use a small multi-step prompt with high reasoning effort so
    the live API reliably reports non-zero reasoning tokens.
    """
    model = get_model(
        OPENAI_REASONING_MODEL,
        config=OPENAI_REASONING_CONFIG,
    )

    # Sanity-check the test is actually exercising the path under test:
    # the OpenAI override should report True for Responses API. If the model
    # ever stops defaulting to Responses, this assertion catches the silent
    # change.
    assert model.api.apply_redacted_reasoning_tokens_to_input(), (
        "expected the OpenAI Responses API path; the e2e is testing the "
        "wrong code path otherwise"
    )

    output = await model.generate(OPENAI_REASONING_PROMPT)

    assert output.usage is not None
    assert output.usage.reasoning_tokens, (
        "expected non-zero reasoning_tokens from a reasoning model"
    )

    metadata = output.message.metadata or {}
    assert REDACTED_REASONING_TOKENS_METADATA_KEY in metadata, (
        f"expected wrapper to stamp {REDACTED_REASONING_TOKENS_METADATA_KEY!r} "
        f"on the assistant message; got metadata={metadata!r}"
    )
    assert (
        metadata[REDACTED_REASONING_TOKENS_METADATA_KEY]
        == output.usage.reasoning_tokens
    ), (
        f"stamped value should equal usage.reasoning_tokens; "
        f"got {metadata[REDACTED_REASONING_TOKENS_METADATA_KEY]!r} "
        f"vs {output.usage.reasoning_tokens!r}"
    )


@skip_if_no_openai
@pytest.mark.slow
async def test_compaction_counts_redacted_reasoning_tokens_e2e(monkeypatch) -> None:
    """End-to-end: compaction's threshold computation reads the stamped count.

    Generates a real OpenAI Responses turn (which stamps metadata) and then
    asks compaction's `_redacted_reasoning_tokens_total` helper to sum the
    metadata across the resulting message list. The helper should report
    exactly `usage.reasoning_tokens` from the response — the same number
    that the API omits from `usage.input_tokens` and that compaction needs
    to add back when checking its threshold.

    This closes the gap the original PR's tests had: it doesn't just check
    that the metadata exists, it verifies the count flows through the
    actual compaction code path against a real Responses-API response.
    """
    from inspect_ai.model._compaction._compaction import (
        _redacted_reasoning_tokens_total,
    )

    model = get_model(
        OPENAI_REASONING_MODEL,
        config=OPENAI_REASONING_CONFIG,
    )
    assert model.api.apply_redacted_reasoning_tokens_to_input(), (
        "expected the OpenAI Responses API path"
    )

    prompt = OPENAI_REASONING_PROMPT
    output = await model.generate(prompt)
    assert output.usage is not None
    assert output.usage.reasoning_tokens

    messages: list[ChatMessage] = [
        ChatMessageUser(content=prompt),
        output.message,
    ]

    # With the flag on (OpenAI Responses default), the helper sums the
    # stamped metadata and returns the redacted reasoning token count —
    # the exact value the threshold check needs to add back.
    assert (
        _redacted_reasoning_tokens_total(messages, model)
        == output.usage.reasoning_tokens
    ), (
        "compaction's helper should sum the stamped metadata to recover "
        "the reasoning_tokens count that usage.input_tokens omits"
    )

    # Sanity check the provider flag gates the correction: with the flag
    # off, the helper returns 0 even though the metadata is present.
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: False
    )
    assert _redacted_reasoning_tokens_total(messages, model) == 0


@skip_if_no_openai
@pytest.mark.slow
async def test_compaction_threshold_trips_on_baseline_plus_redacted_e2e() -> None:
    """End-to-end: baseline shortcut + redacted correction trips threshold.

    Runs `compact.compact_input(...)` against a real OpenAI Responses turn
    and asserts that compaction trips at a threshold that's strictly between
    `baseline_tokens` alone (would not trip) and `baseline_tokens +
    redacted_reasoning_tokens` (does trip). Then re-runs with the provider
    flag patched off and asserts the same workload does NOT trip — proving
    the trip in the first run is driven specifically by the redacted-
    reasoning correction in the baseline-shortcut branch.

    Uses try/finally instead of pytest's `monkeypatch` because flaky_retry
    re-invokes the test function on failure but `monkeypatch` only undoes
    on test teardown — leaking patched state across retries. The pattern
    here cleans up at the end of each attempt.

    Complements the synthetic
    `test_baseline_shortcut_trips_only_with_redacted_reasoning_correction`:
    one extra real generate, catches API-shape changes the synthetic test
    can't see.
    """
    from inspect_ai.model._compaction._compaction import compaction
    from inspect_ai.model._compaction.trim import CompactionTrim

    model = get_model(
        "openai/gpt-5-mini",
        config=GenerateConfig(reasoning_effort="low"),
    )

    # Prompt chosen to reliably produce non-trivial reasoning_tokens.
    # Trivial prompts ("2+5") sometimes return reasoning_tokens=0 because
    # the model elects not to reason; this would break the threshold-trip
    # arithmetic below.
    prompt = (
        "Find three positive integers a < b < c with a + b + c = 12 and "
        "a * b * c = 36. Show your reasoning briefly."
    )
    output = await model.generate(prompt)
    assert output.usage is not None
    if not output.usage.reasoning_tokens:
        pytest.skip(
            "Model returned reasoning_tokens=0 for a reasoning-heavy prompt; "
            "the threshold-trip arithmetic depends on a non-zero count."
        )

    baseline_input_tokens = output.usage.input_tokens
    redacted = output.usage.reasoning_tokens

    # Threshold strictly between baseline alone and baseline + redacted.
    # With the correction off: total ≈ baseline + small + 0 < threshold → no trip.
    # With the correction on:  total ≈ baseline + small + redacted > threshold → trip.
    threshold = baseline_input_tokens + redacted // 2

    api = model.api

    def patch_flag(value: bool) -> None:
        api.apply_redacted_reasoning_tokens_to_input = lambda: value  # type: ignore[method-assign]

    def restore_flag() -> None:
        # Remove instance-level shadow; the class-level method takes over again.
        api.__dict__.pop("apply_redacted_reasoning_tokens_to_input", None)

    async def run_and_check_trip(*, expect_trip: bool) -> None:
        compact = compaction(
            CompactionTrim(threshold=threshold, preserve=0.5),
            prefix=[],
            tools=None,
            model=model,
        )
        # Install the real baseline directly via record_output. Doing this
        # without first calling compact_input keeps the test focused on
        # the baseline-shortcut branch and avoids a count-tokens-path call
        # whose `count_tokens([user, assistant_full_response])` can itself
        # exceed threshold (because the assistant text is substantial)
        # and confuse the assertion below.
        initial: list[ChatMessage] = [
            ChatMessageUser(content=prompt),
            output.message,
        ]
        await compact.record_output(initial, output)

        # Add a tiny new user message and run compaction. With baseline set
        # and baseline_ids ⊆ target_ids, this hits the baseline-shortcut
        # branch. With correction on:  total ≈ baseline + small + redacted
        # > threshold → trip. With correction off: total ≈ baseline + small
        # < threshold → no trip.
        followup: list[ChatMessage] = initial + [ChatMessageUser(content="Why?")]
        result, _ = await compact.compact_input(followup)

        if expect_trip:
            assert len(result) < len(followup), (
                f"expected compaction to trip at threshold={threshold}: "
                f"baseline_input_tokens={baseline_input_tokens}, "
                f"redacted_reasoning_tokens={redacted}; "
                f"got {len(result)} messages from {len(followup)} input"
            )
        else:
            assert len(result) == len(followup), (
                f"expected NO compaction with correction off; "
                f"got {len(result)} messages from {len(followup)} input"
            )

    try:
        # First pass: correction on (matches OpenAI Responses default).
        patch_flag(True)
        await run_and_check_trip(expect_trip=True)

        # Second pass: correction off → must not trip. This proves the
        # trip in the first pass was driven by the redacted_reasoning_tokens
        # correction, not by the plain baseline + new-user-message tokens.
        patch_flag(False)
        await run_and_check_trip(expect_trip=False)
    finally:
        restore_flag()
