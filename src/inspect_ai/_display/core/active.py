import sys
from contextvars import ContextVar

import rich

from inspect_ai._util.display import display_type
from inspect_ai.util._trace import trace_enabled

from ..rich.display import RichDisplay
from ..textual.display import TextualDisplay
from .display import Display, TaskScreen


def display() -> Display:
    global _active_display
    if _active_display is None:
        if (
            display_type() == "full"
            and sys.stdout.isatty()
            and not trace_enabled()
            and not rich.get_console().is_jupyter
        ):
            _active_display = TextualDisplay()
        else:
            _active_display = RichDisplay()

    return _active_display


_active_display: Display | None = None


def task_screen() -> TaskScreen:
    screen = _active_task_screen.get(None)
    if screen is None:
        raise RuntimeError(
            "console input function called outside of running evaluation."
        )
    return screen


def init_task_screen(screen: TaskScreen) -> None:
    _active_task_screen.set(screen)


def clear_task_screen() -> None:
    _active_task_screen.set(None)


_active_task_screen: ContextVar[TaskScreen | None] = ContextVar(
    "task_screen", default=None
)
