import os
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_asyncio, skip_if_trio

from inspect_ai import eval

TEST_TASK_CHDIR_PATH = Path("tests/test_task_chdir")


@skip_if_trio
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


@skip_if_asyncio
def test_trio_chdir_error():
    with pytest.raises(RuntimeError):
        eval(
            (TEST_TASK_CHDIR_PATH / "task1").as_posix(),
            model="mockllm/model",
        )


def test_task_chdir_error():
    log3 = eval(
        (TEST_TASK_CHDIR_PATH / "task3").as_posix(),
        model="mockllm/model",
    )[0]
    assert log3.status == "error"
