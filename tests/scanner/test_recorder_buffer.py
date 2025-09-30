from __future__ import annotations

import tempfile

import pytest

from inspect_ai.scanner._recorder.buffer import RecorderBuffer
from inspect_ai.scanner._scanner.result import Reference, Result
from inspect_ai.scanner._transcript.types import TranscriptInfo


@pytest.fixture
def recorder_buffer():
    """Create a temporary RecorderBuffer for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        buffer = RecorderBuffer(tmpdir)
        yield buffer
        buffer.cleanup()


@pytest.fixture
def sample_transcript():
    """Create a sample TranscriptInfo for testing."""
    return TranscriptInfo(
        id="test-transcript-123",
        source_id="source-42",
        source_uri="/path/to/source.log",
        metadata={"model": "gpt-4", "temperature": 0.7},
    )


@pytest.fixture
def sample_results():
    """Create sample Results for testing."""
    return [
        Result(
            value="correct",
            answer="42",
            explanation="The answer to everything",
            metadata={"confidence": 0.95},
            references=[Reference(type="message", id="msg-1")],
        ),
        Result(
            value=True,
            answer="yes",
            explanation="Affirmative response",
            metadata={"confidence": 0.88},
            references=[Reference(type="event", id="evt-1")],
        ),
        Result(
            value=3.14159,
            answer=None,
            explanation="Pi value",
            metadata=None,
            references=[],
        ),
    ]


@pytest.mark.asyncio
async def test_is_recorded(
    recorder_buffer: RecorderBuffer,
    sample_transcript: TranscriptInfo,
    sample_results: list[Result],
):
    """Test is_recorded method."""
    scanner_name = "test_scanner"

    # Check before recording
    is_recorded = await recorder_buffer.is_recorded(sample_transcript, scanner_name)
    assert is_recorded is False

    # Record data
    await recorder_buffer.record(sample_transcript, scanner_name, sample_results)

    # Check after recording
    is_recorded = await recorder_buffer.is_recorded(sample_transcript, scanner_name)
    assert is_recorded is True

    # Check with different transcript ID
    other_transcript = TranscriptInfo(
        id="other-transcript-456", source_id="42", source_uri="/other/source.log"
    )
    is_recorded = await recorder_buffer.is_recorded(other_transcript, scanner_name)
    assert is_recorded is False


@pytest.mark.asyncio
async def test_sanitize_table_names(
    recorder_buffer: RecorderBuffer,
    sample_transcript: TranscriptInfo,
    sample_results: list[Result],
):
    """Test that table names with special characters are sanitized."""
    scanner_name = "test-scanner.with:special/chars"

    # Record with special characters in scanner name
    await recorder_buffer.record(sample_transcript, scanner_name, sample_results)

    # Should still be able to retrieve
    recorder_buffer.scanner_table(scanner_name)
