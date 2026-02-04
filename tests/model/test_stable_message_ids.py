import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._message_ids import stable_message_ids
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput


def make_model_event(
    input_messages: list, output: ModelOutput, model: str = "test-model"
) -> ModelEvent:
    """Helper to create a ModelEvent with required fields."""
    return ModelEvent(
        model=model,
        input=input_messages,
        output=output,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )


@pytest.fixture
def user_message():
    return ChatMessageUser(content="Hello, world!")


@pytest.fixture
def system_message():
    return ChatMessageSystem(content="You are a helpful assistant.")


@pytest.fixture
def assistant_message():
    return ChatMessageAssistant(content="Hello! How can I help you?")


def test_stable_ids_same_content_same_id():
    """Messages with identical content should get the same ID across calls."""
    apply_ids = stable_message_ids()

    # First call
    msg1 = ChatMessageUser(content="Hello")
    apply_ids([msg1])
    id1 = msg1.id

    # Second call with identical content
    msg2 = ChatMessageUser(content="Hello")
    apply_ids([msg2])
    id2 = msg2.id

    assert id1 == id2


def test_stable_ids_different_content_different_id():
    """Messages with different content should get different IDs."""
    apply_ids = stable_message_ids()

    msg1 = ChatMessageUser(content="Hello")
    msg2 = ChatMessageUser(content="Goodbye")
    apply_ids([msg1, msg2])

    assert msg1.id != msg2.id


def test_stable_ids_duplicates_in_same_conversation():
    """Duplicate messages within the same conversation get unique IDs."""
    apply_ids = stable_message_ids()

    # Two messages with same content in one call
    msg1 = ChatMessageUser(content="Hello")
    msg2 = ChatMessageUser(content="Hello")
    apply_ids([msg1, msg2])

    # They should have different IDs within the same conversation
    assert msg1.id != msg2.id


def test_stable_ids_reuse_across_conversations():
    """IDs should be reused across conversations when not conflicting."""
    apply_ids = stable_message_ids()

    # First conversation
    msg1 = ChatMessageUser(content="Hello")
    apply_ids([msg1])
    id1 = msg1.id

    # Second conversation - same content, should reuse ID
    msg2 = ChatMessageUser(content="Hello")
    apply_ids([msg2])
    id2 = msg2.id

    assert id1 == id2


def test_stable_ids_different_roles_same_content():
    """Messages with same content but different roles get different IDs."""
    apply_ids = stable_message_ids()

    user_msg = ChatMessageUser(content="Hello")
    assistant_msg = ChatMessageAssistant(content="Hello")
    apply_ids([user_msg, assistant_msg])

    # Different roles means different hash
    assert user_msg.id != assistant_msg.id


def test_stable_ids_preserves_message_order():
    """Applying IDs should not change message order or content."""
    apply_ids = stable_message_ids()

    messages = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="User question"),
        ChatMessageAssistant(content="Assistant response"),
    ]

    original_contents = [m.content for m in messages]
    apply_ids(messages)

    # Content should be unchanged
    assert [m.content for m in messages] == original_contents
    # All messages should have IDs
    assert all(m.id is not None for m in messages)


def test_stable_ids_with_model_event():
    """stable_message_ids should work with ModelEvent."""
    apply_ids = stable_message_ids()

    input_messages = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="User question"),
    ]

    output = ModelOutput(
        model="test-model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="Response"),
                stop_reason="stop",
            )
        ],
    )

    event = make_model_event(input_messages, output)

    apply_ids(event)

    # Input messages should have IDs
    assert all(m.id is not None for m in event.input)
    # Output message should have ID
    assert event.output.message.id is not None


def test_stable_ids_model_event_output_distinct_from_input():
    """Output message ID should be distinct from input message IDs."""
    apply_ids = stable_message_ids()

    input_messages = [
        ChatMessageUser(content="Question"),
    ]

    output = ModelOutput(
        model="test-model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="Answer"),
                stop_reason="stop",
            )
        ],
    )

    event = make_model_event(input_messages, output)

    apply_ids(event)

    input_ids = {m.id for m in event.input}
    output_id = event.output.message.id

    # Output ID should not be in input IDs
    assert output_id not in input_ids


def test_stable_ids_consistent_across_multiple_events():
    """Same messages appearing in multiple events should get same IDs."""
    apply_ids = stable_message_ids()

    # First event
    input1 = [ChatMessageUser(content="Question 1")]
    output1 = ModelOutput(
        model="test-model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="Answer 1"),
                stop_reason="stop",
            )
        ],
    )
    event1 = make_model_event(input1, output1)
    apply_ids(event1)

    # Second event includes first question+answer plus new question
    input2 = [
        ChatMessageUser(content="Question 1"),
        ChatMessageAssistant(content="Answer 1"),
        ChatMessageUser(content="Question 2"),
    ]
    output2 = ModelOutput(
        model="test-model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="Answer 2"),
                stop_reason="stop",
            )
        ],
    )
    event2 = make_model_event(input2, output2)
    apply_ids(event2)

    # First question should have same ID in both events
    assert input1[0].id == input2[0].id
    # First answer should have same ID
    assert output1.message.id == input2[1].id


def test_stable_ids_empty_messages() -> None:
    """Applying IDs to empty list should not raise."""
    apply_ids = stable_message_ids()
    messages: list[ChatMessageUser] = []
    apply_ids(messages)  # Should not raise


def test_stable_ids_independent_instances():
    """Different stable_message_ids instances should be independent."""
    apply_ids1 = stable_message_ids()
    apply_ids2 = stable_message_ids()

    msg1 = ChatMessageUser(content="Hello")
    msg2 = ChatMessageUser(content="Hello")

    apply_ids1([msg1])
    apply_ids2([msg2])

    # Different instances generate different IDs
    assert msg1.id != msg2.id
