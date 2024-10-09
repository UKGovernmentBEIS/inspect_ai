import os
from pathlib import Path

from inspect_ai import eval

TEST_RUN_DIR_PATH = Path("tests/test_run_dir")


def test_run_dir():
    cwd = os.getcwd()

    log1, log2 = eval(
        [(TEST_RUN_DIR_PATH / task).as_posix() for task in ["task1", "task2"]],
        model="mockllm/model",
        max_tasks=2,
    )
    assert all([log.status == "success" for log in [log1, log2]])

    assert log1.eval.metadata["task_idx"] == 1
    assert log2.eval.metadata["task_idx"] == 2

    assert cwd == os.getcwd()
