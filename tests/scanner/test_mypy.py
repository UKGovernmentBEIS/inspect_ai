"""Tests for mypy type checking of scanner and loader declarations."""

import subprocess
import tempfile
import textwrap
from pathlib import Path


def test_mypy_scanner_and_loader_types():
    """Test all mypy type checking for scanners and loaders in a single run."""
    # Create a single file with all test cases
    test_code = textwrap.dedent("""
        from typing import AsyncGenerator, Sequence, Union
        from inspect_ai.event import Event, ModelEvent, ToolEvent
        from inspect_ai.model._chat_message import (
            ChatMessage,
            ChatMessageAssistant,
            ChatMessageSystem,
            ChatMessageUser,
        )
        from inspect_ai.scanner._scanner.result import Result
        from inspect_ai.scanner._scanner.scanner import Scanner, scanner
        from inspect_ai.scanner._scanner.loader import Loader, loader
        from inspect_ai.scanner._transcript.types import Transcript

        # Valid scanner patterns

        @scanner(messages=["assistant"])
        def valid_single_type() -> Scanner[ChatMessageAssistant]:
            async def scan(message: ChatMessageAssistant) -> Result | None:
                return Result(value={"model": message.model})
            return scan

        @scanner(messages=["system", "user"])
        def valid_union_type() -> Scanner[ChatMessageSystem | ChatMessageUser]:
            async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
                return Result(value={"role": message.role})
            return scan

        @scanner(messages=["system", "user"])
        def valid_base_type() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"role": message.role})
            return scan

        @scanner(messages="all")
        def valid_all_messages() -> Scanner[ChatMessage]:
            async def scan(message: ChatMessage) -> Result | None:
                return Result(value={"role": message.role})
            return scan

        @scanner(messages=["assistant"])
        def valid_list_type() -> Scanner[list[ChatMessageAssistant]]:
            async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
                count = len(messages)
                if messages:
                    first = messages[0]
                    model = first.model
                return Result(value={"count": count})
            return scan

        @scanner(messages=["user"], events=["model"])
        def valid_transcript() -> Scanner[Transcript]:
            async def scan(transcript: Transcript) -> Result | None:
                msg_count = len(transcript.messages)
                event_count = len(transcript.events)
                return Result(value={"messages": msg_count, "events": event_count})
            return scan

        # Valid loader patterns

        @loader(messages=["assistant"])
        def typed_loader():  # type: ignore[no-untyped-def]
            async def load(
                transcript: Transcript
            ) -> AsyncGenerator[ChatMessageAssistant, None]:
                for msg in transcript.messages:
                    if msg.role == "assistant" and isinstance(msg, ChatMessageAssistant):
                        yield msg
            return load

        @loader(events=["model", "tool"])
        def event_loader():  # type: ignore[no-untyped-def]
            async def load(
                transcript: Transcript
            ) -> AsyncGenerator[Event, None]:
                for event in transcript.events:
                    if event.event in ["model", "tool"]:
                        yield event
            return load

        # Scanner with loader integration

        @loader(messages=["user"])
        def user_loader():  # type: ignore[no-untyped-def]
            async def load(
                transcript: Transcript
            ) -> AsyncGenerator[ChatMessageUser, None]:
                for msg in transcript.messages:
                    if msg.role == "user" and isinstance(msg, ChatMessageUser):
                        yield msg
            return load

        @scanner(loader=user_loader())
        def scanner_with_loader() -> Scanner[ChatMessageUser]:
            async def scan(message: ChatMessageUser) -> Result | None:
                text = message.text
                return Result(value={"user_said": text})
            return scan

        # Factory patterns

        @scanner(messages=["assistant"])
        def factory_scanner(min_length: int = 100) -> Scanner[ChatMessageAssistant]:
            async def scan(message: ChatMessageAssistant) -> Result | None:
                text = message.text
                if len(text) > min_length:
                    return Result(value={"long": True, "model": message.model})
                return Result(value={"short": True})
            return scan

        @loader(messages=["assistant"])
        def factory_loader(include_model: str | None = None):  # type: ignore[no-untyped-def]
            async def load(
                transcript: Transcript
            ) -> AsyncGenerator[ChatMessageAssistant, None]:
                for msg in transcript.messages:
                    if msg.role == "assistant" and isinstance(msg, ChatMessageAssistant):
                        if include_model is None or msg.model == include_model:
                            yield msg
            return load

        # Create instances
        scanner1 = factory_scanner(min_length=50)
        scanner2 = factory_scanner(min_length=200)
        loader1 = factory_loader(include_model="gpt-4")
        loader2 = factory_loader()
    """)

    # Create a temporary file with the code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_code)
        temp_path = f.name

    try:
        # Run mypy on the file
        result = subprocess.run(
            ["python", "-m", "mypy", "--strict", "--no-error-summary", temp_path],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),  # Run from project root
        )

        # Check that mypy passes
        assert result.returncode == 0, f"Mypy failed:\n{result.stdout}\n{result.stderr}"

    finally:
        # Clean up the temp file
        Path(temp_path).unlink(missing_ok=True)


def test_mypy_detects_type_errors():
    """Test that mypy can detect obvious type errors."""
    error_code = textwrap.dedent("""
        from typing import AsyncGenerator, Sequence
        from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageUser
        from inspect_ai.scanner._result import Result
        from inspect_ai.scanner._scanner import Scanner, scanner
        from inspect_ai.scanner._loader import loader
        from inspect_ai.scanner._transcript import Transcript

        # This should be an error - returning wrong type
        @scanner(messages=["assistant"])
        def wrong_return_type() -> Scanner[ChatMessageAssistant]:
            async def scan(message: ChatMessageAssistant) -> str:  # Wrong return type!
                return "this is wrong"
            return scan

        # This should be an error - scan function not async
        @scanner(messages=["assistant"])
        def not_async_scanner() -> Scanner[ChatMessageAssistant]:
            def scan(message: ChatMessageAssistant) -> Result | None:  # Not async!
                return Result(value={"bad": True})
            return scan

        # This should be an error - loader returns User but scanner expects Assistant
        @loader(messages=["user"])
        def user_msg_loader():  # type: ignore[no-untyped-def]
            async def load(
                transcript: Transcript
            ) -> AsyncGenerator[ChatMessageUser, None]:
                for msg in transcript.messages:
                    if msg.role == "user" and isinstance(msg, ChatMessageUser):
                        yield msg
            return load

        @scanner(loader=user_msg_loader())
        def mismatched_scanner() -> Scanner[ChatMessageAssistant]:  # Wrong type!
            async def scan(message: ChatMessageAssistant) -> Result | None:
                return Result(value={"model": message.model})
            return scan
    """)

    # Create a temporary file with the code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(error_code)
        temp_path = f.name

    try:
        # Run mypy on the file
        result = subprocess.run(
            ["python", "-m", "mypy", "--strict", "--no-error-summary", temp_path],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        # Check that mypy detects errors
        assert result.returncode != 0, "Mypy should have detected type errors"

    finally:
        # Clean up the temp file
        Path(temp_path).unlink(missing_ok=True)
