import os

import boto3
import pytest

from inspect_ai.log import (
    read_eval_log,
    read_eval_log_sample,
    read_eval_log_sample_summaries,
    write_eval_log,
)


@pytest.fixture
def mock_s3_versioning(mock_s3):
    """Extend mock_s3 fixture to enable versioning on the test bucket."""
    s3_client = boto3.client("s3")
    s3_client.put_bucket_versioning(
        Bucket="test-bucket",
        VersioningConfiguration={"Status": "Enabled"},
    )
    yield


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_s3_version_id(mock_s3_versioning, format):
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None

    log_path = f"s3://test-bucket/versioned_log.{format}"

    log.eval.metadata = {"version": 1}
    write_eval_log(log, log_path)

    s3_client = boto3.client("s3")
    versions = s3_client.list_object_versions(
        Bucket="test-bucket", Prefix=f"versioned_log.{format}"
    )
    version_1 = versions["Versions"][0]["VersionId"]

    log.eval.metadata = {"version": 2}
    write_eval_log(log, log_path)

    log_version_path = f"{log_path}?versionId={version_1}"
    log_version = read_eval_log(log_version_path)
    assert log_version.eval.metadata is not None
    assert log_version.eval.metadata["version"] == 1


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_header_only_s3_version_id(mock_s3_versioning, format):
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None

    log_path = f"s3://test-bucket/versioned_header.{format}"

    log.eval.metadata = {"version": 1}
    write_eval_log(log, log_path)

    s3_client = boto3.client("s3")
    versions = s3_client.list_object_versions(
        Bucket="test-bucket", Prefix=f"versioned_header.{format}"
    )
    version_1 = versions["Versions"][0]["VersionId"]

    log.eval.metadata = {"version": 2}
    write_eval_log(log, log_path)

    log_version_path = f"{log_path}?versionId={version_1}"
    log_version = read_eval_log(log_version_path, header_only=True)
    assert log_version.eval.metadata is not None
    assert log_version.eval.metadata["version"] == 1
    assert log_version.samples is None


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_sample_s3_version_id(mock_s3_versioning, format):
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None

    log_path = f"s3://test-bucket/versioned_sample.{format}"

    log.eval.metadata = {"version": 1}
    write_eval_log(log, log_path)

    s3_client = boto3.client("s3")
    versions = s3_client.list_object_versions(
        Bucket="test-bucket", Prefix=f"versioned_sample.{format}"
    )
    version_1 = versions["Versions"][0]["VersionId"]

    assert log.samples
    sample_id = log.samples[0].id

    log.eval.metadata = {"version": 2}
    write_eval_log(log, log_path)

    log_version_path = f"{log_path}?versionId={version_1}"
    sample = read_eval_log_sample(log_version_path, id=sample_id)
    assert sample.id == sample_id


@pytest.mark.parametrize("format", ["json", "eval"])
def test_write_eval_log_rejects_version_id(mock_s3_versioning, format):
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None

    versioned_path = f"s3://test-bucket/versioned_write.{format}?versionId=abc123"
    with pytest.raises(ValueError, match="query parameters"):
        write_eval_log(log, versioned_path)


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_eval_log_sample_summaries_s3_version_id(mock_s3_versioning, format):
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None

    log_path = f"s3://test-bucket/versioned_summaries.{format}"

    log.eval.metadata = {"version": 1}
    write_eval_log(log, log_path)

    s3_client = boto3.client("s3")
    versions = s3_client.list_object_versions(
        Bucket="test-bucket", Prefix=f"versioned_summaries.{format}"
    )
    version_1 = versions["Versions"][0]["VersionId"]

    log.eval.metadata = {"version": 2}
    write_eval_log(log, log_path)

    log_version_path = f"{log_path}?versionId={version_1}"
    summaries = read_eval_log_sample_summaries(log_version_path)
    assert summaries
