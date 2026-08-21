"""Regression tests for the S3/Azure auth-fallback helpers.

Covers `is_s3_auth_error` (cause-chain walk that refreshes the message at
every step), `should_suppress_remote_auth_error` (single dispatcher) and
`remote_auth_warning_hint` (returns either the Azure or S3 hint, or None
for unrecognised paths).
"""
from __future__ import annotations

from inspect_ai._util.azure import (
    azure_warning_hint,
    is_azure_path,
    is_s3_auth_error,
    is_s3_path,
    remote_auth_warning_hint,
    s3_warning_hint,
    should_suppress_remote_auth_error,
    should_suppress_s3_error,
)


def test_is_s3_path_matches_s3_scheme() -> None:
    assert is_s3_path("s3://bucket/prefix")
    assert is_s3_path("S3://Bucket/Prefix")
    assert not is_s3_path("abfs://container/path")
    assert not is_s3_path("./local/logs")


def test_is_s3_auth_error_matches_top_level_message() -> None:
    err = OSError("Unable to locate credentials")
    assert is_s3_auth_error(err)
    err = OSError("An error occurred (ExpiredToken) when calling S3 operation")
    assert is_s3_auth_error(err)
    err = OSError("AccessDeniedException calling ListObjectsV2")
    assert is_s3_auth_error(err)


def test_is_s3_auth_error_walks_cause_chain() -> None:
    # The auth signal is buried in __cause__; the top-level OSError mentions
    # something else entirely. Regression for the bug where the walk only
    # re-evaluated `cls_name` but kept the top-level `msg` for every
    # iteration.
    inner = OSError("An error occurred (InvalidAccessKeyId) when calling S3")
    outer = OSError("probe failed")
    outer.__cause__ = inner
    assert is_s3_auth_error(outer)


def test_is_s3_auth_error_handles_context_chain() -> None:
    inner = OSError("Missing credentials in environment")
    outer = RuntimeError("Listing failed during probe")
    outer.__context__ = inner
    assert is_s3_auth_error(outer)


def test_is_s3_auth_error_respects_cycle() -> None:
    # Self-referential exceptions don't infinite-loop.
    a = OSError("Missing credentials")
    a.__cause__ = a  # cyc
    assert is_s3_auth_error(a) is True


def test_is_s3_auth_error_negative() -> None:
    assert is_s3_auth_error(OSError("network unreachable")) is False
    assert is_s3_auth_error(KeyError("rate limit")) is False


def test_should_suppress_s3_error_respects_path() -> None:
    err = OSError("ExpiredToken")
    assert should_suppress_s3_error("s3://bucket/prefix", err) is True
    # A local error with the same message must NOT be suppressed - only S3
    # paths grant credential forgiveness.
    assert should_suppress_s3_error("./logs", err) is False


def test_should_suppress_remote_auth_error_dispatch() -> None:
    azure_err = OSError(
        "Server failed to authenticate the request"
    )
    s3_err = OSError("ExpiredToken when calling S3")
    other_err = OSError("network unreachable")

    assert (
        should_suppress_remote_auth_error("az://account/container", azure_err)
        is True
    )
    assert (
        should_suppress_remote_auth_error("s3://bucket/prefix", s3_err)
        is True
    )
    # Genuinely negative: not Azure, not S3, not an auth error -> not suppressed
    assert (
        should_suppress_remote_auth_error("./local/logs", other_err) is False
    )
    # Auth-shaped message on a local path still must not be downgraded -
    # this is what the S3 helper's path gate prevents.
    assert (
        should_suppress_remote_auth_error("./local/logs", s3_err) is False
    )


def test_remote_auth_warning_hint_dispatches_per_scheme() -> None:
    azure_err = OSError("Server failed to authenticate the request")
    s3_err = OSError("ExpiredToken")

    az_hint = remote_auth_warning_hint("az://acct/cont", azure_err)
    s3_hint = remote_auth_warning_hint("s3://bucket/p", s3_err)
    none_hint = remote_auth_warning_hint("./local", OSError("boom"))

    assert az_hint is not None and az_hint.startswith("Azure")
    assert s3_hint is not None and s3_hint.startswith("AWS")
    assert none_hint is None


def test_remote_auth_warning_hint_text_roundtrip() -> None:
    err = OSError("ExpiredToken when calling S3")
    s3_path = "s3://bucket/prefix"
    hint = remote_auth_warning_hint(s3_path, err)
    assert hint == s3_warning_hint(s3_path, err)


def test_azure_path_helper() -> None:
    assert is_azure_path("az://account/container")
    assert is_azure_path("abfss://account/container")
    assert not is_azure_path("s3://bucket")


def test_azure_warning_hint_distinct_from_s3() -> None:
    err = OSError("probe")
    assert azure_warning_hint("az://acct/c", err) != s3_warning_hint(
        "s3://bucket/p", err
    )
