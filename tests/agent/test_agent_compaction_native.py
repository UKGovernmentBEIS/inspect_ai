"""End-to-end tests for native compaction with real API calls.

These tests verify that CompactionNative works correctly with real
Anthropic and OpenAI API calls, including:
1. Multiple compaction events occur in a trajectory
2. Semantic context is preserved through compaction
"""

import pytest
from test_helpers.utils import flaky_retry, skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import CompactionEvent
from inspect_ai.log import EvalLog
from inspect_ai.model._compaction import CompactionNative
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, tool

# --- Helper Functions ---


def get_compaction_events(log: EvalLog) -> list[CompactionEvent]:
    """Extract CompactionEvents from eval log."""
    assert log.samples, "Log must have samples"
    return [e for e in log.samples[0].events if isinstance(e, CompactionEvent)]


@tool
def token_filler() -> Tool:
    """Tool that returns large filler content to help trigger compaction."""

    async def execute(topic: str = "general") -> str:
        """Generate filler content about a topic.

        Args:
            topic: The topic to generate content about

        Returns:
            A large string of content about the topic
        """
        # Generate approximately 3000-4000 tokens of filler
        # ~1.3 tokens per word, so ~2500 words
        base_content = f"""
        Detailed analysis of {topic}:

        This comprehensive exploration covers multiple aspects and considerations.
        We examine the theoretical foundations, practical applications, and future directions.
        The subject matter requires careful attention to nuance and context.
        """
        # Repeat to reach target size
        return (base_content.strip() + " ") * 150

    return execute


@tool
def large_content_with_secret() -> Tool:
    """Tool that returns large content with an embedded secret code.

    Used to test Anthropic native compaction by generating ~32k tokens per call.
    With 2 calls (~64k tokens), this exceeds Anthropic's internal requirement
    that input × 0.9 >= 50k (i.e., need ~56k+ tokens to trigger compaction).
    """

    async def execute(topic: str) -> str:
        """Generate large content with embedded secret about a topic.

        Args:
            topic: The topic to generate content about

        Returns:
            Large content with embedded secret code
        """
        # Generate ~32k tokens per call
        # "This is context. " ≈ 4 tokens, 8000 repetitions ≈ 32k tokens
        # Byte size: 17 chars × 8000 = 136KB (needs max_tool_output >= 150000)
        # With 2 calls: ~64k tokens, and 64k × 0.9 = 57.6k > Anthropic's 50k minimum
        filler = f"Detailed analysis of {topic}: " + ("This is context. " * 8000)
        return f"{filler}\n\nIMPORTANT SECRET_CODE: VELVET_THUNDER_3847"

    return execute


# --- OpenAI Tests ---


@skip_if_no_openai
@flaky_retry(max_retries=2)
def test_openai_native_compaction_multiple_events() -> None:
    """Verify OpenAI native compaction triggers at least one compaction event.

    Note: The exact number of compaction events depends on model behavior
    (how many tool calls it makes before submitting). We verify that:
    1. At least one compaction event occurs
    2. The compaction shows token reduction
    3. Context is preserved (codes are in output)
    """
    # Embed unique codes that should be preserved through compaction
    unique_facts = {
        "ALPHA_CODE": "PURPLE_GIRAFFE_9182",
        "BETA_CODE": "ORANGE_ELEPHANT_7364",
    }

    prompt = f"""You have been given these important codes to remember:
- ALPHA_CODE: {unique_facts["ALPHA_CODE"]}
- BETA_CODE: {unique_facts["BETA_CODE"]}

IMPORTANT: You MUST use the token_filler tool exactly 4 times before submitting.
Use these topics in order: 'history', 'science', 'technology', 'mathematics'.

After all 4 tool calls, provide your final answer including BOTH codes you were given
at the start (ALPHA_CODE and BETA_CODE values).
"""

    task = Task(
        dataset=[Sample(input=prompt, target=unique_facts["ALPHA_CODE"])],
        solver=react(
            tools=[token_filler()],
            # Low threshold - each tool result is ~5000 tokens
            # Should trigger compaction after ~2 tool calls
            compaction=CompactionNative(threshold=8000),
        ),
        scorer=includes(),
        message_limit=20,
    )

    log = eval(task, model="openai/gpt-5.1-codex")[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least one compaction event occurred
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 1, (
        f"Expected at least 1 compaction event, got {len(compaction_events)}"
    )

    # Verify compaction events show token reduction
    for event in compaction_events:
        assert event.tokens_before is not None
        assert event.tokens_after is not None
        # Native compaction should reduce tokens
        assert event.tokens_before >= event.tokens_after, (
            f"Compaction should not increase tokens: {event.tokens_before} -> {event.tokens_after}"
        )

    # Verify the model preserved at least one of the unique codes
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    preserved_code = (
        unique_facts["ALPHA_CODE"] in final_output
        or unique_facts["BETA_CODE"] in final_output
    )
    assert preserved_code, (
        f"Expected model to preserve at least one code in output. "
        f"Looking for '{unique_facts['ALPHA_CODE']}' or '{unique_facts['BETA_CODE']}' "
        f"in: {final_output[:500]}..."
    )


# --- Anthropic Tests ---


@skip_if_no_anthropic
@pytest.mark.slow
@flaky_retry(max_retries=1)
def test_anthropic_native_compaction_context_preservation() -> None:
    """Verify Anthropic native compaction preserves context from tool results.

    This test uses tool results to generate 50k+ tokens (Anthropic's minimum
    for compaction) rather than large initial prompts. This approach better
    tests real-world usage where content accumulates during tool use.
    """
    # The secret is embedded in tool results, not the initial prompt
    secret_code = "VELVET_THUNDER_3847"

    task = Task(
        dataset=[
            Sample(
                input=(
                    "Call large_content_with_secret twice with topics 'history' and 'science'. "
                    "Then report the SECRET_CODE you found in the tool results."
                ),
                target=secret_code,
            )
        ],
        solver=react(
            tools=[large_content_with_secret()],
            # 2 calls at ~32k each = ~64k tokens. Anthropic requires input × 0.9 >= 50k,
            # so we need ~56k+ tokens. Setting threshold=56000 triggers compaction.
            compaction=CompactionNative(threshold=56000),
        ),
        scorer=includes(),
        message_limit=15,
    )

    # Use max_tool_output to allow larger tool results (in bytes)
    # Each tool call generates ~136KB, need at least 150000 bytes
    log = eval(task, model="anthropic/claude-opus-4-6", max_tool_output=200000)[0]

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

    # Verify the model preserved the secret through compaction
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    assert secret_code in final_output, (
        f"Expected SECRET_CODE '{secret_code}' to be preserved in output. "
        f"Output: {final_output[:300]}..."
    )
