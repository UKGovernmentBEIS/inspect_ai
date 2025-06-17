from anyio.abc import TaskGroup

_eval_task_group: TaskGroup | None = None


def init_eval_task_group(tg: TaskGroup | None) -> None:
    global _eval_task_group
    _eval_task_group = tg


def eval_task_group() -> TaskGroup:
    global _eval_task_group
    if _eval_task_group is None:
        raise RuntimeError("Task group has not been initialized")
    return _eval_task_group
