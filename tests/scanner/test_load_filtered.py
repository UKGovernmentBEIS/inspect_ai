"""Tests for load_filtered_transcript function."""

import io
import json
import os
import shutil
import time
import urllib.request
from typing import Counter
from zipfile import ZipFile

import pytest

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai.scanner._transcript.json.load_filtered import (
    RawTranscript,
    _parse_and_filter,
    _resolve_attachments,
    _resolve_dict_attachments,
    load_filtered_transcript,
)
from inspect_ai.scanner._transcript.types import Transcript, TranscriptInfo


def create_json_stream(data: dict) -> io.BytesIO:
    """Create a BytesIO stream from dictionary data."""
    return io.BytesIO(json.dumps(data).encode())


@pytest.mark.asyncio
async def test_basic_loading():
    """Test basic transcript loading."""
    data = {
        "id": "test-001",
        "messages": [
            {"id": "m1", "role": "user", "content": "Hello"},
            {"id": "m2", "role": "assistant", "content": "Hi"},
        ],
        "events": [
            {
                "span_id": "s1",
                "timestamp": 1640995200.123,
                "event": "score",
                "score": {"value": 0.85},
            }
        ],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(
        id="test-001",
        source_id="source-001",
        source_uri="/test.json",
        metadata={"test": True},
    )

    result = await load_filtered_transcript(stream, info, "all", "all")

    assert isinstance(result, Transcript)
    assert result.id == "test-001"
    assert result.source_uri == "/test.json"
    assert result.metadata == {"test": True}
    assert len(result.messages) == 2
    assert len(result.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message_filter,expected_count,expected_roles",
    [
        (None, 0, []),
        (["user"], 1, ["user"]),
        (["user", "assistant"], 2, ["user", "assistant"]),
        ("all", 3, ["user", "assistant", "system"]),
    ],
)
async def test_message_filtering(message_filter, expected_count, expected_roles):
    """Test message filtering with different filter configurations."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant message"},
            {"role": "system", "content": "System message"},
        ],
        "events": [],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, message_filter, "all")

    assert len(result.messages) == expected_count
    actual_roles = [msg.role for msg in result.messages]
    assert set(actual_roles) == set(expected_roles)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_filter,expected_count,expected_types",
    [
        (None, 0, []),
        (["score"], 1, ["score"]),
        (["span_begin", "score"], 2, ["span_begin", "score"]),
        ("all", 3, ["span_begin", "score", "span_end"]),
    ],
)
async def test_event_filtering(event_filter, expected_count, expected_types):
    """Test event filtering with different filter configurations."""
    data = {
        "id": "test",
        "messages": [],
        "events": [
            {
                "span_id": "s1",
                "timestamp": 1.0,
                "event": "span_begin",
                "id": "s1",
                "name": "test_span",
            },
            {
                "span_id": "s2",
                "timestamp": 2.0,
                "event": "score",
                "score": {"value": 0.85},
            },
            {"span_id": "s3", "timestamp": 3.0, "event": "span_end", "id": "s1"},
        ],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", event_filter)

    assert len(result.events) == expected_count
    actual_types = [evt.event for evt in result.events]
    assert set(actual_types) == set(expected_types)


@pytest.mark.asyncio
async def test_combined_filtering():
    """Test filtering both messages and events simultaneously."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "system", "content": "S"},
        ],
        "events": [
            {
                "span_id": "s1",
                "timestamp": 1.0,
                "event": "score",
                "score": {"value": 0.9},
            },
            {"span_id": "s2", "timestamp": 2.0, "event": "error", "error": "Test"},
        ],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, ["user"], ["score"])

    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    assert len(result.events) == 1
    assert result.events[0].event == "score"


@pytest.mark.asyncio
async def test_attachment_resolution():
    """Test resolution of attachment references."""
    data = {
        "id": "test",
        "messages": [
            {
                "role": "user",
                "content": "attachment://a1b2c3d4e5f678901234567890123456",
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "attachment://b2c3d4e5f67890123456789012345678",
                    }
                ],
            },
        ],
        "events": [
            {
                "span_id": "s1",
                "timestamp": 1.0,
                "event": "tool",
                "id": "tool1",
                "function": "test_function",
                "arguments": {},
                "result": "attachment://c3d4e5f6789012345678901234567890",
            }
        ],
        "attachments": {
            "a1b2c3d4e5f678901234567890123456": "Content A",
            "b2c3d4e5f67890123456789012345678": "Content B",
            "c3d4e5f6789012345678901234567890": "Content C",
        },
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", "all")

    assert result.messages[0].content == "Content A"
    assert result.messages[1].content[0].text == "Content B"
    assert result.events[0].result == "Content C"


@pytest.mark.asyncio
async def test_missing_attachments():
    """Test handling of missing attachment references."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "attachment://missingabcdef1234567890123456"}
        ],
        "events": [],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", "all")

    # Missing attachment should remain as reference
    assert "attachment://missingabcdef1234567890123456" in result.messages[0].content


@pytest.mark.asyncio
async def test_malformed_attachments():
    """Test handling of malformed attachment references."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "attachment://short"},
            {
                "role": "user",
                "content": "attachment://toolong123456789012345678901234567890",
            },
            {"role": "user", "content": "Regular text without attachments"},
        ],
        "events": [],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", "all")

    # Malformed references should remain unchanged
    assert result.messages[0].content == "attachment://short"
    assert (
        result.messages[1].content
        == "attachment://toolong123456789012345678901234567890"
    )
    assert result.messages[2].content == "Regular text without attachments"


@pytest.mark.asyncio
async def test_unicode_and_special_chars():
    """Test handling of unicode and special characters in attachments."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "attachment://a1b2c3d4e5f678901234567890123456"}
        ],
        "events": [],
        "attachments": {
            "a1b2c3d4e5f678901234567890123456": "Unicode: éñ中文🌟\nSpecial: @#$%"
        },
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(id="test", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", "all")

    assert result.messages[0].content == "Unicode: éñ中文🌟\nSpecial: @#$%"


@pytest.mark.asyncio
async def test_empty_transcript():
    """Test handling of empty transcript."""
    data = {"id": "empty", "messages": [], "events": [], "attachments": {}}

    stream = create_json_stream(data)
    info = TranscriptInfo(id="empty", source_id="42", source_uri="/test.json")

    result = await load_filtered_transcript(stream, info, "all", "all")

    assert len(result.messages) == 0
    assert len(result.events) == 0


def test_parse_and_filter():
    """Test _parse_and_filter function directly."""
    data = {
        "id": "test",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "System"},
        ],
        "events": [
            {
                "span_id": "s1",
                "timestamp": 1.0,
                "event": "score",
                "score": {"value": 0.9},
            },
            {"span_id": "s2", "timestamp": 2.0, "event": "error", "error": "Error"},
        ],
        "attachments": {},
    }

    stream = create_json_stream(data)
    info = TranscriptInfo(
        id="test", source_id="42", source_uri="/test.json", metadata={"key": "value"}
    )

    raw_transcript, _ = _parse_and_filter(stream, info, ["user"], ["score"])

    assert isinstance(raw_transcript, RawTranscript)
    assert raw_transcript.id == "test"
    assert raw_transcript.metadata == {"key": "value"}
    assert len(raw_transcript.messages) == 1
    assert raw_transcript.messages[0]["role"] == "user"
    assert len(raw_transcript.events) == 1
    assert raw_transcript.events[0]["event"] == "score"


def test_resolve_dict_attachments():
    """Test _resolve_dict_attachments function."""

    def resolve_func(text: str) -> str:
        return text.replace("attachment://test", "RESOLVED")

    # Test string resolution
    result = _resolve_dict_attachments("attachment://test", resolve_func)
    assert result == "RESOLVED"

    # Test dict resolution
    test_dict = {
        "key1": "attachment://test",
        "nested": {"key2": "attachment://test"},
        "normal": "no attachment",
    }
    result = _resolve_dict_attachments(test_dict, resolve_func)
    assert result["key1"] == "RESOLVED"
    assert result["nested"]["key2"] == "RESOLVED"
    assert result["normal"] == "no attachment"

    # Test list resolution
    test_list = ["attachment://test", {"key": "attachment://test"}, 123]
    result = _resolve_dict_attachments(test_list, resolve_func)
    assert result[0] == "RESOLVED"
    assert result[1]["key"] == "RESOLVED"
    assert result[2] == 123

    # Test non-string/dict/list passthrough
    assert _resolve_dict_attachments(None, resolve_func) is None
    assert _resolve_dict_attachments(42, resolve_func) == 42


def test_resolve_attachments():
    """Test _resolve_attachments function."""
    raw_transcript = RawTranscript(
        id="test",
        source_id="source-42",
        source_uri="/test.json",
        metadata={},
        messages=[
            {"role": "user", "content": "attachment://a1b2c3d4e5f678901234567890123456"}
        ],
        events=[
            {
                "span_id": "s1",
                "timestamp": 1.0,
                "event": "tool",
                "id": "tool1",
                "function": "test_function",
                "arguments": {"input": "attachment://b2c3d4e5f67890123456789012345678"},
                "result": "test result",
            }
        ],
    )

    attachments = {
        "a1b2c3d4e5f678901234567890123456": "Resolved A",
        "b2c3d4e5f67890123456789012345678": "Resolved B",
    }

    result = _resolve_attachments(raw_transcript, attachments)

    assert isinstance(result, Transcript)
    assert result.messages[0].content == "Resolved A"
    assert result.events[0].arguments["input"] == "Resolved B"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_vend_fat_eval_assistant_tool_filter():
    # TODO: For now, we'll just copy the s3 file locally. Eventually, the test
    # will stream directly from s3
    s3_path = "https://slow-tests.s3.us-east-2.amazonaws.com/vend.eval"
    cache_root = inspect_cache_dir("tests")
    cache_root.mkdir(parents=True, exist_ok=True)
    file_path = str(cache_root / os.path.basename(s3_path))
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        tmp_download = file_path + ".partial"
        with urllib.request.urlopen(s3_path, timeout=30) as response:
            with open(tmp_download, "wb") as f:
                shutil.copyfileobj(response, f)
        os.replace(tmp_download, file_path)

    info = TranscriptInfo(
        id="what id?",
        source_id="vend_fat_eval",
        source_uri=file_path,
        metadata={"test": True},
    )

    # Extract the first JSON file from samples/ directory in the ZIP
    with ZipFile(file_path, mode="r") as zipfile:
        # Find the first JSON file in samples/
        sample_file = next(
            (
                f
                for f in zipfile.namelist()
                if f.startswith("samples/") and f.endswith(".json")
            ),
            None,
        )
        with zipfile.open(sample_file, "r") as sample_json:
            start = time.time()
            result = await load_filtered_transcript(
                sample_json,
                info,
                ["assistant", "tool"],  # Filter for assistant and tool messages
                None,
            )
            duration = time.time() - start
            print(f"Parse took {duration:.3f}s")

    assert isinstance(result, Transcript)
    assert result.id == "what id?"
    assert result.source_uri == file_path
    # Check that we got what we asked for and only what we asked for
    role_counts = Counter(msg.role for msg in result.messages)
    assert len(role_counts) == 2
    assert role_counts["assistant"] == 887
    assert role_counts["tool"] == 923
    assert not result.events
