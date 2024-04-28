import ast
import inspect
import os
import re
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from inspect_ai._util.dotenv import dotenv_environ
from inspect_ai._util.error import exception_message, pip_dependency_error
from inspect_ai._util.file import file
from inspect_ai._util.path import chdir_python
from inspect_ai._util.registry import RegistryInfo, is_registry_object, registry_info
from inspect_ai.model import ModelName

from .registry import task_create
from .task import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR, Task, TaskInfo

logger = getLogger(__name__)


def list_tasks(
    globs: str | list[str] = [],
    absolute: bool = False,
    root_dir: Path = Path.cwd(),
    filter: Callable[[TaskInfo], bool] | None = None,
) -> list[TaskInfo]:
    """List the tasks located at the specified locations.

    Args:
        globs (str | list[str]): File location(s). Can be
           globs (e.g. have bash-style wildcards).
        absolute (bool): Return absolute paths (defaults
           to False)
        root_dir (Path): Base directory to scan from
           (defaults to current working directory)
        filter (Callable[[TaskInfo], bool] | None):
           Filtering function.

    Returns:
        List of TaskInfo
    """
    # resovle globs
    globs = globs if isinstance(globs, list) else [globs]

    # build list of tasks to return
    tasks: list[TaskInfo] = []
    files = task_files(globs, root_dir)
    for task_file in files:
        tasks.extend(parse_tasks(task_file, root_dir, absolute))

    # filter if necessary
    tasks = [task for task in tasks if filter is None or filter(task)]

    # return sorted
    return sorted(tasks, key=lambda t: f"{t.file}@{t.name}")


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
        # that inclue an @ index. for this case directly
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


def task_files(globs: list[str] = [], root_dir: Path | None = None) -> list[Path]:
    # root dir
    root_dir = root_dir if root_dir else Path.cwd()

    # no globs is cwds
    if len(globs) == 0:
        return tasks_in_dir(root_dir)

    # resolve the first level of globs
    paths: list[Path] = []
    for glob in globs:
        # we will have matched a set of directories and files
        # (depending on how the user wrote the globs). for
        # each file, add it to to our list if its a task file;
        # for each dir, recursively search it for task files
        expanded = list(root_dir.glob(glob))
        for path in expanded:
            if path.is_dir():
                paths.extend(tasks_in_dir(path))
            elif is_task_path(path):
                paths.append(path)

    return [path.absolute() for path in paths]


def tasks_in_dir(path: Path) -> list[Path]:
    paths: list[Path] = []
    for dir, dirnames, filenames in os.walk(path):
        # compute dir_path
        dir_path = Path(dir)

        # remove dirs that start with . or _
        dirnames[:] = [
            dirname for dirname in dirnames if not is_task_path_excluded(dirname)
        ]

        # select files w/ the right extension
        for filename in filenames:
            file_path = dir_path / filename
            if is_task_path(file_path):
                paths.append(file_path)

    return paths


def load_file_tasks(file: Path) -> list[RegistryInfo]:
    with chdir_python(file.parent.as_posix()), dotenv_environ():
        return _load_task_specs(file)


def create_file_tasks(
    file: Path,
    model: ModelName,
    task_specs: list[str] | list[RegistryInfo] | None = None,
    task_args: dict[str, Any] = {},
) -> list[Task]:
    with chdir_python(file.parent.as_posix()), dotenv_environ():
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
        return tasks


# don't call this function directly, rather, call one of the
# higher level loading functions above (those functions
# change the working directory, this one does not b/c it is
# intended as a helper funciton)
def _load_task_specs(task_path: Path) -> list[RegistryInfo]:
    # load the module
    module = load_task_module(task_path)
    if module:
        # find the tasks in the module
        tasks = inspect.getmembers(module, lambda m: is_registry_object(m, "task"))
        return [registry_info(task[1]) for task in tasks]
    else:
        return []


excluded_pattern = re.compile("^[_\\.].*$")


def is_task_path_excluded(path: str) -> bool:
    return (
        re.match(excluded_pattern, path) is not None
        or path == "env"
        or path == "venv"
        or path == "tests"
    )


def is_task_path(path: Path) -> bool:
    return (
        path.suffix == ".py" or path.suffix == ".ipynb"
    ) and not is_task_path_excluded(path.name)


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
            raise pip_dependency_error(
                "Loading tasks from notebooks", ["ipython", "nbformat"]
            )

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
    tree = ast.parse(code)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name):
                    if str(decorator.id) == "task":
                        return True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name):
                        if str(decorator.func.id) == "task":
                            return True
    return False


def parse_tasks(path: Path, root_dir: Path, absolute: bool) -> list[TaskInfo]:
    # read code from python source file
    if path.suffix.lower() == ".py":
        with file(path.as_posix(), "r", encoding="utf-8") as f:
            code = f.read()

    # read code from notebook
    elif path.suffix.lower() == ".ipynb":
        try:
            from inspect_ai._util.notebook import read_notebook_code
        except ImportError:
            raise pip_dependency_error(
                "Parsing tasks from notebooks", ["ipython", "nbformat"]
            )
        code = read_notebook_code(path)

    # unsupported file type
    else:
        raise ModuleNotFoundError(f"Invalid extension for task file: {path.suffix}")

    # parse the top level tasks out of the code
    tasks: list[TaskInfo] = []
    tree = ast.parse(code)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                result = parse_decorator(node, decorator)
                if result:
                    name, attribs = result
                    tasks.append(
                        TaskInfo(
                            file=task_path(path, root_dir, absolute),
                            name=name,
                            attribs=attribs,
                        )
                    )
    return tasks


def parse_decorator(
    node: ast.FunctionDef, decorator: ast.expr
) -> tuple[str, dict[str, Any]] | None:
    if isinstance(decorator, ast.Name):
        if str(decorator.id) == "task":
            return node.name, {}
    elif isinstance(decorator, ast.Call):
        if isinstance(decorator.func, ast.Name):
            if str(decorator.func.id) == "task":
                return parse_task_decorator(node, decorator)
    return None


def parse_task_decorator(
    node: ast.FunctionDef, decorator: ast.Call
) -> tuple[str, dict[str, Any]]:
    name = node.name
    attribs: dict[str, Any] = {}
    for arg in decorator.keywords:
        if arg.arg is not None:
            try:
                value = ast.literal_eval(arg.value)
                if arg.arg == "name":
                    name = value
                else:
                    attribs[arg.arg] = value
            except ValueError as ex:
                # when parsing tasks, we can't provide the values of expressions that execute code
                logger.debug(
                    f"Error parsing attribute {arg.arg} of task {node.name}: {exception_message(ex)}"
                )
                pass
    return name, attribs


# manage relative vs. absolute paths
def task_path(path: Path, root_dir: Path, absolute: bool) -> str:
    if absolute:
        return path.resolve().as_posix()
    else:
        return path.relative_to(root_dir.resolve()).as_posix()
