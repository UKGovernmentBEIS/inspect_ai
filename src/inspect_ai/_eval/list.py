import ast
import os
import re
from logging import getLogger
from pathlib import Path
from typing import Any, Callable

from inspect_ai._util.error import exception_message
from inspect_ai._util.file import file

from .task import TaskInfo

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
    # resolve globs
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
            return []

        code = read_notebook_code(path)

    # unsupported file type
    else:
        raise ModuleNotFoundError(f"Invalid extension for task file: {path.suffix}")

    # parse the top level tasks out of the code
    tasks: list[TaskInfo] = []
    try:
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
    except SyntaxError:
        pass

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
