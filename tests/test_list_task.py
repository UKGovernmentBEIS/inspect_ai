import ntpath
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Callable
from unittest.mock import Mock

import pytest

from inspect_ai import TaskInfo, list_tasks
from inspect_ai._eval.list import task_files, task_path

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


@pytest.mark.parametrize("glob", ["*.py/", "multiple_dir/"])
def test_task_list_absolute_directory_glob(glob: str) -> None:
    assert list_tasks(
        f"{TEST_TASKS_DIR.resolve().as_posix()}/{glob}", root_dir=TEST_TASKS_DIR
    ) == list_tasks(glob, root_dir=TEST_TASKS_DIR)


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


@pytest.mark.parametrize("suffix", ["", ".", "//"])
def test_task_files_rejects_absolute_anchor(
    suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = Path(Path.cwd().anchor)
    scan = Mock(side_effect=AssertionError("must not scan a filesystem root"))
    monkeypatch.setattr("inspect_ai._eval.list.tasks_in_dir", scan)

    with pytest.raises(ValueError, match="filesystem root"):
        task_files([f"{anchor}{suffix}"])
    scan.assert_not_called()


@pytest.mark.parametrize(
    "glob",
    ["C:/", "C:\\", "C:/.", "//server/share/", "\\\\server\\share\\"],
)
def test_task_files_rejects_windows_anchor(
    glob: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scan = Mock(side_effect=AssertionError("must not scan a filesystem root"))
    monkeypatch.setattr("inspect_ai._eval.list.Path", PureWindowsPath)
    monkeypatch.setattr("inspect_ai._eval.list.tasks_in_dir", scan)

    with pytest.raises(ValueError, match="filesystem root"):
        task_files([glob], root_dir=Mock(wraps=PureWindowsPath("C:/work")))
    scan.assert_not_called()


@pytest.mark.parametrize(
    "file,root,relative",
    [
        ("C:/tasks/task.py", "C:/tasks", "task.py"),
        ("C:/tasks/task.py", "C:/work", "../tasks/task.py"),
        ("//server/share/tasks/task.py", "//server/share/work", "../tasks/task.py"),
        ("D:/tasks/task.py", "C:/work", None),
        ("//server/share/tasks/task.py", "//server/other/work", None),
        ("//server/share/tasks/task.py", "//other/share/work", None),
        ("//server/share/tasks/task.py", "C:/work", None),
    ],
)
@pytest.mark.parametrize("absolute", [False, True])
def test_task_path_windows(
    file: str,
    root: str,
    relative: str | None,
    absolute: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise Windows path semantics without requiring mounted drives or shares.
    path = Mock(wraps=PureWindowsPath(file))
    path.resolve = Mock(return_value=PureWindowsPath(file))
    root_dir = Mock(wraps=PureWindowsPath(root))
    root_dir.resolve = Mock(return_value=PureWindowsPath(root))
    monkeypatch.setattr("inspect_ai._eval.list.Path", PureWindowsPath)
    monkeypatch.setattr("inspect_ai._eval.list.os", SimpleNamespace(path=ntpath))

    if not absolute and relative is None:
        with pytest.raises(ValueError, match=r"absolute=True.*--absolute"):
            task_path(path, root_dir, absolute)
    else:
        assert task_path(path, root_dir, absolute) == (file if absolute else relative)
