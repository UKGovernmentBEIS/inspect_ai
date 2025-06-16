from anyio.abc import TaskGroup

_task_group: TaskGroup | None = None


def init_task_group(tg: TaskGroup | None) -> None:
    global _task_group
    _task_group = tg


def get_task_group() -> TaskGroup:
    global _task_group
    if _task_group is None:
        raise RuntimeError("Task group has not been initialized")
    return _task_group
