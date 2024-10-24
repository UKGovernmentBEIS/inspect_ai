import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from test_helpers.utils import failing_solver, failing_task, failing_task_deterministic

from inspect_ai import Task, task
from inspect_ai._eval.evalset import (
    ModelList,
    eval_set,
    latest_completed_task_eval_logs,
    list_all_eval_logs,
    schedule_pending_tasks,
    schedule_retry_tasks,
)
from inspect_ai._eval.loader import ResolvedTask
from inspect_ai.dataset import Sample
from inspect_ai.log._file import list_eval_logs
from inspect_ai.model import Model, get_model
from inspect_ai.scorer._match import includes
from inspect_ai.solver._solver import generate


def test_eval_set() -> None:
    # run eval with a solver that fails 10% of the time
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task(rate=0.1, samples=10),
            log_dir=log_dir,
            retry_attempts=1000,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert success
        assert logs[0].status == "success"

    # run eval that is guaranteed to fail
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task(rate=1, samples=10),
            log_dir=log_dir,
            retry_attempts=1,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert not success
        assert logs[0].status == "error"


def test_eval_set_dynamic() -> None:
    with tempfile.TemporaryDirectory() as log_dir:
        dataset: list[Sample] = []
        for _ in range(0, 10):
            dataset.append(Sample(input="Say hello", target="hello"))
        task1 = Task(
            name="task1",
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.2), generate()],
            scorer=includes(),
        )
        task2 = Task(
            name="task2",
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.2), generate()],
            scorer=includes(),
        )
        success, logs = eval_set(
            tasks=[task1, task2],
            log_dir=log_dir,
            model=[get_model("mockllm/model"), get_model("mockllm/model2")],
            retry_attempts=100,
            retry_wait=0.1,
        )
        assert len(logs) == 4
        assert success


def test_eval_set_identifiers() -> None:
    dataset: list[Sample] = []
    for _ in range(0, 10):
        dataset.append(Sample(input="Say hello", target="hello"))

    @task
    def make_task(param="param"):
        return Task(
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.2), generate()],
            scorer=includes(),
        )

    def eval_tasks(tasks: list[Task]):
        with tempfile.TemporaryDirectory() as log_dir:
            success, logs = eval_set(
                tasks=tasks,
                log_dir=log_dir,
                model=[get_model("mockllm/model")],
                retry_attempts=100,
                retry_wait=0.1,
            )
            assert success

    # test that task parameters create unique identfiers
    try:
        eval_tasks([make_task("a"), make_task("b")])
    except Exception:
        assert False

    # test that using identical params results in an error
    try:
        eval_tasks([make_task("a"), make_task("a")])
        assert False
    except Exception:
        pass


def test_schedule_pending_tasks() -> None:
    task1 = Task(dataset=[], name="task1")
    task2 = Task(dataset=[], name="task2")
    task3 = Task(dataset=[], name="task3")
    task4 = Task(dataset=[], name="task4")
    task5 = Task(dataset=[], name="task5")
    openai = get_model("mockllm/openai")
    anthropic = get_model("mockllm/anthropic")
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
        sched: tuple[ModelList, list[ResolvedTask]],
        models: list[Model],
        tasks: list[Task],
    ) -> None:
        assert sched[0] == ModelList(models)
        sched_tasks = list(sched[1])
        sched_tasks.sort(key=lambda x: x.task.name)
        tasks = list(tasks)
        tasks.sort(key=lambda x: x.name)
        assert [task.task for task in sched_tasks] == tasks

    # test schedule with all models for each task
    tasks: list[ResolvedTask] = []
    for tk in [task1, task2, task3, task4, task5]:
        for model in [openai, anthropic, mock]:
            tasks.append(resolved_task(tk, model))
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

    # test retry scheduling (single model at a time)
    schedule = schedule_retry_tasks(tasks)
    assert len(schedule) == 3
    assert_schedule(schedule[0], [anthropic], [task1, task2, task4])
    assert_schedule(schedule[1], [mock], [task1, task3, task5])
    assert_schedule(schedule[2], [openai], [task1, task2, task4])


def test_latest_completed_task_eval_logs() -> None:
    # cleanup previous tests
    TEST_EVAL_SET_PATH = Path("tests/test_eval_set")
    clean_dir = TEST_EVAL_SET_PATH / "clean"
    if clean_dir.exists():
        shutil.rmtree(clean_dir.as_posix())

    # verify we correctly select only the most recent log
    all_logs = list_all_eval_logs(TEST_EVAL_SET_PATH.as_posix())
    assert len(all_logs) == 2
    latest = latest_completed_task_eval_logs(all_logs, False)
    assert len(latest) == 1

    # verify that we correctly clean when requested
    clean_dir.mkdir(exist_ok=True)
    try:
        for filename in TEST_EVAL_SET_PATH.glob("*.json"):
            destination = clean_dir / filename.name
            shutil.copy2(filename, destination)
        all_logs = list_all_eval_logs(clean_dir.as_posix())
        latest = latest_completed_task_eval_logs(all_logs, True)
        assert len(list_eval_logs(clean_dir.as_posix())) == 1
    finally:
        shutil.rmtree(clean_dir, ignore_errors=True)


@pytest.mark.slow
def test_eval_set_s3(mock_s3) -> None:
    success, logs = eval_set(
        tasks=failing_task(rate=0, samples=1),
        log_dir="s3://test-bucket",
        retry_attempts=1,
        retry_wait=0.1,
        model="mockllm/model",
    )
    assert success
    assert logs[0].status == "success"


def test_eval_zero_retries() -> None:
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task_deterministic([True, False]),
            log_dir=log_dir,
            retry_attempts=0,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert not success
