import sys
from pathlib import Path
from typing import Callable

import pytest

from inspect_ai import TaskInfo, list_tasks
from inspect_ai._eval.list import task_files

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


@pytest.mark.parametrize(
    "glob",
    [
        ".",
        "multiple.py",
        "multiple_dir",
        "multiple_dir/*.py",
        "recurse",
        "recurse/**/*.py",
        "attribs.ipynb",
    ],
)
@pytest.mark.parametrize("absolute", [False, True])
def test_task_list_absolute_glob(glob: str, absolute: bool) -> None:
    expected = list_tasks(glob, absolute=absolute, root_dir=TEST_TASKS_DIR)
    tasks = list_tasks(
        str(TEST_TASKS_DIR.resolve() / glob),
        absolute=absolute,
        root_dir=TEST_TASKS_DIR,
    )
    assert tasks == expected


@pytest.mark.parametrize("absolute_glob", [False, True])
def test_task_list_outside_root(absolute_glob: bool) -> None:
    glob = (
        str((TEST_TASKS_DIR / "multiple.py").resolve())
        if absolute_glob
        else "../multiple.py"
    )
    tasks = list_tasks(glob, root_dir=TEST_TASKS_DIR / "multiple_dir")
    assert [(task.file, task.name) for task in tasks] == [
        ("../multiple.py", "first"),
        ("../multiple.py", "second_task"),
    ]


@pytest.mark.parametrize("outside_root", [False, True])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation is unreliable/privileged on Windows",
)
def test_task_list_preserves_symlink_parent(tmp_path: Path, outside_root: bool) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    (outside / "subdir").mkdir(parents=True)
    (root / "link").symlink_to(outside / "subdir", target_is_directory=True)
    (root / "task.py").write_text("@task\ndef wrong(): pass\n")
    (outside / "task.py").write_text("@task\ndef right(): pass\n")
    if outside_root:
        glob = str(root / "link" / ".." / "task.py")
        root = tmp_path / "elsewhere"
        root.mkdir()
    else:
        glob = "link/../task.py"

    tasks = list_tasks(glob, root_dir=root)

    assert [task.name for task in tasks] == ["right"]
    assert (root / tasks[0].file).resolve() == outside / "task.py"


def test_task_files_absolute_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    anchor = Path(Path.cwd().anchor)
    # Avoid traversing the actual filesystem root.
    monkeypatch.setattr(
        "inspect_ai._eval.list.tasks_in_dir", lambda path: [path / "task.py"]
    )

    assert task_files([str(anchor)]) == [anchor / "task.py"]
