import inspect
import logging
from copy import deepcopy
from typing import Any, Callable, TypeVar, cast

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_info,
    registry_lookup,
    registry_name,
    registry_tag,
)
from inspect_ai.model import ModelName

from .task import Task

MODEL_PARAM = "model"

logger = logging.getLogger(__name__)


TaskType = TypeVar("TaskType", bound=Callable[..., Task])


def task_register(
    task: TaskType, name: str, attribs: dict[str, Any], params: list[str]
) -> TaskType:
    r"""Register a task.

    Args:
        task (TaskType):
            function that returns a Task or class
            deriving from Task
        name (str): Name of task
        attribs (dict[str,Any]): Attributes of task decorator
        params (list[str]): Task parameter names

    Returns:
        Task with registry attributes.
    """
    registry_add(
        task,
        RegistryInfo(
            type="task", name=name, metadata=dict(attribs=attribs, params=params)
        ),
    )
    return task


def task_create(name: str, model: ModelName, **kwargs: Any) -> Task:
    r"""Create a Task based on its registered name.

    Tasks can be a function that returns a Task or a
    class deriving from Task.

    Args:
        name (str): Name of task (Optional, defaults to object name)
        model (ModelName): Model name
        **kwargs (dict): Optional creation arguments for the task

    Returns:
        Task with registry info attribute
    """
    # bring in model arg (first deepcopy as we will mutate it)
    # add model to task_args
    kwargs = deepcopy(kwargs)
    kwargs[MODEL_PARAM] = model

    # match kwargs params to signature (warn if param not found)
    # (note that we always pass the 'model' param but tasks aren't
    # required to consume it, so we don't warn for 'model')
    task = registry_lookup("task", name)
    task_info = registry_info(task)
    task_params: list[str] = task_info.metadata["params"]
    task_args: dict[str, Any] = {}
    for param in kwargs.keys():
        if param in task_params:
            task_args[param] = kwargs[param]
        elif param != MODEL_PARAM:
            logger.warning(f"param '{param}' not used by task '{name}'")

    return cast(Task, registry_create("task", name, **task_args))


def task(*task: TaskType | None, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering tasks.

    Args:
      *task (TaskType): Function returning `Task` targeted by
        plain task decorator without attributes (e.g. `@task`)
      name (str | None):
        Optional name for task. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.
      **attribs: (dict[str,Any]): Additional task attributes.

    Returns:
        Task with registry attributes.
    """

    def create_task_wrapper(task_type: TaskType) -> TaskType:
        # get the name and params
        task_name = registry_name(task_type, name or getattr(task_type, "__name__"))
        params = list(inspect.signature(task_type).parameters.keys())

        # create and return the wrapper
        def wrapper(*w_args: Any, **w_kwargs: Any) -> Task:
            # create the task
            task = task_type(*w_args, **w_kwargs)

            # tag it
            registry_tag(
                task_type,
                task,
                RegistryInfo(
                    type="task",
                    name=task_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # return it
            return task

        return task_register(
            task=cast(TaskType, wrapper), name=task_name, attribs=attribs, params=params
        )

    if task:
        return create_task_wrapper(cast(TaskType, task[0]))
    else:
        return create_task_wrapper
