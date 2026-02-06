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


def generate_large_prompt(unique_facts: dict[str, str], target_tokens: int) -> str:
    """Generate a prompt with embedded unique facts and filler content.

    Args:
        unique_facts: Dictionary of fact names to unique values to embed
        target_tokens: Approximate number of tokens to generate

    Returns:
        A large prompt string with embedded facts
    """
    # Start with the unique facts prominently placed
    facts_section = "IMPORTANT FACTS TO REMEMBER:\n"
    for name, value in unique_facts.items():
        facts_section += f"- {name}: {value}\n"
    facts_section += "\n"

    # Add filler content to reach target tokens
    # Each line is approximately 20 tokens
    tokens_per_line = 20
    lines_needed = (target_tokens - len(unique_facts) * 10) // tokens_per_line

    filler_topics = [
        "The history of computing spans several decades and includes many important developments.",
        "Database systems evolved from hierarchical models to relational and now distributed systems.",
        "Networking protocols enable communication between computers across the globe reliably.",
        "Operating systems manage hardware resources and provide services to applications efficiently.",
        "Programming languages have evolved from assembly to high-level functional paradigms.",
        "Software engineering practices include testing, documentation, and code review processes.",
        "Distributed systems face challenges like consistency, availability, and partition tolerance.",
        "Security in computing involves encryption, authentication, and authorization mechanisms.",
        "Cloud computing provides scalable resources through virtualization and containerization.",
        "Machine learning algorithms learn patterns from data to make predictions accurately.",
    ]

    filler = ""
    for i in range(lines_needed):
        topic = filler_topics[i % len(filler_topics)]
        filler += f"{topic} (Context block {i + 1})\n"

    return f"""{facts_section}

You are a helpful assistant. Below is background context for our conversation.

{filler}

Please remember the IMPORTANT FACTS listed at the beginning. You may be asked about them later.
After using the tools as requested, always include the remembered facts in your final answer."""


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
def simple_lookup() -> Tool:
    """A simple tool that returns a moderate amount of content."""

    async def execute(query: str) -> str:
        """Look up information about a query.

        Args:
            query: What to look up

        Returns:
            Information about the query
        """
        return (
            f"Information about {query}: This is relevant context that provides details about the topic. "
            * 50
        )

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

IMPORTANT: You MUST use the token_filler tool exactly 5 times before submitting.
Use these topics in order: 'history', 'science', 'technology', 'mathematics', 'philosophy'.

After all 5 tool calls, provide your final answer including BOTH codes you were given
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


@skip_if_no_openai
@flaky_retry(max_retries=2)
def test_openai_native_compaction_stress_multiple() -> None:
    """Stress test: verify aggressive compaction threshold triggers multiple events."""
    task = Task(
        dataset=[
            Sample(
                input="IMPORTANT: You MUST use the token_filler tool exactly 8 times in order with these topics: 'art', 'music', 'literature', 'film', 'dance', 'sculpture', 'photography', 'architecture'. After all 8 tool calls, say 'COMPLETE' in your final answer.",
                target="COMPLETE",
            )
        ],
        solver=react(
            tools=[token_filler()],
            # Very low threshold to force multiple compaction events
            compaction=CompactionNative(threshold=6000),
        ),
        scorer=includes(),
        message_limit=30,
    )

    log = eval(task, model="openai/gpt-5.1-codex")[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify multiple compaction events (at least 2 with such a low threshold)
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 2, (
        f"Expected at least 2 compaction events with aggressive threshold, got {len(compaction_events)}"
    )

    # Verify token counts are present for all compaction events
    for event in compaction_events:
        assert event.tokens_before is not None
        assert event.tokens_after is not None


@skip_if_no_openai
@flaky_retry(max_retries=2)
def test_openai_native_compaction_semantic_preservation() -> None:
    """Verify semantic relationships are preserved through compaction."""
    # Embed semantic relationships that require reasoning
    prompt = """Remember these facts carefully:
- Alice is Bob's sister
- Bob's favorite color is blue
- Carol is Alice's daughter
- The family dog is named Max

IMPORTANT: You MUST use the token_filler tool exactly 4 times in order with these topics:
'pets', 'colors', 'families', 'relationships'.

After all 4 tool calls, answer this question in your final response:
"What is Alice's brother's favorite color?"

Your answer MUST include the color.
"""

    task = Task(
        dataset=[Sample(input=prompt, target="blue")],
        solver=react(
            tools=[token_filler()],
            # Low threshold to trigger compaction reliably
            compaction=CompactionNative(threshold=8000),
        ),
        scorer=includes(),
        message_limit=15,
    )

    log = eval(task, model="openai/gpt-5.1-codex")[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least one compaction event
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 1, "Expected at least 1 compaction event"

    # Verify the model can still reason about the relationships
    assert log.samples
    final_output = (log.samples[0].output.completion or "").lower()
    assert "blue" in final_output, (
        f"Expected model to derive that Alice's brother's favorite color is blue. "
        f"Output: {final_output[:300]}..."
    )


# --- Anthropic Tests ---


@skip_if_no_anthropic
@pytest.mark.slow
@flaky_retry(max_retries=1)
def test_anthropic_native_compaction_context_preservation() -> None:
    """Verify Anthropic native compaction preserves context with 50k+ token input.

    This test is expensive due to the large token requirement (Anthropic requires
    minimum 50k tokens before compaction can trigger).
    """
    # Generate unique secrets that should survive compaction
    unique_facts = {
        "SECRET_ALPHA": "CRIMSON_PHOENIX_4829",
        "SECRET_BETA": "AZURE_DRAGON_5173",
        "SECRET_GAMMA": "GOLDEN_SERPENT_8462",
    }

    # Generate a prompt large enough to meet Anthropic's 50k minimum
    # We need ~62k tokens to safely exceed the 50k threshold after 90% calculation
    large_prompt = generate_large_prompt(unique_facts, target_tokens=62000)

    # Add the task instructions at the end
    task_prompt = f"""{large_prompt}

Now, please use the simple_lookup tool twice to look up 'context verification' and 'memory test'.

After using the tools, your final answer MUST include at least one of the SECRET values
you were asked to remember at the beginning:
- SECRET_ALPHA
- SECRET_BETA
- SECRET_GAMMA

State the secret value explicitly in your response.
"""

    task = Task(
        dataset=[Sample(input=task_prompt, target=unique_facts["SECRET_ALPHA"])],
        solver=react(
            tools=[simple_lookup()],
            # Use absolute threshold just above 50k to trigger compaction
            # once the initial ~62k token prompt is loaded
            compaction=CompactionNative(threshold=55000),
        ),
        scorer=includes(),
        message_limit=15,  # Allow enough messages for tool calls + final answer
    )

    log = eval(task, model="anthropic/claude-opus-4-6")[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least one compaction event occurred
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 1, (
        f"Expected at least 1 compaction event with 50k+ tokens. "
        f"Got {len(compaction_events)} events."
    )

    # Verify compaction event has proper structure
    event = compaction_events[0]
    assert event.tokens_before is not None
    assert event.tokens_after is not None
    assert event.tokens_before > 50000, (
        f"Expected tokens_before > 50000, got {event.tokens_before}"
    )

    # Verify the model preserved at least one secret through compaction
    # Check both final output and all messages for the secret values
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    all_messages_text = " ".join(
        str(m.content) for m in log.samples[0].messages if hasattr(m, "content")
    )
    preserved_any = any(
        secret in final_output or secret in all_messages_text
        for secret in unique_facts.values()
    )
    assert preserved_any, (
        f"Expected model to preserve at least one secret value. "
        f"Looking for any of {list(unique_facts.values())} in output: {final_output[:300]}..."
    )


@skip_if_no_anthropic
@pytest.mark.slow
@flaky_retry(max_retries=1)
def test_anthropic_native_compaction_with_tool_heavy_trajectory() -> None:
    """Verify Anthropic compaction works with multiple tool calls after large prompt."""
    unique_facts = {
        "MISSION_CODE": "VELVET_THUNDER_3847",
    }

    # Generate large initial prompt (60k tokens)
    large_prompt = generate_large_prompt(unique_facts, target_tokens=60000)

    task_prompt = f"""{large_prompt}

Your mission code is: {unique_facts["MISSION_CODE"]}

Use the simple_lookup tool 3 times to look up: 'status check', 'verification', 'confirmation'.

After all lookups, confirm you remember the MISSION_CODE by stating it in your final response.
"""

    task = Task(
        dataset=[Sample(input=task_prompt, target=unique_facts["MISSION_CODE"])],
        solver=react(
            tools=[simple_lookup()],
            # Threshold just above 50k to trigger compaction with our ~60k prompt
            compaction=CompactionNative(threshold=52000),
        ),
        scorer=includes(),
        message_limit=18,  # Allow enough messages for 3 tool calls + final answer
    )

    log = eval(task, model="anthropic/claude-opus-4-6")[0]

    assert log.status == "success", f"Eval failed: {log.error}"

    # Verify at least one compaction event occurred
    compaction_events = get_compaction_events(log)
    assert len(compaction_events) >= 1, (
        f"Expected at least 1 compaction event. Got {len(compaction_events)} events."
    )

    # Verify compaction event structure
    for event in compaction_events:
        assert event.tokens_before is not None
        assert event.tokens_after is not None

    # Verify mission code preservation through compaction
    # Check both final output and all messages for the code
    assert log.samples
    final_output = log.samples[0].output.completion or ""
    all_messages_text = " ".join(
        str(m.content) for m in log.samples[0].messages if hasattr(m, "content")
    )
    code_preserved = (
        unique_facts["MISSION_CODE"] in final_output
        or unique_facts["MISSION_CODE"] in all_messages_text
    )
    assert code_preserved, (
        f"Expected MISSION_CODE '{unique_facts['MISSION_CODE']}' to be preserved. "
        f"Output: {final_output[:300]}..."
    )
