# ruff: noqa: F401 F403 F405

from importlib.metadata import version as importlib_version

from inspect_ai._eval.eval import eval, eval_async, eval_retry, eval_retry_async
from inspect_ai._eval.list import list_tasks
from inspect_ai._eval.registry import task
from inspect_ai._eval.score import score, score_async
from inspect_ai._eval.task import Task, TaskInfo, Tasks
from inspect_ai._util.constants import PKG_NAME

__version__ = importlib_version(PKG_NAME)


__all__ = [
    "__version__",
    "eval",
    "eval_async",
    "eval_retry",
    "eval_retry_async",
    "score",
    "score_async",
    "Task",
    "TaskInfo",
    "Tasks",
    "task",
    "list_tasks",
]
