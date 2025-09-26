from __future__ import annotations

import tempfile

import pandas as pd
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
        source="/path/to/source.log",
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
async def test_record_and_retrieve(
    recorder_buffer: RecorderBuffer,
    sample_transcript: TranscriptInfo,
    sample_results: list[Result],
):
    """Test basic record and retrieve functionality."""
    scanner_name = "test_scanner"

    # Record data
    await recorder_buffer.record(sample_transcript, scanner_name, sample_results)

    # Retrieve data
    table = await recorder_buffer.table_for_scanner(scanner_name)

    assert table is not None
    assert table.num_rows == 3
    assert "transcript_id" in table.column_names
    assert "transcript_source" in table.column_names
    assert "value" in table.column_names
    assert "answer" in table.column_names
    assert "explanation" in table.column_names
    assert "metadata" in table.column_names
    assert "references" in table.column_names

    # Convert to pandas for easier assertions
    df = table.to_pandas()

    # Check transcript info
    assert df["transcript_id"].iloc[0] == "test-transcript-123"
    assert df["transcript_source"].iloc[0] == "/path/to/source.log"

    # Check values (mixed types are converted to strings)
    assert df["value"].iloc[0] == "correct"
    assert df["value"].iloc[1] == "True"
    assert df["value"].iloc[2] == "3.14159"


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
        id="other-transcript-456", source="/other/source.log"
    )
    is_recorded = await recorder_buffer.is_recorded(other_transcript, scanner_name)
    assert is_recorded is False


@pytest.mark.asyncio
async def test_table_for_nonexistent_scanner(recorder_buffer: RecorderBuffer):
    """Test table_for_scanner with non-existent scanner."""
    table = await recorder_buffer.table_for_scanner("nonexistent_scanner")
    assert table is None


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
    table = await recorder_buffer.table_for_scanner(scanner_name)
    assert table is not None
    assert table.num_rows == 3

    # Check is_recorded also works
    is_recorded = await recorder_buffer.is_recorded(sample_transcript, scanner_name)
    assert is_recorded is True


@pytest.mark.asyncio
async def test_type_preservation(
    recorder_buffer: RecorderBuffer, sample_transcript: TranscriptInfo
):
    """Test that types are preserved through arrow mapping."""
    scanner_name = "type_test"

    # Create results with various types
    results = [
        Result(value="string_value"),
        Result(value=42),
        Result(value=3.14),
        Result(value=True),
        Result(value=False),
        Result(value=None),
        Result(value={"nested": "dict"}),
        Result(value=["list", "of", "items"]),
    ]

    # Record data
    await recorder_buffer.record(sample_transcript, scanner_name, results)

    # Retrieve data
    table = await recorder_buffer.table_for_scanner(scanner_name)

    assert table is not None
    assert table.num_rows == 8

    # Convert to pandas for easier assertions
    df = table.to_pandas()

    # Check that values are preserved (mixed types converted to strings)
    values = df["value"].tolist()
    assert values[0] == "string_value"
    assert values[1] == "42"
    assert values[2] == "3.14"
    assert values[3] == "True"
    assert values[4] == "False"
    assert pd.isna(values[5]) or values[5] is None
    # Complex types are JSON stringified (might have formatting)
    import json
    assert json.loads(values[6]) == {"nested": "dict"}
    assert json.loads(values[7]) == ["list", "of", "items"]


@pytest.mark.asyncio
async def test_multiple_scanners(
    recorder_buffer: RecorderBuffer,
    sample_transcript: TranscriptInfo,
    sample_results: list[Result],
):
    """Test handling multiple scanners in the same buffer."""
    scanner1 = "scanner_one"
    scanner2 = "scanner_two"

    # Record to two different scanners
    await recorder_buffer.record(sample_transcript, scanner1, sample_results[:2])
    await recorder_buffer.record(sample_transcript, scanner2, sample_results[1:])

    # Check both tables exist and have correct data
    table1 = await recorder_buffer.table_for_scanner(scanner1)
    table2 = await recorder_buffer.table_for_scanner(scanner2)

    assert table1 is not None
    assert table2 is not None
    assert table1.num_rows == 2
    assert table2.num_rows == 2

    # Check is_recorded for both
    assert await recorder_buffer.is_recorded(sample_transcript, scanner1) is True
    assert await recorder_buffer.is_recorded(sample_transcript, scanner2) is True


@pytest.mark.asyncio
async def test_empty_results(
    recorder_buffer: RecorderBuffer, sample_transcript: TranscriptInfo
):
    """Test recording empty results list."""
    scanner_name = "empty_scanner"

    # Record empty results
    await recorder_buffer.record(sample_transcript, scanner_name, [])

    # Table should not exist
    table = await recorder_buffer.table_for_scanner(scanner_name)
    assert table is None

    # Should not be recorded
    is_recorded = await recorder_buffer.is_recorded(sample_transcript, scanner_name)
    assert is_recorded is False


@pytest.mark.asyncio
async def test_duplicate_recording(
    recorder_buffer: RecorderBuffer,
    sample_transcript: TranscriptInfo,
    sample_results: list[Result],
):
    """Test that recording is idempotent for the same transcript."""
    scanner_name = "duplicate_test"

    # Record initial data
    await recorder_buffer.record(sample_transcript, scanner_name, sample_results[:1])

    table1 = await recorder_buffer.table_for_scanner(scanner_name)
    assert table1 is not None
    assert table1.num_rows == 1

    # Record again with more data for same transcript - should be idempotent
    await recorder_buffer.record(sample_transcript, scanner_name, sample_results)

    table2 = await recorder_buffer.table_for_scanner(scanner_name)
    assert table2 is not None
    # Should still have 1 row (idempotent - one file per transcript)
    assert table2.num_rows == 1
