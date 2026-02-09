import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import CompactionEvent
from inspect_ai.log import EvalLog
from inspect_ai.model._compaction import CompactionNative
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, tool


@skip_if_no_anthropic
@pytest.mark.slow
def test_anthropic_native_compaction_context_preservation() -> None:
    check_native_compaction_context_preservation("anthropic/claude-opus-4-6")


@skip_if_no_anthropic
@pytest.mark.slow
def test_anthropic_native_compaction_context_preservation_reasoning() -> None:
    check_native_compaction_context_preservation(
        "anthropic/claude-opus-4-6", config=GenerateConfig(reasoning_effort="medium")
    )


@skip_if_no_anthropic
@pytest.mark.slow
def test_anthropic_native_compaction_multiple_events() -> None:
    # Note: reasoning_effort cannot be used here because Anthropic's API
    # doesn't support tool_choice (and thus disable_parallel_tool_use) with
    # thinking mode. The model would make all tool calls in parallel, exceeding
    # the context window. Reasoning + compaction is tested separately in
    # test_anthropic_native_compaction_context_preservation_reasoning.
    check_native_compaction_multiple_events("anthropic/claude-opus-4-6")


@skip_if_no_openai
@pytest.mark.slow
def test_openai_native_compaction_context_preservation() -> None:
    check_native_compaction_context_preservation("openai/gpt-5.2")


@skip_if_no_openai
@pytest.mark.slow
def test_openai_native_compaction_multiple_events() -> None:
    check_native_compaction_multiple_events(
        "openai/gpt-5.2", config=GenerateConfig(reasoning_effort="medium")
    )


def check_native_compaction_context_preservation(
    model: str, config: GenerateConfig | None = None
) -> None:
    """Verify native compaction preserves context from tool results.

    This test uses tool results to generate 50k+ tokens (Anthropic's minimum
    for compaction) rather than large initial prompts. This approach better
    tests real-world usage where content accumulates during tool use.
    """
    # The reference ID is embedded in tool results, not the initial prompt
    reference_id = "BLUE_MARBLE_4729"

    task = Task(
        dataset=[
            Sample(
                input=(
                    "Call large_content_with_identifier twice with topics 'history' and 'science'. "
                    "Then report the REFERENCE_ID you found in the tool results using the submit() tool."
                ),
                target=reference_id,
            )
        ],
        solver=react(
            tools=[large_content_with_identifier()],
            # 2 calls at ~32k each = ~64k tokens. Anthropic requires input × 0.9 >= 50k,
            # so we need ~56k+ tokens. Setting threshold=56000 triggers compaction.
            compaction=CompactionNative(threshold=56000),
        ),
        scorer=includes(),
        config=config or GenerateConfig(),
    )

    # Use max_tool_output to allow larger tool results (in bytes)
    # Each tool call generates ~136KB, need at least 150000 bytes
    log = eval(task, model=model, max_tool_output=200000)[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least one compaction event occurred
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 1, (
        f"Expected at least 1 compaction event with 56k+ tokens from tool results. "
        f"Got {len(compaction_events)} events."
    )

    # Verify compaction event has proper structure
    event = compaction_events[0]
    assert event.tokens_before is not None
    assert event.tokens_after is not None
    assert event.tokens_before >= 56000, (
        f"Expected tokens_before >= 56000, got {event.tokens_before}"
    )

    # Verify the model preserved the reference ID through compaction
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    assert reference_id in final_output, (
        f"Expected REFERENCE_ID '{reference_id}' to be preserved in output. "
        f"Output: {final_output[:300]}..."
    )


@tool
def large_content_with_identifier() -> Tool:
    """Tool that returns large content with an embedded reference identifier.

    Used to test native compaction by generating ~32k tokens per call.
    With 2 calls (~64k tokens), this exceeds Anthropic's internal requirement
    that input × 0.9 >= 50k (i.e., need ~56k+ tokens to trigger compaction).
    """

    async def execute(topic: str) -> str:
        """Generate large content with embedded reference ID about a topic.

        Args:
            topic: The topic to generate content about

        Returns:
            Large content with embedded reference identifier
        """
        # Generate ~32k tokens per call
        # "This is context. " ≈ 4 tokens, 8000 repetitions ≈ 32k tokens
        # Byte size: 17 chars × 8000 = 136KB (needs max_tool_output >= 150000)
        # With 2 calls: ~64k tokens, and 64k × 0.9 = 57.6k > Anthropic's 50k minimum
        filler = f"Detailed analysis of {topic}: " + ("This is context. " * 8000)
        return f"{filler}\n\nREFERENCE_ID: BLUE_MARBLE_4729"

    return execute


def get_compaction_events(log: EvalLog) -> list[CompactionEvent]:
    """Extract CompactionEvents from eval log."""
    assert log.samples, "Log must have samples"
    return [e for e in log.samples[0].events if isinstance(e, CompactionEvent)]


def check_native_compaction_multiple_events(
    model: str, config: GenerateConfig | None = None
) -> None:
    """Verify multiple compaction events preserve context from all phases."""
    alpha_ref = "RED_OCEAN_1234"
    beta_ref = "GREEN_FOREST_5678"
    gamma_ref = "PURPLE_MOUNTAIN_9012"

    task = Task(
        dataset=[
            Sample(
                input=(
                    "Call large_content_with_phase_identifier six times:\n"
                    "1. phase='alpha', topic='history'\n"
                    "2. phase='alpha', topic='science'\n"
                    "3. phase='beta', topic='mathematics'\n"
                    "4. phase='beta', topic='philosophy'\n"
                    "5. phase='gamma', topic='art'\n"
                    "6. phase='gamma', topic='music'\n\n"
                    "Then report ALL THREE reference IDs (ALPHA_REF, BETA_REF, and GAMMA_REF) "
                    "you found in the tool results using submit()."
                ),
                target=alpha_ref,  # Just need one for scorer
            )
        ],
        solver=react(
            tools=[large_content_with_phase_identifier()],
            # Each call generates ~48k tokens. With threshold=56k, compaction
            # triggers after every 2 calls. Even if the model shortcuts to
            # 3 calls (one per phase), we still get 2 compaction events:
            # calls 1-2 → compaction, then compacted (~15k) + call 3 (~48k) > 56k.
            compaction=CompactionNative(threshold=56000),
        ),
        scorer=includes(),
        config=config or GenerateConfig(),
    )

    # parallel_tool_calls=False ensures calls happen over multiple turns
    # so tokens accumulate and trigger compaction at the right points
    log = eval(task, model=model, max_tool_output=250000, parallel_tool_calls=False)[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least 2 compaction events occurred
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 2, (
        f"Expected at least 2 compaction events. Got {len(compaction_events)}."
    )

    # Verify all reference IDs preserved through multiple compactions
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    assert alpha_ref in final_output, (
        f"Expected ALPHA_REF '{alpha_ref}' to be preserved. Output: {final_output[:300]}..."
    )
    assert beta_ref in final_output, (
        f"Expected BETA_REF '{beta_ref}' to be preserved. Output: {final_output[:300]}..."
    )
    assert gamma_ref in final_output, (
        f"Expected GAMMA_REF '{gamma_ref}' to be preserved. Output: {final_output[:300]}..."
    )


@tool
def large_content_with_phase_identifier() -> Tool:
    """Tool that returns large content with phase-specific reference identifiers."""

    async def execute(phase: str, topic: str) -> str:
        """Generate large content with phase-specific reference ID.

        Args:
            phase: Either "alpha", "beta", or "gamma" to determine which reference ID
            topic: The topic to generate content about
        """
        # Generate ~48k tokens per call (12000 repetitions × ~4 tokens each).
        # Larger results ensure 2+ compaction events even if the model
        # shortcuts to 3 calls (one per phase) when using reasoning.
        filler = f"Detailed analysis of {topic}: " + ("This is context. " * 12000)

        if phase == "alpha":
            return f"{filler}\n\nALPHA_REF: RED_OCEAN_1234"
        elif phase == "beta":
            return f"{filler}\n\nBETA_REF: GREEN_FOREST_5678"
        else:
            return f"{filler}\n\nGAMMA_REF: PURPLE_MOUNTAIN_9012"

    return execute
