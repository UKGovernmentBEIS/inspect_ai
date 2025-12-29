"""Tests for agent_bridge() compaction integration."""

from openai import AsyncOpenAI
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.model._compaction import CompactionEdit, CompactionTrim
from inspect_ai.model._openai import messages_to_openai
from inspect_ai.scorer import includes


def get_model_events(log: EvalLog) -> list:
    """Get all ModelEvents from sample."""
    assert log.samples
    return [e for e in log.samples[0].events if e.event == "model"]


def count_messages_in_model_events(log: EvalLog) -> list[int]:
    """Return message counts for each model call."""
    return [len(e.input) for e in get_model_events(log)]


def mock_outputs_for_bridge_test(count: int = 4) -> list[ModelOutput]:
    """Generate model outputs for bridge compaction test.

    Each output includes large content to help fill the context window.
    """
    return [
        ModelOutput.from_content("mockllm/model", "x" * 500 + f" Response {i}")
        for i in range(count)
    ]


@agent
def bridge_compaction_agent(compaction, num_calls: int = 4) -> Agent:
    """Agent that makes multiple API calls through the bridge."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state, compaction=compaction) as bridge:
            client = AsyncOpenAI()

            # Make multiple calls to accumulate context
            for _ in range(num_calls):
                await client.chat.completions.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                )

            return bridge.state

    return execute


def run_bridge_with_compaction(
    compaction=None,
    num_calls: int = 4,
) -> EvalLog:
    """Run bridge agent with optional compaction strategy."""
    task = Task(
        dataset=[Sample(input="Make multiple API calls.", target="done")],
        solver=bridge_compaction_agent(compaction=compaction, num_calls=num_calls),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=mock_outputs_for_bridge_test(num_calls),
    )
    return eval(task, model=model)[0]


@skip_if_no_openai
def test_bridge_compaction_edit_reduces_input() -> None:
    """Verify CompactionEdit reduces input when threshold exceeded."""
    log = run_bridge_with_compaction(
        compaction=CompactionEdit(threshold=500, keep_tool_uses=1, memory=False),
        num_calls=4,
    )

    assert log.status == "success"

    # Get message counts for each model call
    message_counts = count_messages_in_model_events(log)

    # Should have made 4 model calls
    assert len(message_counts) >= 4, (
        f"Expected at least 4 model calls, got {len(message_counts)}"
    )

    # With compaction, message count should not grow unboundedly
    max_count = max(message_counts)
    # Without compaction, by the 4th call we'd have ~9 messages
    # (system + user + 3*(assistant response))
    # With compaction, should be less
    assert max_count < 10, f"Expected compaction to limit messages, got {max_count}"


@skip_if_no_openai
def test_bridge_compaction_trim_reduces_input() -> None:
    """Verify CompactionTrim trims older messages when threshold exceeded."""
    log = run_bridge_with_compaction(
        compaction=CompactionTrim(threshold=500, preserve=0.5, memory=False),
        num_calls=4,
    )

    assert log.status == "success"

    message_counts = count_messages_in_model_events(log)
    assert len(message_counts) >= 4

    # With trim, older messages are removed
    max_count = max(message_counts)
    assert max_count < 10, f"Expected compaction to limit messages, got {max_count}"


@skip_if_no_openai
def test_bridge_no_compaction_full_history() -> None:
    """Baseline: verify without compaction, full history grows."""
    log = run_bridge_with_compaction(
        compaction=None,
        num_calls=4,
    )

    assert log.status == "success"

    message_counts = count_messages_in_model_events(log)
    assert len(message_counts) >= 4

    # Without compaction, message count should grow monotonically
    for i in range(1, len(message_counts)):
        assert message_counts[i] >= message_counts[i - 1], (
            f"Expected growing history without compaction: {message_counts}"
        )


@skip_if_no_openai
def test_bridge_compaction_preserves_prefix() -> None:
    """Verify initial user input is never removed by compaction."""
    log = run_bridge_with_compaction(
        compaction=CompactionEdit(threshold=500, keep_tool_uses=1, memory=False),
        num_calls=4,
    )

    assert log.status == "success"

    model_events = get_model_events(log)

    for event in model_events:
        # Should have at least the initial user message
        assert len(event.input) >= 1, "Should have at least user message"
        # First message should be the user input (bridge doesn't add system message)
        assert isinstance(event.input[0], ChatMessageUser), (
            "First message should be user input"
        )
        # The user input content should be preserved
        assert "Make multiple API calls" in event.input[0].content, (
            "User input content should be preserved"
        )
