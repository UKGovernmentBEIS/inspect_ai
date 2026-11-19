import io
import json
import sys
from logging import INFO, LogRecord
from types import TracebackType
from typing import Any

import pytest
import rich.console

from inspect_ai._util.constants import EXC_SNAPSHOT
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import (
    LoggerFormat,
    LogHandler,
    exc_snapshot_filter,
    logger_display_format,
)
from inspect_ai._util.trace import TraceFormatter


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


def snapshot_record(exc_info: Any) -> LogRecord:
    """A record carrying a failed task's error as LogDisplay logs it."""
    from inspect_ai._display.core.display import TaskError

    snapshot = TaskError.from_exception(0, *exc_info)
    record = log_record("failed")
    setattr(record, EXC_SNAPSHOT, snapshot.text)
    return record


def chained_exc_info() -> Any:
    try:
        try:
            raise KeyError("inner")
        except KeyError as ex:
            raise ValueError("boom") from ex
    except ValueError:
        return sys.exc_info()


@pytest.mark.parametrize("logger_format", ["plain", "json"])
def test_logger_format_renders_exc_snapshot_like_exc_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path, logger_format: LoggerFormat
) -> None:
    monkeypatch.setenv("INSPECT_TRACE_LEVEL", "info")
    exc_info = chained_exc_info()

    def emitted(record: LogRecord) -> str:
        stream = io.StringIO()
        handler = LogHandler(
            capture_levelno=INFO,
            display_levelno=INFO,
            transcript_levelno=0,
            trace_dir=tmp_path,
            logger_format=logger_format,
            display_stream=stream,
        )
        handler.emit(record)
        return stream.getvalue()

    from_snapshot = emitted(snapshot_record(exc_info))
    from_exc_info = emitted(log_record("failed", exc_info=exc_info))
    assert "KeyError: 'inner'" in from_snapshot
    if logger_format == "json":
        snapshot_payload = json.loads(from_snapshot)
        exc_info_payload = json.loads(from_exc_info)
        assert snapshot_payload["msg"] == "failed"
        assert snapshot_payload["exc_info"] == exc_info_payload["exc_info"]
    else:
        # the timestamp prefix differs between the two records
        assert from_snapshot.split(" - ", 1)[1] == from_exc_info.split(" - ", 1)[1]


def test_trace_formatter_omits_exc_snapshot() -> None:
    formatter = TraceFormatter()
    exc_info = chained_exc_info()

    snapshot = snapshot_record(exc_info)
    setattr(snapshot, "unrelated", "kept")
    plain = log_record("failed", exc_info=exc_info)
    setattr(plain, "unrelated", "kept")

    snapshot_json = json.loads(formatter.format(snapshot))
    plain_json = json.loads(formatter.format(plain))
    snapshot_json.pop("timestamp")
    plain_json.pop("timestamp")
    assert EXC_SNAPSHOT not in snapshot_json
    assert snapshot_json == plain_json
    assert snapshot_json["unrelated"] == "kept"


def test_task_error_snapshot_holds_no_frames() -> None:
    """A failed task's display row keeps no frame, so the task's locals are freed."""
    import gc
    import weakref

    from inspect_ai._display.core.display import TaskError
    from inspect_ai._util.rich import rich_traceback

    class Dataset:
        pass

    def run_task(dataset: Dataset) -> None:
        raise ValueError("task failed")

    dataset = Dataset()
    dataset_ref = weakref.ref(dataset)
    exc_info: Any = None
    try:
        run_task(dataset)
    except ValueError:
        exc_info = sys.exc_info()
    expected = rich_traceback(*exc_info)
    snapshot = TaskError.from_exception(3, *exc_info)
    del exc_info, dataset
    gc.collect()

    assert dataset_ref() is None
    assert snapshot.samples_completed == 3
    assert snapshot.exc_type is ValueError
    assert "ValueError: task failed" in snapshot.text
    assert not snapshot.text.endswith("\n")

    def render(renderable: Any) -> str:
        console = rich.console.Console(width=120, record=True, file=io.StringIO())
        console.print(renderable)
        return console.export_text()

    assert render(snapshot.rendered) == render(expected)


def test_failed_task_traceback_reaches_an_application_handler() -> None:
    """A handler installed before Inspect's formats the failed task's traceback."""
    import logging

    from inspect_ai._display.core.display import (
        TaskError,
        TaskProfile,
        TaskWithResult,
    )
    from inspect_ai._display.log.display import LogDisplay
    from inspect_ai.log import EvalConfig
    from inspect_ai.model import GenerateConfig, ModelName

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.ERROR)
    try:
        profile = TaskProfile(
            name="task",
            file=None,
            model=ModelName("mockllm/model"),
            agent=None,
            dataset="dataset",
            scorer="scorer",
            samples=1,
            steps=1,
            eval_config=EvalConfig(),
            task_args={},
            generate_config=GenerateConfig(),
            tags=None,
            log_location="log.eval",
            task_id="task-id",
            task_cancel=None,
        )
        error = TaskError.from_exception(0, *chained_exc_info())
        LogDisplay()._log_result(TaskWithResult(profile, error))
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    output = stream.getvalue()
    assert "failed (0/1 logged)" in output
    assert "ValueError: boom" in output
    assert "KeyError: 'inner'" in output
    # the filter is installed only for the failed task's record
    assert exc_snapshot_filter not in root.filters
