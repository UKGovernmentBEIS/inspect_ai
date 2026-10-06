"""Tests for the shared tool-execution helpers.

These helpers are consumed by both the model tool path and the human agent
tool path (human_cli tools=...), so the same exception or result produces
identical classification, truncation, and content handling on both. The
parametrized zoos here are the shared contract: classified exceptions are
recoverable and unclassified (None) exceptions fail the sample. The
fail-the-sample disposition for unclassified exceptions is agreed for both
paths but is exercised here, and by the model path's own tests, only for
the model path; #3053's corresponding caller change and tests for the
human agent path remain outstanding.
"""

import sys

import anyio
import pytest

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError, TerminateTaskError
from inspect_ai.model._call_tools import (
    classify_tool_exception,
    resolve_tool_content,
    tool_call_error,
)
from inspect_ai.tool import ToolError
from inspect_ai.tool._tool import ToolApprovalError, ToolParsingError
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.events import SandboxTimeoutError
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from inspect_ai.util._sandbox.service import raise_if_control_flow

# ---------------------------------------------------------------------------
# tool_call_error (single classification implementation)
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
    mapped = tool_call_error(ex, "some_tool")
    assert mapped is not None
    assert mapped.error.type == expected_type
    assert expected_in_message in mapped.error.message


def test_timeout_with_truncated_output_carries_partial_result():
    mapped = tool_call_error(
        SandboxTimeoutError("timed out", truncated_output="partial"), "some_tool"
    )
    assert mapped is not None
    assert mapped.result == "partial"


def test_timeout_without_truncated_output_has_no_partial_result():
    mapped = tool_call_error(TimeoutError(), "some_tool")
    assert mapped is not None
    assert mapped.result is None


def test_output_limit_classified_with_partial_result():
    mapped = tool_call_error(
        OutputLimitExceededError("1 KiB", "partial output"), "some_tool"
    )
    assert mapped is not None
    assert mapped.error.type == "limit"
    assert mapped.result == "partial output"


def test_output_limit_with_no_truncated_output_still_has_empty_string_result():
    # deliberately "" rather than None here: a limit-truncated result of
    # zero bytes is a known ("no output") partial result, not "no partial
    # result available" — see the comment at this branch in tool_call_error.
    mapped = tool_call_error(OutputLimitExceededError("1 KiB", ""), "some_tool")
    assert mapped is not None
    assert mapped.result == ""


def test_unexpected_exception_unclassified():
    assert tool_call_error(RuntimeError("boom"), "some_tool") is None


def test_terminate_errors_unclassified():
    # control flow: callers handle disposition (model fails the sample,
    # human propagates through the service boundary)
    assert tool_call_error(TerminateSampleError("kill"), "t") is None
    assert tool_call_error(TerminateTaskError("kill"), "t") is None


def test_other_value_errors_unclassified():
    # only embedded-null-byte ValueErrors are tool errors; other ValueErrors
    # are unexpected — the classifier stays policy-free and returns None
    # (the model call site applies its historical immediate-rethrow itself)
    assert tool_call_error(ValueError("unrelated"), "some_tool") is None


# ---------------------------------------------------------------------------
# classify_tool_exception (compatibility adapter for #3053)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ex",
    [
        TimeoutError(),
        SandboxTimeoutError("timed out", truncated_output="partial"),
        UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte"),
        ValueError("embedded null byte"),
        SandboxUnavailableError("container gone"),
        PermissionError(13, "Permission denied", "/etc/shadow"),
        FileNotFoundError(2, "No such file", "missing.txt"),
        IsADirectoryError(21, "Is a directory", "/tmp"),
        OutputLimitExceededError("1 KiB", "partial output"),
        OutputLimitExceededError("1 KiB", ""),
        LimitExceededError("token", value=1001, limit=1000),
        ToolParsingError("bad args"),
        ToolApprovalError("rejected"),
        ToolError("expected failure"),
    ],
)
def test_adapter_matches_canonical_error_and_translates_sentinel(ex):
    """classify_tool_exception() must not diverge from tool_call_error().

    It is a thin adapter, not a second classification implementation: same
    error for every case, and result translated only at the `None` <-> `""`
    sentinel (a `""` result on the canonical side, e.g. from
    OutputLimitExceededError with no captured output, passes through
    unchanged rather than becoming a second "no result" case).
    """
    mapped = tool_call_error(ex, "some_tool")
    classified = classify_tool_exception(ex, "some_tool")
    assert mapped is not None
    assert classified is not None
    assert classified.error == mapped.error
    assert classified.result == (mapped.result if mapped.result is not None else "")


@pytest.mark.parametrize(
    "ex",
    [RuntimeError("boom"), TerminateSampleError("kill"), TerminateTaskError("kill")],
)
def test_adapter_unclassified_matches_canonical(ex):
    assert tool_call_error(ex, "some_tool") is None
    assert classify_tool_exception(ex, "some_tool") is None


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
        raise TerminateSampleError("kill")

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        group: Exception | None = None
    except Exception as ex:
        group = ex

    assert group is not None
    with pytest.raises(TerminateSampleError):
        raise_if_control_flow(group)


def test_terminate_found_in_mixed_group():
    # a mixed group must not hide a termination behind an ordinary sibling
    # (first-leaf unwrapping missed it depending on flattening order)
    group = ExceptionGroup(
        "mixed", [RuntimeError("noise"), TerminateSampleError("kill")]
    )
    with pytest.raises(TerminateSampleError):
        raise_if_control_flow(group)


def test_task_terminate_not_routed():
    # TerminateTaskError has no task-boundary consumer in the sample
    # runner, so the service protocol deliberately excludes it
    raise_if_control_flow(TerminateTaskError("kill"))  # no-op


def _fake_service(method, monkeypatch, responses: list):
    """A SandboxService whose sandbox I/O is faked, dispatching for real.

    _handle_request runs its actual parse/dispatch/error-handling code —
    including the outer except that previously recaught re-raised
    terminations — with only the sandbox exec and response write faked.
    """
    import json as json_module

    from inspect_ai.util._sandbox.service import SandboxService
    from inspect_ai.util._subprocess import ExecResult

    service = SandboxService.__new__(SandboxService)
    service._name = "svc"
    service._methods = {"boom": method}
    service._requests_dir = "/req"
    service._in_flight = set()

    request_json = json_module.dumps({"id": "r1", "method": "boom", "params": {}})

    async def fake_exec(cmd, **kwargs):
        return ExecResult(success=True, returncode=0, stdout=request_json, stderr="")

    async def fake_write_response(request_file, request_id, result, error=None):
        responses.append((result, error))

    async def fake_remove(request_file):
        pass

    monkeypatch.setattr(service, "_exec", fake_exec)
    monkeypatch.setattr(service, "_write_response", fake_write_response)
    monkeypatch.setattr(service, "_remove_request_file", fake_remove)
    return service


@pytest.mark.anyio
async def test_terminate_propagates_through_real_handler(monkeypatch):
    """_handle_request's own outer handler must not recatch the re-raise.

    The inner control-flow branch answers the RPC then re-raises; the
    outer except Exception previously caught it immediately and logged
    it as an ordinary failure, so nothing ever terminated.
    """
    responses: list = []

    async def method() -> str:
        raise TerminateSampleError("kill")

    service = _fake_service(method, monkeypatch, responses)
    with pytest.raises(TerminateSampleError):
        await service._handle_request_tracked("/req/r1.json", "r1")

    # the RPC was answered exactly once before propagation
    assert len(responses) == 1
    assert responses[0][1] is not None and "Terminating" in responses[0][1]


@pytest.mark.anyio
async def test_grouped_terminate_answers_rpc_then_propagates(monkeypatch):
    """A grouped termination still answers the RPC exactly once.

    A method exiting with an ExceptionGroup containing the termination
    previously propagated before _write_response() ran — the sandbox
    client polled forever for a response that never came.
    """
    responses: list = []

    async def method() -> str:
        raise ExceptionGroup(
            "mixed", [RuntimeError("noise"), TerminateSampleError("kill")]
        )

    service = _fake_service(method, monkeypatch, responses)
    with pytest.raises(TerminateSampleError):
        await service._handle_request_tracked("/req/r1.json", "r1")

    assert len(responses) == 1
    assert responses[0][1] is not None and "Terminating" in responses[0][1]


@pytest.mark.anyio
async def test_ordinary_method_errors_still_swallowed(monkeypatch):
    responses: list = []

    async def method() -> str:
        raise RuntimeError("ordinary failure")

    service = _fake_service(method, monkeypatch, responses)
    await service._handle_request_tracked("/req/r1.json", "r1")  # no raise
    assert len(responses) == 1
    assert responses[0][1] is not None and "ordinary failure" in responses[0][1]


def test_terminate_detected_as_explicit_cause():
    """An exception raised from a termination must surface it.

    Explicit wrapping preserves the termination as __cause__; failing to
    follow it meant an author who deliberately chained it lost the
    termination while implicit context surfaced one — inverted intent.
    """
    terminate = TerminateSampleError("kill")
    try:
        raise RuntimeError("wrapper") from terminate
    except RuntimeError as ex:
        wrapped = ex
    with pytest.raises(TerminateSampleError):
        raise_if_control_flow(wrapped)


def test_terminate_sticky_across_context():
    """Termination is sticky: suppress-then-raise still terminates.

    Deliberate protocol (fail-safe direction): once a termination has
    been raised anywhere in the causal history of the escaping
    exception, it propagates. The only way to suppress a termination is
    to handle it and return normally. This is also what rescues a
    termination when a response write fails mid-handling.
    """
    try:
        try:
            raise TerminateSampleError("kill")
        except TerminateSampleError:
            raise RuntimeError("suppressor")  # noqa: B904 — deliberately implicit context, not chained, to test that path
    except RuntimeError as ex:
        chained = ex
    with pytest.raises(TerminateSampleError):
        raise_if_control_flow(chained)


def test_ordinary_exceptions_not_reraised():
    raise_if_control_flow(RuntimeError("boom"))  # no-op
    raise_if_control_flow(ValueError("boom"))  # no-op
