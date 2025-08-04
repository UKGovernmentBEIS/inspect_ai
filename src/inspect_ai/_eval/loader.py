import ast
import contextlib
import inspect
import os
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Tuple, cast

from typing_extensions import overload

from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.util import task_file, task_run_dir
from inspect_ai._util.decorator import parse_decorators
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.path import chdir_python, cwd_relative_path
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_create,
    registry_info,
    registry_lookup,
    registry_params,
)
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.model import Model
from inspect_ai.scorer._scorer import Scorer, ScorerSpec, scorer_create
from inspect_ai.solver._bridge import bridge
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentSpec, SandboxEnvironmentType
from inspect_ai.util._sandbox.environment import (
    resolve_sandbox_environment,
)
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

from .list import task_files
from .registry import task_create
from .task import PreviousTask, Task, TaskInfo
from .task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR
from .task.run import eval_log_sample_source
from .task.tasks import Tasks

logger = getLogger(__name__)


def resolve_tasks(
    tasks: Tasks,
    task_args: dict[str, Any],
    model: Model,
    model_roles: dict[str, Model] | None,
    sandbox: SandboxEnvironmentType | None,
    sample_shuffle: bool | int | None,
) -> list[ResolvedTask]:
    def as_resolved_tasks(tasks: list[Task]) -> list[ResolvedTask]:
        # shuffle data in tasks if requested
        if sample_shuffle:
            for task in tasks:
                if not task.dataset.shuffled:
                    task.dataset.shuffle(
                        None if sample_shuffle is True else sample_shuffle
                    )

        return [
            ResolvedTask(
                task=task,
                task_args=resolve_task_args(task),
                task_file=task_file(task, relative=True),
                model=task.model or model,
                model_roles=task.model_roles or model_roles,
                sandbox=resolve_task_sandbox(task, sandbox),
                sequence=sequence,
            )
            for sequence, task in enumerate(tasks)
        ]

    # reflect resolved tasks right back
    if isinstance(tasks, ResolvedTask):
        return [tasks]
    elif isinstance(tasks, list) and isinstance(tasks[0], ResolvedTask):
        return cast(list[ResolvedTask], tasks)

    # take empty lists out of play
    if isinstance(tasks, list) and len(tasks) == 0:
        return as_resolved_tasks(load_tasks(None, task_args))

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
                loaded_task_args = previous_task.task_args
                loaded_task = previous_task.task
            else:
                loaded_task_args = previous_task.task_args
                loaded_task = load_tasks([previous_task.task], loaded_task_args)[0]
            if sample_shuffle is not None:
                if not loaded_task.dataset.shuffled:
                    loaded_task.dataset.shuffle(
                        None if sample_shuffle is True else sample_shuffle
                    )
            loaded_tasks.append(loaded_task)
            loaded_tasks_args.append(loaded_task_args)

        return [
            ResolvedTask(
                task=loaded_task,
                task_args=loaded_task_args,
                task_file=previous_task.log.eval.task_file,
                model=previous_task.model or loaded_task.model or model,
                model_roles=(
                    previous_task.model_roles or loaded_task.model_roles or model_roles
                ),
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
    return as_resolved_tasks(load_tasks(cast(list[str] | None, tasks), task_args))


def resolve_task_args(task: Task) -> dict[str, Any]:
    # was the task instantiated via the registry or a decorator?
    # if so then we can get the task_args from the registry.
    try:
        task_args = dict(registry_params(task))
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
        if isinstance(resolved_sandbox.config, str):
            file_path = Path(resolved_sandbox.config)
            if not file_path.is_absolute():
                file_path = Path(task_run_dir(task)) / file_path
                resolved_sandbox = SandboxEnvironmentSpec(
                    resolved_sandbox.type, file_path.as_posix()
                )

    # return resolved sandbox
    return resolved_sandbox


def load_tasks(
    task_specs: list[str] | None, task_args: dict[str, Any] = {}
) -> list[Task]:
    """Load one more more tasks (if no tasks are specified, load from the current working directory"""
    # load tasks
    return [
        spec
        for task_spec in (task_specs if task_specs else [Path.cwd().as_posix()])
        for spec in load_task_spec(task_spec, task_args)
    ]


def load_task_spec(task_spec: str, task_args: dict[str, Any] = {}) -> list[Task]:
    # task in a python package
    if registry_lookup("task", task_spec) is not None:
        # create the task from a python package
        return [task_create(task_spec, **task_args)]
    else:
        # load tasks from glob
        return create_tasks([task_spec], task_args)


def create_tasks(
    globs: list[str],
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
            tasks.extend(create_file_tasks(task_path, [spec_split[1]], task_args))
        else:
            # if the glob is the root dir then set it to empty (will result in
            # enumeration of the root dir)
            target = [] if Path(glob).resolve() == root_dir.resolve() else [glob]
            files = task_files(target, root_dir)
            files = sorted(files, key=lambda f: f.as_posix())
            for file in files:
                tasks.extend(create_file_tasks(file, None, task_args))
    return tasks


def load_file_tasks(file: Path) -> None:
    with chdir_python(file.parent.as_posix()):
        _load_task_specs(file)


def create_file_tasks(
    file: Path,
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
            task = task_create(task_spec, **task_args)
            setattr(task, TASK_FILE_ATTR, file.as_posix())
            setattr(task, TASK_RUN_DIR_ATTR, run_dir)
            tasks.append(task)

            # warn that chdir has been removed
            if "chdir" in task.attribs:
                warn_once(
                    logger,
                    "The 'chdir' task attribute is no longer supported "
                    + "(you should write your tasks to not depend on their runtime working directory)",
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


@overload
def load_module(
    module_path: Path, filter: Callable[[str], bool]
) -> ModuleType | None: ...


@overload
def load_module(module_path: Path, filter: None = None) -> ModuleType: ...


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
    solver_file, solver_name = parse_spec_str(spec.solver)

    # switch contexts if we are loading from a file
    create_cm = (
        chdir_python(solver_file.parent.as_posix())
        if solver_file is not None
        else contextlib.nullcontext()
    )

    # pretty solver name for error messages
    pretty_solver_file = (
        cwd_relative_path(solver_file.as_posix()) if solver_file else None
    )

    with create_cm:
        # if there is no solver file then just create from the registry by name
        if solver_file is None:
            if solver_name is None:
                raise ValueError(f"Unable to resolve solver name from {spec.solver}")
            elif registry_lookup("solver", solver_name) is not None:
                return registry_create("solver", solver_name, **spec.args)
            elif registry_lookup("agent", solver_name) is not None:
                agent = registry_create("agent", solver_name, **spec.args)
                return as_solver(agent)
            else:
                raise ValueError(
                    f"Unknown solver {solver_name} (not registered as a @solver or @agent)"
                )

        # we do have a solver file
        else:
            # load the module and parse decorators
            solver_module = load_module(solver_file)
            solver_decorators = parse_decorators(solver_file, "solver")
            agent_decorators = parse_decorators(solver_file, "agent")

            # if there is no solver_name see if we can discover it
            if solver_name is None:
                if len(solver_decorators) == 1:
                    # decorator based solver
                    solver_name = solver_decorators[0][0]
                elif len(agent_decorators) == 1:
                    # decorator based agent
                    solver_name = agent_decorators[0][0]
                elif len(solver_decorators) == 0 and len(agent_decorators) == 0:
                    # see if we can find an agent based solver
                    functions = [
                        function
                        for function in inspect.getmembers(
                            solver_module, inspect.isfunction
                        )
                        if function[1].__module__ == solver_module.__name__
                    ]
                    agent_functions = [
                        function
                        for function in functions
                        if "agent" in function[0] and not function[0].startswith("_")
                    ]
                    if len(agent_functions) == 1:
                        # agent based solver
                        solver_name = agent_functions[0][0]

                    elif len(agent_functions) == 0:
                        raise PrerequisiteError(
                            f"The source file {pretty_solver_file} does not contain any @solver, @agent or bridged agent functions."
                        )
                    else:
                        raise PrerequisiteError(
                            f"The source file {pretty_solver_file} has more than one bridged agent function (qualify which agent using e.g. '{solver_file.name}@agent_fn')"
                        )
                elif len(solver_decorators) > 1:
                    raise PrerequisiteError(
                        f"The source file {pretty_solver_file} has more than one @solver function (qualify which solver using e.g. '{solver_file.name}y@solver_fn')"
                    )
                else:
                    raise PrerequisiteError(
                        f"The source file {pretty_solver_file} has more than one @agent function (qualify which agent using e.g. '{solver_file.name}y@agent_fn')"
                    )

            # create decorator based solvers using the registry
            if any(solver[0] == solver_name for solver in solver_decorators):
                return registry_create("solver", solver_name, **spec.args)

            # create decorator based agents using the registry
            elif any(agent[0] == solver_name for agent in agent_decorators):
                agent = registry_create("agent", solver_name, **spec.args)
                return as_solver(agent)

            # create bridge based solvers by calling the function and wrapping it in bridge()
            else:
                agent_fn = getattr(solver_module, solver_name, None)
                if inspect.isfunction(agent_fn):
                    return bridge(agent_fn(**spec.args))
                elif agent_fn is not None:
                    raise PrerequisiteError(
                        f"The object {solver_name} in file {pretty_solver_file} is not a Python function."
                    )
                else:
                    raise PrerequisiteError(
                        f"The function {solver_name} was not found in file {pretty_solver_file}."
                    )


def scorer_from_spec(spec: ScorerSpec, task_path: Path | None, **kwargs: Any) -> Scorer:
    """
    Load a scorer

    Args:
        spec: The scorer spec
        task_path: An optional path to the task file
        **kwargs: Additional keyword arguments passed to the scorer initialization

    Returns:
        Scorer: the loaded scorer

    Raises:
        PrerequisiteError: If the scorer cannot be found, loaded, or lacks required type annotations
    """
    # resolve @ reference
    scorer_file, scorer_name = parse_spec_str(spec.scorer)

    # switch contexts if we are loading from a file
    create_cm = (
        chdir_python(scorer_file.parent.as_posix())
        if scorer_file is not None
        else contextlib.nullcontext()
    )

    # pretty solver name for error messages
    pretty_scorer_file = (
        cwd_relative_path(scorer_file.as_posix()) if scorer_file else None
    )

    # See if the scorer doesn't have type annotations. Currently the registry will not load
    # the function without type annotations.
    # TODO: We could consider calling this ourselves if we're certain it is what we're looking for
    def validate_scorer(scorer_fn: Scorer, task_name: str, task_path: str) -> None:
        signature = inspect.signature(scorer_fn)
        if signature.return_annotation is inspect.Signature.empty:
            raise PrerequisiteError(
                f"The scorer '{task_name}' in the file '{task_path}' requires a 'Scorer' return type annotation. Please add the 'Scorer' type annotation to load the scorer."
            )

    with create_cm:
        # is there a scorer file being provided? if not, load from registry
        if scorer_file is None:
            if scorer_name is None:
                raise ValueError(f"Unable to resolve scorer name from {spec.scorer}")

            try:
                return scorer_create(scorer_name, **kwargs)
            except ValueError:
                # We need a valid path to a scorer file to try to load the scorer from there
                if not task_path:
                    raise PrerequisiteError(
                        f"The scorer '{scorer_name}' couldn't be loaded. Please provide a path to the file containing the scorer using the '--scorer' parameter"
                    )

                task_pretty_path = task_path.as_posix()
                if not task_path.exists():
                    raise PrerequisiteError(
                        f"The scorer `{scorer_name}` couldn't be loaded. The file '{task_pretty_path}' was not found. Please provide a path to the file containing the scorer using the '--scorer' parameter"
                    )

                # We have the path to a file, so load that and try again
                try:
                    load_module(task_path)
                    scorer_fn = scorer_create(scorer_name, **kwargs)
                    validate_scorer(scorer_fn, scorer_name, task_pretty_path)
                    return scorer_fn
                except ValueError:
                    # we still couldn't load this, request the user provide a path
                    raise PrerequisiteError(
                        f"The scorer '{scorer_name}' in the file '{task_pretty_path}' couldn't be loaded. Please provide a path to the file containing the scorer using the '--scorer' parameter."
                    )
                except ModuleNotFoundError:
                    # we still couldn't load this, request the user provide a path
                    raise PrerequisiteError(
                        f"The scorer '{scorer_name}' in the file '{task_pretty_path}' couldn't be loaded. Please provide a path to the file containing the scorer using the '--scorer' parameter."
                    )

        # solver is a path, so load it that way
        else:
            load_module(scorer_file)
            decorators = parse_decorators(scorer_file, "scorer")

            # if there is no solver_name see if we can discover it
            if scorer_name is None:
                if len(decorators) == 1:
                    # decorator based solver
                    scorer_name = decorators[0][0]
                elif len(decorators) == 0:
                    raise PrerequisiteError(
                        f"The source file {pretty_scorer_file} does not contain any @scorer functions."
                    )
                else:
                    raise PrerequisiteError(
                        f"The source file {pretty_scorer_file} has more than one @solver function (qualify which solver using e.g. '{scorer_file.name}y@solver_fn')"
                    )

            # create decorator based solvers using the registry
            if any(solver[0] == scorer_name for solver in decorators):
                scorer_fn = scorer_create(scorer_name, **kwargs)
                validate_scorer(scorer_fn, scorer_name, pretty_scorer_file or "")
                return scorer_fn
            else:
                raise PrerequisiteError(
                    f"The function {scorer_name} was not found in file {pretty_scorer_file}."
                )


def parse_spec_str(spec_str: str) -> Tuple[Path | None, str | None]:
    spec_split = split_spec(spec_str)
    if spec_split[1] is not None:
        file: Path | None = Path(spec_split[0]).resolve()
        name: str | None = spec_split[1]
    elif Path(spec_split[0]).exists():
        file = Path(spec_split[0]).resolve()
        name = None
    else:
        file = None
        name = spec_split[0]
    return file, name
