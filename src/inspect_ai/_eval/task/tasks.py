from typing import Callable, TypeAlias

from .resolved import ResolvedTask
from .task import PreviousTask, Task, TaskInfo

Tasks: TypeAlias = (
    str
    | PreviousTask
    | ResolvedTask
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
    | list[PreviousTask]
    | list[ResolvedTask]
    | list[TaskInfo]
    | list[Task]
    | list[Callable[..., Task]]
    | list[type[Task]]
    | None
)
r"""One or more tasks.

Tasks to be evaluated. Many forms of task specification are
supported including directory names, task functions, task
classes, and task instances (a single task or list of tasks
can be specified). None is a request to read a task out
of the current working directory.
"""
