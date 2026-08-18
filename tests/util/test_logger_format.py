import io
import json
import sys
from logging import INFO, LogRecord
from types import TracebackType
from typing import Any

import pytest

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import LogHandler, logger_display_format


def log_record(
    message: str = "log message",
    exc_info: tuple[type[BaseException], BaseException, TracebackType] | None = None,
) -> LogRecord:
    return LogRecord(
        name="inspect_ai.test",
        level=INFO,
        pathname=__file__,
        lineno=12,
        msg=message,
        args=(),
        exc_info=exc_info,
    )


def captured_exc_info() -> Any:
    try:
        raise ValueError("boom")
    except ValueError:
        return sys.exc_info()


def test_logger_display_format_defaults_to_rich(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INSPECT_PY_LOGGER_FORMAT", raising=False)
    assert logger_display_format() == "rich"


def test_logger_display_format_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECT_PY_LOGGER_FORMAT", "xml")
    with pytest.raises(PrerequisiteError):
        logger_display_format()


def test_plain_logger_format_writes_single_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("INSPECT_TRACE_LEVEL", "info")
    stream = io.StringIO()
    handler = LogHandler(
        capture_levelno=INFO,
        display_levelno=INFO,
        transcript_levelno=0,
        trace_dir=tmp_path,
        logger_format="plain",
        display_stream=stream,
    )

    handler.emit_display(log_record("Downloading archive from s3://bucket/path.tar"))

    output = stream.getvalue()
    assert output.count("\n") == 1
    assert "INFO" in output
    assert "Downloading archive from s3://bucket/path.tar" in output


def test_json_logger_format_writes_one_json_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("INSPECT_TRACE_LEVEL", "info")
    stream = io.StringIO()
    handler = LogHandler(
        capture_levelno=INFO,
        display_levelno=INFO,
        transcript_levelno=0,
        trace_dir=tmp_path,
        logger_format="json",
        display_stream=stream,
    )

    handler.emit_display(log_record("Downloading archive from s3://bucket/path.tar"))

    output = stream.getvalue()
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "inspect_ai.test"
    assert payload["msg"] == "Downloading archive from s3://bucket/path.tar"
    assert payload["module"] == "test_logger_format.py"
    assert payload["line"] == 12


def test_json_logger_format_includes_exc_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("INSPECT_TRACE_LEVEL", "info")
    stream = io.StringIO()
    handler = LogHandler(
        capture_levelno=INFO,
        display_levelno=INFO,
        transcript_levelno=0,
        trace_dir=tmp_path,
        logger_format="json",
        display_stream=stream,
    )

    handler.emit_display(log_record("failed", exc_info=captured_exc_info()))

    output = stream.getvalue()
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert "exc_info" in payload
    assert "ValueError: boom" in payload["exc_info"]
    assert "Traceback" in payload["exc_info"]


def test_plain_logger_format_escapes_newlines_in_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("INSPECT_TRACE_LEVEL", "info")
    stream = io.StringIO()
    handler = LogHandler(
        capture_levelno=INFO,
        display_levelno=INFO,
        transcript_levelno=0,
        trace_dir=tmp_path,
        logger_format="plain",
        display_stream=stream,
    )

    handler.emit_display(log_record("failed", exc_info=captured_exc_info()))

    output = stream.getvalue()
    assert output.count("\n") == 1
    assert "\\n" in output
    assert "ValueError: boom" in output
