from anyio.abc import TaskGroup

_eval_task_group: TaskGroup | None = None


def init_eval_task_group(tg: TaskGroup | None) -> None:
    global _eval_task_group
    _eval_task_group = tg


def eval_task_group() -> TaskGroup | None:
    global _eval_task_group
    return _eval_task_group
