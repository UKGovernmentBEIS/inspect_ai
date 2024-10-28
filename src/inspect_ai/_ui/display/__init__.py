from .display import (
    Display,
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    clear_task_screen,
    init_task_screen,
    task_screen,
)
from .rich import rich_display


def display() -> Display:
    return rich_display()


__all__ = [
    "display",
    "Display",
    "TaskCancelled",
    "TaskError",
    "TaskProfile",
    "TaskSuccess",
    "task_screen",
    "clear_task_screen",
    "init_task_screen",
]
