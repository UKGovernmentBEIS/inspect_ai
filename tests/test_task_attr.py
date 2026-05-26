from pathlib import Path

import pytest
from test_helpers.tasks import empty_task

from inspect_ai._eval.loader import load_file_tasks, resolve_task_sandbox
from inspect_ai._eval.registry import task_create
from inspect_ai._eval.task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR


def test_local_module_attr():
    task = empty_task()
    assert getattr(task, TASK_FILE_ATTR, None)
    assert getattr(task, TASK_RUN_DIR_ATTR, None)


def test_installed_package_task_run_dir_resolves_implicit_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    module_file = package_dir / "registry_tasks.py"
    module_file.write_text(
        "\n".join(
            [
                "from inspect_ai import Task, task",
                "",
                "@task",
                "def registry_sandbox_task():",
                "    return Task(sandbox='docker')",
                "",
            ]
        )
    )
    dockerfile = package_dir / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\n")

    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()
    monkeypatch.chdir(caller_dir)
    monkeypatch.setattr(
        "inspect_ai._eval.registry.get_installed_package_name",
        lambda _obj: "sample_package",
    )
    monkeypatch.setattr(
        "inspect_ai._util.registry.get_installed_package_name",
        lambda _obj: "sample_package",
    )

    load_file_tasks(module_file)
    task = task_create("sample_package/registry_sandbox_task")

    assert getattr(task, TASK_FILE_ATTR, None) is None
    assert getattr(task, TASK_RUN_DIR_ATTR) == package_dir.as_posix()
    sandbox = resolve_task_sandbox(task, None)
    assert sandbox is not None
    assert sandbox.config == dockerfile.as_posix()
