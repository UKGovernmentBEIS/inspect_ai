"""Tests for reconstructing EvalSample from buffer DB data."""

from datetime import datetime, timezone

from inspect_ai.event._model import ModelEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import AttachmentData, EventData, SampleData
from inspect_ai.log._recover import reconstruct_eval_sample
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score


def _make_model_event(
    input_messages: list[ChatMessage],
    output_content: str,
) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=input_messages,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=output_content),
    )


def _event_to_event_data(
    event: ModelEvent | StepEvent, id: int, sample_id: str = "1", epoch: int = 1
) -> EventData:
    """Convert a typed event to EventData (simulating buffer DB storage)."""
    from pydantic_core import to_jsonable_python

    return EventData(
        id=id,
        event_id=event.uuid or f"event-{id}",
        sample_id=sample_id,
        epoch=epoch,
        event=to_jsonable_python(event, exclude_none=True),
    )


def _make_completed_summary() -> EvalSampleSummary:
    return EvalSampleSummary(
        id=1,
        epoch=1,
        input="What is 2+2?",
        target="4",
        scores={"accuracy": Score(value="C", answer="4")},
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_in_progress_summary() -> EvalSampleSummary:
    return EvalSampleSummary(
        id=2,
        epoch=1,
        input="What is 3+3?",
        target="6",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def test_reconstruct_completed_sample() -> None:
    """Test reconstructing a completed sample with messages and scores."""
    summary = _make_completed_summary()

    user_msg = ChatMessageUser(content="What is 2+2?")
    model_event = _make_model_event([user_msg], "The answer is 4.")

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1)],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert isinstance(sample, EvalSample)
    assert sample.id == 1
    assert sample.epoch == 1
    assert sample.input == "What is 2+2?"
    assert sample.target == "4"
    assert sample.scores is not None
    assert "accuracy" in sample.scores
    assert sample.error is None

    # Messages extracted from ModelEvent
    assert len(sample.messages) == 2  # user + assistant
    assert sample.messages[0].role == "user"
    assert sample.messages[1].role == "assistant"

    # Output from last ModelEvent
    assert sample.output is not None
    assert not sample.output.empty

    # Events deserialized
    assert len(sample.events) == 1
    assert isinstance(sample.events[0], ModelEvent)


def test_reconstruct_cancelled_sample() -> None:
    """Test reconstructing an in-progress sample with cancellation error."""
    summary = _make_in_progress_summary()

    user_msg = ChatMessageUser(content="What is 3+3?")
    model_event = _make_model_event([user_msg], "Let me think...")

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1, sample_id="2")],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data, cancelled=True)

    assert sample.id == 2
    assert sample.scores is None
    assert sample.error is not None
    assert sample.error.message == "CancelledError()"
    assert "recovered from crashed eval" in sample.error.traceback

    # Still has messages from before crash
    assert len(sample.messages) == 2


def test_reconstruct_no_model_events() -> None:
    """Test reconstruction when there are no ModelEvents."""
    summary = _make_in_progress_summary()

    # Only a StepEvent, no ModelEvent
    step_event = StepEvent(action="begin", name="init")
    sample_data = SampleData(
        events=[_event_to_event_data(step_event, id=1, sample_id="2")],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data, cancelled=True)

    assert sample.messages == []
    assert sample.output == ModelOutput()
    assert len(sample.events) == 1


def test_reconstruct_multiple_model_events() -> None:
    """Test that multiple ModelEvents produce correct message history."""
    summary = _make_completed_summary()

    # First turn
    user1 = ChatMessageUser(content="Hi")
    event1 = _make_model_event([user1], "Hello!")

    # Second turn (includes full history)
    assistant1 = ChatMessageAssistant(content="Hello!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user1, assistant1, user2], "4")

    sample_data = SampleData(
        events=[
            _event_to_event_data(event1, id=1),
            _event_to_event_data(event2, id=2),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    # Messages from the last ModelEvent's input + output
    # (span_messages pattern with "all" compaction, no compaction events)
    assert len(sample.messages) == 4  # user1, assistant1, user2, assistant2
    assert sample.messages[0].content == "Hi"
    assert sample.messages[-1].role == "assistant"

    # Output from last ModelEvent
    assert sample.output.choices[0].message.content == "4"


def test_reconstruct_empty_events() -> None:
    """Test reconstruction with no events at all."""
    summary = _make_in_progress_summary()

    sample_data = SampleData(events=[], attachments=[])

    sample = reconstruct_eval_sample(summary, sample_data, cancelled=True)

    assert sample.messages == []
    assert sample.output == ModelOutput()
    assert sample.events == []
    assert sample.timelines is None


def test_reconstruct_with_attachments() -> None:
    """Test that attachments from buffer DB are included."""
    summary = _make_completed_summary()

    user_msg = ChatMessageUser(content="What is 2+2?")
    model_event = _make_model_event([user_msg], "4")

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1)],
        attachments=[
            AttachmentData(
                id=1,
                sample_id="1",
                epoch=1,
                hash="abc123",
                content="base64imagedata",
            ),
        ],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert sample.attachments == {"abc123": "base64imagedata"}


def test_reconstruct_summary_can_be_generated() -> None:
    """Test that .summary() works on reconstructed samples."""
    summary = _make_completed_summary()

    user_msg = ChatMessageUser(content="What is 2+2?")
    model_event = _make_model_event([user_msg], "4")

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1)],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)
    new_summary = sample.summary()

    assert new_summary.id == 1
    assert new_summary.epoch == 1
    assert new_summary.scores is not None
    assert new_summary.message_count == 2
