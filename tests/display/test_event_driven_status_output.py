import logging

import pytest

from inspect_ai._display.core.display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskWithResult,
)
from inspect_ai._display.log.display import LogDisplay, LogTaskDisplay
from inspect_ai._display.plain.display import PlainTaskDisplay
from inspect_ai.log import EvalConfig, EvalStats
from inspect_ai.model import GenerateConfig, ModelName


def task_profile(*, steps: int = 18, name: str = "MirrorCode") -> TaskProfile:
    return TaskProfile(
        name=name,
        file=None,
        model=ModelName("anthropic/claude-opus-4-7"),
        agent=None,
        dataset="",
        scorer="",
        samples=18,
        steps=steps,
        eval_config=EvalConfig(),
        task_args={},
        generate_config=GenerateConfig(),
        tags=None,
        log_location="logs/test.eval",
        task_id="mirror-code",
        task_cancel=None,
    )


def test_log_status_emits_when_progress_updates(caplog):
    display = LogTaskDisplay(TaskWithResult(task_profile(), None))
    display._log_status_throttled = lambda stacklevel: display._log_status(stacklevel)
    display.samples_complete = 13
    display.samples_total = 18

    with caplog.at_level(logging.INFO):
        with display.progress() as progress:
            progress.update(2)

    assert display.samples_complete == 13
    assert display.samples_total == 18
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Steps: 2/18 11%" in message and "Samples: 13/18" in message
        for message in messages
    )


def test_plain_status_prints_when_progress_updates(capsys):
    display = PlainTaskDisplay(
        TaskWithResult(task_profile(), None),
        show_task_names=False,
        show_model_names=False,
    )
    display._print_status_throttled = display._print_status
    display.samples_complete = 13
    display.samples_total = 18

    with display.progress() as progress:
        progress.update(2)

    assert display.samples_complete == 13
    assert display.samples_total == 18
    output = capsys.readouterr().out
    assert "Steps:   2/18  11%" in output
    assert "Samples:  13/ 18" in output


def test_log_status_handles_zero_step_progress(caplog):
    display = LogTaskDisplay(TaskWithResult(task_profile(steps=0), None))
    display._log_status_throttled = lambda stacklevel: display._log_status(stacklevel)

    with caplog.at_level(logging.INFO):
        with display.progress() as progress:
            progress.update()

    messages = [record.getMessage() for record in caplog.records]
    assert any("Steps: 1/0 100%" in message for message in messages)


def test_plain_status_prints_when_progress_completes(capsys):
    display = PlainTaskDisplay(
        TaskWithResult(task_profile(), None),
        show_task_names=False,
        show_model_names=False,
    )
    display._print_status_throttled = display._print_status

    with display.progress() as progress:
        progress.complete()

    assert "Steps:  18/18 100%" in capsys.readouterr().out


def test_log_display_reports_row_completed_before_exception(caplog):
    """A row completed before an exception leaves the task context still logs its result.

    An abandoned retry completes its row as cancelled and then re-raises.
    """
    display = LogDisplay()
    display.tasks = []
    stats = EvalStats(
        started_at="2026-01-01T00:00:00", completed_at="2026-01-01T00:00:01"
    )
    with caplog.at_level(logging.INFO):
        with display.task(task_profile()) as td:
            error = RuntimeError("sample failure")
            td.complete(TaskError.from_exception(0, RuntimeError, error, None))
        with pytest.raises(RuntimeError, match="abandoned"):
            with display.task(task_profile(name="MirrorCode (retry 1 of 1)")) as td:
                td.complete(TaskCancelled(0, stats))
                raise RuntimeError("abandoned")
        with pytest.raises(RuntimeError, match="no result"):
            with display.task(task_profile(name="Other")) as td:
                raise RuntimeError("no result")

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "(retry 1 of 1)" in m and "cancelled (0/18 logged)" in m for m in messages
    )
    status = [m for m in messages if m.endswith("tasks complete")]
    # the row with no result logs nothing
    assert status == ["1/1 tasks complete", "1/1 tasks complete"]
