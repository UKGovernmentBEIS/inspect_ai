"""Tests for reconstructing EvalSample from buffer DB data."""

from datetime import datetime, timezone

from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import AttachmentData, EventData, SampleData
from inspect_ai.log._recover import reconstruct_eval_sample
from inspect_ai.log._recover._reconstruct import MessageAccumulator
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
    event: ModelEvent | StepEvent | CompactionEvent,
    id: int,
    sample_id: str = "1",
    epoch: int = 1,
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


def test_reconstruct_with_summary_compaction() -> None:
    """Test message extraction across a summary compaction boundary.

    Summary compaction grafts pre-compaction messages onto the merged list,
    then continues with post-compaction messages.
    """
    summary = _make_completed_summary()

    # Pre-compaction: two turns
    user1 = ChatMessageUser(content="Hello")
    event1 = _make_model_event([user1], "Hi there!")

    assistant1 = ChatMessageAssistant(content="Hi there!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user1, assistant1, user2], "4")

    # CompactionEvent (summary) — conversation was summarized
    compaction = CompactionEvent(type="summary")

    # Post-compaction: model sees summarized history + new message
    summary_msg = ChatMessageUser(content="[Summary of prior conversation]")
    user3 = ChatMessageUser(content="And what is 3+3?")
    event3 = _make_model_event([summary_msg, user3], "6")

    sample_data = SampleData(
        events=[
            _event_to_event_data(event1, id=1),
            _event_to_event_data(event2, id=2),
            _event_to_event_data(compaction, id=3),
            _event_to_event_data(event3, id=4),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    # Pre-compaction segment: _segment_messages(event2) = [user1, assistant1, user2, "4"]
    # Post-compaction segment: _segment_messages(event3) = [summary_msg, user3, "6"]
    # Total: 7 messages
    assert len(sample.messages) == 7
    assert sample.messages[0].text == "Hello"  # user1
    assert sample.messages[1].text == "Hi there!"  # assistant1
    assert sample.messages[2].text == "What is 2+2?"  # user2
    assert sample.messages[3].text == "4"  # assistant from event2
    assert sample.messages[4].text == "[Summary of prior conversation]"  # summary_msg
    assert sample.messages[5].text == "And what is 3+3?"  # user3
    assert sample.messages[6].text == "6"  # assistant from event3
    assert sample.output.choices[0].message.content == "6"


def test_reconstruct_with_trim_compaction() -> None:
    """Test message extraction across a trim compaction boundary.

    Trim compaction drops early messages. The trimmed prefix should be
    recovered from the pre-compaction ModelEvent.
    """
    summary = _make_completed_summary()

    # Pre-compaction: long conversation
    user1 = ChatMessageUser(content="First message", id="msg1")
    assistant1 = ChatMessageAssistant(content="First reply", id="msg2")
    user2 = ChatMessageUser(content="Second message", id="msg3")
    event1 = _make_model_event([user1, assistant1, user2], "Second reply")

    # Trim compaction — drops first two messages
    compaction = CompactionEvent(type="trim")

    # Post-compaction: only the later messages remain
    event2 = _make_model_event([user2], "Second reply again")

    sample_data = SampleData(
        events=[
            _event_to_event_data(event1, id=1),
            _event_to_event_data(compaction, id=2),
            _event_to_event_data(event2, id=3),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    # Trimmed prefix: [user1, assistant1] (before overlap point at user2)
    # Post-compaction segment: _segment_messages(event2) = [user2, "Second reply again"]
    # Total: 4 messages
    assert len(sample.messages) == 4
    assert sample.messages[0].text == "First message"  # user1 (trimmed prefix)
    assert sample.messages[1].text == "First reply"  # assistant1 (trimmed prefix)
    assert sample.messages[2].text == "Second message"  # user2
    assert sample.messages[3].text == "Second reply again"  # assistant from event2


def test_reconstruct_with_edit_compaction() -> None:
    """Test that edit compaction is transparent (no effect on message merging)."""
    summary = _make_completed_summary()

    user1 = ChatMessageUser(content="Hello")
    event1 = _make_model_event([user1], "Hi!")

    # Edit compaction — transparent, should not break message accumulation
    compaction = CompactionEvent(type="edit")

    assistant1 = ChatMessageAssistant(content="Hi!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user1, assistant1, user2], "4")

    sample_data = SampleData(
        events=[
            _event_to_event_data(event1, id=1),
            _event_to_event_data(compaction, id=2),
            _event_to_event_data(event2, id=3),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    # Edit is transparent — messages should be from the last ModelEvent
    assert len(sample.messages) == 4  # user1, assistant1, user2, assistant2
    assert sample.messages[0].text == "Hello"
    assert sample.messages[-1].text == "4"


def test_reconstruct_multi_epoch() -> None:
    """Test reconstruction of a sample with epoch > 1."""
    summary = EvalSampleSummary(
        id=1,
        epoch=3,
        input="What is 2+2?",
        target="4",
        scores={"accuracy": Score(value="C", answer="4")},
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    user_msg = ChatMessageUser(content="What is 2+2?")
    model_event = _make_model_event([user_msg], "4")

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1, epoch=3)],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert sample.id == 1
    assert sample.epoch == 3
    assert sample.scores is not None


def test_message_accumulator_single_batch() -> None:
    """MessageAccumulator produces same result as _extract_messages_from_events."""
    user_msg = ChatMessageUser(content="Hello")
    event1 = _make_model_event([user_msg], "Hi!")
    assistant1 = ChatMessageAssistant(content="Hi!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user_msg, assistant1, user2], "4")

    events: list[Event] = [event1, event2]

    acc = MessageAccumulator()
    acc.process_events(events)
    messages, output = acc.result()

    assert len(messages) == 4
    assert messages[0].text == "Hello"
    assert messages[-1].text == "4"
    assert output.choices[0].message.content == "4"


def test_message_accumulator_chunked() -> None:
    """Chunked feeding produces same result as single batch."""
    user_msg = ChatMessageUser(content="Hello")
    event1 = _make_model_event([user_msg], "Hi!")
    assistant1 = ChatMessageAssistant(content="Hi!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user_msg, assistant1, user2], "4")

    acc = MessageAccumulator()
    acc.process_events([event1])
    acc.process_events([event2])
    messages, output = acc.result()

    assert len(messages) == 4
    assert messages[0].text == "Hello"
    assert messages[-1].text == "4"
    assert output.choices[0].message.content == "4"


def test_message_accumulator_bounded_state_across_many_events() -> None:
    """Accumulator state must not grow with the number of ModelEvents.

    Regression test for a prior bug where every ModelEvent was retained
    in an internal list (even though only the most recent one was ever
    read), causing O(N) memory growth on samples with no compaction
    events. The fix was to keep only the last ModelEvent.
    """
    user_msg = ChatMessageUser(content="q")

    acc = MessageAccumulator()
    for i in range(1000):
        acc.process_events([_make_model_event([user_msg], f"r{i}")])

    messages, output = acc.result()
    assert output.choices[0].message.content == "r999"
    assert len(messages) == 2


def test_message_accumulator_compaction_across_chunks() -> None:
    """Compaction boundary split across chunks works correctly."""
    user1 = ChatMessageUser(content="Hello")
    event1 = _make_model_event([user1], "Hi there!")
    assistant1 = ChatMessageAssistant(content="Hi there!")
    user2 = ChatMessageUser(content="What is 2+2?")
    event2 = _make_model_event([user1, assistant1, user2], "4")
    compaction = CompactionEvent(type="summary")
    summary_msg = ChatMessageUser(content="[Summary]")
    user3 = ChatMessageUser(content="And 3+3?")
    event3 = _make_model_event([summary_msg, user3], "6")

    acc = MessageAccumulator()
    acc.process_events([event1, event2])
    acc.process_events([compaction, event3])
    messages, output = acc.result()

    assert len(messages) == 7
    assert messages[0].text == "Hello"
    assert messages[4].text == "[Summary]"
    assert messages[6].text == "6"
    assert output.choices[0].message.content == "6"
