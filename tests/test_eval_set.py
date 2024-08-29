import shutil
from pathlib import Path
from typing import Set

from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task
from inspect_ai._eval.evalset import (
    ModelList,
    latest_completed_task_eval_logs,
    schedule_pending_tasks,
)
from inspect_ai._eval.loader import ResolvedTask
from inspect_ai.log._file import list_eval_logs, read_eval_log_headers
from inspect_ai.model import Model, get_model

TEST_EVAL_SET_PATH = Path("tests/test_eval_set")


@skip_if_no_openai
@skip_if_no_anthropic
def test_schedule_pending_tasks() -> None:
    task1 = Task(dataset=[], name="task1")
    task2 = Task(dataset=[], name="task2")
    task3 = Task(dataset=[], name="task3")
    task4 = Task(dataset=[], name="task4")
    task5 = Task(dataset=[], name="task5")
    openai = get_model("openai/gpt-4o")
    anthropic = get_model("anthropic/claude-3-haiku-20240307")
    mock = get_model("mockllm/model")

    def resolved_task(task: Task, model: Model) -> ResolvedTask:
        return ResolvedTask(
            task=task,
            task_args={},
            task_file=None,
            model=model,
            sandbox=None,
            sequence=1,
        )

    def assert_schedule(
        sched: tuple[ModelList, Set[Task]], models: list[Model], tasks: list[Task]
    ) -> None:
        assert sched[0] == ModelList(models)
        sched_tasks = list(sched[1])
        sched_tasks.sort(key=lambda x: x.name)
        tasks = list(tasks)
        tasks.sort(key=lambda x: x.name)
        assert sched_tasks == tasks

    # test schedule with all models for each task
    tasks: list[ResolvedTask] = []
    for task in [task1, task2, task3, task4, task5]:
        for model in [openai, anthropic, mock]:
            tasks.append(resolved_task(task, model))
    schedule = schedule_pending_tasks(tasks)
    assert len(schedule) == 1
    assert_schedule(
        schedule[0], [openai, anthropic, mock], [task1, task2, task3, task4, task5]
    )

    # test schedule w/ varying models per task
    tasks = [
        resolved_task(task1, openai),
        resolved_task(task1, anthropic),
        resolved_task(task1, mock),
        resolved_task(task2, openai),
        resolved_task(task4, openai),
        resolved_task(task2, anthropic),
        resolved_task(task4, anthropic),
        resolved_task(task3, mock),
        resolved_task(task5, mock),
    ]
    schedule = schedule_pending_tasks(tasks)
    assert len(schedule) == 3
    assert_schedule(schedule[0], [mock], [task3, task5])
    assert_schedule(schedule[1], [openai, anthropic], [task2, task4])
    assert_schedule(schedule[2], [openai, anthropic, mock], [task1])


def test_latest_completed_task_eval_logs() -> None:
    # cleanup previous tests
    clean_dir = TEST_EVAL_SET_PATH / "clean"
    if clean_dir.exists():
        shutil.rmtree(clean_dir.as_posix())

    # verify we correctly select only the most recent log
    logs = list_eval_logs(TEST_EVAL_SET_PATH.as_posix(), recursive=False)
    log_headers = read_eval_log_headers(logs)
    latest = latest_completed_task_eval_logs(logs, log_headers, False)
    assert latest[0].status == "error"
    assert len(list_eval_logs(TEST_EVAL_SET_PATH.as_posix())) == 2

    # verify that we correctly clean when requested
    clean_dir.mkdir(exist_ok=True)
    try:
        for filename in TEST_EVAL_SET_PATH.glob("*.json"):
            destination = clean_dir / filename.name
            shutil.copy2(filename, destination)
        logs = list_eval_logs(clean_dir.as_posix(), recursive=False)
        log_headers = read_eval_log_headers(logs)
        latest = latest_completed_task_eval_logs(logs, log_headers, True)
        assert len(list_eval_logs(clean_dir.as_posix())) == 1
    finally:
        shutil.rmtree(clean_dir, ignore_errors=True)
