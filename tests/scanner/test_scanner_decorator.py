"""Tests for the scanner decorator functionality."""

import pytest

from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._scanner import Scanner, scanner

# Scanner decorator tests


def test_scanner_creates_config():
    """Scanner decorator should add __scanner__ config."""

    @scanner(messages=["system"])
    def test_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    instance = test_scanner()
    assert hasattr(instance, "__scanner__")
    config = instance.__scanner__
    assert config.name == "test_scanner"
    assert config.content.messages == ["system"]


def test_scanner_with_custom_name():
    """Scanner decorator should accept custom name."""

    @scanner(messages=["user"], name="custom_scanner")
    def test_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    instance = test_scanner()
    assert instance.__scanner__.name == "custom_scanner"


def test_scanner_with_events():
    """Scanner decorator should handle event filters."""
    from inspect_ai.log._transcript import Event

    @scanner(events=["model", "tool"])
    def test_scanner() -> Scanner[Event]:
        async def scan(event: Event) -> Result | None:
            return Result(value={"event": event.event})

        return scan

    instance = test_scanner()
    assert instance.__scanner__.content.events == ["model", "tool"]


def test_scanner_with_both_filters():
    """Scanner decorator should handle both message and event filters."""
    from inspect_ai.scanner._transcript.types import Transcript

    @scanner(messages=["user"], events=["model"])
    def test_scanner() -> Scanner[Transcript]:
        async def scan(transcript: Transcript) -> Result | None:
            return Result(value={"id": transcript.id})

        return scan

    instance = test_scanner()
    config = instance.__scanner__
    assert config.content.messages == ["user"]
    assert config.content.events == ["model"]


def test_scanner_requires_async():
    """Scanner must be async."""
    with pytest.raises(TypeError, match="not declared as an async callable"):

        @scanner(messages=["system"])
        def test_scanner() -> Scanner[ChatMessage]:
            def scan(message: ChatMessage) -> Result | None:  # Not async!
                return Result(value={"bad": True})

            return scan  # type: ignore[return-value]

        test_scanner()


def test_scanner_requires_at_least_one_filter_or_loader():
    """Scanner decorator requires at least one filter or loader."""
    with pytest.raises(ValueError, match="requires at least one of"):

        @scanner()  # No filters or loader!
        def test_scanner() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"bad": True})

            return scan

        test_scanner()


def test_scanner_factory_with_parameters():
    """Scanner factory can accept parameters."""

    @scanner(messages=["assistant"])
    def parameterized_scanner(threshold: int = 10) -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            if len(message.text) > threshold:
                return Result(value={"long": True})
            return Result(value={"short": True})

        return scan

    # Create instances with different parameters
    scanner1 = parameterized_scanner(threshold=5)
    scanner2 = parameterized_scanner(threshold=20)

    assert hasattr(scanner1, "__scanner__")
    assert hasattr(scanner2, "__scanner__")
    # Both should have the same config
    assert scanner1.__scanner__.name == scanner2.__scanner__.name


def test_scanner_with_loader():
    """Scanner can use a custom loader."""
    from inspect_ai.scanner._loader import loader
    from inspect_ai.scanner._transcript.types import Transcript

    @loader(name="test_loader")
    def test_loader():
        async def load(transcripts):
            for t in transcripts:
                yield t

        return load

    loader_instance = test_loader()

    @scanner(loader=loader_instance)
    def test_scanner() -> Scanner[Transcript]:
        async def scan(transcript: Transcript) -> Result | None:
            return Result(value={"id": transcript.id})

        return scan

    instance = test_scanner()
    assert instance.__scanner__.loader
    assert instance.__scanner__.loader == loader_instance


def test_scanner_preserves_function_metadata():
    """Scanner decorator should preserve function metadata."""

    @scanner(messages=["system"])
    def test_scanner_with_doc() -> Scanner[ChatMessage]:
        """This is a test scanner."""

        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    # Check that metadata is preserved
    assert test_scanner_with_doc.__name__ == "test_scanner_with_doc"
    assert test_scanner_with_doc.__doc__ == "This is a test scanner."


# Scanner registry tests


def test_scanner_added_to_registry():
    """Scanner should be added to registry."""

    @scanner(messages=["system"], name="registry_test_scanner")
    def test_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"ok": True})

        return scan

    # Create an instance to trigger registration
    scanner_instance = test_scanner()

    # The scanner instance should have __scanner__ config
    assert hasattr(scanner_instance, "__scanner__")
    assert scanner_instance.__scanner__.name == "registry_test_scanner"


def test_multiple_scanners_different_names():
    """Multiple scanners can be registered with different names."""

    @scanner(messages=["system"], name="scanner_one")
    def scanner1() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"scanner": 1})

        return scan

    @scanner(messages=["user"], name="scanner_two")
    def scanner2() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"scanner": 2})

        return scan

    instance1 = scanner1()
    instance2 = scanner2()

    assert instance1.__scanner__.name == "scanner_one"
    assert instance2.__scanner__.name == "scanner_two"
