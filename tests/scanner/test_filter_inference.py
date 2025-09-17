"""Tests for automatic filter inference from type annotations."""

import pytest

from inspect_ai.log._transcript import ModelEvent, ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._scanner import Scanner, scanner
from inspect_ai.scanner._transcript.types import Transcript


def test_infer_single_message_type():
    """Scanner with specific message type should infer filter."""

    @scanner()  # No explicit messages filter
    def user_scanner() -> Scanner[ChatMessageUser]:
        async def scan(message: ChatMessageUser) -> Result | None:
            return Result(value={"text": message.text})

        return scan

    instance = user_scanner()
    assert hasattr(instance, "__scanner__")
    assert instance.__scanner__.content.messages == ["user"]


def test_infer_union_message_types():
    """Scanner with union of message types should infer filters."""

    @scanner()  # No explicit filters
    def multi_scanner() -> Scanner[ChatMessageSystem | ChatMessageUser]:
        async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
            return Result(value={"role": message.role})

        return scan

    instance = multi_scanner()
    assert set(instance.__scanner__.content.messages) == {"system", "user"}


def test_infer_assistant_type():
    """Scanner with assistant type should infer filter."""

    @scanner()
    def assistant_scanner() -> Scanner[ChatMessageAssistant]:
        async def scan(message: ChatMessageAssistant) -> Result | None:
            return Result(value={"model": message.model})

        return scan

    instance = assistant_scanner()
    assert instance.__scanner__.content.messages == ["assistant"]


def test_infer_list_message_type():
    """Scanner with list of specific message type should infer filter."""

    @scanner()
    def batch_scanner() -> Scanner[list[ChatMessageAssistant]]:
        async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
            return Result(value={"count": len(messages)})

        return scan

    instance = batch_scanner()
    assert instance.__scanner__.content.messages == ["assistant"]


def test_infer_event_type():
    """Scanner with specific event type should infer filter."""

    @scanner()
    def model_scanner() -> Scanner[ModelEvent]:
        async def scan(event: ModelEvent) -> Result | None:
            return Result(value={"model": event.model})

        return scan

    instance = model_scanner()
    assert instance.__scanner__.content.events == ["model"]


def test_infer_union_event_types():
    """Scanner with union of event types should infer filters."""

    @scanner()
    def event_scanner() -> Scanner[ModelEvent | ToolEvent]:
        async def scan(event: ModelEvent | ToolEvent) -> Result | None:
            return Result(value={"event": event.event})

        return scan

    instance = event_scanner()
    assert set(instance.__scanner__.content.events) == {"model", "tool"}


def test_no_inference_for_base_message_type():
    """Scanner with base ChatMessage type should require explicit filter."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner()  # No filter, can't infer from base type
        def base_scanner() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"role": message.role})

            return scan

        base_scanner()


def test_no_inference_for_transcript():
    """Scanner with Transcript type should require explicit filters."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner()  # No filters, can't infer for Transcript
        def transcript_scanner() -> Scanner[Transcript]:
            async def scan(transcript: Transcript) -> Result | None:
                return Result(value={"id": transcript.id})

            return scan

        transcript_scanner()


def test_explicit_filter_overrides_inference():
    """Explicit filter should take precedence over type inference."""

    @scanner(messages=["system"])  # Explicit filter
    def explicit_scanner() -> Scanner[ChatMessageSystem]:  # Must match filter
        async def scan(message: ChatMessageSystem) -> Result | None:
            return Result(value={"text": message.text})

        return scan

    instance = explicit_scanner()
    # Should use explicit filter (no inference needed)
    assert instance.__scanner__.content.messages == ["system"]


def test_inference_with_custom_name():
    """Filter inference should work with custom scanner name."""

    @scanner(name="custom_inferred")
    def named_scanner() -> Scanner[ChatMessageAssistant]:
        async def scan(message: ChatMessageAssistant) -> Result | None:
            return Result(value={"model": message.model})

        return scan

    instance = named_scanner()
    assert instance.__scanner__.name == "custom_inferred"
    assert instance.__scanner__.content.messages == ["assistant"]


def test_inference_with_factory_pattern():
    """Filter inference should work with factory pattern."""

    @scanner()
    def parameterized_scanner(threshold: int = 10) -> Scanner[ChatMessageAssistant]:
        async def scan(message: ChatMessageAssistant) -> Result | None:
            if len(message.text) > threshold:
                return Result(value={"long": True})
            return Result(value={"short": True})

        return scan

    instance = parameterized_scanner(threshold=5)
    assert instance.__scanner__.content.messages == ["assistant"]


def test_no_inference_with_loader():
    """No filter inference when loader is provided."""
    from inspect_ai.scanner._loader import loader

    @loader(name="test_loader")
    def test_loader():
        async def load(transcripts):
            for t in transcripts:
                yield t

        return load

    loader_instance = test_loader()

    # Should work without filters when loader is provided
    @scanner(loader=loader_instance)
    def loader_scanner() -> Scanner[Transcript]:
        async def scan(transcript: Transcript) -> Result | None:
            return Result(value={"id": transcript.id})

        return scan

    instance = loader_scanner()
    assert instance.__scanner__.loader
    # No messages or events should be inferred
    assert instance.__scanner__.content.messages is None
    assert instance.__scanner__.content.messages is None


def test_no_inference_with_mixed_message_event_union():
    """Scanner with union of messages and events should require explicit filters or Transcript."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner()  # Can't infer when mixing messages and events
        def mixed_scanner() -> Scanner[ChatMessageUser | ModelEvent]:
            async def scan(item: ChatMessageUser | ModelEvent) -> Result | None:
                if isinstance(item, ChatMessageUser):
                    return Result(value={"type": "message", "content": item.text})
                else:
                    return Result(value={"type": "event", "model": item.model})

            return scan

        mixed_scanner()


def test_no_inference_without_type_hints():
    """Scanner without type hints should require explicit filters."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner()
        def untyped_scanner():  # No type annotation
            async def scan(message):  # No type annotation
                return Result(value={"ok": True})

            return scan

        untyped_scanner()


def test_decorator_without_parentheses():
    """Scanner decorator can be used without parentheses when types can be inferred."""

    @scanner  # No parentheses!
    def user_scanner() -> Scanner[ChatMessageUser]:
        async def scan(message: ChatMessageUser) -> Result | None:
            return Result(value={"text": message.text})

        return scan

    instance = user_scanner()
    assert hasattr(instance, "__scanner__")
    assert instance.__scanner__.content.messages == ["user"]


def test_decorator_without_parentheses_with_union():
    """Scanner decorator without parentheses works with union types."""

    @scanner  # No parentheses!
    def multi_scanner() -> Scanner[ChatMessageSystem | ChatMessageUser]:
        async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
            return Result(value={"role": message.role})

        return scan

    instance = multi_scanner()
    assert set(instance.__scanner__.content.messages) == {"system", "user"}


def test_decorator_without_parentheses_fails_for_base_type():
    """Scanner decorator without parentheses should fail for base ChatMessage type."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner  # No parentheses, but base type needs explicit filter
        def base_scanner() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"role": message.role})

            return scan

        base_scanner()
