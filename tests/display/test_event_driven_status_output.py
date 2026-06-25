import logging

from inspect_ai._display.core.display import TaskProfile, TaskWithResult
from inspect_ai._display.log.display import LogTaskDisplay
from inspect_ai._display.plain.display import PlainTaskDisplay
from inspect_ai.log import EvalConfig
from inspect_ai.model import GenerateConfig, ModelName


def task_profile(*, steps: int = 18) -> TaskProfile:
    return TaskProfile(
        name="MirrorCode",
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
