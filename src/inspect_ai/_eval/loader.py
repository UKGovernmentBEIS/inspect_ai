import ast
import contextlib
import os
from dataclasses import dataclass, field
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from inspect_ai._eval.task.util import task_file, task_run_dir
from inspect_ai._util.decorator import parse_decorators
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.path import chdir_python
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_create,
    registry_info,
    registry_lookup,
    registry_params,
)
from inspect_ai.model import Model, ModelName
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentSpec, SandboxEnvironmentType
from inspect_ai.util._sandbox.environment import resolve_sandbox_environment
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
    sandbox: SandboxEnvironmentSpec | None
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
    sandbox: SandboxEnvironmentType | None,
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
    task: Task, sandbox: SandboxEnvironmentType | None
) -> SandboxEnvironmentSpec | None:
    # do the resolution
    resolved_sandbox = resolve_sandbox_environment(sandbox) or task.sandbox

    # if we have a sandbox with no config, see if there are implcit
    # config files available for the provider
    if resolved_sandbox is not None:
        # look for default
        if resolved_sandbox.config is None:
            # get config files for this type
            sandboxenv_type = registry_find_sandboxenv(resolved_sandbox.type)
            config_files_fn = cast(
                Callable[..., list[str]], getattr(sandboxenv_type, "config_files")
            )
            config_files = config_files_fn()

            # probe for them in task src dir
            src_dir = task_run_dir(task)
            for config_file in config_files:
                config_file_path = os.path.join(src_dir, config_file)
                if os.path.isfile(config_file_path):
                    resolved_sandbox = SandboxEnvironmentSpec(
                        resolved_sandbox.type, config_file
                    )
                    break

        # resolve relative paths
        if resolved_sandbox.config is not None:
            file_path = Path(resolved_sandbox.config)
            if not file_path.is_absolute():
                file_path = Path(task_run_dir(task)) / file_path
                resolved_sandbox = SandboxEnvironmentSpec(
                    resolved_sandbox.type, file_path.as_posix()
                )

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
        spec_split = split_spec(glob)
        if spec_split[1] is not None:
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


def load_file_tasks(file: Path) -> None:
    with chdir_python(file.parent.as_posix()):
        _load_task_specs(file)


def create_file_tasks(
    file: Path,
    model: ModelName,
    task_specs: list[str] | list[RegistryInfo] | None = None,
    task_args: dict[str, Any] = {},
) -> list[Task]:
    run_dir = file.parent.resolve().as_posix()
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
            setattr(task, TASK_RUN_DIR_ATTR, run_dir)
            tasks.append(task)

            # warn about deprecated chdir attrib
            if "chdir" in task.attribs:
                warn_once(
                    logger,
                    "The 'chdir' task attribute is deprecated (tasks now always chdir)",
                )

        return tasks


# don't call this function directly, rather, call one of the
# higher level loading functions above (those functions
# change the working directory, this one does not b/c it is
# intended as a helper function)
def _load_task_specs(task_path: Path) -> list[str]:
    # load the module
    module = load_module(task_path, code_has_task)
    if module:
        # find the tasks in the module
        tasks = parse_decorators(task_path, "task")
        return [task[0] for task in tasks]
    else:
        return []


def split_spec(spec: str) -> tuple[str, str | None]:
    parts = spec.rsplit("@", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    else:
        return spec, None


def load_module(
    module_path: Path, filter: Callable[[str], bool] | None = None
) -> ModuleType | None:
    if module_path.suffix == ".py":
        # bail if the code doesn't pass the filter
        with open(module_path, "r", encoding="utf-8") as file:
            if filter and not filter(file.read()):
                return None

        module_name = module_path.as_posix()
        loader = SourceFileLoader(module_name, module_path.absolute().as_posix())
        spec = spec_from_loader(loader.name, loader)
        if not spec:
            raise ModuleNotFoundError(f"Module {module_name} not found")
        module = module_from_spec(spec)
        loader.exec_module(module)
        return module

    elif module_path.suffix == ".ipynb":
        try:
            from inspect_ai._util.notebook import NotebookLoader
        except ImportError:
            return None

        # bail if the code doesn't pass the filter
        def exec_filter(cells: list[str]) -> bool:
            code = "\n\n".join(cells)
            return not filter or filter(code)

        notebook_loader = NotebookLoader(exec_filter)
        return notebook_loader.load_module(module_path.as_posix())

    else:
        raise ModuleNotFoundError(
            f"Invalid extension for task file: {module_path.suffix}"
        )


def code_has_decorator(code: str, decorator: str) -> bool:
    try:
        tree = ast.parse(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        if str(dec.id) == decorator:
                            return True
                    elif (
                        isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Name)
                        and str(dec.func.id) == decorator
                    ):
                        return True
    except SyntaxError:
        pass

    return False


def code_has_task(code: str) -> bool:
    return code_has_decorator(code, "task")


def as_solver_spec(solver: Solver) -> SolverSpec:
    if not is_registry_object(solver):
        raise PrerequisiteError(
            f"The solver {getattr(solver, '__name__', '<unknown>')} was not created by a function decorated with @solver so cannot be recorded."
        )
    return SolverSpec(solver=registry_info(solver).name, args=registry_params(solver))


def solver_from_spec(spec: SolverSpec) -> Solver:
    # resolve @ reference
    spec_split = split_spec(spec.solver)
    if spec_split[1] is not None:
        solver_file: Path | None = Path(spec_split[0]).resolve()
        solver_name: str | None = spec_split[1]
    elif Path(spec_split[0]).exists():
        solver_file = Path(spec_split[0]).resolve()
        solver_name = None
    else:
        solver_file = None
        solver_name = spec_split[0]

    # switch contexts if we are loading from a file
    create_cm = (
        chdir_python(solver_file.parent.as_posix())
        if solver_file is not None
        else contextlib.nullcontext()
    )

    with create_cm:
        # if we have a file then we need to load it and (if required) determine the solver name
        if solver_file is not None:
            # load the module so that registry_create works
            load_module(solver_file)

            # if there is no solver_name we need to discover the first @solver
            if solver_name is None:
                solvers = parse_decorators(solver_file, "solver")
                if len(solvers) == 0:
                    raise PrerequisiteError(
                        f"The source file {solver_file.as_posix()} does not contain any @solver functions."
                    )
                if len(solvers) > 1:
                    raise PrerequisiteError(
                        f"The source file {solver_file.as_posix()} has more than one @solver function (qualify which solver using file.py@solver)"
                    )
                solver_name = solvers[0][0]

        # make mypy happy and catch unexpected branching
        if solver_name is None:
            raise ValueError(f"Unable to resolve solver name from {spec.solver}")

        solver = cast(Solver, registry_create("solver", solver_name, **spec.args))
        return solver
