from pathlib import Path
from typing import Any, cast

from inspect_ai._util.registry import (
    registry_info,
    registry_lookup,
)
from inspect_ai.model import Model, ModelName

from .list import create_tasks
from .registry import task_create
from .task import Task, TaskInfo, Tasks


def resolve_tasks(
    tasks: Tasks,
    model: Model,
    task_args: dict[str, Any],
) -> list[Task]:
    # take empty lists out of play
    if isinstance(tasks, list) and len(tasks) == 0:
        return load_tasks(None, model, task_args)

    # simple cases of passing us Task objects
    if isinstance(tasks, Task):
        return [tasks]
    elif isinstance(tasks, list) and isinstance(tasks[0], Task):
        return cast(list[Task], tasks)

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
    return load_tasks(cast(list[str] | None, tasks), model, task_args)


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
