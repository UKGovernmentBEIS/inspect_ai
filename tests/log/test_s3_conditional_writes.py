"""
Tests for S3 conditional writes using ETags.

Tests the new include_etag and if_match_etag parameters for
read_eval_log and write_eval_log functions.
"""

import os
import tempfile
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

from inspect_ai._util.error import ConcurrentModificationError
from inspect_ai.log import read_eval_log, write_eval_log


@pytest.fixture
def sample_log():
    """Fixture to provide a sample log for testing."""
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None
    return log


@pytest.fixture
def temp_dir():
    """Fixture to create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


def test_local_file_etag_is_none(sample_log, temp_dir):
    """Test that include_etag=True returns None for local files."""
    # Write to local file
    local_path = temp_dir / "test.json"
    write_eval_log(sample_log, local_path)

    # Read with include_etag=True - should get None for local files
    log, etag = read_eval_log(local_path, include_etag=True)

    assert etag is None
    assert log.eval.task == sample_log.eval.task

    # Also test with eval format
    eval_path = temp_dir / "test.eval"
    write_eval_log(sample_log, eval_path)

    log, etag = read_eval_log(eval_path, include_etag=True)
    assert etag is None
    assert log.eval.task == sample_log.eval.task


def test_s3_etag_retrieval(sample_log, mock_s3):
    """Test that include_etag=True returns proper ETag from S3."""
    # Write to S3
    s3_path = "s3://test-bucket/test_etag.json"
    write_eval_log(sample_log, s3_path)

    # Read with include_etag=True - should get an ETag
    log, etag = read_eval_log(s3_path, include_etag=True)

    assert etag is not None
    assert isinstance(etag, str)
    assert len(etag) > 0
    assert log.eval.task == sample_log.eval.task

    # ETag should be consistent across reads (same content = same ETag)
    log2, etag2 = read_eval_log(s3_path, include_etag=True)
    assert etag == etag2
    assert log.model_dump_json() == log2.model_dump_json()


def test_s3_etag_eval_format(sample_log, mock_s3):
    """Test ETag retrieval with .eval format."""
    # Write to S3 in eval format
    s3_path = "s3://test-bucket/test_etag.eval"
    write_eval_log(sample_log, s3_path, format="eval")

    # Read with include_etag=True
    log, etag = read_eval_log(s3_path, include_etag=True, format="eval")

    assert etag is not None
    assert isinstance(etag, str)
    assert log.eval.task == sample_log.eval.task


def test_s3_conditional_write_success(sample_log, mock_s3):
    """Test successful conditional write when ETag matches."""
    s3_path = "s3://test-bucket/test_conditional.json"

    # Initialize metadata if None
    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    # Initial write
    write_eval_log(sample_log, s3_path)

    # Read with ETag
    log, etag = read_eval_log(s3_path, include_etag=True)

    # Modify the log
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["test"] = "conditional_write"

    # Conditional write with matching ETag should succeed
    write_eval_log(log, s3_path, if_match_etag=etag)

    # Verify the write succeeded
    updated_log = read_eval_log(s3_path)
    assert updated_log.eval.metadata is not None
    assert updated_log.eval.metadata["test"] == "conditional_write"


def test_s3_conditional_write_conflict(sample_log, mock_s3):
    """Test that conditional write fails when ETag doesn't match."""
    s3_path = "s3://test-bucket/test_conflict.json"

    # Initialize metadata if None
    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    # Initial write
    write_eval_log(sample_log, s3_path)

    # Read with ETag
    log, etag = read_eval_log(s3_path, include_etag=True)

    # Simulate another process modifying the file
    # (directly update S3 to change the ETag)
    another_log = read_eval_log(s3_path)
    if another_log.eval.metadata is None:
        another_log.eval.metadata = {}
    another_log.eval.metadata["modified_by"] = "another_process"
    write_eval_log(another_log, s3_path)

    # Now try conditional write with old ETag - should fail
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["modified_by"] = "original_process"

    with pytest.raises(ConcurrentModificationError) as exc_info:
        write_eval_log(log, s3_path, if_match_etag=etag)

    # Verify error contains expected ETag
    assert etag in str(exc_info.value)

    # Verify the file wasn't overwritten
    current_log = read_eval_log(s3_path)
    assert current_log.eval.metadata is not None
    assert current_log.eval.metadata["modified_by"] == "another_process"


def test_s3_concurrent_modification_scenario(sample_log, mock_s3):
    """Test realistic concurrent modification scenario with two parties."""
    s3_path = "s3://test-bucket/test_concurrent.json"

    # Initial state - initialize metadata properly
    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}
    sample_log.eval.metadata.update({"counter": 0, "history": []})
    write_eval_log(sample_log, s3_path)

    # Party A reads
    log_a, etag_a = read_eval_log(s3_path, include_etag=True)

    # Party B reads (same initial state)
    log_b, etag_b = read_eval_log(s3_path, include_etag=True)

    assert etag_a == etag_b  # Both have same initial version

    # Party A modifies and writes first
    if log_a.eval.metadata is None:
        log_a.eval.metadata = {}
    log_a.eval.metadata["counter"] = 1
    log_a.eval.metadata["history"] = log_a.eval.metadata.get("history", []) + [
        "Party A"
    ]
    write_eval_log(log_a, s3_path, if_match_etag=etag_a)

    # Party B tries to write with stale ETag
    if log_b.eval.metadata is None:
        log_b.eval.metadata = {}
    log_b.eval.metadata["counter"] = 1
    log_b.eval.metadata["history"] = log_b.eval.metadata.get("history", []) + [
        "Party B"
    ]

    with pytest.raises(ConcurrentModificationError):
        write_eval_log(log_b, s3_path, if_match_etag=etag_b)

    # Party B recovers: read fresh, merge, and retry
    current_log, current_etag = read_eval_log(s3_path, include_etag=True)
    assert current_log.eval.metadata is not None
    assert current_log.eval.metadata["counter"] == 1
    assert current_log.eval.metadata["history"] == ["Party A"]

    # Merge B's changes with A's
    current_log.eval.metadata["counter"] = 2
    current_log.eval.metadata["history"].append("Party B")
    write_eval_log(current_log, s3_path, if_match_etag=current_etag)

    # Verify final state has both updates
    final_log = read_eval_log(s3_path)
    assert final_log.eval.metadata is not None
    assert final_log.eval.metadata["counter"] == 2
    assert final_log.eval.metadata["history"] == ["Party A", "Party B"]


def test_s3_conditional_write_eval_format(sample_log, mock_s3):
    """Test conditional writes with .eval format."""
    s3_path = "s3://test-bucket/test_conditional.eval"

    # Initialize metadata if None
    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    # Initial write in eval format
    write_eval_log(sample_log, s3_path, format="eval")

    # Read with ETag
    log, etag = read_eval_log(s3_path, include_etag=True, format="eval")

    # Modify and write conditionally
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["test"] = "eval_format_conditional"
    write_eval_log(log, s3_path, if_match_etag=etag, format="eval")

    # Verify success
    updated_log = read_eval_log(s3_path, format="eval")
    assert updated_log.eval.metadata is not None
    assert updated_log.eval.metadata["test"] == "eval_format_conditional"


def test_s3_etag_changes_after_modification(sample_log, mock_s3):
    """Test that ETag changes when file content changes."""
    s3_path = "s3://test-bucket/test_etag_change.json"

    # Initial write
    write_eval_log(sample_log, s3_path)
    log1, etag1 = read_eval_log(s3_path, include_etag=True)

    # Modify and write
    log1.eval.metadata = {"version": 2}
    write_eval_log(log1, s3_path)

    # Read again - ETag should be different
    log2, etag2 = read_eval_log(s3_path, include_etag=True)

    assert etag1 != etag2  # ETag changed
    assert log2.eval.metadata["version"] == 2  # Content updated


def test_conditional_write_without_etag_succeeds(sample_log, mock_s3):
    """Test that write without if_match_etag always succeeds (backward compatibility)."""
    s3_path = "s3://test-bucket/test_unconditional.json"

    # Initial write
    write_eval_log(sample_log, s3_path)

    # Read (could include etag, but we ignore it)
    log, etag = read_eval_log(s3_path, include_etag=True)

    # Another process modifies
    another_log = read_eval_log(s3_path)
    another_log.eval.metadata = {"modified": "by_another"}
    write_eval_log(another_log, s3_path)

    # Unconditional write should still succeed (overwrites)
    log.eval.metadata = {"modified": "unconditionally"}
    write_eval_log(log, s3_path)  # No if_match_etag

    # Verify it overwrote
    final_log = read_eval_log(s3_path)
    assert final_log.eval.metadata["modified"] == "unconditionally"


def test_s3_conditional_write_with_boto_directly(sample_log, mock_s3):
    """Test S3 conditional write mechanics using boto3 directly to verify behavior."""
    s3_path = "s3://test-bucket/test_boto.json"

    # Write initial file
    write_eval_log(sample_log, s3_path)

    # Get S3 client
    s3_client = boto3.client("s3")

    # Get object and its ETag
    response = s3_client.get_object(Bucket="test-bucket", Key="test_boto.json")
    original_etag = response["ETag"].strip('"')

    # Try to put with matching ETag (should succeed)
    try:
        s3_client.put_object(
            Bucket="test-bucket",
            Key="test_boto.json",
            Body=b'{"test": "data"}',
            IfMatch=f'"{original_etag}"',
        )
    except ClientError:
        pytest.fail("Conditional write with matching ETag should succeed")

    # Try to put with old ETag (should fail)
    with pytest.raises(ClientError) as exc_info:
        s3_client.put_object(
            Bucket="test-bucket",
            Key="test_boto.json",
            Body=b'{"test": "data2"}',
            IfMatch=f'"{original_etag}"',
        )

    assert exc_info.value.response["Error"]["Code"] == "PreconditionFailed"


def test_concurrent_modification_error_attributes(sample_log, mock_s3):
    """Test that ConcurrentModificationError contains expected attributes."""
    s3_path = "s3://test-bucket/test_error_attrs.json"

    # Initialize metadata if None
    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    # Setup conflict scenario
    write_eval_log(sample_log, s3_path)
    log, etag = read_eval_log(s3_path, include_etag=True)

    # Cause conflict
    another_log = read_eval_log(s3_path)
    if another_log.eval.metadata is None:
        another_log.eval.metadata = {}
    another_log.eval.metadata["changed"] = True
    write_eval_log(another_log, s3_path)

    # Attempt conflicting write
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["my_change"] = True

    try:
        write_eval_log(log, s3_path, if_match_etag=etag)
        pytest.fail("Should have raised ConcurrentModificationError")
    except ConcurrentModificationError as e:
        # Verify error has expected attributes
        assert etag in str(e)
        assert "modified by another process" in str(e).lower()
        assert hasattr(e, "etag_expected")
        assert e.etag_expected == etag
