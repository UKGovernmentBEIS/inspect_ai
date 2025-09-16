"""Tests for the loader functionality."""

from typing import AsyncGenerator, Sequence

import pytest

from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.scanner._loader import loader
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._scanner import Scanner, scanner
from inspect_ai.scanner._transcript import Transcript

# Loader decorator tests


def test_loader_creates_config():
    """Loader decorator should add __loader__ config."""

    @loader(name="test_loader")
    def test_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[ChatMessage, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for msg in t.messages:
                    yield msg

        return load

    instance = test_loader()
    assert hasattr(instance, "__loader__")
    config = instance.__loader__
    assert config.name == "test_loader"


def test_loader_with_message_filter():
    """Loader can have message filters."""

    @loader(messages=["user"])
    def test_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[ChatMessageUser, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for msg in t.messages:
                    if msg.role == "user" and isinstance(msg, ChatMessageUser):
                        yield msg

        return load

    instance = test_loader()
    assert instance.__loader__.content.messages == ["user"]


def test_loader_with_event_filter():
    """Loader can have event filters."""
    from inspect_ai.log._transcript import Event

    @loader(events=["model", "tool"])
    def test_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[Event, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for event in t.events:
                    if event.event in ["model", "tool"]:
                        yield event

        return load

    instance = test_loader()
    assert instance.__loader__.content.events == ["model", "tool"]


def test_loader_requires_async():
    """Loader must be async."""
    with pytest.raises(TypeError, match="not declared as an async callable"):

        @loader(name="bad_loader")
        def test_loader():
            def load(transcripts):  # Not async!
                return transcripts

            return load

        test_loader()


def test_loader_with_both_filters():
    """Loader can have both message and event filters."""

    @loader(messages=["user"], events=["model"])
    def test_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[Transcript, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                yield t

        return load

    instance = test_loader()
    config = instance.__loader__
    assert config.content.messages == ["user"]
    assert config.content.events == ["model"]


# Loader integration tests


def test_scanner_with_custom_loader():
    """Scanner can use a custom loader."""

    @loader(messages=["user"])
    def user_message_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[ChatMessageUser, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for msg in t.messages:
                    if msg.role == "user" and isinstance(msg, ChatMessageUser):
                        yield msg

        return load

    loader_instance = user_message_loader()

    @scanner(loader=loader_instance)
    def user_scanner() -> Scanner[ChatMessageUser]:
        async def scan(message: ChatMessageUser) -> Result | None:
            return Result(value={"user_content": message.text})

        return scan

    scanner_instance = user_scanner()
    assert scanner_instance.__scanner__.loader == loader_instance


def test_loader_type_transformation():
    """Loader can transform transcript data types."""
    from inspect_ai.log._transcript import Event

    @loader(name="event_extractor")
    def event_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[Event, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for event in t.events:
                    yield event

        return load

    loader_instance = event_loader()

    @scanner(loader=loader_instance)
    def event_scanner() -> Scanner[Event]:
        async def scan(event: Event) -> Result | None:
            return Result(value={"event_type": event.event})

        return scan

    scanner_instance = event_scanner()
    assert scanner_instance.__scanner__.loader


def test_loader_with_custom_logic():
    """Loader can implement custom filtering/transformation logic."""

    @loader(name="long_message_loader")
    def long_message_loader(min_length: int = 100):
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[ChatMessage, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for msg in t.messages:
                    content = (
                        msg.text
                        if hasattr(msg, "text")
                        else str(msg.content)
                        if msg.content
                        else ""
                    )
                    if len(content) > min_length:
                        yield msg

        return load

    # Create loader with custom parameter
    loader_instance = long_message_loader(min_length=50)

    @scanner(loader=loader_instance)
    def long_message_scanner() -> Scanner[ChatMessage]:
        async def scan(message: ChatMessage) -> Result | None:
            return Result(value={"length": len(message.text)})

        return scan

    scanner_instance = long_message_scanner()
    assert scanner_instance.__scanner__.loader


# Loader registry tests


def test_loader_added_to_registry():
    """Loader should be added to registry."""

    @loader(name="registry_test_loader")
    def test_loader():
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[Transcript, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                yield t

        return load

    # Create an instance to trigger registration
    loader_instance = test_loader()

    # The loader instance should have __loader__ config
    assert hasattr(loader_instance, "__loader__")
    assert loader_instance.__loader__.name == "registry_test_loader"


def test_loader_factory_with_parameters():
    """Loader factory can accept parameters."""

    @loader(name="parameterized_loader", messages=["assistant"])
    def param_loader(include_model: bool = True):
        async def load(
            transcripts: Transcript | Sequence[Transcript],
        ) -> AsyncGenerator[ChatMessageAssistant, None]:
            if isinstance(transcripts, Transcript):
                transcripts = [transcripts]
            for t in transcripts:
                for msg in t.messages:
                    if msg.role == "assistant" and isinstance(
                        msg, ChatMessageAssistant
                    ):
                        if include_model or not hasattr(msg, "model"):
                            yield msg

        return load

    # Create instances with different parameters
    loader1 = param_loader(include_model=True)
    loader2 = param_loader(include_model=False)

    assert hasattr(loader1, "__loader__")
    assert hasattr(loader2, "__loader__")
    # Both should have the same config name
    assert loader1.__loader__.name == loader2.__loader__.name
