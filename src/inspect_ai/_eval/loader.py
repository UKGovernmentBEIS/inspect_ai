import ast
import inspect
import os
from dataclasses import dataclass, field
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from inspect_ai._eval.task.util import task_file, task_run_dir
from inspect_ai._util.path import chdir_python
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_info,
    registry_lookup,
    registry_params,
)
from inspect_ai.model import Model, ModelName
from inspect_ai.util import SandboxEnvironmentSpec
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

from .list import task_files
from .registry import task_create
from .task import PreviousTask, Task, TaskInfo, Tasks
from .task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR
from .task.run import EvalSampleSource, eval_log_sample_source

logger = getLogger(__name__)


@dataclass(frozen=True)
class ResolvedTask:
    task: Task
    task_args: dict[str, Any]
    task_file: str | None
    model: Model
    sandbox: tuple[str, str | None] | None
    sequence: int
    id: str | None = field(default=None)
    sample_source: EvalSampleSource | None = field(default=None)

    @property
    def has_sandbox(self) -> bool:
        if self.sandbox:
            return True
        else:
            return any(
                [True if sample.sandbox else False for sample in self.task.dataset]
            )


def resolve_tasks(
    tasks: Tasks,
    task_args: dict[str, Any],
    model: Model,
    sandbox: SandboxEnvironmentSpec | None,
) -> list[ResolvedTask]:
    def as_resolved_tasks(tasks: list[Task]) -> list[ResolvedTask]:
        return [
            ResolvedTask(
                task=task,
                task_args=resolve_task_args(task),
                task_file=task_file(task, relative=True),
                model=model,
                sandbox=resolve_task_sandbox(task, sandbox),
                sequence=sequence,
            )
            for sequence, task in enumerate(tasks)
        ]

    # take empty lists out of play
    if isinstance(tasks, list) and len(tasks) == 0:
        return as_resolved_tasks(load_tasks(None, model, task_args))

    # simple cases of passing us Task objects
    if isinstance(tasks, Task):
        return as_resolved_tasks([tasks])
    elif isinstance(tasks, list) and isinstance(tasks[0], Task):
        return as_resolved_tasks(cast(list[Task], tasks))

    # simple case of passing us PreviousTask
    if isinstance(tasks, PreviousTask):
        tasks = [tasks]
    if isinstance(tasks, list) and isinstance(tasks[0], PreviousTask):
        # for previous tasks, prefer recreating from the registry (so we have
        # a fresh instance) but also allow recycling of task instances for
        # fully dynamic tasks
        previous_tasks = cast(list[PreviousTask], tasks)
        loaded_tasks: list[Task] = []
        loaded_tasks_args: list[dict[str, Any]] = []
        for previous_task in previous_tasks:
            if isinstance(previous_task.task, Task):
                loaded_task_args = task_args
                loaded_task = previous_task.task
            else:
                loaded_task_args = previous_task.task_args
                loaded_task = load_tasks([previous_task.task], model, loaded_task_args)[
                    0
                ]
            loaded_tasks.append(loaded_task)
            loaded_tasks_args.append(loaded_task_args)

        return [
            ResolvedTask(
                task=loaded_task,
                task_args=loaded_task_args,
                task_file=previous_task.log.eval.task_file,
                model=model,
                sandbox=previous_task.log.eval.sandbox,
                sequence=sequence,
                id=previous_task.id,
                sample_source=eval_log_sample_source(
                    previous_task.log, loaded_task.dataset
                ),
            )
            for sequence, loaded_task, loaded_task_args, previous_task in zip(
                range(0, len(loaded_tasks)),
                loaded_tasks,
                loaded_tasks_args,
                previous_tasks,
            )
        ]

    # convert TaskInfo to str
    if isinstance(tasks, TaskInfo):
        tasks = [tasks]
    if isinstance(tasks, list) and isinstance(tasks[0], TaskInfo):
        tasks = [f"{task.file}@{task.name}" for task in cast(list[TaskInfo], tasks)]

    # handle functions that return tasks (we get their registry name)
    if isinstance(tasks, list) and callable(tasks[0]):
        tasks = [registry_info(task).name for task in tasks]
    elif callable(tasks):
        tasks = [registry_info(tasks).name]

    # str to list[str]
    if isinstance(tasks, str):
        tasks = [tasks]

    # done! let's load the tasks
    return as_resolved_tasks(
        load_tasks(cast(list[str] | None, tasks), model, task_args)
    )


def resolve_task_args(task: Task) -> dict[str, Any]:
    # was the task instantiated via the registry or a decorator?
    # if so then we can get the task_args from the registry.
    try:
        # filter out model as that's dyanmic and automatically passed
        task_args = dict(registry_params(task))
        if "model" in task_args:
            del task_args["model"]
        return task_args

    # if it wasn't instantiated via the registry or a decorator
    # then it will not be in the registy and not have formal
    # task args (as it was simply synthesized via ad-hoc code)
    except ValueError:
        return {}


def resolve_task_sandbox(
    task: Task, sandbox: SandboxEnvironmentSpec | None
) -> tuple[str, str | None] | None:
    # do the resolution
    resolved_sandbox = (
        (sandbox, None)
        if isinstance(sandbox, str)
        else sandbox
        if sandbox is not None
        else task.sandbox
    )

    # if we have a sandbox with no config, see if there are implcit
    # config files available for the provider
    if resolved_sandbox is not None:
        # look for default
        if resolved_sandbox[1] is None:
            # get config files for this type
            sandboxenv_type = registry_find_sandboxenv(resolved_sandbox[0])
            config_files_fn = cast(
                Callable[..., list[str]], getattr(sandboxenv_type, "config_files")
            )
            config_files = config_files_fn()

            # probe for them in task src dir
            src_dir = task_run_dir(task)
            for config_file in config_files:
                config_file_path = os.path.join(src_dir, config_file)
                if os.path.isfile(config_file_path):
                    resolved_sandbox = (resolved_sandbox[0], config_file)
                    break

        # resolve relative paths
        if resolved_sandbox[1] is not None:
            file_path = Path(resolved_sandbox[1])
            if not file_path.is_absolute():
                file_path = Path(task_run_dir(task)) / file_path
                resolved_sandbox = (resolved_sandbox[0], file_path.as_posix())

    # return resolved sandbox
    return resolved_sandbox


def load_tasks(
    task_specs: list[str] | None, model: Model, task_args: dict[str, Any] = {}
) -> list[Task]:
    """Load one more more tasks (if no tasks are specified, load from the current working directory"""
    # determine ModelName object for task creation parameterized by model
    model_name = ModelName(model)
    # load tasks
    return [
        spec
        for task_spec in (task_specs if task_specs else [Path.cwd().as_posix()])
        for spec in load_task_spec(task_spec, model_name, task_args)
    ]


def load_task_spec(
    task_spec: str, model: ModelName, task_args: dict[str, Any] = {}
) -> list[Task]:
    # task in a python package
    if registry_lookup("task", task_spec) is not None:
        # create the task from a python package
        return [task_create(task_spec, model, **task_args)]
    else:
        # load tasks from glob
        return create_tasks([task_spec], model, task_args)


def create_tasks(
    globs: list[str],
    model: ModelName,
    task_args: dict[str, Any] = {},
    root_dir: Path | None = None,
) -> list[Task]:
    tasks: list[Task] = []

    root_dir = root_dir if root_dir is not None else Path.cwd()

    for glob in globs:
        # sometimes globs are direct references to files
        # that include an @ index. for this case directly
        # create the task (we also need to load the file
        # so the task is registered before we create it)
        spec_split = split_task_spec(glob)
        if len(spec_split[1]) > 0:
            task_path = Path(spec_split[0])
            load_file_tasks(task_path.absolute())
            tasks.extend(
                create_file_tasks(task_path, model, [spec_split[1]], task_args)
            )
        else:
            # if the glob is the root dir then set it to empty (will result in
            # enumeration of the root dir)
            target = [] if Path(glob).resolve() == root_dir.resolve() else [glob]
            files = task_files(target, root_dir)
            files = sorted(files, key=lambda f: f.as_posix())
            for file in files:
                tasks.extend(create_file_tasks(file, model, None, task_args))
    return tasks


def load_file_tasks(file: Path) -> list[RegistryInfo]:
    with chdir_python(file.parent.as_posix()):
        return _load_task_specs(file)


def create_file_tasks(
    file: Path,
    model: ModelName,
    task_specs: list[str] | list[RegistryInfo] | None = None,
    task_args: dict[str, Any] = {},
) -> list[Task]:
    with chdir_python(file.parent.as_posix()):
        # if we don't have task specs then go get them (also,
        # turn them into plain names)
        if task_specs is None:
            task_specs = _load_task_specs(file)
        # convert to plain names
        task_specs = [
            spec if isinstance(spec, str) else spec.name for spec in task_specs
        ]

        tasks: list[Task] = []
        for task_spec in task_specs:
            # create the task from the loaded source file and
            # note that it was loaded from this directory
            # (will be used later to ensure it runs in the directory)
            task = task_create(task_spec, model, **task_args)
            setattr(task, TASK_FILE_ATTR, file.as_posix())
            setattr(task, TASK_RUN_DIR_ATTR, file.parent.as_posix())
            tasks.append(task)

            # warn about deprecated chdir attrib
            if "chdir" in task.attribs:
                logger.warning(
                    "The 'chdir' task attribute is deprecated (tasks now always chdir)"
                )

        return tasks


# don't call this function directly, rather, call one of the
# higher level loading functions above (those functions
# change the working directory, this one does not b/c it is
# intended as a helper function)
def _load_task_specs(task_path: Path) -> list[RegistryInfo]:
    # load the module
    module = load_task_module(task_path)
    if module:
        # find the tasks in the module
        tasks = inspect.getmembers(module, lambda m: is_registry_object(m, "task"))
        return [registry_info(task[1]) for task in tasks]
    else:
        return []


def split_task_spec(task_spec: str) -> tuple[str, str]:
    parts = task_spec.rsplit("@", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    else:
        return task_spec, ""


def load_task_module(task_path: Path) -> ModuleType | None:
    if task_path.suffix == ".py":
        # bail if the code doesn't have a task
        with open(task_path, "r", encoding="utf-8") as file:
            if not code_has_task(file.read()):
                return None

        module_name = task_path.as_posix()
        loader = SourceFileLoader(module_name, task_path.absolute().as_posix())
        spec = spec_from_loader(loader.name, loader)
        if not spec:
            raise ModuleNotFoundError(f"Module {module_name} not found")
        module = module_from_spec(spec)
        loader.exec_module(module)
        return module

    elif task_path.suffix == ".ipynb":
        try:
            from inspect_ai._util.notebook import NotebookLoader
        except ImportError:
            return None

        # bail if the code doesn't have a task
        def exec_filter(cells: list[str]) -> bool:
            code = "\n\n".join(cells)
            return code_has_task(code)

        notebook_loader = NotebookLoader(exec_filter)
        return notebook_loader.load_module(task_path.as_posix())

    else:
        raise ModuleNotFoundError(
            f"Invalid extension for task file: {task_path.suffix}"
        )


def code_has_task(code: str) -> bool:
    try:
        tree = ast.parse(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Name):
                        if str(decorator.id) == "task":
                            return True
                    elif (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Name)
                        and str(decorator.func.id) == "task"
                    ):
                        return True
    except SyntaxError:
        pass

    return False
