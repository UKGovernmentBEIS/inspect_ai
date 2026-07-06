"""A failed log write must not tear down the whole run.

Log writes at task start (``log_start`` header flush) and the error-status
``log_finish`` are the only exceptions that escape ``task_run``. If log
storage (e.g. S3) is unreachable at that moment, the failure previously
propagated out of ``_run_task`` and crashed the entire eval — cancelling
every sibling task. It should instead surface as an errored ``EvalLog`` so
the task can be retried like any other task error.
"""

from typing import Any, cast

from botocore.exceptions import ClientError

from inspect_ai import Task, eval, task
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai.dataset import Sample


@task
def trivial_task() -> Task:
    return Task(dataset=[Sample(id=1, input="x", target="y")], name="trivial_task")


def _skew_error() -> ClientError:
    return ClientError(
        cast(
            Any,
            {
                "Error": {
                    "Code": "RequestTimeTooSkewed",
                    "Message": "The difference between the request time and the "
                    "current time is too large.",
                },
                "ResponseMetadata": {"RequestId": "request-1"},
            },
        ),
        "PutObject",
    )


def test_failed_log_start_returns_errored_log(monkeypatch, tmp_path):
    """A permanently failing log_start yields an errored log, not a crash."""

    async def failing_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        raise _skew_error()

    monkeypatch.setattr(TaskLogger, "log_start", failing_log_start)

    logs = eval(
        trivial_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )

    assert len(logs) == 1
    assert logs[0].status == "error"
    assert logs[0].error is not None
    assert "RequestTimeTooSkewed" in logs[0].error.message


def test_failed_log_start_is_retried(monkeypatch, tmp_path):
    """A transient log_start failure is retried and the task completes."""
    calls = {"n": 0}
    original_log_start = TaskLogger.log_start

    async def flaky_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _skew_error()
        return await original_log_start(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_start", flaky_log_start)

    logs = eval(
        trivial_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert calls["n"] == 2
