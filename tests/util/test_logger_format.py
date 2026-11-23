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


def chained_exc_info() -> Any:
    try:
        try:
            raise KeyError("inner")
        except KeyError as ex:
            raise ValueError("boom") from ex
    except ValueError:
        return sys.exc_info()


def test_task_error_snapshot_holds_no_frames_once_released() -> None:
    """A failed task's display row keeps no frame, so the task's locals are freed."""
    import gc
    import weakref

    import rich.console

    from inspect_ai._display.core.display import TaskError
    from inspect_ai._util.rich import rich_traceback

    class Dataset:
        pass

    def run_task(dataset: Dataset) -> None:
        raise ValueError("task failed")

    def failed_task() -> tuple[weakref.ref[Dataset], TaskError, Any]:
        # the failing code runs in a frame that has returned, as a task's
        # does once its row closes (a live frame's locals snapshot on
        # Python 3.11 and 3.12 would keep the dataset alive on its own)
        dataset = Dataset()
        exc_info: Any = None
        try:
            run_task(dataset)
        except ValueError:
            exc_info = sys.exc_info()
        return (
            weakref.ref(dataset),
            TaskError.from_exception(3, *exc_info),
            rich_traceback(*exc_info),
        )

    dataset_ref, snapshot, expected = failed_task()
    gc.collect()

    # the live exception is kept until the row closes
    assert dataset_ref() is not None
    snapshot.release_exception()
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


def test_log_display_logs_a_failed_task_with_its_exception() -> None:
    """Handlers get the failed task's exc_info: text formatters and structured ones."""
    import logging
    import traceback

    from inspect_ai._display.core.display import (
        TaskError,
        TaskProfile,
        TaskWithResult,
    )
    from inspect_ai._display.log.display import LogDisplay
    from inspect_ai.log import EvalConfig
    from inspect_ai.model import GenerateConfig, ModelName

    class StructuredFormatter(logging.Formatter):
        """Builds error fields from record.exc_info, as JSON log formatters do."""

        def format(self, record: LogRecord) -> str:
            fields: dict[str, Any] = {"message": record.getMessage()}
            if record.exc_info:
                exc_type, exc_value, exc_tb = record.exc_info
                fields["error"] = {
                    "kind": exc_type.__name__ if exc_type is not None else None,
                    "message": str(exc_value),
                    "stack": "".join(
                        traceback.format_exception(exc_type, exc_value, exc_tb)
                    ),
                }
            return json.dumps(fields)

    text_stream = io.StringIO()
    text_handler = logging.StreamHandler(text_stream)
    structured_stream = io.StringIO()
    structured_handler = logging.StreamHandler(structured_stream)
    structured_handler.setFormatter(StructuredFormatter())
    root = logging.getLogger()
    root.addHandler(text_handler)
    root.addHandler(structured_handler)
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
        root.removeHandler(text_handler)
        root.removeHandler(structured_handler)
        root.setLevel(previous_level)

    text = text_stream.getvalue()
    assert "failed (0/1 logged)" in text
    assert "ValueError: boom" in text
    assert "KeyError: 'inner'" in text

    structured = json.loads(structured_stream.getvalue())
    assert structured["error"]["kind"] == "ValueError"
    assert structured["error"]["message"] == "boom"
    assert "KeyError: 'inner'" in structured["error"]["stack"]
    assert 'raise ValueError("boom") from ex' in structured["error"]["stack"]
