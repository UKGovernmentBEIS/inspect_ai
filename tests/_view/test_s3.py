"""Unit tests for the S3 view helpers (issue #4914)."""

import pytest

from inspect_ai._view.s3 import (
    is_s3_path,
    s3_warning_hint,
    should_suppress_s3_error,
)


class TestIsS3Path:
    def test_s3_scheme(self) -> None:
        assert is_s3_path("s3://bucket/logs")

    def test_s3a_scheme(self) -> None:
        assert is_s3_path("s3a://bucket/logs")

    @pytest.mark.parametrize(
        "path",
        ["az://container/logs", "abfs://container/logs", "/local/path", "gs://bucket"],
    )
    def test_non_s3_paths(self, path: str) -> None:
        assert not is_s3_path(path)


class TestShouldSuppressS3Error:
    @pytest.mark.parametrize(
        "message",
        [
            # botocore ClientError str() embeds the camel-case code
            "An error occurred (AccessDenied) when calling the ListObjectsV2 operation: Access Denied",
            "An error occurred (InvalidAccessKeyId) when calling the ListObjectsV2 operation",
            "An error occurred (SignatureDoesNotMatch) when calling the ListObjectsV2 operation",
            "An error occurred (ExpiredToken) when calling the ListObjectsV2 operation: The provided token has expired",
            # botocore credential errors surface as plain messages
            "Unable to locate credentials",
            "No credentials were found for profile default",
            # s3fs raises bare PermissionError("Access Denied")
            "Access Denied",
            "Auth failure. Credentials were only partially specified.",
        ],
    )
    def test_auth_errors_are_suppressed_on_s3_paths(self, message: str) -> None:
        error = PermissionError(message)
        assert should_suppress_s3_error("s3://bucket/logs", error)

    def test_suppressed_on_s3a_scheme(self) -> None:
        assert should_suppress_s3_error(
            "s3a://bucket/logs", PermissionError("Access Denied")
        )

    def test_non_auth_error_is_not_suppressed(self) -> None:
        error = OSError("connection reset by peer")
        assert not should_suppress_s3_error("s3://bucket/logs", error)

    def test_auth_error_is_not_suppressed_on_non_s3_path(self) -> None:
        error = PermissionError("Access Denied")
        assert not should_suppress_s3_error("/local/logs", error)


class TestS3WarningHint:
    def test_hint_includes_path_and_original_error(self) -> None:
        error = PermissionError("Access Denied")
        hint = s3_warning_hint("s3://bucket/logs", error)
        assert "s3://bucket/logs" in hint
        assert "Access Denied" in hint
        assert "aws sts get-caller-identity" in hint
