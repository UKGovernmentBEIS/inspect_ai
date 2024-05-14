from pathlib import Path
from typing import Callable

from inspect_ai import TaskInfo, list_tasks

TEST_TASKS_DIR = Path("tests/test_task_list")


def list_test_tasks_dir(
    globs: list[str], filter: Callable[[TaskInfo], bool] | None = None
):
    return list_tasks(globs, filter=filter, root_dir=TEST_TASKS_DIR)


def test_task_list_multiple_file():
    tasks = list_test_tasks_dir(["multiple.py"])
    assert len(tasks) == 2
    names = [task.name for task in tasks]
    assert "first" in names
    assert "second_task" in names


def test_task_list_multiple_dir():
    tasks = list_test_tasks_dir(["multiple_dir"])
    assert len(tasks) == 2


def test_task_list_attribs():
    tasks = list_test_tasks_dir(["attribs.ipynb"])
    assert tasks[0].attribs.get("light") is True
    assert tasks[0].attribs.get("type") == "bio"


def test_task_list_filter():
    tasks = list_test_tasks_dir(["*"], filter=lambda t: t.attribs.get("type") == "bio")
    assert len(tasks) == 1


def test_task_list_recurse():
    tasks = list_test_tasks_dir(["recurse"])
    assert len(tasks) == 3
