"""Tests for the ACP upstream-disconnect log filter.

The upstream ``acp`` library logs at ERROR via ``logging.exception`` on
the root logger when its receive / send / main loops hit an exception
— including the BrokenPipeError / ConnectionResetError that fire on
every routine peer disconnect. The filter installed in
:mod:`_guards` drops those specific tracebacks while leaving every
other log record (including unrelated module errors and library
errors caused by *real* failures) untouched.
"""

from __future__ import annotations

import logging

import anyio

from inspect_ai.agent._acp._guards import (
    _AcpDisconnectFilter,
    install_acp_disconnect_log_filter,
)


def _make_record(message: str, exc: BaseException | None) -> logging.LogRecord:
    """Build a LogRecord that mirrors what ``logging.exception`` produces."""
    record = logging.LogRecord(
        name="root",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg=message,
        args=None,
        exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
    )
    return record


def test_filter_drops_main_loop_traceback_for_broken_pipe() -> None:
    filt = _AcpDisconnectFilter()
    record = _make_record(
        "Connection main loop failed", BrokenPipeError(32, "Broken pipe")
    )
    assert filt.filter(record) is False


def test_filter_drops_receive_loop_traceback_for_connection_reset() -> None:
    filt = _AcpDisconnectFilter()
    record = _make_record("Receive loop failed", ConnectionResetError())
    assert filt.filter(record) is False


def test_filter_drops_send_loop_traceback_for_anyio_broken_resource() -> None:
    filt = _AcpDisconnectFilter()
    record = _make_record("Send loop failed", anyio.BrokenResourceError())
    assert filt.filter(record) is False


def test_filter_keeps_main_loop_traceback_for_real_error() -> None:
    """A non-disconnect exception is a real failure — keep the traceback."""
    filt = _AcpDisconnectFilter()
    record = _make_record("Connection main loop failed", RuntimeError("bug in handler"))
    assert filt.filter(record) is True


def test_filter_passes_unrelated_messages_through() -> None:
    """Records whose message isn't on the suppression list are untouched.

    The filter sits on the root logger, so it sees every log record in
    the process. Anything that isn't one of the three known
    upstream-library messages must propagate normally — even when the
    exception happens to be in the disconnect set.
    """
    filt = _AcpDisconnectFilter()
    record = _make_record("some other error", BrokenPipeError())
    assert filt.filter(record) is True


def test_filter_passes_when_record_has_no_exc_info() -> None:
    """A log call without ``exc_info`` can't be classified — let it through."""
    filt = _AcpDisconnectFilter()
    record = _make_record("Receive loop failed", None)
    assert filt.filter(record) is True


def test_install_is_idempotent() -> None:
    """Multiple installs attach the filter only once.

    Long-running processes (eval sequences, test runs) re-enter the
    server start path; without dedup the root logger would accumulate
    redundant filters that each re-evaluate every log record.
    """
    install_acp_disconnect_log_filter()
    root = logging.getLogger()
    count_after_first = sum(
        1 for f in root.filters if isinstance(f, _AcpDisconnectFilter)
    )
    install_acp_disconnect_log_filter()
    count_after_second = sum(
        1 for f in root.filters if isinstance(f, _AcpDisconnectFilter)
    )
    assert count_after_first == 1
    assert count_after_second == 1


def test_installed_filter_suppresses_upstream_emission(
    caplog: object,
) -> None:
    """End-to-end: installed filter actually silences the upstream message.

    Exercises the integration path (root logger emit → filter chain
    → handler) so a future regression in install / filter attachment
    surfaces here, not just in the unit tests above.
    """
    install_acp_disconnect_log_filter()
    root = logging.getLogger()
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture(level=logging.DEBUG)
    root.addHandler(handler)
    try:
        try:
            raise BrokenPipeError(32, "Broken pipe")
        except BrokenPipeError:
            logging.exception("Receive loop failed")
        try:
            raise RuntimeError("real bug")
        except RuntimeError:
            logging.exception("Connection main loop failed")
    finally:
        root.removeHandler(handler)

    # The disconnect traceback is gone; the real-failure traceback is
    # preserved.
    assert "Receive loop failed" not in captured
    assert "Connection main loop failed" in captured
