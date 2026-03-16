import os
import tempfile
from pathlib import Path

import pytest

from inspect_ai._util.error import WriteConflictError
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


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_returns_no_etag_for_local_path(sample_log, temp_dir, format):
    """Test that ETag is None for local files in different formats."""
    local_path = temp_dir / f"test.{format}"
    write_eval_log(sample_log, local_path)

    log = read_eval_log(local_path)

    assert log.etag is None
    assert log.eval.task == sample_log.eval.task


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_returns_etag_for_s3_path(sample_log, mock_s3, format):
    """Test that ETag is populated when reading from S3 in different formats."""
    log_path = f"s3://test-bucket/test_etag.{format}"
    write_eval_log(sample_log, log_path)

    log = read_eval_log(log_path)

    assert log.etag is not None
    assert isinstance(log.etag, str)
    assert len(log.etag) > 0
    assert log.eval.task == sample_log.eval.task

    # ETag should be the same for the same content
    log2 = read_eval_log(log_path)
    assert log.etag == log2.etag
    assert log.model_dump_json() == log2.model_dump_json()


@pytest.mark.parametrize("format", ["json", "eval"])
def test_s3_conditional_write_success(sample_log, mock_s3, format):
    """Test successful conditional write when ETag matches in different formats."""
    log_path = f"s3://test-bucket/test_conditional.{format}"

    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    write_eval_log(sample_log, log_path)

    log = read_eval_log(log_path)

    # Modify the log
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["test"] = f"{format}_format_conditional"

    # conditional write with matching ETag should succeed
    write_eval_log(log, log_path, if_match_etag=log.etag)

    # verify the write succeeded
    new_log = read_eval_log(log_path)
    assert new_log.eval.metadata is not None
    assert new_log.eval.metadata["test"] == f"{format}_format_conditional"


def test_s3_conditional_write_error(sample_log, mock_s3):
    """Test that conditional write errors when ETag doesn't match."""
    log_path = "s3://test-bucket/test_conflict.json"

    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}

    # Initial write
    write_eval_log(sample_log, log_path)

    log = read_eval_log(log_path)

    # simulate another process modifying the file
    # update to change the ETag
    log2 = read_eval_log(log_path)
    if log2.eval.metadata is None:
        log2.eval.metadata = {}
    log2.eval.metadata["modified_by"] = "another_process"
    write_eval_log(log2, log_path)

    # try conditional write with old ETag
    if log.eval.metadata is None:
        log.eval.metadata = {}
    log.eval.metadata["modified_by"] = "original_process"

    with pytest.raises(WriteConflictError) as exc_info:
        write_eval_log(log, log_path, if_match_etag=log.etag)

    # verify error contains expected information
    assert log.etag in str(exc_info.value)
    assert "modified by another process" in str(exc_info.value).lower()

    # verify the file wasn't overwritten
    current_log = read_eval_log(log_path)
    assert current_log.eval.metadata is not None
    assert current_log.eval.metadata["modified_by"] == "another_process"


def test_s3_concurrent_modification_scenario(sample_log, mock_s3):
    """Test realistic concurrent modification scenario with two parties."""
    log_path = "s3://test-bucket/test_concurrent.json"

    if sample_log.eval.metadata is None:
        sample_log.eval.metadata = {}
    sample_log.eval.metadata.update({"counter": 0, "history": []})
    write_eval_log(sample_log, log_path)

    # party 1 reads
    log1 = read_eval_log(log_path)

    # party 2 reads
    log2 = read_eval_log(log_path)

    assert log1.etag == log2.etag  # both have same initial version

    # party 1 modifies and writes first
    if log1.eval.metadata is None:
        log1.eval.metadata = {}
    log1.eval.metadata["counter"] = 1
    log1.eval.metadata["history"] = log1.eval.metadata.get("history", []) + ["Party A"]
    write_eval_log(log1, log_path, if_match_etag=log1.etag)

    # party 2 tries to write with old ETag
    if log2.eval.metadata is None:
        log2.eval.metadata = {}
    log2.eval.metadata["counter"] = 1
    log2.eval.metadata["history"] = log2.eval.metadata.get("history", []) + ["Party B"]

    with pytest.raises(WriteConflictError):
        write_eval_log(log2, log_path, if_match_etag=log2.etag)

    # party 2 reads again and retries
    current_log = read_eval_log(log_path)
    assert current_log.eval.metadata is not None
    assert current_log.eval.metadata["counter"] == 1
    assert current_log.eval.metadata["history"] == ["Party A"]

    # add party 2's changes to party 1's
    current_log.eval.metadata["counter"] = 2
    current_log.eval.metadata["history"].append("Party B")
    write_eval_log(current_log, log_path, if_match_etag=current_log.etag)

    # verify final state has both updates
    new_log = read_eval_log(log_path)
    assert new_log.eval.metadata is not None
    assert new_log.eval.metadata["counter"] == 2
    assert new_log.eval.metadata["history"] == ["Party A", "Party B"]


def test_s3_etag_changes_after_modification(sample_log, mock_s3):
    """Test that ETag changes when content changes."""
    log_path = "s3://test-bucket/test_etag_change.json"

    write_eval_log(sample_log, log_path)
    log1 = read_eval_log(log_path)

    # update
    log1.eval.metadata = {"version": 2}
    write_eval_log(log1, log_path)

    # read again
    log2 = read_eval_log(log_path)

    assert log1.etag != log2.etag  # the ETag has changed
    assert log2.eval.metadata["version"] == 2  # content has changed


@pytest.mark.parametrize("format", ["json", "eval"])
def test_etag_consistent_between_full_and_header_only_read(sample_log, mock_s3, format):
    """Test that ETag format is consistent between full read and header-only read.

    Reproduces a bug where header_only=True returns ETag with surrounding quotes
    (e.g. '"abc123"') while header_only=False returns it without quotes ('abc123').
    """
    log_path = f"s3://test-bucket/test_etag_consistency.{format}"
    write_eval_log(sample_log, log_path)

    full_log = read_eval_log(log_path, header_only=False)
    header_log = read_eval_log(log_path, header_only=True)

    assert full_log.etag is not None
    assert header_log.etag is not None

    # ETags should be identical — no surrounding quotes on either
    assert full_log.etag == header_log.etag, (
        f"ETag mismatch: full read returned {full_log.etag!r}, "
        f"header-only read returned {header_log.etag!r}"
    )

    # Neither should have surrounding quotes
    assert not full_log.etag.startswith('"'), (
        f"Full read ETag has surrounding quotes: {full_log.etag!r}"
    )
    assert not header_log.etag.startswith('"'), (
        f"Header-only read ETag has surrounding quotes: {header_log.etag!r}"
    )


def test_conditional_write_without_etag_succeeds(sample_log, mock_s3):
    """Test that write without if_match_etag always succeeds (backward compatibility)."""
    log_path = "s3://test-bucket/test_unconditional.json"

    write_eval_log(sample_log, log_path)

    log = read_eval_log(log_path)

    # another process updates
    log2 = read_eval_log(log_path)
    log2.eval.metadata = {"modified": "by_another"}
    write_eval_log(log2, log_path)

    # unconditional write should still succeed (overwrites)
    log.eval.metadata = {"modified": "unconditionally"}
    write_eval_log(log, log_path)

    # verify it overwrote
    new_log = read_eval_log(log_path)
    assert new_log.eval.metadata["modified"] == "unconditionally"
