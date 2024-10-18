import inspect
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, TypeVar, cast, overload

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.package import get_installed_package_name
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
from .task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR

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
    if not task:
        raise PrerequisiteError(f"Task named '{name}' not found.")
    task_info = registry_info(task)
    task_params: list[str] = task_info.metadata["params"]
    task_args: dict[str, Any] = {}
    for param in kwargs.keys():
        if param in task_params:
            task_args[param] = kwargs[param]
        elif param != MODEL_PARAM:
            if "kwargs" in task_params:
                task_args[param] = kwargs[param]
            else:
                logger.warning(f"param '{param}' not used by task '{name}'")

    return cast(Task, registry_create("task", name, **task_args))


@overload
def task(func: TaskType) -> TaskType: ...


@overload
def task(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[TaskType], TaskType]: ...


def task(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering tasks.

    Args:
      *args: Function returning `Task` targeted by
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
        # Get the name and parameters of the task
        task_name = registry_name(task_type, name or getattr(task_type, "__name__"))
        params = list(inspect.signature(task_type).parameters.keys())

        # Create and return the wrapper function
        def wrapper(*w_args: Any, **w_kwargs: Any) -> Task:
            # Create the task
            task_instance = task_type(*w_args, **w_kwargs)

            # Tag the task with registry information
            registry_tag(
                task_type,
                task_instance,
                RegistryInfo(
                    type="task",
                    name=task_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # if its not from an installed package then it is a "local"
            # module import, so set its task file and run dir
            if get_installed_package_name(task_type) is None:
                module = inspect.getmodule(task_type)
                if module and module.__file__:
                    file = Path(module.__file__)
                    setattr(task_instance, TASK_FILE_ATTR, file.as_posix())
                    setattr(task_instance, TASK_RUN_DIR_ATTR, file.parent.as_posix())

            # Return the task instance
            return task_instance

        # Register the task and return the wrapper
        return task_register(
            task=cast(TaskType, wrapper), name=task_name, attribs=attribs, params=params
        )

    if args:
        # The decorator was used without arguments: @task
        func = args[0]
        return create_task_wrapper(func)
    else:
        # The decorator was used with arguments: @task(name="foo")
        def decorator(func: TaskType) -> TaskType:
            return create_task_wrapper(func)

        return decorator
