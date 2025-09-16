"""Tests for runtime type validation in the scanner module."""

import pytest

from inspect_ai.log._transcript import Event, ModelEvent, ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._scanner import Scanner, scanner
from inspect_ai.scanner._transcript import Transcript

# Valid scanner tests


def test_base_type_with_filter():
    """Base ChatMessage type should work with any message filter."""

    @scanner(messages=["system", "user"])
    def test_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    # Should not raise
    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")
    assert scanner_instance.__scanner__.content.messages == ["system", "user"]


def test_exact_union_match():
    """Union type matching filter should work."""

    @scanner(messages=["system", "user"])
    def test_scanner() -> Scanner[ChatMessageSystem | ChatMessageUser]:
        async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_single_type_single_filter():
    """Single type with matching single filter should work."""

    @scanner(messages=["assistant"])
    def test_scanner() -> Scanner[ChatMessageAssistant]:
        async def scan(message: ChatMessageAssistant) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_list_of_base_type():
    """List of base type should work."""

    @scanner(messages=["system", "user"])
    def test_scanner() -> Scanner[list[ChatMessage]]:
        async def scan(messages: list[ChatMessage]) -> Result | None:
            return Result(value={"count": len(messages)})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_list_of_specific_type():
    """List of specific type with matching filter should work."""

    @scanner(messages=["assistant"])
    def test_scanner() -> Scanner[list[ChatMessageAssistant]]:
        async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
            return Result(value={"count": len(messages)})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_list_of_union_type():
    """List of union types should work."""

    @scanner(messages=["system", "user"])
    def test_scanner() -> Scanner[list[ChatMessageSystem | ChatMessageUser]]:
        async def scan(
            messages: list[ChatMessageSystem | ChatMessageUser],
        ) -> Result | None:
            return Result(value={"count": len(messages)})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_messages_all_with_base_type():
    """messages='all' should work with ChatMessage."""

    @scanner(messages="all")
    def test_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert scanner_instance.__scanner__.content.messages == "all"


def test_events_all_with_base_type():
    """events='all' should work with Event."""

    @scanner(events="all")
    def test_scanner() -> Scanner[Event]:
        async def scan(event: Event) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert scanner_instance.__scanner__.content.events == "all"


def test_event_union_types():
    """Event union types should work."""

    @scanner(events=["model", "tool"])
    def test_scanner() -> Scanner[ModelEvent | ToolEvent]:
        async def scan(event: ModelEvent | ToolEvent) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_transcript_with_both_filters():
    """Both message and event filters should require Transcript."""

    @scanner(messages=["user"], events=["model"])
    def test_scanner() -> Scanner[Transcript]:
        async def scan(transcript: Transcript) -> Result | None:
            return Result(value={"id": transcript.id})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_all_message_types_union():
    """Union of all message types should work with 'all'."""

    @scanner(messages="all")
    def test_scanner() -> Scanner[
        ChatMessageSystem | ChatMessageUser | ChatMessageAssistant | ChatMessageTool
    ]:
        async def scan(
            message: ChatMessageSystem
            | ChatMessageUser
            | ChatMessageAssistant
            | ChatMessageTool,
        ) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


# Invalid scanner tests


def test_subset_type_error():
    """Single type can't handle multiple filter types."""
    with pytest.raises(TypeError, match="must be able to handle all types"):

        @scanner(messages=["system", "user"])
        def test_scanner() -> Scanner[ChatMessageSystem]:
            async def scan(message: ChatMessageSystem) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()  # Validation happens here


def test_wrong_type_error():
    """Type not in filter should fail."""
    with pytest.raises(TypeError, match="must be able to handle all types"):

        @scanner(messages=["user"])
        def test_scanner() -> Scanner[ChatMessageAssistant]:
            async def scan(message: ChatMessageAssistant) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_partial_union_error():
    """Union missing required types should fail."""
    with pytest.raises(TypeError, match="must be able to handle all types"):

        @scanner(messages=["system", "user", "assistant"])
        def test_scanner() -> Scanner[ChatMessageSystem | ChatMessageUser]:
            async def scan(
                message: ChatMessageSystem | ChatMessageUser,
            ) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_all_filter_with_specific_type():
    """messages='all' with specific type should fail."""
    with pytest.raises(TypeError, match="must accept ChatMessage"):

        @scanner(messages="all")
        def test_scanner() -> Scanner[ChatMessageAssistant]:
            async def scan(message: ChatMessageAssistant) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_events_all_with_specific_type():
    """events='all' with specific type should fail."""
    with pytest.raises(TypeError, match="must accept Event"):

        @scanner(events="all")
        def test_scanner() -> Scanner[ModelEvent]:
            async def scan(event: ModelEvent) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_both_filters_without_transcript():
    """Both filters present but not accepting Transcript should fail."""
    with pytest.raises(TypeError, match="must accept Transcript"):

        @scanner(messages=["user"], events=["model"])
        def test_scanner() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_list_of_wrong_type():
    """List of wrong type should fail."""
    with pytest.raises(TypeError, match="must be able to handle all types"):

        @scanner(messages=["user"])
        def test_scanner() -> Scanner[list[ChatMessageAssistant]]:
            async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_list_of_partial_union():
    """List of partial union should fail."""
    with pytest.raises(TypeError, match="must be able to handle all types"):

        @scanner(messages=["system", "user", "assistant"])
        def test_scanner() -> Scanner[list[ChatMessageSystem | ChatMessageUser]]:
            async def scan(
                messages: list[ChatMessageSystem | ChatMessageUser],
            ) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


# Edge case tests


def test_no_type_hints():
    """Scanner without type hints should not raise."""

    @scanner(messages=["system"])
    def test_scanner():
        async def scan(message):
            return Result(value={"ok": True})

        return scan

    # Should not raise even without type hints
    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")


def test_scanner_without_filters_but_with_loader():
    """Scanner with only a custom loader should work."""
    from inspect_ai.scanner._loader import loader

    @loader(name="test_loader")
    def test_loader():
        async def load(transcripts):
            for t in transcripts:
                yield t

        return load

    @scanner(loader=test_loader())
    def test_scanner() -> Scanner[Transcript]:
        async def scan(transcript: Transcript) -> Result | None:
            return Result(value={"id": transcript.id})

        return scan

    scanner_instance = test_scanner()
    assert hasattr(scanner_instance, "__scanner__")
    assert scanner_instance.__scanner__.loader


def test_non_async_scanner():
    """Non-async scanner should raise TypeError."""
    with pytest.raises(TypeError, match="not declared as an async callable"):

        @scanner(messages=["system"])
        def test_scanner() -> Scanner[ChatMessage]:
            def scan(message: ChatMessage) -> Result | None:  # Not async!
                return Result(value={"bad": True})

            return scan  # type: ignore[return-value]

        test_scanner()


def test_multiple_event_types():
    """Multiple event types should work correctly."""

    @scanner(events=["model", "tool", "error", "sample_init"])
    def test_scanner() -> Scanner[Event]:
        async def scan(event: Event) -> Result | None:
            return Result(value={"event": event.event})

        return scan

    scanner_instance = test_scanner()
    assert len(scanner_instance.__scanner__.content.events) == 4


def test_all_supported_event_types():
    """Test all currently supported event types."""
    all_events = [
        "model",
        "tool",
        "sample_init",
        "sample_limit",
        "sandbox",
        "state",
        "store",
        "approval",
        "input",
        "score",
        "error",
        "logger",
        "info",
        "span_begin",
        "span_end",
    ]

    @scanner(events=all_events)
    def test_scanner() -> Scanner[Event]:
        async def scan(event: Event) -> Result | None:
            return Result(value={"ok": True})

        return scan

    scanner_instance = test_scanner()
    assert len(scanner_instance.__scanner__.content.events) == len(all_events)


# Parametrized tests


@pytest.mark.parametrize(
    "filter_types,scanner_type,should_pass",
    [
        # Valid cases
        (["system"], ChatMessageSystem, True),
        (["system"], ChatMessage, True),
        (["system", "user"], ChatMessage, True),
        (["assistant"], ChatMessageAssistant, True),
        ("all", ChatMessage, True),
        # Invalid cases
        (["system", "user"], ChatMessageSystem, False),
        (["user"], ChatMessageAssistant, False),
        (["system", "user", "assistant"], ChatMessageSystem | ChatMessageUser, False),
        ("all", ChatMessageAssistant, False),
    ],
)
def test_message_validation_matrix(filter_types, scanner_type, should_pass):
    """Test various combinations of filters and types."""
    if should_pass:

        @scanner(messages=filter_types)
        def test_scanner() -> Scanner[scanner_type]:  # pyright: ignore[reportInvalidTypeForm]
            async def scan(message: scanner_type) -> Result | None:  # type: ignore
                return Result(value={"ok": True})

            return scan

        scanner_instance = test_scanner()
        assert hasattr(scanner_instance, "__scanner__")
    else:
        with pytest.raises(TypeError):

            @scanner(messages=filter_types)
            def test_scanner() -> Scanner[scanner_type]:  # pyright: ignore[reportInvalidTypeForm]
                async def scan(message: scanner_type) -> Result | None:  # type: ignore
                    return Result(value={"bad": True})

                return scan

            test_scanner()
