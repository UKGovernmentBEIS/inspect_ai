import inspect
import logging
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast, overload

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.package import get_installed_package_name
from inspect_ai._util.registry import (
    RegistryInfo,
    extract_named_params,
    registry_add,
    registry_create,
    registry_info,
    registry_lookup,
    registry_name,
    registry_tag,
)

from .task import Task
from .task.constants import TASK_ALL_PARAMS_ATTR, TASK_FILE_ATTR, TASK_RUN_DIR_ATTR
from .task.task_source import TaskSource

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


def task_create(name: str, **kwargs: Any) -> Task:
    r"""Create a Task based on its registered name.

    Tasks can be a function that returns a Task or a
    class deriving from Task.

    Args:
        name (str): Name of task (Optional, defaults to object name)
        **kwargs (dict): Optional creation arguments for the task

    Returns:
        Task with registry info attribute
    """
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
        if param in task_params or "kwargs" in task_params:
            task_args[param] = kwargs[param]
        else:
            logger.warning(f"param '{param}' not used by task '{name}'")

    return registry_create("task", name, **task_args)


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
        @wraps(task_type)
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

            # extract all task parameters including defaults
            named_params = extract_named_params(task_type, True, *w_args, **w_kwargs)
            setattr(task_instance, TASK_ALL_PARAMS_ATTR, named_params)

            # if its not from an installed package then it is a "local"
            # module import, so set its task file and run dir
            if get_installed_package_name(task_type) is None:
                module = inspect.getmodule(task_type)
                if module and hasattr(module, "__file__") and module.__file__:
                    file = Path(getattr(module, "__file__"))
                    setattr(task_instance, TASK_FILE_ATTR, file.as_posix())
                    setattr(task_instance, TASK_RUN_DIR_ATTR, file.parent.as_posix())

            # Return the task instance
            return task_instance

        # functools.wraps overrides the return type annotation of the inner function, so
        # we explicitly set it again
        wrapper.__annotations__["return"] = Task

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


TaskSourceType = TypeVar("TaskSourceType", bound=Callable[..., TaskSource])


def task_source_register(
    task_source: TaskSourceType,
    name: str,
    attribs: dict[str, Any],
    params: list[str],
) -> TaskSourceType:
    r"""Register a task source (function that returns a `TaskSource`)."""
    registry_add(
        task_source,
        RegistryInfo(
            type="task_source",
            name=name,
            metadata=dict(attribs=attribs, params=params),
        ),
    )
    return task_source


def task_source_create(name: str, **kwargs: Any) -> TaskSource:
    r"""Create a `TaskSource` based on its registered name.

    Args:
        name: Name of the registered task source.
        **kwargs: Optional creation arguments (matched against the source's
            parameters; unused params warn, mirroring `task_create`).

    Returns:
        A `TaskSource` instance with registry info attached.
    """
    source = registry_lookup("task_source", name)
    if not source:
        raise PrerequisiteError(f"Task source named '{name}' not found.")
    info = registry_info(source)
    params: list[str] = info.metadata["params"]
    args: dict[str, Any] = {}
    for param in kwargs.keys():
        if param in params or "kwargs" in params:
            args[param] = kwargs[param]
        else:
            logger.warning(f"param '{param}' not used by task source '{name}'")
    # call the registered wrapper directly (it tags the instance with registry
    # info); registry_create only invokes factories whose return-type name
    # matches the registry type, which "task_source" / TaskSource does not
    return cast(Callable[..., TaskSource], source)(**args)


@overload
def task_source(func: TaskSourceType) -> TaskSourceType: ...


@overload
def task_source(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[TaskSourceType], TaskSourceType]: ...


def task_source(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering task sources.

    Mirrors `@task`: registers a function that returns a `TaskSource` so it can
    be referenced and loaded by name (e.g. `eval("file.py@my_source")` or
    `inspect eval file.py@my_source -T arg=value`) and parameterized.

    Args:
      *args: Function returning `TaskSource` targeted by a plain decorator
        without attributes (e.g. `@task_source`).
      name: Optional name for the source (defaults to the function name).
      **attribs: Additional task source attributes.

    Returns:
        The registered task source wrapper.
    """

    def create_task_source_wrapper(source_type: TaskSourceType) -> TaskSourceType:
        source_name = registry_name(
            source_type, name or getattr(source_type, "__name__")
        )
        params = list(inspect.signature(source_type).parameters.keys())

        @wraps(source_type)
        def wrapper(*w_args: Any, **w_kwargs: Any) -> TaskSource:
            source_instance = source_type(*w_args, **w_kwargs)

            # tag the source with registry information
            registry_tag(
                source_type,
                source_instance,
                RegistryInfo(
                    type="task_source",
                    name=source_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # extract all params including defaults
            named_params = extract_named_params(source_type, True, *w_args, **w_kwargs)
            setattr(source_instance, TASK_ALL_PARAMS_ATTR, named_params)

            # for a local (non-package) module, record the source file / run dir
            if get_installed_package_name(source_type) is None:
                module = inspect.getmodule(source_type)
                if module and hasattr(module, "__file__") and module.__file__:
                    file = Path(getattr(module, "__file__"))
                    setattr(source_instance, TASK_FILE_ATTR, file.as_posix())
                    setattr(source_instance, TASK_RUN_DIR_ATTR, file.parent.as_posix())

            return source_instance

        # functools.wraps overrides the return annotation, so set it again
        wrapper.__annotations__["return"] = TaskSource

        return task_source_register(
            task_source=cast(TaskSourceType, wrapper),
            name=source_name,
            attribs=attribs,
            params=params,
        )

    if args:
        # used without arguments: @task_source
        return create_task_source_wrapper(args[0])
    else:
        # used with arguments: @task_source(name="foo")
        def decorator(func: TaskSourceType) -> TaskSourceType:
            return create_task_source_wrapper(func)

        return decorator
