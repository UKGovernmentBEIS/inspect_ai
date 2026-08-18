"""Tests for stable_message_ids and message ID stability."""

from inspect_ai.event._model import ModelEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.model._message_ids import stable_message_ids


class TestStableMessageIds:
    """Tests for stable_message_ids factory function."""

    def test_same_content_same_id(self) -> None:
        """Messages with identical content get the same ID."""
        apply_ids = stable_message_ids()
        msg1 = ChatMessageUser(content="Hello")
        msg2 = ChatMessageUser(content="Hello")  # Same content

        apply_ids([msg1])
        apply_ids([msg2])

        assert msg1.id == msg2.id

    def test_different_content_different_id(self) -> None:
        """Messages with different content get different IDs."""
        apply_ids = stable_message_ids()
        msg1 = ChatMessageUser(content="Hello")
        msg2 = ChatMessageUser(content="Goodbye")

        apply_ids([msg1])
        apply_ids([msg2])

        assert msg1.id != msg2.id

    def test_duplicate_in_conversation_gets_new_id(self) -> None:
        """Same content appearing twice in same conversation gets different IDs."""
        apply_ids = stable_message_ids()
        messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello"),
            ChatMessageUser(content="Hello"),  # Same content
        ]

        apply_ids(messages)

        # Should be different since both are in the same conversation
        assert messages[0].id != messages[1].id

    def test_reuse_across_conversations(self) -> None:
        """Same content in different conversations can reuse IDs."""
        apply_ids = stable_message_ids()
        msg1 = ChatMessageUser(content="Hello")
        msg2 = ChatMessageUser(content="Hello")  # Same content

        # First conversation
        apply_ids([msg1])

        # Different conversation (separate call)
        apply_ids([msg2])

        # Should reuse the same ID
        assert msg1.id == msg2.id

    def test_apply_ids_basic(self) -> None:
        """apply_ids assigns IDs to all messages."""
        apply_ids = stable_message_ids()
        messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello"),
            ChatMessageAssistant(content="Hi there!"),
            ChatMessageUser(content="How are you?"),
        ]

        apply_ids(messages)

        # All messages should have IDs
        for msg in messages:
            assert msg.id is not None
            assert len(msg.id) > 0

        # All IDs should be unique within this conversation
        ids = [msg.id for msg in messages]
        assert len(ids) == len(set(ids))

    def test_apply_ids_duplicate_content(self) -> None:
        """apply_ids handles duplicate content correctly."""
        apply_ids = stable_message_ids()
        messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello"),
            ChatMessageAssistant(content="Hi!"),
            ChatMessageUser(content="Hello"),  # Same as first
        ]

        apply_ids(messages)

        # First and third messages have same content but should have different IDs
        # because they're in the same conversation
        assert messages[0].id != messages[2].id

    def test_cross_event_stability(self) -> None:
        """Same message appearing in multiple events gets same ID."""
        apply_ids = stable_message_ids()

        # First event: just user message
        event1_messages: list[ChatMessage] = [ChatMessageUser(content="Hello")]
        apply_ids(event1_messages)
        user_id_event1 = event1_messages[0].id

        # Second event: user message + assistant response + user followup
        event2_messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello"),  # Same as before
            ChatMessageAssistant(content="Hi there!"),
            ChatMessageUser(content="How are you?"),
        ]
        apply_ids(event2_messages)
        user_id_event2 = event2_messages[0].id

        # The "Hello" message should have the same ID across events
        assert user_id_event1 == user_id_event2

    def test_different_roles_different_ids(self) -> None:
        """Same text but different roles gets different IDs."""
        apply_ids = stable_message_ids()
        user_msg = ChatMessageUser(content="Hello")
        assistant_msg = ChatMessageAssistant(content="Hello")

        apply_ids([user_msg])
        apply_ids([assistant_msg])

        assert user_msg.id != assistant_msg.id


class TestStableMessageIdsWithModelEvent:
    """Tests for stable_message_ids with ModelEvent."""

    def test_applies_ids_to_input(self) -> None:
        """IDs are applied to input messages."""
        apply_ids = stable_message_ids()
        event = ModelEvent(
            model="test-model",
            input=[
                ChatMessageUser(content="Hello"),
                ChatMessageAssistant(content="Hi!"),
            ],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(
                ChatMessageAssistant(content="Response"),
            ),
        )

        apply_ids(event)

        # Input messages should have IDs
        for msg in event.input:
            assert msg.id is not None

    def test_applies_id_to_output(self) -> None:
        """ID is applied to output message."""
        apply_ids = stable_message_ids()
        event = ModelEvent(
            model="test-model",
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(
                ChatMessageAssistant(content="Response"),
            ),
        )

        apply_ids(event)

        # Output message should have an ID
        assert event.output is not None
        assert isinstance(event.output, ModelOutput)
        assert event.output.message is not None
        assert event.output.message.id is not None

    def test_output_id_distinct_from_input(self) -> None:
        """Output message ID is distinct from input message IDs."""
        apply_ids = stable_message_ids()
        event = ModelEvent(
            model="test-model",
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(
                ChatMessageAssistant(content="Hi there!"),
            ),
        )

        apply_ids(event)

        input_ids = {msg.id for msg in event.input}
        assert event.output is not None
        assert isinstance(event.output, ModelOutput)
        assert event.output.message is not None
        output_id = event.output.message.id

        assert output_id not in input_ids

    def test_multi_event_stability(self) -> None:
        """Messages appearing in multiple events maintain stable IDs."""
        apply_ids = stable_message_ids()

        # First event
        event1 = ModelEvent(
            model="test-model",
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(
                ChatMessageAssistant(content="Hi!"),
            ),
        )
        apply_ids(event1)

        # Store IDs from first event
        user_id_1 = list(event1.input)[0].id
        assert event1.output is not None
        assert isinstance(event1.output, ModelOutput)
        assert event1.output.message is not None
        assistant_id_1 = event1.output.message.id

        # Second event includes messages from first event
        event2 = ModelEvent(
            model="test-model",
            input=[
                ChatMessageUser(content="Hello"),  # Same as event1
                ChatMessageAssistant(content="Hi!"),  # Same as event1 output
                ChatMessageUser(content="How are you?"),  # New message
            ],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(
                ChatMessageAssistant(content="I'm good!"),
            ),
        )
        apply_ids(event2)

        # Same content should have same IDs
        input_list = list(event2.input)
        assert input_list[0].id == user_id_1  # "Hello" user message
        assert input_list[1].id == assistant_id_1  # "Hi!" assistant message

        # New message should have new ID
        assert input_list[2].id is not None
        assert input_list[2].id not in {user_id_1, assistant_id_1}

    def test_handles_output_without_choices(self) -> None:
        """Handles events with output but no choices gracefully."""
        apply_ids = stable_message_ids()
        event = ModelEvent(
            model="test-model",
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(model="test-model", choices=[]),
        )

        # Should not raise
        apply_ids(event)

        # Input should still have IDs
        assert list(event.input)[0].id is not None
