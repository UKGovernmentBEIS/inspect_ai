import importlib
from pathlib import Path

from test_helpers.tasks import empty_task
from test_helpers.utils import ensure_test_package_installed, skip_if_no_docker

from inspect_ai import eval
from inspect_ai._eval.loader import resolve_task_file_sandbox, resolve_task_sandbox
from inspect_ai._eval.registry import task_create
from inspect_ai._eval.task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.util import task_run_dir, task_source_dir
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalConfig
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.model import get_model


def test_local_module_attr():
    task = empty_task()
    assert getattr(task, TASK_FILE_ATTR, None)
    assert getattr(task, TASK_RUN_DIR_ATTR, None)


def test_package_task_implicit_sandbox_resolves_relative_to_package_dir():
    ensure_test_package_installed()

    inspect_package = importlib.import_module("inspect_package")

    task = task_create("inspect_package/implicit_sandbox_task")
    resolved = resolve_task_sandbox(task, None)

    assert resolved is not None
    assert resolved.config == str(
        Path(str(inspect_package.__file__)).parent / "podman.yaml"
    )


def test_package_task_relative_sandbox_config_resolves_relative_to_package_dir():
    ensure_test_package_installed()

    inspect_package = importlib.import_module("inspect_package")

    task = task_create("inspect_package/relative_sandbox_task")
    resolved = resolve_task_sandbox(task, None)

    assert resolved is not None
    assert resolved.config == str(
        Path(str(inspect_package.__file__)).parent / "podman.yaml"
    )


def test_package_task_uses_source_dir_without_changing_run_dir():
    ensure_test_package_installed()

    inspect_package = importlib.import_module("inspect_package")

    task = task_create("inspect_package/implicit_sandbox_task")

    assert task_source_dir(task) == str(Path(str(inspect_package.__file__)).parent)
    assert task_run_dir(task) == str(Path.cwd())


def test_package_task_override_sandbox_resolves_relative_to_run_dir():
    ensure_test_package_installed()

    task = task_create("inspect_package/implicit_sandbox_task")
    resolved = resolve_task_sandbox(task, ("podman", "override.yaml"))

    assert resolved is not None
    assert resolved.config == str(Path.cwd() / "override.yaml")


def test_package_task_logs_absolute_sandbox_config_for_retry(monkeypatch, tmp_path):
    ensure_test_package_installed()

    inspect_package = importlib.import_module("inspect_package")

    monkeypatch.chdir("/home/claw/.openclaw/workspace/repos/inspect_ai")

    task = task_create("inspect_package/implicit_sandbox_task")
    sandbox = resolve_task_sandbox(task, None)

    assert sandbox is not None

    logger = TaskLogger(
        task_name=task.name,
        task_version=task.version,
        task_file=None,
        task_registry_name=task.registry_name,
        task_display_name=task.display_name,
        task_id=None,
        eval_set_id=None,
        run_id="run-id",
        solver=None,
        tags=None,
        model=get_model("mockllm/model"),
        model_roles=None,
        dataset=MemoryDataset([Sample(input="hi", id=1)], name="dataset"),
        scorer=None,
        metrics=None,
        sandbox=sandbox,
        task_attribs=task.attribs,
        task_args={},
        task_args_passed={},
        model_args={},
        eval_config=EvalConfig(),
        metadata=None,
        viewer=None,
        recorder=EvalRecorder(tmp_path.as_posix()),
        header_only=False,
    )

    expected = str(Path(str(inspect_package.__file__)).parent / "podman.yaml")
    assert logger.eval.sandbox is not None
    assert logger.eval.sandbox.config == expected

    monkeypatch.chdir(tmp_path)
    retried = resolve_task_file_sandbox(logger.eval.task_file, logger.eval.sandbox)
    assert retried is not None
    assert retried.config == expected


@skip_if_no_docker
def test_package_task_implicit_docker_build_uses_package_dockerfile():
    ensure_test_package_installed()

    task = task_create("inspect_package/docker_implicit_task")
    log = eval(task, model="mockllm/model")[0]

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.store.get("package_marker") == "package-docker-proof"
