"""Tests for the shared tool-execution helpers.

These helpers are consumed by both the model tool path and the human agent
tool path (human_cli tools=...), so the same exception or result produces
identical classification, truncation, and content handling on both. The
parametrized zoos here are the shared contract; path-specific dispositions
(fail-the-sample vs surface-and-continue) are tested with each path.
"""

import anyio
import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError, TerminateTaskError
from inspect_ai.model._call_tools import (
    classify_tool_exception,
    resolve_tool_content,
)
from inspect_ai.tool import ToolError
from inspect_ai.tool._tool import ToolApprovalError, ToolParsingError
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from inspect_ai.util._sandbox.service import raise_if_control_flow

# ---------------------------------------------------------------------------
# classify_tool_exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ex,expected_type,expected_in_message",
    [
        (TimeoutError(), "timeout", "timed out"),
        (
            UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte"),
            "unicode_decode",
            "invalid start byte",
        ),
        (ValueError("embedded null byte"), "parsing", "null byte"),
        (SandboxUnavailableError("container gone"), "sandbox_unavailable", "gone"),
        (
            PermissionError(13, "Permission denied", "/etc/shadow"),
            "permission",
            "shadow",
        ),
        (
            FileNotFoundError(2, "No such file", "missing.txt"),
            "file_not_found",
            "missing.txt",
        ),
        (IsADirectoryError(21, "Is a directory", "/tmp"), "is_a_directory", "/tmp"),
        (
            LimitExceededError("token", value=1001, limit=1000),
            "limit",
            "token",
        ),
        (ToolParsingError("bad args"), "parsing", "bad args"),
        (ToolApprovalError("rejected"), "approval", "rejected"),
        (ToolError("expected failure"), "unknown", "expected failure"),
    ],
)
def test_classification_zoo(ex, expected_type, expected_in_message):
    classified = classify_tool_exception(ex, "some_tool")
    assert classified is not None
    assert classified.error.type == expected_type
    assert expected_in_message in classified.error.message


def test_output_limit_classified_with_partial_result():
    classified = classify_tool_exception(
        OutputLimitExceededError("1 KiB", "partial output"), "some_tool"
    )
    assert classified is not None
    assert classified.error.type == "limit"
    assert classified.result == "partial output"


def test_unexpected_exception_unclassified():
    assert classify_tool_exception(RuntimeError("boom"), "some_tool") is None


def test_terminate_errors_unclassified():
    # control flow: callers handle disposition (model fails the sample,
    # human propagates through the service boundary)
    assert classify_tool_exception(TerminateSampleError("kill"), "t") is None
    assert classify_tool_exception(TerminateTaskError("kill"), "t") is None


def test_other_value_errors_reraise():
    # historical model-path behavior: only embedded-null-byte ValueErrors
    # are tool errors; anything else is not swallowed into a classification
    with pytest.raises(ValueError, match="unrelated"):
        classify_tool_exception(ValueError("unrelated"), "some_tool")


# ---------------------------------------------------------------------------
# resolve_tool_content
# ---------------------------------------------------------------------------


def test_content_list_passes_through_untruncated():
    # structured content is never string-truncated — images and text survive
    result = [ContentText(text="x" * (64 * 1024)), ContentImage(image="b64")]
    content, truncated = resolve_tool_content(result, "t", None)
    assert content is result
    assert truncated is None


def test_single_content_wrapped_in_list():
    item = ContentText(text="hello")
    content, truncated = resolve_tool_content(item, "t", None)
    assert content == [item]
    assert truncated is None


def test_oversize_string_truncated():
    content, truncated = resolve_tool_content("x" * (64 * 1024), "t", 1024)
    assert isinstance(content, str)
    assert len(content) < 64 * 1024
    assert truncated is not None
    assert truncated[0] == 64 * 1024


def test_scalar_stringified():
    content, truncated = resolve_tool_content(42, "t", None)
    assert content == "42"
    assert truncated is None


# ---------------------------------------------------------------------------
# raise_if_control_flow
# ---------------------------------------------------------------------------


def test_terminate_reraised_directly():
    with pytest.raises(TerminateSampleError):
        raise_if_control_flow(TerminateSampleError("kill"))


@pytest.mark.anyio
async def test_terminate_reraised_from_task_group():
    # anyio task groups wrap child exceptions in an ExceptionGroup — the
    # service's error handling must unwrap before matching
    async def child() -> None:
        raise TerminateTaskError("kill")

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        group: Exception | None = None
    except Exception as ex:
        group = ex

    assert group is not None
    with pytest.raises(TerminateTaskError):
        raise_if_control_flow(group)


def test_ordinary_exceptions_not_reraised():
    raise_if_control_flow(RuntimeError("boom"))  # no-op
    raise_if_control_flow(ValueError("boom"))  # no-op
