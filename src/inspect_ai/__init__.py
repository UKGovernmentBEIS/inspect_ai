# ruff: noqa: F401

from typing import TYPE_CHECKING

from inspect_ai._util.lazy import lazy_attributes

__all__ = [
    "__version__",
    "eval",
    "eval_async",
    "eval_retry",
    "eval_retry_async",
    "eval_set",
    "list_tasks",
    "score",
    "score_async",
    "edit_score",
    "recompute_metrics",
    "Epochs",
    "EvalScannerConfig",
    "Task",
    "Tasks",
    "TaskInfo",
    "task",
    "task_with",
    "view",
]


if TYPE_CHECKING:
    __version__: str
    from inspect_ai._eval.eval import eval, eval_async, eval_retry, eval_retry_async
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai._eval.list import list_tasks
    from inspect_ai._eval.registry import task
    from inspect_ai._eval.score import score, score_async
    from inspect_ai._eval.task import Epochs, Task, TaskInfo, task_with
    from inspect_ai._eval.task.scan import EvalScannerConfig
    from inspect_ai._eval.task.tasks import Tasks
    from inspect_ai._view.view import view
    from inspect_ai.agent._human.agent import human_cli
    from inspect_ai.log._metric import recompute_metrics
    from inspect_ai.log._score import edit_score
    from inspect_ai.solver._human_agent import human_agent


def __getattr__(name: str) -> object:
    # ``importlib.metadata`` pulls in email/zipfile/inspect/urllib (~45ms),
    # so resolve the version lazily on first access. ``lazy_attributes``
    # below chains to this for names it doesn't own.
    if name == "__version__":
        from importlib.metadata import version

        globals()["__version__"] = v = version("inspect_ai")
        return v
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


lazy_attributes(
    __name__,
    {
        "eval": "inspect_ai._eval.eval",
        "eval_async": "inspect_ai._eval.eval",
        "eval_retry": "inspect_ai._eval.eval",
        "eval_retry_async": "inspect_ai._eval.eval",
        "eval_set": "inspect_ai._eval.evalset",
        "list_tasks": "inspect_ai._eval.list",
        "task": "inspect_ai._eval.registry",
        "score": "inspect_ai._eval.score",
        "score_async": "inspect_ai._eval.score",
        "Epochs": "inspect_ai._eval.task",
        "Task": "inspect_ai._eval.task",
        "TaskInfo": "inspect_ai._eval.task",
        "task_with": "inspect_ai._eval.task",
        "EvalScannerConfig": "inspect_ai._eval.task.scan",
        "Tasks": "inspect_ai._eval.task.tasks",
        "view": "inspect_ai._view.view",
        "human_cli": "inspect_ai.agent._human.agent",
        "recompute_metrics": "inspect_ai.log._metric",
        "edit_score": "inspect_ai.log._score",
        "human_agent": "inspect_ai.solver._human_agent",
    },
)
