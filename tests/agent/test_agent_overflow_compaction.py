"""Tests for forced-compaction recovery in the react agent's overflow path."""

import pytest
from typing_extensions import override

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._compaction import CompactionStrategy
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.tool._tool_info import ToolInfo


class _AlwaysRaisesCompaction(CompactionStrategy):
    """Test-only strategy that always raises when compact() is called."""

    def __init__(self) -> None:
        # High threshold so predictive compaction never triggers; only
        # forced compaction (force=True) will invoke compact().
        super().__init__(type="trim", threshold=10_000, memory=False)

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        raise RuntimeError("simulated compaction failure")


@pytest.mark.parametrize(
    "react_factory",
    [
        pytest.param(lambda **kw: react(**kw), id="react"),
        pytest.param(
            lambda **kw: react(submit=False, **kw),  # exercises react_no_submit path
            id="react_no_submit",
        ),
    ],
)
def test_model_length_with_compaction_triggers_force_and_continues(
    react_factory,
) -> None:
    """Forced compaction recovers from model_length when compaction is configured.

    When generate returns model_length and compaction is configured,
    the overflow handler invokes forced compaction and the agent continues.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after compaction",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react_factory(
            compaction=CompactionTrim(threshold=10_000),
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", f"Agent should have recovered. Status: {log.status}"

    # Verify the recovery emitted a differentiated CompactionEvent. This is
    # the load-bearing assertion: it confirms that _handle_overflow invoked
    # compact_input(force=True), which is the wiring this task adds.
    from inspect_ai.event import CompactionEvent

    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, CompactionEvent)]
    assert any(e.source == "inspect_recovery" for e in events), (
        "Expected at least one CompactionEvent with source='inspect_recovery' "
        f"from forced compaction; got sources {[e.source for e in events]}"
    )


@pytest.mark.parametrize(
    "strategy_factory",
    [
        pytest.param(
            lambda: CompactionTrim(threshold=10_000, preserve=0.5),
            id="trim",
        ),
        # CompactionEdit reduces message *content* (replaces tool results
        # with TOOL_RESULT_REMOVED) but not message *count*. This test
        # verifies that recovery happens despite no count reduction --
        # the previous len(compacted) < len(previous_messages) gate broke
        # this path.
        pytest.param(
            lambda: CompactionEdit(threshold=10_000, keep_tool_uses=0),
            id="edit",
        ),
    ],
)
def test_model_length_with_compaction_recovers_and_continues(strategy_factory) -> None:
    """With a realistic conversation, forced compaction recovers and the agent continues.

    The submit answer is the canary -- if the agent broke out on overflow
    instead of recovering, it would never reach submit. We additionally
    assert there are no duplicate message IDs in the recovered history,
    which guards against summary-style strategies where the c_message
    object is also the last element of the compacted input.
    """
    # Build conversation: 10 plain turns (each adds an assistant message
    # and a default-continue user prompt = 20 messages), then overflow,
    # then recovery, then submit.
    custom_outputs = [
        ModelOutput.from_content(model="mockllm/model", content=f"Turn {i}")
        for i in range(10)
    ]
    custom_outputs.extend(
        [
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after compaction",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ]
    )

    model = get_model("mockllm/model", custom_outputs=custom_outputs)

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(compaction=strategy_factory()),
        message_limit=100,
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    # Canary: the submit was reached only if the agent recovered from overflow.
    assert log.samples
    output_text = log.samples[0].output.completion or ""
    assert "done" in output_text, (
        f"Expected agent to reach submit after overflow recovery; "
        f"got output completion: {output_text!r}"
    )

    # Guard against C1 (CompactionSummary duplicate-summary regression):
    # any message with an id should appear exactly once.
    ids = [m.id for m in log.samples[0].messages if m.id]
    assert len(ids) == len(set(ids)), (
        f"Duplicate message IDs detected in recovered history: {ids}"
    )


def test_model_length_with_compaction_failure_falls_through_to_filter() -> None:
    """Falls through to overflow filter when forced compaction fails.

    If forced compaction raises (e.g., RuntimeError 'compaction insufficient'),
    the existing overflow filter takes over.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after truncation",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    # Use a strategy that always raises when compact() is invoked.
    # The high threshold ensures predictive compaction never triggers;
    # only forced compaction in _handle_overflow will invoke compact().
    impossible_strategy = _AlwaysRaisesCompaction()

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            compaction=impossible_strategy,
            truncation="auto",  # Falls back to message-trim filter
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", (
        "Agent should have recovered via the truncation filter even when "
        f"forced compaction fails. Status: {log.status}"
    )


def test_model_length_without_recovery_terminates() -> None:
    """No compaction, no overflow filter: the agent terminates cleanly."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(),  # No compaction, default truncation="disabled"
    )

    log = eval(task, model=model)[0]
    # Agent should NOT have submitted (no successful path).
    assert log.samples
    sample = log.samples[0]
    last_message = sample.messages[-1] if sample.messages else None
    if last_message is not None:
        # If there's a final message, it should be the failed assistant turn,
        # not a submit tool call.
        assert "submit" not in (
            last_message.content if isinstance(last_message.content, str) else ""
        ), "Agent should not have reached submit when no recovery is configured"
