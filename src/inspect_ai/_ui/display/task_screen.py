from contextvars import ContextVar

from .display import TaskScreen


def task_screen() -> TaskScreen:
    screen = _task_screen.get(None)
    if screen is None:
        raise RuntimeError(
            "console input function called outside of running evaluation."
        )
    return screen


def init_task_screen(screen: TaskScreen) -> None:
    _task_screen.set(screen)


def clear_task_screen() -> None:
    _task_screen.set(None)


_task_screen: ContextVar[TaskScreen | None] = ContextVar("task_screen", default=None)
