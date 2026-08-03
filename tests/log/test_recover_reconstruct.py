"""Tests for reconstructing EvalSample from buffer DB data."""

import json
from datetime import datetime, timezone

from pydantic_core import to_jsonable_python

from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import (
    AttachmentData,
    CallPoolData,
    EventData,
    MessagePoolData,
    SampleData,
)
from inspect_ai.log._recover import reconstruct_eval_sample
from inspect_ai.log._recover._reconstruct import MessageAccumulator
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelFallback, ModelOutput
from inspect_ai.scorer._metric import Score


def _make_model_event(
    input_messages: list[ChatMessage],
    output_content: str,
    role: str | None = None,
) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        role=role,
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
        model_fallbacks=[
            ModelFallback(
                model="claude-fable-5", fallback_model="claude-opus-4-8", count=2
            )
        ],
        turn_count=3,
        token_limit=1000,
        token_limit_type="output",
        token_limit_usage=15,
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
    assert sample.model_fallbacks == summary.model_fallbacks
    assert sample.turn_count == 3
    assert sample.token_limit == 1000
    assert sample.token_limit_type == "output"
    assert sample.token_limit_usage == 15

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


def test_reconstruct_multi_agent_follows_first_role() -> None:
    """Reconstruction follows the first ModelEvent's role under concurrent agents.

    A solver running two agents in parallel (e.g. an auditor driving a
    target) interleaves both agents' ModelEvents, each carrying its own
    conversation. Recovery must return the first role's conversation
    deterministically, not whichever agent's event happened to fire last.
    """
    summary = _make_completed_summary()

    auditor_user = ChatMessageUser(content="Probe the target.")
    auditor_event1 = _make_model_event(
        [auditor_user], "Sending a question.", role="auditor"
    )

    target_user = ChatMessageUser(content="What is 2+2?")
    target_event1 = _make_model_event([target_user], "4", role="target")

    auditor_assistant = ChatMessageAssistant(content="Sending a question.")
    auditor_user2 = ChatMessageUser(content="The target answered 4.")
    auditor_event2 = _make_model_event(
        [auditor_user, auditor_assistant, auditor_user2],
        "Audit complete.",
        role="auditor",
    )

    target_assistant = ChatMessageAssistant(content="4")
    target_user2 = ChatMessageUser(content="Are you sure?")
    target_event2 = _make_model_event(
        [target_user, target_assistant, target_user2], "Yes, 4.", role="target"
    )

    # The target's event fires last
    sample_data = SampleData(
        events=[
            _event_to_event_data(auditor_event1, id=1),
            _event_to_event_data(target_event1, id=2),
            _event_to_event_data(auditor_event2, id=3),
            _event_to_event_data(target_event2, id=4),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert [m.text for m in sample.messages] == [
        "Probe the target.",
        "Sending a question.",
        "The target answered 4.",
        "Audit complete.",
    ]
    assert sample.output.choices[0].message.content == "Audit complete."


def test_reconstruct_multi_agent_primary_is_first_in_stream() -> None:
    """The primary role is whichever role's ModelEvent appears first."""
    summary = _make_completed_summary()

    target_user = ChatMessageUser(content="Hello")
    target_event = _make_model_event([target_user], "Hi there!", role="target")

    auditor_user = ChatMessageUser(content="The target said hi.")
    auditor_event = _make_model_event([auditor_user], "Noted.", role="auditor")

    sample_data = SampleData(
        events=[
            _event_to_event_data(target_event, id=1),
            _event_to_event_data(auditor_event, id=2),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert [m.text for m in sample.messages] == ["Hello", "Hi there!"]
    assert sample.output.choices[0].message.content == "Hi there!"


def test_reconstruct_multi_agent_compaction_survives_foreign_interleave() -> None:
    """A compaction attributed to the primary role survives a foreign event in between.

    Regression for a review comment on #4417: primary P1, then a foreign
    secondary event, then a compaction of the primary's own conversation,
    then primary P2. Since the secondary event is the most recent
    ModelEvent when the compaction fires, attributing the compaction by
    "most recent event's role" would skip flushing P1 and drop
    p1_input/p1_output. CompactionEvent.role removes the guesswork.
    """
    summary = _make_completed_summary()

    p1_user = ChatMessageUser(content="p1_input")
    p1_event = _make_model_event([p1_user], "p1_output", role="primary")

    s1_user = ChatMessageUser(content="s1_input")
    s1_event = _make_model_event([s1_user], "s1_output", role="secondary")

    compaction = CompactionEvent(type="summary", role="primary")

    summary_msg = ChatMessageUser(content="summary")
    p2_user = ChatMessageUser(content="p2_input")
    p2_event = _make_model_event([summary_msg, p2_user], "p2_output", role="primary")

    sample_data = SampleData(
        events=[
            _event_to_event_data(p1_event, id=1),
            _event_to_event_data(s1_event, id=2),
            _event_to_event_data(compaction, id=3),
            _event_to_event_data(p2_event, id=4),
        ],
        attachments=[],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert [m.text for m in sample.messages] == [
        "p1_input",
        "p1_output",
        "summary",
        "p2_input",
        "p2_output",
    ]
    assert sample.output.choices[0].message.content == "p2_output"


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
    # limit fields survive the summary -> sample -> summary round trip
    assert new_summary.turn_count == 3
    assert new_summary.token_limit == 1000
    assert new_summary.token_limit_type == "output"
    assert new_summary.token_limit_usage == 15


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


def test_message_accumulator_multi_role_chunked() -> None:
    """The primary role persists across chunked segment batches."""
    auditor_user = ChatMessageUser(content="Probe the target.")
    auditor_event1 = _make_model_event(
        [auditor_user], "Sending a question.", role="auditor"
    )
    target_event1 = _make_model_event(
        [ChatMessageUser(content="What is 2+2?")], "4", role="target"
    )
    auditor_assistant = ChatMessageAssistant(content="Sending a question.")
    auditor_user2 = ChatMessageUser(content="The target answered 4.")
    auditor_event2 = _make_model_event(
        [auditor_user, auditor_assistant, auditor_user2],
        "Audit complete.",
        role="auditor",
    )
    target_event2 = _make_model_event(
        [ChatMessageUser(content="Are you sure?")], "Yes, 4.", role="target"
    )

    acc = MessageAccumulator()
    acc.process_events([auditor_event1])
    acc.process_events([target_event1, auditor_event2])
    acc.process_events([target_event2])
    messages, output = acc.result()

    assert [m.text for m in messages] == [
        "Probe the target.",
        "Sending a question.",
        "The target answered 4.",
        "Audit complete.",
    ]
    assert output.choices[0].message.content == "Audit complete."


def test_message_accumulator_compaction_attributed_to_last_role() -> None:
    """A compaction following another role's event leaves the primary conversation alone.

    CompactionEvent carries no role, so it is attributed to the most recent
    ModelEvent's role. Here the summary compacted the target's conversation;
    flushing the auditor's history instead would duplicate its messages in
    the merged result.
    """
    auditor_user = ChatMessageUser(content="Probe the target.")
    auditor_event1 = _make_model_event(
        [auditor_user], "Sending a question.", role="auditor"
    )
    target_event = _make_model_event(
        [ChatMessageUser(content="Question")], "Answer", role="target"
    )
    compaction = CompactionEvent(type="summary")
    auditor_assistant = ChatMessageAssistant(content="Sending a question.")
    auditor_event2 = _make_model_event(
        [auditor_user, auditor_assistant], "Done.", role="auditor"
    )

    acc = MessageAccumulator()
    acc.process_events([auditor_event1, target_event, compaction, auditor_event2])
    messages, output = acc.result()

    assert [m.text for m in messages] == [
        "Probe the target.",
        "Sending a question.",
        "Done.",
    ]
    assert output.choices[0].message.content == "Done."


def test_message_accumulator_compaction_role_survives_foreign_interleave() -> None:
    """CompactionEvent.role is used when present instead of the last-event heuristic.

    Same regression as test_reconstruct_multi_agent_compaction_survives_foreign_interleave,
    exercised directly against MessageAccumulator: a foreign event between the
    primary's last event and its own compaction must not cause that
    compaction to be skipped.
    """
    p1_event = _make_model_event(
        [ChatMessageUser(content="p1_input")], "p1_output", role="primary"
    )
    s1_event = _make_model_event(
        [ChatMessageUser(content="s1_input")], "s1_output", role="secondary"
    )
    compaction = CompactionEvent(type="summary", role="primary")
    p2_event = _make_model_event(
        [ChatMessageUser(content="summary"), ChatMessageUser(content="p2_input")],
        "p2_output",
        role="primary",
    )

    acc = MessageAccumulator()
    acc.process_events([p1_event, s1_event, compaction, p2_event])
    messages, output = acc.result()

    assert [m.text for m in messages] == [
        "p1_input",
        "p1_output",
        "summary",
        "p2_input",
        "p2_output",
    ]
    assert output.choices[0].message.content == "p2_output"


def test_reconstruct_in_progress_summary_without_uuid_synthesizes_one() -> None:
    """Legacy in-flight buffer rows lack a uuid; recovery synthesizes one."""
    summary = EvalSampleSummary(id="some-sample", epoch=1, input="2+2?", target="4")
    assert summary.uuid is None

    sample = reconstruct_eval_sample(
        summary, SampleData(events=[], attachments=[]), cancelled=True
    )

    assert sample.uuid is not None


def test_reconstruct_resolves_message_pool_refs() -> None:
    """Regression: reconstruct must rehydrate ModelEvent.input from message_pool."""
    summary = _make_completed_summary()
    user_msg = ChatMessageUser(content="What is 2+2?")
    assert user_msg.id is not None

    model_event = ModelEvent(
        model="mockllm/model",
        input=[],
        input_refs=[(0, 1)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(
            model="mockllm/model", content="The answer is 4."
        ),
    )

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1)],
        attachments=[],
        message_pool=[
            MessagePoolData(
                id=1,
                sample_id="1",
                epoch=1,
                msg_id=user_msg.id,
                data=json.dumps(to_jsonable_python(user_msg, exclude_none=True)),
            )
        ],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert isinstance(sample.events[0], ModelEvent)
    assert len(sample.events[0].input) == 1, (
        f"expected resolved input from message_pool, got {sample.events[0].input!r}"
    )
    assert sample.events[0].input[0].text == "What is 2+2?"

    assert len(sample.messages) == 2
    assert sample.messages[0].role == "user"
    assert sample.messages[0].text == "What is 2+2?"
    assert sample.messages[1].role == "assistant"


def test_reconstruct_resolves_call_pool_refs() -> None:
    """Regression: reconstruct must rehydrate ModelCall.request from call_pool."""
    summary = _make_completed_summary()
    pooled_message = {"role": "user", "content": "What is 2+2?"}

    model_event = ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="What is 2+2?")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(
            model="mockllm/model", content="The answer is 4."
        ),
        call=ModelCall(
            request={"model": "mockllm/model", "messages": []},
            response={},
            call_refs=[(0, 1)],
            call_key="messages",
        ),
    )

    sample_data = SampleData(
        events=[_event_to_event_data(model_event, id=1)],
        attachments=[],
        call_pool=[
            CallPoolData(
                id=1,
                sample_id="1",
                epoch=1,
                hash="dummy-hash",
                data=json.dumps(pooled_message),
            )
        ],
    )

    sample = reconstruct_eval_sample(summary, sample_data)

    assert isinstance(sample.events[0], ModelEvent)
    call = sample.events[0].call
    assert call is not None
    assert call.call_refs is None
    assert call.request["messages"] == [pooled_message]
