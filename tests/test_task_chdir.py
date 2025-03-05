import os
from pathlib import Path

from inspect_ai import eval

TEST_TASK_CHDIR_PATH = Path("tests/test_task_chdir")


def test_task_chdir():
    cwd = os.getcwd()

    log1, log2 = eval(
        [(TEST_TASK_CHDIR_PATH / task).as_posix() for task in ["task1", "task2"]],
        model="mockllm/model",
        max_tasks=2,
    )
    assert all([log.status == "success" for log in [log1, log2]])

    assert log1.eval.metadata["task_idx"] == 1
    assert log2.eval.metadata["task_idx"] == 2

    assert cwd == os.getcwd()


def test_task_chdir_error():
    log3 = eval(
        (TEST_TASK_CHDIR_PATH / "task3").as_posix(),
        model="mockllm/model",
    )[0]
    assert log3.status == "error"
