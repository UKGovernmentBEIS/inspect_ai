from pathlib import Path

from test_helpers.tasks import empty_task
from test_helpers.utils import ensure_test_package_installed

from inspect_ai._eval.loader import resolve_task_sandbox
from inspect_ai._eval.registry import task_create
from inspect_ai._eval.task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR
from inspect_ai._eval.task.util import task_run_dir, task_source_dir


def test_local_module_attr():
    task = empty_task()
    assert getattr(task, TASK_FILE_ATTR, None)
    assert getattr(task, TASK_RUN_DIR_ATTR, None)


def test_package_task_implicit_sandbox_resolves_relative_to_package_dir():
    ensure_test_package_installed()

    import inspect_package

    task = task_create("inspect_package/implicit_sandbox_task")
    resolved = resolve_task_sandbox(task, None)

    assert resolved is not None
    assert resolved.config == str(Path(inspect_package.__file__).parent / "podman.yaml")


def test_package_task_relative_sandbox_config_resolves_relative_to_package_dir():
    ensure_test_package_installed()

    import inspect_package

    task = task_create("inspect_package/relative_sandbox_task")
    resolved = resolve_task_sandbox(task, None)

    assert resolved is not None
    assert resolved.config == str(Path(inspect_package.__file__).parent / "podman.yaml")


def test_package_task_uses_source_dir_without_changing_run_dir():
    ensure_test_package_installed()

    import inspect_package

    task = task_create("inspect_package/implicit_sandbox_task")

    assert task_source_dir(task) == str(Path(inspect_package.__file__).parent)
    assert task_run_dir(task) == str(Path.cwd())
