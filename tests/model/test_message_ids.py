"""Tests for stable_message_ids and message ID stability."""

import pytest
from test_helpers.message_ids import assert_message_ids, edited_id, shown

from inspect_ai import Task, eval
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    UrlCitation,
    get_model,
)
from inspect_ai.model._message_ids import (
    canonical_tool_arguments,
    edited_message,
    stable_message_ids,
)
from inspect_ai.model._model import resolve_reasoning_history, resolve_tool_model_input
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolCall, ToolDef, tool
from inspect_ai.tool._tool_call import ToolCallModelInputHints


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


def test_reasoning_history_stripping_derives_ids() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question"),
        ChatMessageAssistant(
            content=[ContentReasoning(reasoning="hmm"), ContentText(text="Answer")]
        ),
    ]
    resolved = resolve_reasoning_history(
        messages,
        GenerateConfig(reasoning_history="none"),
        get_model("mockllm/model").api,
    )

    again = resolve_reasoning_history(
        messages,
        GenerateConfig(reasoning_history="none"),
        get_model("mockllm/model").api,
    )

    assert resolved[1].content == [ContentText(text="Answer")]
    assert resolved[0] is messages[0]
    assert resolved[1].id == edited_id(messages[1].id, resolved[1])
    assert [m.id for m in again] == [m.id for m in resolved]


def test_reasoning_summary_edit_gets_a_new_id() -> None:
    """A changed summary is a changed message, even with the same reasoning payload."""
    reply = ChatMessageAssistant(
        id="reply",
        content=[
            ContentReasoning(reasoning="signature", summary="First.", redacted=True),
            ContentText(text="Answer"),
        ],
    )

    edited = edited_message(
        reply,
        content=[
            ContentReasoning(reasoning="signature", summary="Second.", redacted=True),
            ContentText(text="Answer"),
        ],
    )

    assert edited.id != reply.id
    assert shown(edited) != shown(reply)


def test_tool_arguments_compare_by_json_numbers() -> None:
    """5.0 and 5 are one JSON number, but a bool is not a number."""
    assert canonical_tool_arguments({"n": [5.0, {"m": -0.0}]}) == (
        canonical_tool_arguments({"n": [5, {"m": 0}]})
    )
    assert canonical_tool_arguments({"n": 5.5}) != canonical_tool_arguments({"n": 5})
    assert canonical_tool_arguments({"n": True}) != canonical_tool_arguments({"n": 1})
    assert canonical_tool_arguments({"n": 1.0}) != canonical_tool_arguments({"n": True})

    def reply(arguments: dict[str, object]) -> ChatMessageAssistant:
        call = ToolCall(id="c1", function="read", arguments=arguments)
        return ChatMessageAssistant(id="reply", content="", tool_calls=[call])

    assert (
        edited_message(reply({"n": 5.0}), tool_calls=reply({"n": 5}).tool_calls).id
        == "reply"
    )


def test_tool_model_input_derives_ids() -> None:
    async def lookup(query: str) -> str:
        """Look up a query.

        Args:
          query: The query.
        """
        return query

    tdef = ToolDef(lookup, model_input=lambda index, total, content, hints: "(removed)")
    messages: list[ChatMessage] = [
        ChatMessageTool(content="result", tool_call_id="c1", function="lookup")
    ]
    resolved = resolve_tool_model_input(
        [tdef], messages, {"disable_computer_screenshot_truncation": False}
    )

    again = resolve_tool_model_input(
        [tdef], messages, {"disable_computer_screenshot_truncation": False}
    )

    assert resolved[0].content == "(removed)"
    assert resolved[0].id == edited_id(messages[0].id, resolved[0])
    assert again[0].id == resolved[0].id
    assert messages[0].content == "result"


def _redact_older_in_place(
    index: int, total: int, content: str | list[Content], hints: ToolCallModelInputHints
) -> str | list[Content]:
    """Redact all but the latest result by editing its items, in a new list."""
    if isinstance(content, str) or index == total - 1:
        return content
    redacted = list(content)
    for item in redacted:
        if isinstance(item, ContentText):
            item.text = "(removed)"
    return redacted


def test_tool_model_input_editing_content_in_place_derives_ids() -> None:
    async def lookup(query: str) -> str:
        """Look up a query.

        Args:
          query: The query.
        """
        return query

    tdef = ToolDef(lookup, model_input=_redact_older_in_place)
    hints: ToolCallModelInputHints = {"disable_computer_screenshot_truncation": False}
    first = ChatMessageTool(
        content=[ContentText(text="full result")], tool_call_id="c1", function="lookup"
    )
    second = ChatMessageTool(
        content=[ContentText(text="next")], tool_call_id="c2", function="lookup"
    )

    latest = resolve_tool_model_input([tdef], [first], hints)
    older = resolve_tool_model_input([tdef], [first, second], hints)
    again = resolve_tool_model_input([tdef], [first, second], hints)

    assert latest[0].id == first.id
    assert latest[0].text == "full result"
    assert older[0].text == "(removed)"
    assert older[0].id == edited_id(first.id, older[0])
    assert again[0].id == older[0].id
    assert first.text == "full result"


_SCREENSHOT = "data:image/png;base64," + "A" * 100_000


def _screenshot_results(count: int) -> list[ChatMessage]:
    return [
        ChatMessageTool(
            content=[ContentText(text=f"step {n}"), ContentImage(image=_SCREENSHOT)],
            tool_call_id=f"c{n}",
            function="computer",
        )
        for n in range(count)
    ]


def _prepared_hash_bytes(messages: list[ChatMessage]) -> int:
    """Bytes `content_hash` hashes preparing `messages` for a model without tool result images."""
    from unittest.mock import patch

    from inspect_ai._util.hash import mm3_hash
    from inspect_ai.model import _message_ids
    from inspect_ai.model._model import tool_result_media_as_user_message
    from inspect_ai.tool._tools._computer._computer import _computer_model_input

    async def computer(action: str) -> str:
        """Use the computer.

        Args:
          action: The action.
        """
        return action

    tdef = ToolDef(computer, model_input=_computer_model_input(max_screenshots=1))
    hashed = 0

    def counting_hash(value: str) -> str:
        nonlocal hashed
        hashed += len(value)
        return mm3_hash(value)

    with patch.object(_message_ids, "mm3_hash", counting_hash):
        resolved = resolve_tool_model_input(
            [tdef], messages, {"disable_computer_screenshot_truncation": False}
        )
        tool_result_media_as_user_message(resolved, (ContentImage,))
    return hashed


def test_tool_model_input_does_not_hash_removed_screenshots() -> None:
    """Preparing a call hashes the screenshots kept for the model, not every one in the history.

    Each call runs the model input handler over every result, so hashing each
    source to tell whether the handler changed it made a run's preparation
    quadratic in its screenshots.
    """
    few = _prepared_hash_bytes(_screenshot_results(4))
    many = _prepared_hash_bytes(_screenshot_results(64))

    assert many - few < len(_SCREENSHOT)


class _Label(str):
    pass


@pytest.mark.parametrize(
    "a,b",
    [
        ("x", "x"),
        ("x", "y"),
        (1, 1.0),
        (True, 1),
        (0.0, -0.0),
        (float("nan"), float("nan")),
        (None, "null"),
        ([1, "x"], (1, "x")),
        ([1], [1, 1]),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
        ({"1": "x"}, {1: "x"}),
        ({"a": [1.5]}, {"a": [1.5]}),
        (_Label("x"), "x"),
        (["x"], ["x", None]),
    ],
)
def test_same_content_agrees_with_content_hash(a: object, b: object) -> None:
    import json

    from inspect_ai.model._message_ids import _dumps_equal

    assert _dumps_equal(a, b) == (
        json.dumps(a, default=str) == json.dumps(b, default=str)
    )


def test_tool_model_input_editing_an_image_in_place_derives_an_id() -> None:
    async def computer(action: str) -> str:
        """Use the computer.

        Args:
          action: The action.
        """
        return action

    def downscale(
        index: int,
        total: int,
        content: str | list[Content],
        hints: ToolCallModelInputHints,
    ) -> str | list[Content]:
        assert isinstance(content, list)
        for item in content:
            if isinstance(item, ContentImage):
                item.image = "data:image/png;base64,c21hbGw="
        return content

    tdef = ToolDef(computer, model_input=downscale)
    message = _screenshot_results(1)[0]

    resolved = resolve_tool_model_input(
        [tdef], [message], {"disable_computer_screenshot_truncation": False}
    )

    assert resolved[0].id == edited_id(message.id, resolved[0])
    assert resolved[0].id != message.id
    assert isinstance(message.content, list)
    assert message.content[1] == ContentImage(image=_SCREENSHOT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("citations", [UrlCitation(url="https://example.com", cited_text="result")]),
        ("internal", {"provider": "payload"}),
        ("cache_breakpoint", True),
    ],
)
def test_tool_model_input_metadata_edit_is_applied_under_the_same_id(
    field: str, value: object
) -> None:
    async def lookup(query: str) -> str:
        """Look up a query.

        Args:
          query: The query.
        """
        return query

    def strip(
        index: int,
        total: int,
        content: str | list[Content],
        hints: ToolCallModelInputHints,
    ) -> str | list[Content]:
        assert isinstance(content, list)
        return [item.model_copy(update={field: None}) for item in content]

    tdef = ToolDef(lookup, model_input=strip)
    message = ChatMessageTool(
        content=[ContentText(text="result").model_copy(update={field: value})],
        tool_call_id="c1",
        function="lookup",
    )

    resolved = resolve_tool_model_input(
        [tdef], [message], {"disable_computer_screenshot_truncation": False}
    )

    assert isinstance(resolved[0].content, list)
    assert getattr(resolved[0].content[0], field) is None
    assert resolved[0].id == message.id
    assert isinstance(message.content, list)
    assert getattr(message.content[0], field) == value


@tool(model_input=_redact_older_in_place)
def lookup() -> Tool:
    async def execute(query: str) -> str:
        """Look up a query.

        Args:
          query: The query.
        """
        return query

    return execute


@solver
def _lookups(results: list[str]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.tools = [lookup()]
        for n, result in enumerate(results):
            call = ToolCall(id=f"c{n}", function="lookup", arguments={"query": "q"})
            state.messages.append(ChatMessageAssistant(content="", tool_calls=[call]))
            state.messages.append(
                ChatMessageTool(
                    content=[ContentText(text=result)],
                    tool_call_id=call.id,
                    function="lookup",
                )
            )
            state = await generate(state, tool_calls="none")
        return state

    return solve


def test_tool_model_input_editing_content_in_place_logs_one_content_per_id() -> None:
    log = eval(
        Task(
            dataset=[Sample(input="look it up")],
            solver=_lookups(["full result", "next", "last"]),
        ),
        model="mockllm/model",
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert_message_ids(sample)
    assert sample.messages[2].text == "full result"
