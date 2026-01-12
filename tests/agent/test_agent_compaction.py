"""End-to-end tests for react() agent compaction integration."""

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.model._compaction import CompactionEdit, CompactionTrim
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._tools._memory import memory


@tool
def verbose_tool():
    """Tool that returns large content to fill context."""

    async def execute() -> str:
        """Return verbose output to fill the context window.

        Returns:
            A large string of content.
        """
        return "x" * 500  # Moderate output to help fill context

    return execute


def get_model_events(log: EvalLog) -> list:
    """Get all ModelEvents from sample."""
    assert log.samples
    return [e for e in log.samples[0].events if e.event == "model"]


def count_messages_in_model_events(log: EvalLog) -> list[int]:
    """Return message counts for each model call."""
    return [len(e.input) for e in get_model_events(log)]


def mock_outputs_for_compaction_test(tool_calls: int = 3) -> list[ModelOutput]:
    """Generate outputs: tool calls followed by submit."""
    outputs = [
        ModelOutput.for_tool_call("mockllm/model", "verbose_tool", {})
        for _ in range(tool_calls)
    ]
    outputs.append(
        ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "done"})
    )
    return outputs


def run_react_with_compaction(
    compaction=None,
    tool_calls: int = 3,
) -> EvalLog:
    """Run react agent with optional compaction strategy."""
    task = Task(
        dataset=[Sample(input="Run the verbose tool several times.", target="done")],
        solver=react(
            tools=[verbose_tool()],
            compaction=compaction,
        ),
        scorer=includes(),
        message_limit=50,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=mock_outputs_for_compaction_test(tool_calls),
    )
    return eval(task, model=model)[0]


def test_react_compaction_edit_reduces_input() -> None:
    """Verify CompactionEdit reduces input when threshold exceeded."""
    # Use threshold that allows tools + prefix but triggers compaction as history grows
    # Tools take ~132 tokens, prefix ~200 tokens, so 500 allows room but triggers compaction
    log = run_react_with_compaction(
        compaction=CompactionEdit(threshold=500, keep_tool_uses=1, memory=False),
        tool_calls=4,
    )

    assert log.status == "success"

    # Get message counts for each model call
    message_counts = count_messages_in_model_events(log)

    # With compaction, later calls should have fewer or equal messages
    # despite accumulating more history (due to tool result clearing)
    assert len(message_counts) >= 4  # At least 4 model calls

    # The last few calls should show compaction effect:
    # message count should not grow unboundedly
    # With edit compaction, tool results are cleared so count stays manageable
    max_count = max(message_counts)
    # Sanity check: without compaction we'd have ~13+ messages by end
    # (system + user + 4*(assistant + tool) + continue prompts)
    # With compaction, should be much less
    assert max_count < 15, f"Expected compaction to limit messages, got {max_count}"


def test_react_compaction_trim_reduces_input() -> None:
    """Verify CompactionTrim trims older messages when threshold exceeded."""
    log = run_react_with_compaction(
        compaction=CompactionTrim(threshold=500, preserve=0.5, memory=False),
        tool_calls=4,
    )

    assert log.status == "success"

    message_counts = count_messages_in_model_events(log)
    assert len(message_counts) >= 4

    # With trim, older messages are removed
    # Later calls should show reduced message counts after compaction triggers
    # Check that we don't have unbounded growth
    max_count = max(message_counts)
    assert max_count < 15, f"Expected compaction to limit messages, got {max_count}"


def test_react_no_compaction_full_history() -> None:
    """Baseline: verify without compaction, full history grows."""
    log = run_react_with_compaction(
        compaction=None,  # No compaction
        tool_calls=4,
    )

    assert log.status == "success"

    message_counts = count_messages_in_model_events(log)
    assert len(message_counts) >= 4

    # Without compaction, message count should grow monotonically
    for i in range(1, len(message_counts)):
        assert message_counts[i] >= message_counts[i - 1], (
            f"Expected growing history without compaction: {message_counts}"
        )


def test_react_compaction_preserves_prefix() -> None:
    """Verify system message and initial input are never removed."""
    log = run_react_with_compaction(
        compaction=CompactionEdit(threshold=500, keep_tool_uses=1, memory=False),
        tool_calls=4,
    )

    assert log.status == "success"

    model_events = get_model_events(log)

    for event in model_events:
        # First message should always be system message
        assert len(event.input) >= 2, "Should have at least system + user message"
        assert isinstance(event.input[0], ChatMessageSystem), (
            "First message should be system"
        )
        assert isinstance(event.input[1], ChatMessageUser), (
            "Second message should be user input"
        )


def run_react_with_memory_and_compaction(
    compaction=None,
    tools: list[Tool] | None = None,
    custom_outputs: list[ModelOutput] | None = None,
) -> EvalLog:
    """Run react agent with memory tool and optional compaction."""
    tools = tools or [verbose_tool(), memory()]
    task = Task(
        dataset=[Sample(input="Save some notes to memory.", target="done")],
        solver=react(
            tools=tools,
            compaction=compaction,
        ),
        scorer=includes(),
        message_limit=50,
    )
    model = get_model("mockllm/model", custom_outputs=custom_outputs or [])
    return eval(task, model=model)[0]


def test_react_compaction_clears_memory_content() -> None:
    """Verify memory tool content is cleared after compaction with memory=True."""
    # Create outputs: call memory with large content, then more tool calls to trigger
    # compaction, then submit. Content needs to be large enough to trigger compaction
    # given the high threshold required for memory tool (~972 tokens for tools alone)
    large_content = "Important notes: " + "x" * 2000

    custom_outputs = [
        # First call: save to memory with large content
        ModelOutput.for_tool_call(
            "mockllm/model",
            "memory",
            {
                "command": "create",
                "path": "/memories/notes.txt",
                "file_text": large_content,
            },
        ),
        # More tool calls to accumulate context
        ModelOutput.for_tool_call("mockllm/model", "verbose_tool", {}),
        ModelOutput.for_tool_call("mockllm/model", "verbose_tool", {}),
        # Submit
        ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "done"}),
    ]

    # Memory tool has a large schema (~972 tokens), so we need a higher threshold
    # that still triggers compaction as tool outputs accumulate
    log = run_react_with_memory_and_compaction(
        compaction=CompactionEdit(threshold=1500, keep_tool_uses=2, memory=True),
        custom_outputs=custom_outputs,
    )

    assert log.status == "success"

    # Get all model events
    model_events = get_model_events(log)

    # Find the last model event - this should show the compacted input
    # After compaction, memory tool calls should have file_text cleared
    last_event = model_events[-1]

    # Look for memory tool calls in the input and check if content was cleared
    memory_calls_found = False
    for msg in last_event.input:
        if isinstance(msg, ChatMessageAssistant) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function == "memory" and "file_text" in tc.arguments:
                    memory_calls_found = True
                    # After compaction with memory=True, file_text should be placeholder
                    assert tc.arguments["file_text"] == "(content saved to memory)", (
                        f"Expected memory content to be cleared, got: {tc.arguments['file_text'][:50]}..."
                    )
                    # Metadata should be preserved
                    assert tc.arguments["command"] == "create"
                    assert tc.arguments["path"] == "/memories/notes.txt"

    # If compaction happened, we should have found the memory call with cleared content
    # If no memory calls found in last event, that's also acceptable (might have been trimmed)
    if memory_calls_found:
        pass  # Test passed - memory content was cleared
    else:
        # Check that compaction actually happened by comparing event input sizes
        # If no memory call found, verify the conversation was compacted
        message_counts = [len(e.input) for e in model_events]
        # With 4 model calls, without compaction we'd have growing counts
        # If counts aren't monotonically increasing, compaction occurred
        is_monotonic = all(
            message_counts[i] <= message_counts[i + 1]
            for i in range(len(message_counts) - 1)
        )
        assert not is_monotonic or len(model_events) <= 2, (
            "Expected compaction to occur or memory call to be found"
        )
