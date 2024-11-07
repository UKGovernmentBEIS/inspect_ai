import os
import sys
from contextvars import ContextVar

from inspect_ai._util.ansi import no_ansi

from ..rich.rich import RichDisplay
from ..textual.textual import TextualDisplay
from .display import Display, TaskScreen


def display() -> Display:
    global _active_display
    if _active_display is None:
        have_tty = sys.stdout.isatty()
        if (
            have_tty
            and not no_ansi()
            and os.environ.get("INSPECT_TEXTUAL_UI", None) is not None
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
